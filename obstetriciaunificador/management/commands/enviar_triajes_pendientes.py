"""
Envía al repositorio clínico (NAS / carpeta local de pruebas) el formato de
triaje de las pacientes que ya recibieron ingreso en Dinámica. Normalmente no
hace falta correrlo a mano: lo hace sola la sincronización periódica
(sincronizar_signos_vitales_dinamica) y la apertura del tablero de la
paciente. Ver obstetriciaunificador/repositorio.py (enviar_triaje_si_corresponde).

    python manage.py enviar_triajes_pendientes [--dias 7]
"""
from django.core.management.base import BaseCommand

from obstetriciaunificador.repositorio import enviar_triajes_pendientes


class Command(BaseCommand):
    help = 'Envía al repositorio los triajes de pacientes que ya tienen ingreso.'

    def add_arguments(self, parser):
        parser.add_argument('--dias', type=int, default=7,
                            help='Revisar triajes de los últimos N días (por defecto 7).')

    def handle(self, *args, **opts):
        enviados = enviar_triajes_pendientes(dias=opts['dias'])
        if not enviados:
            self.stdout.write('Sin triajes pendientes de enviar.')
        for documento, envio in enviados:
            estilo = self.style.SUCCESS if envio.estado == envio.ESTADO_ENVIADO else self.style.ERROR
            self.stdout.write(estilo(
                f'{documento}/{envio.numero_ingreso}: {envio.estado} '
                f'{envio.nombre_archivo or envio.detalle_error}'
            ))
