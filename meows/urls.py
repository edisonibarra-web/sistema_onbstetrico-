"""
URLs para la app meows
"""
from django.urls import path
from meows import views

urlpatterns = [
    path("crear/", views.abrir_meows_desde_atencion, name="abrir_meows_desde_atencion"),
    path("crear/<str:doc>/", views.abrir_meows_desde_atencion, name="abrir_meows_desde_atencion_doc"),
    path("historial-doc/<str:doc>/", views.abrir_historial_meows_desde_documento, name="historial_meows_doc"),
    path("nuevo/<int:paciente_id>/", views.crear_medicion_meows, name="crear_meows"),
    path("resultado/<int:medicion_id>/", views.ver_meows, name="ver_meows"),
    path("historial/<int:paciente_id>/", views.historial_meows_paciente, name="historial_meows"),
    path("pdf/<int:paciente_id>/", views.generar_pdf_meows_paciente, name="generar_pdf_meows"),
    # API endpoints
    path("api/rangos/", views.api_rangos_meows, name="api_rangos_meows"),
    path("api/calcular-score/", views.api_calcular_score, name="api_calcular_score"),
    path("api/buscar-paciente/", views.api_buscar_paciente, name="api_buscar_paciente"),
    path("api/pacientes-activos/", views.api_pacientes_activos, name="api_pacientes_activos"),
    path("api/save-biometrics/", views.guardar_huella, name="guardar_huella"),
    path("api/huella/<str:paciente_id>/", views.ultima_huella, name="ultima_huella"),
]

