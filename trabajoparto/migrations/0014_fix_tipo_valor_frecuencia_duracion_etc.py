from django.db import migrations


CAMPOS_A_CORREGIR = [16, 17, 9, 10]
# 16: Frecuencia -> Tiempo (contracciones, min) — ya usa <input type="number"> en el formulario
# 17: Duración -> Tiempo (contracciones, seg) — ídem
# 9:  Intensidad -> Descripción (escala 0-4: Ausente/Leve/Moderada/Fuerte/Hipertónica)
# 10: Movimientos Fetales -> Descripción (escala 0-3: Ausentes/Disminuidos/Presentes/Exagerados)
# Los 4 estaban tipificados como 'text' pese a que su valor real es numérico (una
# medida cruda los dos primeros, una escala ordinal codificada los otros dos),
# lo que los dejaba fuera de cualquier gráfica/trazabilidad numérica.


def corregir_tipo_y_backfill(apps, schema_editor):
    CampoParametro = apps.get_model("clinico", "CampoParametro")
    MedicionValor = apps.get_model("clinico", "MedicionValor")

    CampoParametro.objects.filter(id__in=CAMPOS_A_CORREGIR).update(tipo_valor="number")

    candidatos = MedicionValor.objects.filter(
        campo_id__in=CAMPOS_A_CORREGIR,
        valor_number__isnull=True,
        valor_text__isnull=False,
    ).exclude(valor_text="")

    actualizados = 0
    for mv in candidatos:
        try:
            numero = float(mv.valor_text.strip())
        except (TypeError, ValueError):
            continue
        mv.valor_number = numero
        mv.valor_text = None
        mv.save(update_fields=["valor_number", "valor_text"])
        actualizados += 1

    if actualizados:
        print(f"  Backfill Frecuencia/Duración/Intensidad/Mov. Fetales: {actualizados} registro(s) corregido(s).")


def revertir(apps, schema_editor):
    CampoParametro = apps.get_model("clinico", "CampoParametro")
    CampoParametro.objects.filter(id__in=CAMPOS_A_CORREGIR).update(tipo_valor="text")
    # Los valores numéricos migrados de vuelta a texto no se revierten
    # automáticamente (no es reversible de forma segura).


class Migration(migrations.Migration):

    dependencies = [
        ("clinico", "0013_backfill_valor_number"),
    ]

    operations = [
        migrations.RunPython(corregir_tipo_y_backfill, revertir),
    ]
