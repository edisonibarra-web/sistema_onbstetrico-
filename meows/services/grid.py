"""
Construcción de la cuadrícula clínica MEOWS ("Línea de Tiempo Clínica"): una fila por
cada banda de valores posibles de cada parámetro y una columna por cada medición
registrada, marcando la celda real de cada toma.

Extraído de meows.views.historial_meows_paciente para poder reutilizarse desde otras
vistas del sistema (p.ej. Control Posparto Inmediato en frecuenciafetal), de modo que
cualquier medición MEOWS nueva se refleje ahí también al recargar esa página.
"""
from meows.models import Paciente, Medicion, Parametro


# Etiquetas de fila especiales para parámetros donde el valor numérico crudo
# de RangoParametro no es lo que se muestra en la tabla oficial FRSPA-026 —
# 2026-09-09, a pedido: la fila de Nivel de Conciencia debe leerse "Alerta =
# Glasgow 15" / "No Alerta = Glasgow <15", igual que ya rotula el <select>
# del formulario MEOWS (ver meows/templates/meows/formulario.html), no el
# número de Glasgow (15 / ≤14) que salía antes con el formateador genérico.
_ETIQUETAS_ESPECIALES = {
    'glasgow': {
        (0, 14): 'No Alerta = Glasgow <15',
        (15, 15): 'Alerta = Glasgow 15',
    },
    # 2026-09-09: tramos oficiales confirmados por el usuario (con su color en
    # la tabla física: 21%=blanco/0, 24-39%=verde/1, ≥40%=rojo/3 — sin tramo
    # amarillo/2 intermedio, tal como en la imagen de referencia). Reemplaza
    # el único tramo placeholder 0-999->0 que había antes. La primera fila se
    # rotuló "Aire ambiente" al principio; el usuario corrigió que debe decir
    # "21%" (el valor real de FiO2 del aire ambiente, no la palabra genérica).
    'o2_req': {
        (0, 23): '21%',
        (24, 39): '24-39%',
        (40, 999): '≥40%',
    },
}


