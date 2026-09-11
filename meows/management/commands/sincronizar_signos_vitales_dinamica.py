"""
Job de sincronización: revisa en Dinámica si hay signos vitales nuevos para
las pacientes activas y, si los hay, crea automáticamente el registro MEOWS
correspondiente (mismo cálculo que si se hubiera diligenciado a mano) y
dispara la alerta si el riesgo lo amerita.

Pensado para correr periódicamente (cron / Task Scheduler de Windows / Celery
beat — lo que ya tengan disponible), NO bajo demanda de un usuario. Es la
pieza que falta para que la alerta salga sin que nadie tenga que abrir la
pantalla de esa paciente.

Ejecutar manualmente para probar:
    python manage.py sincronizar_signos_vitales_dinamica
    python manage.py sincronizar_signos_vitales_dinamica --verbosity 2

Requiere que meows/services/dinamica_signos_vitales.py ya tenga configurado
el mapeo de columnas (ver ese archivo) — mientras no lo esté, el comando
avisa claramente y no hace nada.
"""
from django.core.management.base import BaseCommand
from django.db.models import Max
from django.utils import timezone

from frecuenciafetal.sala_partos_db import listar_pacientes_sala_partos
from meows.models import Formulario, Medicion, MedicionValor, Parametro, Paciente
from meows.services.dinamica_signos_vitales import (
    MapeoNoConfigurado,
    obtener_signos_vitales_nuevos,
)
from meows.services.meows import calcular_meows


def disparar_alerta(medicion, resultado):
    """
    Marca la medición como alerta y guarda cuándo se disparó: cualquier
    pantalla con el sidebar cargado (ver obstetricia/sidebar.html) la recoge
    en su próximo sondeo a /meows/api/alertas-pendientes/ y reproduce el
    sonido — TODAS las pantallas abiertas dentro de la ventana de tiempo, no
    solo la primera que pregunte. Ver meows/views.py:api_alertas_pendientes.

    Se llama solo para mediciones de riesgo AMARILLO o ROJO (ver el filtro en
    el llamador, más abajo) — decisión explícita de enfermería (2026-09-09):
    Blanco/Verde ya no deben interrumpir con notificación ni sonido, solo se
    consultan en la Línea de Tiempo del paciente. (Reemplaza la decisión
    anterior del 2026-09-03, que notificaba todo nivel de riesgo.)
    """
    medicion.alerta_pendiente = True
    medicion.alerta_generada_en = timezone.now()
    medicion.save(update_fields=["alerta_pendiente", "alerta_generada_en"])
    print(
        f"[ALERTA MEOWS] Paciente {medicion.paciente} — "
        f"riesgo {resultado['meows_riesgo']} (total {resultado['meows_total']}) — "
        f"medición #{medicion.id} importada de Dinámica (folio {medicion.dinamica_folio})"
    )


