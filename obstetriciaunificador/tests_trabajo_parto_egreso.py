"""
2026-10-21: Trabajo de Parto automático al egreso -- y, sobre todo, que NUNCA
genere duplicados (el botón "Finalizar" sigue existiendo).
"""
from contextlib import contextmanager
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from obstetriciaunificador.models import AtencionParto, DocumentoRepositorio
from obstetriciaunificador.repositorio import enviar_trabajo_parto_al_egreso, enviar_trabajo_parto_egresos_pendientes

DOC = '1099000111'
INGRESO = '1844001'
R = 'obstetriciaunificador.repositorio'


def _estado(horas_desde_egreso):
    egreso = None if horas_desde_egreso is None else (timezone.localtime() - timedelta(hours=horas_desde_egreso)).replace(tzinfo=None)
    return {'activo': egreso is None, 'fecha_egreso': egreso, 'tiene_estancias': True, 'anulado': False, 'tipo': 'hospitalizacion'}


class TrabajoPartoAlEgresoTests(TestCase):
    def setUp(self):
        from trabajoparto.models import EstadoFormulario, Formulario, Medicion, Paciente, Parametro
        cache.clear()
        paciente = Paciente.objects.create(num_historia_clinica=DOC, num_identificacion=DOC, nombres='PACIENTE PRUEBA')
        self.atencion = AtencionParto.objects.create(paciente=DOC, numero_ingreso=INGRESO)
        self.hoja = Formulario.objects.create(
            atencion=self.atencion, paciente=paciente, codigo='FRSPA', version='1', fecha_elabora=timezone.localdate(),
            num_hoja=1, estado=EstadoFormulario.G, responsable='ENFERMERA',
        )
        Medicion.objects.create(formulario=self.hoja, parametro=Parametro.objects.first(), tomada_en=timezone.now())
        self.horas_egreso = 30  # egresó hace 30 h
        self.archivos_nas = []
        self.subidos = []

        def enviar_formato(pdf, *, cedula, numero_ingreso, formato, atencion=None, referencia='', usuario='', huella=None):
            from obstetriciaunificador.repositorio import huella_contenido
            self.subidos.append(referencia)
            nombre = f'otros_trabajo_de_parto_{cedula}_{len(self.archivos_nas) + 1}.pdf'
            self.archivos_nas.append(nombre)
            return DocumentoRepositorio.objects.create(
                atencion=atencion, cedula=cedula, numero_ingreso=numero_ingreso, formato=formato,
                referencia=str(referencia), modo='nas', estado=DocumentoRepositorio.ESTADO_ENVIADO,
                nombre_archivo=nombre, enviado_por=usuario,
                huella_contenido=huella if huella is not None else huella_contenido(pdf),  # como el real
            )
        for p in (mock.patch('frecuenciafetal.sala_partos_db.consultar_estado_ingreso',
                             side_effect=lambda n: _estado(self.horas_egreso)),
                  mock.patch(f'{R}.listar_documentos_ingreso', side_effect=lambda c, i: list(self.archivos_nas)),
                  mock.patch('trabajoparto.pdf_utils.generar_pdf_formulario_clinico', return_value=b'%PDF trabajo de parto'),
                  mock.patch(f'{R}.enviar_formato', side_effect=enviar_formato)):
            p.start()
            self.addCleanup(p.stop)

    def _envio_manual_previo(self, estado=DocumentoRepositorio.ESTADO_ENVIADO):
        nombre = f'otros_trabajo_de_parto_{DOC}_1.pdf'
        self.archivos_nas.append(nombre)
        DocumentoRepositorio.objects.create(
            cedula=DOC, numero_ingreso=INGRESO, formato='trabajo_parto', referencia=str(self.hoja.pk),
            modo='nas', estado=estado, nombre_archivo=nombre, enviado_por='ENFERMERA (botón Finalizar)',
        )

    # --- Lo que SÍ debe pasar --------------------------------------------
    def test_hoja_olvidada_se_envia_una_sola_vez(self):
        self.assertIsNotNone(enviar_trabajo_parto_al_egreso(self.hoja))
        self.assertIsNone(enviar_trabajo_parto_al_egreso(self.hoja))           # segunda pasada: nada
        enviar_trabajo_parto_egresos_pendientes()                             # tercera pasada: nada
        self.assertEqual(self.subidos, [self.hoja.pk])
        self.assertEqual(DocumentoRepositorio.objects.get().enviado_por, 'automático (egreso)')

    # --- Duplicados: NO debe subir nada ------------------------------------
    def test_si_la_enfermera_ya_pulso_finalizar_no_se_envia_otra_copia(self):
        self._envio_manual_previo()
        self.assertIsNone(enviar_trabajo_parto_al_egreso(self.hoja))
        self.assertEqual(enviar_trabajo_parto_egresos_pendientes(), [])
        self.assertEqual(self.subidos, [])

    def test_si_hay_un_envio_en_curso_no_se_envia(self):
        self._envio_manual_previo(estado=DocumentoRepositorio.ESTADO_ENVIANDO)
        self.assertIsNone(enviar_trabajo_parto_al_egreso(self.hoja))
        self.assertEqual(self.subidos, [])

    def test_si_el_pdf_ya_esta_en_la_nas_sin_constancia_no_se_sube_otro(self):
        self.archivos_nas.append(f'otros_trabajo_de_parto_{DOC}_1.pdf')  # subido pero no confirmado
        envio = enviar_trabajo_parto_al_egreso(self.hoja)
        self.assertEqual(self.subidos, [])
        self.assertEqual(envio.enviado_por, 'automático (ya estaba en el repositorio)')
        self.assertIsNone(enviar_trabajo_parto_al_egreso(self.hoja))           # y no vuelve a intentarlo

    def test_si_el_boton_tiene_el_candado_no_se_envia(self):
        @contextmanager
        def ocupado(*a, **k):
            yield False
        with mock.patch(f'{R}.bloqueo_envio', ocupado):
            self.assertIsNone(enviar_trabajo_parto_al_egreso(self.hoja))
        self.assertEqual(self.subidos, [])

    def test_mismo_candado_que_el_boton_finalizar(self):
        claves = []

        @contextmanager
        def registrar(clave, **k):
            claves.append(clave)
            yield True
        with mock.patch(f'{R}.bloqueo_envio', registrar):
            enviar_trabajo_parto_al_egreso(self.hoja)
        self.assertEqual(claves, [f'manual|trabajo_parto|{DOC}|{INGRESO}|{self.hoja.pk}'])

    # --- Cuándo NO corresponde enviar ------------------------------------
    def test_paciente_en_atencion_no_se_envia(self):
        self.horas_egreso = None
        self.assertIsNone(enviar_trabajo_parto_al_egreso(self.hoja))
        self.assertEqual(self.subidos, [])

    def test_egreso_de_hace_mas_de_7_dias_no_se_envia(self):
        self.horas_egreso = 8 * 24
        self.assertIsNone(enviar_trabajo_parto_al_egreso(self.hoja))
        self.assertEqual(self.subidos, [])

    def test_hoja_sin_controles_no_se_envia(self):
        self.hoja.mediciones.all().delete()
        self.assertIsNone(enviar_trabajo_parto_al_egreso(self.hoja))
        self.assertEqual(self.subidos, [])

    def test_tras_5_errores_deja_de_intentar(self):
        for _ in range(5):
            DocumentoRepositorio.objects.create(
                cedula=DOC, numero_ingreso=INGRESO, formato='trabajo_parto', referencia=str(self.hoja.pk),
                modo='nas', estado=DocumentoRepositorio.ESTADO_ERROR, enviado_por='automático (egreso)',
            )
        self.assertIsNone(enviar_trabajo_parto_al_egreso(self.hoja))
        self.assertEqual(self.subidos, [])

    def test_el_pdf_de_otra_hoja_del_mismo_ingreso_no_bloquea(self):
        nombre = f'otros_trabajo_de_parto_{DOC}_1.pdf'
        self.archivos_nas.append(nombre)
        DocumentoRepositorio.objects.create(
            cedula=DOC, numero_ingreso=INGRESO, formato='trabajo_parto', referencia='999999',  # otra hoja
            modo='nas', estado=DocumentoRepositorio.ESTADO_ENVIADO, nombre_archivo=nombre,
        )
        self.assertIsNotNone(enviar_trabajo_parto_al_egreso(self.hoja))
        self.assertEqual(self.subidos, [self.hoja.pk])

    def test_si_la_enfermera_pulsa_finalizar_despues_del_automatico_no_se_duplica(self):
        import io
        from reportlab.pdfgen import canvas
        from obstetriciaunificador.repositorio import SinCambiosError, enviar_trabajo_parto
        salida = io.BytesIO()
        c = canvas.Canvas(salida)
        c.drawString(72, 720, 'PARTOGRAMA PACIENTE PRUEBA - 1 control')
        c.save()
        with mock.patch('trabajoparto.pdf_utils.generar_pdf_formulario_clinico', return_value=salida.getvalue()):
            self.assertIsNotNone(enviar_trabajo_parto_al_egreso(self.hoja))        # automático al egreso
            with self.assertRaises(SinCambiosError):                               # luego el botón "Finalizar"
                enviar_trabajo_parto(self.hoja, usuario='ENFERMERA')
        self.assertEqual(self.subidos, [self.hoja.pk])                             # un solo PDF en la NAS

    def test_si_ya_estaba_en_la_nas_y_luego_pulsan_finalizar_no_se_duplica(self):
        import io
        from reportlab.pdfgen import canvas
        from obstetriciaunificador.repositorio import SinCambiosError, enviar_trabajo_parto
        salida = io.BytesIO()
        c = canvas.Canvas(salida)
        c.drawString(72, 720, 'PARTOGRAMA PACIENTE PRUEBA - 1 control')
        c.save()
        pdf = salida.getvalue()
        self.archivos_nas.append(f'otros_trabajo_de_parto_{DOC}_1.pdf')  # subido pero no confirmado
        with mock.patch('trabajoparto.pdf_utils.generar_pdf_formulario_clinico', return_value=pdf), \
             mock.patch(f'{R}.leer_documento_ingreso', return_value=pdf):
            self.assertIsNotNone(enviar_trabajo_parto_al_egreso(self.hoja))   # deja constancia (con huella)
            with self.assertRaises(SinCambiosError):
                enviar_trabajo_parto(self.hoja, usuario='ENFERMERA')
        self.assertEqual(self.subidos, [])