# ============================================================================
# FILAS EXPLÍCITAS ("flowsheet" de la tabla física FRSPA-026) — 2026-09-09
# ============================================================================
# La tabla física trae una fila por cada valor puntual (ej. TA Sistólica: 200,
# 190, 180 ... 70 — 14 filas), mucho más fino que las franjas anchas que
# calculábamos antes desde RangoParametro (ahí hay solo 6 franjas para ese
# mismo parámetro). A pedido, se transcriben aquí LITERALMENTE los valores de
# la tabla física, para estos 6 parámetros (foto de la tabla, confirmada por
# el usuario). Glasgow y o2_req no necesitan esto: cada uno tiene exactamente
# tantas franjas reales en RangoParametro como filas en la tabla física, así
# que basta con renombrarlas vía _ETIQUETAS_ESPECIALES (ver arriba) en vez de
# definir límites de marca a mano aquí.
#
# Cada fila es (etiqueta, marca_desde, marca_hasta, puntaje):
#   - marca_desde/marca_hasta: límites [desde, hasta) usados SOLO para saber
#     qué fila marcar en cada columna según el valor real registrado (None =
#     sin límite en esa punta). Son "cubetas" de una década (o el ancho exacto
#     ya en rango de la tabla física, ej. FR/FCF) sin huecos ni traslapes.
#   - puntaje: el COLOR REAL de esa fila en la foto de la tabla física
#     (blanco=0, verde=1, amarillo=2, rojo=3), confirmado por el usuario
#     2026-09-09. IMPORTANTE — primer intento (mismo día) calculó esto
#     evaluando cada valor contra los RangoParametro ya calibrados en vez de
#     mirar el color real, y salió mal en 3 filas: TA Sistólica 90 (daba
#     blanco, es amarillo) y 80 (daba amarillo, es rojo), y FC 110 (daba
#     blanco, es amarillo) — la tabla física NO coincide 1:1 con los
#     RangoParametro vigentes en esos puntos exactos. Corregido con la foto
#     real (usuario confirmó 2026-09-09 que la foto es la fuente correcta,
#     no los RangoParametro); NO volver a derivar estos puntajes desde
#     RangoParametro. La "Guía de referencia MEOWS" (el modal 🔎, ver
#     meows/templates/meows/_timeline_grid.html) mostraba las viejas franjas
#     de RangoParametro para PAS y FC — se corrigió también, en el mismo
#     sentido que aquí.
#
# 2026-09-10: RangoParametro (el motor de puntaje: meows_total, meows_riesgo,
# alertas, estado de Sala de Partos, PDF MEOWS) SE ALINEÓ con esta tabla —
# ver meows/migrations/0023_rangos_meows_frspa026.py y
# meows/management/commands/cargar_rangos_meows.py. Ahora GRILLA == MOTOR ==
# PDF para temp/ta_sys/fc/fcf. Esta tabla se conserva porque muestra una fila
# por valor puntual (más fino que las 4-6 franjas consolidadas de
# RangoParametro), pero YA NO contradice el puntaje.
#
# ⚠️ SI SE CAMBIA UN UMBRAL: hay que tocar LOS TRES a la vez -> (1) esta
# tabla FILAS_EXPLICITAS, (2) RANGOS_MEOWS en cargar_rangos_meows.py, (3) los
# rangos reales en la BD (una migración de datos como la 0023, o el admin).
# Y la "Guía de referencia MEOWS" del template si aplica.
FILAS_EXPLICITAS = {
    # Confirmado por el usuario (2026-09-09), tras revisar contra la tabla
    # física completa, que esta lista está correcta tal como estaba
    # calculada (única corrección real: la fila "34", ya aplicada abajo).
    'temp': [
        ('40', 39.5, None, 3),
        ('39', 38.5, 39.5, 3),
        ('38', 37.5, 38.5, 1),
        ('37', 36.5, 37.5, 0),
        ('36', 35.5, 36.5, 0),
        ('35', 34.5, 35.5, 1),
        ('34', None, 34.5, 3),  # confirmado por el usuario: es roja
    ],
    'ta_sys': [
        # Colores confirmados por foto (2026-09-09): 90-99 es amarillo (2),
        # 80-89 es rojo (3). Desde 2026-09-10 RangoParametro coincide (ver
        # migración 0023).
        ('>200', 200, None, 3),
        ('190', 190, 200, 3),
        ('180', 180, 190, 3),
        ('170', 170, 180, 3),
        ('160', 160, 170, 3),
        ('150', 150, 160, 2),
        ('140', 140, 150, 1),
        ('130', 130, 140, 0),
        ('120', 120, 130, 0),
        ('110', 110, 120, 0),
        ('100', 100, 110, 0),
        ('90', 90, 100, 2),
        ('80', 80, 90, 3),
        ('70', None, 80, 3),
    ],
    'ta_dia': [
        # Confirmado por foto (2026-09-09): coincide exacto con el
        # RangoParametro vigente (0-59->0, 60-89->0, 90-99->1, 100-109->2,
        # 110-120->3, 121-999->3), no hizo falta corregir nada aquí.
        ('>120', 120, None, 3),
        ('110', 110, 120, 3),
        ('100', 100, 110, 2),
        ('90', 90, 100, 1),
        ('80', 80, 90, 0),
        ('70', 70, 80, 0),
        ('60', None, 70, 0),
    ],
    'fc': [
        # Color confirmado por foto (2026-09-09): 110 es amarillo (2), no
        # blanco. Desde 2026-09-10 RangoParametro coincide (60-109->0,
        # 110-149->2; ver migración 0023).
        ('>150', 150, None, 3),
        ('140', 140, 150, 2),
        ('130', 130, 140, 2),
        ('120', 120, 130, 2),
        ('110', 110, 120, 2),
        ('100', 100, 110, 0),
        ('90', 90, 100, 0),
        ('80', 80, 90, 0),
        ('70', 70, 80, 0),
        ('60', 60, 70, 0),
        ('50', 50, 60, 3),
        ('40', None, 50, 3),
    ],
    'fr': [
        # Confirmado por foto (2026-09-09): coincide exacto con las 6
        # franjas del RangoParametro vigente (0-4->3, 5-9->3, 10-17->0,
        # 18-24->1, 25-29->2, 30-999->3), solo cambia cómo se rotula cada una.
        ('30', 30, None, 3),
        ('25', 25, 30, 2),
        ('18-24', 18, 25, 1),
        ('10-17', 10, 18, 0),
        ('9', 5, 10, 3),
        ('5', None, 5, 3),
    ],
    # Confirmado por foto (2026-09-09): las 6 filas son blancas (puntaje 0)
    # sin excepción, incluidas las dos filas abiertas de los extremos
    # (">160" y "<120"). Esta tabla física, a diferencia de ta_sys/ta_dia/fc/fr,
    # NO tiene ninguna franja de alerta para FCF. Desde 2026-09-10
    # RangoParametro coincide: un solo rango 0-999 -> 0, así FCF ya no aporta
    # puntaje MEOWS ni dispara alerta (ver migración 0023). Antes daba
    # 0-99->3, 100-109->2, 161-180->2, 181-999->3.
    'fcf': [
        ('>160', 161, None, 0),
        ('150-160', 150, 161, 0),
        ('140-149', 140, 150, 0),
        ('130-139', 130, 140, 0),
        ('120-129', 120, 130, 0),
        ('<120', None, 120, 0),
    ],
}


