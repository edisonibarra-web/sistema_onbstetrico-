"""
MÓDULO MEOWS
Motor lógico para cálculo y clasificación de riesgo materno.

✅ Reglas dinámicas desde base de datos – permite cambiar rangos sin modificar código.
"""
from django.core.cache import cache
from meows.models import Parametro, RangoParametro


# ============================================================================
# 8️⃣ FUNCIÓN GENÉRICA DE CÁLCULO DE PUNTAJE DESDE BASE DE DATOS
# ============================================================================

def calcular_score_desde_bd(codigo_parametro: str, valor: float) -> int:
    """
    Calcula el puntaje para un parámetro usando rangos desde la base de datos.
    
    Args:
        codigo_parametro: Código del parámetro (ej: "fc", "ta_sys", "fr")
        valor: Valor numérico a evaluar
        
    Returns:
        int: Puntaje (0-3) o None si no se encuentra rango válido
    """
    # Intentar obtener desde caché primero
    cache_key = f"rangos_parametro_{codigo_parametro}"
    rangos = cache.get(cache_key)
    
    if rangos is None:
        try:
            parametro = Parametro.objects.get(codigo=codigo_parametro, activo=True)
            rangos = list(
                parametro.rangos.filter(activo=True)
                .order_by('orden', 'valor_min')
                .values('valor_min', 'valor_max', 'score')
            )
            # Cachear por 1 hora
            cache.set(cache_key, rangos, 3600)
        except Parametro.DoesNotExist:
            return None
    
    # Buscar el rango que contiene el valor
    for rango in rangos:
        if rango['valor_min'] <= valor <= rango['valor_max']:
            return rango['score']
    
    # Si no se encuentra ningún rango, retornar None
    return None


# ============================================================================
# FUNCIONES LEGACY (mantener por compatibilidad, pero usar BD preferiblemente)
# ============================================================================

def score_fc(valor: int) -> int:
    """
    Calcula el puntaje para Frecuencia Cardiaca (FC).

    2026-09-10: alineado con la tabla física FRSPA-026
    (meows/services/grid.py:FILAS_EXPLICITAS['fc'] y migración
    meows/0023). Este es solo el respaldo si RangoParametro no tiene datos.

    Returns:
        3: <60
        0: 60-109
        2: 110-149
        3: >=150
    """
    if valor < 60:
        return 3
    elif valor <= 109:
        return 0
    elif valor <= 149:
        return 2
    else:  # >= 150
        return 3


def score_ta_sistolica(valor: int) -> int:
    """
    Calcula el puntaje para Tensión Arterial Sistólica (TA Sistólica).

    2026-09-10: alineado con la tabla física FRSPA-026
    (meows/services/grid.py:FILAS_EXPLICITAS['ta_sys'] y migración
    meows/0023). Este es solo el respaldo si RangoParametro no tiene datos.

    Returns:
        3: <90            (incluye 80-89, que es rojo en la tabla física)
        2: 90-99
        0: 100-139
        1: 140-149
        2: 150-159
        3: >=160
    """
    if valor < 90:
        return 3
    elif valor <= 99:
        return 2
    elif valor <= 139:
        return 0
    elif valor <= 149:
        return 1
    elif valor <= 159:
        return 2
    else:  # >= 160
        return 3


def score_fr(valor: int) -> int:
    """
    Calcula el puntaje para Frecuencia Respiratoria (FR).
    
    Args:
        valor: Frecuencia respiratoria en rpm
        
    Returns:
        0: Normal (12-20)
        1: Moderado (9-11 o 21-30)
        2: Moderado-Alto (6-8 o 31-35)
        3: Crítico (<6 o >35)
    """
    if valor < 6:
        return 3
    elif 6 <= valor <= 8:
        return 2
    elif 9 <= valor <= 11:
        return 1
    elif 12 <= valor <= 20:
        return 0
    elif 21 <= valor <= 30:
        return 1
    elif 31 <= valor <= 35:
        return 2
    else:  # > 35
        return 3


def score_temp(valor: float) -> int:
    """
    Calcula el puntaje para Temperatura Corporal.

    2026-09-10: alineado con la tabla física FRSPA-026
    (meows/services/grid.py:FILAS_EXPLICITAS['temp'] y migración
    meows/0023). Este es solo el respaldo si RangoParametro no tiene datos.

    Returns:
        3: <34.5
        1: 34.5-35.49
        0: 35.5-37.49
        1: 37.5-38.49
        3: >=38.5
    """
    if valor < 34.5:
        return 3
    elif valor < 35.5:
        return 1
    elif valor < 37.5:
        return 0
    elif valor < 38.5:
        return 1
    else:  # >= 38.5
        return 3


