"""
Database Router para separar la BD local (default) de la BD externa (readonly).
Evita que Django intente migrar o verificar la BD remota al arrancar.
"""


MODELOS_EXTERNOS = {
    'Genpacien', 'Gendiagno', 'Gendetcon', 'Hpngrupos', 'Hpnsubgru',
    'Hpndefcam', 'Adningreso', 'Hpnestanc', 'Hcnfolio', 'Hcndiapac',
    'Hcmwingin',
}


class ReadonlyRouter:
    """
    Enruta los modelos externos (managed=False) a la BD 'readonly'
    y los modelos propios a 'default'. Bloquea migraciones en 'readonly'.
    """

    def db_for_read(self, model, **hints):
        if model.__name__ in MODELOS_EXTERNOS:
            return 'readonly'
        return 'default'

    def db_for_write(self, model, **hints):
        if model.__name__ in MODELOS_EXTERNOS:
            return 'readonly'
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == 'readonly':
            return False
        return True
