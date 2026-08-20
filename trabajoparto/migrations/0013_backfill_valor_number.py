from django.db import migrations


def backfill_valor_number(apps, schema_editor):
    """
    Bug histórico: el guardado de mediciones (main.js) escribía SIEMPRE en
    valor_text, incluso para campos cuyo tipo declarado es 'number' (Dilatación,
    Borramiento, FCF, Frecuencia, etc.), impidiendo cualquier análisis/gráfica
    numérica de esos datos. Ya se corrigió el guardado hacia adelante; esta
    migración rescata los valores numéricos que quedaron atrapados en
    valor_text para los registros existentes.

    MedicionValor tiene un CheckConstraint que exige que solo UNO de
    valor_number/valor_text/valor_boolean/valor_json esté definido, así que
    al rellenar valor_number también hay que vaciar valor_text en el mismo
    registro.
    """
    MedicionValor = apps.get_model("clinico", "MedicionValor")

    candidatos = MedicionValor.objects.filter(
        campo__tipo_valor="number",
        valor_number__isnull=True,
        valor_text__isnull=False,
    ).exclude(valor_text="")

    actualizados = 0
    for mv in candidatos:
        texto = mv.valor_text.strip()
        try:
            numero = float(texto)
        except (TypeError, ValueError):
            continue
        mv.valor_number = numero
        mv.valor_text = None
        mv.save(update_fields=["valor_number", "valor_text"])
        actualizados += 1

    if actualizados:
        print(f"  Backfill valor_number: {actualizados} registro(s) corregido(s).")


def revertir(apps, schema_editor):
    # No reversible de forma segura (no se guarda de dónde vino cada valor).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("clinico", "0012_formulario_abortos_formulario_cesareas_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_valor_number, revertir),
    ]
