"""
Management command para cargar los rangos de valores MEOWS desde las reglas estándar.
Ejecutar: python manage.py cargar_rangos_meows

Este comando carga los rangos iniciales basados en las reglas MEOWS estándar.
Los rangos pueden modificarse después desde el admin sin tocar código.
"""
from django.core.management.base import BaseCommand
from meows.models import Parametro, RangoParametro


# Definición de rangos basados en la tabla oficial MEOWS
RANGOS_MEOWS = {
    "temp": [  # Temperatura (°C)
        {"valor_min": 0, "valor_max": 33.9, "score": 3, "orden": 1},  # ROJO
        {"valor_min": 34.0, "valor_max": 34.9, "score": 3, "orden": 2},  # ROJO
        {"valor_min": 35.0, "valor_max": 35.9, "score": 1, "orden": 3},  # VERDE
        {"valor_min": 36.0, "valor_max": 37.4, "score": 0, "orden": 4},  # BLANCO
        {"valor_min": 37.5, "valor_max": 38.9, "score": 1, "orden": 5},  # VERDE (37 tiene score 1)
        {"valor_min": 39.0, "valor_max": 39.9, "score": 3, "orden": 6},  # ROJO
        {"valor_min": 40.0, "valor_max": 999, "score": 3, "orden": 7},  # ROJO
    ],
    "ta_sys": [  # Presión Arterial Sistólica (mmHg)
        {"valor_min": 0, "valor_max": 89, "score": 3, "orden": 1},  # ROJO (<90)
        {"valor_min": 90, "valor_max": 99, "score": 2, "orden": 2},  # AMARILLO
        {"valor_min": 100, "valor_max": 139, "score": 0, "orden": 3},  # BLANCO
        {"valor_min": 140, "valor_max": 149, "score": 1, "orden": 4},  # VERDE
        {"valor_min": 150, "valor_max": 159, "score": 2, "orden": 5},  # AMARILLO
        {"valor_min": 160, "valor_max": 999, "score": 3, "orden": 6},  # ROJO (>=160)
    ],
    "ta_dia": [  # Presión Arterial Diastólica (mmHg)
        {"valor_min": 0, "valor_max": 59, "score": 0, "orden": 1},  # BLANCO (<60, asumiendo normal)
        {"valor_min": 60, "valor_max": 89, "score": 0, "orden": 2},  # BLANCO
        {"valor_min": 90, "valor_max": 99, "score": 1, "orden": 3},  # VERDE
        {"valor_min": 100, "valor_max": 109, "score": 2, "orden": 4},  # AMARILLO
        {"valor_min": 110, "valor_max": 120, "score": 3, "orden": 5},  # ROJO
        {"valor_min": 121, "valor_max": 999, "score": 3, "orden": 6},  # ROJO (>120)
    ],
    "fc": [  # Frecuencia Cardiaca (lpm)
        {"valor_min": 0, "valor_max": 49, "score": 3, "orden": 1},  # ROJO (<50)
        {"valor_min": 50, "valor_max": 59, "score": 3, "orden": 2},  # ROJO (50)
        {"valor_min": 60, "valor_max": 109, "score": 0, "orden": 3},  # BLANCO
        {"valor_min": 110, "valor_max": 150, "score": 2, "orden": 4},  # AMARILLO (110-150)
        {"valor_min": 151, "valor_max": 999, "score": 3, "orden": 5},  # ROJO (>150)
    ],
    "fr": [  # Frecuencia Respiratoria (rpm)
        {"valor_min": 0, "valor_max": 4, "score": 3, "orden": 1},  # ROJO (<5)
        {"valor_min": 5, "valor_max": 9, "score": 3, "orden": 2},  # ROJO (5-9)
        {"valor_min": 10, "valor_max": 17, "score": 0, "orden": 3},  # BLANCO
        {"valor_min": 18, "valor_max": 24, "score": 1, "orden": 4},  # VERDE
        {"valor_min": 25, "valor_max": 29, "score": 2, "orden": 5},  # AMARILLO
        {"valor_min": 30, "valor_max": 999, "score": 3, "orden": 6},  # ROJO (>=30)
    ],
    "spo2": [  # Saturación de Oxígeno (%)
        # Nota: La tabla muestra % de O2 suplementario, pero mantenemos SaO2 estándar
        {"valor_min": 0, "valor_max": 89, "score": 3, "orden": 1},  # ROJO
        {"valor_min": 90, "valor_max": 92, "score": 2, "orden": 2},  # AMARILLO
        {"valor_min": 93, "valor_max": 94, "score": 1, "orden": 3},  # VERDE
        {"valor_min": 95, "valor_max": 100, "score": 0, "orden": 4},  # BLANCO (>=95%)
    ],
    "glasgow": [  # Escala de Glasgow
        {"valor_min": 0, "valor_max": 14, "score": 3, "orden": 1},  # ROJO (<15)
        {"valor_min": 15, "valor_max": 15, "score": 0, "orden": 2},  # BLANCO (Alerta=Glasgow 15)
    ],
    "fcf": [  # Frecuencia Cardíaca Fetal (lpm) — rango normal FIGO/OMS 110-160 lpm
        {"valor_min": 0, "valor_max": 99, "score": 3, "orden": 1},  # ROJO — bradicardia fetal severa (<100)
        {"valor_min": 100, "valor_max": 109, "score": 2, "orden": 2},  # AMARILLO — bradicardia fetal
        {"valor_min": 110, "valor_max": 160, "score": 0, "orden": 3},  # BLANCO — normal
        {"valor_min": 161, "valor_max": 180, "score": 2, "orden": 4},  # AMARILLO — taquicardia fetal
        {"valor_min": 181, "valor_max": 999, "score": 3, "orden": 5},  # ROJO — taquicardia fetal severa (>180)
    ],
}


