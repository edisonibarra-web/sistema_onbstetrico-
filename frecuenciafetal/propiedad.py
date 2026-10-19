"""
2026-10-19: cada dato de Control Posparto es de quien lo registró.

Regla (a pedido): lo que registró una enfermera SOLO ella puede corregirlo o
borrarlo -- nadie más, tampoco un administrador. Las demás sí pueden llenar
lo que está vacío y agregar controles nuevos (relevo de turno).

El dueño es el USUARIO del login (request.user.username), no el nombre:
- controles (sangrado, globo, sutura, fetocardia, postparto), glucometrías:
  `registrado_usuario` de cada fila;
- huella plantar: `huella_subida_usuario`;
- campos del registro y del recién nacido: `duenos_campos`
  ({campo: {"usuario", "nombre"}}), del primero que lo llenó.

Lo hace cumplir el servidor (esto); la pantalla solo lo muestra bloqueado.
"""
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import PermissionDenied

from sistema_obstetrico.auth_utils import nombre_profesional_sesion

# Campos del registro con dueño. Nombre, identificación y edad gestacional
# vienen de Dinámica; globo/sutura/sangrado salen de sus controles.
CAMPOS_REGISTRO_CON_DUENO = (
    'tipo_parto', 'hora_parto', 'hora_parto_b', 'episiotomia', 'tipo_alumbramiento',
    'desgarro', 'desgarro_subgrado', 'numero_fetos', 'nombre_acompanante', 'parto_atendido_por',
)
# Campos del recién nacido SIN dueño (firma, archivo, y la hora de nacimiento,
# que sale de la hora de parto de su feto).
_RN_SIN_DUENO = {
    'id', 'registro', 'feto', 'huella_pdf', 'huella_subida_por', 'huella_subida_en', 'huella_subida_usuario',
    'registrado_por', 'registrado_en', 'registrado_usuario', 'duenos_campos', 'hora_nacimiento',
}


def campos_rn_con_dueno():
    from .models import ControlRecienNacido
    return tuple(f.name for f in ControlRecienNacido._meta.concrete_fields if f.name not in _RN_SIN_DUENO)


def usuario_y_nombre(request):
    """(usuario del login, nombre del profesional). Sin sesión: ('', '')."""
    usuario = getattr(getattr(request, 'user', None), 'username', '') or ''
    if not usuario:
        return '', ''
    return usuario[:150], (nombre_profesional_sesion(request) or usuario)[:255]


def es_ajeno(usuario_dueno, usuario):
    """True si el dato tiene dueño y no es quien está en sesión."""
    return bool(usuario and usuario_dueno and usuario_dueno != usuario)


class DatoAjenoError(PermissionDenied):
    """403 con la lista de datos de otra persona que se intentó cambiar:
    {'detail': '…', 'campos_ajenos': [{'campo', 'nombre'}]} (la pantalla los
    devuelve a su valor guardado)."""

    def __init__(self, bloqueados):
        nombres = sorted({b['nombre'] for b in bloqueados})
        super().__init__({
            'detail': (f'Hay datos registrados por {", ".join(nombres)}: solo esa persona puede '
                       'corregirlos o borrarlos. No se guardó ningún cambio de este guardado.'),
            'campos_ajenos': bloqueados,
        })


def exigir_autoria(obj, usuario, que='Este dato', campo_usuario='registrado_usuario', campo_nombre='registrado_por'):
    """Para corregir / eliminar una fila (control, huella): solo su autora."""
    dueno = getattr(obj, campo_usuario, '') or ''
    if es_ajeno(dueno, usuario):
        nombre = getattr(obj, campo_nombre, '') or dueno
        raise PermissionDenied(f'{que} lo registró {nombre}: solo esa persona puede corregirlo o eliminarlo.')


def _defecto(modelo, campo):
    try:
        return modelo._meta.get_field(campo).get_default()
    except Exception:
        return None


def vacio(modelo, campo, valor):
    """Sin dato: vacío o igual al valor por defecto (p. ej. un embarazo único)."""
    return valor is None or valor == '' or valor == _defecto(modelo, campo)


def iguales(a, b):
    if a == b:
        return True
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except (InvalidOperation, TypeError, ValueError):
        return str(a) == str(b)


def datos_ajenos(instancia, cambios, campos_con_dueno, usuario, sufijo=''):
    """[{campo, nombre}] de los campos de `cambios` que tienen otro dueño y
    cuyo valor cambiaría (si llega el mismo valor no es un cambio)."""
    if instancia is None or not usuario:
        return []
    duenos = instancia.duenos_campos or {}
    bloqueados = []
    for campo, nuevo in cambios.items():
        dueno = duenos.get(campo) if campo in campos_con_dueno else None
        if not dueno or not es_ajeno(dueno.get('usuario'), usuario):
            continue
        if iguales(getattr(instancia, campo, None), nuevo):
            continue
        bloqueados.append({'campo': campo + sufijo, 'nombre': dueno.get('nombre') or dueno.get('usuario')})
    return bloqueados


def asignar_duenos(instancia, campos, valores_antes, campos_con_dueno, usuario, nombre):
    """Después de guardar: el que llenó un campo vacío queda como su dueño;
    un campo que quedó vacío deja de tener dueño. Guarda solo duenos_campos."""
    if instancia is None or not usuario:
        return
    modelo = type(instancia)
    duenos = dict(instancia.duenos_campos or {})
    for campo in campos:
        if campo not in campos_con_dueno:
            continue
        ahora = getattr(instancia, campo, None)
        if vacio(modelo, campo, ahora):
            duenos.pop(campo, None)
        elif campo not in duenos and not iguales(valores_antes.get(campo), ahora):
            duenos[campo] = {'usuario': usuario, 'nombre': nombre}
    if duenos != (instancia.duenos_campos or {}):
        instancia.duenos_campos = duenos
        modelo.objects.filter(pk=instancia.pk).update(duenos_campos=duenos)


