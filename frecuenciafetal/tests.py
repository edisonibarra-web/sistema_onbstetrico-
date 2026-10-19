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
        # 2026-10-19: la hora de nacimiento ya no se pide por recién nacido
        # (es la hora de parto de cada feto, ver test_hora_de_parto_de_cada_gemelo).
        self.assertFalse(any('hora de nacimiento' in f for f in faltan))

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

    def test_hora_de_parto_de_cada_gemelo(self):
        """2026-10-19: cada feto con su hora de parto en "Características del
        parto"; la hora de nacimiento de cada recién nacido se toma de ella."""
        from frecuenciafetal.pdf_generator import _hora_nacimiento, generar_pdf_registro
        from frecuenciafetal.views import _intentar_cerrar_registro
        from pypdf import PdfReader

        self._actualizar({
            'numero_fetos': 2, 'hora_parto': '14:44',
            'control_recien_nacido': dict(RN_COMPLETO, hora_nacimiento='09:00'),   # la pantalla no manda
            'control_recien_nacido_b': dict(RN_COMPLETO, hora_nacimiento='14:44'),  # la hora de nacimiento
        })
        rn_a, rn_b = self.registro.recien_nacido(1), self.registro.recien_nacido(2)
        self.assertEqual(rn_a.hora_nacimiento, time(14, 44))  # = hora de parto del Feto A
        self.assertIsNone(rn_b.hora_nacimiento)               # el Feto B NO hereda la del A
        self.assertIsNone(_hora_nacimiento(self.registro, rn_b))
        from unittest import mock
        sin_6h = mock.patch('frecuenciafetal.views._faltantes_control_6h', return_value=[])
        with sin_6h:
            aviso = _intentar_cerrar_registro(self.registro, self.request)
        self.assertIn('hora de parto del Feto B', aviso)

        self._actualizar({'hora_parto_b': '14:51'})
        rn_b.refresh_from_db()
        self.assertEqual(rn_b.hora_nacimiento, time(14, 51))
        self.assertEqual(_hora_nacimiento(self.registro, rn_b), time(14, 51))
        with sin_6h:
            self.assertNotIn('hora de parto del Feto B', _intentar_cerrar_registro(self.registro, self.request) or '')

        # Al corregir la hora de parto del Feto A, su recién nacido la sigue; el B no cambia.
        self._actualizar({'hora_parto': '14:40'})
        rn_a.refresh_from_db(); rn_b.refresh_from_db()
        self.assertEqual((rn_a.hora_nacimiento, rn_b.hora_nacimiento), (time(14, 40), time(14, 51)))
        texto = '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(generar_pdf_registro(self.registro))).pages)
        self.assertIn('Feto A: 14:40', texto)
        self.assertIn('Feto B: 14:51', texto)

    def test_embarazo_unico_no_usa_la_hora_del_feto_b(self):
        self._actualizar({'hora_parto': '10:00', 'control_recien_nacido': RN_COMPLETO})
        self.assertIsNone(self.registro.hora_parto_b)
        from frecuenciafetal.pdf_generator import _hora_nacimiento
        self.assertEqual(_hora_nacimiento(self.registro, self.registro.recien_nacido(1)), time(10, 0))
