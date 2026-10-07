from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registros', '0040_desgarro_episiotomia_no_aplica'),
    ]

    operations = [
        migrations.AddField(
            model_name='controlreciennacido',
            name='glucometrias_no_aplica',
            field=models.BooleanField(default=False, verbose_name='Glucometrías: no aplica'),
        ),
    ]
