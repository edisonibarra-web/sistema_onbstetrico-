"""
2026-10-20: Consulta histórica de pacientes egresadas (obstetriciaunificador/historico.py).
Dinámica y la NAS se simulan: las pruebas no salen de la máquina.
"""
from datetime import datetime
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.test import TestCase

from obstetriciaunificador.models import AccesoDocumentoRepositorio, CambioPermisoHistorico, ConsultaHistorico

CEDULA = '1086578557'
EGRESADO = '1830660'
EN_CURSO = '1834370'
DE_OTRA = '1700000'

INGRESOS_PACIENTE = [
    {'numero_ingreso': EN_CURSO, 'fecha_ingreso': datetime(2026, 10, 20, 8), 'fecha_egreso': None,
     'anulado': False, 'tipo': 'hospitalizacion', 'estancia_abierta': True},
    {'numero_ingreso': EGRESADO, 'fecha_ingreso': datetime(2026, 10, 13, 12), 'fecha_egreso': datetime(2026, 10, 16, 11),
     'anulado': False, 'tipo': 'hospitalizacion', 'estancia_abierta': False},
    {'numero_ingreso': '1820000', 'fecha_ingreso': datetime(2026, 9, 1, 9), 'fecha_egreso': datetime(2026, 9, 2, 9),
     'anulado': True, 'tipo': 'urgencias', 'estancia_abierta': False},
    {'numero_ingreso': '1810000', 'fecha_ingreso': datetime(2026, 8, 1, 9), 'fecha_egreso': None,
     'anulado': False, 'tipo': 'consulta', 'estancia_abierta': False},
]


def _paciente_de_ingreso(numero):
    base = {'cedula': CEDULA, 'nombre': 'NAYELIN PRUEBA', 'fecha_ingreso': datetime(2026, 10, 13, 12),
            'anulado': False, 'tipo': 'hospitalizacion'}
    if numero == EGRESADO:
        return {**base, 'fecha_egreso': datetime(2026, 10, 16, 11)}
    if numero == EN_CURSO:
        return {**base, 'fecha_egreso': None}
    if numero == DE_OTRA:
        return {**base, 'cedula': '999', 'fecha_egreso': datetime(2026, 1, 2, 9)}
    return {}


ARCHIVOS_NAS = [
    f'otros_triaje_obstetrico_{CEDULA}_1.pdf',
    f'otros_escala_meows_{CEDULA}_1.pdf',
    f'otros_control_posparto_inmediato_{CEDULA}_1.pdf',
    f'otros_escala_downton_{CEDULA}_535.pdf',      # de otro aplicativo
    f'informacion-egreso_{CEDULA}.pdf',            # de otro aplicativo
]

DINAMICA = [
    mock.patch('frecuenciafetal.sala_partos_db.consultar_ingresos_paciente', return_value=INGRESOS_PACIENTE),
    mock.patch('frecuenciafetal.sala_partos_db.consultar_nombre_paciente', return_value=('NAYELIN', 'PRUEBA')),
    mock.patch('frecuenciafetal.sala_partos_db.consultar_paciente_de_ingreso', side_effect=_paciente_de_ingreso),
]


