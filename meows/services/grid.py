"""
Construcción de la cuadrícula clínica MEOWS ("Línea de Tiempo Clínica"): una fila por
cada banda de valores posibles de cada parámetro y una columna por cada medición
registrada, marcando la celda real de cada toma.

Extraído de meows.views.historial_meows_paciente para poder reutilizarse desde otras
vistas del sistema (p.ej. Control Posparto Inmediato en frecuenciafetal), de modo que
cualquier medición MEOWS nueva se refleje ahí también al recargar esa página.
"""
from meows.models import Paciente, Medicion, Parametro


def _etiqueta_rango_meows(valor_min, valor_max):
    """Formatea una banda de RangoParametro como etiqueta de fila para la
    cuadrícula clínica del historial (ej: '≤89', '90-99', '≥160', '15')."""
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
        })

    parametros = Parametro.objects.filter(activo=True).order_by('orden').prefetch_related('rangos')
    grid_parametros = []
    for parametro in parametros:
        rangos = list(parametro.rangos.filter(activo=True).order_by('orden', 'valor_min'))
        filas = []
        # De mayor a menor: los valores más críticos quedan arriba, como en un flowsheet de papel.
        for rango in reversed(rangos):
            valor_min = float(rango.valor_min)
            valor_max = float(rango.valor_max)
            celdas = []
            for columna in columnas:
                valor = columna['valores_num'].get(parametro.codigo)
                celdas.append({'marcado': valor is not None and valor_min <= valor <= valor_max})
            filas.append({
                'label': _etiqueta_rango_meows(valor_min, valor_max),
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
