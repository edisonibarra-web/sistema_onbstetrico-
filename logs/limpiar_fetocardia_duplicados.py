"""
2026-10-07: limpieza de tomas de fetocardia DUPLICADAS que dejó el error del
autoguardado (corregido el 2026-10-06: cada toma nueva se volvía a crear en
cada autoguardado).

Deja UNA toma por grupo (misma paciente/registro, fecha, hora y valor): la
primera que se guardó (id más bajo). Antes de borrar guarda un respaldo JSON
de lo eliminado en logs/.

Uso (desde la carpeta sistema_obstetrico):
    venv\\Scripts\\python.exe manage.py shell -c "exec(open('logs/limpiar_fetocardia_duplicados.py', encoding='utf-8').read())"
En Docker:
    docker exec sistema-obstetrico-dev python manage.py shell -c "exec(open('logs/limpiar_fetocardia_duplicados.py', encoding='utf-8').read())"
(No usar "shell < archivo": la consola interactiva no ejecuta el último bloque.)

Para solo VER qué borraría, sin borrar nada, cambiar SOLO_REVISAR = True.
"""
import os
from datetime import datetime

from django.core import serializers
from django.db import transaction
from django.db.models import Count, Min

from frecuenciafetal.models import ControlFetocardia, RegistroParto

SOLO_REVISAR = False

grupos = (ControlFetocardia.objects
          .values('registro_id', 'fecha', 'hora', 'fetocardia')
          .annotate(n=Count('id'), conservar=Min('id'))
          .filter(n__gt=1))

borrar_ids, cerrados = [], set()
for g in grupos:
    ids = list(ControlFetocardia.objects
               .filter(registro_id=g['registro_id'], fecha=g['fecha'], hora=g['hora'], fetocardia=g['fetocardia'])
               .exclude(id=g['conservar'])
               .values_list('id', flat=True))
    borrar_ids += ids
    r = RegistroParto.objects.filter(pk=g['registro_id']).first()
    print(f"{(r.identificacion if r else '?'):>12}  {g['fecha']} {str(g['hora'])[:5]}  fc={g['fetocardia']:>4}  "
          f"copias={g['n']:>3}  se conserva id={g['conservar']}  se borran={len(ids)}")
    if r and r.completado_en:
        cerrados.add(f'{r.identificacion} ({r.pk})')

print(f'\nGrupos duplicados: {grupos.count()} | tomas a borrar: {len(borrar_ids)}')
if cerrados:
    print('Registros YA CERRADOS afectados (su PDF en el repositorio tiene las copias; '
          'reenviar desde "Reenviar a repositorio" si se quiere la versión limpia):')
    for c in sorted(cerrados):
        print('  -', c)

if SOLO_REVISAR or not borrar_ids:
    print('\nNo se borró nada.')
else:
    ruta = os.path.join('logs', f'respaldo_fetocardia_duplicados_{datetime.now():%Y%m%d_%H%M%S}.json')
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write(serializers.serialize('json', ControlFetocardia.objects.filter(id__in=borrar_ids), indent=1))
    antes = ControlFetocardia.objects.count()
    with transaction.atomic():
        eliminados, _ = ControlFetocardia.objects.filter(id__in=borrar_ids).delete()
    quedan = (ControlFetocardia.objects.values('registro_id', 'fecha', 'hora', 'fetocardia')
              .annotate(n=Count('id')).filter(n__gt=1).count())
    print(f'\nRespaldo: {ruta}')
    print(f'Tomas antes: {antes} | eliminadas: {eliminados} | después: {ControlFetocardia.objects.count()}')
    print(f'Grupos duplicados que quedan: {quedan}')
