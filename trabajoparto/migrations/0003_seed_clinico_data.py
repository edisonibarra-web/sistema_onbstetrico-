from django.db import migrations
from django.core.management import call_command


def seed_clinico_data(apps, schema_editor):
    """Ejecutar el comando de seed para poblar datos clínicos"""
    call_command('seed_clinico')


def reverse_seed_clinico_data(apps, schema_editor):
    """Eliminar los datos creados por el seed (opcional)"""
    # Obtener los modelos
    Item = apps.get_model('clinico', 'Item')
    
    # Eliminar los items creados por el seed
    items_codigos = [
        'CTRL_MAT',
        'CONTRAC_UTER', 
        'CTRL_FETAL',
        'TACTO_VAG',
        'MON_FETAL',
        'OXITOCINA'
    ]
    
    Item.objects.filter(codigo__in=items_codigos).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('clinico', '0002_remove_unique_together_formulario'),
    ]

    operations = [
        migrations.RunPython(
            seed_clinico_data,
            reverse_code=reverse_seed_clinico_data,
        ),
    ]