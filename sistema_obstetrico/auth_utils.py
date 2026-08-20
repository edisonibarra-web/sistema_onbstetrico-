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