class ConsultaHistoricaTests(TestCase):
    def setUp(self):
        for p in DINAMICA:
            p.start()
            self.addCleanup(p.stop)
        self.autorizada = User.objects.create_user('autorizada', password='x')
        self.autorizada.user_permissions.add(Permission.objects.get(codename='consultar_historico'))
        self.normal = User.objects.create_user('normal', password='x')
        self.admin = User.objects.create_superuser('admin', password='x')
        self.staff = User.objects.create_user('staff', password='x', is_staff=True)

    def _buscar(self, tipo, q):
        return self.client.get('/atencion/api/historico/buscar/', {'tipo': tipo, 'q': q}).json()

    # --- Permisos -------------------------------------------------------
    def test_sin_permiso_no_entra(self):
        self.client.force_login(self.staff)  # is_staff sin el permiso tampoco entra
        self.assertEqual(self.client.get('/atencion/historico/').status_code, 403)
        self.client.force_login(self.normal)
        self.assertEqual(self.client.get('/atencion/historico/').status_code, 403)
        self.assertEqual(self.client.get('/atencion/api/historico/buscar/', {'tipo': 'cedula', 'q': CEDULA}).status_code, 403)
        self.assertFalse(ConsultaHistorico.objects.exists())

    def test_con_permiso_o_admin_entra(self):
        for usuario in (self.autorizada, self.admin):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get('/atencion/historico/').status_code, 200)

    def test_menu_solo_para_autorizados(self):
        self.client.force_login(self.autorizada)
        self.assertContains(self.client.get('/atencion/historico/'), 'href="/atencion/historico/"')
        self.client.force_login(self.normal)
        self.assertNotContains(self.client.get('/atencion/manual/'), 'href="/atencion/historico/"')

    # --- Búsqueda ---------------------------------------------------------
    def test_por_cedula_solo_ingresos_egresados(self):
        self.client.force_login(self.autorizada)
        data = self._buscar('cedula', CEDULA)
        self.assertTrue(data['ok'])
        self.assertEqual([i['numero'] for i in data['ingresos']], [EGRESADO])  # sin en curso, anulado ni consulta
        self.assertEqual(data['nombre'], 'NAYELIN PRUEBA')
        consulta = ConsultaHistorico.objects.get()
        self.assertEqual((consulta.cedula, consulta.ingresos_encontrados, consulta.username), (CEDULA, 1, 'autorizada'))

    def test_por_ingreso_egresado(self):
        self.client.force_login(self.autorizada)
        data = self._buscar('ingreso', EGRESADO)
        self.assertTrue(data['ok'])
        self.assertEqual(data['cedula'], CEDULA)

    def test_por_ingreso_en_curso_o_inexistente_no_muestra(self):
        self.client.force_login(self.autorizada)
        self.assertIn('todavía no tiene egreso', self._buscar('ingreso', EN_CURSO)['mensaje'])
        self.assertIn('No existe', self._buscar('ingreso', '1234567')['mensaje'])
        self.assertEqual(ConsultaHistorico.objects.count(), 2)  # también quedan las búsquedas sin resultado

    def test_dinamica_caida(self):
        self.client.force_login(self.autorizada)
        with mock.patch('frecuenciafetal.sala_partos_db.consultar_ingresos_paciente', return_value=None):
            self.assertIn('Dinámica no responde', self._buscar('cedula', CEDULA)['mensaje'])

    # --- Documentos -------------------------------------------------------
    @mock.patch('obstetriciaunificador.historico.listar_documentos_ingreso', return_value=ARCHIVOS_NAS)
    def test_documentos_solo_de_la_app(self, _):
        self.client.force_login(self.autorizada)
        data = self.client.get('/atencion/api/historico/documentos/', {'doc': CEDULA, 'ingreso': EGRESADO}).json()
        self.assertEqual([d['formato'] for d in data['documentos']], ['triaje', 'meows', 'control_posparto'])

    @mock.patch('obstetriciaunificador.historico.listar_documentos_ingreso', return_value=ARCHIVOS_NAS)
    def test_documentos_de_ingreso_en_curso_o_de_otra_paciente(self, _):
        self.client.force_login(self.autorizada)
        for ingreso in (EN_CURSO, DE_OTRA):
            r = self.client.get('/atencion/api/historico/documentos/', {'doc': CEDULA, 'ingreso': ingreso})
            self.assertEqual(r.status_code, 404)

    @mock.patch('obstetriciaunificador.repositorio.leer_documento_ingreso', return_value=b'%PDF-1.4 prueba')
    def test_abrir_documento_queda_registrado(self, leer):
        self.client.force_login(self.autorizada)
        archivo = f'otros_control_posparto_inmediato_{CEDULA}_1.pdf'
        r = self.client.get('/atencion/api/historico/documento/', {'doc': CEDULA, 'ingreso': EGRESADO, 'archivo': archivo})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b'%PDF-1.4 prueba')
        self.assertTrue(AccesoDocumentoRepositorio.objects.filter(nombre_archivo=archivo, numero_ingreso=EGRESADO).exists())

    @mock.patch('obstetriciaunificador.repositorio.leer_documento_ingreso', return_value=b'%PDF')
    def test_no_abre_documentos_de_otros_aplicativos_ni_ingresos_en_curso(self, leer):
        self.client.force_login(self.autorizada)
        otro = self.client.get('/atencion/api/historico/documento/',
                               {'doc': CEDULA, 'ingreso': EGRESADO, 'archivo': f'informacion-egreso_{CEDULA}.pdf'})
        en_curso = self.client.get('/atencion/api/historico/documento/',
                                   {'doc': CEDULA, 'ingreso': EN_CURSO, 'archivo': f'otros_escala_meows_{CEDULA}_1.pdf'})
        self.assertEqual((otro.status_code, en_curso.status_code), (404, 404))
        leer.assert_not_called()


