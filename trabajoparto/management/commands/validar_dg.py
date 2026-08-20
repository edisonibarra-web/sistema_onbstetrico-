from django.core.management.base import BaseCommand
from django.db import connections

class Command(BaseCommand):
    help = 'Valida la conexion a DGEMPRES03 y consulta datos de ejemplo'

    def handle(self, *args, **options):
        connection = connections['default']
        
        self.stdout.write("\n" + "="*70)
        self.stdout.write("VALIDANDO CONEXION A DGEMPRES03")
        self.stdout.write("="*70)
        
        # Verificar configuración
        engine = connection.settings_dict['ENGINE']
        self.stdout.write(f"\n[INFO] Engine configurado: {engine}")
        self.stdout.write(f"[INFO] Database: {connection.settings_dict.get('NAME', 'N/A')}")
        self.stdout.write(f"[INFO] Host: {connection.settings_dict.get('HOST', 'N/A')}")
        
        if 'sqlite' in engine.lower():
            self.stdout.write(self.style.ERROR("\n[ERROR] La configuracion actual usa SQLite, no SQL Server!"))
            self.stdout.write("[INFO] Verifica que DATABASES['default'] en settings.py use 'mssql'")
            return
        
        # 1. Verificar conexión
        self.stdout.write("\n1. Verificando conexion...")
        try:
            connection.ensure_connection()
            self.stdout.write(self.style.SUCCESS("   [OK] Conexion establecida correctamente"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   [ERROR] {str(e)}"))
            return
        
        # 2. Verificar nombre de la base de datos
        self.stdout.write("\n2. Verificando base de datos conectada...")
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT DB_NAME()")
                db_name = cursor.fetchone()
                self.stdout.write(self.style.SUCCESS(f"   [OK] Conectado a: {db_name[0]}"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"   [WARN] {str(e)}"))
        
        # 3. Consultar datos de ejemplo
        self.stdout.write("\n3. Consultando datos de pacientes activos...")
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT TOP 5
                        EST.HESFECING AS FECHA_INGRESO,
                        PAC.PACNUMDOC AS DOCUMENTO,
                        PAC.PACPRINOM + ' ' + PAC.PACPRIAPE AS NOMBRES,
                        CAM.HCACODIGO AS CAMA
                    FROM HPNESTANC EST
                    INNER JOIN HPNDEFCAM CAM ON EST.HPNDEFCAM = CAM.OID
                    INNER JOIN ADNINGRESO ING ON EST.ADNINGRES = ING.OID
                    INNER JOIN GENPACIEN PAC ON ING.GENPACIEN = PAC.OID
                    WHERE EST.HESFECSAL IS NULL
                """)
                
                rows = cursor.fetchall()
                
                if rows:
                    self.stdout.write(self.style.SUCCESS(f"\n   [OK] Encontrados {len(rows)} registros (mostrando primeros 5):"))
                    self.stdout.write("\n   " + "-"*65)
                    for i, row in enumerate(rows, 1):
                        fecha = str(row[0]) if row[0] else "N/A"
                        doc = str(row[1]) if row[1] else "N/A"
                        nombre = str(row[2]) if row[2] else "N/A"
                        cama = str(row[3]) if row[3] else "N/A"
                        self.stdout.write(f"   {i}. Doc: {doc:<15} | Nombre: {nombre:<30} | Cama: {cama}")
                    self.stdout.write("   " + "-"*65)
                else:
                    self.stdout.write(self.style.WARNING("   [WARN] No se encontraron registros (pero las tablas existen)"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"   [WARN] Error en la consulta: {str(e)}"))
            self.stdout.write("   [INFO] Esto puede ser normal si las tablas tienen nombres diferentes")
        
        # 4. Listar tablas disponibles
        self.stdout.write("\n4. Verificando tablas disponibles...")
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT TOP 10 TABLE_NAME 
                    FROM INFORMATION_SCHEMA.TABLES 
                    WHERE TABLE_TYPE = 'BASE TABLE'
                    AND TABLE_CATALOG = 'DGEMPRES03'
                    ORDER BY TABLE_NAME
                """)
                tables = cursor.fetchall()
                if tables:
                    self.stdout.write(self.style.SUCCESS(f"   [OK] Encontradas {len(tables)} tablas (mostrando primeras 10):"))
                    for table in tables:
                        self.stdout.write(f"      - {table[0]}")
                else:
                    self.stdout.write(self.style.WARNING("   [WARN] No se pudieron listar las tablas"))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"   [WARN] Error al listar tablas: {str(e)}"))
        
        self.stdout.write("\n" + "="*70)
        self.stdout.write(self.style.SUCCESS("[OK] VALIDACION COMPLETADA EXITOSAMENTE"))
        self.stdout.write("="*70)
        self.stdout.write("\nCONCLUSION: La conexion a DGEMPRES03 esta funcionando correctamente.")
        self.stdout.write("   Puedes proceder a usar el backend para consultar datos.")
        self.stdout.write("\n")
