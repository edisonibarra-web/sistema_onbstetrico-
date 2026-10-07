"""
2026-10-06: SOLO LECTURA. Lista las carpetas del repositorio clínico (NAS /
carpeta local de pruebas) donde una paciente tiene MÁS DE UN PDF de triaje en
el mismo ingreso (el triaje se envía una sola vez por ingreso: más de uno es
un duplicado). No borra, no sube y no modifica la bitácora.

Revisa solo las carpetas <cédula>/<ingreso> que esta app tocó según la
bitácora (DocumentoRepositorio): recorrer toda la NAS por FTP sería muy lento
(la raíz tiene una carpeta por cada paciente del hospital).

    python manage.py revisar_triajes_duplicados                 # últimos 60 días
    python manage.py revisar_triajes_duplicados --dias 365
    python manage.py revisar_triajes_duplicados --comparar      # además, compara el contenido
    python manage.py revisar_triajes_duplicados --formato meows
"""
from collections import Counter
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from obstetriciaunificador.models import DocumentoRepositorio
from obstetriciaunificador.repositorio import (
    FORMATOS, _archivos_del_formato, _limpiar, huella_contenido,
    leer_documento_ingreso, listar_documentos_ingreso,
)


class Command(BaseCommand):
    help = 'Solo lectura: lista PDF de triaje duplicados en el repositorio clínico (NAS).'

    def add_arguments(self, parser):
        parser.add_argument('--dias', type=int, default=60,
                            help='Revisar envíos de la bitácora de los últimos N días (por defecto 60).')
        parser.add_argument('--formato', default='triaje', choices=sorted(FORMATOS),
                            help='Formato a revisar (por defecto triaje).')
        parser.add_argument('--comparar', action='store_true',
                            help='Descarga cada PDF repetido y compara su contenido (más lento).')

    def handle(self, *args, **opts):
        formato = opts['formato']
        desde = timezone.now() - timedelta(days=opts['dias'])
        self.stdout.write(
            f"Modo del repositorio: {settings.REPOSITORIO_MODO} | formato: {formato} | "
            f"bitácora desde {timezone.localtime(desde):%d/%m/%Y}"
        )
        if formato != 'triaje':
            self.stdout.write(self.style.WARNING(
                'Ojo: en este formato varios PDF pueden ser normales (p. ej. "Reenviar a repositorio").'
            ))

        grupos = (
            DocumentoRepositorio.objects.filter(formato=formato, creado_en__gte=desde)
            .order_by().values_list('cedula', 'numero_ingreso').distinct()
        )
        grupos = sorted({(_limpiar(c), _limpiar(i)) for c, i in grupos if c and i})
        self.stdout.write(f'Carpetas a revisar: {len(grupos)}\n')

        con_duplicados, sobrantes, errores = 0, 0, 0
        for cedula, ingreso in grupos:
            try:
                archivos = listar_documentos_ingreso(cedula, ingreso)
            except Exception as exc:
                errores += 1
                self.stdout.write(self.style.ERROR(f'{cedula}/{ingreso}: no se pudo listar ({exc})'))
                continue
            del_formato = _archivos_del_formato(archivos, formato, cedula)  # {consecutivo: nombre}
            if len(del_formato) <= 1:
                continue

            con_duplicados += 1
            sobrantes += len(del_formato) - 1
            bitacora = Counter(
                DocumentoRepositorio.objects.filter(cedula=cedula, numero_ingreso=ingreso, formato=formato)
                .values_list('estado', flat=True)
            )
            resumen_bitacora = ', '.join(f'{estado}: {n}' for estado, n in sorted(bitacora.items())) or 'sin filas'
            self.stdout.write(self.style.WARNING(
                f'{cedula}/{ingreso}: {len(del_formato)} PDF de {formato} (bitácora -> {resumen_bitacora})'
            ))

            huellas = {}
            if opts['comparar']:
                for n, nombre in sorted(del_formato.items()):
                    try:
                        huellas[n] = huella_contenido(leer_documento_ingreso(cedula, ingreso, nombre))[:12] or '?'
                    except Exception as exc:
                        huellas[n] = f'error: {exc}'
            primera = huellas.get(min(del_formato)) if huellas else None
            for n, nombre in sorted(del_formato.items()):
                linea = f'    {nombre}'
                if huellas:
                    igual = huellas[n] == primera and not str(primera).startswith(('error', '?'))
                    linea += f'   [{huellas[n]}]' + ('  = igual al primero' if n != min(del_formato) and igual else '')
                self.stdout.write(linea)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Listo. Carpetas con duplicados: {con_duplicados} | PDF sobrantes: {sobrantes} | '
            f'carpetas que no se pudieron leer: {errores}. No se modificó nada.'
        ))
