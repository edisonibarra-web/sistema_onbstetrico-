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

    "PULSO" y "FRECUENCIA CARDIACA" son dos signos vitales distintos en
    Dinámica y el personal los usa de forma inconsistente (a veces uno, a
    veces el otro, para la misma paciente). Por eso `fc` se completa
    primero con FRECUENCIA CARDIACA y, si esa toma no la trae, se usa PULSO.

    OID 22 (SATURACION ARTERIAL DE OXIGENO / SpO2) YA NO SE EXTRAE — quitado
    del sistema MEOWS por completo el 2026-09-09 a pedido de enfermería. Era
    un sustituto temporal de "% de O2 requerido" (ver bloque de o2_req más
    abajo) mientras ese campo oficial no existía en Dinámica; con o2_req ya
    disponible, SpO2 sobra (el Parametro 'spo2' quedó con activo=False en la
    base de datos). Si se necesitara alguna vez de nuevo, el OID sigue siendo
    22 y el mapeo era `lectura["spo2"] = _a_numero(valor)`.

Mapeo DE PRUEBA — % de O2 requerido y Nivel de Conciencia (2026-09-08, ajustado
2026-09-09 tras el rediseño del formulario de enfermería en Dinámica):
    Estos campos existen SOLO en el ambiente de PRUEBAS de Dinámica (base
    DGEMPRES01, servidor 172.20.100.188) — todavía NO existen en
    DGEMPRES_NEXUS (producción, 172.20.100.209). Mientras se valida esto con
    la jefe de sala de partos, la conexión 'readonly' apunta TEMPORALMENTE a
    DGEMPRES01 (ver .env).

    2026-09-09: el formulario de "Registro Signos Vitales" de enfermería se
    reorganizó de 2 campos numéricos a 5 opciones — una por cada tramo de la
    tabla física FRSPA-026, en vez de un solo número libre:

        OID  Nombre en Dinámica (DGEMPRES01)   Rango declarado
        27   AIRE AMBIENTE                     0 - 1     (era el "% de O2
                                                          requerido" original,
                                                          solo le cambiaron
                                                          el nombre)
        29   24-39%                            24 - 39
        30   >=40%                             40 - (sin tope)
        28   ALERTA=GLASGOW 15                 0 - 1     (era "NIVEL DE
                                                          CONCIENCIA" original,
                                                          solo le cambiaron
                                                          el nombre)
        31   NO ALERTA=GLASGOW<15              sin rango

    La enfermera diligencia UNA sola de las 3 opciones de O2 y UNA sola de
    las 2 de conciencia por toma (confirmado con el usuario 2026-09-09),
    dejando las demás en blanco — como un grupo de radio-buttons.

    ⚠️ OID 27 y 28 son los MISMOS que ya usábamos desde el 2026-09-08 (antes
    numéricos libres) — a pesar del rango declarado "0-1" en el catálogo, en
    la práctica TODAVÍA aceptan y guardan un número libre igual que antes
    (confirmado con datos reales: hay tomas con HCSVALOR="23","41","45" en
    OID 27 y "21" en OID 28 — ninguno es 0 ni 1). Por eso, para O2 se toma el
    NÚMERO REAL que traiga cualquiera de los 3 OID (27/29/30, el que la
    enfermera haya diligenciado) como `o2_req` tal cual — igual que antes,
    solo que ahora puede venir de 3 sitios en vez de uno. Para conciencia, en
    cambio, NO se usa el número que traiga OID 28/31 (no es confiable como
    puntaje de Glasgow real, ver hallazgo previo del valor "21"): alcanza con
    saber CUÁL de los dos EXISTE para esa toma — 28 presente -> Alerta
    (Glasgow 15, se fuerza el valor a 15); 31 presente -> No Alerta (se fuerza
    a 0, cualquier valor 0-14 dispara el mismo puntaje 3 en RangoParametro).

    ⚠️ IMPORTANTE: estos números de OID son específicos de DGEMPRES01 — cada
    base de datos numera su propio catálogo HCNTIPSVIT de forma independiente,
    así que NO hay garantía de que sean los mismos OID cuando estos campos se
    confirmen y agreguen a DGEMPRES99/Nexus. Al volver a apuntar a Nexus, hay
    que volver a consultar HCNTIPSVIT ahí y actualizar estas constantes con
    los OID reales que le correspondan en esa base.

    El puntaje de "o2_req" (RangoParametro) ya tiene sus 3 tramos oficiales
    confirmados (2026-09-09, tabla física FRSPA-026): 21% -aire ambiente-
    (0-23%) -> 0, 24-39% -> 1, >=40% -> 3 (sin tramo intermedio 2). Ver
    meows/services/grid.py:_ETIQUETAS_ESPECIALES para cómo se rotulan estas
    franjas en la Línea de Tiempo Clínica.
