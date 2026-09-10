"""
2026-09-10 — Alinea RangoParametro (el motor de puntaje MEOWS) con la tabla
física FRSPA-026 avalada por Calidad, ya transcrita en
meows/services/grid.py:FILAS_EXPLICITAS (verificada contra foto por el usuario
el 2026-09-09).

Hasta ahora la GRILLA en pantalla (Línea de Tiempo Clínica) mostraba los
colores de la tabla física, pero el puntaje que alimenta Medicion.meows_total /
meows_riesgo / la campana de alertas / el estado ESTABLE·ALERTA·CRÍTICO de Sala
de Partos / el PDF MEOWS seguía saliendo de RangoParametro con valores viejos
que NO coincidían en:

  - TA sistólica 90-99 mmHg : era 0 (blanco)  ->  pasa a 2 (amarillo)
  - TA sistólica 80-89 mmHg : era 2 (amarillo) ->  pasa a 3 (rojo)
  - FC = 110 lpm exacto     : era 0 (blanco)  ->  pasa a 2 (amarillo)
  - FCF (toda)              : la tabla física NO tiene franjas de alerta para
                              FCF -> TODO valor pasa a 0. Antes <100 y >180
                              daban 3, 100-109 y 161-180 daban 2.
  - Temperatura             : se afinan los límites a los de la tabla física
                              (cortes en .5 en vez de .0/.1). Cambia el puntaje
                              en las franjas 34.0-34.4, 35.1-35.4, 37.5-37.9 y
                              38.5-38.9.

No se tocan ta_dia, fr, glasgow ni o2_req: ya coincidían.

⚠️ ESTA MIGRACIÓN NO re-puntúa las mediciones ya guardadas — solo cambia las
reglas para las mediciones NUEVAS. Re-puntuar el histórico es una decisión
aparte (cambia clasificaciones de riesgo ya registradas en la historia
clínica).

Reversible: revertir restaura exactamente los rangos anteriores.
"""
from decimal import Decimal

from django.db import migrations


RANGOS_NUEVOS = {
    "temp": [
        ("0.00", "34.49", 3),
        ("34.50", "35.49", 1),
        ("35.50", "37.49", 0),
        ("37.50", "38.49", 1),
        ("38.50", "999.00", 3),
    ],
    "ta_sys": [
        ("0", "89", 3),
        ("90", "99", 2),
        ("100", "139", 0),
        ("140", "149", 1),
        ("150", "159", 2),
        ("160", "999", 3),
    ],
    "fc": [
        ("0", "59", 3),
        ("60", "109", 0),
        ("110", "149", 2),
        ("150", "999", 3),
    ],
    "fcf": [
        ("0", "999", 0),
    ],
}

RANGOS_VIEJOS = {
    "temp": [
        ("0.00", "33.90", 3),
        ("34.00", "35.00", 1),
        ("35.10", "37.90", 0),
        ("38.00", "38.90", 1),
        ("39.00", "999.00", 3),
    ],
    "ta_sys": [
        ("0", "79", 3),
        ("80", "89", 2),
        ("90", "139", 0),
        ("140", "149", 1),
        ("150", "159", 2),
        ("160", "999", 3),
    ],
    "fc": [
        ("0", "59", 3),
        ("60", "110", 0),
        ("111", "149", 2),
        ("150", "999", 3),
    ],
    "fcf": [
        ("0", "99", 3),
        ("100", "109", 2),
        ("110", "160", 0),
        ("161", "180", 2),
        ("181", "999", 3),
    ],
}


def _aplicar(apps, rangos_por_codigo):
    Parametro = apps.get_model("meows", "Parametro")
    RangoParametro = apps.get_model("meows", "RangoParametro")
    for codigo, filas in rangos_por_codigo.items():
        try:
            parametro = Parametro.objects.get(codigo=codigo)
        except Parametro.DoesNotExist:
            continue
        RangoParametro.objects.filter(parametro=parametro).delete()
        for orden, (vmin, vmax, score) in enumerate(filas, start=1):
            RangoParametro.objects.create(
                parametro=parametro,
                valor_min=Decimal(vmin),
                valor_max=Decimal(vmax),
                score=score,
                orden=orden,
                activo=True,
            )
    # calcular_score_desde_bd cachea los rangos por parámetro 1 hora; se limpia
    # para que el efecto sea inmediato en este proceso (el servidor web se
    # reinicia aparte tras aplicar la migración).
    try:
        from django.core.cache import cache
        cache.delete_many([f"rangos_parametro_{c}" for c in rangos_por_codigo])
    except Exception:
        pass


def forward(apps, schema_editor):
    _aplicar(apps, RANGOS_NUEVOS)


def backward(apps, schema_editor):
    _aplicar(apps, RANGOS_VIEJOS)


class Migration(migrations.Migration):

    dependencies = [
        ("meows", "0022_medicion_alerta_vista_en_medicion_alerta_vista_por"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
