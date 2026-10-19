"""
2026-10-19: junta los registros de Control Posparto duplicados (misma
paciente, mismo ingreso) en el registro principal -- ver frecuenciafetal/unicidad.py.

Sin --aplicar solo muestra lo que haría (no escribe nada):

    python manage.py fusionar_registros_posparto
    python manage.py fusionar_registros_posparto --documento 1007012196
    python manage.py fusionar_registros_posparto --documento 1007012196 --aplicar

Con --aplicar, todo lo del duplicado pasa al principal (los controles se
mueven con su firma original) y el duplicado se elimina solo si quedó vacío.
Lo que choca con un dato del principal se deja en el duplicado y se informa.
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from frecuenciafetal.models import RegistroParto
from frecuenciafetal.unicidad import cantidad_datos, fusionar_registros, registro_principal, registro_vacio


def _describir(r):
    return (f'{r.pk} | creado {r.created_at:%Y-%m-%d %H:%M} UTC por {r.creado_por or "?"} | '
            f'{"CERRADO" if r.completado_en else "abierto"} | '
            f'sangrado {r.controles_sangrado.count()}, globo {r.controles_globo.count()}, '
            f'sutura {r.controles_sutura.count()}, fetocardia {r.controles_fetocardia.count()}, '
            f'recién nacido {r.recien_nacidos.count()} | {cantidad_datos(r)} datos')


class Command(BaseCommand):
    help = 'Junta los registros de Control Posparto duplicados (misma paciente y mismo ingreso).'

    def add_arguments(self, parser):
        parser.add_argument('--documento', default='', help='Solo esta paciente.')
        parser.add_argument('--aplicar', action='store_true', help='Hacer la fusión (sin esto solo se muestra).')

    def handle(self, *args, **opts):
        documento = (opts['documento'] or '').strip()
        aplicar = opts['aplicar']
        grupos = (RegistroParto.objects.exclude(atencion__numero_ingreso__isnull=True)
                  .exclude(atencion__numero_ingreso='')
                  .order_by().values('identificacion', 'atencion__numero_ingreso')
                  .annotate(n=Count('id')).filter(n__gt=1))
        if documento:
            grupos = grupos.filter(identificacion=documento)
        grupos = list(grupos)
        if not grupos:
            self.stdout.write(self.style.SUCCESS('No hay registros duplicados por paciente e ingreso.'))
            return
        self.stdout.write(f'{"APLICANDO" if aplicar else "REVISIÓN (no se escribe nada)"}: {len(grupos)} paciente(s)/ingreso(s) con duplicados.\n')

        for g in grupos:
            registros = list(RegistroParto.objects.filter(
                identificacion=g['identificacion'], atencion__numero_ingreso=g['atencion__numero_ingreso']))
            principal = registro_principal(registros)
            self.stdout.write(self.style.MIGRATE_HEADING(
                f'Paciente {g["identificacion"]} · ingreso {g["atencion__numero_ingreso"]} · {len(registros)} registros'))
            self.stdout.write(f'  PRINCIPAL: {_describir(principal)}')
            for otro in registros:
                if otro.pk == principal.pk:
                    continue
                self.stdout.write(f'  duplicado: {_describir(otro)}')
                if otro.completado_en is not None:
                    self.stdout.write(self.style.WARNING('    Los dos están cerrados: se deja igual (revisar a mano).'))
                    continue
                if not aplicar:
                    continue
                movidos, conflictos = fusionar_registros(principal, otro)
                for m in movidos:
                    self.stdout.write(f'    → movido: {m}')
                for c in conflictos:
                    self.stdout.write(self.style.WARNING(f'    ⚠ {c}'))
                otro.refresh_from_db()
                if registro_vacio(otro) and not conflictos:
                    otro.delete()
                    self.stdout.write(self.style.SUCCESS('    Duplicado vacío eliminado.'))
                else:
                    self.stdout.write(self.style.WARNING('    El duplicado conserva datos en conflicto: no se eliminó.'))
            if aplicar:
                principal.refresh_from_db()
                self.stdout.write(self.style.SUCCESS(f'  RESULTADO: {_describir(principal)}'))
        if not aplicar:
            self.stdout.write('\nPara hacer la fusión, vuelva a ejecutar con --aplicar.')