def _valor_en_fila(valor, marca_desde, marca_hasta):
    """True si `valor` cae dentro de [marca_desde, marca_hasta) de una fila
    de FILAS_EXPLICITAS (None en cualquier punta = sin límite ahí)."""
    if valor is None:
        return False
    if marca_desde is not None and valor < marca_desde:
        return False
    if marca_hasta is not None and valor >= marca_hasta:
        return False
    return True


def _etiqueta_rango_meows(codigo, valor_min, valor_max):
    """Formatea una banda de RangoParametro como etiqueta de fila para la
    cuadrícula clínica del historial (ej: '≤89', '90-99', '≥160', '15') —
    salvo que `codigo` tenga una etiqueta especial en _ETIQUETAS_ESPECIALES."""
    especiales = _ETIQUETAS_ESPECIALES.get(codigo)
    if especiales:
        etiqueta = especiales.get((int(valor_min), int(valor_max)))
        if etiqueta:
            return etiqueta

    def fmt(v):
        return str(int(v)) if v == int(v) else f"{v:g}"

    if valor_min <= 0:
        return f"≤{fmt(valor_max)}"
    if valor_max >= 999:
        return f"≥{fmt(valor_min)}"
    if valor_min == valor_max:
        return fmt(valor_min)
    return f"{fmt(valor_min)}-{fmt(valor_max)}"


def construir_grid_meows(paciente):
    """
    Dado un meows.Paciente, arma (grid_parametros, columnas) tal como los espera
    el partial meows/_timeline_grid.html. Devuelve columnas=[] si el paciente no
    tiene mediciones registradas.
    """
    mediciones = Medicion.objects.filter(
        paciente=paciente
    ).select_related('formulario').prefetch_related(
        'valores__parametro'
    ).order_by("fecha_hora")

    columnas = []
    for medicion in mediciones:
        valores_num = {}
        for valor_obj in medicion.valores.all():
            try:
                valores_num[valor_obj.parametro.codigo] = float(valor_obj.valor)
            except (TypeError, ValueError):
                continue
        columnas.append({
            'medicion_id': medicion.id,
            'hora': medicion.fecha_hora,
            'score_total': medicion.meows_total,
            'riesgo': medicion.meows_riesgo,
            'valores_num': valores_num,
            'origen': medicion.origen,
        })

    parametros = Parametro.objects.filter(activo=True).order_by('orden').prefetch_related('rangos')
    grid_parametros = []
    for parametro in parametros:
        filas = []
        filas_explicitas = FILAS_EXPLICITAS.get(parametro.codigo)
        if filas_explicitas:
            # Flowsheet de la tabla física FRSPA-026 (ver FILAS_EXPLICITAS arriba):
            # ya viene en el orden correcto (más crítico arriba).
            for etiqueta, marca_desde, marca_hasta, puntaje in filas_explicitas:
                celdas = []
                for columna in columnas:
                    valor = columna['valores_num'].get(parametro.codigo)
                    celdas.append({'marcado': _valor_en_fila(valor, marca_desde, marca_hasta)})
                filas.append({'label': etiqueta, 'score': puntaje, 'celdas': celdas})
        else:
            rangos = list(parametro.rangos.filter(activo=True).order_by('orden', 'valor_min'))
            # De mayor a menor: los valores más críticos quedan arriba, como en un flowsheet de papel.
            for rango in reversed(rangos):
                valor_min = float(rango.valor_min)
                valor_max = float(rango.valor_max)
                celdas = []
                for columna in columnas:
                    valor = columna['valores_num'].get(parametro.codigo)
                    celdas.append({'marcado': valor is not None and valor_min <= valor <= valor_max})
                filas.append({
                    'label': _etiqueta_rango_meows(parametro.codigo, valor_min, valor_max),
                    'score': rango.score,
                    'celdas': celdas,
                })
        grid_parametros.append({
            'codigo': parametro.codigo,
            'nombre': parametro.nombre,
            'unidad': parametro.unidad,
            'filas': filas,
        })

    return grid_parametros, columnas


def obtener_paciente_meows_por_documento(documento):
    """Resuelve el meows.Paciente asociado a un número de documento, o None si
    todavía no existe (el paciente aún no tiene ninguna medición MEOWS creada)."""
    if not documento:
        return None
    return Paciente.objects.filter(numero_documento=documento).first()
