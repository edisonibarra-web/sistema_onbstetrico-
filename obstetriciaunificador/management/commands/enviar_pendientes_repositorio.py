"""
Envía al repositorio clínico (NAS / carpeta local de pruebas) los formatos
automáticos pendientes:
  - Triaje de pacientes que ya recibieron ingreso.
  - MEOWS de pacientes que ya egresaron (una vez por ingreso).
Normalmente no hace falta correrlo a mano: lo hace la sincronización
periódica con Dinámica (sincronizar_signos_vitales_dinamica).

    python manage.py enviar_pendientes_repositorio [--dias 30]
"""
from django.core.management.base import BaseCommand

from obstetriciaunificador.repositorio import (
    DIAS_REVISION_EGRESO, enviar_meows_egresos_pendientes, enviar_triajes_pendientes,
)


class Command(BaseCommand):
    help = 'Envía al repositorio los triajes con ingreso y los MEOWS de pacientes egresadas.'

    def add_arguments(self, parser):
        parser.add_argument('--dias', type=int, default=None,
                            help=f'Revisar los últimos N días (por defecto: triajes 7, MEOWS de egreso {DIAS_REVISION_EGRESO}).')

    def handle(self, *args, **opts):
        enviados = (
            [('TRIAJE', d, e) for d, e in enviar_triajes_pendientes(dias=opts['dias'] or 7)]
            + [('MEOWS EGRESO', d, e) for d, e in enviar_meows_egresos_pendientes(dias=opts['dias'] or DIAS_REVISION_EGRESO)]
        )
        if not enviados:
            self.stdout.write('Sin formatos pendientes de enviar.')
        for tipo, documento, envio in enviados:
            estilo = self.style.SUCCESS if envio.estado == envio.ESTADO_ENVIADO else self.style.ERROR
            self.stdout.write(estilo(
                f'[{tipo}] {documento}/{envio.numero_ingreso}: {envio.estado} '
                f'{envio.nombre_archivo or envio.detalle_error}'
            ))
