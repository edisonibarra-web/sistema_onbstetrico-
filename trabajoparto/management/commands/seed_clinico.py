from django.core.management.base import BaseCommand
from trabajoparto.models import Item, Parametro, CampoParametro, TipoValor, Aseguradora


class Command(BaseCommand):
    help = 'Poblar las tablas Item, Parametro y Aseguradora con datos clínicos maternos'

    def handle(self, *args, **options):
        self.stdout.write('Iniciando seed de datos clínicos...')

        # Primero crear las aseguradoras
        self.create_aseguradoras()

        # Controles Maternos
        item_controles_maternos, created = Item.objects.get_or_create(
            codigo='CTRL_MAT',
            defaults={'nombre': 'Controles Maternos'}
        )
        if created:
            self.stdout.write(f'[OK] Item creado: {item_controles_maternos.nombre}')
        else:
            self.stdout.write(f'- Item existente: {item_controles_maternos.nombre}')

        parametros_controles = [
            {'codigo': 'TENSION_ART', 'nombre': 'Tensión arterial', 'unidad': 'mmHg', 'orden': 1},
            {'codigo': 'FREC_CARD', 'nombre': 'Frec. Cardiaca', 'unidad': 'lpm', 'orden': 2},
            {'codigo': 'FREC_RESP', 'nombre': 'Frec. Respiratoria', 'unidad': 'rpm', 'orden': 3},
            {'codigo': 'TEMPERATURA', 'nombre': 'Temperatura', 'unidad': '°C', 'orden': 4},
        ]

        for param_data in parametros_controles:
            param, created = Parametro.objects.get_or_create(
                item=item_controles_maternos,
                codigo=param_data['codigo'],
                defaults={
                    'nombre': param_data['nombre'],
                    'unidad': param_data['unidad'],
                    'orden': param_data['orden']
                }
            )
            if created:
                self.stdout.write(f'  [OK] Parámetro creado: {param.nombre}')
            else:
                self.stdout.write(f'  - Parámetro existente: {param.nombre}')

        # Contracciones uterinas
        item_contracciones, created = Item.objects.get_or_create(
            codigo='CONTRAC_UTER',
            defaults={'nombre': 'Contracciones uterinas'}
        )
        if created:
            self.stdout.write(f'[OK] Item creado: {item_contracciones.nombre}')
        else:
            self.stdout.write(f'- Item existente: {item_contracciones.nombre}')

        parametros_contracciones = [
            {'codigo': 'FRECUENCIA', 'nombre': 'Frecuencia', 'unidad': 'min', 'orden': 1},
            {'codigo': 'DURACION', 'nombre': 'Duración', 'unidad': 'seg', 'orden': 2},
            {'codigo': 'INTENSIDAD', 'nombre': 'Intensidad', 'unidad': None, 'orden': 3},
        ]

        for param_data in parametros_contracciones:
            param, created = Parametro.objects.get_or_create(
                item=item_contracciones,
                codigo=param_data['codigo'],
                defaults={
                    'nombre': param_data['nombre'],
                    'unidad': param_data['unidad'],
                    'orden': param_data['orden']
                }
            )
            if created:
                self.stdout.write(f'  [OK] Parámetro creado: {param.nombre}')
            else:
                self.stdout.write(f'  - Parámetro existente: {param.nombre}')

        # Control Fetal
        item_control_fetal, created = Item.objects.get_or_create(
            codigo='CTRL_FETAL',
            defaults={'nombre': 'Control Fetal'}
        )
        if created:
            self.stdout.write(f'[OK] Item creado: {item_control_fetal.nombre}')
        else:
            self.stdout.write(f'- Item existente: {item_control_fetal.nombre}')

        parametros_fetal = [
            {'codigo': 'FREC_CARD_FETAL', 'nombre': 'Frecuencia Cardiaca Fetal', 'unidad': 'lpm', 'orden': 1},
            {'codigo': 'MOV_FETALES', 'nombre': 'Movimientos Fetales', 'unidad': None, 'orden': 2},
            {'codigo': 'PRESENTACION', 'nombre': 'Presentación', 'unidad': None, 'orden': 3},
        ]

        for param_data in parametros_fetal:
            param, created = Parametro.objects.get_or_create(
                item=item_control_fetal,
                codigo=param_data['codigo'],
                defaults={
                    'nombre': param_data['nombre'],
                    'unidad': param_data['unidad'],
                    'orden': param_data['orden']
                }
            )
            if created:
                self.stdout.write(f'  [OK] Parámetro creado: {param.nombre}')
            else:
                self.stdout.write(f'  - Parámetro existente: {param.nombre}')

        # Tacto Vaginal
        item_tacto, created = Item.objects.get_or_create(
            codigo='TACTO_VAG',
            defaults={'nombre': 'Tacto Vaginal'}
        )
        if created:
            self.stdout.write(f'[OK] Item creado: {item_tacto.nombre}')
        else:
            self.stdout.write(f'- Item existente: {item_tacto.nombre}')

        parametros_tacto = [
            {'codigo': 'MEMB_INTEGRAS', 'nombre': 'Membranas Integras', 'unidad': None, 'orden': 1},
            {'codigo': 'MEMB_ROTAS', 'nombre': 'Membranas Rotas', 'unidad': None, 'orden': 2},
            {'codigo': 'LIQ_AMNIOTICO', 'nombre': 'Liquido Amniotico', 'unidad': None, 'orden': 3},
            {'codigo': 'HORA_RUPTURA', 'nombre': 'Hora Ruptura', 'unidad': None, 'orden': 4},
            {'codigo': 'DILATACION', 'nombre': 'Dilatación', 'unidad': 'cm', 'orden': 5},
            {'codigo': 'BORRAMIENTO', 'nombre': 'Borramiento', 'unidad': '%', 'orden': 6},
        ]

        for param_data in parametros_tacto:
            param, created = Parametro.objects.get_or_create(
                item=item_tacto,
                codigo=param_data['codigo'],
                defaults={
                    'nombre': param_data['nombre'],
                    'unidad': param_data['unidad'],
                    'orden': param_data['orden']
                }
            )
            if created:
                self.stdout.write(f'  [OK] Parámetro creado: {param.nombre}')
            else:
                self.stdout.write(f'  - Parámetro existente: {param.nombre}')

        # Monitoreo Fetal
        item_monitoreo, created = Item.objects.get_or_create(
            codigo='MON_FETAL',
            defaults={'nombre': 'Monitoreo Fetal'}
        )
        if created:
            self.stdout.write(f'[OK] Item creado: {item_monitoreo.nombre}')
        else:
            self.stdout.write(f'- Item existente: {item_monitoreo.nombre}')

        parametros_monitoreo = [
            {'codigo': 'HORA', 'nombre': 'Hora', 'unidad': None, 'orden': 1},
            {'codigo': 'CATEGORIA', 'nombre': 'Categoria', 'unidad': None, 'orden': 2},
        ]

        for param_data in parametros_monitoreo:
            param, created = Parametro.objects.get_or_create(
                item=item_monitoreo,
                codigo=param_data['codigo'],
                defaults={
                    'nombre': param_data['nombre'],
                    'unidad': param_data['unidad'],
                    'orden': param_data['orden']
                }
            )
            if created:
                self.stdout.write(f'  [OK] Parámetro creado: {param.nombre}')
            else:
                self.stdout.write(f'  - Parámetro existente: {param.nombre}')

        # Oxitocina
        item_oxitocina, created = Item.objects.get_or_create(
            codigo='OXITOCINA',
            defaults={'nombre': 'Oxitocina'}
        )
        if created:
            self.stdout.write(f'[OK] Item creado: {item_oxitocina.nombre}')
        else:
            self.stdout.write(f'- Item existente: {item_oxitocina.nombre}')

        parametros_oxitocina = [
            {'codigo': 'MILIUNIDADES', 'nombre': 'Miliunidades', 'unidad': 'mU', 'orden': 1},
            {'codigo': 'CC_H', 'nombre': 'CC/H', 'unidad': 'cc/h', 'orden': 2},
        ]

        for param_data in parametros_oxitocina:
            param, created = Parametro.objects.get_or_create(
                item=item_oxitocina,
                codigo=param_data['codigo'],
                defaults={
                    'nombre': param_data['nombre'],
                    'unidad': param_data['unidad'],
                    'orden': param_data['orden']
                }
            )
            if created:
                self.stdout.write(f'  [OK] Parámetro creado: {param.nombre}')
            else:
                self.stdout.write(f'  - Parámetro existente: {param.nombre}')

        # Crear campos básicos para algunos parámetros que los requieran
        self.create_basic_fields()

        self.stdout.write(
            self.style.SUCCESS('¡Seed completado exitosamente!')
        )

    def create_aseguradoras(self):
        """Crear las aseguradoras principales"""
        self.stdout.write('\nCreando aseguradoras...')
        
        aseguradoras_data = [
            'Sura EPS',
            'Nueva EPS',
            'Sanitas',
            'Famisanar',
            'Coosalud',
            'Mutual SER',
            'Emssanar'
        ]

        for nombre_aseguradora in aseguradoras_data:
            aseguradora, created = Aseguradora.objects.get_or_create(
                nombre=nombre_aseguradora
            )
            if created:
                self.stdout.write(f'[OK] Aseguradora creada: {aseguradora.nombre}')
            else:
                self.stdout.write(f'- Aseguradora existente: {aseguradora.nombre}')

    def create_basic_fields(self):
        """Crear campos básicos para parámetros que los requieran"""
        
        # Campos para tensión arterial (sistólica y diastólica)
        tension_param = Parametro.objects.filter(codigo='TENSION_ART').first()
        if tension_param:
            CampoParametro.objects.get_or_create(
                parametro=tension_param,
                codigo='SISTOLICA',
                defaults={
                    'nombre': 'Sistólica',
                    'tipo_valor': TipoValor.NUMBER,
                    'unidad': 'mmHg',
                    'orden': 1
                }
            )
            CampoParametro.objects.get_or_create(
                parametro=tension_param,
                codigo='DIASTOLICA',
                defaults={
                    'nombre': 'Diastólica',
                    'tipo_valor': TipoValor.NUMBER,
                    'unidad': 'mmHg',
                    'orden': 2
                }
            )

        # Campo simple para otros parámetros numéricos
        numeric_params = ['FREC_CARD', 'FREC_RESP', 'TEMPERATURA', 'FREC_CARD_FETAL', 'DILATACION', 'BORRAMIENTO']
        for param_codigo in numeric_params:
            param = Parametro.objects.filter(codigo=param_codigo).first()
            if param:
                CampoParametro.objects.get_or_create(
                    parametro=param,
                    codigo='VALOR',
                    defaults={
                        'nombre': 'Valor',
                        'tipo_valor': TipoValor.NUMBER,
                        'unidad': param.unidad,
                        'orden': 1
                    }
                )

        # Campos de texto para parámetros descriptivos
        text_params = ['INTENSIDAD', 'MOV_FETALES', 'PRESENTACION', 'LIQ_AMNIOTICO', 'CATEGORIA']
        for param_codigo in text_params:
            param = Parametro.objects.filter(codigo=param_codigo).first()
            if param:
                CampoParametro.objects.get_or_create(
                    parametro=param,
                    codigo='DESCRIPCION',
                    defaults={
                        'nombre': 'Descripción',
                        'tipo_valor': TipoValor.TEXT,
                        'orden': 1
                    }
                )

        # Campos booleanos para membranas
        bool_params = ['MEMB_INTEGRAS', 'MEMB_ROTAS']
        for param_codigo in bool_params:
            param = Parametro.objects.filter(codigo=param_codigo).first()
            if param:
                CampoParametro.objects.get_or_create(
                    parametro=param,
                    codigo='ESTADO',
                    defaults={
                        'nombre': 'Estado',
                        'tipo_valor': TipoValor.BOOLEAN,
                        'orden': 1
                    }
                )

        # Campos especiales para tiempo
        time_params = ['FRECUENCIA', 'DURACION', 'HORA_RUPTURA', 'HORA']
        for param_codigo in time_params:
            param = Parametro.objects.filter(codigo=param_codigo).first()
            if param:
                CampoParametro.objects.get_or_create(
                    parametro=param,
                    codigo='TIEMPO',
                    defaults={
                        'nombre': 'Tiempo',
                        'tipo_valor': TipoValor.TEXT,
                        'orden': 1
                    }
                )

        # Campos para oxitocina
        oxitocina_params = ['MILIUNIDADES', 'CC_H']
        for param_codigo in oxitocina_params:
            param = Parametro.objects.filter(codigo=param_codigo).first()
            if param:
                CampoParametro.objects.get_or_create(
                    parametro=param,
                    codigo='CANTIDAD',
                    defaults={
                        'nombre': 'Cantidad',
                        'tipo_valor': TipoValor.NUMBER,
                        'unidad': param.unidad,
                        'orden': 1
                    }
                )

        self.stdout.write('[OK] Campos básicos creados para los parámetros')