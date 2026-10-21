"""
2026-10-20: Consulta histórica de pacientes EGRESADAS -- buscar por cédula o
número de ingreso y abrir los documentos que esta app dejó en el repositorio
clínico (NAS) para cada ingreso ya cerrado.

- Acceso: el superusuario y los usuarios que él autorice desde la sección
  "Usuarios autorizados" del mismo módulo (permiso obstetricia.consultar_historico),
  con uno de cuatro tipos (ACCESOS): "Módulos clínicos + Histórico egresadas"
  (enfermería), "Solo Histórico egresadas" (archivo; además
  obstetricia.solo_consulta_historica), "Solo módulos clínicos" (lo de cualquier
  usuario de Dinámica) o "Sin acceso a la aplicación" (obstetricia.sin_acceso_aplicacion:
  no puede iniciar sesión). sistema_obstetrico/middleware.py hace cumplir las restricciones.
  Solo se pide el usuario de Dinámica, nunca su contraseña: la app no guarda
  claves (el inicio de sesión se valida contra Dinámica).
- Solo ingresos con egreso oficial en Dinámica (AINFECEGRE) y no anulados: los
  ingresos en curso se consultan en los módulos normales.
- Los formatos de esta app (repositorio.FORMATOS) y, de los otros aplicativos
  del hospital que comparten la carpeta del ingreso, solo los aprobados en
  OTROS_DOCUMENTOS_APROBADOS (2026-10-21: CLAP).
- Solo lectura: no envía, reemplaza ni borra nada en la NAS.
"""
import re

from django.utils import timezone

from .repositorio import FORMATOS, PREFIJO_CATEGORIA, _limpiar, listar_documentos_ingreso, versiones_de_documentos

PERMISO = 'obstetricia.consultar_historico'
PERMISO_SOLO = 'obstetricia.solo_consulta_historica'
PERMISO_SIN_ACCESO = 'obstetricia.sin_acceso_aplicacion'
# Tipos de acceso que maneja el administrador. "solo_clinicos" es lo que tiene
# cualquier usuario de Dinámica sin nada asignado (no aparece en la lista).
ACCESOS = {
    'completo': 'Módulos clínicos + Histórico egresadas',
    'solo_historico': 'Solo Histórico egresadas',
    'solo_clinicos': 'Solo módulos clínicos',
    'sin_acceso': 'Sin acceso a la aplicación',
}
# Permisos de cada tipo (el resto de los tres se quita).
_PERMISOS_DEL_ACCESO = {
    'completo': {PERMISO},
    'solo_historico': {PERMISO, PERMISO_SOLO},
    'solo_clinicos': set(),
    'sin_acceso': {PERMISO_SIN_ACCESO},
}
MENSAJE_SIN_ACCESO = 'Su usuario no tiene acceso a esta aplicación. Comuníquese con el administrador.'

NOMBRES_FORMATO = {
    'triaje': 'Triaje obstétrico',
    'meows': 'Escala MEOWS',
    'trabajo_parto': 'Trabajo de parto',
    'control_posparto': 'Control posparto inmediato',
}
ORDEN_FORMATOS = ('triaje', 'meows', 'trabajo_parto', 'control_posparto')

TIPOS_TEXTO = {'hospitalizacion': 'Hospitalización', 'urgencias': 'Urgencias', 'consulta': 'Consulta externa'}

_RE_INGRESO = re.compile(r'^\d{5,10}$')


class ConsultaError(Exception):
    """Mensaje para el usuario (búsqueda sin resultado, Dinámica sin respuesta...)."""


def puede_consultar(usuario):
    """Superusuario o usuario autorizado por él (permiso PERMISO)."""
    return bool(
        usuario and getattr(usuario, 'is_authenticated', False)
        and (usuario.is_superuser or usuario.has_perm(PERMISO))
    )


