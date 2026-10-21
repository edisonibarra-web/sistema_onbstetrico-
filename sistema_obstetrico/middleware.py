"""
2026-10-20: personal autorizado SOLO a la Consulta histórica de pacientes
egresadas (p. ej. archivo; permiso obstetricia.solo_consulta_historica, ver
obstetriciaunificador/historico.py). Ocultar el menú no basta: aquí se bloquea
en el servidor cualquier otra pantalla o API aunque se escriba la dirección.
El resto del personal y el superusuario no se ven afectados.

2026-10-21: además, quien tenga "Sin acceso a la aplicación"
(obstetricia.sin_acceso_aplicacion) pierde la sesión y no entra a nada.
"""
from django.http import JsonResponse
from django.shortcuts import redirect

INICIO_SOLO_HISTORICO = '/atencion/historico/'

# Lo único que puede abrir el personal de "solo histórico".
RUTAS_PERMITIDAS = (
    '/atencion/historico/',
    '/atencion/api/historico/',
    '/atencion/manual/',
    '/login/',
    '/logout/',
    '/static/',
    '/favicon.ico',
)


class RestriccionSoloHistoricoMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from obstetriciaunificador.historico import MENSAJE_SIN_ACCESO, es_sin_acceso, es_solo_historico

        ruta = request.path
        usuario = getattr(request, 'user', None)
        # 2026-10-21: "Sin acceso a la aplicación": se cierra la sesión en el
        # siguiente clic (también la que ya estaba abierta) y no entra a nada.
        if not ruta.startswith('/static/') and es_sin_acceso(usuario):
            from django.contrib.auth import logout
            logout(request)
            if ruta.startswith('/login/'):
                return self.get_response(request)
            if '/api/' in ruta or 'application/json' in request.headers.get('accept', ''):
                return JsonResponse({'ok': False, 'mensaje': MENSAJE_SIN_ACCESO}, status=403)
            return redirect('/login/?sin_acceso=1')
        if not ruta.startswith(RUTAS_PERMITIDAS) and es_solo_historico(usuario):
            if '/api/' in ruta or request.headers.get('x-requested-with') == 'XMLHttpRequest' \
                    or 'application/json' in request.headers.get('accept', ''):
                return JsonResponse(
                    {'ok': False, 'mensaje': 'Su usuario solo tiene acceso a la consulta histórica.'}, status=403,
                )
            return redirect(INICIO_SOLO_HISTORICO)
        return self.get_response(request)
