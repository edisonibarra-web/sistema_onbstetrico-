"""
2026-10-19: un solo registro de Control Posparto por paciente e ingreso
(frecuenciafetal/unicidad.py) -- ningún escenario de guardado debe perder
datos ni crear un duplicado que los "esconda".
"""
import io
import shutil
import tempfile
from datetime import time
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from frecuenciafetal.models import (
    ControlGlobo, ControlRecienNacido, ControlSangrado, ControlSutura, ParticipacionRegistroParto, RegistroParto,
)
from obstetriciaunificador.models import AtencionParto

DOC = 'UNI-PP-1'
INGRESO = '900001'
URL = '/fetal/api/registros/'
SIN_DINAMICA = mock.patch('obstetriciaunificador.ingresos.resumen_ingresos', side_effect=Exception('sin Dinámica'))


def _foto_png():
    salida = io.BytesIO()
    Image.new('RGB', (400, 300), 'white').save(salida, 'PNG')
    salida.seek(0)
    salida.name = 'huella.png'
    return salida


def _payload(**extra):
    datos = {'nombre_paciente': 'PACIENTE PRUEBA', 'identificacion': DOC, 'edad_gestacional': 38}
    datos.update(extra)
    return datos


class UnicidadBase(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        ajustes = override_settings(MEDIA_ROOT=self.media)
        ajustes.enable()
        self.addCleanup(ajustes.disable)
        # Administrador: el bloqueo de ingresos cerrados no consulta Dinámica.
        self.usuario = User.objects.create_user('enfermera_prueba', password='x', is_staff=True,
                                                first_name='ENFERMERA', last_name='PRUEBA')
        self.api = APIClient()
        self.api.force_authenticate(self.usuario)
        self.atencion = AtencionParto.objects.create(paciente=DOC, numero_ingreso=INGRESO)

    def crear(self, **extra):
        return self.api.post(URL, _payload(atencion=self.atencion.id, **extra), format='json')


@SIN_DINAMICA
class CrearSinDuplicarTests(UnicidadBase):
    def test_segundo_guardado_del_mismo_ingreso_usa_el_registro_existente(self, _):
        primero = self.crear()
        self.assertEqual(primero.status_code, 200, primero.data)
        segundo = self.crear()
        self.assertEqual(segundo.status_code, 200, segundo.data)
        self.assertEqual(segundo.data['id'], primero.data['id'])
        self.assertTrue(segundo.data['registro_existente'])
        self.assertEqual(RegistroParto.objects.filter(identificacion=DOC).count(), 1)

    def test_no_pisa_lo_guardado_y_llena_lo_vacio(self, _):
        self.crear(edad_gestacional=38, tipo_parto='VAGINAL')
        self.crear(edad_gestacional=40, tipo_parto='CESAREA', nombre_acompanante='ACOMPAÑANTE NUEVO')
        registro = RegistroParto.objects.get(identificacion=DOC)
        self.assertEqual(registro.edad_gestacional, 38)
        self.assertEqual(registro.tipo_parto, 'VAGINAL')
        self.assertEqual(registro.nombre_acompanante, 'ACOMPAÑANTE NUEVO')

    def test_controles_de_vigilancia_no_se_pierden(self, _):
        self.crear(controles_globo=[
            {'minuto_control': 15, 'hora': '10:15', 'estado': 'NORMAL'},
            {'minuto_control': 30, 'hora': '10:30', 'estado': 'NORMAL'},
        ])
        respuesta = self.crear(controles_globo=[
            {'minuto_control': 15, 'hora': '10:15', 'estado': 'NORMAL'},   # reintento: igual -> no se duplica
            {'minuto_control': 30, 'hora': '10:31', 'estado': 'ALERTA'},   # minuto ocupado por otro -> siguiente libre
            {'minuto_control': 45, 'hora': '10:45', 'estado': 'NORMAL'},   # nuevo
        ], controles_sutura=[{'minuto_control': 15, 'hora': '10:15', 'estado': 'NORMAL'}],
            controles_sangrado=[{'minuto_control': 15, 'hora': '10:15', 'cc': 50}])
        registro = RegistroParto.objects.get(identificacion=DOC)
        globo = {c.minuto_control: (c.hora, c.estado) for c in registro.controles_globo.all()}
        self.assertEqual(globo[15], (time(10, 15), 'NORMAL'))
        self.assertEqual(globo[30], (time(10, 30), 'NORMAL'))
        self.assertEqual(globo[45], (time(10, 45), 'NORMAL'))
        self.assertEqual(globo[60], (time(10, 31), 'ALERTA'))
        self.assertEqual(len(globo), 4)
        self.assertTrue(any('30 min' in a and '60 min' in a for a in respuesta.data['avisos']))
        self.assertEqual(registro.controles_sutura.count(), 1)
        sangrado = registro.controles_sangrado.get()
        self.assertEqual(sangrado.cc, 50)
        self.assertIsNotNone(sangrado.estado)  # semáforo calculado por el servidor
        self.assertTrue(sangrado.registrado_por)  # con la firma de quien lo registró

    def test_huella_y_recien_nacido_se_conservan(self, _):
        registro_id = self.crear(control_recien_nacido={'genero': 'F', 'peso': 3100}).data['id']
        subida = self.api.post(f'{URL}{registro_id}/huella-rn/', {'archivo': _foto_png()}, format='multipart')
        self.assertEqual(subida.status_code, 200, subida.data)
        # Una pantalla en blanco (no pudo cargar) manda otro recién nacido.
        respuesta = self.crear(control_recien_nacido={'genero': 'M', 'peso': 2000, 'talla': 50})
        rn = ControlRecienNacido.objects.get(registro_id=registro_id, feto=1)
        self.assertEqual((rn.genero, rn.peso, rn.talla), ('F', 3100, 50))
        self.assertTrue(rn.huella_pdf)
        self.assertTrue(respuesta.data['control_recien_nacido']['tiene_huella'])
        # La huella se sigue pudiendo ver.
        self.assertEqual(self.api.get(f'{URL}{registro_id}/huella-rn/').status_code, 200)

    def test_registro_cerrado_no_se_modifica_ni_se_duplica(self, _):
        registro_id = self.crear(tipo_parto='VAGINAL').data['id']
        RegistroParto.objects.filter(pk=registro_id).update(completado_en=timezone.now())
        respuesta = self.crear(tipo_parto='CESAREA', controles_globo=[{'minuto_control': 15, 'hora': '10:15', 'estado': 'NORMAL'}])
        self.assertEqual(respuesta.data['id'], registro_id)
        self.assertIn('cerrado', respuesta.data['avisos'][0])
        registro = RegistroParto.objects.get(pk=registro_id)
        self.assertEqual(registro.tipo_parto, 'VAGINAL')
        self.assertEqual(registro.controles_globo.count(), 0)
        self.assertEqual(RegistroParto.objects.filter(identificacion=DOC).count(), 1)

    def test_otro_ingreso_si_crea_su_propio_registro(self, _):
        self.crear()
        otra = AtencionParto.objects.create(paciente=DOC, numero_ingreso='900002')
        respuesta = self.api.post(URL, _payload(atencion=otra.id), format='json')
        self.assertNotIn('registro_existente', respuesta.data)
        self.assertEqual(RegistroParto.objects.filter(identificacion=DOC).count(), 2)

    def test_otra_paciente_no_se_mezcla(self, _):
        self.crear()
        respuesta = self.api.post(URL, _payload(identificacion='OTRA-PACIENTE', atencion=self.atencion.id), format='json')
        self.assertNotIn('registro_existente', respuesta.data)
        self.assertEqual(RegistroParto.objects.count(), 2)

    def test_quien_registra_queda_como_participante(self, _):
        registro_id = self.crear().data['id']
        otra = User.objects.create_user('enfermera_dos', password='x', is_staff=True, first_name='OTRA', last_name='ENFERMERA')
        self.api.force_authenticate(otra)
        self.crear(controles_globo=[{'minuto_control': 15, 'hora': '10:15', 'estado': 'NORMAL'}])
        nombres = set(ParticipacionRegistroParto.objects.filter(registro_id=registro_id).values_list('profesional', flat=True))
        self.assertEqual(nombres, {'ENFERMERA PRUEBA', 'OTRA ENFERMERA'})
        self.assertEqual(ControlGlobo.objects.get(registro_id=registro_id).registrado_por, 'OTRA ENFERMERA')


class CrearConSelectorDeIngresosTests(UnicidadBase):
    """Con Dinámica disponible se usa el mismo selector de ingresos que al
    abrir el formulario (aunque el enlace no traiga ?atencion=)."""

    def test_sin_atencion_en_el_enlace_igual_encuentra_el_registro(self):
        registro = RegistroParto.objects.create(nombre_paciente='P', identificacion=DOC, edad_gestacional=38)
        resumen = ({'elegido': INGRESO}, {INGRESO: [registro.id]})
        with mock.patch('obstetriciaunificador.ingresos.resumen_ingresos', return_value=resumen):
            respuesta = self.api.post(URL, _payload(), format='json')
        self.assertEqual(respuesta.data['id'], str(registro.id))
        self.assertEqual(RegistroParto.objects.filter(identificacion=DOC).count(), 1)

    def test_ingreso_sin_registros_crea_uno_nuevo(self):
        resumen = ({'elegido': INGRESO}, {})
        with mock.patch('obstetriciaunificador.ingresos.resumen_ingresos', return_value=resumen):
            respuesta = self.api.post(URL, _payload(), format='json')
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertNotIn('registro_existente', respuesta.data)


class AbrirRegistroPrincipalTests(UnicidadBase):
    """Con duplicados ya existentes, el formulario abre el que tiene los datos."""

    def test_abre_el_registro_con_datos_y_no_el_duplicado_vacio(self):
        con_datos = RegistroParto.objects.create(nombre_paciente='P', identificacion=DOC, edad_gestacional=38, atencion=self.atencion)
        for minuto in (15, 30):
            ControlGlobo.objects.create(registro=con_datos, minuto_control=minuto, hora=time(10, minuto), estado='NORMAL')
        vacio = RegistroParto.objects.create(nombre_paciente='P', identificacion=DOC, edad_gestacional=38, atencion=self.atencion)
        resumen = ({'elegido': INGRESO, 'solo_consulta': False}, {INGRESO: [con_datos.id, vacio.id]})
        with mock.patch('obstetriciaunificador.ingresos.resumen_ingresos', return_value=resumen):
            respuesta = self.api.get(f'{URL}por-atencion/', {'documento': DOC})
        self.assertEqual(respuesta.data['id'], str(con_datos.id))
        self.assertEqual(len(respuesta.data['controles_globo']), 2)

    def test_el_cerrado_gana_sobre_el_abierto(self):
        cerrado = RegistroParto.objects.create(nombre_paciente='P', identificacion=DOC, edad_gestacional=38, atencion=self.atencion,
                                               completado_en=timezone.now())
        abierto = RegistroParto.objects.create(nombre_paciente='P', identificacion=DOC, edad_gestacional=38, atencion=self.atencion)
        ControlGlobo.objects.create(registro=abierto, minuto_control=15, hora=time(10, 15), estado='NORMAL')
        resumen = ({'elegido': INGRESO, 'solo_consulta': False}, {INGRESO: [cerrado.id, abierto.id]})
        with mock.patch('obstetriciaunificador.ingresos.resumen_ingresos', return_value=resumen):
            respuesta = self.api.get(f'{URL}por-atencion/', {'documento': DOC})
        self.assertEqual(respuesta.data['id'], str(cerrado.id))


class FusionarDuplicadosTests(UnicidadBase):
    """Comando fusionar_registros_posparto (reparación de los duplicados)."""

    def _registro(self, **extra):
        return RegistroParto.objects.create(nombre_paciente='P', identificacion=DOC, edad_gestacional=38, atencion=self.atencion, **extra)

    def _comando(self, *args):
        salida = io.StringIO()
        call_command('fusionar_registros_posparto', '--documento', DOC, *args, stdout=salida)
        return salida.getvalue()

    def test_sin_aplicar_no_cambia_nada(self):
        principal, duplicado = self._registro(), self._registro()
        ControlGlobo.objects.create(registro=principal, minuto_control=15, hora=time(10, 15), estado='NORMAL')
        ControlGlobo.objects.create(registro=duplicado, minuto_control=30, hora=time(10, 30), estado='NORMAL')
        salida = self._comando()
        self.assertIn('REVISIÓN', salida)
        self.assertEqual(duplicado.controles_globo.count(), 1)
        self.assertEqual(RegistroParto.objects.filter(identificacion=DOC).count(), 2)

    def test_mueve_todo_al_principal_y_elimina_el_duplicado_vacio(self):
        principal = self._registro()
        for minuto in (15, 30):
            ControlSangrado.objects.create(registro=principal, minuto_control=minuto, hora=time(10, minuto), cc=10,
                                           registrado_por='ENF A')
        duplicado = self._registro(nombre_acompanante='ESPOSO')
        ControlSutura.objects.create(registro=duplicado, minuto_control=15, hora=time(10, 15), estado='NORMAL',
                                     registrado_por='ENF B')
        rn = ControlRecienNacido.objects.create(registro=duplicado, feto=1, genero='F', peso=3000)
        ParticipacionRegistroParto.objects.create(registro=duplicado, profesional='ENF B',
                                                  primera_vez=timezone.now(), ultima_vez=timezone.now())
        self._comando('--aplicar')
        self.assertFalse(RegistroParto.objects.filter(pk=duplicado.pk).exists())
        principal.refresh_from_db()
        self.assertEqual(principal.nombre_acompanante, 'ESPOSO')
        self.assertEqual(principal.controles_sangrado.count(), 2)
        sutura = principal.controles_sutura.get()
        self.assertEqual(sutura.registrado_por, 'ENF B')  # conserva su firma original
        self.assertEqual(ControlRecienNacido.objects.get(pk=rn.pk).registro_id, principal.pk)
        self.assertTrue(principal.participaciones.filter(profesional='ENF B').exists())

    def test_con_conflictos_no_borra_nada(self):
        principal = self._registro()
        ControlGlobo.objects.create(registro=principal, minuto_control=15, hora=time(10, 15), estado='NORMAL')
        ControlGlobo.objects.create(registro=principal, minuto_control=30, hora=time(10, 30), estado='NORMAL')
        duplicado = self._registro()
        ControlGlobo.objects.create(registro=duplicado, minuto_control=15, hora=time(10, 16), estado='ALERTA')
        salida = self._comando('--aplicar')
        self.assertIn('ya existe en el registro principal', salida)
        self.assertTrue(RegistroParto.objects.filter(pk=duplicado.pk).exists())
        self.assertEqual(duplicado.controles_globo.get().estado, 'ALERTA')  # el dato en conflicto no se pierde

    def test_huella_del_duplicado_pasa_al_principal(self):
        principal = self._registro()
        ControlGlobo.objects.create(registro=principal, minuto_control=15, hora=time(10, 15), estado='NORMAL')
        ControlRecienNacido.objects.create(registro=principal, feto=1, genero='F')
        duplicado = self._registro()
        registro_dup = duplicado.pk
        subida = self.api.post(f'{URL}{registro_dup}/huella-rn/', {'archivo': _foto_png()}, format='multipart')
        self.assertEqual(subida.status_code, 200, subida.data)
        self._comando('--aplicar')
        rn = ControlRecienNacido.objects.get(registro=principal, feto=1)
        self.assertTrue(rn.huella_pdf)
        self.assertEqual(self.api.get(f'{URL}{principal.pk}/huella-rn/').status_code, 200)
