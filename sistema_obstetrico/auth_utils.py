"""
Helper compartido por las apps del proyecto para proteger vistas función con login.

Se evalúa una sola vez, al importar el módulo (arranque del proceso), porque
settings.REQUIRE_LOGIN es un valor de entorno fijo para la vida del proceso, no algo que
cambie por request.
"""
from django.conf import settings
from django.contrib.auth.decorators import login_required


def login_required_if_enabled(view_func):
    """Exige sesión iniciada solo si settings.REQUIRE_LOGIN es True."""
    if settings.REQUIRE_LOGIN:
        return login_required(view_func)
    return view_func


# ---------------------------------------------------------------------------
# Nombre del profesional en sesión (para autocompletar el campo "Responsable").
# request.session['dgh_info'] lo llena frecuenciafetal.auth_dgh al validar
# contra Dinámica y también registro_usuario_view para cuentas locales.
# ---------------------------------------------------------------------------

def nombre_profesional_sesion(request):
    """
    Nombre completo del profesional en sesión, para precargar "RESPONSABLE".

    2026-09-14: HALLAZGO -- antes, si no había dgh_info (típicamente una
    cuenta local/admin que nunca pasó por DGHBackend), esta función devolvía
    '' -- y el JS de cada formulario, al ver el campo vacío, caía a mostrar
    el "responsable" YA GUARDADO en el registro existente de esa paciente
    (quien lo diligenció en un turno anterior, ej. una enfermera real). Un
    admin abriendo el registro de una paciente que otra persona ya había
    guardado veía el nombre de ESA persona en vez del suyo propio o vacío --
    parecía que la sesión "filtraba" el nombre de otro usuario, cuando en
    realidad era ese fallback de "campo vacío -> usar lo ya guardado" el que
    disparaba.

    Ahora, si no hay dgh_info pero SÍ hay un usuario autenticado localmente
    (ModelBackend), se usa su nombre completo o su username -- así el campo
    nunca queda vacío para una sesión real, y el fallback de "usar lo ya
    guardado" solo se activa cuando de verdad no hay NADIE identificable
    (ej. REQUIRE_LOGIN=False, sin sesión de ningún tipo).
    """
    try:
        nombre_dgh = (request.session.get('dgh_info', {}) or {}).get('nombre_completo')
        if nombre_dgh:
            return nombre_dgh
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            return user.get_full_name() or user.username
        return ''
    except Exception:
        return ''


def profesional_actual_context(request):
    """
    Context processor: expone 'profesional_nombre_sesion' en TODOS los
    templates (ej. sidebar.html, para mostrar quién tiene la sesión
    iniciada), sin que cada vista tenga que pasarlo a mano. Las vistas que
    ya lo pasan explícitamente en su propio context (trabajoparto, meows,
    frecuenciafetal) no se ven afectadas: ese valor explícito sigue ganando
    igual, este solo cubre las páginas que no lo pasaban.
    """
    return {'profesional_nombre_sesion': nombre_profesional_sesion(request)}
