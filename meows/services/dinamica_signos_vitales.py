"""
Puente entre la tabla de signos vitales de Dinámica (BD readonly DGEMPRES_NEXUS)
y el motor MEOWS.

⚠️ PENDIENTE DE CONFIGURAR ⚠️
Los valores de TABLA_SIGNOS_VITALES, COLUMNA_FECHA_HORA y MAPEO_CAMPOS son
placeholders. Hay que reemplazarlos por los reales una vez identificados con
el comando de descubrimiento:

    python manage.py dinamica_diff_folio <FOLIO_OID> --modo antes
    ... diligenciar el signo vital de prueba en Dinámica ...
    python manage.py dinamica_diff_folio <FOLIO_OID> --modo despues --esperado <valor>

Repetir una vez por cada uno de los 8 parámetros para completar el mapeo.

No se sabe todavía si los signos vitales quedan en HCMWINGIN (mismo formulario
de ingreso de donde ya se leen grupo sanguíneo/gestas) o en otra tabla de la
familia HCM*/HCMW* con una fila por cada toma (lo más probable, dado que este
monitoreo se repite varias veces por turno). Si es una tabla de tomas
repetidas, probablemente tenga su propia columna de fecha/hora del registro
(no confundir con la fecha del folio) — ese es COLUMNA_FECHA_HORA.
"""
from django.db import connections


# TODO: reemplazar por el nombre real de la tabla (ver docstring arriba).
TABLA_SIGNOS_VITALES = None

# TODO: columna datetime que indica cuándo se tomó cada lectura (no HCFECFOL).
COLUMNA_FECHA_HORA = None

# TODO: reemplazar cada None por el código HCCM0XN## real de esa tabla.
# Las claves (ta_sys, ta_dia, ...) son fijas — son los mismos códigos que usa
# meows/meows_params.py y el motor de cálculo, no se deben cambiar.
MAPEO_CAMPOS = {
    "ta_sys": None,    # Presión arterial sistólica (mmHg)
    "ta_dia": None,    # Presión arterial diastólica (mmHg)
    "fc": None,        # Frecuencia cardiaca (lpm)
    "fr": None,        # Frecuencia respiratoria (rpm)
    "temp": None,      # Temperatura corporal (°C)
    "spo2": None,      # Saturación de oxígeno (%)
    "glasgow": None,   # Escala de Glasgow — OJO al mapear este: la tarjeta de MEOWS
                       # solo acepta "15" (ALERTA) o "14" (NO ALERTA), no la escala real
                       # 3-15. Si en Dinámica queda el puntaje real de Glasgow, hay que
                       # traducirlo aquí (15 -> "15", cualquier otro valor -> "14") antes
                       # de devolverlo, no pasarlo tal cual.
    "fcf": None,       # Frecuencia cardiaca fetal (lpm)
}


class MapeoNoConfigurado(Exception):
    """Se lanza mientras TABLA_SIGNOS_VITALES/COLUMNA_FECHA_HORA/MAPEO_CAMPOS sigan con placeholders."""


def _validar_configuracion():
    faltantes = [codigo for codigo, columna in MAPEO_CAMPOS.items() if columna is None]
    if TABLA_SIGNOS_VITALES is None or COLUMNA_FECHA_HORA is None or faltantes:
        raise MapeoNoConfigurado(
            "El mapeo de columnas de Dinámica para signos vitales todavía no está "
            "configurado en meows/services/dinamica_signos_vitales.py. "
            f"Faltan: TABLA_SIGNOS_VITALES={TABLA_SIGNOS_VITALES!r}, "
            f"COLUMNA_FECHA_HORA={COLUMNA_FECHA_HORA!r}, "
            f"campos sin mapear={faltantes}. "
            "Usa el comando 'dinamica_diff_folio' para identificarlas primero."
        )


def obtener_signos_vitales_nuevos(folio: int, desde=None):
    """
    Trae las lecturas de signos vitales de Dinámica para un folio, opcionalmente
    solo las posteriores a `desde` (un datetime), para no reprocesar lo ya
    importado en corridas anteriores del job de sincronización.

    Devuelve una lista de dicts, uno por lectura, con la forma:
        {
            "fecha_hora": datetime,
            "ta_sys": 120, "ta_dia": 80, "fc": 88, "fr": 18,
            "temp": 36.8, "spo2": 97, "glasgow": 15, "fcf": 140,
        }
    (con None en los campos que esa lectura no traiga diligenciados).

    Lanza MapeoNoConfigurado si el mapeo de columnas aún no se llenó.
    """
    _validar_configuracion()

    columnas_sql = ", ".join(f"{col} AS {codigo}" for codigo, col in MAPEO_CAMPOS.items())
    sql = f"""
        SELECT {COLUMNA_FECHA_HORA} AS fecha_hora, {columnas_sql}
        FROM {TABLA_SIGNOS_VITALES}
        WHERE HCNFOLIO = %s
    """
    params = [folio]
    if desde is not None:
        sql += f" AND {COLUMNA_FECHA_HORA} > %s"
        params.append(desde)
    sql += f" ORDER BY {COLUMNA_FECHA_HORA} ASC"

    with connections['readonly'].cursor() as cur:
        cur.execute(sql, params)
        columnas = [c[0].lower() for c in cur.description]
        filas = [dict(zip(columnas, fila)) for fila in cur.fetchall()]

    return filas
