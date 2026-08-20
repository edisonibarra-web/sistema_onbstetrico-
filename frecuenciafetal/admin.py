from django.contrib import admin
from .models import (
    RegistroParto,
    ControlFetocardia,
    ControlRecienNacido,
    GlucometriaRecienNacido,
    ControlPostpartoInmediato,
)


class ControlFetocardiaInline(admin.TabularInline):
    model = ControlFetocardia
    extra = 1


class ControlRecienNacidoInline(admin.StackedInline):
    model = ControlRecienNacido
    extra = 0


class GlucometriaRecienNacidoInline(admin.TabularInline):
    model = GlucometriaRecienNacido
    extra = 1


class ControlPostpartoInmediatoInline(admin.TabularInline):
    model = ControlPostpartoInmediato
    extra = 1


@admin.register(RegistroParto)
class RegistroPartoAdmin(admin.ModelAdmin):
    list_display = ('nombre_paciente', 'identificacion', 'edad_gestacional', 'tipo_parto', 'created_at')
    list_filter = ('tipo_parto', 'episiotomia', 'created_at')
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
    inlines = [GlucometriaRecienNacidoInline]


@admin.register(GlucometriaRecienNacido)
class GlucometriaRecienNacidoAdmin(admin.ModelAdmin):
    list_display = ('control_rn', 'hora', 'resultado')


@admin.register(ControlPostpartoInmediato)
class ControlPostpartoInmediatoAdmin(admin.ModelAdmin):
    list_display = ('registro', 'minuto_control', 'fecha', 'hora', 'tension_arterial', 'temperatura')
    list_filter = ('fecha',)
