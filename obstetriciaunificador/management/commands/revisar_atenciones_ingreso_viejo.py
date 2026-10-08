"""
2026-10-08: atenciones creadas con un ingreso que YA estaba cerrado cuando se
crearon (p. ej. paciente que volvió a Triaje y la app le tomó su último ingreso
de hace años como "actual"; ver consultar_ingreso_paciente).

Por defecto SOLO LISTA. Con --borrar-vacias elimina únicamente las que no
tienen ningún registro asociado (MEOWS, posparto, trabajo de parto, envíos a la
NAS...); las que tienen registros nunca se tocan.

    python manage.py revisar_atenciones_ingreso_viejo
    python manage.py revisar_atenciones_ingreso_viejo --borrar-vacias
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from frecuenciafetal.sala_partos_db import consultar_estado_ingreso
from obstetriciaunificador.ingresos import _aware, olvidar_ingresos_de_paciente
from obstetriciaunificador.models import AtencionParto


def _registros_asociados(atencion):
    """{'modelo': n} de todo lo que apunta a la atención."""
    conteo = {}
    for rel in atencion._meta.related_objects:
        if not (rel.one_to_many or rel.one_to_one):
            continue
        n = rel.related_model._base_manager.filter(**{rel.field.name: atencion}).count()
        if n:
            conteo[rel.related_model._meta.label] = n
    return conteo


class Command(BaseCommand):
    help = 'Lista (y opcionalmente borra si están vacías) las atenciones creadas con un ingreso ya cerrado.'

    def add_arguments(self, parser):
        parser.add_argument('--borrar-vacias', action='store_true',
                            help='Elimina SOLO las atenciones sin ningún registro asociado.')

    def handle(self, *args, **opts):
        gracia = timedelta(hours=getattr(settings, 'INGRESO_HORAS_GRACIA_EDICION', 24))
        borrar = opts['borrar_vacias']
        afectadas = vacias = borradas = sin_dato = 0
        for atencion in AtencionParto.objects.exclude(numero_ingreso='').order_by('fecha_inicio'):
            estado = consultar_estado_ingreso(atencion.numero_ingreso)
            if not estado:
                sin_dato += 1
                continue
            egreso = _aware(estado.get('fecha_egreso'))
            if egreso is None or atencion.fecha_inicio <= egreso + gracia:
                continue
            afectadas += 1
            registros = _registros_asociados(atencion)
            texto = ', '.join(f'{k}: {v}' for k, v in registros.items()) or 'VACÍA'
            self.stdout.write(
                f'{atencion.paciente} | ingreso {atencion.numero_ingreso} egresó '
                f'{timezone.localtime(egreso):%d/%m/%Y} | atención creada '
                f'{timezone.localtime(atencion.fecha_inicio):%d/%m/%Y %H:%M} | {texto}'
            )
            if not registros:
                vacias += 1
                if borrar:
                    doc = atencion.paciente
                    atencion.delete()
                    olvidar_ingresos_de_paciente(doc)
                    borradas += 1
        self.stdout.write(self.style.SUCCESS(
            f'Afectadas: {afectadas} (vacías: {vacias}, borradas: {borradas}). '
            f'Sin respuesta de Dinámica: {sin_dato}.'
        ))
