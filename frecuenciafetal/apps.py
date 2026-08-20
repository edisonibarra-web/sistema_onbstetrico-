from django.apps import AppConfig


class FrecuenciaFetalConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'frecuenciafetal'
    label = 'registros'
    verbose_name = 'Registros de Parto y Control de Frecuencia'
