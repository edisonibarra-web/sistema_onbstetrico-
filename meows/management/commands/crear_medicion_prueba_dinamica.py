"""
Crea UNA medición de prueba origen='dinamica' con fecha_hora = ahora mismo,
para verificar en vivo el prellenado de las cards (Opción B+C) sin depender
del retraso de replicación del Nexus de pruebas.

No inventa un folio nuevo ni toca datos reales de Dinámica: reutiliza los
mismos valores y el mismo dinamica_folio de la última lectura real que ya
existe para esa paciente, cambiando solo la fecha_hora a "ahora".

Uso:
    python manage.py crear_medicion_prueba_dinamica --doc VEN32021521
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from meows.models import Formulario, Medicion, MedicionValor, Parametro, Paciente
from meows.services.meows import calcular_meows


class Command(BaseCommand):
    help = "Crea una medición de prueba origen='dinamica' con fecha_hora=ahora para probar el prellenado."

    def add_arguments(self, parser):
        parser.add_argument("--doc", required=True, help="Número de documento de la paciente.")

    def handle(self, *args, **options):
        documento = options["doc"].strip()
        paciente = Paciente.objects.filter(numero_documento=documento).first()
        if not paciente:
            raise CommandError(f"No existe paciente con documento {documento}")

        ultima = (
            Medicion.objects.filter(paciente=paciente, origen="dinamica")
            .order_by("-fecha_hora")
            .first()
        )
        if not ultima:
            raise CommandError(f"{paciente} no tiene ninguna medición origen=dinamica previa para copiar valores.")

        valores_dict = {
            v.parametro.codigo: v.valor
            for v in ultima.valores.select_related("parametro")
        }

        formulario, _ = Formulario.objects.get_or_create(
            codigo="MEOWS",
            defaults={"nombre": "Sistema de Alerta Temprana Obstétrico", "version": "1.0", "activo": True},
        )
        parametros_por_codigo = {p.codigo: p for p in Parametro.objects.filter(activo=True)}

        resultado = calcular_meows({k: v for k, v in valores_dict.items()})
        puntajes_por_codigo = resultado["puntajes"]

        medicion = Medicion.objects.create(
            paciente=paciente,
            formulario=formulario,
            fecha_hora=timezone.now(),
            origen="dinamica",
            dinamica_folio=ultima.dinamica_folio,
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

        self.stdout.write(self.style.SUCCESS(
            f"Medición de prueba #{medicion.id} creada para {paciente} — "
            f"fecha_hora={medicion.fecha_hora}, valores copiados de la medición #{ultima.id}."
        ))