USUARIOS_DINAMICA = {
    'RDELGADO': {'usuario': 'RDELGADO', 'nombre': 'ROSA ERNESTINA DELGADO', 'activo': True},
    'INACTIVA': {'usuario': 'INACTIVA', 'nombre': 'USUARIA INACTIVA', 'activo': False},
}


@mock.patch('frecuenciafetal.sala_partos_db.consultar_usuario_dinamica',
            side_effect=lambda u: USUARIOS_DINAMICA.get(u, {}))
class PermisosHistoricoTests(TestCase):
    URL = '/atencion/api/historico/permisos/'

    def setUp(self):
        self.admin = User.objects.create_superuser('admin', password='x')
        self.autorizada = User.objects.create_user('autorizada', password='x')
        self.autorizada.user_permissions.add(Permission.objects.get(codename='consultar_historico'))

    def _post(self, accion, usuario):
        return self.client.post(self.URL, {'accion': accion, 'usuario': usuario}, content_type='application/json')

    def test_solo_el_superusuario_gestiona(self, _):
        self.client.force_login(self.autorizada)  # puede consultar, pero no dar permisos
        self.assertEqual(self.client.get(self.URL).status_code, 403)
        self.assertEqual(self._post('autorizar', 'RDELGADO').status_code, 403)
        self.assertNotContains(self.client.get('/atencion/historico/'), 'id="perm-seccion"')

    def test_verificar_muestra_nombre_de_dinamica(self, _):
        self.client.force_login(self.admin)
        data = self.client.get(self.URL + 'verificar/', {'usuario': 'RDELGADO'}).json()
        self.assertEqual((data['nombre'], data['activo'], data['autorizado']), ('ROSA ERNESTINA DELGADO', True, False))
        self.assertIn('no existe', self.client.get(self.URL + 'verificar/', {'usuario': 'NADIE'}).json()['mensaje'])

    def test_autorizar_a_quien_nunca_entro_y_luego_quitar(self, _):
        self.client.force_login(self.admin)
        data = self._post('autorizar', 'RDELGADO').json()
        self.assertTrue(data['ok'])
        rosa = User.objects.get(username='RDELGADO')
        self.assertFalse(rosa.has_usable_password())  # sin clave local: entra solo por Dinámica
        self.assertTrue(rosa.has_perm('obstetricia.consultar_historico'))
        self.assertIn('RDELGADO', [u['username'] for u in data['usuarios']])

        self.assertTrue(self._post('quitar', 'RDELGADO').json()['ok'])
        rosa = User.objects.get(username='RDELGADO')
        self.assertFalse(rosa.has_perm('obstetricia.consultar_historico'))
        self.assertEqual(
            list(CambioPermisoHistorico.objects.order_by('creado_en').values_list('accion', 'username', 'realizado_por')),
            [('autorizar', 'RDELGADO', 'admin'), ('quitar', 'RDELGADO', 'admin')],
        )

    def test_no_autoriza_usuarios_inactivos_o_inexistentes(self, _):
        self.client.force_login(self.admin)
        self.assertIn('inactivo', self._post('autorizar', 'INACTIVA').json()['mensaje'])
        self.assertIn('no existe', self._post('autorizar', 'NADIE').json()['mensaje'])
        self.assertFalse(User.objects.filter(username__in=['INACTIVA', 'NADIE']).exists())
        self.assertFalse(CambioPermisoHistorico.objects.exists())

    def test_superusuario_ve_la_seccion(self, _):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/atencion/historico/'), 'id="perm-seccion"')


