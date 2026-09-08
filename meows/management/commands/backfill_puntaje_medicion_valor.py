"""
Rellena MedicionValor.puntaje para los registros ya existentes.

Bug encontrado 2026-09-07: ninguno de los puntos donde se crea un
MedicionValor (formulario manual, sync de Dinámica, comandos de prueba)
guardaba el puntaje individual de ese parámetro — solo Medicion.meows_total
(el agregado) quedaba bien. Esto hacía que la tabla "Detalle de Parámetros"
en meows/resultado.html mostrara "-" en Puntaje y Estado para TODO registro,
manual o automático, sin importar cuándo se creó.

Ese problema de origen ya se corrigió (ver meows/views.py y
sincronizar_signos_vitales_dinamica.py) — este comando es solo para poner al
día los registros que ya existían antes del fix.

Uso:
    python manage.py backfill_puntaje_medicion_valor --dry-run
    python manage.py backfill_puntaje_medicion_valor
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from meows.models import Medicion
from meows.services.meows import calcular_meows


class Command(BaseCommand):
    help = "Calcula y guarda MedicionValor.puntaje para mediciones ya guardadas que quedaron en NULL."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Solo muestra cuántas filas se afectarían.")

    def handle(self, *args, **options):
        mediciones = (
            Medicion.objects.filter(valores__puntaje__isnull=True)
            .distinct()
            .prefetch_related("valores__parametro")
        )
        total_mediciones = mediciones.count()
        total_valores = 0
        self.stdout.write(f"Mediciones con al menos un MedicionValor sin puntaje: {total_mediciones}")

        if options["dry_run"]:
            n = 0
            for medicion in mediciones:
                n += medicion.valores.filter(puntaje__isnull=True).count()
            self.stdout.write(self.style.WARNING(f"--dry-run: {n} filas de MedicionValor se actualizarían. No se modificó nada."))
            return

        with transaction.atomic():
            for medicion in mediciones:
                valores_qs = list(medicion.valores.select_related("parametro"))
                valores_dict = {v.parametro.codigo: v.valor for v in valores_qs}
                resultado = calcular_meows(valores_dict)
                puntajes_por_codigo = resultado["puntajes"]

                for v in valores_qs:
                    if v.puntaje is not None:
                        continue
                    nuevo_puntaje = puntajes_por_codigo.get(v.parametro.codigo)
                    if nuevo_puntaje is None:
                        continue
                    v.puntaje = nuevo_puntaje
                    v.save(update_fields=["puntaje"])
                    total_valores += 1

        self.stdout.write(self.style.SUCCESS(
            f"Listo: {total_valores} filas de MedicionValor actualizadas en {total_mediciones} mediciones."
        ))
