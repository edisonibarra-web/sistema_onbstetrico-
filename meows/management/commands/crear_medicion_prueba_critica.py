"""
Crea UNA medición de prueba origen='dinamica' con fecha_hora = ahora mismo,
en el nivel de riesgo que se indique, para verificar en vivo el toast + el
sonido sin depender de datos reales de Dinámica.

Replica lo que hace sincronizar_signos_vitales_dinamica.py: crea la Medicion,
sus MedicionValor, calcula MEOWS y marca alerta_pendiente + alerta_generada_en
=ahora — SIEMPRE, sin importar el riesgo (decisión del usuario, 2026-09-03:
notificar toda medición nueva, no solo las de riesgo alto).

Uso:
    python manage.py crear_medicion_prueba_critica --doc VEN32021521 --nivel rojo
    python manage.py crear_medicion_prueba_critica --doc VEN32021521 --nivel blanco
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from meows.models import Formulario, Medicion, MedicionValor, Parametro, Paciente
from meows.services.meows import calcular_meows


# Recalibrado 2026-09-08: los presets de "verde" y "amarillo" quedaron viejos
# respecto a los rangos reales vigentes (RangoParametro) y en realidad sumaban
# >=6 -> siempre daban ROJO, sin importar el --nivel pedido. Verificado cada
# preset contra los rangos reales de la BD antes de dejarlo aquí:
#   blanco:   total 0            (todos en score 0)
#   verde:    total 1-3, ningún parámetro individual en score 3
#   amarillo: total 4-5, ningún parámetro individual en score 3
#   rojo:     total >=6 (aquí además con varios parámetros en score 3)
VALORES_POR_NIVEL = {
    "rojo": {"ta_sys": 200, "ta_dia": 115, "fc": 175, "fr": 35, "temp": 40.2, "spo2": 82, "fcf": 95},
    "amarillo": {"ta_sys": 152, "ta_dia": 95, "fc": 120, "fr": 15, "temp": 37.0, "spo2": 98, "fcf": 140},
    "verde": {"ta_sys": 140, "ta_dia": 70, "fc": 90, "fr": 20, "temp": 37.0, "spo2": 98, "fcf": 140},
    "blanco": {"ta_sys": 110, "ta_dia": 70, "fc": 80, "fr": 16, "temp": 36.5, "spo2": 98, "fcf": 140},
}


class Command(BaseCommand):
    help = "Crea una medición de prueba en el nivel de riesgo indicado, para probar el toast/sonido."

    def add_arguments(self, parser):
        parser.add_argument("--doc", required=True, help="Número de documento de la paciente.")
        parser.add_argument(
            "--nivel", default="rojo", choices=sorted(VALORES_POR_NIVEL.keys()),
            help="Nivel de riesgo objetivo de los valores de prueba (default: rojo).",
        )

    def handle(self, *args, **options):
        documento = options["doc"].strip()
        valores = VALORES_POR_NIVEL[options["nivel"]]
        paciente = Paciente.objects.filter(numero_documento=documento).first()
        if not paciente:
            raise CommandError(f"No existe paciente con documento {documento}")

        ultima = (
            Medicion.objects.filter(paciente=paciente, origen="dinamica")
            .order_by("-fecha_hora")
            .first()
        )
        folio = ultima.dinamica_folio if ultima else None

        formulario, _ = Formulario.objects.get_or_create(
            codigo="MEOWS",
            defaults={"nombre": "Sistema de Alerta Temprana Obstétrico", "version": "1.0", "activo": True},
        )
        parametros_por_codigo = {p.codigo: p for p in Parametro.objects.filter(activo=True)}

        resultado = calcular_meows(valores)
        puntajes_por_codigo = resultado["puntajes"]

        medicion = Medicion.objects.create(
            paciente=paciente,
            formulario=formulario,
            fecha_hora=timezone.now(),
            origen="dinamica",
            dinamica_folio=folio,
        )
        for codigo, valor in valores.items():
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

        # Notifica SIEMPRE, igual que ya quedó el job real.
        medicion.alerta_pendiente = True
        medicion.alerta_generada_en = timezone.now()
        medicion.save(update_fields=["alerta_pendiente", "alerta_generada_en"])

        self.stdout.write(self.style.SUCCESS(
            f"Medición de prueba #{medicion.id} creada para {paciente} — "
            f"riesgo={medicion.meows_riesgo} total={medicion.meows_total} "
            f"alerta_pendiente={medicion.alerta_pendiente}"
        ))
