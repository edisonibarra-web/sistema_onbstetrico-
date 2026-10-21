"""
Genera y sube a la NAS el PDF de Trabajo de Parto (partograma) de una paciente
cuyas hojas tienen controles pero nunca se envió (nadie pulsó "Finalizar"). Es
lo que la Consulta histórica avisa como "Falta: Trabajo de parto". Pasadas 24 h
del egreso la pantalla queda en solo consulta, por eso se hace desde la consola.

    python manage.py enviar_trabajo_parto_pendiente <cedula>            # solo muestra qué haría
    python manage.py enviar_trabajo_parto_pendiente <cedula> --aplicar  # genera y sube el PDF
    python manage.py enviar_trabajo_parto_pendiente <cedula> --ingreso 1817104 [--aplicar]

--ingreso: para hojas antiguas que no quedaron asociadas a un ingreso. Solo se
usa si el ingreso es de esa paciente en Dinámica y la hoja se creó dentro de
sus fechas; con --aplicar la hoja queda asociada a ese ingreso.

No modifica los controles (solo los lee para generar el PDF), no reenvía una
hoja que ya está en la NAS y no envía hojas sin controles. Solo con REPOSITORIO_MODO=nas.
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from obstetriciaunificador.models import AtencionParto, DocumentoRepositorio
from obstetriciaunificador.repositorio import RepositorioError, enviar_trabajo_parto, resumen_envio

# Margen para hojas abiertas en triaje poco antes del ingreso formal.
MARGEN_ANTES_DEL_INGRESO = timedelta(hours=24)


def _aware(dt):
    return timezone.make_aware(dt) if dt is not None and timezone.is_naive(dt) else dt


class Command(BaseCommand):
    help = 'Sube a la NAS el PDF de Trabajo de Parto de las hojas con controles que nunca se enviaron.'

    def add_arguments(self, parser):
        parser.add_argument('cedula')
        parser.add_argument('--aplicar', action='store_true', help='Generar y subir de verdad (sin esto, solo muestra qué haría).')
        parser.add_argument('--ingreso', default='', help='Ingreso para las hojas que no tienen uno asociado.')

    def _validar_ingreso(self, cedula, numero):
        """(fecha_ingreso, fecha_egreso) si el ingreso es de la paciente; si no, CommandError."""
        from frecuenciafetal.sala_partos_db import consultar_paciente_de_ingreso
        info = consultar_paciente_de_ingreso(numero)
        if info is None:
            raise CommandError('Dinámica no responde: no se puede comprobar el ingreso. Intente más tarde.')
        if not info:
            raise CommandError(f'El ingreso {numero} no existe en Dinámica.')
        if info['cedula'].strip() != cedula:
            raise CommandError(f'El ingreso {numero} NO es de la cédula {cedula} (es de {info["cedula"]}).')
        if info['anulado']:
            raise CommandError(f'El ingreso {numero} está anulado.')
        return _aware(info['fecha_ingreso']), _aware(info['fecha_egreso'])

    def handle(self, *args, cedula, aplicar, ingreso, **opts):
        from trabajoparto.models import Formulario

        if settings.REPOSITORIO_MODO != 'nas':
            raise CommandError(
                f"REPOSITORIO_MODO es '{settings.REPOSITORIO_MODO}': ponga REPOSITORIO_MODO=nas en el .env "
                "(y pruebe con: manage.py probar_repositorio)."
            )
        cedula = cedula.strip()
        ingreso_indicado = ingreso.strip()
        ventana = self._validar_ingreso(cedula, ingreso_indicado) if ingreso_indicado else None

        hojas = (Formulario.objects.filter(paciente__num_identificacion=cedula)
                 .select_related('paciente', 'aseguradora', 'atencion').order_by('created_at'))
        if not hojas:
            raise CommandError(f'No hay hojas de Trabajo de Parto para la cédula {cedula}.')

        for hoja in hojas:
            controles = hoja.mediciones.count()
            self.stdout.write(f'\nHoja {hoja.pk} (creada {timezone.localtime(hoja.created_at):%d/%m/%Y %H:%M}) - {controles} controles')
            if not controles:
                self.stdout.write('  Sin controles: no se envía.')
                continue
            en_nas = DocumentoRepositorio.objects.filter(
                formato='trabajo_parto', referencia=str(hoja.pk), estado=DocumentoRepositorio.ESTADO_ENVIADO, modo='nas',
            ).order_by('-creado_en').first()
            if en_nas:
                self.stdout.write(self.style.SUCCESS(f'  Ya está en la NAS: {en_nas.ruta}'))
                continue
            # Solo el ingreso guardado en la hoja (o el indicado y comprobado):
            # sin él, enviar_trabajo_parto tomaría el ingreso ACTUAL de la paciente.
            numero = (getattr(hoja.atencion, 'numero_ingreso', '') or '').strip()
            asociar = False
            if not numero:
                if not ventana:
                    self.stdout.write(self.style.ERROR(
                        '  La hoja no tiene ingreso asociado: no se envía. Si sabe el ingreso, use --ingreso NUMERO.'))
                    continue
                desde, hasta = ventana
                creada = hoja.created_at
                if creada < desde - MARGEN_ANTES_DEL_INGRESO or (hasta is not None and creada > hasta):
                    hasta_txt = f'{timezone.localtime(hasta):%d/%m/%Y}' if hasta else 'en curso'
                    self.stdout.write(self.style.ERROR(
                        f'  La hoja no se creó dentro de las fechas del ingreso {ingreso_indicado} '
                        f'({timezone.localtime(desde):%d/%m/%Y} a {hasta_txt}): no se envía.'))
                    continue
                numero, asociar = ingreso_indicado, True
            if not aplicar:
                extra = f' (se asociará la hoja al ingreso {numero})' if asociar else ''
                self.stdout.write(f'  PRUEBA: se subiría a /{settings.REPO_FTP_BASE_PATH}/{cedula}/{numero}/{extra} '
                                  '(agregue --aplicar para subirlo).')
                continue
            if asociar:
                atencion = (AtencionParto.objects.filter(paciente=cedula, numero_ingreso=numero).order_by('fecha_inicio').first()
                            or AtencionParto.objects.create(paciente=cedula, numero_ingreso=numero,
                                                            fecha_ingreso_dinamica=ventana[0]))
                hoja.atencion = atencion
                hoja.save(update_fields=['atencion'])
                self.stdout.write(f'  Hoja asociada al ingreso {numero}.')
            try:
                envio = enviar_trabajo_parto(hoja, usuario='envío manual (consola)')
            except RepositorioError as exc:
                self.stdout.write(self.style.WARNING(f'  No se envió: {exc}'))
                continue
            resumen = resumen_envio(envio)
            estilo = self.style.SUCCESS if resumen['ok'] else self.style.ERROR
            self.stdout.write(estilo(f'  {resumen["mensaje"]}'))
