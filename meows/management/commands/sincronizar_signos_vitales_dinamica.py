"""
Job de sincronización: revisa en Dinámica si hay signos vitales nuevos para
las pacientes activas y, si los hay, crea automáticamente el registro MEOWS
correspondiente (mismo cálculo que si se hubiera diligenciado a mano) y
dispara la alerta si el riesgo lo amerita.

Pensado para correr periódicamente (cron / Task Scheduler de Windows / Celery
beat — lo que ya tengan disponible), NO bajo demanda de un usuario. Es la
pieza que falta para que la alerta salga sin que nadie tenga que abrir la
pantalla de esa paciente.

2026-09-21: además de traer tomas genuinamente nuevas, también RE-CHEQUEA una
ventana reciente (VENTANA_RECHEQUEO_HORAS) de tomas ya importadas, por si
alguien editó su valor en Dinámica después de sincronizada -- antes eso
quedaba invisible para siempre (el filtro "HCRHORREG > última importada" solo
mira hacia adelante, y HCRHORREG no cambia al editar solo el valor). Se
identifica la misma fila de Dinámica entre corridas por su OID
(MedicionValor.dinamica_oid) — ver meows/services/dinamica_signos_vitales.py.
Si una edición cambia el riesgo a AMARILLO/ROJO, se dispara alerta igual que
con una toma nueva.

Ejecutar manualmente para probar:
    python manage.py sincronizar_signos_vitales_dinamica
    python manage.py sincronizar_signos_vitales_dinamica --verbosity 2

Requiere que meows/services/dinamica_signos_vitales.py ya tenga configurado
el mapeo de columnas (ver ese archivo) — mientras no lo esté, el comando
avisa claramente y no hace nada.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Max
from django.utils import timezone

from frecuenciafetal.sala_partos_db import listar_pacientes_sala_partos
from meows.models import Formulario, Medicion, MedicionValor, Parametro, Paciente
from meows.services.dinamica_signos_vitales import (
    MapeoNoConfigurado,
    obtener_signos_vitales_nuevos,
    _a_numero,
)
from meows.services.meows import calcular_meows

# Cuántas horas hacia atrás se re-chequean en cada ciclo por si alguien
# corrigió en Dinámica el valor de una toma ya sincronizada (ver docstring
# del módulo). Acotado a propósito: el job corre ~cada 1s, así que esta
# ventana no debe crecer con la duración de la hospitalización.
VENTANA_RECHEQUEO_HORAS = 6


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
        total_editadas = 0

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

                # Además de lo genuinamente nuevo, se re-consulta una ventana
                # reciente de lo YA importado, por si alguien lo editó en
                # Dinámica después de sincronizado (ver docstring del módulo).
                # Acotada a VENTANA_RECHEQUEO_HORAS para que el costo no
                # crezca con la duración de la hospitalización.
                ventana_rechequeo = (
                    timezone.localtime(timezone.now()).replace(tzinfo=None)
                    - timedelta(hours=VENTANA_RECHEQUEO_HORAS)
                )
                desde_consulta = min(ultima_fecha, ventana_rechequeo)
            else:
                # Primera sincronización de esta paciente: trae todo su
                # historial sin recorte, igual que siempre.
                desde_consulta = None

            try:
                lecturas = obtener_signos_vitales_nuevos(folio, desde=desde_consulta)
            except MapeoNoConfigurado as e:
                self.stderr.write(self.style.ERROR(str(e)))
                return  # no tiene sentido seguir iterando pacientes, el mapeo falta para todas
            except Exception as e:
                self.stderr.write(self.style.WARNING(
                    f'Error consultando signos vitales del folio {folio} ({documento}): {e}'
                ))
                continue

            mediciones_a_recalcular = set()

            for lectura in lecturas:
                fecha_hora = lectura.pop('fecha_hora')
                # Quien digitó ESTA toma en Dinámica (ver docstring de
                # obtener_signos_vitales_nuevos) -- se saca del dict ANTES de
                # armar valores_dict, igual que fecha_hora, para que no se
                # trate como si fuera un parámetro MEOWS más.
                responsable_dinamica = lectura.pop('responsable', None)
                oids_por_campo = lectura.pop('_oids', {}) or {}

                valores_dict = {k: v for k, v in lectura.items() if v is not None}
                if not valores_dict:
                    continue

                medicion_existente = Medicion.objects.filter(
                    paciente=paciente, origen='dinamica', fecha_hora=fecha_hora
                ).first()

                if medicion_existente is not None:
                    # Ya está importada -- revisar campo por campo si el
                    # valor cambió en Dinámica desde que se trajo (ver
                    # docstring del módulo). Se identifica la misma fila de
                    # Dinámica por su OID, no por el valor -- así se detecta
                    # la edición aunque el nuevo valor coincida por
                    # casualidad con el de otro campo.
                    hubo_cambio = False
                    for codigo, valor_nuevo in valores_dict.items():
                        parametro = parametros_por_codigo.get(codigo)
                        if parametro is None:
                            continue
                        oid_campo = oids_por_campo.get(codigo)
                        valor_texto_nuevo = str(valor_nuevo)
                        mv = MedicionValor.objects.filter(
                            medicion=medicion_existente, parametro=parametro
                        ).first()
                        if mv is None:
                            # Parámetro que esta toma no traía antes y ahora sí
                            # (ej. se completó en Dinámica después de la
                            # primera sincronización) -- se agrega.
                            MedicionValor.objects.create(
                                medicion=medicion_existente, parametro=parametro,
                                valor=valor_texto_nuevo, dinamica_oid=oid_campo,
                            )
                            hubo_cambio = True
                        elif mv.valor != valor_texto_nuevo:
                            if verbosity >= 2:
                                self.stdout.write(
                                    f'  ~ Corrección detectada: {documento} {codigo} '
                                    f'{mv.valor} -> {valor_texto_nuevo} (medición #{medicion_existente.id})'
                                )
                            mv.valor = valor_texto_nuevo
                            if oid_campo is not None:
                                mv.dinamica_oid = oid_campo
                            mv.save(update_fields=['valor', 'dinamica_oid'])
                            hubo_cambio = True
                        elif oid_campo is not None and mv.dinamica_oid != oid_campo:
                            # Mismo valor, pero todavía no teníamos guardado
                            # el OID de origen (dato importado antes de que
                            # existiera este campo) -- se completa sin
                            # contar como una corrección real.
                            mv.dinamica_oid = oid_campo
                            mv.save(update_fields=['dinamica_oid'])
                    if hubo_cambio:
                        mediciones_a_recalcular.add(medicion_existente.id)
                    continue

                # Toma genuinamente nueva -- mismo comportamiento de siempre,
                # ahora guardando también el OID de origen de cada valor.
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
                    responsable_dinamica=responsable_dinamica,
                )
                for codigo, valor in valores_dict.items():
                    parametro = parametros_por_codigo.get(codigo)
                    if parametro is None:
                        continue
                    MedicionValor.objects.create(
                        medicion=medicion, parametro=parametro, valor=str(valor),
                        puntaje=puntajes_por_codigo.get(codigo),
                        dinamica_oid=oids_por_campo.get(codigo),
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

            # Recalcular puntaje/riesgo total de cada medición que tuvo al
            # menos un valor corregido en Dinámica, y re-alertar si el nuevo
            # riesgo lo amerita (confirmado explícitamente: una corrección
            # que revela un riesgo real no debe quedar en silencio).
            for medicion_id in mediciones_a_recalcular:
                medicion = Medicion.objects.get(id=medicion_id)
                valores_medicion = list(medicion.valores.select_related('parametro'))
                valores_dict = {
                    mv.parametro.codigo: _a_numero(mv.valor)
                    for mv in valores_medicion
                }
                valores_dict = {k: v for k, v in valores_dict.items() if v is not None}
                if not valores_dict:
                    continue

                resultado = calcular_meows(valores_dict)
                puntajes_por_codigo = resultado["puntajes"]
                for mv in valores_medicion:
                    nuevo_puntaje = puntajes_por_codigo.get(mv.parametro.codigo)
                    if mv.puntaje != nuevo_puntaje:
                        mv.puntaje = nuevo_puntaje
                        mv.save(update_fields=['puntaje'])

                medicion.meows_total = resultado["meows_total"]
                medicion.meows_riesgo = resultado["meows_riesgo"]
                medicion.meows_mensaje = resultado["meows_mensaje"]
                # Señal separada de alerta_generada_en (esa solo se llena en
                # Amarillo/Rojo) -- permite refrescar sola la pantalla de
                # esa paciente aunque la corrección no dispare alerta. Ver
                # api_correcciones_recientes (views.py) y el sondeo nuevo en
                # sidebar.html.
                medicion.ultima_correccion_en = timezone.now()
                medicion.save(update_fields=[
                    "meows_total", "meows_riesgo", "meows_mensaje", "ultima_correccion_en",
                ])

                total_editadas += 1
                if verbosity >= 2:
                    self.stdout.write(
                        f'  ~ Medición #{medicion.id} recalculada tras corrección '
                        f'(riesgo: {resultado["meows_riesgo"]})'
                    )
                if resultado["meows_riesgo"] in ("AMARILLO", "ROJO"):
                    disparar_alerta(medicion, resultado)
                    total_alertas += 1

        self.stdout.write(self.style.SUCCESS(
            f'[OK] {total_nuevas} medición(es) nueva(s), {total_editadas} corregida(s) '
            f'importada(s) desde Dinámica ({total_alertas} con alerta).'
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
