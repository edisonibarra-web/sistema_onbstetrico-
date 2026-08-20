from django.contrib import admin
from .models import (
    Paciente,
    Formulario,
    Parametro,
    Medicion,
    MedicionValor,
    ParametroMEOWS,
    RangoParametro,
)


@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ('numero_documento', 'nombres', 'apellidos', 'fecha_nacimiento', 'sexo')
    list_filter = ('sexo', 'aseguradora')
    search_fields = ('numero_documento', 'nombres', 'apellidos')
    ordering = ('apellidos', 'nombres')
    readonly_fields = ('numero_documento', 'fecha_nacimiento', 'edad', 'tipo_documento')


@admin.register(Formulario)
class FormularioAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'version', 'activo')
    list_filter = ('activo', 'version')
    search_fields = ('codigo', 'nombre')
    ordering = ('nombre', 'version')


@admin.register(Parametro)
class ParametroAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'unidad', 'orden', 'activo')
    list_filter = ('unidad', 'activo')
    search_fields = ('codigo', 'nombre')
    ordering = ('orden',)


@admin.register(Medicion)
class MedicionAdmin(admin.ModelAdmin):
    list_display = ('id', 'paciente', 'formulario', 'fecha_hora', 'meows_total', 'meows_riesgo')
    list_filter = ('formulario', 'meows_riesgo', 'fecha_hora')
    search_fields = ('paciente__numero_documento', 'paciente__nombres', 'paciente__apellidos')
    ordering = ('-fecha_hora',)
    readonly_fields = ('fecha_hora',)
    date_hierarchy = 'fecha_hora'


@admin.register(MedicionValor)
class MedicionValorAdmin(admin.ModelAdmin):
    list_display = ('medicion', 'parametro', 'valor', 'puntaje')
    list_filter = ('parametro', 'puntaje')
    search_fields = ('medicion__id', 'parametro__codigo', 'parametro__nombre')
    ordering = ('medicion', 'parametro__orden')


@admin.register(RangoParametro)
class RangoParametroAdmin(admin.ModelAdmin):
    list_display = ('parametro', 'valor_min', 'valor_max', 'score', 'orden', 'activo')
    list_filter = ('parametro', 'score', 'activo')
    search_fields = ('parametro__codigo', 'parametro__nombre')
    ordering = ('parametro__orden', 'orden', 'valor_min')
    list_editable = ('activo',)
    
    fieldsets = (
        ('Parámetro', {
            'fields': ('parametro',)
        }),
        ('Rango de Valores', {
            'fields': ('valor_min', 'valor_max', 'score', 'orden')
        }),
        ('Estado', {
            'fields': ('activo',)
        }),
    )


@admin.register(ParametroMEOWS)
class ParametroMEOWSAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'unidad', 'orden')
    list_filter = ('unidad',)
    search_fields = ('codigo', 'nombre')
    ordering = ('orden',)
    readonly_fields = ('codigo',)  # El código no debe modificarse después de creado
