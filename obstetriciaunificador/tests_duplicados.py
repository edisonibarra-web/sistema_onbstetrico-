"""
2026-10-21: inspección de duplicados y documentos mal archivados en la NAS.
Cada prueba reproduce una situación que ANTES duplicaba (o archivaba en otro
ingreso) y comprueba que ya no. (El MEOWS no se toca: se envía solo, sin botón.)
"""
import io
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from frecuenciafetal.models import RegistroParto
from obstetriciaunificador.models import AtencionParto, DocumentoRepositorio
from obstetriciaunificador.repositorio import (
    RepositorioError, SinCambiosError, enviar_control_posparto, huella_contenido,
)

DOC = '1099000222'
INGRESO = '1844002'
R = 'obstetriciaunificador.repositorio'


def _pdf(texto='CONTROL POSPARTO PACIENTE PRUEBA'):
    from reportlab.pdfgen import canvas
    salida = io.BytesIO()
    c = canvas.Canvas(salida)
    c.drawString(72, 720, texto)
    c.save()
    return salida.getvalue()


class BaseDuplicados(TestCase):
    def setUp(self):
        cache.clear()
        self.subidos = []
        self.archivos_nas = []

        def enviar_formato(pdf, *, cedula, numero_ingreso, formato, atencion=None, referencia='', usuario='', huella=None):
            self.subidos.append((formato, str(referencia), numero_ingreso))
            nombre = f'otros_x_{cedula}_{len(self.subidos)}.pdf'
            return DocumentoRepositorio.objects.create(
                atencion=atencion, cedula=cedula, numero_ingreso=numero_ingreso, formato=formato,
                referencia=str(referencia), modo='nas', estado=DocumentoRepositorio.ESTADO_ENVIADO,
                nombre_archivo=nombre, huella_contenido=huella if huella is not None else huella_contenido(pdf),
                enviado_por=usuario,
            )
        self.pdf = _pdf()
        for p in (mock.patch(f'{R}.enviar_formato', side_effect=enviar_formato),
                  mock.patch(f'{R}.listar_documentos_ingreso', side_effect=lambda c, i: list(self.archivos_nas)),
                  mock.patch('frecuenciafetal.pdf_generator.generar_pdf_registro', side_effect=lambda r: self.pdf)):
            p.start()
            self.addCleanup(p.stop)

    def registro(self, atencion=None, creado_hace=timedelta(hours=10), **extra):
        r = RegistroParto.objects.create(atencion=atencion, nombre_paciente='PACIENTE', identificacion=DOC,
                                         edad_gestacional=38, completado_en=timezone.now(), **extra)
        RegistroParto.objects.filter(pk=r.pk).update(created_at=timezone.now() - creado_hace)
        return RegistroParto.objects.get(pk=r.pk)


class RegistroSinIngresoTests(BaseDuplicados):
    """FALLA 1: un registro sin ingreso ya no se archiva en la carpeta de otro ingreso."""

    def _ingreso_vigente(self, inicio_hace=timedelta(hours=30)):
        info = {'numero_ingreso': INGRESO, 'fecha_ingreso': (timezone.localtime() - inicio_hace).replace(tzinfo=None)}
        return mock.patch('frecuenciafetal.sala_partos_db.consultar_ingreso_paciente', return_value=info)

    def test_sin_ingreso_vigente_no_se_envia_a_ninguna_carpeta(self):
        AtencionParto.objects.create(paciente=DOC, numero_ingreso='1700000')  # una atención vieja de OTRO ingreso
        r = self.registro()
        with mock.patch('frecuenciafetal.sala_partos_db.consultar_ingreso_paciente', return_value=None), \
             mock.patch('frecuenciafetal.sala_partos_db.dinamica_disponible', return_value=True):
            with self.assertRaises(RepositorioError):
                enviar_control_posparto(r)
        self.assertEqual(self.subidos, [])  # antes iba a la carpeta del ingreso 1700000

    def test_registro_abierto_antes_del_ingreso_vigente_no_se_envia(self):
        r = self.registro(creado_hace=timedelta(days=10))  # de un ingreso anterior
        with self._ingreso_vigente(), mock.patch('frecuenciafetal.sala_partos_db.dinamica_disponible', return_value=True):
            with self.assertRaises(RepositorioError):
                enviar_control_posparto(r)
        self.assertEqual(self.subidos, [])

    def test_registro_abierto_durante_el_ingreso_vigente_si_se_envia(self):
        r = self.registro(creado_hace=timedelta(hours=10))
        with self._ingreso_vigente(), mock.patch('frecuenciafetal.sala_partos_db.dinamica_disponible', return_value=True):
            enviar_control_posparto(r)
        self.assertEqual(self.subidos, [('control_posparto', str(r.pk), INGRESO)])

    def test_no_se_cierra_un_registro_sin_ingreso_que_no_se_puede_ubicar(self):
        from frecuenciafetal.views import _cerrar_y_enviar_a_repositorio
        r = self.registro()
        RegistroParto.objects.filter(pk=r.pk).update(completado_en=None)
        r = RegistroParto.objects.get(pk=r.pk)
        data = {}
        with mock.patch('frecuenciafetal.sala_partos_db.consultar_ingreso_paciente', return_value=None), \
             mock.patch('frecuenciafetal.sala_partos_db.dinamica_disponible', return_value=True):
            _cerrar_y_enviar_a_repositorio(r, mock.Mock(), data)
        self.assertIn('No se cerró el registro', data['advertencia_cierre'])
        self.assertIsNone(RegistroParto.objects.get(pk=r.pk).completado_en)
        self.assertEqual(self.subidos, [])


