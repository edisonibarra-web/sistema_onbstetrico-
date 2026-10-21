"""
2026-10-19: lo que registra una enfermera solo ella lo corrige o borra
(frecuenciafetal/propiedad.py). La otra puede llenar lo vacío y agregar
controles nuevos. Ni un administrador puede cambiar lo de otra persona.
"""
import io
import shutil
import tempfile
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from frecuenciafetal.models import (
    CambioRegistroParto, ControlGlobo, ControlRecienNacido, ControlSangrado, GlucometriaRecienNacido,
    ParticipacionRegistroParto, RegistroParto,
)

URL = '/fetal/api/registros/'
SIN_DINAMICA = mock.patch('obstetriciaunificador.ingresos.resumen_ingresos', side_effect=Exception('sin Dinámica'))


def _foto():
    salida = io.BytesIO()
    Image.new('RGB', (300, 200), 'white').save(salida, 'PNG')
    salida.seek(0)
    salida.name = 'huella.png'
    return salida


@SIN_DINAMICA
class SoloLaAutoraTests(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        ajuste = override_settings(MEDIA_ROOT=media)
        ajuste.enable()
        self.addCleanup(ajuste.disable)
        self.a = APIClient()
        self.a.force_authenticate(User.objects.create_user('enf_a', first_name='ENFERMERA', last_name='A'))
        self.b = APIClient()
        # Administradora: ni así puede cambiar lo de otra persona (decisión del hospital).
        self.b.force_authenticate(User.objects.create_user('enf_b', first_name='ENFERMERA', last_name='B',
                                                           is_staff=True, is_superuser=True))
        respuesta = self.a.post(URL, {
            'nombre_paciente': 'PACIENTE', 'identificacion': 'PROP-1', 'edad_gestacional': 38,
            'tipo_parto': 'VAGINAL', 'hora_parto': '10:00',
            'control_recien_nacido': {'genero': 'F', 'peso': 3000},
        }, format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.id = respuesta.data['id']
        self.url = f'{URL}{self.id}/'

    def registro(self):
        return RegistroParto.objects.get(pk=self.id)

    # --- Campos del registro -------------------------------------------------
    def test_la_otra_no_cambia_un_campo_ajeno(self, _):
        r = self.b.patch(self.url, {'tipo_parto': 'CESAREA'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data['campos_ajenos'][0]['campo'], 'tipo_parto')
        self.assertIn('ENFERMERA A', r.data['detail'])
        self.assertEqual(self.registro().tipo_parto, 'VAGINAL')

    def test_un_campo_ajeno_rechaza_todo_el_guardado(self, _):
        r = self.b.patch(self.url, {'tipo_parto': 'CESAREA', 'tipo_alumbramiento': 'DIRIGIDO'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(self.registro().tipo_alumbramiento)  # nada a medias

    def test_la_otra_llena_lo_vacio_y_queda_como_duena(self, _):
        r = self.b.patch(self.url, {'tipo_alumbramiento': 'DIRIGIDO'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.registro().duenos_campos['tipo_alumbramiento']['usuario'], 'enf_b')
        r = self.a.patch(self.url, {'tipo_alumbramiento': 'MANUAL'}, format='json')
        self.assertEqual(r.status_code, 403)  # ahora es de B

    def test_la_autora_corrige_lo_suyo(self, _):
        r = self.a.patch(self.url, {'tipo_parto': 'CESAREA', 'hora_parto': '10:05'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.registro().tipo_parto, 'CESAREA')

    def test_reenviar_el_mismo_valor_no_es_un_cambio(self, _):
        r = self.b.patch(self.url, {'tipo_parto': 'VAGINAL', 'hora_parto': '10:00'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_si_la_autora_lo_borra_queda_libre(self, _):
        self.assertEqual(self.a.patch(self.url, {'tipo_parto': None}, format='json').status_code, 200)
        self.assertNotIn('tipo_parto', self.registro().duenos_campos)
        self.assertEqual(self.b.patch(self.url, {'tipo_parto': 'CESAREA'}, format='json').status_code, 200)

    def test_cerrado_la_vista_previa_tampoco_cambia_lo_ajeno(self, _):
        RegistroParto.objects.filter(pk=self.id).update(completado_en=timezone.now())
        self.assertEqual(self.b.patch(self.url, {'hora_parto': '11:00'}, format='json').status_code, 403)
        self.assertEqual(self.a.patch(self.url, {'hora_parto': '11:00'}, format='json').status_code, 200)

    # --- Recién nacido ---------------------------------------------------------
    def test_recien_nacido_por_campo(self, _):
        r = self.b.patch(self.url, {'control_recien_nacido': {'peso': 2500}}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(ControlRecienNacido.objects.get(registro_id=self.id).peso, 3000)
        r = self.b.patch(self.url, {'control_recien_nacido': {'talla': 50}}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        rn = ControlRecienNacido.objects.get(registro_id=self.id)
        self.assertEqual((rn.peso, rn.talla), (3000, 50))
        self.assertEqual(rn.duenos_campos['talla']['usuario'], 'enf_b')
        self.assertEqual(rn.duenos_campos['peso']['usuario'], 'enf_a')
        # Por el endpoint del recién nacido, igual.
        r = self.b.patch(f'{self.url}recien-nacido/{rn.pk}/', {'peso': 1}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.b.delete(f'{self.url}recien-nacido/{rn.pk}/').status_code, 403)

    def test_glucometrias(self, _):
        hora = {'hora': '10:30', 'resultado': '60'}
        self.assertEqual(self.a.patch(self.url, {'control_recien_nacido': {'glucometrias_agregar': [hora]}},
                                      format='json').status_code, 200)
        g = GlucometriaRecienNacido.objects.get()
        self.assertEqual(g.registrado_usuario, 'enf_a')
        r = self.b.patch(self.url, {'control_recien_nacido': {'glucometrias_quitar': [hora]}}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.b.patch(self.url, {'control_recien_nacido': {'glucometrias': []}}, format='json')
        self.assertEqual(r.status_code, 403)  # una lista que ya no la trae tampoco la borra
        otra = {'hora': '11:30', 'resultado': '70'}
        self.assertEqual(self.b.patch(self.url, {'control_recien_nacido': {'glucometrias_agregar': [otra]}},
                                      format='json').status_code, 200)
        self.assertEqual(self.b.patch(self.url, {'control_recien_nacido': {'glucometrias_quitar': [otra]}},
                                      format='json').status_code, 200)
        self.assertEqual(list(GlucometriaRecienNacido.objects.values_list('registrado_usuario', flat=True)), ['enf_a'])

    # --- Controles (filas) -------------------------------------------------------
    def test_controles_de_vigilancia(self, _):
        r = self.a.post(f'{self.url}globo/', {'minuto_control': 15, 'hora': '10:15', 'estado': 'NORMAL'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        url_globo = f'{self.url}globo/{r.data["id"]}/'
        self.assertEqual(ControlGlobo.objects.get().registrado_usuario, 'enf_a')
        r = self.b.patch(url_globo, {'estado': 'ALERTA'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertIn('ENFERMERA A', str(r.data['detail']))
        self.assertEqual(self.b.delete(url_globo).status_code, 403)
        self.assertEqual(ControlGlobo.objects.get().estado, 'NORMAL')
        # El siguiente control sí lo agrega la otra (relevo de turno).
        r = self.b.post(f'{self.url}globo/', {'minuto_control': 30, 'hora': '10:30', 'estado': 'NORMAL'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.a.patch(url_globo, {'estado': 'ALERTA'}, format='json').status_code, 200)
        self.assertEqual(self.b.patch(url_globo, {'estado': 'ALERTA'}, format='json').status_code, 200)  # mismo valor

    def test_sangrado(self, _):
        r = self.a.post(f'{self.url}sangrado/', {'minuto_control': 15, 'hora': '10:15', 'cc': 40}, format='json')
        url = f'{self.url}sangrado/{r.data["id"]}/'
        self.assertEqual(self.b.patch(url, {'cc': 80}, format='json').status_code, 403)
        self.assertEqual(self.b.delete(url).status_code, 403)
        self.assertEqual(ControlSangrado.objects.get().cc, 40)
        self.assertEqual(self.a.delete(url).status_code, 204)

    def test_fetocardia(self, _):
        r = self.a.post(f'{self.url}fetocardia/', {'fecha': '2026-10-19', 'hora': '09:00', 'fetocardia': 140}, format='json')
        url = f'{self.url}fetocardia/{r.data["id"]}/'
        self.assertEqual(self.b.patch(url, {'fetocardia': 150}, format='json').status_code, 403)
        self.assertEqual(self.a.patch(url, {'fetocardia': 150}, format='json').status_code, 200)

    # --- Huella ------------------------------------------------------------------
    def test_huella(self, _):
        url = f'{self.url}huella-rn/'
        self.assertEqual(self.a.post(url, {'archivo': _foto()}, format='multipart').status_code, 200)
        self.assertEqual(ControlRecienNacido.objects.get(registro_id=self.id).huella_subida_usuario, 'enf_a')
        self.assertEqual(self.b.post(url, {'archivo': _foto()}, format='multipart').status_code, 403)
        self.assertEqual(self.b.delete(url).status_code, 403)
        self.assertTrue(ControlRecienNacido.objects.get(registro_id=self.id).huella_pdf)
        self.assertEqual(self.a.delete(url).status_code, 200)
        # Sin huella, la otra sí puede cargarla.
        self.assertEqual(self.b.post(url, {'archivo': _foto()}, format='multipart').status_code, 200)
        # Ver la de otra persona sí se puede (al final: en Windows un archivo abierto no se borra).
        self.assertEqual(self.a.get(url).status_code, 200)

    def test_la_api_devuelve_los_duenos(self, _):
        datos = self.b.get(self.url).data
        self.assertEqual(datos['duenos_campos']['tipo_parto']['usuario'], 'enf_a')
        self.assertEqual(datos['control_recien_nacido']['duenos_campos']['peso']['nombre'], 'ENFERMERA A')


class DatosAnterioresTests(TestCase):
    """Migración 0046: el dueño de lo ya registrado sale de la firma y la bitácora."""

    def test_asigna_por_firma_y_bitacora(self):
        from django.apps import apps
        from frecuenciafetal.propiedad import asignar_duenos_existentes
        r = RegistroParto.objects.create(nombre_paciente='P', identificacion='OLD-1', edad_gestacional=38,
                                         tipo_parto='VAGINAL', tipo_alumbramiento='MANUAL')
        ahora = timezone.now()
        ParticipacionRegistroParto.objects.create(registro=r, profesional='ANA', usuario='ana', primera_vez=ahora, ultima_vez=ahora)
        g = ControlGlobo.objects.create(registro=r, minuto_control=15, hora='10:15', estado='NORMAL', registrado_por='ANA')
        sin = ControlGlobo.objects.create(registro=r, minuto_control=30, hora='10:30', estado='NORMAL', registrado_por='DESCONOCIDA')
        CambioRegistroParto.objects.create(registro=r, seccion='parto', accion='registro', detalle='Tipo de parto',
                                           profesional='ANA', usuario='ana')
        CambioRegistroParto.objects.create(registro=r, seccion='parto', accion='correccion', detalle='Tipo de parto',
                                           profesional='LUZ', usuario='luz')
        asignar_duenos_existentes({n: apps.get_model('registros', n) for n in (
            'RegistroParto', 'ControlSangrado', 'ControlGlobo', 'ControlSutura', 'ControlFetocardia',
            'ControlPostpartoInmediato', 'ControlRecienNacido', 'ParticipacionRegistroParto', 'CambioRegistroParto')})
        g.refresh_from_db(); sin.refresh_from_db(); r.refresh_from_db()
        self.assertEqual(g.registrado_usuario, 'ana')
        self.assertEqual(sin.registrado_usuario, '')                    # no se sabe: queda libre
        self.assertEqual(r.duenos_campos['tipo_parto']['usuario'], 'ana')  # quien lo registró primero
        self.assertNotIn('tipo_alumbramiento', r.duenos_campos)         # sin bitácora: libre


@SIN_DINAMICA
class PacienteEnCirugiaTests(TestCase):
    """2026-10-21: "Paciente en cirugía" en Globo de seguridad y Sutura y heridas."""
    setUp = SoloLaAutoraTests.setUp

    def test_globo_y_sutura_aceptan_paciente_en_cirugia(self, _):
        from frecuenciafetal.models import ControlSutura
        for tipo, modelo in (('globo', ControlGlobo), ('sutura', ControlSutura)):
            r = self.a.post(f'{self.url}{tipo}/', {'minuto_control': 15, 'hora': '10:15', 'estado': 'EN_CIRUGIA'}, format='json')
            self.assertEqual(r.status_code, 201, r.data)
            self.assertEqual(modelo.objects.get().get_estado_display(), 'Paciente en cirugía')
