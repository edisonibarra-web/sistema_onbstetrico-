"""
Motor de la conexión 'readonly' (Dinámica): el mismo 'mssql' de siempre, con
un "cortocircuito" cuando Dinámica no responde.

2026-09-24 -- causa de lentitud encontrada: si el servidor de Dinámica no
responde (red caída, VPN, servidor apagado), CADA intento de conexión deja la
pantalla congelada hasta que vence el timeout del driver. Con muchas partes
de la app consultando Dinámica (Sala de Partos, búsquedas, edad, ingresos...)
eso se sentía como "la app se volvió lenta".

Aquí: tras una falla de conexión se deja de intentar durante
SEGUNDOS_PAUSA_DINAMICA; mientras tanto cualquier consulta a 'readonly' falla
al instante con el mismo tipo de error (OperationalError), que todo el código
ya maneja como "Dinámica no disponible". Solo afecta el ESTABLECER la
conexión: una conexión ya abierta y las consultas normales no cambian.
"""
from django.core.cache import cache
from mssql.base import Database, DatabaseWrapper as MssqlDatabaseWrapper

# Misma clave que usa frecuenciafetal.sala_partos_db.dinamica_disponible().
CLAVE_DINAMICA_CAIDA = 'dinamica_readonly_caida'
SEGUNDOS_PAUSA_DINAMICA = 60


class DatabaseWrapper(MssqlDatabaseWrapper):
    def get_new_connection(self, conn_params):
        if cache.get(CLAVE_DINAMICA_CAIDA):
            raise Database.OperationalError(
                '08001', 'Dinámica no disponible (en pausa tras una falla de conexión reciente).'
            )
        try:
            return super().get_new_connection(conn_params)
        except Database.Error:
            cache.set(CLAVE_DINAMICA_CAIDA, True, SEGUNDOS_PAUSA_DINAMICA)
            raise
