"""
2026-10-21: para que los Control Posparto no queden a medias -- requisitos de
cierre, anulación de registros abiertos por error y panel de pendientes.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from frecuenciafetal.models import ControlGlobo, ControlSangrado, ControlSutura, RegistroParto
from obstetriciaunificador.models import AtencionParto

DOC = 'PEND-PP-1'
INGRESO = '900777'
URL = '/fetal/api/registros/'
SIN_DINAMICA = mock.patch('obstetriciaunificador.ingresos.resumen_ingresos', side_effect=Exception('sin Dinámica'))


def _estado(horas_desde_egreso):
    """Respuesta simulada de consultar_estado_ingreso."""
    # Dinámica entrega la hora local de Colombia, sin zona horaria.
    egreso = None if horas_desde_egreso is None else (timezone.localtime() - timedelta(hours=horas_desde_egreso)).replace(tzinfo=None)
    return {'activo': egreso is None, 'fecha_egreso': egreso, 'tiene_estancias': True, 'anulado': False, 'tipo': 'hospitalizacion'}


@SIN_DINAMICA
class RequisitosYAnulacionTests(TestCase):
    def setUp(self):
        self.enfermera = User.objects.create_user('enf', password='x', first_name='ENFERMERA', last_name='UNO')
        self.admin = User.objects.create_superuser('admin', password='x')
        self.api = APIClient()
        self.api.force_authenticate(self.enfermera)
        self.atencion = AtencionParto.objects.create(paciente=DOC, numero_ingreso=INGRESO)
        self.registro = RegistroParto.objects.create(
            atencion=self.atencion, nombre_paciente='PACIENTE PRUEBA', identificacion=DOC, edad_gestacional=38,
        )
        # Ingreso en curso: el bloqueo por egreso no aplica.
        p = mock.patch('frecuenciafetal.sala_partos_db.consultar_estado_ingreso', return_value=_estado(None))
        p.start()
        self.addCleanup(p.stop)

    def _req(self):
        return self.api.get(f'{URL}{self.registro.pk}/requisitos-cierre/').json()

    def test_requisitos_de_un_registro_vacio(self, _):
        data = self._req()
        faltan = [q['texto'] for q in data['requisitos'] if not q['ok']]
        self.assertEqual(data['completos'], 0)
        self.assertTrue(any('acompañante' in t for t in faltan))
        self.assertTrue(any('Hora de parto' in t for t in faltan))
        self.assertTrue(any('Huella plantar' in t for t in faltan))
        self.assertEqual(sum('control de las 6 horas' in t for t in faltan), 3)
        self.assertTrue(data['puede_anular'])

    def test_los_controles_de_6_horas_cuentan(self, _):
        hora = timezone.localtime().time()
        ControlSangrado.objects.create(registro=self.registro, minuto_control=360, hora=hora, cc=50)
        ControlGlobo.objects.create(registro=self.registro, minuto_control=360, hora=hora, estado='NORMAL')
        ControlSutura.objects.create(registro=self.registro, minuto_control=360, hora=hora, estado='EN_CIRUGIA')
        faltan = [q['texto'] for q in self._req()['requisitos'] if not q['ok']]
        self.assertFalse(any('control de las 6 horas' in t for t in faltan))

    def test_la_enfermera_anula_un_registro_vacio_y_se_puede_abrir_otro(self, _):
        r = self.api.post(f'{URL}{self.registro.pk}/anular/', {'motivo': 'SIN_PARTO'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.registro.refresh_from_db()
        self.assertIsNotNone(self.registro.anulado_en)
        self.assertEqual(self.registro.motivo_anulacion, 'SIN_PARTO')
        self.assertTrue(self.registro.cambios.filter(accion='eliminacion', detalle__startswith='Anuló').exists())
        # Ya no se abre al volver a la paciente, y un guardado nuevo crea otro registro.
        self.assertFalse(self.api.get(f'{URL}por-atencion/', {'atencion': self.atencion.id, 'documento': DOC}).data['encontrado'])
        nuevo = self.api.post(URL, {'nombre_paciente': 'PACIENTE PRUEBA', 'identificacion': DOC, 'edad_gestacional': 38,
                                    'atencion': self.atencion.id}, format='json')
        self.assertIn(nuevo.status_code, (200, 201), nuevo.data)
        self.assertNotEqual(str(nuevo.data['id']), str(self.registro.pk))

    def test_un_registro_anulado_no_se_puede_modificar(self, _):
        self.api.post(f'{URL}{self.registro.pk}/anular/', {'motivo': 'POR_ERROR'}, format='json')
        r = self.api.patch(f'{URL}{self.registro.pk}/', {'nombre_acompanante': 'X'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_con_datos_clinicos_solo_el_administrador_anula(self, _):
        self.registro.hora_parto = timezone.localtime().time()
        self.registro.save()
        r = self.api.post(f'{URL}{self.registro.pk}/anular/', {'motivo': 'POR_ERROR'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(self._req()['puede_anular'])
        admin = APIClient()
        admin.force_authenticate(self.admin)
        r = admin.post(f'{URL}{self.registro.pk}/anular/', {'motivo': 'OTRO', 'detalle': 'Paciente equivocada'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_un_registro_anulado_nunca_se_cierra_ni_se_envia(self, _):
        from frecuenciafetal.views import _intentar_cerrar_registro
        RegistroParto.objects.filter(pk=self.registro.pk).update(anulado_en=timezone.now())
        instancia = RegistroParto.objects.get(pk=self.registro.pk)
        instancia.anulado_en = None  # la pantalla todavía no sabe que se anuló
        with mock.patch('frecuenciafetal.views._faltantes_control_6h', return_value=[]),              mock.patch('frecuenciafetal.views.pendientes_datos_cierre', return_value=[]),              mock.patch('frecuenciafetal.views.nombre_profesional_sesion', return_value='ENFERMERA UNO'):
            _intentar_cerrar_registro(instancia, mock.Mock())
        self.assertIsNone(RegistroParto.objects.get(pk=self.registro.pk).completado_en)
        self.assertFalse(getattr(instancia, '_cerrado_ahora', False))  # sin _cerrado_ahora no se envía a la NAS

    def test_no_se_anula_si_otra_pantalla_lo_acaba_de_cerrar(self, _):
        from frecuenciafetal.views import RegistroPartoViewSet
        original = RegistroPartoViewSet.get_object
        def cerrar_justo_antes(vista):
            obj = original(vista)
            RegistroParto.objects.filter(pk=obj.pk).update(completado_en=timezone.now())
            return obj
        with mock.patch.object(RegistroPartoViewSet, 'get_object', cerrar_justo_antes):
            r = self.api.post(f'{URL}{self.registro.pk}/anular/', {'motivo': 'POR_ERROR'}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertIsNone(RegistroParto.objects.get(pk=self.registro.pk).anulado_en)

    def test_validaciones(self, _):
        self.assertEqual(self.api.post(f'{URL}{self.registro.pk}/anular/', {}, format='json').status_code, 400)
        self.assertEqual(self.api.post(f'{URL}{self.registro.pk}/anular/', {'motivo': 'OTRO'}, format='json').status_code, 400)
        self.registro.completado_en = timezone.now()
        self.registro.save()
        self.assertEqual(self.api.post(f'{URL}{self.registro.pk}/anular/', {'motivo': 'POR_ERROR'}, format='json').status_code, 400)


class PanelPendientesTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.usuario = User.objects.create_user('enf', password='x')
        self.client.force_login(self.usuario)

        hora = timezone.localtime().time()

        def registro(doc, ingreso, con_datos=True, **extra):
            at = AtencionParto.objects.create(paciente=doc, numero_ingreso=ingreso)
            datos = {'hora_parto': hora, 'tipo_parto': 'VAGINAL'} if con_datos else {}
            return RegistroParto.objects.create(atencion=at, nombre_paciente=f'PACIENTE {doc}', identificacion=doc,
                                                edad_gestacional=38, **datos, **extra)
        self.urgente = registro('D1', '1001')          # egresó hace 2 h
        self.en_atencion = registro('D2', '1002')      # sigue hospitalizada
        self.bloqueado = registro('D3', '1003')        # egresó hace 3 días
        registro('D4', '1004', completado_en=timezone.now())                       # cerrado: no aparece
        registro('D5', '1005', anulado_en=timezone.now(), motivo_anulacion='POR_ERROR')  # anulado: no aparece
        registro('D6', '1006', con_datos=False)                                    # vacío: no aparece
        estados = {'1001': _estado(2), '1002': _estado(None), '1003': _estado(72), '1006': _estado(2)}
        p = mock.patch('frecuenciafetal.sala_partos_db.consultar_estado_ingreso', side_effect=lambda n: estados.get(n))
        p.start()
        self.addCleanup(p.stop)

    def test_lista_pendientes_en_orden_de_urgencia(self):
        from frecuenciafetal.pendientes import registros_pendientes
        filas = registros_pendientes()
        self.assertEqual([f['cedula'] for f in filas], ['D1', 'D2', 'D3'])
        self.assertEqual([f['situacion'] for f in filas], ['urgente', 'en_atencion', 'bloqueado'])
        # Egresó hace 2 h: quedan 21 h y algo de las 24 (se muestra la hora entera, hacia abajo).
        self.assertIn('Quedan 21 h', filas[0]['situacion_texto'])
        self.assertNotIn('D6', [f['cedula'] for f in filas])  # los vacíos no se listan

    def test_pagina_y_contador(self):
        r = self.client.get('/fetal/pendientes/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'PACIENTE D1')
        self.assertNotContains(r, 'PACIENTE D4')
        self.assertNotContains(r, 'PACIENTE D5')
        self.assertNotContains(r, 'PACIENTE D6')
        self.assertEqual(self.client.get('/fetal/api/pendientes-resumen/').json()['urgentes'], 1)

    def test_recuadros_y_contador_coinciden_con_las_tarjetas(self):
        from frecuenciafetal.models import RegistroParto as RP
        sin_ingreso = RP.objects.create(nombre_paciente='PACIENTE D7', identificacion='D7', edad_gestacional=38,
                                        hora_parto=timezone.localtime().time())  # sin atención: sin dato de Dinámica
        self.client.force_login(User.objects.create_superuser('admin', password='x'))  # el admin ve también los grises
        r = self.client.get('/fetal/pendientes/')
        ctx = r.context
        tarjetas = len(ctx['filas'])
        self.assertEqual(tarjetas, 4)
        self.assertEqual(ctx['urgentes'] + ctx['en_atencion'] + ctx['bloqueados'] + ctx['listos'] + ctx['sin_dato'], tarjetas)
        self.assertEqual(ctx['sin_dato'], 1)
        self.assertEqual(self.client.get('/fetal/api/pendientes-resumen/').json()['total'], tarjetas)
        sin_ingreso.delete()

    def test_resumen_trae_el_detalle_de_las_urgentes(self):
        d = self.client.get('/fetal/api/pendientes-resumen/').json()
        self.assertEqual(d['urgentes'], 1)
        self.assertEqual([p['cedula'] for p in d['detalle_urgentes']], ['D1'])
        self.assertEqual(d['detalle_urgentes'][0]['horas_restantes'], 21)
        self.assertIn('ingreso=1001', d['detalle_urgentes'][0]['url'])
        # Cronómetro: egresó hace 2 h -> quedan unas 22 h (en segundos, calculado al responder).
        seg = d['detalle_urgentes'][0]['segundos_restantes']
        self.assertTrue(22 * 3600 - 120 <= seg <= 22 * 3600, seg)
        self.assertTrue(d['detalle_urgentes'][0]['egreso_texto'])

    def test_alerta_del_encabezado_presente_para_el_personal(self):
        html = self.client.get('/fetal/pendientes/').content.decode()
        self.assertIn('id="posparto-campana-btn"', html)

    def test_la_enfermera_no_ve_los_de_mas_de_24_horas(self):
        r = self.client.get('/fetal/pendientes/')  # sesión de enfermería (no administrador)
        self.assertNotContains(r, 'PACIENTE D3')
        self.assertNotContains(r, 'Pasaron 24 h · solo administrador')
        self.assertContains(r, 'PACIENTE D1')
        self.assertEqual(self.client.get('/fetal/api/pendientes-resumen/').json()['total'], 2)
        self.client.force_login(User.objects.create_superuser('admin2', password='x'))
        r = self.client.get('/fetal/pendientes/')
        self.assertContains(r, 'PACIENTE D3')
        self.assertContains(r, 'Pasaron 24 h · solo administrador')
        self.assertEqual(self.client.get('/fetal/api/pendientes-resumen/').json()['total'], 3)

    def test_el_menu_cuenta_solo_los_completos(self):
        import frecuenciafetal.views as V
        real = V.requisitos_cierre
        completo = self.en_atencion.pk
        def req(r):  # D2 (en atención) con todo completo: tarjeta verde
            q = real(r)
            return [dict(x, ok=True) for x in q] if r.pk == completo else q
        with mock.patch.object(V, 'requisitos_cierre', req):
            d = self.client.get('/fetal/api/pendientes-resumen/').json()
            ctx = self.client.get('/fetal/pendientes/').context
        self.assertEqual(d['completos'], 1)
        self.assertEqual(d['completos'], ctx['listos'])
        self.assertEqual(d['urgentes'], 1)  # la alerta del encabezado sigue con las egresadas

    def test_el_selector_de_ingresos_no_cuenta_anulados(self):
        from obstetriciaunificador.ingresos import asignar_registros_posparto
        ingresos = [{'numero': '1005', 'fecha_ingreso': None, 'fecha_egreso': None, 'tipo': 'hospitalizacion',
                     'anulado': False, 'fuente': 'app', 'clinico': True, 'fin': None, 'en_curso': False}]
        self.assertEqual(asignar_registros_posparto('D5', ingresos), {})


@SIN_DINAMICA
class GuardarCompletoTests(TestCase):
    """2026-10-21: un registro completo se guarda desde el panel; mismo plazo de 24 h tras el egreso."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.enfermera = User.objects.create_user('enf', password='x', first_name='ENFERMERA', last_name='UNO')
        self.api = APIClient()
        self.api.force_authenticate(self.enfermera)
        atencion = AtencionParto.objects.create(paciente=DOC, numero_ingreso=INGRESO)
        self.registro = RegistroParto.objects.create(
            atencion=atencion, nombre_paciente='PACIENTE PRUEBA', identificacion=DOC, edad_gestacional=38,
            hora_parto=timezone.localtime().time(), tipo_parto='VAGINAL', nombre_acompanante='ACOMPAÑANTE',
        )
        # Abierto durante el ingreso (antes del egreso).
        RegistroParto.objects.filter(pk=self.registro.pk).update(created_at=timezone.now() - timedelta(days=4))
        self.horas_egreso = 72
        for p in (mock.patch('frecuenciafetal.sala_partos_db.consultar_estado_ingreso',
                             side_effect=lambda n: _estado(self.horas_egreso)),
                  mock.patch('frecuenciafetal.views._faltantes_control_6h', return_value=[]),
                  mock.patch('frecuenciafetal.views.pendientes_datos_cierre', return_value=[]),
                  mock.patch('obstetriciaunificador.repositorio.resumen_envio',
                             return_value={'ok': True, 'mensaje': 'Formato guardado en la NAS'})):
            p.start()
            self.addCleanup(p.stop)

    def _completo(self):
        import frecuenciafetal.views as V
        real = V.requisitos_cierre
        return mock.patch.object(V, 'requisitos_cierre', lambda r: [dict(x, ok=True) for x in real(r)])

    @mock.patch('obstetriciaunificador.repositorio.enviar_control_posparto')
    def test_dentro_de_las_24_h_la_enfermera_lo_guarda(self, enviar, _):
        self.horas_egreso = 5
        with self._completo():
            r = self.api.post(f'{URL}{self.registro.pk}/cerrar/', {}, format='json')
            self.assertEqual(r.status_code, 200, r.data)
            enviar.assert_called_once()
            # Volver a pulsarlo no envía otra vez.
            self.assertEqual(self.api.post(f'{URL}{self.registro.pk}/cerrar/', {}, format='json').data['mensaje'],
                             'El registro ya estaba cerrado.')
        enviar.assert_called_once()

    @mock.patch('obstetriciaunificador.repositorio.enviar_control_posparto')
    def test_pasadas_24_h_solo_el_administrador_lo_guarda(self, enviar, _):
        with self._completo():
            self.assertEqual(self.api.post(f'{URL}{self.registro.pk}/cerrar/', {}, format='json').status_code, 403)
            enviar.assert_not_called()
            admin = APIClient()
            admin.force_authenticate(User.objects.create_superuser('admin', password='x'))
            r = admin.post(f'{URL}{self.registro.pk}/cerrar/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        enviar.assert_called_once()

    def test_pasadas_24_h_no_se_pueden_cambiar_datos(self, _):
        r = self.api.patch(f'{URL}{self.registro.pk}/', {'nombre_acompanante': 'OTRO'}, format='json')
        self.assertEqual(r.status_code, 403)

    @mock.patch('obstetriciaunificador.repositorio.enviar_control_posparto')
    def test_un_incompleto_no_se_cierra(self, enviar, _):
        self.horas_egreso = 5
        r = self.api.post(f'{URL}{self.registro.pk}/cerrar/', {}, format='json')  # sin RN ni huella
        self.assertEqual(r.status_code, 400)
        enviar.assert_not_called()

    def test_categoria_y_alerta_del_encabezado(self, _):
        from frecuenciafetal.pendientes import registros_pendientes, resumen_pendientes
        from django.core.cache import cache
        with self._completo():
            self.assertEqual(registros_pendientes()[0]['categoria'], 'bloqueado')  # pasadas 24 h: gris
            self.horas_egreso = 5
            cache.clear()
            self.assertEqual(registros_pendientes()[0]['categoria'], 'completo')   # dentro de 24 h: verde
            cache.clear()
            resumen = resumen_pendientes()
        self.assertEqual(resumen['urgentes'], 1)            # también en la alerta del cronómetro
        self.assertTrue(resumen['detalle_urgentes'][0]['completo'])
        self.assertEqual(resumen['completos'], 1)           # y en el aviso verde del menú


@SIN_DINAMICA
class CedulaDeOtroIngresoTests(TestCase):
    """2026-10-22 (caso real): registro con la cédula de otra paciente. Al
    abrirlo, la pantalla cargaba a la dueña de esa cédula y creaba registros
    vacíos pegados al ingreso equivocado."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.admin = User.objects.create_superuser('admin', password='x')
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        # El ingreso 1827594 es de ANGIE (1004439565); el registro quedó con la cédula de VALERYN.
        self.atencion = AtencionParto.objects.create(paciente='1080831722', numero_ingreso='1827594')
        self.malo = RegistroParto.objects.create(atencion=self.atencion, nombre_paciente='ANGIE', identificacion='1080831722',
                                                 edad_gestacional=38, hora_parto=timezone.localtime().time())
        info = {'cedula': '1004439565', 'nombre': 'ANGIE MARCELA URRESTI GARCIA', 'fecha_egreso': None, 'anulado': False}
        for p in (mock.patch('frecuenciafetal.sala_partos_db.consultar_paciente_de_ingreso',
                             side_effect=lambda n: info if n == '1827594' else {}),
                  mock.patch('frecuenciafetal.sala_partos_db.consultar_estado_ingreso', return_value=_estado(72))):
            p.start()
            self.addCleanup(p.stop)

    def test_no_crea_un_registro_en_el_ingreso_de_otra_paciente(self, _):
        antes = RegistroParto.objects.count()
        RegistroParto.objects.filter(pk=self.malo.pk).update(anulado_en=timezone.now())  # que no lo encuentre como existente
        r = self.api.post(URL, {'nombre_paciente': 'VALERYN', 'identificacion': '1080831722', 'edad_gestacional': 36,
                                'atencion': self.atencion.id}, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn('pertenece a otra paciente', r.data['detail'])
        self.assertEqual(RegistroParto.objects.count(), antes)

    def test_la_cedula_correcta_si_crea(self, _):
        atencion = AtencionParto.objects.create(paciente='1004439565', numero_ingreso='1827594')
        r = self.api.post(URL, {'nombre_paciente': 'ANGIE', 'identificacion': '1004439565', 'edad_gestacional': 38,
                                'atencion': atencion.id}, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)

    def test_el_panel_avisa_y_no_ofrece_abrir(self, _):
        from frecuenciafetal.pendientes import registros_pendientes
        fila = registros_pendientes()[0]
        self.assertIn('pertenece a otra paciente', fila['cedula_no_coincide'])
        self.client.force_login(self.admin)
        r = self.client.get('/fetal/pendientes/')
        self.assertContains(r, 'quedó con la cédula equivocada')
        self.assertNotContains(r, 'Abrir registro</a>')