def es_solo_historico(usuario):
    """True para el personal autorizado SOLO a la consulta histórica (p. ej.
    archivo): no ve ni usa los módulos clínicos (ver sistema_obstetrico/middleware.py).
    El superusuario nunca queda restringido."""
    return bool(
        usuario and getattr(usuario, 'is_authenticated', False) and not usuario.is_superuser
        and usuario.has_perm(PERMISO_SOLO)
    )


def es_sin_acceso(usuario):
    """True si el administrador le quitó todo acceso a la aplicación: no puede
    iniciar sesión (frecuenciafetal.views.login_view) y, si tenía la sesión
    abierta, se le cierra (sistema_obstetrico/middleware.py). Nunca al superusuario."""
    return bool(
        usuario and getattr(usuario, 'is_authenticated', False) and not usuario.is_superuser
        and usuario.has_perm(PERMISO_SIN_ACCESO)
    )


def puede_administrar_permisos(usuario):
    """Solo el superusuario da o quita el acceso a la consulta histórica."""
    return bool(usuario and getattr(usuario, 'is_authenticated', False) and usuario.is_superuser)


def _permiso(nombre=PERMISO):
    from django.contrib.auth.models import Permission
    app_label, codename = nombre.split('.')
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def _acceso_de(usuario):
    """'sin_acceso' | 'solo_historico' | 'completo' según los permisos asignados,
    o None si no tiene ninguno (= solo módulos clínicos, lo de cualquier usuario)."""
    if usuario is None:
        return None
    codigos = set(usuario.user_permissions.values_list('codename', flat=True))
    if PERMISO_SIN_ACCESO.split('.')[1] in codigos:
        return 'sin_acceso'
    if PERMISO.split('.')[1] not in codigos:
        return None
    return 'solo_historico' if PERMISO_SOLO.split('.')[1] in codigos else 'completo'


def _aplicar_acceso(usuario, acceso):
    todos = [_permiso(p) for p in (PERMISO, PERMISO_SOLO, PERMISO_SIN_ACCESO)]
    usuario.user_permissions.remove(*todos)
    usuario.user_permissions.add(*[_permiso(p) for p in _PERMISOS_DEL_ACCESO[acceso]])


def _accion(anterior, nuevo):
    if nuevo == 'solo_clinicos':
        return 'quitar'
    return 'autorizar' if anterior == 'solo_clinicos' and nuevo in ('completo', 'solo_historico') else 'cambiar'


def usuarios_autorizados():
    """[{'username', 'nombre', 'acceso', 'acceso_texto'}] de quienes tienen un acceso
    distinto al normal (histórico, solo histórico o sin acceso)."""
    from django.contrib.auth.models import User
    from django.db.models import Q
    usuarios = (User.objects.filter(is_active=True, is_superuser=False)
                .filter(Q(user_permissions=_permiso()) | Q(user_permissions=_permiso(PERMISO_SIN_ACCESO)))
                .distinct().order_by('username'))
    resultado = []
    for u in usuarios:
        acceso = _acceso_de(u)
        resultado.append({'username': u.username, 'nombre': u.first_name or '',
                          'acceso': acceso, 'acceso_texto': ACCESOS[acceso]})
    return resultado


def verificar_usuario(username):
    """{'usuario', 'nombre', 'activo', 'autorizado', 'acceso', 'acceso_actual', 'es_superusuario'}
    del usuario en Dinámica. Lanza ConsultaError si no existe o Dinámica no responde."""
    from django.contrib.auth.models import User
    from frecuenciafetal.sala_partos_db import consultar_usuario_dinamica

    username = (username or '').strip()
    if not username or len(username) > 150:
        raise ConsultaError('Escriba el usuario de Dinámica de la persona.')
    # Los administradores (p. ej. la cuenta local "admin") no son usuarios de
    # Dinámica y ya tienen acceso a todo: no hay nada que autorizar.
    if User.objects.filter(username__iexact=username, is_superuser=True).exists():
        raise ConsultaError(f'"{username}" es un administrador del sistema: ya tiene acceso a todo, no necesita permiso.')
    info = consultar_usuario_dinamica(username)
    if info is None:
        raise ConsultaError('Dinámica no responde en este momento. Intente de nuevo en unos minutos.')
    if not info:
        raise ConsultaError(f'El usuario "{username}" no existe en Dinámica.')
    usuario = User.objects.filter(username=info['usuario']).first()
    es_super = bool(usuario and usuario.is_superuser)
    acceso = _acceso_de(usuario)
    return {**info, 'autorizado': es_super or acceso in ('completo', 'solo_historico'), 'acceso': acceso,
            'acceso_actual': acceso or 'solo_clinicos', 'es_superusuario': es_super}


