from django.urls import path

from .views import (
    parto_home,
    generar_pdf_formulario,
    generar_pdf_paciente,
    preview_pdf_paciente,
    vista_impresion_formulario,
    ver_huella,
    guardar_huella
)

urlpatterns = [
    path('', parto_home, name='parto_home'),
    # Endpoints de PDF (mantenidos en backend)
    path('formulario/<int:formulario_id>/pdf/', generar_pdf_formulario, name='generar_pdf_formulario'),
    path('formulario/<int:formulario_id>/impresion/', vista_impresion_formulario, name='vista_impresion_formulario'),
    path('pacientes/<int:paciente_id>/pdf/', generar_pdf_paciente, name='generar_pdf_paciente'),
    path('pacientes/<int:paciente_id>/preview/', preview_pdf_paciente, name='preview_pdf_paciente'),
    path('huella/ver/<str:documento>/', ver_huella, name='ver_huella'),
    path('api/guardar-huella/', guardar_huella, name='guardar_huella')
]
