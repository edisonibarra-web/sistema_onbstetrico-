"""
SOLO DESARROLLO: paciente egresada FICTICIA para probar la Consulta histórica
sin conexión a Dinámica.

    python manage.py demo_consulta_historica            # crea la paciente y abre el servidor en :8000
    python manage.py demo_consulta_historica --puerto 8001
    python manage.py demo_consulta_historica --limpiar  # borra todo lo de la paciente demo

Crea (con la cédula 9900000001, "PACIENTE DEMO EGRESADA"):
  - Ingreso 9000001 (egresado): triaje, MEOWS, trabajo de parto y control
    posparto en la carpeta LOCAL de pruebas; el posparto con dos versiones.
  - Ingreso 9000002 (egresado): triaje y MEOWS, y un Control Posparto que
    nunca se cerró (falta el acompañante) -> aviso naranja de faltante.
  - Ingreso 9000003 (en curso): no debe aparecer.
y levanta el servidor de desarrollo simulando las respuestas de Dinámica solo
para esa cédula (y para los usuarios DEMO1 / DEMO2 en "Usuarios autorizados").
Se niega a correr si DEBUG no es True o si REPOSITORIO_MODO no es "local".
"""
import io
import shutil
from datetime import datetime
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

CEDULA = '9900000001'
NOMBRE = 'PACIENTE DEMO EGRESADA'
INGRESOS = [  # numero, ingreso, egreso
    ('9000003', datetime(2026, 10, 19, 8, 0), None),
    ('9000002', datetime(2026, 10, 15, 9, 30), datetime(2026, 10, 17, 14, 0)),
    ('9000001', datetime(2026, 10, 10, 7, 15), datetime(2026, 10, 12, 16, 45)),
]
USUARIOS = {
    'DEMO1': {'usuario': 'DEMO1', 'nombre': 'USUARIO DEMO UNO', 'activo': True},
    'DEMO2': {'usuario': 'DEMO2', 'nombre': 'USUARIO DEMO DOS (INACTIVO)', 'activo': False},
}


def _aware(dt):
    return timezone.make_aware(dt) if dt else None


def _pdf(titulo, ingreso, version=1):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    salida = io.BytesIO()
    c = canvas.Canvas(salida, pagesize=letter)
    c.setFont('Helvetica-Bold', 20)
    c.drawString(72, 700, titulo)
    c.setFont('Helvetica', 12)
    c.drawString(72, 670, f'{NOMBRE} - Cedula {CEDULA}')
    c.drawString(72, 650, f'Ingreso {ingreso} - version {version}')
    c.setFillColorRGB(0.8, 0.1, 0.1)
    c.drawString(72, 610, 'DOCUMENTO DE DEMOSTRACION - DATOS FICTICIOS')
    c.save()
    return salida.getvalue()


