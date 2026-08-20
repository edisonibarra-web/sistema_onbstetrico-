from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registros', '0002_allow_blank_responsable_fetocardia'),
    ]

    operations = [
        migrations.AddField(
            model_name='controlpostpartoinmediato',
            name='cuantificacion_gravimetrica_vaginal',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Cuantificación Gravimétrica Vaginal (g)'),
        ),
        migrations.AlterField(
            model_name='controlpostpartoinmediato',
            name='involucion_uterina',
            field=models.CharField(blank=True, choices=[('1CM_UMBILICAL', '1 cm umbilical'), ('2CM_UMBILICAL', '2 cm umbilical')], max_length=20, null=True),
        ),
    ]

