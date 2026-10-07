from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registros', '0039_globo_sutura_no_aplica'),
    ]

    operations = [
        migrations.AlterField(
            model_name='registroparto',
            name='desgarro',
            field=models.CharField(blank=True, choices=[('GRADO_I', 'Grado I'), ('GRADO_II', 'Grado II'), ('GRADO_III', 'Grado III'), ('GRADO_IV', 'Grado IV'), ('NO_APLICA', 'No aplica')], max_length=20, null=True, verbose_name='Desgarro'),
        ),
        migrations.AlterField(
            model_name='registroparto',
            name='episiotomia',
            field=models.BooleanField(blank=True, default=False, null=True, verbose_name='Episiotomía'),
        ),
    ]
