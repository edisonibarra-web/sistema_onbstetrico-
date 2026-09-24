"""
Prueba de conexión con el repositorio clínico (NAS por FTP), sin tocar
carpetas de pacientes.

    python manage.py probar_repositorio              # conexión + login + lectura
    python manage.py probar_repositorio --escritura  # además crea, sube y borra
                                                     # un archivo de prueba en
                                                     # <base>/_prueba_conexion_sistema_obstetrico/

Siempre prueba la NAS (REPO_FTP_*), aunque REPOSITORIO_MODO sea "local".
"""
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from obstetriciaunificador.repositorio import _DestinoFTP

CARPETA_PRUEBA = '_prueba_conexion_sistema_obstetrico'


class Command(BaseCommand):
    help = 'Prueba la conexión FTP con el repositorio clínico (NAS).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--escritura', action='store_true',
            help='Crear, subir y borrar un archivo de prueba (fuera de las carpetas de pacientes).',
        )

    def handle(self, *args, **opts):
        self.stdout.write(f'REPOSITORIO_MODO actual: {settings.REPOSITORIO_MODO}')
        if settings.REPOSITORIO_MODO == 'local':
            self.stdout.write(f'  (los formatos se guardan hoy en {settings.REPOSITORIO_LOCAL_DIR})')
        self.stdout.write(
            f'NAS: ftp://{settings.REPO_FTP_HOST}:{settings.REPO_FTP_PORT}/'
            f'{settings.REPO_FTP_BASE_PATH} usuario={settings.REPO_FTP_USER} '
            f'TLS={settings.REPO_FTP_TLS}'
        )
        t0 = time.perf_counter()
        try:
            with _DestinoFTP() as nas:
                self.stdout.write(self.style.SUCCESS(
                    f'  Conexión y login OK ({nas.ftp.getwelcome().strip()})'
                ))
                carpetas, archivos = nas.listar([])
                self.stdout.write(self.style.SUCCESS(
                    f'  Lectura OK: {len(carpetas)} carpetas en /{settings.REPO_FTP_BASE_PATH}'
                ))
                if opts['escritura']:
                    self._probar_escritura(nas, carpetas)
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f'Falló la prueba con la NAS: {type(exc).__name__}: {exc}')
        self.stdout.write(f'Tiempo total: {time.perf_counter() - t0:.2f}s')

    def _probar_escritura(self, nas, carpetas):
        contenido = b'%PDF-1.4\n% prueba de conexion sistema obstetrico\n'
        nombre = f'prueba_{int(time.time())}.pdf'
        if CARPETA_PRUEBA not in carpetas:
            nas.crear_carpeta([CARPETA_PRUEBA])
        try:
            ruta = nas.guardar([CARPETA_PRUEBA], nombre, contenido)
            self.stdout.write(self.style.SUCCESS(f'  Escritura OK: {ruta} ({len(contenido)} B)'))
        finally:
            try:
                nas.ftp.delete(nas._ruta([CARPETA_PRUEBA], nombre))
            except Exception:
                pass
            try:
                nas.ftp.rmd(nas._ruta([CARPETA_PRUEBA]))
                self.stdout.write(self.style.SUCCESS('  Limpieza OK (archivo y carpeta de prueba borrados)'))
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f'  No se pudo borrar la carpeta de prueba: {exc}'))
