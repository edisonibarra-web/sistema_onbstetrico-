"""
Borra un Paciente MEOWS de prueba y todo lo que dependa de él (mediciones,
valores) en cascada. Pensado para limpiar pacientes sintéticos creados con
crear_medicion_prueba_dinamica / crear_medicion_prueba_critica, NUNCA para un
paciente real.

Uso:
    python manage.py borrar_paciente_prueba --doc VEN32021521
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from meows.models import Paciente


class Command(BaseCommand):
    help = "Borra un Paciente MEOWS de prueba (y sus mediciones/valores) por número de documento."

    def add_arguments(self, parser):
        parser.add_argument("--doc", required=True, help="Número de documento del paciente a borrar.")

    def handle(self, *args, **options):
        documento = options["doc"].strip()
        paciente = Paciente.objects.filter(numero_documento=documento).first()
        if not paciente:
            raise CommandError(f"No existe ningún Paciente local con documento {documento}")

        nombre = str(paciente)
        with transaction.atomic():
            _, detalle = paciente.delete()

        self.stdout.write(self.style.SUCCESS(f"Borrado {nombre} — detalle: {detalle}"))
