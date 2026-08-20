from django.contrib import admin
from .models import (
    Aseguradora,
    Paciente,
    Formulario,
    Item,
    Parametro,
    FormularioItemParametro,
    CampoParametro,
    Medicion,
    MedicionValor,
    Huella
)


@admin.register(Aseguradora)
class AseguradoraAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre')
    search_fields = ('nombre',)
    list_filter = ('nombre',)


@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ('id', 'num_historia_clinica', 'num_identificacion', 'nombres', 'fecha_nacimiento', 'tipo_sangre')
    search_fields = ('num_historia_clinica', 'num_identificacion', 'nombres')
    list_filter = ('tipo_sangre', 'fecha_nacimiento')
    date_hierarchy = 'fecha_nacimiento'


class FormularioItemParametroInline(admin.TabularInline):
    model = FormularioItemParametro
    extra = 1
    autocomplete_fields = ('item', 'parametro')


@admin.register(Formulario)
class FormularioAdmin(admin.ModelAdmin):
    list_display = ('id', 'codigo', 'version', 'num_hoja', 'paciente', 'aseguradora', 'estado', 'fecha_actualizacion')
    list_filter = ('estado', 'aseguradora', 'fecha_elabora', 'fecha_actualizacion')
    search_fields = ('codigo', 'paciente__nombres', 'paciente__num_identificacion')
    date_hierarchy = 'fecha_actualizacion'
    autocomplete_fields = ('paciente', 'aseguradora')
    inlines = [FormularioItemParametroInline]
    readonly_fields = ('fecha_actualizacion',)


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'codigo', 'nombre')
    search_fields = ('codigo', 'nombre')
    list_filter = ('codigo',)


class CampoParametroInline(admin.TabularInline):
    model = CampoParametro
    extra = 1
    fields = ('codigo', 'nombre', 'tipo_valor', 'unidad', 'orden')


@admin.register(Parametro)
class ParametroAdmin(admin.ModelAdmin):
    list_display = ('id', 'codigo', 'nombre', 'item', 'unidad', 'orden', 'activo')
    list_filter = ('item', 'activo', 'orden')
    search_fields = ('codigo', 'nombre', 'item__nombre')
    autocomplete_fields = ('item',)
    inlines = [CampoParametroInline]


@admin.register(FormularioItemParametro)
class FormularioItemParametroAdmin(admin.ModelAdmin):
    list_display = ('id', 'formulario', 'item', 'parametro', 'requerido')
    list_filter = ('requerido', 'item', 'parametro')
    search_fields = ('formulario__codigo', 'item__nombre', 'parametro__nombre')
    autocomplete_fields = ('formulario', 'item', 'parametro')


@admin.register(CampoParametro)
class CampoParametroAdmin(admin.ModelAdmin):
    list_display = ('id', 'codigo', 'nombre', 'parametro', 'tipo_valor', 'unidad', 'orden')
    list_filter = ('tipo_valor', 'parametro', 'orden')
    search_fields = ('codigo', 'nombre', 'parametro__nombre')
    autocomplete_fields = ('parametro',)


class MedicionValorInline(admin.TabularInline):
    model = MedicionValor
    extra = 1
    fields = ('campo', 'valor_number', 'valor_text', 'valor_boolean', 'valor_json')


@admin.register(Medicion)
class MedicionAdmin(admin.ModelAdmin):
    list_display = ('id', 'formulario', 'parametro', 'tomada_en', 'observacion')
    list_filter = ('parametro', 'tomada_en')
    search_fields = ('formulario__codigo', 'parametro__nombre', 'observacion')
    date_hierarchy = 'tomada_en'
    autocomplete_fields = ('formulario', 'parametro')
    inlines = [MedicionValorInline]


@admin.register(MedicionValor)
class MedicionValorAdmin(admin.ModelAdmin):
    list_display = ('id', 'medicion', 'campo', 'valor_number', 'valor_text', 'valor_boolean')
    list_filter = ('campo', 'campo__tipo_valor')
    search_fields = ('medicion__formulario__codigo', 'campo__nombre')
    autocomplete_fields = ('medicion', 'campo')
@admin.register(Huella)
class HuellaAdmin(admin.ModelAdmin):
    list_display = ('id', 'paciente_id', 'formulario_id', 'usuario', 'fecha')
    search_fields = ('paciente_id', 'formulario_id', 'usuario')
    list_filter = ('fecha', 'usuario')
    readonly_fields = ('fecha',)
