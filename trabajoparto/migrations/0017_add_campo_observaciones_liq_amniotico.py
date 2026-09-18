# Generated manually on 2026-09-18
#
# Agrega un campo de texto "OBSERVACIONES" al parámetro LÍQUIDO AMNIÓTICO
# (LIQ_AMNIOTICO), para documentar detalles adicionales junto al grado de
# meconio elegido en el select principal (campo DESCRIPCION, ver
# create_basic_fields en seed_clinico.py / migración 0003_seed_clinico_data).

from django.db import migrations


def crear_campo_observaciones(apps, schema_editor):
    Parametro = apps.get_model('clinico', 'Parametro')
    CampoParametro = apps.get_model('clinico', 'CampoParametro')

    param_liq = Parametro.objects.filter(codigo='LIQ_AMNIOTICO').first()
    if not param_liq:
        return

    CampoParametro.objects.get_or_create(
        parametro=param_liq,
        codigo='OBSERVACIONES',
        defaults={
            'nombre': 'Observaciones',
            'tipo_valor': 'text',
            'orden': 2,
        },
    )


def eliminar_campo_observaciones(apps, schema_editor):
    Parametro = apps.get_model('clinico', 'Parametro')
    CampoParametro = apps.get_model('clinico', 'CampoParametro')

    param_liq = Parametro.objects.filter(codigo='LIQ_AMNIOTICO').first()
    if not param_liq:
        return

    CampoParametro.objects.filter(parametro=param_liq, codigo='OBSERVACIONES').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('clinico', '0016_medicion_responsable'),
    ]

    operations = [
        migrations.RunPython(crear_campo_observaciones, eliminar_campo_observaciones),
    ]
