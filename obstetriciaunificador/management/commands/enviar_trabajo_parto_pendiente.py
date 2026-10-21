"""
Genera y sube a la NAS el PDF de Trabajo de Parto (partograma) de una paciente
cuyas hojas tienen controles pero nunca se envió (nadie pulsó "Finalizar"). Es
lo que la Consulta histórica avisa como "Falta: Trabajo de parto". Pasadas 24 h
del egreso la pantalla queda en solo consulta, por eso se hace desde la consola.

    python manage.py enviar_trabajo_parto_pendiente <cedula>            # solo muestra qué haría
    python manage.py enviar_trabajo_parto_pendiente <cedula> --aplicar  # genera y sube el PDF

No toca las hojas (solo las lee para generar el PDF), no reenvía una hoja que
ya está en la NAS y no envía hojas sin controles. Solo con REPOSITORIO_MODO=nas.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from obstetriciaunificador.models import DocumentoRepositorio
from obstetriciaunificador.repositorio import RepositorioError, enviar_trabajo_parto, resumen_envio


class Command(BaseCommand):
    help = 'Sube a la NAS el PDF de Trabajo de Parto de las hojas con controles que nunca se enviaron.'

    def add_arguments(self, parser):
        parser.add_argument('cedula')
        parser.add_argument('--aplicar', action='store_true', help='Generar y subir de verdad (sin esto, solo muestra qué haría).')

    def handle(self, *args, cedula, aplicar, **opts):
        from trabajoparto.models import Formulario

        if settings.REPOSITORIO_MODO != 'nas':
            raise CommandError(
                f"REPOSITORIO_MODO es '{settings.REPOSITORIO_MODO}': ponga REPOSITORIO_MODO=nas en el .env "
                "(y pruebe con: manage.py probar_repositorio)."
            )
        cedula = cedula.strip()
        hojas = (Formulario.objects.filter(paciente__num_identificacion=cedula)
                 .select_related('paciente', 'aseguradora', 'atencion').order_by('created_at'))
        if not hojas:
            raise CommandError(f'No hay hojas de Trabajo de Parto para la cédula {cedula}.')

        for hoja in hojas:
            controles = hoja.mediciones.count()
            self.stdout.write(f'\nHoja {hoja.pk} (creada {hoja.created_at:%d/%m/%Y}) - {controles} controles')
            if not controles:
                self.stdout.write('  Sin controles: no se envía.')
                continue
            en_nas = DocumentoRepositorio.objects.filter(
                formato='trabajo_parto', referencia=str(hoja.pk), estado=DocumentoRepositorio.ESTADO_ENVIADO, modo='nas',
            ).order_by('-creado_en').first()
            if en_nas:
                self.stdout.write(self.style.SUCCESS(f'  Ya está en la NAS: {en_nas.ruta}'))
                continue
            # Solo el ingreso guardado en la hoja: sin él, enviar_trabajo_parto
            # tomaría el ingreso ACTUAL de la paciente (puede ser otro).
            ingreso = (getattr(hoja.atencion, 'numero_ingreso', '') or '').strip()
            if not ingreso:
                self.stdout.write(self.style.ERROR(
                    '  La hoja no tiene ingreso asociado: no se envía (habría que ubicar el ingreso a mano).'))
                continue
            if not aplicar:
                self.stdout.write(f'  PRUEBA: se subiría a /{settings.REPO_FTP_BASE_PATH}/{cedula}/{ingreso}/ '
                                  '(agregue --aplicar para subirlo).')
                continue
            try:
                envio = enviar_trabajo_parto(hoja, usuario='envío manual (consola)')
            except RepositorioError as exc:
                self.stdout.write(self.style.WARNING(f'  No se envió: {exc}'))
                continue
            resumen = resumen_envio(envio)
            estilo = self.style.SUCCESS if resumen['ok'] else self.style.ERROR
            self.stdout.write(estilo(f'  {resumen["mensaje"]}'))