class Command(BaseCommand):
    help = 'Carga los rangos de valores MEOWS desde las reglas estándar'

    def add_arguments(self, parser):
        parser.add_argument(
            '--sobrescribir',
            action='store_true',
            help='Sobrescribe los rangos existentes (por defecto solo crea nuevos)',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Iniciando carga de rangos MEOWS...'))
        
        sobrescribir = options['sobrescribir']
        total_cargados = 0
        total_existentes = 0
        total_errores = 0
        
        for codigo_parametro, rangos in RANGOS_MEOWS.items():
            try:
                parametro = Parametro.objects.get(codigo=codigo_parametro, activo=True)
                self.stdout.write(f'\n  Procesando: {parametro.nombre} ({codigo_parametro})')
                
                if sobrescribir:
                    RangoParametro.objects.filter(parametro=parametro).delete()
                    self.stdout.write(f'  [DEL] Rangos anteriores eliminados')
                
                for rango_data in rangos:
                    rango, created = RangoParametro.objects.get_or_create(
                        parametro=parametro,
                        valor_min=rango_data['valor_min'],
                        valor_max=rango_data['valor_max'],
                        defaults={
                            'score': rango_data['score'],
                            'orden': rango_data['orden'],
                            'activo': True,
                        }
                    )
                    
                    if not created and rango.score != rango_data['score']:
                        rango.score = rango_data['score']
                        rango.orden = rango_data['orden']
                        rango.activo = True
                        rango.save()
                        created = True
                    
                    if created:
                        total_cargados += 1
                        self.stdout.write(
                            f'  [OK] Creado: [{rango.valor_min}-{rango.valor_max}] = {rango.score}'
                        )
                    else:
                        total_existentes += 1
                        self.stdout.write(
                            f'  [->] Ya existe: [{rango.valor_min}-{rango.valor_max}] = {rango.score}'
                        )
                        
            except Parametro.DoesNotExist:
                total_errores += 1
                self.stdout.write(
                    self.style.ERROR(f'  [ERR] Parametro "{codigo_parametro}" no encontrado')
                )
            except Exception as e:
                total_errores += 1
                self.stdout.write(
                    self.style.ERROR(f'  [ERR] Error procesando "{codigo_parametro}": {e}')
                )
        
        self.stdout.write('\n' + '='*60)
        if total_cargados > 0:
            self.stdout.write(
                self.style.SUCCESS(f'[OK] Cargados {total_cargados} rangos nuevos')
            )
        if total_existentes > 0:
            self.stdout.write(
                self.style.WARNING(f'[->] {total_existentes} rangos ya existian')
            )
        if total_errores > 0:
            self.stdout.write(
                self.style.ERROR(f'[ERR] {total_errores} errores encontrados')
            )
        
        self.stdout.write(self.style.SUCCESS(
            f'\n[OK] Proceso completado: {total_cargados} nuevos, {total_existentes} existentes, {total_errores} errores'
        ))


