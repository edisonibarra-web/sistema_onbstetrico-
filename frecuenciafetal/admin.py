from django.contrib import admin
from .models import (
    RegistroParto,
    ControlFetocardia,
    ControlRecienNacido,
    GlucometriaRecienNacido,
    ControlPostpartoInmediato,
    CambioRegistroParto,
)


class ControlFetocardiaInline(admin.TabularInline):
    model = ControlFetocardia
    extra = 1


class ControlRecienNacidoInline(admin.StackedInline):
    model = ControlRecienNacido
    extra = 0
    # 2026-09-30: la huella solo se sube desde el formulario (valida el PDF).
    readonly_fields = ('huella_pdf', 'huella_subida_por', 'huella_subida_en')


class GlucometriaRecienNacidoInline(admin.TabularInline):
    model = GlucometriaRecienNacido
    extra = 1


class ControlPostpartoInmediatoInline(admin.TabularInline):
    model = ControlPostpartoInmediato
    extra = 1


@admin.register(RegistroParto)
class RegistroPartoAdmin(admin.ModelAdmin):
    # 2026-09-22: completado_en/completado_por -- ver "Guardar Registro
    # Completo" en formulario.html. Visibles/filtrables acá para poder
    # auditar qué registros quedaron cerrados y cuáles siguen abiertos.
    list_display = ('nombre_paciente', 'identificacion', 'edad_gestacional', 'tipo_parto', 'created_at', 'completado_en')
    list_filter = ('tipo_parto', 'episiotomia', 'created_at', 'completado_en')
    search_fields = ('nombre_paciente', 'identificacion')
    inlines = [
        ControlFetocardiaInline,
        ControlRecienNacidoInline,
        ControlPostpartoInmediatoInline,
    ]


@admin.register(ControlFetocardia)
class ControlFetocardiaAdmin(admin.ModelAdmin):
    list_display = ('registro', 'fecha', 'hora', 'fetocardia', 'responsable')
    list_filter = ('fecha',)


@admin.register(ControlRecienNacido)
class ControlRecienNacidoAdmin(admin.ModelAdmin):
    list_display = ('registro', 'hora_nacimiento', 'genero', 'peso', 'talla', 'apgar_1min', 'apgar_5min')
    readonly_fields = ('huella_pdf', 'huella_subida_por', 'huella_subida_en')
    inlines = [GlucometriaRecienNacidoInline]


@admin.register(GlucometriaRecienNacido)
class GlucometriaRecienNacidoAdmin(admin.ModelAdmin):
    list_display = ('control_rn', 'hora', 'resultado')


@admin.register(ControlPostpartoInmediato)
class ControlPostpartoInmediatoAdmin(admin.ModelAdmin):
    list_display = ('registro', 'minuto_control', 'fecha', 'hora', 'tension_arterial', 'temperatura')
    list_filter = ('fecha',)


# 2026-10-06: bitácora de quién registró / corrigió / eliminó cada dato (solo consulta).
@admin.register(CambioRegistroParto)
class CambioRegistroPartoAdmin(admin.ModelAdmin):
    list_display = ('creado_en', 'registro', 'seccion', 'accion', 'detalle', 'profesional')
    list_filter = ('seccion', 'accion')
    search_fields = ('profesional', 'detalle', 'registro__identificacion')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