def score_fcf(valor: int) -> int:
    """
    Frecuencia Cardíaca Fetal. 2026-09-10: la tabla física FRSPA-026 NO tiene
    ninguna franja de alerta para FCF -> siempre 0 (no aporta al puntaje MEOWS).
    Respaldo si RangoParametro no tiene datos para 'fcf'.
    """
    return 0


def score_glasgow(valor: int) -> int:
    """
    Calcula el puntaje para Escala de Glasgow.
    
    Args:
        valor: Puntaje de Glasgow
        
    Returns:
        0: Normal (15)
        1: Moderado (13-14)
        2: Moderado-Alto (9-12)
        3: Crítico (<9)
    """
    if valor < 9:
        return 3
    elif 9 <= valor <= 12:
        return 2
    elif 13 <= valor <= 14:
        return 1
    else:  # == 15
        return 0


# ============================================================================
# 📌 MAPEO DE FUNCIONES POR CÓDIGO DE PARÁMETRO (LEGACY)
# ============================================================================
# 2026-09-09: se quitó "spo2" (Saturación de Oxígeno) de aquí a propósito, no
# es un olvido — era un sustituto temporal de "% de O2 requerido" (o2_req)
# mientras ese campo oficial no existía en Dinámica (ver cargar_rangos_meows.py
# para el detalle histórico). Con o2_req ya disponible, SpO2 se quitó del
# sistema MEOWS por completo (Parametro.activo=False + no se sincroniza más
# desde Dinámica, ver dinamica_signos_vitales.py) — si quedara aquí, cualquier
# código que todavía pasara una clave "spo2" la seguiría puntuando por este
# fallback aunque el parámetro esté desactivado en la base de datos.
SCORE_FUNCTIONS = {
    "fc": score_fc,
    "ta_sys": score_ta_sistolica,
    "fr": score_fr,
    "temp": score_temp,
    "glasgow": score_glasgow,
    "fcf": score_fcf,  # 2026-09-10: siempre 0 (FRSPA-026 no puntúa FCF)
}


# ============================================================================
# 9️⃣ FUNCIÓN CENTRAL DE EVALUACIÓN MEOWS
# ============================================================================
def evaluar_meows(valores: dict, usar_bd: bool = True) -> dict:
    """
    Evalúa los valores clínicos y calcula puntajes MEOWS.
    
    Args:
        valores: Diccionario con valores clínicos por código de parámetro
                Ejemplo: {
                    "fc": 110,
                    "ta_sys": 95,
                    "fr": 28,
                    "temp": 38.2,
                    "glasgow": 14
                }
        usar_bd: Si True, usa rangos desde base de datos. Si False, usa funciones legacy.
    
    Returns:
        dict: {
            "puntajes": {codigo: puntaje},
            "total": suma_total,
            "alerta": bool
        }
    """
    puntajes = {}
    
    for codigo, valor in valores.items():
        # Convertir valor a tipo apropiado
        try:
            if codigo == "temp":
                valor_convertido = float(valor)
            else:
                valor_convertido = float(valor)  # Usar float para compatibilidad con DecimalField
            
            # Intentar usar base de datos primero
            if usar_bd:
                score = calcular_score_desde_bd(codigo, valor_convertido)
                if score is not None:
                    puntajes[codigo] = score
                    continue
            
            # Fallback a funciones legacy si BD no tiene datos o usar_bd=False
            if codigo in SCORE_FUNCTIONS:
                if codigo == "temp":
                    puntajes[codigo] = SCORE_FUNCTIONS[codigo](valor_convertido)
                else:
                    puntajes[codigo] = SCORE_FUNCTIONS[codigo](int(valor_convertido))
        except (ValueError, TypeError):
            # Si no se puede convertir, omitir este parámetro
            continue
    
    total = sum(puntajes.values())
    
    # Contar parámetros por nivel de puntaje
    parametros_3 = sum(1 for p in puntajes.values() if p == 3)
    parametros_2 = sum(1 for p in puntajes.values() if p == 2)
    parametros_1 = sum(1 for p in puntajes.values() if p == 1)
    
    # Evaluar reglas de alerta MEOWS
    # Alerta si: 
    # - 1 parámetro con 3 puntos (crítico)
    # - 1 parámetro con 2 puntos (moderado-alto)
    # - 2 parámetros con 1 punto (moderado)
    # - total >= 3
    alerta = (
        parametros_3 >= 1 or
        parametros_2 >= 1 or
        parametros_1 >= 2 or
        total >= 3
    )
    
    return {
        "puntajes": puntajes,
        "total": total,
        "alerta": alerta,
        "parametros_3": parametros_3,
        "parametros_2": parametros_2,
        "parametros_1": parametros_1,
    }


