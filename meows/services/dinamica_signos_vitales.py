"""
Puente entre los signos vitales de Dinámica (BD readonly DGEMPRES_NEXUS) y el
motor MEOWS.

A diferencia de lo que se pensó al principio, los signos vitales NO viven en
una tabla de formulario dinámico sin documentar (familia HCM*/HCMW*) sino en
el mecanismo estándar y documentado de Dinámica:

    HCNTIPSVIT  — catálogo de tipos de signo vital (OID, nombre, código)
    HCNSIGVIT   — una fila por cada toma: (HCNREGENF, HCNTIPSVIT, HCSVALOR, HCRHORREG)
    HCNREGENF   — registro de enfermería, referencia el ingreso (ADNINGRESO)
    HCNFOLIO    — el folio de historia clínica, referencia el ingreso (ADNINGRESO)

Se usa HCNSIGVIT (no HCNREGSIGVIT, el otro mecanismo que también existe en
Dinámica) porque HCNSIGVIT referencia el OID exacto del tipo de signo vital.
HCNREGSIGVIT en cambio solo guarda un código de "clase" (HCSCLASE) que varias
tipos comparten — por ejemplo PULSO, FETOCARDIO y los tres perímetros
comparten clase 0 — así que con HCNREGSIGVIT no se podría distinguir de forma
confiable un pulso de una fetocardia.

Mapeo confirmado con datos reales en Nexus (folio 16995986 y paciente con
cédula 27294904, revisados en sept/2026):

    OID  Nombre en Dinámica                   -> campo MEOWS
    15   TEMPERATURA                           -> temp
    16   TENSION            (ej. "120/80")     -> ta_sys / ta_dia (se separa por "/")
    17   PULSO                                 -> fc (respaldo)
    18   FRECUENCIA CARDIACA                   -> fc (preferido)
    19   RESPIRACION                           -> fr
    20   FETOCARDIO                            -> fcf
    22   SATURACION ARTERIAL DE OXIGENO        -> spo2

    "PULSO" y "FRECUENCIA CARDIACA" son dos signos vitales distintos en
    Dinámica y el personal los usa de forma inconsistente (a veces uno, a
    veces el otro, para la misma paciente). Por eso `fc` se completa
    primero con FRECUENCIA CARDIACA y, si esa toma no la trae, se usa PULSO.

Mapeo DE PRUEBA — Nivel de Conciencia y % de O2 requerido (2026-09-08):
    Se acaban de agregar 2 signos vitales nuevos, pero SOLO en el ambiente de
    PRUEBAS de Dinámica (base DGEMPRES01, servidor 172.20.100.188) — todavía
    NO existen en DGEMPRES_NEXUS (producción, 172.20.100.209). Mientras se
    valida esto con la jefe de sala de partos, la conexión 'readonly' apunta
    TEMPORALMENTE a DGEMPRES01 (ver .env) y se usan estos OID:

        OID  Nombre en Dinámica (DGEMPRES01)      -> campo MEOWS
        27   % DE O2 PARA SaO2 >= 95%              -> o2_req (parámetro NUEVO)
        28   NIVEL DE CONCIENCIA                   -> glasgow (ya existía)

    ⚠️ IMPORTANTE: estos números de OID son específicos de DGEMPRES01 — cada
    base de datos numera su propio catálogo HCNTIPSVIT de forma independiente,
    así que NO hay garantía de que sean los mismos OID cuando estos campos se
    confirmen y agreguen a DGEMPRES99/Nexus. Al volver a apuntar a Nexus, hay
    que volver a consultar HCNTIPSVIT ahí y actualizar estas dos constantes
    con los OID reales que le correspondan en esa base.

    El puntaje de "o2_req" (RangoParametro) también es PROVISIONAL — un solo
    tramo que da 0 puntos siempre, porque ni Dinámica ni la tabla física
    FRSPA-026 tienen todavía los rangos oficiales confirmados. Reemplazar por
    los tramos reales antes de usar esto con pacientes de verdad.
"""
from django.db import connections

# OIDs reales de HCNTIPSVIT, confirmados contra Nexus (ver docstring arriba).
_OID_TEMPERATURA = 15
_OID_TENSION = 16
_OID_PULSO = 17
_OID_FRECUENCIA_CARDIACA = 18
_OID_RESPIRACION = 19
_OID_FETOCARDIO = 20
_OID_SATURACION_O2 = 22

# OID de PRUEBA, válidos solo en DGEMPRES01 (ver docstring arriba) — NO
# confirmados todavía en Nexus/producción.
_OID_O2_REQUERIDO = 27
_OID_NIVEL_CONCIENCIA = 28