"""
from django.db import connections

# OIDs reales de HCNTIPSVIT, confirmados contra Nexus (ver docstring arriba).
_OID_TEMPERATURA = 15
_OID_TENSION = 16
_OID_PULSO = 17
_OID_FRECUENCIA_CARDIACA = 18
_OID_RESPIRACION = 19
_OID_FETOCARDIO = 20
# _OID_SATURACION_O2 = 22  # SpO2 — quitado del sistema MEOWS el 2026-09-09 (ver docstring arriba)

# OID de PRUEBA, válidos solo en DGEMPRES01 (ver docstring arriba) — NO
# confirmados todavía en Nexus/producción. El formulario de enfermería usa
# uno de estos 3 para O2 y uno de estos 2 para conciencia, nunca ambos del
# mismo grupo a la vez (ver docstring).
_OID_O2_AIRE_AMBIENTE = 27  # numérico libre pese al nombre, ver docstring
_OID_O2_24_39 = 29
_OID_O2_MAYOR_40 = 30
_OID_GLASGOW_ALERTA = 28  # numérico libre pese al nombre, pero se ignora su valor
_OID_GLASGOW_NO_ALERTA = 31

_OIDS_USADOS = (
    _OID_TEMPERATURA, _OID_TENSION, _OID_PULSO,
    _OID_FRECUENCIA_CARDIACA, _OID_RESPIRACION,
    _OID_FETOCARDIO,
    _OID_O2_AIRE_AMBIENTE, _OID_O2_24_39, _OID_O2_MAYOR_40,
    _OID_GLASGOW_ALERTA, _OID_GLASGOW_NO_ALERTA,
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
            "temp": 36.8, "glasgow": None, "fcf": 140,
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
            "temp": None, "glasgow": None, "fcf": None,
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
        elif tipo_oid in (_OID_O2_AIRE_AMBIENTE, _OID_O2_24_39, _OID_O2_MAYOR_40):
            # Uno solo de los 3 trae dato por toma (ver docstring) — el que
            # sea, su número real es el % de O2 requerido.
            lectura["o2_req"] = _a_numero(valor)
        elif tipo_oid == _OID_GLASGOW_ALERTA:
            # No se usa el número que traiga (no es un Glasgow real, ver
            # docstring) — que este OID exista para la toma YA significa
            # "Alerta", se fuerza a 15 (única franja de RangoParametro que
            # da puntaje 0).
            lectura["glasgow"] = 15
        elif tipo_oid == _OID_GLASGOW_NO_ALERTA:
            # Mismo criterio: "No Alerta" se fuerza a un valor dentro de la
            # franja 0-14 (puntaje 3), sin importar qué número traiga.
            lectura["glasgow"] = 0

    for hora, valor_pulso in pulso_por_hora.items():
        lectura = lecturas_por_hora.get(hora)
        if lectura is not None and lectura["fc"] is None:
            lectura["fc"] = valor_pulso

    return sorted(lecturas_por_hora.values(), key=lambda l: l["fecha_hora"])
