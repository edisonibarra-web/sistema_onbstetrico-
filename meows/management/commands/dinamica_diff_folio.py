"""
Herramienta de descubrimiento: identifica en qué tabla/columna de la BD
readonly de Dinamica (DGEMPRES_NEXUS) queda un dato que se diligencia desde
la pantalla de Dinamica, comparando una foto de "antes" contra una de
"despues" para el mismo folio clinico (HCNFOLIO).

Los formularios dinamicos de Dinamica (familia de tablas HCM*/HCMW*) usan
columnas genericas sin nombre descriptivo (HCCM03N09, HCCM00N256, etc.);
el significado de cada una no esta documentado en el diccionario de datos
del fabricante porque se configura por instalacion. Por eso el unico modo
confiable de mapearlas es empirico: capturar un valor reconocible desde la
UI de Dinamica y ver que celda cambio.

Uso:
    1) Antes de diligenciar el dato de prueba en Dinamica:
       python manage.py dinamica_diff_folio 12345 --modo antes

    2) Diligenciar en Dinamica el signo vital de prueba (ej. FC = 199,
       un valor que no se preste a confusion con otro dato) y guardarlo.

    3) Despues de guardar en Dinamica:
       python manage.py dinamica_diff_folio 12345 --modo despues --esperado 199

--esperado es opcional: si se pasa, resalta las celdas cuyo valor nuevo
coincide con ese texto, para ubicar la columna de un vistazo.

El folio (HCNFOLIO.OID) es el mismo numero que ya usan MEOWS/Trabajo de
Parto/Frecuencia Fetal para leer al paciente desde Dinamica.
"""
import json
import os
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections


def _json_default(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    return str(valor)


def _ruta_snapshot(folio):
    carpeta = os.path.join(settings.BASE_DIR, 'tmp_dinamica_diff')
    os.makedirs(carpeta, exist_ok=True)
    return os.path.join(carpeta, f'folio_{folio}.json')


def tomar_snapshot(folio):
    """
    Recorre todas las tablas HCM*/HCMW* que tienen columna HCNFOLIO y trae
    las filas asociadas al folio dado. Solo guarda tablas con datos, para
    no inflar el snapshot con cientos de tablas vacias.
    """
    resultado = {}
    with connections['readonly'].cursor() as cur:
        cur.execute("""
            SELECT DISTINCT TABLE_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE COLUMN_NAME = 'HCNFOLIO' AND TABLE_NAME LIKE 'HCM%%'
            ORDER BY TABLE_NAME
        """)
        tablas = [row[0] for row in cur.fetchall()]

        for tabla in tablas:
            cur.execute(f"SELECT * FROM {tabla} WHERE HCNFOLIO = %s", [folio])
            columnas = [c[0] for c in cur.description]
            filas = [dict(zip(columnas, fila)) for fila in cur.fetchall()]
            if filas:
                resultado[tabla] = filas
    return resultado


class Command(BaseCommand):
    help = (
        'Compara un snapshot "antes"/"despues" de las tablas de Dinamica '
        'para un folio, con el fin de descubrir en que tabla/columna queda '
        'un dato capturado desde la UI de Dinamica (ej. signos vitales).'
    )

    def add_arguments(self, parser):
        parser.add_argument('folio', type=int, help='HCNFOLIO.OID del paciente de prueba')
        parser.add_argument('--modo', choices=['antes', 'despues'], required=True)
        parser.add_argument(
            '--esperado', default=None,
            help='Valor de prueba que se diligencio en Dinamica (ej. 199), para resaltar la celda donde aparece.'
        )

    def handle(self, *args, **options):
        folio = options['folio']
        modo = options['modo']
        esperado = options['esperado']
        archivo = _ruta_snapshot(folio)

        if modo == 'antes':
            self.stdout.write(f'Consultando tablas de Dinamica para folio {folio}...')
            snapshot = tomar_snapshot(folio)
            with open(archivo, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, default=_json_default, ensure_ascii=False, indent=2)
            self.stdout.write(self.style.SUCCESS(
                f'[OK] Snapshot "antes" guardado ({len(snapshot)} tablas con datos) en {archivo}'
            ))
            self.stdout.write(
                'Ahora diligencia el dato de prueba en Dinamica y guarda, '
                'luego corre este comando con --modo despues.'
            )
            return

        # modo == 'despues'
        if not os.path.exists(archivo):
            raise CommandError(
                f'No existe snapshot "antes" para el folio {folio} ({archivo}). '
                'Corre primero con --modo antes.'
            )
        with open(archivo, 'r', encoding='utf-8') as f:
            antes = json.load(f)

        self.stdout.write(f'Consultando de nuevo las tablas de Dinamica para folio {folio}...')
        despues = tomar_snapshot(folio)

        hallazgos = []
        tablas_relevantes = sorted(set(antes) | set(despues))

        for tabla in tablas_relevantes:
            filas_antes = {str(f.get('OID')): f for f in antes.get(tabla, [])}
            filas_despues = {str(f.get('OID')): f for f in despues.get(tabla, [])}

            for oid, fila in filas_despues.items():
                if oid not in filas_antes:
                    hallazgos.append((tabla, oid, None, 'FILA NUEVA', fila))
                    continue
                fila_antes = filas_antes[oid]
                for col, val_despues in fila.items():
                    val_antes = fila_antes.get(col)
                    if str(val_antes) != str(val_despues):
                        hallazgos.append((tabla, oid, col, val_antes, val_despues))

        if not hallazgos:
            self.stdout.write(self.style.WARNING(
                'No se detectaron cambios entre "antes" y "despues" para este folio. '
                '¿Se guardó el dato en Dinamica? ¿Es el folio correcto?'
            ))
            return

        self.stdout.write(self.style.SUCCESS(f'\n{len(hallazgos)} cambio(s) detectado(s):\n'))
        for tabla, oid, col, val_antes, val_despues in hallazgos:
            if col == 'FILA NUEVA':
                self.stdout.write(f'  [{tabla}] OID={oid} -> fila nueva completa:')
                for k, v in val_despues.items():
                    marca = ' <== coincide con --esperado' if esperado and str(v) == str(esperado) else ''
                    self.stdout.write(f'      {k} = {v!r}{marca}')
            else:
                marca = ''
                if esperado and str(val_despues) == str(esperado):
                    marca = '  <== *** coincide con --esperado ***'
                self.stdout.write(
                    f'  [{tabla}] OID={oid}  {col}: {val_antes!r} -> {val_despues!r}{marca}'
                )

        if esperado:
            self.stdout.write(self.style.SUCCESS(
                f'\nBusca arriba las líneas marcadas con --esperado={esperado!r} '
                'para identificar la columna exacta.'
            ))