_OIDS_USADOS = (
    _OID_TEMPERATURA, _OID_TENSION, _OID_PULSO,
    _OID_FRECUENCIA_CARDIACA, _OID_RESPIRACION,
    _OID_FETOCARDIO, _OID_SATURACION_O2,
    _OID_O2_REQUERIDO, _OID_NIVEL_CONCIENCIA,
)


class MapeoNoConfigurado(Exception):
    """Se conserva por compatibilidad con quien la importe; ya no se lanza
    en operación normal porque el mapeo de los 7 parámetros disponibles
    está completo — Glasgow pendiente no bloquea el resto."""


def _a_numero(valor_texto):
    """Convierte '36,5' / '36.5' / '120' a float o int. None si no aplica."""
    if valor_texto is None:
        return None
    texto = str(valor_texto).strip().replace(",", ".")
    if not texto:
        return None
    try:
        numero = float(texto)
    except ValueError:
        return None
    return int(numero) if numero.is_integer() else numero


def _partir_tension(valor_texto):
    """Parte 'sistólica/diastólica' (ej. '120/80', '96 /64') en (120, 80)."""
    if not valor_texto or "/" not in valor_texto:
        return None, None
    sistolica_txt, _, diastolica_txt = valor_texto.partition("/")
    return _a_numero(sistolica_txt), _a_numero(diastolica_txt)


def obtener_signos_vitales_nuevos(folio: int, desde=None):
    """
    Trae las lecturas de signos vitales de Dinámica para un folio, agrupadas
    por hora de toma, opcionalmente solo las posteriores a `desde` (un
    datetime), para no reprocesar lo ya importado en corridas anteriores.

    Devuelve una lista de dicts, uno por hora de toma, con la forma:
        {
            "fecha_hora": datetime,
            "ta_sys": 120, "ta_dia": 80, "fc": 88, "fr": 18,
            "temp": 36.8, "spo2": 97, "glasgow": None, "fcf": 140,
            "o2_req": None,
        }
    (con None en los campos que esa toma no traiga diligenciados).
    """
    with connections['readonly'].cursor() as cur:
        cur.execute("SELECT ADNINGRESO FROM HCNFOLIO WHERE OID = %s", [folio])
        fila = cur.fetchone()
        if not fila or fila[0] is None:
            return []
        adningreso = fila[0]

        placeholders = ", ".join(["%s"] * len(_OIDS_USADOS))
        sql = f"""
            SELECT sv.HCRHORREG, sv.HCNTIPSVIT, sv.HCSVALOR
            FROM HCNSIGVIT sv
            JOIN HCNREGENF re ON re.OID = sv.HCNREGENF
            WHERE re.ADNINGRESO = %s
              AND sv.HCNTIPSVIT IN ({placeholders})
        """
        params = [adningreso, *_OIDS_USADOS]
        if desde is not None:
            sql += " AND sv.HCRHORREG > %s"
            params.append(desde)
        sql += " ORDER BY sv.HCRHORREG ASC"

        cur.execute(sql, params)
        filas = cur.fetchall()

    lecturas_por_hora = {}
    pulso_por_hora = {}

    for hora, tipo_oid, valor in filas:
        lectura = lecturas_por_hora.setdefault(hora, {
            "fecha_hora": hora,
            "ta_sys": None, "ta_dia": None, "fc": None, "fr": None,
            "temp": None, "spo2": None, "glasgow": None, "fcf": None,
            "o2_req": None,
        })
        if tipo_oid == _OID_TEMPERATURA:
            lectura["temp"] = _a_numero(valor)
        elif tipo_oid == _OID_TENSION:
            lectura["ta_sys"], lectura["ta_dia"] = _partir_tension(valor)
        elif tipo_oid == _OID_FRECUENCIA_CARDIACA:
            lectura["fc"] = _a_numero(valor)
        elif tipo_oid == _OID_PULSO:
            # Solo se aplica al final, como respaldo, si esa toma no trajo
            # FRECUENCIA CARDIACA (ver docstring: el personal usa ambos).
            pulso_por_hora[hora] = _a_numero(valor)
        elif tipo_oid == _OID_RESPIRACION:
            lectura["fr"] = _a_numero(valor)
        elif tipo_oid == _OID_FETOCARDIO:
            lectura["fcf"] = _a_numero(valor)
        elif tipo_oid == _OID_SATURACION_O2:
            lectura["spo2"] = _a_numero(valor)
        elif tipo_oid == _OID_NIVEL_CONCIENCIA:
            lectura["glasgow"] = _a_numero(valor)
        elif tipo_oid == _OID_O2_REQUERIDO:
            lectura["o2_req"] = _a_numero(valor)

    for hora, valor_pulso in pulso_por_hora.items():
        lectura = lecturas_por_hora.get(hora)
        if lectura is not None and lectura["fc"] is None:
            lectura["fc"] = valor_pulso

    return sorted(lecturas_por_hora.values(), key=lambda l: l["fecha_hora"])