def _ingresos_simulados():
    from django.utils import timezone as tz
    from obstetriciaunificador.ingresos import _calcular_ventanas
    ingresos = [{
        'numero': EGRESADO, 'tipo': 'hospitalizacion', 'anulado': False, 'fuente': 'dinamica',
        'fecha_ingreso': tz.make_aware(datetime(2026, 10, 13, 12)),
        'fecha_egreso': tz.make_aware(datetime(2026, 10, 16, 11)),
    }]
    _calcular_ventanas(ingresos)
    return ingresos, True, ''


class AlertasHistoricoTests(TestCase):
    """Segunda entrega: lo que debería estar en la NAS y no está, con el motivo."""
    URL = '/atencion/api/historico/documentos/'

    def setUp(self):
        from django.utils import timezone as tz
        from frecuenciafetal.models import RegistroParto
        from obstetriciaunificador.models import AtencionParto

        for p in DINAMICA + [mock.patch('obstetriciaunificador.ingresos.ingresos_de_paciente',
                                        side_effect=lambda *a, **k: _ingresos_simulados())]:
            p.start()
            self.addCleanup(p.stop)
        self.admin = User.objects.create_superuser('admin', password='x')
        self.client.force_login(self.admin)
        atencion = AtencionParto.objects.create(paciente=CEDULA, numero_ingreso=EGRESADO)
        self.registro = RegistroParto.objects.create(
            atencion=atencion, nombre_paciente='NAYELIN PRUEBA', identificacion=CEDULA, edad_gestacional=38,
        )
        RegistroParto.objects.filter(pk=self.registro.pk).update(created_at=tz.make_aware(datetime(2026, 10, 14, 15)))

    def _revisar(self, archivos):
        with mock.patch('obstetriciaunificador.historico.listar_documentos_ingreso', return_value=archivos):
            return self.client.get(self.URL, {'doc': CEDULA, 'ingreso': EGRESADO}).json()

    def test_posparto_sin_cerrar_dice_que_falta(self):
        data = self._revisar([])
        self.assertEqual(len(data['alertas']), 1)
        alerta = data['alertas'][0]
        self.assertEqual(alerta['formato'], 'control_posparto')
        self.assertIn('nunca se cerró', alerta['mensaje'])
        self.assertTrue(any('acompañante' in d for d in alerta['detalle']))

    def test_posparto_cerrado_sin_pdf_en_la_nas(self):
        from django.utils import timezone as tz
        self.registro.completado_en = tz.now()
        self.registro.save()
        alerta = self._revisar([])['alertas'][0]
        self.assertIn('cerrado pero el documento no está', alerta['mensaje'])
        self.assertTrue(any(f'reenviar_control_posparto {CEDULA}' in d for d in alerta['detalle']))

    def test_posparto_cerrado_y_en_la_nas_no_alerta(self):
        from django.utils import timezone as tz
        from obstetriciaunificador.models import DocumentoRepositorio
        self.registro.completado_en = tz.now()
        self.registro.save()
        nombre = f'otros_control_posparto_inmediato_{CEDULA}_1.pdf'
        DocumentoRepositorio.objects.create(
            cedula=CEDULA, numero_ingreso=EGRESADO, formato='control_posparto', referencia=str(self.registro.pk),
            modo='nas', estado=DocumentoRepositorio.ESTADO_ENVIADO, nombre_archivo=nombre,
        )
        data = self._revisar([nombre])
        self.assertEqual(data['alertas'], [])
        self.assertEqual([d['nombre'] for d in data['documentos']], [nombre])

    def test_si_fallan_las_alertas_los_documentos_se_ven_igual(self):
        nombre = f'otros_escala_meows_{CEDULA}_1.pdf'
        with mock.patch('obstetriciaunificador.historico.alertas_de_faltantes', side_effect=RuntimeError('x')):
            data = self._revisar([nombre])
        self.assertTrue(data['ok'])
        self.assertEqual([d['nombre'] for d in data['documentos']], [nombre])
        self.assertEqual(data['alertas'][0]['titulo'], 'Revisión incompleta')