class Command(BaseCommand):
    help = (
        'Sincroniza signos vitales nuevos desde Dinámica para las pacientes '
        'activas y genera automáticamente los registros y alertas MEOWS.'
    )

    def handle(self, *args, **options):
        verbosity = options.get('verbosity', 1)

        formulario, _ = Formulario.objects.get_or_create(
            codigo="MEOWS",
            defaults={
                'nombre': 'Sistema de Alerta Temprana Obstétrico',
                'version': '1.0',
                'activo': True,
            },
        )
        parametros_por_codigo = {p.codigo: p for p in Parametro.objects.filter(activo=True)}

        try:
            pacientes = listar_pacientes_sala_partos(limit=500)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'No se pudo consultar Dinámica: {e}'))
            return

        total_nuevas = 0
        total_alertas = 0

        for p in pacientes:
            folio = p.get('folio')
            documento = (p.get('identificacion') or '').strip()
            if not folio or not documento:
                continue

            paciente, creado = Paciente.objects.get_or_create(
                numero_documento=documento,
                defaults=self._datos_basicos_paciente(p),
            )
            # Aunque el paciente ya existiera localmente, se refrescan estos
            # campos en CADA ciclo con lo que traiga Nexus ahora mismo (cama,
            # aseguradora, fecha de ingreso, etc. cambian durante la
            # hospitalización). Antes solo se llenaban una vez, al crear el
            # registro (get_or_create con defaults=), así que una paciente
            # como esta podía quedarse para siempre con "Fecha nacimiento",
            # "Tipo de sangre", "Fecha de ingreso" y "Edad gestacional" vacíos
            # en "Datos registrados del paciente" aunque Nexus sí los tuviera
            # — no es que la enfermería no los haya diligenciado en Dinámica,
            # es que nuestro caché local nunca los traía después del primer
            # registro. "responsable" NO se toca aquí: no viene de Nexus, lo
            # diligencia el personal directamente en esta app.
            self._actualizar_datos_basicos_paciente(paciente, p)

            ultima_fecha = Medicion.objects.filter(
                paciente=paciente, origen='dinamica'
            ).aggregate(m=Max('fecha_hora'))['m']
            if ultima_fecha is not None:
                # HCRHORREG en Dinámica es un datetime NAIVE en hora local (Bogotá).
                # `ultima_fecha` sale del ORM como aware en UTC (USE_TZ=True) -- si
                # se compara tal cual contra la columna naive (ej. "> 2026-09-11
                # 12:00" contra valores como "2026-09-11 07:30"), toda lectura
                # nueva del mismo día queda por debajo del corte y se pierde en
                # silencio durante ~5 horas (el offset Bogotá/UTC) después de cada
                # sincronización. Se convierte a naive-local antes de usarla como
                # filtro -- mismo fix aplicado en trabajoparto/management/commands/
                # sincronizar_frecuencia_fetal_dinamica.py (bug idéntico, mismo
                # patrón de comparación de horas).
                ultima_fecha = timezone.localtime(ultima_fecha).replace(tzinfo=None)

            try:
                lecturas = obtener_signos_vitales_nuevos(folio, desde=ultima_fecha)
            except MapeoNoConfigurado as e:
                self.stderr.write(self.style.ERROR(str(e)))
                return  # no tiene sentido seguir iterando pacientes, el mapeo falta para todas
            except Exception as e:
                self.stderr.write(self.style.WARNING(
                    f'Error consultando signos vitales del folio {folio} ({documento}): {e}'
                ))
                continue

            for lectura in lecturas:
                fecha_hora = lectura.pop('fecha_hora')

                # Salvaguarda extra ante lecturas repetidas por reintentos del job.
                if Medicion.objects.filter(
                    paciente=paciente, origen='dinamica', fecha_hora=fecha_hora
                ).exists():
                    continue

                valores_dict = {k: v for k, v in lectura.items() if v is not None}
                if not valores_dict:
                    continue

                # Calcular ANTES de crear los MedicionValor, para poder guardar
                # el puntaje individual de cada uno junto con su valor (si no,
                # queda NULL y la vista de resultado no puede mostrar el
                # puntaje/estado por parámetro, solo el total de la medición).
                resultado = calcular_meows(valores_dict)
                puntajes_por_codigo = resultado["puntajes"]

                medicion = Medicion.objects.create(
                    paciente=paciente,
                    formulario=formulario,
                    fecha_hora=fecha_hora,
                    origen='dinamica',
                    dinamica_folio=folio,
                )
                for codigo, valor in valores_dict.items():
                    parametro = parametros_por_codigo.get(codigo)
                    if parametro is None:
                        continue
                    MedicionValor.objects.create(
                        medicion=medicion, parametro=parametro, valor=str(valor),
                        puntaje=puntajes_por_codigo.get(codigo),
                    )

                medicion.meows_total = resultado["meows_total"]
                medicion.meows_riesgo = resultado["meows_riesgo"]
                medicion.meows_mensaje = resultado["meows_mensaje"]
                medicion.save(update_fields=["meows_total", "meows_riesgo", "meows_mensaje"])

                total_nuevas += 1
                if verbosity >= 2:
                    self.stdout.write(f'  + Medición #{medicion.id} para {documento} ({fecha_hora})')

                # 2026-09-09: a pedido de enfermería, ya NO se notifica Blanco/Verde
                # (antes se notificaba todo, ver docstring de disparar_alerta() —
                # decisión anterior del 2026-09-03, ahora reemplazada). Solo
                # Amarillo/Rojo entran a la campana/panel de alertas; Blanco/Verde
                # se guardan igual y se ven en la Línea de Tiempo del paciente, pero
                # sin sonido ni notificación emergente.
                if resultado["meows_riesgo"] in ("AMARILLO", "ROJO"):
                    disparar_alerta(medicion, resultado)
                    total_alertas += 1

        self.stdout.write(self.style.SUCCESS(
            f'[OK] {total_nuevas} medición(es) nueva(s) importada(s) desde Dinámica '
            f'({total_alertas} con alerta).'
        ))

    @staticmethod
    def _datos_basicos_paciente(p):
        nombre = (p.get('nombre_paciente') or '').strip()
        partes = nombre.split(maxsplit=1) if nombre else []
        return {
            'nombres': partes[0] if partes else 'N/A',
            'apellidos': partes[1] if len(partes) > 1 else 'N/A',
            'sexo': 'F',
            'aseguradora': p.get('aseguradora') or '',
            'cama': p.get('numero_cama') or '',
        }

    @staticmethod
    def _actualizar_datos_basicos_paciente(paciente, p):
        """
        Refresca en el Paciente local los campos que SÍ vienen de Nexus, cada
        vez que aparece en el listado de listar_pacientes_sala_partos() — no
        solo la primera vez. Ver comentario en el punto donde se llama.
        """
        def _a_fecha(valor):
            # listar_pacientes_sala_partos() devuelve datetime (con hora);
            # Paciente.fecha_nacimiento/fecha_ingreso son DateField.
            if valor is None:
                return None
            return valor.date() if hasattr(valor, 'date') else valor

        def _a_entero(valor):
            if valor is None:
                return None
            try:
                return int(valor)
            except (TypeError, ValueError):
                return None

        cambios = {
            'aseguradora': p.get('aseguradora') or '',
            'cama': p.get('numero_cama') or '',
            'num_historia_clinica': p.get('historia_clinica') or paciente.num_historia_clinica,
            'fecha_nacimiento': _a_fecha(p.get('fecha_nacimiento')) or paciente.fecha_nacimiento,
            'fecha_ingreso': _a_fecha(p.get('fecha_ingreso')) or paciente.fecha_ingreso,
            'diagnostico': p.get('diagnostico') or paciente.diagnostico,
            'tipo_sangre': p.get('grupo_sanguineo') or paciente.tipo_sangre,
            'nombre_acompanante': p.get('nombre_acompanante') or paciente.nombre_acompanante,
            'edad_gestacional': _a_entero(p.get('edad_gestacional')) or paciente.edad_gestacional,
            'gestas': _a_entero(p.get('gestas')) or paciente.gestas,
            'n_controles_prenatales': _a_entero(p.get('controles_prenatales')) or paciente.n_controles_prenatales,
        }

        hubo_cambio = False
        for campo, valor_nuevo in cambios.items():
            if getattr(paciente, campo) != valor_nuevo:
                setattr(paciente, campo, valor_nuevo)
                hubo_cambio = True
        if hubo_cambio:
            paciente.save(update_fields=list(cambios.keys()))
