"""
2026-10-14: embarazo gemelar en Control Posparto (RegistroParto.numero_fetos,
ControlFetocardia.feto, ControlRecienNacido.feto).
"""
import io
from datetime import date, time

from django.test import RequestFactory, TestCase

from frecuenciafetal.models import ControlFetocardia, ControlRecienNacido, RegistroParto
from frecuenciafetal.serializers import RegistroPartoSerializer, feto_valido
from frecuenciafetal.views import _faltantes_recien_nacido

RN_COMPLETO = {'genero': 'M', 'peso': 2500, 'talla': 48, 'apgar_1min': 8, 'apgar_5min': 9}


class GemelosPospartoTests(TestCase):
    def setUp(self):
        self.registro = RegistroParto.objects.create(
            nombre_paciente='PACIENTE GEMELAR', identificacion='GEM-PP-1', edad_gestacional=37,
        )
        self.request = RequestFactory().patch('/')

    def _actualizar(self, datos):
        serializer = RegistroPartoSerializer(self.registro, data=datos, partial=True,
                                             context={'request': self.request})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return serializer.save()

    def test_el_recien_nacido_de_siempre_es_el_del_feto_a(self):
        rn = ControlRecienNacido.objects.create(registro=self.registro, genero='F')
        self.assertEqual(rn.feto, 1)
        self.assertEqual(self.registro.control_recien_nacido, rn)
        self.assertIsNone(self.registro.control_recien_nacido_b)

    def test_rn_b_ignorado_si_el_registro_no_es_gemelar(self):
        self._actualizar({'control_recien_nacido_b': {'genero': 'M'}})
        self.assertFalse(self.registro.recien_nacidos.filter(feto=2).exists())

    def test_rn_de_cada_gemelo(self):
        self._actualizar({
            'numero_fetos': 2,
            'control_recien_nacido': {'genero': 'F', 'peso': 2300},
            'control_recien_nacido_b': {'genero': 'M', 'peso': 2450},
        })
        self.assertEqual(self.registro.control_recien_nacido.genero, 'F')
        self.assertEqual(self.registro.control_recien_nacido_b.genero, 'M')
        # Un guardado que solo trae el A no toca el B.
        self._actualizar({'control_recien_nacido': {'genero': 'F', 'peso': 2310}})
        self.assertEqual(self.registro.control_recien_nacido_b.peso, 2450)
        datos = RegistroPartoSerializer(self.registro, context={'request': self.request}).data
        self.assertEqual(datos['numero_fetos'], 2)
        self.assertEqual(datos['control_recien_nacido_b']['genero'], 'M')

    def test_no_se_quita_gemelar_con_datos_del_feto_b(self):
        self._actualizar({'numero_fetos': 2, 'control_recien_nacido_b': {'genero': 'M'}})
        serializer = RegistroPartoSerializer(self.registro, data={'numero_fetos': 1}, partial=True,
                                             context={'request': self.request})
        self.assertFalse(serializer.is_valid())
        self.assertIn('numero_fetos', serializer.errors)

    def test_cierre_exige_el_recien_nacido_de_cada_feto(self):
        ControlRecienNacido.objects.create(registro=self.registro, **RN_COMPLETO)
        self.assertEqual(_faltantes_recien_nacido(self.registro), ['huella plantar (PDF)'])
        self.registro.numero_fetos = 2
        self.registro.save()
        faltan = _faltantes_recien_nacido(self.registro)
        self.assertIn('huella plantar (PDF) (Feto A)', faltan)
        self.assertIn('género (Feto B)', faltan)
        self.assertIn('huella plantar (PDF) (Feto B)', faltan)
        # Gemelos: cada uno con su hora de nacimiento.
        self.assertIn('hora de nacimiento (Feto A)', faltan)
        self.assertIn('hora de nacimiento (Feto B)', faltan)
        rn_a = self.registro.recien_nacido(1)
        rn_a.hora_nacimiento = time(9, 30)
        rn_a.save()
        self.assertNotIn('hora de nacimiento (Feto A)', _faltantes_recien_nacido(self.registro))

    def test_feto_valido(self):
        self.assertEqual(feto_valido(self.registro, 2), 1)
        self.registro.numero_fetos = 2
        self.assertEqual(feto_valido(self.registro, 2), 2)
        self.assertEqual(feto_valido(self.registro, 3), 1)
        self.assertEqual(feto_valido(self.registro, None), 1)

    def test_pdf_gemelar(self):
        from pypdf import PdfReader
        from frecuenciafetal.pdf_generator import generar_pdf_registro

        self.registro.numero_fetos = 2
        self.registro.save()
        ControlFetocardia.objects.create(registro=self.registro, fecha=date(2026, 10, 14), hora=time(10, 0), fetocardia=141, feto=1)
        ControlFetocardia.objects.create(registro=self.registro, fecha=date(2026, 10, 14), hora=time(10, 0), fetocardia=152, feto=2)
        ControlRecienNacido.objects.create(registro=self.registro, feto=1, **RN_COMPLETO)
        ControlRecienNacido.objects.create(registro=self.registro, feto=2, **dict(RN_COMPLETO, peso=2222))
        pdf = generar_pdf_registro(self.registro)
        texto = '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(pdf)).pages)
        self.assertIn('Embarazo gemelar', texto)
        self.assertIn('FETO A', texto)
        self.assertIn('FETO B', texto)
        for valor in ('141', '152', '2222'):
            self.assertIn(valor, texto)

    def test_pdf_embarazo_unico_sin_cambios(self):
        from pypdf import PdfReader
        from frecuenciafetal.pdf_generator import generar_pdf_registro

        ControlRecienNacido.objects.create(registro=self.registro, **RN_COMPLETO)
        pdf = generar_pdf_registro(self.registro)
        texto = '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(pdf)).pages)
        self.assertIn('CONTROL DEL RECIÉN NACIDO', texto)
        self.assertNotIn('FETO B', texto)
        self.assertNotIn('Embarazo gemelar', texto)  # la fila solo va cuando es gemelar
