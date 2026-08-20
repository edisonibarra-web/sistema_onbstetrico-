# Generated manually for allow_blank_responsable_fetocardia

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registros', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='controlfetocardia',
            name='responsable',
            field=models.CharField(blank=True, default='', max_length=200, verbose_name='Responsable'),
        ),
    ]