def valores(instancia, campos):
    return {c: getattr(instancia, c, None) for c in campos} if instancia is not None else {}


def glucometrias_ajenas(rn, quitar, reemplazo, usuario):
    """Glucometrías de otra persona que se quitarían (por `glucometrias_quitar`
    o por una lista `glucometrias` que ya no las trae)."""
    if rn is None or not usuario:
        return []
    ajenas = [g for g in rn.glucometrias.all() if es_ajeno(g.registrado_usuario, usuario)]
    clave = lambda h, r: (str(h)[:5], Decimal(str(r)).normalize())
    quitadas = {clave(g['hora'], g['resultado']) for g in (quitar or [])}
    if reemplazo is not None:
        quedan = {clave(g['hora'], g['resultado']) for g in reemplazo}
        quitadas |= {clave(g.hora, g.resultado) for g in ajenas} - quedan
    return [{'campo': 'glucometrias', 'nombre': g.registrado_por or g.registrado_usuario}
            for g in ajenas if clave(g.hora, g.resultado) in quitadas]


# ---------------------------------------------------------------------------
# Datos anteriores a esta regla (migración 0046): el dueño se toma de lo que
# ya se sabía -- la firma (nombre) de cada fila y la bitácora por campo.
# ---------------------------------------------------------------------------
def asignar_duenos_existentes(m):
    """`m`: dict de modelos (de la migración). Idempotente."""
    from .responsables import CAMPOS_PARTO, CAMPOS_REGISTRO_EN_RN, ETIQUETAS_RN

    usuario_de = {}  # (registro_id, nombre) -> usuario
    global_de = {}   # nombre -> {usuarios}
    for p in m['ParticipacionRegistroParto'].objects.exclude(usuario='').values('registro_id', 'profesional', 'usuario'):
        usuario_de[(p['registro_id'], p['profesional'])] = p['usuario']
        global_de.setdefault(p['profesional'], set()).add(p['usuario'])
    for c in m['CambioRegistroParto'].objects.exclude(usuario='').values('registro_id', 'profesional', 'usuario'):
        usuario_de.setdefault((c['registro_id'], c['profesional']), c['usuario'])
        global_de.setdefault(c['profesional'], set()).add(c['usuario'])

    def buscar(registro_id, nombre):
        if not nombre:
            return ''
        u = usuario_de.get((registro_id, nombre))
        if u:
            return u
        candidatos = global_de.get(nombre) or set()
        return next(iter(candidatos)) if len(candidatos) == 1 else ''

    for nombre_modelo in ('ControlSangrado', 'ControlGlobo', 'ControlSutura', 'ControlFetocardia',
                          'ControlPostpartoInmediato', 'ControlRecienNacido'):
        for fila in m[nombre_modelo].objects.filter(registrado_usuario='').exclude(registrado_por=''):
            u = buscar(fila.registro_id, fila.registrado_por)
            if u:
                m[nombre_modelo].objects.filter(pk=fila.pk).update(registrado_usuario=u)
    for rn in m['ControlRecienNacido'].objects.filter(huella_subida_usuario='').exclude(huella_subida_por=''):
        u = buscar(rn.registro_id, rn.huella_subida_por)
        if u:
            m['ControlRecienNacido'].objects.filter(pk=rn.pk).update(huella_subida_usuario=u)

    # Campos: el primero que los registró según la bitácora (desde 2026-10-06).
    campo_registro = {etq: c for c, etq in CAMPOS_PARTO + CAMPOS_REGISTRO_EN_RN}
    campo_rn = {etq: c for c, etq in ETIQUETAS_RN.items()}
    duenos_reg, duenos_rn = {}, {}
    for c in (m['CambioRegistroParto'].objects.exclude(usuario='')
              .filter(seccion__in=('parto', 'recien_nacido'), accion__in=('registro', 'correccion'))
              .order_by('creado_en', 'id')):
        dueno = {'usuario': c.usuario, 'nombre': c.profesional or c.usuario}
        if c.detalle in campo_registro:
            duenos_reg.setdefault(c.registro_id, {}).setdefault(campo_registro[c.detalle], dueno)
            continue
        detalle, feto = c.detalle, 1
        if detalle.endswith(' (Feto B)'):
            detalle, feto = detalle[:-len(' (Feto B)')], 2
        if detalle in campo_rn:
            duenos_rn.setdefault((c.registro_id, feto), {}).setdefault(campo_rn[detalle], dueno)

    def completar(instancia, posibles, campos_validos):
        actuales = dict(instancia.duenos_campos or {})
        for campo, dueno in posibles.items():
            if campo in campos_validos and campo not in actuales \
                    and not vacio(type(instancia), campo, getattr(instancia, campo, None)):
                actuales[campo] = dueno
        if actuales != (instancia.duenos_campos or {}):
            type(instancia).objects.filter(pk=instancia.pk).update(duenos_campos=actuales)

    rn_validos = {f.name for f in m['ControlRecienNacido']._meta.concrete_fields} - _RN_SIN_DUENO
    for registro in m['RegistroParto'].objects.filter(pk__in=list(duenos_reg)):
        completar(registro, duenos_reg[registro.pk], CAMPOS_REGISTRO_CON_DUENO)
    for (registro_id, feto), posibles in duenos_rn.items():
        rn = m['ControlRecienNacido'].objects.filter(registro_id=registro_id, feto=feto).first()
        if rn is not None:
            completar(rn, posibles, rn_validos)