class Command(BaseCommand):
    help = 'SOLO DESARROLLO: paciente egresada ficticia para probar la Consulta histórica sin Dinámica.'

    def add_arguments(self, parser):
        parser.add_argument('--puerto', default='8000')
        parser.add_argument('--limpiar', action='store_true', help='Borrar la paciente demo y salir.')

    def handle(self, *args, puerto, limpiar, **opts):
        if not settings.DEBUG or settings.REPOSITORIO_MODO != 'local':
            raise CommandError('Solo para desarrollo: requiere DJANGO_DEBUG=True y REPOSITORIO_MODO=local.')
        self._limpiar()
        if limpiar:
            self.stdout.write(self.style.SUCCESS('Paciente demo borrada.'))
            return
        self._crear()
        self.stdout.write(self.style.SUCCESS(
            f'\nPaciente demo lista. Abra http://localhost:{puerto}/atencion/historico/ con su usuario admin y busque:\n'
            f'  - Cédula {CEDULA}  (2 ingresos egresados; el 9000003 en curso no aparece)\n'
            f'  - Número de ingreso 9000002  (muestra el aviso de posparto sin cerrar)\n'
            f'  - Número de ingreso 9000003  (en curso: debe decir que no tiene egreso)\n'
            f'  - En "Usuarios autorizados": DEMO1 (activo) o DEMO2 (inactivo)\n'
            f'Para terminar: Ctrl+C. Para borrar la demo: manage.py demo_consulta_historica --limpiar\n'
        ))
        for p in self._simular_dinamica():
            p.start()
        call_command('runserver', puerto, use_reloader=False)

    # ------------------------------------------------------------------
    def _carpeta(self):
        return settings.REPOSITORIO_LOCAL_DIR / CEDULA

    def _limpiar(self):
        from frecuenciafetal.models import RegistroParto
        from obstetriciaunificador.models import AtencionParto, DocumentoRepositorio
        RegistroParto.objects.filter(identificacion=CEDULA).delete()
        DocumentoRepositorio.objects.filter(cedula=CEDULA).delete()
        AtencionParto.objects.filter(paciente=CEDULA).delete()
        shutil.rmtree(self._carpeta(), ignore_errors=True)

    def _crear(self):
        from frecuenciafetal.models import RegistroParto
        from obstetriciaunificador.models import AtencionParto, DocumentoRepositorio
        from obstetriciaunificador.repositorio import FORMATOS

        atenciones = {
            numero: AtencionParto.objects.create(paciente=CEDULA, numero_ingreso=numero, fecha_ingreso_dinamica=_aware(ing))
            for numero, ing, _ in INGRESOS
        }

        def guardar(ingreso, formato, titulo, version=1, referencia=''):
            carpeta = self._carpeta() / ingreso
            carpeta.mkdir(parents=True, exist_ok=True)
            nombre = f'otros_{FORMATOS[formato]}_{CEDULA}_{version}.pdf'
            (carpeta / nombre).write_bytes(_pdf(titulo, ingreso, version))
            DocumentoRepositorio.objects.create(
                atencion=atenciones[ingreso], cedula=CEDULA, numero_ingreso=ingreso, formato=formato,
                referencia=str(referencia), modo='local', estado=DocumentoRepositorio.ESTADO_ENVIADO,
                nombre_archivo=nombre, ruta=str(carpeta / nombre), enviado_por='demo',
            )

        # Ingreso 9000001: completo, posparto cerrado con dos versiones.
        cerrado = RegistroParto.objects.create(
            atencion=atenciones['9000001'], nombre_paciente=NOMBRE, identificacion=CEDULA, edad_gestacional=39,
            nombre_acompanante='ACOMPAÑANTE DEMO', completado_en=_aware(datetime(2026, 10, 11, 9, 0)),
            completado_por='DEMO',
        )
        RegistroParto.objects.filter(pk=cerrado.pk).update(created_at=_aware(datetime(2026, 10, 10, 20, 0)))
        guardar('9000001', 'triaje', 'TRIAJE OBSTETRICO')
        guardar('9000001', 'meows', 'ESCALA MEOWS')
        guardar('9000001', 'trabajo_parto', 'TRABAJO DE PARTO')
        guardar('9000001', 'control_posparto', 'CONTROL POSPARTO INMEDIATO', 1, cerrado.pk)
        guardar('9000001', 'control_posparto', 'CONTROL POSPARTO INMEDIATO (corregido)', 2, cerrado.pk)

        # Ingreso 9000002: posparto sin cerrar (sin acompañante) -> aviso.
        abierto = RegistroParto.objects.create(
            atencion=atenciones['9000002'], nombre_paciente=NOMBRE, identificacion=CEDULA, edad_gestacional=38,
        )
        RegistroParto.objects.filter(pk=abierto.pk).update(created_at=_aware(datetime(2026, 10, 16, 3, 0)))
        guardar('9000002', 'triaje', 'TRIAJE OBSTETRICO')
        guardar('9000002', 'meows', 'ESCALA MEOWS')

    def _simular_dinamica(self):
        from frecuenciafetal import sala_partos_db as db
        from obstetriciaunificador import ingresos as ing

        originales = {
            'ingresos': db.consultar_ingresos_paciente, 'nombre': db.consultar_nombre_paciente,
            'de_ingreso': db.consultar_paciente_de_ingreso, 'usuario': db.consultar_usuario_dinamica,
            'ingresos_app': ing.ingresos_de_paciente,
        }

        def ingresos_paciente(cedula):
            if (cedula or '').strip() != CEDULA:
                return originales['ingresos'](cedula)
            return [{'numero_ingreso': n, 'fecha_ingreso': i, 'fecha_egreso': e, 'anulado': False,
                     'tipo': 'hospitalizacion', 'estancia_abierta': e is None} for n, i, e in INGRESOS]

        def nombre_paciente(cedula):
            return ('PACIENTE DEMO', 'EGRESADA') if (cedula or '').strip() == CEDULA else originales['nombre'](cedula)

        def paciente_de_ingreso(numero):
            for n, i, e in INGRESOS:
                if str(numero).strip() == n:
                    return {'cedula': CEDULA, 'nombre': NOMBRE, 'fecha_ingreso': i, 'fecha_egreso': e,
                            'anulado': False, 'tipo': 'hospitalizacion'}
            return originales['de_ingreso'](numero)

        def usuario_dinamica(usuario):
            return USUARIOS.get((usuario or '').strip().upper()) or originales['usuario'](usuario)

        def ingresos_de_paciente(doc, fresco=False):
            if (doc or '').strip() != CEDULA:
                return originales['ingresos_app'](doc, fresco=fresco)
            lista = [{'numero': n, 'fecha_ingreso': _aware(i), 'fecha_egreso': _aware(e), 'tipo': 'hospitalizacion',
                      'anulado': False, 'fuente': 'dinamica'} for n, i, e in INGRESOS]
            ing._calcular_ventanas(lista)
            return lista, True, '9000003'

        return [
            mock.patch.object(db, 'consultar_ingresos_paciente', ingresos_paciente),
            mock.patch.object(db, 'consultar_nombre_paciente', nombre_paciente),
            mock.patch.object(db, 'consultar_paciente_de_ingreso', paciente_de_ingreso),
            mock.patch.object(db, 'consultar_usuario_dinamica', usuario_dinamica),
            mock.patch.object(ing, 'ingresos_de_paciente', ingresos_de_paciente),
        ]