class IpClienteTests(TestCase):
    def test_ip_real_solo_detras_de_iis(self):
        from django.test import RequestFactory
        from sistema_obstetrico.auth_utils import ip_cliente
        rf = RequestFactory()
        detras_de_iis = rf.get('/', REMOTE_ADDR='127.0.0.1', HTTP_X_FORWARDED_FOR='172.20.5.33, 10.0.0.1')
        directo = rf.get('/', REMOTE_ADDR='172.20.9.9', HTTP_X_FORWARDED_FOR='1.2.3.4')  # cabecera falseada
        sin_cabecera = rf.get('/', REMOTE_ADDR='127.0.0.1')
        self.assertEqual(ip_cliente(detras_de_iis), '172.20.5.33')
        self.assertEqual(ip_cliente(directo), '172.20.9.9')
        self.assertEqual(ip_cliente(sin_cabecera), '127.0.0.1')


def _con_permisos(username, *codenames):
    usuario = User.objects.create_user(username, password='x')
    for codename in codenames:
        usuario.user_permissions.add(Permission.objects.get(codename=codename))
    return usuario


class TiposDeAccesoTests(TestCase):
    """Enfermería: módulos clínicos + histórico. Archivo: solo histórico."""

    def setUp(self):
        self.archivo = _con_permisos('archivo', 'consultar_historico', 'solo_consulta_historica')
        self.enfermera = _con_permisos('enfermera', 'consultar_historico')

    def test_archivo_solo_entra_al_historico_y_al_manual(self):
        self.client.force_login(self.archivo)
        self.assertEqual(self.client.get('/atencion/historico/').status_code, 200)
        self.assertEqual(self.client.get('/atencion/manual/').status_code, 200)
        for ruta in ('/atencion/sala-de-partos/', '/atencion/', '/meows/', '/fetal/', '/parto/', '/admin/'):
            r = self.client.get(ruta)
            self.assertEqual((r.status_code, r['Location']), (302, '/atencion/historico/'), ruta)

    def test_archivo_no_puede_usar_apis_clinicas(self):
        self.client.force_login(self.archivo)
        for ruta in ('/meows/api/alertas-pendientes/', '/fetal/api/registros/', '/atencion/api/ingresos/'):
            r = self.client.get(ruta)
            self.assertEqual(r.status_code, 403, ruta)
            self.assertIn('solo tiene acceso a la consulta histórica', r.json()['mensaje'])

    def test_archivo_no_ve_menu_clinico_ni_campanas(self):
        self.client.force_login(self.archivo)
        html = self.client.get('/atencion/historico/').content.decode()
        self.assertIn('href="/atencion/historico/"', html)
        for oculto in ('link-sala-partos-plain', 'sala-de-partos/?tab=triaje', 'id="meows-campana-btn"',
                       'id="meows-campana-triaje-btn"', 'id="nas-campana-btn"', 'id="posparto-campana-btn"',
                       'sidebar-pendientes-link'):
            self.assertNotIn(oculto, html, oculto)
        self.assertIn('window.SOLO_HISTORICO = true', html)

    def test_enfermera_ve_todo(self):
        self.client.force_login(self.enfermera)
        html = self.client.get('/atencion/sala-de-partos/').content.decode()
        self.assertIn('href="/atencion/historico/"', html)
        self.assertIn('sala-de-partos/?tab=triaje', html)
        self.assertIn('id="meows-campana-btn"', html)
        self.assertIn('window.SOLO_HISTORICO = false', html)

    def test_superusuario_nunca_queda_restringido(self):
        admin = User.objects.create_superuser('admin', password='x')
        admin.user_permissions.add(Permission.objects.get(codename='solo_consulta_historica'))
        self.client.force_login(admin)
        self.assertEqual(self.client.get('/atencion/sala-de-partos/').status_code, 200)


@mock.patch('frecuenciafetal.sala_partos_db.consultar_usuario_dinamica',
            side_effect=lambda u: USUARIOS_DINAMICA.get(u, {}))
