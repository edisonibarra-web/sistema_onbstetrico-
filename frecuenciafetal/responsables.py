"""
2026-09-28: responsables del formato FRSPA-007 (Control Posparto Inmediato).

El formato lo diligencian por lo general dos o más personas. En vez de un
único campo "Responsable" escrito a mano (que la segunda persona pisaba), el
servidor firma solo cada cosa con el profesional en sesión:

- cada control (fetocardia, posparto, sangrado, globo, sutura, recién
  nacido) guarda registrado_por / registrado_en;
- el registro guarda creado_por (quien lo creó) y completado_por (quien lo
  cerró con "Guardar Registro Completo");
- ParticipacionRegistroParto lleva a TODOS los que escribieron algo.

resumen_responsables() arma, para la pantalla y el PDF, qué hizo cada uno.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from sistema_obstetrico.auth_utils import nombre_profesional_sesion

logger = logging.getLogger(__name__)


def firma_sesion(request, con_responsable=False):
    """Campos de firma automática para guardar un control."""
    nombre = nombre_profesional_sesion(request)[:255] if request is not None else ''
    datos = {'registrado_por': nombre, 'registrado_en': timezone.now()}
    if con_responsable:
        datos['responsable'] = nombre[:200]
    return datos


def registrar_participacion(registro, request):
    """Deja constancia de que el profesional en sesión escribió en `registro`.
    Nunca rompe el guardado: ante cualquier error solo se registra en el log."""
    from .models import ParticipacionRegistroParto, RegistroParto

    if registro is None or getattr(registro, 'pk', None) is None:
        return
    try:
        nombre = (nombre_profesional_sesion(request) or '').strip()[:255]
        if not nombre:
            return
        ahora = timezone.now()
        usuario = getattr(getattr(request, 'user', None), 'username', '') or ''
        actualizadas = ParticipacionRegistroParto.objects.filter(
            registro_id=registro.pk, profesional=nombre,
        ).update(ultima_vez=ahora)
        if not actualizadas:
            try:
                with transaction.atomic():
                    ParticipacionRegistroParto.objects.create(
                        registro_id=registro.pk, profesional=nombre, usuario=usuario[:150],
                        primera_vez=ahora, ultima_vez=ahora,
                    )
            except IntegrityError:  # otra petición simultánea del mismo profesional
                pass
        if not (registro.creado_por or '').strip():
            RegistroParto.objects.filter(pk=registro.pk, creado_por='').update(creado_por=nombre)
            registro.creado_por = nombre
        # Compatibilidad: el campo de texto "Responsable del registro" (lo usan
        # listados y la campana NAS) queda con TODOS los participantes.
        nombres = list(
            ParticipacionRegistroParto.objects.filter(registro_id=registro.pk)
            .order_by('primera_vez').values_list('profesional', flat=True)
        )
        texto = ', '.join(nombres)[:200]
        if texto and texto != (registro.nombre_firma_paciente or ''):
            RegistroParto.objects.filter(pk=registro.pk).update(nombre_firma_paciente=texto)
            registro.nombre_firma_paciente = texto
    except Exception:
        logger.exception('No se pudo registrar la participación en el registro de parto')


def _rango_minutos(minutos):
    minutos = sorted(set(m for m in minutos if m is not None))
    if not minutos:
        return ''
    if len(minutos) == 1:
        return f'{minutos[0]} min'
    if len(minutos) <= 4:
        return ', '.join(str(m) for m in minutos) + ' min'
    return f'{minutos[0]} a {minutos[-1]} min'


def resumen_responsables(registro):
    """
    [{'nombre', 'desde', 'hasta', 'detalle': [..], 'inicio': bool, 'cierre': bool}]
    en orden de participación. Para registros anteriores a la firma
    automática (sin participaciones), se reconstruye con lo que haya
    (responsable de cada control o el campo de texto del registro).
    """
    if registro is None or getattr(registro, 'pk', None) is None:
        return []
    personas = {}

    def persona(nombre):
        nombre = (nombre or '').strip()
        if not nombre:
            return None
        if nombre not in personas:
            personas[nombre] = {'nombre': nombre, 'desde': None, 'hasta': None, 'detalle': {},
                                'inicio': False, 'cierre': False}
        return personas[nombre]

    def tocar(p, momento):
        if p is None or momento is None:
            return
        p['desde'] = momento if p['desde'] is None else min(p['desde'], momento)
        p['hasta'] = momento if p['hasta'] is None else max(p['hasta'], momento)

    for part in registro.participaciones.all():
        p = persona(part.profesional)
        tocar(p, part.primera_vez)
        tocar(p, part.ultima_vez)

    def agregar(qs, etiqueta, con_minuto=True, respaldo_responsable=False):
        for c in qs:
            nombre = c.registrado_por or (getattr(c, 'responsable', '') if respaldo_responsable else '')
            p = persona(nombre)
            if p is None:
                continue
            tocar(p, c.registrado_en)
            p['detalle'].setdefault(etiqueta, []).append(getattr(c, 'minuto_control', None) if con_minuto else 1)

    agregar(registro.controles_fetocardia.all(), 'Fetocardia', con_minuto=False, respaldo_responsable=True)
    agregar(registro.controles_postparto.all(), 'Controles posparto', respaldo_responsable=True)
    agregar(registro.controles_sangrado.all(), 'Sangrado')
    agregar(registro.controles_globo.all(), 'Globo de seguridad')
    agregar(registro.controles_sutura.all(), 'Sutura y heridas')
    try:
        rn = registro.control_recien_nacido
    except Exception:
        rn = None
    if rn is not None:
        agregar([rn], 'Recién nacido', con_minuto=False)

    p = persona(registro.creado_por)
    if p is not None:
        p['inicio'] = True
        tocar(p, registro.created_at)
    p = persona(registro.completado_por)
    if p is not None:
        p['cierre'] = True
        tocar(p, registro.completado_en)

    if not personas:  # registro anterior a la firma automática
        for nombre in (registro.nombre_firma_paciente or registro.profesional_nombre or '').split(','):
            persona(nombre)

    salida = []
    for p in personas.values():
        detalle = []
        if p['inicio']:
            detalle.append('Inició el registro')
        for etiqueta, valores in p['detalle'].items():
            if etiqueta in ('Fetocardia',):
                detalle.append(f'{etiqueta}: {len(valores)} toma' + ('s' if len(valores) != 1 else ''))
            elif etiqueta == 'Recién nacido':
                detalle.append(etiqueta)
            else:
                rango = _rango_minutos(valores)
                detalle.append(f'{etiqueta}: {rango}' if rango else etiqueta)
        if p['cierre']:
            detalle.append('Cerró el registro')
        if not detalle:
            detalle.append('Datos del registro')
        salida.append({**p, 'detalle': detalle})
    ahora = timezone.now()
    salida.sort(key=lambda x: x['desde'] or ahora)
    return salida


def responsables_para_api(registro):
    return [
        {'nombre': r['nombre'], 'desde': r['desde'], 'hasta': r['hasta'], 'detalle': r['detalle']}
        for r in resumen_responsables(registro)
    ]


# ---------------------------------------------------------------------------
# 2026-10-06: responsables POR PASO (Fetocardia, Parto, Vigilancia, Recién
# nacido). Bitácora CambioRegistroParto: quién registró / corrigió / eliminó
# qué campo o control (sin valores). La creación de cada control sale de su
# registrado_por; la bitácora aporta las correcciones, eliminaciones y los
# campos de Parto y Recién nacido.
# ---------------------------------------------------------------------------
SECCIONES_PASO = ('fetocardia', 'parto', 'vigilancia', 'recien_nacido')

# Si la misma persona vuelve a guardar el mismo campo en este lapso (el
# autoguardado guarda mientras escribe), no se repite en la bitácora.
VENTANA_MISMO_CAMBIO = timedelta(minutes=10)

CAMPOS_PARTO = [
    ('tipo_parto', 'Tipo de parto'),
    ('hora_parto', 'Hora de parto'),
    ('episiotomia', 'Episiotomía'),
    ('tipo_alumbramiento', 'Alumbramiento'),
    ('desgarro', 'Desgarro'),
    ('desgarro_subgrado', 'Subclasificación del desgarro'),
]
# Del registro, pero se diligencia en la tarjeta del recién nacido.
CAMPOS_REGISTRO_EN_RN = [('parto_atendido_por', 'Parto atendido por')]

ETIQUETAS_RN = {
    'genero': 'Género', 'pasa_uci_neonatal': 'Pasa a UCI neonatal', 'causa_uci': 'Causa de UCI',
    'peso': 'Peso', 'talla': 'Talla', 'pc': 'Perímetro cefálico', 'pt': 'Perímetro torácico',
    'p_abd': 'Perímetro abdominal', 'apgar_1min': "APGAR 1'", 'apgar_5min': "APGAR 5'",
    'apgar_10min': "APGAR 10'", 'tsh_tomada': 'TSH tomada', 'hemoclasificacion': 'Hemoclasificación',
    'vacuna_hb': 'Vacuna HB', 'vacuna_bcg': 'Vacuna BCG',
    'caracteristicas_liquido_amniotico': 'Líquido amniótico', 'lavado_gastrico': 'Lavado gástrico',
    'lavado_elimina': 'Elimina (lavado gástrico)', 'meconio': 'Meconio',
    'oximetria_nacimiento_preductal': 'Oximetría al nacer (preductal)',
    'oximetria_nacimiento_posductal': 'Oximetría al nacer (posductal)',
    'oximetria_12h_preductal': 'Oximetría 12 h (preductal)', 'oximetria_12h_posductal': 'Oximetría 12 h (posductal)',
    'fc_nacimiento': 'FC al nacer', 'neonato_atendido_por': 'Neonato atendido por',
    'valorado_pediatra': 'Valorado por pediatra', 'glucometrias_no_aplica': 'Glucometrías: no aplica',
}
for _pref, _txt in (('tanac', 'TA al nacer'), ('tanac12', 'Al nacimiento: TA 12 h'), ('tanac24', 'Al nacimiento: TA 24 h'),
                    ('tanac48', 'Al nacimiento: TA 48 h'), ('ta', 'TA neonato 12 h'), ('ta24', 'TA neonato 24 h'),
                    ('ta48', 'TA neonato 48 h')):
    for _miembro in ('msd', 'msi', 'mid', 'miiz'):
        ETIQUETAS_RN[f'{_pref}_{_miembro}'] = f'{_txt} {_miembro.upper()}'
# Campos del RN que no son datos clínicos diligenciados (la huella va aparte).
_RN_NO_BITACORA = {'id', 'registro_id', 'huella_pdf', 'huella_subida_por', 'huella_subida_en'}


def registrar_cambios(registro, request, seccion, cambios):
    """cambios: [(accion, detalle)]. Nunca rompe el guardado."""
    from .models import CambioRegistroParto

    if not cambios or registro is None or getattr(registro, 'pk', None) is None:
        return
    try:
        nombre = (nombre_profesional_sesion(request) or '').strip()[:255] if request is not None else ''
        if not nombre:
            return
        usuario = getattr(getattr(request, 'user', None), 'username', '') or ''
        ahora = timezone.now()
        nuevos = []
        for accion, detalle in cambios:
            detalle = str(detalle)[:255]
            ultimo = (CambioRegistroParto.objects
                      .filter(registro_id=registro.pk, seccion=seccion, detalle=detalle)
                      .order_by('-creado_en', '-id').first())
            # La misma persona sigue escribiendo ese campo: no se repite.
            if (accion != 'eliminacion' and ultimo is not None and ultimo.profesional == nombre
                    and ultimo.accion != 'eliminacion' and ahora - ultimo.creado_en < VENTANA_MISMO_CAMBIO):
                continue
            nuevos.append(CambioRegistroParto(
                registro_id=registro.pk, seccion=seccion, accion=accion, detalle=detalle,
                profesional=nombre, usuario=usuario[:150],
            ))
        if nuevos:
            CambioRegistroParto.objects.bulk_create(nuevos)
    except Exception:
        logger.exception('No se pudo registrar la bitácora de cambios del registro de parto')


def _vacio(valor, defecto=None):
    return valor is None or valor == '' or valor == defecto


def _diferencias(campos, antes, despues, modelo):
    """[(accion, etiqueta)] de los campos que cambiaron. `antes` None = recién creado."""
    cambios = []
    antes = antes or {}
    despues = despues or {}
    for campo, etiqueta in campos:
        try:
            defecto = modelo._meta.get_field(campo).get_default()
        except Exception:
            defecto = None
        a, d = antes.get(campo), despues.get(campo)
        if a == d or (campo not in antes and _vacio(d, defecto)):
            continue
        cambios.append(('registro' if _vacio(a, defecto) else 'correccion', etiqueta))
    return cambios


def bitacora_registro_y_rn(registro, request, antes, despues):
    """Compara las fotos (registro, rn, glucometrías) de antes y después de
    guardar el registro (ver RegistroPartoViewSet._foto_registro) y deja en la
    bitácora los campos de Parto y Recién nacido que cambiaron."""
    from .models import ControlRecienNacido, RegistroParto

    reg_a, rn_a, glu_a = antes if antes else (None, None, [])
    reg_d, rn_d, glu_d = despues
    registrar_cambios(registro, request, 'parto', _diferencias(CAMPOS_PARTO, reg_a, reg_d, RegistroParto))

    cambios_rn = _diferencias(CAMPOS_REGISTRO_EN_RN, reg_a, reg_d, RegistroParto)
    campos_rn = [(c, ETIQUETAS_RN.get(c) or c.replace('_', ' ').capitalize())
                 for c in (rn_d or {}) if c not in _RN_NO_BITACORA]
    cambios_rn += _diferencias(campos_rn, rn_a, rn_d, ControlRecienNacido)
    if glu_a != glu_d:
        cambios_rn.append(('registro' if not glu_a else 'correccion', 'Glucometrías'))
    registrar_cambios(registro, request, 'recien_nacido', cambios_rn)


def responsables_por_seccion(registro):
    """{seccion: [{'nombre', 'desde', 'hasta', 'detalle': ['Registró: …', 'Corrigió: …']}]}"""
    vacio = {s: [] for s in SECCIONES_PASO}
    if registro is None or getattr(registro, 'pk', None) is None:
        return vacio
    secciones = {s: {} for s in SECCIONES_PASO}

    def anotar(seccion, nombre, accion, detalle, momento):
        nombre = (nombre or '').strip()
        if not nombre:
            return
        p = secciones[seccion].setdefault(nombre, {'nombre': nombre, 'desde': None, 'hasta': None, 'acciones': {}})
        if momento is not None:
            p['desde'] = momento if p['desde'] is None else min(p['desde'], momento)
            p['hasta'] = momento if p['hasta'] is None else max(p['hasta'], momento)
        lista = p['acciones'].setdefault(accion, [])
        if detalle not in lista:
            lista.append(detalle)

    # Quién registró cada control (sale del propio control).
    for c in registro.controles_fetocardia.all():
        anotar('fetocardia', c.registrado_por or c.responsable, 'registro', ('toma', c.pk), c.registrado_en)
    for qs, grupo in ((registro.controles_sangrado.all(), 'Sangrado'),
                      (registro.controles_globo.all(), 'Globo de seguridad'),
                      (registro.controles_sutura.all(), 'Sutura y heridas')):
        for c in qs:
            anotar('vigilancia', c.registrado_por, 'registro', (grupo, c.minuto_control), c.registrado_en)

    for cambio in registro.cambios.all():
        anotar(cambio.seccion, cambio.profesional, cambio.accion, cambio.detalle, cambio.creado_en)

    # Registros anteriores a la bitácora: lo poco que se sabe del recién nacido.
    try:
        rn = registro.control_recien_nacido
    except Exception:
        rn = None
    if rn is not None:
        if not secciones['recien_nacido']:
            anotar('recien_nacido', rn.registrado_por, 'registro', 'Datos del recién nacido', rn.registrado_en)
        if rn.huella_subida_por:
            anotar('recien_nacido', rn.huella_subida_por, 'registro', 'Huella plantar', rn.huella_subida_en)

    verbo = dict((('registro', 'Registró'), ('correccion', 'Corrigió'), ('eliminacion', 'Eliminó')))
    salida = {}
    ahora = timezone.now()
    for seccion, personas in secciones.items():
        filas = []
        for p in personas.values():
            detalle = []
            for accion in ('registro', 'correccion', 'eliminacion'):
                items = p['acciones'].get(accion)
                if not items:
                    continue
                if seccion == 'fetocardia' and accion == 'registro':
                    texto = f"{len(items)} toma" + ('s' if len(items) != 1 else '')
                elif seccion == 'vigilancia' and accion == 'registro':
                    por_grupo = {}
                    for grupo, minuto in items:
                        por_grupo.setdefault(grupo, []).append(minuto)
                    texto = '; '.join(f'{g} {_rango_minutos(m)}' for g, m in por_grupo.items())
                else:
                    texto = ', '.join(items)
                detalle.append(f'{verbo[accion]}: {texto}')
            filas.append({'nombre': p['nombre'], 'desde': p['desde'], 'hasta': p['hasta'], 'detalle': detalle})
        filas.sort(key=lambda x: x['desde'] or ahora)
        salida[seccion] = filas
    return salida


# Campos que no cuentan como "cambio" hecho por quien guarda (automáticos).
_CAMPOS_AUTOMATICOS = {'updated_at', 'created_at', 'registrado_en', 'registrado_por', 'estado',
                       'nombre_firma_paciente', 'creado_por', 'responsable'}


def valores_modelo(instancia):
    """Foto de los campos de `instancia` para saber si un guardado cambió algo
    (el autoguardado reenvía todo aunque nadie haya tocado nada)."""
    if instancia is None:
        return None
    return {
        f.attname: getattr(instancia, f.attname)
        for f in instancia._meta.concrete_fields
        if f.name not in _CAMPOS_AUTOMATICOS
    }
