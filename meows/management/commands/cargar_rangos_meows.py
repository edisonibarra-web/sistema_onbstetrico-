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
    "temp": [  # Temperatura (°C) — corregido para calzar con la tabla oficial MEOWS (imagen de referencia)
        {"valor_min": 0, "valor_max": 33.9, "score": 3, "orden": 1},  # ROJO (<34)
        {"valor_min": 34.0, "valor_max": 35.0, "score": 1, "orden": 2},  # VERDE (34-35) — antes daba 3 en 34.0-34.9
        {"valor_min": 35.1, "valor_max": 37.9, "score": 0, "orden": 3},  # BLANCO (35.1-37.9) — antes el normal terminaba en 37.4
        {"valor_min": 38.0, "valor_max": 38.9, "score": 1, "orden": 4},  # VERDE (38-38.9)
        {"valor_min": 39.0, "valor_max": 999, "score": 3, "orden": 5},  # ROJO (>=39)
    ],
    "ta_sys": [  # Presión Arterial Sistólica (mmHg) — corregido para calzar con la tabla oficial MEOWS
        {"valor_min": 0, "valor_max": 79, "score": 3, "orden": 1},  # ROJO (<80)
        {"valor_min": 80, "valor_max": 89, "score": 2, "orden": 2},  # AMARILLO (80-90) — antes daba 3 (crítico)
        {"valor_min": 90, "valor_max": 139, "score": 0, "orden": 3},  # BLANCO
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
    "fc": [  # Frecuencia Cardiaca (lpm) — corregido para calzar con la tabla oficial MEOWS
        {"valor_min": 0, "valor_max": 59, "score": 3, "orden": 1},  # ROJO (<60)
        {"valor_min": 60, "valor_max": 110, "score": 0, "orden": 2},  # BLANCO (60-110) — antes el normal terminaba en 109
        {"valor_min": 111, "valor_max": 149, "score": 2, "orden": 3},  # AMARILLO (111-149)
        {"valor_min": 150, "valor_max": 999, "score": 3, "orden": 4},  # ROJO (>=150) — antes 150 exacto daba 2 en vez de 3
    ],
    "fr": [  # Frecuencia Respiratoria (rpm)
        {"valor_min": 0, "valor_max": 4, "score": 3, "orden": 1},  # ROJO (<5)
        {"valor_min": 5, "valor_max": 9, "score": 3, "orden": 2},  # ROJO (5-9)
        {"valor_min": 10, "valor_max": 17, "score": 0, "orden": 3},  # BLANCO
        {"valor_min": 18, "valor_max": 24, "score": 1, "orden": 4},  # VERDE
        {"valor_min": 25, "valor_max": 29, "score": 2, "orden": 5},  # AMARILLO
        {"valor_min": 30, "valor_max": 999, "score": 3, "orden": 6},  # ROJO (>=30)
    ],
    # "spo2" (Saturación de Oxígeno por oximetría de pulso) — QUITADO el 2026-09-09.
    # Se usaba como sustituto de "% de O2 requerido" (tabla oficial MEOWS) mientras
    # Dinámica no tenía ese campo disponible (solo traía SpO2 directo del oxímetro,
    # OID 22 "SATURACION ARTERIAL DE OXIGENO"). Con "o2_req" ya confirmado y en uso
    # (ver más abajo), SpO2 sobra — se desactivó el Parametro (activo=False) y se
    # quitó su extracción en meows/services/dinamica_signos_vitales.py. Rangos que
    # tenía, por si algún día hiciera falta reactivarlo:
    #   0-89 -> 3 (ROJO), 90-92 -> 2 (AMARILLO), 93-94 -> 1 (VERDE), 95-100 -> 0 (BLANCO)
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