def autorizar(username, realizado_por, acceso='completo'):
    """Deja al usuario con el tipo de acceso elegido (ACCESOS). Si la persona
    nunca ha entrado a la app, se crea su usuario sin contraseña local: al
    iniciar sesión con Dinámica se usa ese mismo (auth_dgh: get_or_create por
    username) y ya tiene lo asignado."""
    from django.contrib.auth.models import User
    from .models import CambioPermisoHistorico

    if acceso not in ACCESOS:
        raise ConsultaError('Elija el tipo de acceso.')
    info = verificar_usuario(username)
    if info['es_superusuario']:
        raise ConsultaError('Ese usuario es administrador: ya tiene acceso a todo.')
    if not info['activo'] and acceso in ('completo', 'solo_historico'):
        raise ConsultaError(f'El usuario "{info["usuario"]}" está inactivo en Dinámica.')
    anterior = info['acceso_actual']
    if anterior == acceso:
        raise ConsultaError(f'Ese usuario ya tiene el acceso "{ACCESOS[acceso]}".')
    usuario, creado = User.objects.get_or_create(username=info['usuario'])
    if creado:
        usuario.set_unusable_password()
        usuario.first_name = info['nombre'][:150]
        usuario.save()
    _aplicar_acceso(usuario, acceso)
    CambioPermisoHistorico.objects.create(
        accion=_accion(anterior, acceso), acceso=acceso,
        username=usuario.username, nombre=info['nombre'][:255], realizado_por=realizado_por[:150],
    )
    return {'username': usuario.username, 'nombre': info['nombre'], 'acceso': acceso}


def quitar(username, realizado_por, dejar='solo_clinicos'):
    """Botón "Quitar" de la lista: deja al usuario con solo módulos clínicos o
    sin acceso. No consulta Dinámica (funciona aunque Dinámica no responda)."""
    from django.contrib.auth.models import User
    from .models import CambioPermisoHistorico

    if dejar not in ('solo_clinicos', 'sin_acceso'):
        raise ConsultaError('Elija cómo dejar al usuario.')
    usuario = User.objects.filter(username=(username or '').strip(), is_superuser=False).first()
    anterior = _acceso_de(usuario)
    if anterior is None:
        raise ConsultaError('Ese usuario no tiene ningún acceso especial asignado.')
    if anterior == dejar:
        raise ConsultaError(f'Ese usuario ya tiene el acceso "{ACCESOS[dejar]}".')
    _aplicar_acceso(usuario, dejar)
    CambioPermisoHistorico.objects.create(
        accion=_accion(anterior, dejar), acceso=dejar, username=usuario.username,
        nombre=(usuario.first_name or '')[:255], realizado_por=realizado_por[:150],
    )


def cambios_recientes(limite=15):
    from .models import CambioPermisoHistorico
    return [
        {'accion': c.get_accion_display(), 'acceso_texto': ACCESOS.get(c.acceso, ''), 'username': c.username,
         'nombre': c.nombre, 'realizado_por': c.realizado_por, 'fecha': _fecha(timezone.localtime(c.creado_en))}
        for c in CambioPermisoHistorico.objects.all()[:limite]
    ]


