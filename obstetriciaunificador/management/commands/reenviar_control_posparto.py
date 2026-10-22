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
from obstetriciaunificador.repositorio import (
    _archivos_del_formato, _contenido_pdf, _limpiar, bloqueo_envio, confirmar_envios_grupo, enviar_formato,
    listar_documentos_ingreso,
)


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
            # 2026-10-21: solo el ingreso GUARDADO en el registro (nunca se adivina:
            # el ingreso "actual" de la paciente puede ser otro).
            atencion = r.atencion
            ingreso = (getattr(atencion, 'numero_ingreso', '') or '').strip()
            if not ingreso:
                self.stdout.write(self.style.ERROR('  El registro no tiene ingreso asociado: no se puede ubicar la carpeta en la NAS.'))
                continue
            if not aplicar:
                self.stdout.write(f'  PRUEBA: se subiría a /{settings.REPO_FTP_BASE_PATH}/{cedula}/{ingreso}/ '
                                  '(agregue --aplicar para subirlo).')
                continue
            # Mismo candado que "Guardar Registro Completo" / "Reenviar": nunca dos a la vez.
            with bloqueo_envio(f'manual|control_posparto|{_limpiar(cedula)}|{_limpiar(ingreso)}|{r.pk}'):
                # Un envío anterior "enviando" (sin confirmar) se resuelve contra la NAS primero.
                if DocumentoRepositorio.objects.filter(formato='control_posparto', referencia=str(r.pk)[:64],
                                                       estado=DocumentoRepositorio.ESTADO_ENVIANDO).exists():
                    confirmar_envios_grupo(cedula, ingreso, 'control_posparto')
                if DocumentoRepositorio.objects.filter(formato='control_posparto', referencia=str(r.pk)[:64],
                                                       estado=DocumentoRepositorio.ESTADO_ENVIADO, modo='nas').exists():
                    self.stdout.write(self.style.SUCCESS('  Ya está en la NAS (se acaba de confirmar).'))
                    continue
                # Un PDF de posparto en la carpeta que la bitácora no atribuye a OTRO
                # registro podría ser este (subido sin constancia): no se sube otro.
                de_otros = set(DocumentoRepositorio.objects.filter(
                    formato='control_posparto', cedula=_limpiar(cedula)[:50], numero_ingreso=_limpiar(ingreso)[:30],
                    modo='nas').exclude(referencia=str(r.pk)[:64]).values_list('nombre_archivo', flat=True))
                sueltos = [n for n in _archivos_del_formato(listar_documentos_ingreso(cedula, ingreso), 'control_posparto',
                                                            _limpiar(cedula)).values() if n not in de_otros]
                if sueltos:
                    self.stdout.write(self.style.WARNING(
                        f'  En la carpeta ya hay un PDF de Control Posparto sin constancia ({", ".join(sueltos)}): '
                        'puede ser este. No se sube otro; revíselo en la NAS.'))
                    continue
                pdf = _contenido_pdf(generar_pdf_registro(r))
                envio = enviar_formato(pdf, cedula=cedula, numero_ingreso=ingreso, formato='control_posparto',
                                       atencion=atencion, referencia=r.pk, usuario='reenvío manual (consola)')
            if envio.estado == DocumentoRepositorio.ESTADO_ENVIADO:
                self.stdout.write(self.style.SUCCESS(f'  Subido a la NAS: {envio.ruta}'))
            else:
                self.stdout.write(self.style.ERROR(f'  Error al subir: {envio.detalle_error}'))
