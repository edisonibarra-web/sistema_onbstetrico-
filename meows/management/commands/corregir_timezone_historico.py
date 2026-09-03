"""
Corrige el desfase de 5 horas en Medicion.fecha_hora causado por el bug de
TIME_ZONE (settings.py tenía 'UTC' en vez de 'America/Bogota'; ver commit que
cambia TIME_ZONE).

Todo datetime naive (el HCRHORREG que llega de Dinámica, o la hora que digita
el personal en el formulario manual) se interpretaba como si YA fuera UTC en
vez de hora de Bogotá, guardando internamente una hora 5 horas "menor" en UTC
de lo que debía ser. La corrección es sumar 5 horas a fecha_hora.

Alcance verificado antes de escribir este comando (sesión del 2026-09-03):
ningún registro de Medicion existente fue creado ya con el fix de TIME_ZONE
aplicado (la tarea programada de Windows nunca ha corrido con éxito desde que
se creó, y no hay entradas manuales posteriores al fix), así que se corrigen
TODOS los registros existentes por igual. Este comando no debe volver a
correrse una vez aplicado — quedaría un desfase inverso.

Uso:
    python manage.py corregir_timezone_historico            # aplica el cambio
    python manage.py corregir_timezone_historico --dry-run   # solo muestra
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F

from meows.models import Medicion


class Command(BaseCommand):
    help = (
        "Corrige el desfase de 5 horas en Medicion.fecha_hora causado por el "
        "bug de TIME_ZONE (naive datetimes interpretados como UTC en vez de "
        "America/Bogota)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra cuántos registros se afectarían, sin escribir nada.",
        )

    def handle(self, *args, **options):
        total = Medicion.objects.count()
        muestra_antes = list(
            Medicion.objects.order_by("id").values_list("id", "fecha_hora")[:3]
        )
        self.stdout.write(f"Registros de Medicion: {total}")
        self.stdout.write(f"Muestra ANTES: {muestra_antes}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(
                "--dry-run: no se modificó nada."
            ))
            return

        with transaction.atomic():
            n = Medicion.objects.update(
                fecha_hora=F("fecha_hora") + timedelta(hours=5)
            )

        muestra_despues = list(
            Medicion.objects.order_by("id").values_list("id", "fecha_hora")[:3]
        )
        self.stdout.write(self.style.SUCCESS(f"Filas actualizadas: {n}"))
        self.stdout.write(f"Muestra DESPUES: {muestra_despues}")
