"""
2026-09-25: huella del contenido de cada PDF enviado al repositorio, para no
guardar copias idénticas (ver repositorio.huella_contenido / _enviar_manual).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('obstetricia', '0005_grupo_ver_todas_notificaciones_nas'),
    ]

    operations = [
        migrations.AddField(
            model_name='documentorepositorio',
            name='huella_contenido',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
