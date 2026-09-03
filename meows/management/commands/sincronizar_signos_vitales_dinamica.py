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

    Se llama para TODA medición nueva importada de Dinámica, sin importar el
    nivel de riesgo (Blanco a Rojo) — decisión explícita del usuario
    (2026-09-03): prefiere notificación de cada lectura nueva antes que
    filtrar solo las de riesgo, aun a costa de más notificaciones. El color
    del toast (ver sidebar.html, clases riesgo-blanco/verde/amarillo/rojo)
    y si suena fuerte o no siguen diferenciando visualmente el nivel real.
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

            ultima_fecha = Medicion.objects.filter(
                paciente=paciente, origen='dinamica'
            ).aggregate(m=Max('fecha_hora'))['m']

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
                        medicion=medicion, parametro=parametro, valor=str(valor)
                    )

                resultado = calcular_meows(valores_dict)
                medicion.meows_total = resultado["meows_total"]
                medicion.meows_riesgo = resultado["meows_riesgo"]
                medicion.meows_mensaje = resultado["meows_mensaje"]
                medicion.save(update_fields=["meows_total", "meows_riesgo", "meows_mensaje"])

                total_nuevas += 1
                if verbosity >= 2:
                    self.stdout.write(f'  + Medición #{medicion.id} para {documento} ({fecha_hora})')

                # Notifica SIEMPRE, sin importar el riesgo (Blanco a Rojo) — ver
                # docstring de disparar_alerta().
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