class EnvioSinConfirmarTests(BaseDuplicados):
    """FALLA 2: "Reenviar" con un envío anterior sin confirmar ya no sube otra copia."""

    def test_reenviar_con_envio_sin_confirmar_que_si_llego(self):
        atencion = AtencionParto.objects.create(paciente=DOC, numero_ingreso=INGRESO)
        r = self.registro(atencion=atencion)
        nombre = f'otros_control_posparto_inmediato_{DOC}_1.pdf'
        self.archivos_nas.append(nombre)  # el PDF sí llegó, pero quedó "enviando"
        DocumentoRepositorio.objects.create(
            cedula=DOC, numero_ingreso=INGRESO, formato='control_posparto', referencia=str(r.pk), modo='nas',
            estado=DocumentoRepositorio.ESTADO_ENVIANDO, huella_contenido=huella_contenido(self.pdf),
        )
        with self.assertRaises(SinCambiosError):
            enviar_control_posparto(r, usuario='ENFERMERA')
        self.assertEqual(self.subidos, [])
        self.assertEqual(DocumentoRepositorio.objects.get().estado, DocumentoRepositorio.ESTADO_ENVIADO)

    def test_reenviar_con_envio_sin_confirmar_que_no_llego_si_sube(self):
        atencion = AtencionParto.objects.create(paciente=DOC, numero_ingreso=INGRESO)
        r = self.registro(atencion=atencion)
        DocumentoRepositorio.objects.create(
            cedula=DOC, numero_ingreso=INGRESO, formato='control_posparto', referencia=str(r.pk), modo='nas',
            estado=DocumentoRepositorio.ESTADO_ENVIANDO, huella_contenido=huella_contenido(self.pdf),
        )
        enviar_control_posparto(r, usuario='ENFERMERA')  # no estaba en la NAS: se sube una vez
        self.assertEqual(len(self.subidos), 1)


@override_settings(REPOSITORIO_MODO='nas')
class ComandoReenviarTests(BaseDuplicados):
    """FALLA 4: reenviar_control_posparto ya no sube si hay un PDF sin constancia en la carpeta."""

    def test_no_sube_si_ya_hay_un_pdf_suelto(self):
        from django.core.management import call_command
        atencion = AtencionParto.objects.create(paciente=DOC, numero_ingreso=INGRESO)
        self.registro(atencion=atencion)
        self.archivos_nas.append(f'otros_control_posparto_inmediato_{DOC}_1.pdf')
        salida = io.StringIO()
        call_command('reenviar_control_posparto', DOC, aplicar=True, stdout=salida)
        self.assertIn('sin constancia', salida.getvalue())
        self.assertEqual(self.subidos, [])

    def test_sin_ingreso_guardado_no_adivina(self):
        from django.core.management import call_command
        self.registro(atencion=None)
        salida = io.StringIO()
        call_command('reenviar_control_posparto', DOC, aplicar=True, stdout=salida)
        self.assertIn('no tiene ingreso asociado', salida.getvalue())
        self.assertEqual(self.subidos, [])