def _fecha(dt):
    return dt.strftime('%d/%m/%Y %I:%M %p') if dt else ''


def _ingreso_egresado(numero, fecha_ingreso, fecha_egreso, tipo):
    return {
        'numero': numero,
        'fecha_ingreso': _fecha(fecha_ingreso),
        'fecha_egreso': _fecha(fecha_egreso),
        'tipo': TIPOS_TEXTO.get(tipo, tipo or ''),
    }


def _por_cedula(cedula):
    from frecuenciafetal.sala_partos_db import consultar_ingresos_paciente, consultar_nombre_paciente

    filas = consultar_ingresos_paciente(cedula)
    if filas is None:
        raise ConsultaError('Dinámica no responde en este momento. Intente de nuevo en unos minutos.')
    if not filas:
        raise ConsultaError(f'No se encontraron ingresos para la cédula {cedula}.')
    # Las consultas externas no tienen egreso: quedan fuera solas.
    egresados = [
        _ingreso_egresado(f['numero_ingreso'], f['fecha_ingreso'], f['fecha_egreso'], f['tipo'])
        for f in filas if f['fecha_egreso'] is not None and not f['anulado']
    ]
    nombre = consultar_nombre_paciente(cedula)
    return {
        'cedula': cedula,
        'nombre': ' '.join(nombre) if nombre else '',
        'ingresos': egresados,
        'aviso': '' if egresados else
        'La paciente no tiene ingresos con egreso. Si está hospitalizada, consúltela en los módulos normales.',
    }


def _por_ingreso(numero):
    from frecuenciafetal.sala_partos_db import consultar_paciente_de_ingreso

    info = consultar_paciente_de_ingreso(numero)
    if info is None:
        raise ConsultaError('Dinámica no responde en este momento. Intente de nuevo en unos minutos.')
    if not info:
        raise ConsultaError(f'No existe el ingreso {numero}.')
    if info['anulado']:
        raise ConsultaError(f'El ingreso {numero} está anulado.')
    if info['fecha_egreso'] is None:
        raise ConsultaError(
            f'El ingreso {numero} todavía no tiene egreso. Consúltelo en los módulos normales.'
        )
    return {
        'cedula': info['cedula'],
        'nombre': info['nombre'],
        'ingresos': [_ingreso_egresado(numero, info['fecha_ingreso'], info['fecha_egreso'], info['tipo'])],
        'aviso': '',
    }


MENSAJE_DINAMICA_CAIDA = 'Dinámica no responde en este momento. Intente de nuevo en unos minutos.'


def _intentar(funcion, texto):
    """(resultado, mensaje de error) sin lanzar; Dinámica caída sí se lanza."""
    try:
        return funcion(texto), ''
    except ConsultaError as exc:
        if str(exc) == MENSAJE_DINAMICA_CAIDA:
            raise
        return None, str(exc)


