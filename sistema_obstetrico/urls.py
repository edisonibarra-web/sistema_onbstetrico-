"""
URLs del sistema obstétrico.
Punto de entrada: http://127.0.0.1:8000/ → redirige a /atencion/ (dashboard)

Estructura robusta: cada módulo tiene prefijo explícito, sin path('', ...) ambiguos.
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView
from django.shortcuts import redirect
from obstetriciaunificador.models import AtencionParto
from frecuenciafetal.views import login_view, logout_view


def home(request):
    """Raíz / → redirige SIEMPRE a /atencion/ (dashboard)."""
    return redirect("/atencion/")


from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url='/static/favicon.svg', permanent=True)),
    path('admin/', admin.site.urls),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('accounts/login/', RedirectView.as_view(url='/login/', permanent=False)),
    path('api/', include('trabajoparto.api_urls')),

    # Módulos con prefijos explícitos (evita conflictos de rutas)
    path('meows/', include('meows.urls')),
    path('fetal/', include('frecuenciafetal.urls')),
    path('parto/', include('trabajoparto.urls')),
    path('atencion/', include('obstetriciaunificador.urls')),

    # Raíz: ÚNICA ruta que captura / → redirige a /atencion/1/
    path('', home, name='home'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)