class GestionTiposDeAccesoTests(TestCase):
    URL = '/atencion/api/historico/permisos/'

    def setUp(self):
        self.client.force_login(User.objects.create_superuser('admin', password='x'))

    def _autorizar(self, acceso):
        return self.client.post(self.URL, {'accion': 'autorizar', 'usuario': 'RDELGADO', 'acceso': acceso},
                                content_type='application/json').json()

    def test_dar_solo_historico_cambiar_a_completo_y_quitar(self, _):
        from obstetriciaunificador.historico import es_solo_historico
        data = self._autorizar('solo_historico')
        self.assertTrue(data['ok'])
        self.assertEqual(data['usuarios'][0]['acceso'], 'solo_historico')
        self.assertTrue(es_solo_historico(User.objects.get(username='RDELGADO')))

        self.assertIn('ya tiene el acceso', self._autorizar('solo_historico')['mensaje'])

        data = self._autorizar('completo')
        self.assertEqual(data['usuarios'][0]['acceso'], 'completo')
        rosa = User.objects.get(username='RDELGADO')
        self.assertFalse(es_solo_historico(rosa))
        self.assertTrue(rosa.has_perm('obstetricia.consultar_historico'))

        self.client.post(self.URL, {'accion': 'quitar', 'usuario': 'RDELGADO'}, content_type='application/json')
        rosa = User.objects.get(username='RDELGADO')
        self.assertFalse(rosa.user_permissions.exists())
        self.assertEqual(
            list(CambioPermisoHistorico.objects.order_by('creado_en').values_list('accion', 'acceso')),
            [('autorizar', 'solo_historico'), ('cambiar', 'completo'), ('quitar', 'solo_clinicos')],
        )

    def test_verificar_informa_el_acceso_actual(self, _):
        self._autorizar('solo_historico')
        data = self.client.get(self.URL + 'verificar/', {'usuario': 'RDELGADO'}).json()
        self.assertEqual((data['autorizado'], data['acceso']), (True, 'solo_historico'))


class AdministradorLocalTests(TestCase):
    def test_verificar_un_administrador_no_consulta_dinamica(self):
        User.objects.create_superuser('admin', password='x')
        self.client.force_login(User.objects.get(username='admin'))
        with mock.patch('frecuenciafetal.sala_partos_db.consultar_usuario_dinamica') as dinamica:
            data = self.client.get('/atencion/api/historico/permisos/verificar/', {'usuario': 'ADMIN'}).json()
        self.assertFalse(data['ok'])
        self.assertIn('administrador del sistema', data['mensaje'])
        dinamica.assert_not_called()