def buscar(texto, tipo='auto'):
    """
    Paciente e ingresos EGRESADOS a partir de una cédula (tipo='cedula'), un
    número de ingreso (tipo='ingreso') o cualquiera de los dos (tipo='auto',
    la barra única de búsqueda).

    En 'auto' se busca el texto como ingreso Y como cédula. Hay cédulas
    antiguas de 7-8 dígitos que coinciden con números de ingreso: si el texto
    es a la vez un ingreso egresado de una paciente y la cédula de OTRA
    paciente con ingresos, no se adivina -- se devuelve {'ambiguo': True,
    'opciones': [...]} para que el usuario elija.
    Lanza ConsultaError con el mensaje para el usuario.
    """
    texto = re.sub(r'[\s.\-]', '', texto or '')
    if tipo == 'ingreso':
        if not _RE_INGRESO.match(texto):
            raise ConsultaError('El número de ingreso debe tener solo dígitos (ej. 1830660).')
        return _por_ingreso(texto)
    if tipo == 'cedula':
        if not texto or not texto.isalnum() or len(texto) > 20:
            raise ConsultaError('Escriba una cédula válida.')
        return _por_cedula(texto)
    if tipo != 'auto':
        raise ConsultaError('Búsqueda no válida.')

    if not texto or not texto.isalnum() or len(texto) > 20:
        raise ConsultaError('Escriba la cédula o el número de ingreso de la paciente.')
    por_ingreso, error_ingreso = _intentar(_por_ingreso, texto) if _RE_INGRESO.match(texto) else (None, '')
    por_cedula, error_cedula = _intentar(_por_cedula, texto)

    if por_ingreso and por_cedula and por_ingreso['cedula'] != texto:
        return {
            'ambiguo': True,
            'mensaje': f'El número {texto} coincide con un ingreso y con una cédula. Elija cuál busca:',
            'opciones': [
                {'tipo': 'ingreso', 'texto': f'Ingreso {texto} de {por_ingreso["nombre"] or "la paciente"} '
                                             f'(cédula {por_ingreso["cedula"]})'},
                {'tipo': 'cedula', 'texto': f'Cédula {texto} de {por_cedula["nombre"] or "la paciente"}'},
            ],
        }
    if por_ingreso:
        return por_ingreso
    if por_cedula:
        return por_cedula
    # Ninguno: el mensaje más útil (p. ej. "el ingreso todavía no tiene egreso").
    if error_ingreso and not error_ingreso.startswith('No existe el ingreso'):
        raise ConsultaError(error_ingreso)
    raise ConsultaError(f'No se encontró ninguna paciente ni ingreso con el número {texto}.')


def ingreso_consultable(cedula, numero):
    """True si `numero` es un ingreso EGRESADO (y no anulado) de esa cédula.
    Se valida en cada pedido de documentos: nunca se confía en lo que manda
    el navegador."""
    from frecuenciafetal.sala_partos_db import consultar_paciente_de_ingreso

    info = consultar_paciente_de_ingreso(numero)
    if info is None:
        raise ConsultaError('Dinámica no responde en este momento. Intente de nuevo en unos minutos.')
    return bool(
        info and _limpiar(info['cedula']) == _limpiar(cedula)
        and info['fecha_egreso'] is not None and not info['anulado']
    )


def _formato_de_archivo(nombre, cedula_l):
    for formato in ORDEN_FORMATOS:
        patron = rf'^{PREFIJO_CATEGORIA}_{re.escape(FORMATOS[formato])}_{re.escape(cedula_l)}_\d+\.pdf$'
        if re.match(patron, nombre, re.IGNORECASE):
            return formato
    return None


def documentos_de_la_app(cedula, numero, archivos=None):
    """[{'nombre', 'formato', 'titulo', 'vigente', 'reemplazado_por', 'con_versiones'}] de los
    PDF de esta app en <cédula>/<ingreso>, en el orden de la atención (triaje,
    MEOWS, trabajo de parto, posparto). Lanza excepción si la NAS no responde."""
    cedula_l = _limpiar(cedula)
    if archivos is None:
        archivos = listar_documentos_ingreso(cedula, numero)
    versiones = versiones_de_documentos(cedula, numero, archivos)
    documentos = []
    for nombre in archivos:
        formato = _formato_de_archivo(nombre, cedula_l)
        if formato is None:
            continue
        version = versiones.get(nombre, {})
        documentos.append({
            'nombre': nombre,
            'formato': formato,
            'titulo': NOMBRES_FORMATO[formato],
            'vigente': version.get('vigente', True),
            'reemplazado_por': version.get('reemplazado_por', ''),
            'con_versiones': bool(version),
        })
    documentos.sort(key=lambda d: (ORDEN_FORMATOS.index(d['formato']), d['nombre']))
    return documentos


def es_documento_de_la_app(cedula, nombre):
    return _formato_de_archivo(nombre, _limpiar(cedula)) is not None


