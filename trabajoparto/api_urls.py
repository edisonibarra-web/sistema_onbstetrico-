from rest_framework.routers import DefaultRouter
from . import views

# Configuración del router de REST Framework
router = DefaultRouter()
router.register(r'aseguradoras', views.AseguradoraViewSet, basename='aseguradora')
router.register(r'pacientes', views.PacienteViewSet, basename='paciente')
router.register(r'formularios', views.FormularioViewSet, basename='formulario')
router.register(r'items', views.ItemViewSet, basename='item')
router.register(r'parametros', views.ParametroViewSet, basename='parametro')
router.register(r'campos-parametro', views.CampoParametroViewSet, basename='campo-parametro')
router.register(r'formularios-items-parametros', views.FormularioItemParametroViewSet, basename='formulario-item-parametro')
router.register(r'mediciones', views.MedicionViewSet, basename='medicion')
router.register(r'mediciones-valores', views.MedicionValorViewSet, basename='medicion-valor')

urlpatterns = router.urls

