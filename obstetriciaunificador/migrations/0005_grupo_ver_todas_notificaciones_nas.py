"""
2026-09-24: grupo para que un profesional que entra con Dinámica (p. ej. una
jefe de enfermería) vea en la campana "NAS" los envíos de TODAS las pacientes.
No sirve marcar is_staff a esas cuentas: el login con Dinámica lo quita en
cada ingreso (frecuenciafetal/auth_dgh.py). Se asigna en /admin/ -> Usuarios.
"""
from django.db import migrations

GRUPO = 'Ve todas las notificaciones NAS'


def crear(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.get_or_create(name=GRUPO)


def quitar(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.filter(name=GRUPO).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('obstetricia', '0004_acceso_documento_repositorio'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]
    operations = [migrations.RunPython(crear, quitar)]
