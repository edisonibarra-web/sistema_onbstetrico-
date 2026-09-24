from django.contrib import admin

from .models import AtencionParto, DocumentoRepositorio


@admin.register(AtencionParto)
class AtencionPartoAdmin(admin.ModelAdmin):
    list_display = ('id', 'paciente', 'numero_ingreso', 'fecha_ingreso_dinamica', 'fecha_inicio', 'estado')
    search_fields = ('paciente', 'numero_ingreso')


@admin.register(DocumentoRepositorio)
class DocumentoRepositorioAdmin(admin.ModelAdmin):
    list_display = ('creado_en', 'cedula', 'numero_ingreso', 'formato', 'estado', 'modo', 'nombre_archivo', 'enviado_por')
    list_filter = ('estado', 'modo', 'formato')
    search_fields = ('cedula', 'numero_ingreso', 'nombre_archivo')
    readonly_fields = [f.name for f in DocumentoRepositorio._meta.fields]
