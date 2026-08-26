"""
Rutas bajo prefijo /atencion/ (definido en sistema_obstetrico/urls.py).
Ej: /atencion/1/ → atencion_detalle
"""
from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('manual/', views.manual_usuario, name='manual_usuario'),
    path('api/datos-paciente-unificado/', views.api_datos_paciente_unificado, name='api_datos_paciente_unificado'),
    path('api/registrar-desde-sala-partos/', views.registrar_atencion_desde_sala_partos, name='registrar_atencion_desde_sala_partos'),
    path('sala-de-partos/', views.sala_de_partos, name='sala_de_partos'),
    path('<int:atencion_id>/guardar-datos-paciente/', views.guardar_datos_paciente_card, name='guardar_datos_paciente_card'),
    path('<int:id>/', views.atencion_detalle, name='atencion_detalle'),
    path('<int:id>/pdf/', views.pdf_atencion, name='pdf_atencion'),
]