# 2026-10-21: documentos de OTROS aplicativos del hospital que también se
# muestran (lista aprobada por el administrador). Clave: el prefijo del nombre
# del archivo antes del primer "_" (p. ej. "clap_..."). Solo PDF.
OTROS_DOCUMENTOS_APROBADOS = {
    'clap': 'Historia clínica perinatal (CLAP)',
}


def _tipo_otro_documento(nombre):
    if not nombre.lower().endswith('.pdf'):
        return None
    prefijo = nombre.split('_', 1)[0].lower()
    return prefijo if prefijo in OTROS_DOCUMENTOS_APROBADOS else None


def otros_documentos(archivos):
    """[{'nombre', 'titulo'}] de los PDF de otros aplicativos aprobados en la carpeta."""
    return [
        {'nombre': nombre, 'titulo': OTROS_DOCUMENTOS_APROBADOS[tipo]}
        for nombre in sorted(archivos)
        for tipo in [_tipo_otro_documento(nombre)] if tipo
    ]


def es_documento_consultable(cedula, nombre):
    """Lo que se puede abrir desde la consulta histórica: PDF de esta app o de
    un aplicativo aprobado (OTROS_DOCUMENTOS_APROBADOS)."""
    return es_documento_de_la_app(cedula, nombre) or _tipo_otro_documento(nombre) is not None


# ---------------------------------------------------------------------------
# 2026-10-20 (segunda entrega): alertas de documentos que DEBERÍAN estar en
# la NAS para un ingreso egresado y no están, con el motivo -- p. ej. un
# Control Posparto que nunca se cerró porque faltó el acompañante.
# ---------------------------------------------------------------------------
def revisar_ingreso(cedula, numero):
    """{'documentos': [...], 'otros': [...], 'alertas': [...]} de un ingreso egresado
    con una sola lectura de la carpeta en la NAS. Lanza excepción si la NAS no responde."""
    archivos = listar_documentos_ingreso(cedula, numero)
    documentos = documentos_de_la_app(cedula, numero, archivos)
    try:
        alertas = alertas_de_faltantes(cedula, numero, archivos, documentos)
    except Exception:
        # Las alertas son un extra: si algo falla (p. ej. Dinámica a medias),
        # los documentos se muestran igual.
        import logging
        logging.getLogger(__name__).exception('Consulta histórica: no se pudieron calcular las alertas de %s/%s', cedula, numero)
        alertas = [{'formato': '', 'titulo': 'Revisión incompleta',
                    'mensaje': 'No se pudo revisar si faltan documentos de este ingreso.', 'detalle': []}]
    return {'documentos': documentos, 'otros': otros_documentos(archivos), 'alertas': alertas}


def _alerta(formato, mensaje, detalle=None):
    return {'formato': formato, 'titulo': NOMBRES_FORMATO[formato], 'mensaje': mensaje, 'detalle': detalle or []}


def _envios(cedula, numero, formato):
    from .models import DocumentoRepositorio
    return list(DocumentoRepositorio.objects.filter(
        cedula=_limpiar(cedula)[:50], numero_ingreso=_limpiar(numero)[:30], formato=formato,
    ).order_by('-creado_en'))


def _ultimo_error(envios):
    """Texto del error del último intento si falló y no hubo un envío exitoso después."""
    from .models import DocumentoRepositorio
    for envio in envios:  # del más reciente al más antiguo
        if envio.estado == DocumentoRepositorio.ESTADO_ENVIADO:
            return ''
        if envio.estado == DocumentoRepositorio.ESTADO_ERROR:
            return (envio.detalle_error or 'error sin detalle')[:300]
    return ''


def _registro_en_nas(referencia, envios, archivos, hay_archivos_del_formato):
    """¿El registro `referencia` (RegistroParto / Formulario) tiene su PDF en la
    carpeta? Por la bitácora de envíos; un PDF del formato sin bitácora para
    ese ingreso (envíos antiguos) se da por bueno."""
    from .models import DocumentoRepositorio
    if any(e.referencia == str(referencia) and e.estado == DocumentoRepositorio.ESTADO_ENVIADO
           and e.nombre_archivo in archivos for e in envios):
        return True
    return hay_archivos_del_formato and not any(e.estado == DocumentoRepositorio.ESTADO_ENVIADO for e in envios)