# ============================================================================
# 🔟 FUNCIÓN DE CLASIFICACIÓN DE RIESGO MEOWS
# ============================================================================
def clasificar_riesgo(total: int, tiene_parametro_critico: bool = False) -> dict:
    """
    Clasifica el riesgo según el puntaje total MEOWS.

    Lógica:
    - Total >= 6 → ROJO (RIESGO ALTO)
    - Total 4 a 5, o cualquier parámetro individual con puntaje 3 → AMARILLO (RIESGO INTERMEDIO)
    - Total = 0 (sin parámetro crítico) → BLANCO
    - Total 1 a 3 (sin parámetro crítico) → VERDE (RIESGO BAJO)

    Un solo parámetro crítico (puntaje 3) escala el riesgo a AMARILLO como mínimo,
    aunque la sumatoria total sea baja (ej: temperatura crítica con el resto normal).

    Args:
        total: Puntaje total MEOWS
        tiene_parametro_critico: True si al menos un parámetro individual tiene puntaje 3

    Returns:
        dict: {
            "riesgo": "BLANCO" | "VERDE" | "AMARILLO" | "ROJO",
            "mensaje": str
        }
    """
    if total >= 6:
        return {
            "riesgo": "ROJO",
            "mensaje": "RIESGO ALTO: OBSERVACION Monitoreo continuo de signos vitales LLAMADO :Emergente al equipo con conpetencias en estado critico y habilidades para el diagnostico"
        }
    elif total >= 4 or tiene_parametro_critico:
        return {
            "riesgo": "AMARILLO",
            "mensaje": "RIESGO INTERMEDIO: OBSERVACION -Minnimo cada hora LLAMADO: Urgente al equipo medico al de la paciente con las competencias para manejo de la emergencia obstetrica"
        }
    elif total == 0:
        return {
            "riesgo": "BLANCO",
            "mensaje": "RUTINA:  OBSERVACION -Minimo 12 horas de Observacion"
        }
    else:  # total 1 a 3, sin parámetro crítico
        return {
            "riesgo": "VERDE",
            "mensaje": "RIESGO BAJO OBSERVACION: mínimo cada 4 horas. LLAMADO: Enfermera a cargo"
        }


# ============================================================================
# 🔁 FUNCIÓN FINAL (TODO EN UNO – RECOMENDADA)
# ============================================================================
def calcular_meows(valores: dict, usar_bd: bool = True) -> dict:
    """
    Función principal que calcula y clasifica el riesgo MEOWS.
    
    Esta es la función que usarás desde vistas o signals.
    
    Args:
        valores: Diccionario con valores clínicos por código de parámetro
                Ejemplo: {
                    "fc": 120,
                    "ta_sys": 85,
                    "fr": 32,
                    "temp": 38.6,
                    "glasgow": 13,
                }
        usar_bd: Si True, usa rangos desde base de datos. Si False, usa funciones legacy.
    
    Returns:
        dict: {
            "puntajes": {codigo: puntaje},
            "meows_total": int,
            "meows_riesgo": "VERDE" | "AMARILLO" | "ROJO",
            "meows_mensaje": str,
            "alerta": bool
        }
    """
    evaluacion = evaluar_meows(valores, usar_bd=usar_bd)
    clasificacion = clasificar_riesgo(
        evaluacion["total"],
        tiene_parametro_critico=evaluacion["parametros_3"] >= 1,
    )
    
    return {
        "puntajes": evaluacion["puntajes"],
        "meows_total": evaluacion["total"],
        "meows_riesgo": clasificacion["riesgo"],
        "meows_mensaje": clasificacion["mensaje"],
        "alerta": evaluacion["alerta"],
    }

