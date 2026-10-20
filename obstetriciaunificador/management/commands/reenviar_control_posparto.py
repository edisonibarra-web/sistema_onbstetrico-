"""
Sube a la NAS el Control Posparto (FRSPA-007) ya CERRADO de una paciente que
no llegó a la NAS (p. ej. se cerró desde la consola con REPOSITORIO_MODO=local
y quedó solo en la carpeta local de pruebas, o el envío falló).

    python manage.py reenviar_control_posparto <cedula>            # solo muestra qué haría
    python manage.py reenviar_control_posparto <cedula> --aplicar  # sube el PDF

No reenvía un registro que ya tenga un envío exitoso a la NAS, ni registros
sin cerrar ("Guardar Registro Completo"). Solo funciona con REPOSITORIO_MODO=nas.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from frecuenciafetal.models import RegistroParto
from obstetriciaunificador.models import DocumentoRepositorio
from obstetriciaunificador.repositorio import _contenido_pdf, enviar_formato, ingreso_para_envio


class Command(BaseCommand):
    help = 'Sube a la NAS el Control Posparto cerrado de una paciente que no llegó a la NAS.'

    def add_arguments(self, parser):
        parser.add_argument('cedula')
        parser.add_argument('--aplicar', action='store_true', help='Subir de verdad (sin esto solo muestra qué haría).')

    def handle(self, *args, cedula, aplicar, **opts):
        if settings.REPOSITORIO_MODO != 'nas':
            raise CommandError(
                f"REPOSITORIO_MODO es '{settings.REPOSITORIO_MODO}': ponga REPOSITORIO_MODO=nas en el .env "
                "(y pruebe con: manage.py probar_repositorio)."
            )
        from frecuenciafetal.pdf_generator import generar_pdf_registro

        cedula = cedula.strip()
        registros = RegistroParto.objects.filter(identificacion=cedula).order_by('created_at')
        if not registros:
            raise CommandError(f'No hay Control Posparto para la cédula {cedula}.')

        for r in registros:
            self.stdout.write(f'\nRegistro {r.pk} - {r.nombre_paciente}')
            if r.completado_en is None:
                self.stdout.write(self.style.WARNING('  Sin cerrar ("Guardar Registro Completo"): no se envía.'))
                continue
            en_nas = DocumentoRepositorio.objects.filter(
                formato='control_posparto', referencia=str(r.pk)[:64],
                estado=DocumentoRepositorio.ESTADO_ENVIADO, modo='nas',
            ).order_by('-creado_en').first()
            if en_nas:
                self.stdout.write(self.style.SUCCESS(f'  Ya está en la NAS: {en_nas.ruta}'))
                continue
            atencion, ingreso = ingreso_para_envio(cedula, r.atencion)
            if not ingreso:
                self.stdout.write(self.style.ERROR('  Sin número de ingreso: no se puede ubicar la carpeta en la NAS.'))
                continue
            if not aplicar:
                self.stdout.write(f'  PRUEBA: se subiría a /{settings.REPO_FTP_BASE_PATH}/{cedula}/{ingreso}/ '
                                  '(agregue --aplicar para subirlo).')
                continue
            pdf = _contenido_pdf(generar_pdf_registro(r))
            envio = enviar_formato(pdf, cedula=cedula, numero_ingreso=ingreso, formato='control_posparto',
                                   atencion=atencion, referencia=r.pk, usuario='reenvío manual (consola)')
            if envio.estado == DocumentoRepositorio.ESTADO_ENVIADO:
                self.stdout.write(self.style.SUCCESS(f'  Subido a la NAS: {envio.ruta}'))
            else:
                self.stdout.write(self.style.ERROR(f'  Error al subir: {envio.detalle_error}'))