def alertas_de_faltantes(cedula, numero, archivos, documentos):
    from frecuenciafetal.models import RegistroParto
    from frecuenciafetal.views import _faltantes_control_6h, pendientes_datos_cierre
    from .ingresos import asignar_mediciones_meows, asignar_registros_posparto, asignar_controles_trabajo_parto, ingresos_de_paciente

    ingresos, _, _ = ingresos_de_paciente(cedula)
    presentes = {d['formato'] for d in documentos}
    alertas = []

    # Triaje y MEOWS: se envían solos (al dar ingreso / al egreso).
    tomas = asignar_mediciones_meows(cedula, ingresos).get(numero, [])
    tomas_triaje = asignar_mediciones_meows(cedula, ingresos, solo_triaje=True).get(numero, [])
    for formato, n in (('triaje', len(tomas_triaje)), ('meows', len(tomas))):
        if n and formato not in presentes:
            error = _ultimo_error(_envios(cedula, numero, formato))
            mensaje = (f'Hay {n} toma{"s" if n != 1 else ""} en la app pero el documento no está en la NAS.')
            detalle = [f'Último intento de envío falló: {error}'] if error else [
                'No hay registro de un envío exitoso. El sistema lo intenta automáticamente; '
                'si no aparece, se puede enviar desde el módulo.']
            alertas.append(_alerta(formato, mensaje, detalle))

    # Trabajo de parto: cada hoja se envía al pulsar "Finalizar".
    envios_tp = _envios(cedula, numero, 'trabajo_parto')
    for hoja_id, controles in asignar_controles_trabajo_parto(cedula, ingresos).get(numero, {}).items():
        if not controles or _registro_en_nas(hoja_id, envios_tp, archivos, 'trabajo_parto' in presentes):
            continue
        error = _ultimo_error([e for e in envios_tp if e.referencia == str(hoja_id)])
        alertas.append(_alerta(
            'trabajo_parto',
            f'Hoja con {len(controles)} control{"es" if len(controles) != 1 else ""} sin documento en la NAS.',
            [f'Último intento de envío falló: {error}'] if error else ['Nadie pulsó "Finalizar" en la hoja de Trabajo de Parto.'],
        ))

    # Control posparto: se envía al cerrar con "Guardar Registro Completo".
    envios_pp = _envios(cedula, numero, 'control_posparto')
    ids = asignar_registros_posparto(cedula, ingresos).get(numero, [])
    for registro in RegistroParto.objects.filter(id__in=ids).order_by('created_at'):
        if registro.completado_en is None:
            faltan = (
                [f'Falta el control de las 6 horas: {f}' for f in _faltantes_control_6h(registro)]
                + [f[:1].upper() + f[1:] for f in pendientes_datos_cierre(registro)]  # 'En "..." falta ...'
            )
            alertas.append(_alerta(
                'control_posparto',
                'El registro nunca se cerró con "Guardar Registro Completo": por eso no está en la NAS.',
                faltan or ['No le falta nada: solo falta pulsar "Guardar Registro Completo".'],
            ))
        elif not _registro_en_nas(registro.pk, envios_pp, archivos, 'control_posparto' in presentes):
            error = _ultimo_error([e for e in envios_pp if e.referencia == str(registro.pk)])
            detalle = [f'Último intento de envío falló: {error}'] if error else []
            detalle.append(f'El administrador puede subirlo con: manage.py reenviar_control_posparto {_limpiar(cedula)}')
            alertas.append(_alerta('control_posparto', 'El registro está cerrado pero el documento no está en la NAS.', detalle))
    return alertas