class SinAccesoTests(TestCase):
    """Cuarto tipo: "Sin acceso a la aplicación"."""

    def setUp(self):
        self.bloqueada = _con_permisos('bloqueada', 'sin_acceso_aplicacion')

    def test_no_puede_iniciar_sesion(self):
        r = self.client.post('/login/', {'username': 'bloqueada', 'password': 'x'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'no tiene acceso a esta aplicación')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_sesion_abierta_se_cierra_en_el_siguiente_clic(self):
        self.client.force_login(self.bloqueada)
        r = self.client.get('/atencion/manual/')
        self.assertEqual((r.status_code, r['Location']), (302, '/login/?sin_acceso=1'))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertContains(self.client.get('/login/?sin_acceso=1'), 'no tiene acceso a esta aplicación')

    def test_apis_responden_403(self):
        self.client.force_login(self.bloqueada)
        r = self.client.get('/meows/api/alertas-pendientes/')
        self.assertEqual(r.status_code, 403)
        self.assertIn('no tiene acceso', r.json()['mensaje'])

    def test_superusuario_nunca_queda_bloqueado(self):
        admin = User.objects.create_superuser('admin', password='x')
        admin.user_permissions.add(Permission.objects.get(codename='sin_acceso_aplicacion'))
        self.client.force_login(admin)
        self.assertEqual(self.client.get('/atencion/manual/').status_code, 200)


@mock.patch('frecuenciafetal.sala_partos_db.consultar_usuario_dinamica',
            side_effect=lambda u: USUARIOS_DINAMICA.get(u, {}))
class GestionSinAccesoTests(TestCase):
    URL = '/atencion/api/historico/permisos/'

    def setUp(self):
        self.client.force_login(User.objects.create_superuser('admin', password='x'))

    def _post(self, **datos):
        return self.client.post(self.URL, datos, content_type='application/json').json()

    def test_cuatro_tipos_de_acceso(self, _):
        from obstetriciaunificador.historico import es_sin_acceso
        self.assertTrue(self._post(accion='autorizar', usuario='RDELGADO', acceso='sin_acceso')['ok'])
        rosa = User.objects.get(username='RDELGADO')
        self.assertTrue(es_sin_acceso(rosa))
        self.assertFalse(rosa.has_perm('obstetricia.consultar_historico'))
        lista = self._post(accion='autorizar', usuario='RDELGADO', acceso='completo')['usuarios']
        self.assertEqual(lista[0]['acceso'], 'completo')
        self.assertFalse(es_sin_acceso(User.objects.get(username='RDELGADO')))
        data = self._post(accion='autorizar', usuario='RDELGADO', acceso='solo_clinicos')
        self.assertEqual(data['usuarios'], [])  # sin nada especial: no aparece en la lista
        self.assertFalse(User.objects.get(username='RDELGADO').user_permissions.exists())
        self.assertIn('ya tiene el acceso', self._post(accion='autorizar', usuario='RDELGADO', acceso='solo_clinicos')['mensaje'])

    def test_quitar_a_archivo_puede_dejarla_sin_acceso(self, _):
        from obstetriciaunificador.historico import es_sin_acceso
        self._post(accion='autorizar', usuario='RDELGADO', acceso='solo_historico')
        data = self._post(accion='quitar', usuario='RDELGADO', dejar='sin_acceso')
        self.assertTrue(data['ok'])
        self.assertEqual(data['usuarios'][0]['acceso'], 'sin_acceso')
        self.assertTrue(es_sin_acceso(User.objects.get(username='RDELGADO')))
        self.assertIn('Elija', self._post(accion='quitar', usuario='RDELGADO', dejar='otra_cosa')['mensaje'])

    def test_bloquear_a_un_usuario_inactivo_en_dinamica(self, _):
        self.assertTrue(self._post(accion='autorizar', usuario='INACTIVA', acceso='sin_acceso')['ok'])
        self.assertIn('inactivo', self._post(accion='autorizar', usuario='INACTIVA', acceso='completo')['mensaje'])


class BarraUnicaTests(TestCase):
    """Una sola barra: el número se busca como cédula y como ingreso."""
    CEDULA_ANTIGUA = EGRESADO  # una cédula antigua con los mismos dígitos que el ingreso

    def setUp(self):
        def ingresos(cedula):
            if cedula == CEDULA:
                return INGRESOS_PACIENTE
            if cedula == self.CEDULA_ANTIGUA and self.hay_cedula_antigua:
                return [INGRESOS_PACIENTE[1]]
            return []
        self.hay_cedula_antigua = False
        for p in [mock.patch('frecuenciafetal.sala_partos_db.consultar_ingresos_paciente', side_effect=ingresos),
                  mock.patch('frecuenciafetal.sala_partos_db.consultar_nombre_paciente', return_value=('NAYELIN', 'PRUEBA')),
                  mock.patch('frecuenciafetal.sala_partos_db.consultar_paciente_de_ingreso', side_effect=_paciente_de_ingreso)]:
            p.start()
            self.addCleanup(p.stop)
        self.client.force_login(User.objects.create_superuser('admin', password='x'))

    def _buscar(self, q):
        return self.client.get('/atencion/api/historico/buscar/', {'q': q}).json()

    def test_por_cedula_sin_elegir_tipo(self):
        data = self._buscar(CEDULA)
        self.assertEqual((data['cedula'], [i['numero'] for i in data['ingresos']]), (CEDULA, [EGRESADO]))

    def test_por_ingreso_sin_elegir_tipo(self):
        data = self._buscar(EGRESADO)
        self.assertEqual((data['cedula'], [i['numero'] for i in data['ingresos']]), (CEDULA, [EGRESADO]))

    def test_numero_que_es_ingreso_y_cedula_pide_elegir(self):
        self.hay_cedula_antigua = True
        data = self._buscar(EGRESADO)
        self.assertTrue(data['ambiguo'])
        self.assertEqual([o['tipo'] for o in data['opciones']], ['ingreso', 'cedula'])
        self.assertNotIn('ingresos', data)  # no muestra ninguna paciente hasta que se elija

    def test_mensajes_claros(self):
        self.assertIn('todavía no tiene egreso', self._buscar(EN_CURSO)['mensaje'])
        self.assertIn('No se encontró ninguna paciente ni ingreso', self._buscar('1234567')['mensaje'])
        self.assertIn('Escriba la cédula o el número de ingreso', self._buscar('')['mensaje'])


class OtrosDocumentosTests(TestCase):
    """2026-10-21: de los otros aplicativos solo se muestra lo aprobado (CLAP)."""
    CLAP = f'clap_clap_{CEDULA}_1.pdf'

    def setUp(self):
        for p in DINAMICA + [mock.patch('obstetriciaunificador.historico.listar_documentos_ingreso',
                                        return_value=ARCHIVOS_NAS + [self.CLAP])]:
            p.start()
            self.addCleanup(p.stop)
        self.client.force_login(User.objects.create_superuser('admin', password='x'))

    def test_clap_aparece_en_otros_documentos_y_lo_demas_no(self):
        data = self.client.get('/atencion/api/historico/documentos/', {'doc': CEDULA, 'ingreso': EGRESADO}).json()
        self.assertEqual(data['otros'], [{'nombre': self.CLAP, 'titulo': 'Historia clínica perinatal (CLAP)'}])
        self.assertNotIn(self.CLAP, [d['nombre'] for d in data['documentos']])

    @mock.patch('obstetriciaunificador.repositorio.leer_documento_ingreso', return_value=b'%PDF clap')
    def test_se_puede_abrir_el_clap(self, _):
        r = self.client.get('/atencion/api/historico/documento/', {'doc': CEDULA, 'ingreso': EGRESADO, 'archivo': self.CLAP})
        self.assertEqual(r.status_code, 200)
        r = self.client.get('/atencion/api/historico/documento/',
                            {'doc': CEDULA, 'ingreso': EGRESADO, 'archivo': f'otros_escala_downton_{CEDULA}_535.pdf'})
        self.assertEqual(r.status_code, 404)  # Downton no está aprobado


class AdministradorCompletaPospartoTests(TestCase):
    """2026-10-22: el administrador completa el Control Posparto de un ingreso
    cerrado hace más de 24 h; para el resto sigue en solo consulta."""

    def setUp(self):
        for p in DINAMICA + [mock.patch('obstetriciaunificador.ingresos.ingresos_de_paciente',
                                        side_effect=lambda *a, **k: _ingresos_simulados())]:
            p.start()
            self.addCleanup(p.stop)
        self.admin = User.objects.create_superuser('admin', password='x')
        self.enfermera = User.objects.create_user('enfermera', password='x')

    def _resumen(self, usuario, modulo='control_posparto'):
        self.client.force_login(usuario)
        r = self.client.get('/atencion/api/ingresos/', {'doc': CEDULA, 'modulo': modulo, 'ingreso': EGRESADO})
        return r.json()

    def test_administrador_puede_completar_posparto(self):
        datos = self._resumen(self.admin)
        self.assertFalse(datos['solo_consulta'])
        self.assertTrue(datos['admin_completa'])

    def test_enfermera_sigue_en_solo_consulta(self):
        datos = self._resumen(self.enfermera)
        self.assertTrue(datos['solo_consulta'])
        self.assertFalse(datos['admin_completa'])

    def test_otros_modulos_no_cambian_para_el_administrador(self):
        for modulo in ('meows', 'trabajo_parto', 'triaje'):
            self.assertTrue(self._resumen(self.admin, modulo)['solo_consulta'], modulo)
