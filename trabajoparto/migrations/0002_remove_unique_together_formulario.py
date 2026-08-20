# Generated manually to remove unique_together constraint from Formulario

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('clinico', '0001_initial'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='formulario',
            unique_together=set(),
        ),
    ]

