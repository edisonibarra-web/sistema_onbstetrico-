from django.apps import AppConfig


class MeowsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'meows'
    
    def ready(self):
        """Importa los signals cuando la app está lista"""
        import meows.signals  # noqa