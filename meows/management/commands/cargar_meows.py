"""
Management command para cargar los parámetros MEOWS desde el archivo congelado.
Ejecutar: python manage.py cargar_meows
"""
from django.core.management.base import BaseCommand
from meows.services.carga_meows import cargar_parametros_meows


class Command(BaseCommand):
    help = 'Carga los parámetros MEOWS desde el archivo congelado meows_params.py'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Iniciando carga de parametros MEOWS...'))
        
        cargados, existentes = cargar_parametros_meows()
        
        if cargados > 0:
            self.stdout.write(
                self.style.SUCCESS(f'[OK] Cargados {cargados} parametros nuevos')
            )
        
        if existentes > 0:
            self.stdout.write(
                self.style.WARNING(f'[->] {existentes} parametros ya existian')
            )
        
        self.stdout.write(self.style.SUCCESS(
            f'\n[OK] Proceso completado: {cargados} nuevos, {existentes} existentes'
        ))

