# 2026-10-19: embarazo gemelar -- RegistroParto.hora_parto_b (hora de parto
# del Feto B, en "Características del parto"). Antes cada recién nacido
# tenía su hora de nacimiento editable y la del Feto B se llenaba sola con la
# hora de parto (los dos gemelos quedaban con la misma hora).
#
# Datos: la hora de nacimiento ya registrada del Feto B pasa a hora_parto_b,
# salvo en registros ABIERTOS donde es igual a la hora de parto (casi seguro
# copiada sola): ahí queda vacía para que se registre la real.

from django.db import migrations, models


def pasar_hora_feto_b(apps, schema_editor):
    RegistroParto = apps.get_model('registros', 'RegistroParto')
    ControlRecienNacido = apps.get_model('registros', 'ControlRecienNacido')
    for rn in ControlRecienNacido.objects.filter(feto=2, hora_nacimiento__isnull=False).select_related('registro'):
        registro = rn.registro
        if registro.hora_parto_b is not None:
            continue
        copiada = registro.hora_parto is not None and rn.hora_nacimiento == registro.hora_parto
        if copiada and registro.completado_en is None:
            continue
        RegistroParto.objects.filter(pk=registro.pk).update(hora_parto_b=rn.hora_nacimiento)


class Migration(migrations.Migration):

    dependencies = [
        ('registros', '0044_gemelos'),
    ]

    operations = [
        migrations.AddField(
            model_name='registroparto',
            name='hora_parto_b',
            field=models.TimeField(blank=True, null=True, verbose_name='Hora de parto (Feto B)'),
        ),
        migrations.RunPython(pasar_hora_feto_b, migrations.RunPython.noop),
    ]
