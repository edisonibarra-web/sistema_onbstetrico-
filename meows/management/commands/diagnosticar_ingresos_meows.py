"""
2026-10-05: muestra, para una paciente, sus ingresos de Dinámica y a qué
ingreso quedó asignada cada toma MEOWS (Dinámica y triaje) -- lo mismo que
usa el selector de ingresos del formato MEOWS. Solo lee, no cambia nada.

    python manage.py diagnosticar_ingresos_meows 1004489674
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from meows.models import Medicion
from obstetriciaunificador.ingresos import (
    MARGEN_TRIAJE_ANTES, asignar_mediciones_meows, ingresos_de_paciente,
)


def _f(dt):
    return timezone.localtime(dt).strftime('%Y-%m-%d %H:%M') if dt else '-'


class Command(BaseCommand):
    help = 'Diagnóstico: ingresos de una paciente y a cuál quedó asignada cada toma MEOWS.'

    def add_arguments(self, parser):
        parser.add_argument('documento')

    def handle(self, *args, **options):
        doc = options['documento'].strip()
        ingresos, dinamica_ok, actual = ingresos_de_paciente(doc, fresco=True)
        self.stdout.write(f'Dinámica responde: {dinamica_ok} | ingreso actual: {actual or "(ninguno)"}')
        self.stdout.write('INGRESOS (más reciente primero; solo los "clínicos" reciben tomas):')
        for i in ingresos[:10]:
            self.stdout.write(
                f'  {i["numero"]:>9}  ingreso {_f(i["fecha_ingreso"])}  egreso {_f(i["fecha_egreso"])}  '
                f'{i["tipo"]:<15} {"CLÍNICO" if i["clinico"] else "-":<8} {"EN CURSO" if i["en_curso"] else ""}'
            )

        grupos = asignar_mediciones_meows(doc, ingresos)
        asignado = {mid: clave for clave, ids in grupos.items() for mid in ids}
        tomas = Medicion.objects.filter(paciente__numero_documento=doc).order_by('fecha_hora')
        self.stdout.write(f'TOMAS MEOWS ({tomas.count()}):')
        for m in tomas:
            self.stdout.write(
                f'  #{m.id}  {_f(m.fecha_hora)}  {m.origen:<9} folio={m.dinamica_folio or "-":<10} '
                f'-> ingreso {asignado.get(m.id, "?")}'
            )
        self.stdout.write(
            f'Regla: una toma de triaje va al ingreso clínico que empieza hasta '
            f'{int(MARGEN_TRIAJE_ANTES.total_seconds() // 3600)} h después de tomada, o al que esté en curso en ese momento.'
        )
