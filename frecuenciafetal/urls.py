from django.urls import path, include
from rest_framework_nested import routers
from . import views
from .views import (
    FormularioRegistroView,
    RegistroPartoViewSet, ControlFetocardiaViewSet,
    ControlRecienNacidoViewSet, ControlPostpartoViewSet
)

# Router principal
router = routers.DefaultRouter()
router.register(r'registros', RegistroPartoViewSet, basename='registro')

# Rutas anidadas: /api/registros/{registro_pk}/fetocardia/
registros_router = routers.NestedDefaultRouter(router, r'registros', lookup='registro')
registros_router.register(r'fetocardia', ControlFetocardiaViewSet, basename='fetocardia')
registros_router.register(r'recien-nacido', ControlRecienNacidoViewSet, basename='recien-nacido')
registros_router.register(r'postparto', ControlPostpartoViewSet, basename='postparto')

urlpatterns = [
    path('', FormularioRegistroView.as_view(), name='home'),
    # Puente para entornos donde este módulo queda montado en raíz.
    path('meows/', include('meows.urls')),
    path('captura-huella/', views.captura_huella, name='captura_huella'),
    path('api/', include(router.urls)),
    path('api/', include(registros_router.urls)),
    path('api/guardar-huella-bebe/', views.guardar_huella_bebe, name='guardar_huella_bebe'),
    path('api/guardar-huella/', views.guardar_huella, name='guardar_huella'),
    path('api/guardar-firma/', views.guardar_firma_digital, name='guardar_firma_digital'),
    path('api/huella/<str:documento>/', views.ultima_huella, name='ultima_huella'),
    path('ver-huella/<str:documento>/', views.ver_huella, name='ver_huella'),
]

# ENDPOINTS DISPONIBLES:
# GET/POST   /api/registros/
# GET/PUT/PATCH/DELETE /api/registros/{id}/
# GET        /api/registros/buscar/?q=nombre
# GET        /api/registros/sala-partos/?q=opcional  (DGEMPRES03, solo lectura)
# GET        /api/registros/{id}/pdf/
# GET/POST   /api/registros/{id}/huella-pie/  (GET: devuelve huella_base64 para vista)
# GET/POST   /api/registros/{id}/fetocardia/
# GET/POST   /api/registros/{id}/recien-nacido/
# GET/POST   /api/registros/{id}/postparto/
