from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.http import HttpResponse
from django.db import connections, models
from django.db.models import Q
from django.conf import settings
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from datetime import date
import logging
import re
import json
import base64
import time
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.core.cache import cache
from sistema_obstetrico.auth_utils import login_required_if_enabled

logger = logging.getLogger(__name__)


def _mas_reciente_con_archivo(queryset, campo):
    """
    Devuelve el registro más reciente (por -fecha) cuyo archivo en `campo`
    exista realmente en el storage, saltando referencias huérfanas (filas
    cuyo ImageField apunta a una ruta cuyo archivo físico ya no está,
    p.ej. datos importados de otro entorno sin copiar el media completo).
    """
    for registro in queryset.order_by('-fecha'):
        archivo = getattr(registro, campo)
        if archivo and default_storage.exists(archivo.name):
            return registro
    return None


@never_cache
@login_required_if_enabled
def parto_home(request):
    """Entrada simple del modulo Parto desde la vista unificada."""
    atencion_id = request.GET.get("atencion")
    documento = request.GET.get("doc")

    formularios = Formulario.objects.all()
    estructura = []

    for formulario in formularios:
        relaciones = (
            FormularioItemParametro.objects
            .filter(formulario=formulario)
            .select_related("item", "parametro")
            .prefetch_related("parametro__campos")
        )

        data_items = []
        for relacion in relaciones:
            opciones = relacion.parametro.campos.all()
            data_items.append({
                "item": relacion.item,
                "parametro": relacion.parametro,
                "opciones": opciones,
            })

        estructura.append({
            "formulario": formulario,
            "items": data_items,
        })

    # Estructura plana para template: [{parametro, opciones}, ...]
    estructura_plana = []
    if estructura:
        for item in estructura[0]["items"]:
            estructura_plana.append({
                "parametro": item["parametro"],
                "opciones": item["opciones"],
            })

    # Items con parámetros y campos para modales dinámicos (selects con opciones)
    items = Item.objects.prefetch_related('parametros__campos').all().order_by('id')

    # Estructura ligera (solo parámetros activos) para que la Vista Previa arme
    # su grilla en JS con la MISMA jerarquía Item → Parámetro que usa el PDF
    # (FRSPA-022), en vez de mantener una lista de categorías/nombres a mano
    # que se desactualiza cada vez que se agregan/quitan parámetros del formulario.
    estructura_grid = [
        {
            "id": item.id,
            "nombre": item.nombre,
            "parametros": [
                {"id": p.id, "nombre": p.nombre, "unidad": p.unidad or ""}
                for p in item.parametros.all() if p.activo
            ],
        }
        for item in items
    ]
    estructura_grid = [i for i in estructura_grid if i["parametros"]]

    context = {
        "atencion_id": atencion_id,
        "documento": documento,
        "estructura": estructura,
        "estructura_plana": estructura_plana,
        "items": items,
        "estructura_grid": estructura_grid,
        "profesional_nombre_sesion": request.session.get('dgh_info', {}).get('nombre_completo') or '',
    }
    return render(request, "desarrollo_frontend.html", context)


# ============================================================================
# HELPER FUNCTIONS PARA CONEXIÓN A DGEMPRES03 (READONLY)
# ============================================================================
def get_readonly_connection():
    """
    Obtiene la conexión a la base de datos DGEMPRES03 (readonly).
    
    IMPORTANTE: Esta función garantiza que todas las consultas a DGEMPRES03
    usen la conexión 'readonly', manteniendo la base de datos como solo lectura.
    
    Uso:
        connection = get_readonly_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT ... FROM DGEMPRES03...")
    
    Returns:
        Database connection object para DGEMPRES03 (readonly)
    """
    connection = connections['readonly']
    connection.ensure_connection()
    return connection

from trabajoparto.models import (
    Aseguradora,
    Paciente,
    Formulario,
    Item,
    Parametro,
    FormularioItemParametro,
    CampoParametro,
    Medicion,
    MedicionValor,
    Huella
)


from trabajoparto.utils_aseguradora import resolver_aseguradora_por_nombre
from trabajoparto.serializers import (
    AseguradoraSerializer,
    PacienteSerializer,
    PacienteListSerializer,
    FormularioSerializer,
    FormularioCreateSerializer,
    ItemSerializer,
    ParametroSerializer,
    CampoParametroSerializer,
    FormularioItemParametroSerializer,
    MedicionSerializer,
    MedicionCreateSerializer,
    MedicionValorSerializer,
    PacienteCompletoSerializer,
)


class AseguradoraViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar Aseguradoras
    Permite CRUD completo sobre el modelo Aseguradora
    """
    queryset = Aseguradora.objects.all()
    serializer_class = AseguradoraSerializer
    lookup_field = 'id'


class PacienteViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar Pacientes
    Permite CRUD completo sobre el modelo Paciente
    """
    queryset = Paciente.objects.all()
    serializer_class = PacienteSerializer
    lookup_field = 'id'
    
    def get_queryset(self):
        """
        Permite filtrar pacientes por num_identificacion o num_historia_clinica
        Ejemplo: /api/pacientes/?num_identificacion=123456
        """
        queryset = Paciente.objects.all()
        
        num_identificacion = self.request.query_params.get('num_identificacion', None)
        if num_identificacion:
            queryset = queryset.filter(num_identificacion=num_identificacion.strip())
            
        num_historia_clinica = self.request.query_params.get('num_historia_clinica', None)
        if num_historia_clinica:
            queryset = queryset.filter(num_historia_clinica=num_historia_clinica.strip())
            
        return queryset
    
    def get_serializer_class(self):
        """Retorna el serializador apropiado según la acción"""
        # Usamos PacienteSerializer para todo, para asegurar que incluya fecha_nacimiento
        return PacienteSerializer

    def perform_update(self, serializer):
        """
        Invalida el caché rápido de `buscar_completo` (TTL 10s) al guardar,
        para que una actualización de aseguradora/tipo_sangre/etc. no siga
        sirviéndose obsoleta durante esa ventana.
        """
        instance = serializer.save()
        cache.delete(f"resp_completa_{instance.num_identificacion}")

    @action(detail=True, methods=['get'])
    def formularios(self, request, id=None):
        """Obtiene todos los formularios de un paciente"""
        paciente = self.get_object()
        formularios = Formulario.objects.filter(paciente=paciente).select_related('paciente', 'aseguradora')
        serializer = FormularioSerializer(formularios, many=True)
        return Response(serializer.data)
    
    @swagger_auto_schema(
        method='get',
        manual_parameters=[
            openapi.Parameter(
                'cedula',
                openapi.IN_QUERY,
                description="Número de identificación (cédula) del paciente",
                type=openapi.TYPE_STRING,
                required=True,
                example="59814467"
            ),
        ],
        responses={
            200: openapi.Response(
                description="Datos del paciente encontrado en DGEMPRES03",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'num_identificacion': openapi.Schema(type=openapi.TYPE_STRING, example='59814467'),
                        'nombres_completos': openapi.Schema(type=openapi.TYPE_STRING, example='Juan Carlos Pérez García'),
                        'num_historia_clinica': openapi.Schema(type=openapi.TYPE_STRING, example='HC-12345'),
                        'fecha_nacimiento': openapi.Schema(type=openapi.TYPE_STRING, example='15/05/90'),
                        'fecha_nacimiento_iso': openapi.Schema(type=openapi.TYPE_STRING, example='1990-05-15'),
                        'fecha_ingreso': openapi.Schema(type=openapi.TYPE_STRING, example='15/01/2024 08:30'),
                        'fecha_ingreso_iso': openapi.Schema(type=openapi.TYPE_STRING, example='2024-01-15T08:30:00'),
                        'edad': openapi.Schema(type=openapi.TYPE_INTEGER, example=34),
                        'edad_gestacional': openapi.Schema(type=openapi.TYPE_INTEGER, example=28),
                        'g_p_c_a_v_m': openapi.Schema(type=openapi.TYPE_STRING, example='G=2 - P=1 - C=0 - A=1'),
                        'g': openapi.Schema(type=openapi.TYPE_INTEGER, example=2),
                        'p': openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                        'c': openapi.Schema(type=openapi.TYPE_INTEGER, example=0),
                        'a': openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                        'n_controles_prenatales': openapi.Schema(type=openapi.TYPE_INTEGER, example=5),
                        'aseguradora': openapi.Schema(type=openapi.TYPE_STRING, example='EPS Sura'),
                        'grupo_sanguineo': openapi.Schema(type=openapi.TYPE_STRING, example='O+'),
                        'diagnostico': openapi.Schema(type=openapi.TYPE_STRING, example='O36.4 Embarazo en curso'),
                        'numero_ingreso': openapi.Schema(type=openapi.TYPE_INTEGER, example=12345),
                        'codigo_cama': openapi.Schema(type=openapi.TYPE_STRING, example='CAMA-101'),
                        'fuente': openapi.Schema(type=openapi.TYPE_STRING, example='DGEMPRES03'),
                    }
                )
            ),
            400: openapi.Response(
                description="Parámetro cedula requerido",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'error': openapi.Schema(type=openapi.TYPE_STRING, example='El parámetro cedula es requerido')
                    }
                )
            ),
            404: openapi.Response(
                description="Paciente no encontrado",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'error': openapi.Schema(type=openapi.TYPE_STRING, example='Paciente no encontrado en DGEMPRES03')
                    }
                )
            ),
            500: openapi.Response(
                description="Error del servidor",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'error': openapi.Schema(type=openapi.TYPE_STRING, example='Error al consultar DGEMPRES03: [mensaje]')
                    }
                )
            ),
        },
        operation_summary="Buscar paciente en DGEMPRES03",
        operation_description="Busca un paciente en la base de datos DGEMPRES03 usando su número de identificación (cédula). La búsqueda parte de HCMWINGIN usando HCNFOLIO como punto de partida. Retorna información completa del paciente incluyendo datos demográficos, clínicos y de ingreso."
    )
    @action(detail=False, methods=['get'], url_path='buscar-dgempres99')
    def buscar_dgempres99(self, request):
        """
        Endpoint para buscar pacientes en la base de datos DGEMPRES03.
        
        Uso: GET /api/pacientes/buscar-dgempres99/?cedula={cedula}
        
        Retorna información completa del paciente desde DGEMPRES03 incluyendo:
        - CC. IDENTIFICACIÓN
        - NOMBRE Y APELLIDO
        - N° HISTORIA CLÍNICA
        - DD/MM/AA (fecha de nacimiento)
        - FECHA INGRESO
        - EDAD
        - EDAD GESTACIONAL
        - G_P_C_A_V_M_ (estado)
        - N° CONTROLES PRENATALES
        - ASEGURADORA
        - GRUPO SANGUÍNEO
        - DIAGNÓSTICO
        
        IMPORTANTE: 
        - Usa conexión readonly a DGEMPRES03 mediante get_readonly_connection()
        - Todas las consultas a DGEMPRES03 deben usar .using('readonly') o connections['readonly']
        - Esto garantiza que la BD se mantenga como solo lectura
        """
        # Aceptar tanto 'cedula', 'num_identificacion' como 'folio' o 'hcnfolio'
        num_identificacion = request.query_params.get('cedula') or request.query_params.get('num_identificacion')
        num_folio = request.query_params.get('folio') or request.query_params.get('hcnfolio')
        
        # Normalizar: convertir a string y limpiar espacios
        if num_identificacion:
            num_identificacion = str(num_identificacion).strip()
        if num_folio:
            num_folio = str(num_folio).strip()
        
        if not num_identificacion and not num_folio:
            return Response(
                {'error': 'Se requiere el parámetro cedula o folio'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Obtener conexión a DGEMPRES03 usando helper que garantiza readonly
            connection = get_readonly_connection()
            
            with connection.cursor() as cursor:
                # Consulta SQL: Parte de HCMWINGIN usando HCNFOLIO como punto de partida
                # Base de datos: DGEMPRES03, Tabla: HCMWINGIN, Campo de relación: HCNFOLIO
                # Permite buscar por cédula (PAC.PACNUMDOC) o por número de folio (HCNFOLIO.OID)
                
                # Construir WHERE clause según el parámetro proporcionado
                if num_folio:
                    # Buscar por número de folio (HCNFOLIO.OID)
                    try:
                        folio_oid = int(num_folio)
                        where_clause = "WHERE HCNFOLIO.OID = %s"
                        params = (folio_oid,)
                        logger.info(f"🔍 Buscando por número de folio: {folio_oid}")
                    except ValueError:
                        return Response(
                            {'error': 'El número de folio debe ser un número válido'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                else:
                    # Buscar por cédula (PAC.PACNUMDOC)
                    doc = str(num_identificacion).strip()
                    where_clause = "WHERE PAC.PACNUMDOC = %s"
                    params = (doc,)
                    logger.info(f"🔍 Buscando por número de cédula: {doc}")
                
                cursor.execute(f"""
                    SELECT DISTINCT 
                        EST.HESFECING AS fecha_ingreso,
                        PLA.GDENOMBRE AS aseguradora,
                        PAC.GPANUMCAR AS num_historia_clinica,
                        PAC.PACNUMDOC AS num_identificacion,
                        FOL.OID AS num_folio,
                        LTRIM(RTRIM(
                            ISNULL(PAC.PACPRINOM, '') + ' ' + 
                            ISNULL(PAC.PACSEGNOM, '') + ' ' + 
                            ISNULL(PAC.PACPRIAPE, '') + ' ' + 
                            ISNULL(PAC.PACSEGAPE, '')
                        )) AS nombres_completos,
                        DX.DIACODIGO + ' ' + DX.DIANOMBRE AS diagnostico,
                        DATEDIFF(YEAR, PAC.GPAFECNAC, GETDATE()) AS edad,
                        PAC.GPAFECNAC AS fecha_nacimiento,
                        HCMWINGIN.HCCM03N191 AS grupo_sanguineo,
                        HCMWINGIN.HCCM00N256,
                        HCMWINGIN.HCCM00N80 AS g,
                        HCMWINGIN.HCCM00N81 AS p,
                        HCMWINGIN.HCCM00N82 AS c,
                        HCMWINGIN.HCCM00N83 AS a,
                        HCMWINGIN.HCCM00N255,
                        ING.AINCONSEC AS numero_ingreso,
                        CAM.HCACODIGO AS codigo_cama
                    FROM HCMWINGIN
                    INNER JOIN HCNFOLIO AS FOL ON FOL.OID = HCMWINGIN.HCNFOLIO
                    INNER JOIN ADNINGRESO AS ING ON ING.OID = FOL.ADNINGRESO
                    INNER JOIN GENPACIEN AS PAC ON PAC.OID = ING.GENPACIEN
                    LEFT JOIN HCNDIAPAC AS DIAP ON FOL.OID = DIAP.HCNFOLIO
                    LEFT JOIN GENDIAGNO AS DX ON DIAP.GENDIAGNO = DX.OID
                    LEFT JOIN GENDETCON AS PLA ON ING.GENDETCON = PLA.OID
                    LEFT JOIN HPNESTANC AS EST ON EST.ADNINGRES = ING.OID
                    LEFT JOIN HPNDEFCAM AS CAM ON EST.HPNDEFCAM = CAM.OID
                    {where_clause}
                    ORDER BY fecha_ingreso DESC, num_folio DESC
                """, params)

                
                row = cursor.fetchone()
                
                if row:
                    # Extraer datos de la fila según el orden de la consulta SQL
                    fecha_ingreso = row[0] if row[0] else None
                    aseguradora = row[1] if row[1] else None
                    num_historia = row[2] if row[2] else None
                    num_ident = row[3] if row[3] else None
                    num_folio = row[4] if row[4] else None  # Número de folio (HCNFOLIO.OID)
                    nombres = row[5] if row[5] else None
                    diagnostico = row[6] if row[6] else None
                    edad = row[7] if row[7] else None
                    fecha_nac = row[8] if row[8] else None
                    grupo_sangre = row[9] if row[9] else None
                    edad_gestacional = row[10] if row[10] else None
                    g = row[11] if row[11] else None
                    p = row[12] if row[12] else None
                    c = row[13] if row[13] else None
                    a = row[14] if row[14] else None
                    n_controles = row[15] if row[15] else None
                    num_ingreso = row[16] if row[16] else None
                    codigo_cama = row[17] if row[17] else None
                    
                    # Convertir fecha de nacimiento a objeto date para formateo
                    # La edad ya viene calculada de la consulta SQL
                    fecha_nac_obj = None
                    fecha_nac_formateada = None
                    fecha_nac_iso = None
                    
                    if fecha_nac:
                        try:
                            from datetime import datetime
                            if isinstance(fecha_nac, str):
                                # Intentar diferentes formatos
                                try:
                                    fecha_nac_obj = datetime.strptime(fecha_nac.split()[0], '%Y-%m-%d').date()
                                except:
                                    fecha_nac_obj = datetime.strptime(fecha_nac.split()[0], '%Y/%m/%d').date()
                            elif hasattr(fecha_nac, 'date'):
                                fecha_nac_obj = fecha_nac.date()
                            elif isinstance(fecha_nac, date):
                                fecha_nac_obj = fecha_nac
                            else:
                                fecha_nac_obj = fecha_nac
                            
                            # Formatear como DD/MM/AA
                            fecha_nac_formateada = fecha_nac_obj.strftime('%d/%m/%y')
                            fecha_nac_iso = fecha_nac_obj.isoformat()
                        except Exception as e:
                            logger.warning(f'Error procesando fecha de nacimiento: {e}')
                            fecha_nac_formateada = str(fecha_nac)
                    
                    # Formatear fecha de ingreso
                    fecha_ingreso_formateada = None
                    fecha_ingreso_iso = None
                    if fecha_ingreso:
                        try:
                            from datetime import datetime
                            if isinstance(fecha_ingreso, str):
                                try:
                                    fecha_ingreso_obj = datetime.strptime(fecha_ingreso, '%Y-%m-%d %H:%M:%S')
                                except:
                                    fecha_ingreso_obj = datetime.strptime(fecha_ingreso.split()[0], '%Y-%m-%d')
                            elif hasattr(fecha_ingreso, 'date'):
                                fecha_ingreso_obj = fecha_ingreso
                            else:
                                fecha_ingreso_obj = fecha_ingreso
                            
                            fecha_ingreso_formateada = fecha_ingreso_obj.strftime('%d/%m/%Y %H:%M') if hasattr(fecha_ingreso_obj, 'hour') else fecha_ingreso_obj.strftime('%d/%m/%Y')
                            if hasattr(fecha_ingreso_obj, 'isoformat'):
                                fecha_ingreso_iso = fecha_ingreso_obj.isoformat()
                            elif hasattr(fecha_ingreso_obj, 'date'):
                                fecha_ingreso_iso = fecha_ingreso_obj.date().isoformat()
                        except Exception as e:
                            logger.warning(f'Error formateando fecha de ingreso: {e}')
                            fecha_ingreso_formateada = str(fecha_ingreso)
                    
                    # Construir G_P_C_A_V_M como string
                    g_p_c_a_v_m = None
                    if g is not None or p is not None or c is not None or a is not None:
                        partes = []
                        if g is not None:
                            partes.append(f"G={g}")
                        if p is not None:
                            partes.append(f"P={p}")
                        if c is not None:
                            partes.append(f"C={c}")
                        if a is not None:
                            partes.append(f"A={a}")
                        g_p_c_a_v_m = " - ".join(partes) if partes else None
                    
                    # Construir respuesta con todos los campos requeridos
                    paciente_data = {
                        'num_identificacion': num_ident,  # CC. IDENTIFICACIÓN
                        'num_folio': num_folio,  # NÚMERO DE FOLIO (HCNFOLIO.OID)
                        'nombres_completos': nombres,  # NOMBRE Y APELLIDO
                        'num_historia_clinica': num_historia,  # N° HISTORIA CLÍNICA
                        'fecha_nacimiento': fecha_nac_formateada,  # DD/MM/AA
                        'fecha_nacimiento_iso': fecha_nac_iso,
                        'fecha_ingreso': fecha_ingreso_formateada,  # FECHA INGRESO
                        'fecha_ingreso_iso': fecha_ingreso_iso,
                        'edad': edad,  # EDAD
                        'edad_gestacional': edad_gestacional,  # EDAD GESTACIONAL
                        'g_p_c_a_v_m': g_p_c_a_v_m,  # G_P_C_A_V_M_ (formato: G=X - P=Y - C=Z - A=W)
                        'g': g,  # G (Gravidez)
                        'p': p,  # P (Paridad)
                        'c': c,  # C (Cesáreas)
                        'a': a,  # A (Abortos)
                        'n_controles_prenatales': n_controles,  # N° CONTROLES PRENATALES
                        'aseguradora': aseguradora,  # ASEGURADORA
                        'grupo_sanguineo': grupo_sangre,  # GRUPO SANGUÍNEO
                        'diagnostico': diagnostico,  # DIAGNÓSTICO
                        'numero_ingreso': num_ingreso,
                        'codigo_cama': codigo_cama,
                        'fuente': 'DGEMPRES03'
                    }
                    
                    # Agregar flag encontrado a la respuesta
                    paciente_data['encontrado'] = True
                    return Response(paciente_data, status=status.HTTP_200_OK)
                else:
                    return Response(
                        {
                            'encontrado': False,
                            'mensaje': 'Paciente no encontrado en DGEMPRES03'
                        },
                        status=status.HTTP_200_OK
                    )
                    
        except Exception as e:
            logger.error(f'Error al buscar paciente en DGEMPRES03: {e}', exc_info=True)
            
            # Proporcionar mensajes de error más descriptivos
            error_message = str(e)
            error_detail = None
            
            if '08001' in error_message or 'Named Pipes' in error_message:
                error_detail = 'Error de conexión: No se pudo establecer conexión con el servidor SQL Server. Verifica la conectividad de red y que el servidor esté accesible.'
            elif 'timeout' in error_message.lower():
                error_detail = 'Timeout de conexión: El servidor no respondió a tiempo. Verifica que el servidor esté ejecutándose y accesible.'
            elif 'login failed' in error_message.lower() or 'authentication' in error_message.lower():
                error_detail = 'Error de autenticación: Las credenciales son incorrectas o el usuario no tiene permisos.'
            elif 'driver' in error_message.lower() or 'odbc' in error_message.lower():
                error_detail = 'Error del driver ODBC: Verifica que el driver ODBC esté instalado correctamente.'
            elif 'network' in error_message.lower() or 'server is not found' in error_message.lower():
                error_detail = 'Error de red: El servidor no se encuentra o no es accesible. Verifica la IP (172.20.100.97) y la conectividad de red.'
            
            response_data = {
                'error': 'Error al consultar DGEMPRES03',
                'error_detail': error_detail or error_message,
                'error_technical': error_message if settings.DEBUG else None
            }
            
            return Response(
                response_data,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @swagger_auto_schema(
        method='get',
        manual_parameters=[
            openapi.Parameter(
                'num_identificacion',
                openapi.IN_QUERY,
                description="Número de identificación (cédula) del paciente. Alternativa: usar 'folio'",
                type=openapi.TYPE_STRING,
                required=False,
                example="59814467"
            ),
            openapi.Parameter(
                'folio',
                openapi.IN_QUERY,
                description="Número de folio (HCNFOLIO.OID) del paciente. Alternativa: usar 'num_identificacion'",
                type=openapi.TYPE_INTEGER,
                required=False,
                example=123456
            ),
        ],
        responses={
            200: openapi.Response(
                description="Datos obstétricos del paciente encontrado",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'num_identificacion': openapi.Schema(type=openapi.TYPE_STRING, example='59814467'),
                        'num_historia_clinica': openapi.Schema(type=openapi.TYPE_STRING, example='HC-12345'),
                        'nombre_paciente': openapi.Schema(type=openapi.TYPE_STRING, example='Juan Carlos Pérez García'),
                        'edad_gestacional': openapi.Schema(type=openapi.TYPE_INTEGER, example=28),
                        'g': openapi.Schema(type=openapi.TYPE_INTEGER, example=2),
                        'p': openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                        'c': openapi.Schema(type=openapi.TYPE_INTEGER, example=0),
                        'a': openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                        'grupo_sanguineo': openapi.Schema(type=openapi.TYPE_STRING, example='O+'),
                        'controles_prenatales': openapi.Schema(type=openapi.TYPE_INTEGER, example=5),
                    }
                )
            ),
            400: openapi.Response(
                description="Parámetro requerido faltante",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'error': openapi.Schema(type=openapi.TYPE_STRING, example='Debe enviar la cédula')
                    }
                )
            ),
            404: openapi.Response(
                description="Paciente sin datos obstétricos",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'mensaje': openapi.Schema(type=openapi.TYPE_STRING, example='Paciente sin datos obstétricos')
                    }
                )
            ),
        },
        operation_summary="Buscar paciente obstétrico en HCMWINGIN",
        operation_description="Busca un paciente en la tabla HCMWINGIN usando su número de identificación. La búsqueda parte de HCMWINGIN usando HCNFOLIO como punto de partida. Retorna información obstétrica del paciente incluyendo edad gestacional, G-P-C-A, grupo sanguíneo y controles prenatales."
    )
    @action(detail=False, methods=['get'], url_path='buscar-obstetrico')
    def buscar_obstetrico(self, request):
        """
        Endpoint para buscar pacientes obstétricos en HCMWINGIN (tabla principal).
        
        Uso: 
        - GET /api/pacientes/buscar-obstetrico/?num_identificacion={cedula}
        - GET /api/pacientes/buscar-obstetrico/?folio={numero_folio}
        
        Retorna información obstétrica del paciente desde HCMWINGIN:
        - CC. IDENTIFICACIÓN
        - N° HISTORIA CLÍNICA
        - NOMBRE Y APELLIDO
        - EDAD GESTACIONAL
        - G (Gravidez)
        - P (Paridad)
        - C (Cesáreas)
        - A (Abortos)
        - GRUPO SANGUÍNEO
        - CONTROLES PRENATALES
        
        IMPORTANTE: 
        - Usa conexión readonly a DGEMPRES03 mediante get_readonly_connection()
        - Todas las consultas a DGEMPRES03 deben usar .using('readonly') o connections['readonly']
        """
        num_identificacion = request.query_params.get('num_identificacion')
        num_folio = request.query_params.get('folio')

        if not num_identificacion and not num_folio:
            return Response(
                {'error': 'Debe enviar la cédula (num_identificacion) o el número de folio (folio)'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Limpiar el documento: remover todos los espacios
        doc = str(num_identificacion).strip().replace(' ', '') if num_identificacion else None

        try:
            # Obtener conexión a DGEMPRES03 usando helper que garantiza readonly
            connection = get_readonly_connection()
            
            with connection.cursor() as cursor:
                # Consulta SQL con HCMWINGIN como tabla principal
                # Usando los mismos campos que buscar-dgempres99 para consistencia
                # Construir WHERE clause según el parámetro proporcionado
                if num_folio:
                    # Buscar por número de folio (HCNFOLIO.OID)
                    try:
                        folio_oid = int(num_folio)
                        where_clause = "WHERE HCNFOLIO.OID = %s"
                        params = [folio_oid]
                        logger.info(f"🔍 [buscar-obstetrico] Buscando por número de folio: {folio_oid}")
                    except ValueError:
                        return Response(
                            {'error': 'El número de folio debe ser un número válido'},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                else:
                    # Buscar por cédula (PAC.PACNUMDOC)
                    doc = str(num_identificacion).strip()
                    where_clause = "WHERE GENPACIEN.PACNUMDOC = %s"
                    params = [doc]
                    logger.info(f"🔍 [buscar-obstetrico] Buscando por número de cédula: {doc}")
                
                query = f"""
                    SELECT
                        GENPACIEN.PACNUMDOC AS num_identificacion,
                        HCNFOLIO.OID AS num_folio,
                        GENPACIEN.GPANUMCAR AS num_historia_clinica,
                        GENPACIEN.PACPRINOM + ' ' +
                        GENPACIEN.PACSEGNOM + ' ' +
                        GENPACIEN.PACPRIAPE + ' ' +
                        GENPACIEN.PACSEGAPE AS nombre_paciente,
                        HCMWINGIN.HCCM00N256,
                        HCMWINGIN.HCCM00N80 AS g,
                        HCMWINGIN.HCCM00N81 AS p,
                        HCMWINGIN.HCCM00N82 AS c,
                        HCMWINGIN.HCCM00N83 AS a,
                        HCMWINGIN.HCCM03N191 AS grupo_sanguineo,
                        HCMWINGIN.HCCM00N255
                    FROM HCMWINGIN
                    INNER JOIN HCNFOLIO
                        ON HCNFOLIO.OID = HCMWINGIN.HCNFOLIO
                    INNER JOIN ADNINGRESO
                        ON ADNINGRESO.OID = HCNFOLIO.ADNINGRESO
                    INNER JOIN GENPACIEN
                        ON GENPACIEN.OID = ADNINGRESO.GENPACIEN
                    {where_clause}
                """
                
                cursor.execute(query, params)
                row = cursor.fetchone()
                
                if not row:
                    return Response(
                        {'mensaje': 'Paciente sin datos obstétricos'},
                        status=status.HTTP_404_NOT_FOUND
                    )
                
                # Construir respuesta
                data = {
                    'num_identificacion': row[0] if row[0] else None,
                    'num_folio': row[1] if row[1] else None,  # Número de folio (HCNFOLIO.OID)
                    'num_historia_clinica': row[2] if row[2] else None,
                    'nombre_paciente': row[3] if row[3] else None,
                    'edad_gestacional': row[4] if row[4] else None,
                    'g': row[5] if row[5] else None,
                    'p': row[6] if row[6] else None,
                    'c': row[7] if row[7] else None,
                    'a': row[8] if row[8] else None,
                    'grupo_sanguineo': row[9] if row[9] else None,
                    'controles_prenatales': row[10] if row[10] else None,
                }
                
                return Response(data, status=status.HTTP_200_OK)
                
        except Exception as e:
            logger.error(f'Error al buscar paciente obstétrico en HCMWINGIN: {e}', exc_info=True)
            
            error_message = str(e)
            error_detail = None
            
            if '08001' in error_message or 'Named Pipes' in error_message:
                error_detail = 'Error de conexión: No se pudo establecer conexión con el servidor SQL Server.'
            elif 'timeout' in error_message.lower():
                error_detail = 'Timeout de conexión: El servidor no respondió a tiempo.'
            elif 'login failed' in error_message.lower() or 'authentication' in error_message.lower():
                error_detail = 'Error de autenticación: Las credenciales son incorrectas.'
            
            response_data = {
                'error': 'Error al consultar HCMWINGIN',
                'error_detail': error_detail or error_message,
                'error_technical': error_message if settings.DEBUG else None
            }
            
            return Response(
                response_data,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @swagger_auto_schema(
        method='get',
        manual_parameters=[
            openapi.Parameter(
                'diagnostico',
                openapi.IN_QUERY,
                description="Nombre del diagnóstico para filtrar (búsqueda parcial, case-insensitive). Ejemplo: 'embarazo', 'trabajo de parto'",
                type=openapi.TYPE_STRING,
                required=False,
                example="embarazo"
            ),
            openapi.Parameter(
                'folio',
                openapi.IN_QUERY,
                description="Número de folio (HCNFOLIO.OID) para filtrar. Puede usarse junto con 'diagnostico'",
                type=openapi.TYPE_INTEGER,
                required=False,
                example=123456
            ),
            openapi.Parameter(
                'limit',
                openapi.IN_QUERY,
                description="Número máximo de resultados a retornar (default: 50, máximo: 200)",
                type=openapi.TYPE_INTEGER,
                required=False,
                example=50
            ),
        ],
        responses={
            200: openapi.Response(
                description="Lista de pacientes en embarazo filtrados por diagnóstico",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'total': openapi.Schema(type=openapi.TYPE_INTEGER, example=25),
                        'pacientes': openapi.Schema(
                            type=openapi.TYPE_ARRAY,
                            items=openapi.Schema(
                                type=openapi.TYPE_OBJECT,
                                properties={
                                    'num_identificacion': openapi.Schema(type=openapi.TYPE_STRING, example='5206311'),
                                    'nombres_completos': openapi.Schema(type=openapi.TYPE_STRING, example='María Pérez García'),
                                    'num_historia_clinica': openapi.Schema(type=openapi.TYPE_STRING, example='HC-12345'),
                                    'fecha_nacimiento': openapi.Schema(type=openapi.TYPE_STRING, example='1990-05-15'),
                                    'edad': openapi.Schema(type=openapi.TYPE_INTEGER, example=34),
                                    'diagnostico': openapi.Schema(type=openapi.TYPE_STRING, example='O36.4 Embarazo en curso'),
                                    'edad_gestacional': openapi.Schema(type=openapi.TYPE_INTEGER, example=28),
                                    'g': openapi.Schema(type=openapi.TYPE_INTEGER, example=2),
                                    'p': openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                                    'c': openapi.Schema(type=openapi.TYPE_INTEGER, example=0),
                                    'a': openapi.Schema(type=openapi.TYPE_INTEGER, example=1),
                                    'grupo_sanguineo': openapi.Schema(type=openapi.TYPE_STRING, example='O+'),
                                    'n_controles_prenatales': openapi.Schema(type=openapi.TYPE_INTEGER, example=5),
                                    'aseguradora': openapi.Schema(type=openapi.TYPE_STRING, example='EPS Sura'),
                                    'fecha_ingreso': openapi.Schema(type=openapi.TYPE_STRING, example='2024-01-15T08:30:00'),
                                }
                            )
                        )
                    }
                )
            ),
            500: openapi.Response(
                description="Error del servidor",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'error': openapi.Schema(type=openapi.TYPE_STRING)
                    }
                )
            ),
        },
        operation_summary="Listar pacientes en embarazo filtrados por diagnóstico o folio",
        operation_description="Lista pacientes que tienen registro en HCMWINGIN (embarazadas) y permite filtrar por nombre de diagnóstico o número de folio. La búsqueda parte de HCMWINGIN usando HCNFOLIO como punto de partida. La búsqueda del diagnóstico es parcial y case-insensitive."
    )
    @action(detail=False, methods=['get'], url_path='listar-embarazadas')
    def listar_embarazadas(self, request):
        """
        Lista pacientes en embarazo actualmente internas, usando el motor único de
        "pacientes activas" compartido con MEOWS y Frecuencia Fetal/Sala de Partos
        (frecuenciafetal.sala_partos_db.listar_pacientes_sala_partos), en vez de una
        consulta propia — evita mantener dos veces la misma lógica contra la BD readonly.

        Uso:
        - GET /api/pacientes/listar-embarazadas/?diagnostico={nombre_diagnostico}
        - GET /api/pacientes/listar-embarazadas/?folio={numero_folio}
        - GET /api/pacientes/listar-embarazadas/?diagnostico={nombre}&folio={folio}

        Parámetros:
        - diagnostico (opcional): Nombre del diagnóstico para filtrar (búsqueda parcial).
        - folio (opcional): Número de folio (HCNFOLIO.OID) para filtrar.
        - limit (opcional): Número máximo de resultados (default: 50, máximo: 200).

        Retorna lista de pacientes actualmente internas con datos obstétricos, diagnóstico y folio.
        """
        from frecuenciafetal.sala_partos_db import listar_pacientes_sala_partos

        try:
            diagnostico_filtro = request.query_params.get('diagnostico', '').strip()
            num_folio = request.query_params.get('folio') or request.query_params.get('hcnfolio')
            if num_folio:
                num_folio = str(num_folio).strip()
            limit = request.query_params.get('limit', 50)

            try:
                limit = int(limit)
                if limit > 200:
                    limit = 200
                if limit < 1:
                    limit = 50
            except (ValueError, TypeError):
                limit = 50

            folio_oid = None
            if num_folio:
                try:
                    folio_oid = int(num_folio)
                except ValueError:
                    return Response(
                        {'error': 'El número de folio debe ser un número válido'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            logger.info(f"🔍 Buscando pacientes en embarazo (diagnóstico: '{diagnostico_filtro}', folio: '{num_folio}', limit: {limit})")

            # El motor único no acepta límite 200 de forma directa para filtros posteriores
            # en Python, así que se pide un poco más y se recorta al final.
            activos = listar_pacientes_sala_partos(limit=200)

            pacientes = []
            for p in activos:
                if folio_oid is not None and p.get('folio') != folio_oid:
                    continue
                diagnostico = p.get('diagnostico')
                if diagnostico_filtro:
                    if not diagnostico or diagnostico_filtro.upper() not in diagnostico.upper():
                        continue
                elif not diagnostico:
                    # Sin filtro de diagnóstico: mantener el requisito histórico de que
                    # exista un diagnóstico registrado para aparecer en esta lista.
                    continue

                pacientes.append({
                    'num_identificacion': p.get('identificacion'),
                    'num_folio': p.get('folio'),
                    'nombres_completos': p.get('nombre_paciente'),
                    'num_historia_clinica': p.get('historia_clinica'),
                    'fecha_nacimiento': str(p['fecha_nacimiento']) if p.get('fecha_nacimiento') else None,
                    'edad': p.get('edad_anos'),
                    'diagnostico': diagnostico,
                    'edad_gestacional': p.get('edad_gestacional'),
                    'g': p.get('gestas'),
                    'p': p.get('partos'),
                    'c': p.get('cesareas'),
                    'a': p.get('abortos'),
                    'grupo_sanguineo': p.get('grupo_sanguineo'),
                    'n_controles_prenatales': p.get('controles_prenatales'),
                    'aseguradora': p.get('aseguradora'),
                    'fecha_ingreso': str(p['fecha_ingreso']) if p.get('fecha_ingreso') else None,
                })

            pacientes = pacientes[:limit]

            logger.info(f"✅ Encontrados {len(pacientes)} pacientes en embarazo")

            return Response({
                'total': len(pacientes),
                'pacientes': pacientes,
                'filtro_diagnostico': diagnostico_filtro if diagnostico_filtro else None,
                'filtro_folio': num_folio if num_folio else None
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f'Error al listar pacientes en embarazo: {e}', exc_info=True)

            return Response(
                {
                    'error': 'Error al consultar pacientes en embarazo',
                    'error_detail': str(e) if settings.DEBUG else 'Error interno del servidor'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _obtener_obstetricos_dgempres99(self, num_identificacion, only_cache=False):
        """
        Obtiene HCCM00N256 (edad gestacional), HCCM00N255 (controles prenatales),
        HCCM00N80–83 (G, P, C, A), GENDETCON.GDENOMBRE (aseguradora) y diagnóstico de DGEMPRES03.
        Retorna (edad_gestacional, n_controles_prenatales, aseguradora, diagnostico, g, p, c, a).
        """
        def _to_int_or_none(val):
            if val is None:
                return None
            try:
                return int(float(val))
            except (TypeError, ValueError):
                return None

        doc = str(num_identificacion or "").strip().replace(" ", "")
        doc_alt = doc.lstrip("0") or doc  # ayuda cuando PACNUMDOC está guardado sin ceros a la izquierda
        if not doc:
            return (None, None, None, None, None, None, None, None)
        
        # 1. Intentar obtener de caché (TTL 10 min)
        cache_key = f"obstetricos_{doc}"
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.info(f"⚡ [Cache Hit] Datos obstétricos recuperados para {doc}")
            return cached_data
        
        # Modo rápido: no consultar DGEMPRES03, usar solo caché si existe.
        if only_cache:
            return (None, None, None, None, None, None, None, None)

        try:
            t0 = time.perf_counter()
            connection = get_readonly_connection()
            with connection.cursor() as cursor:
                # 2. Búsqueda exacta primero (índice PACNUMDOC), probando doc y doc sin ceros a la izquierda.
                logger.info(f"🔍 [DGEMPRES03] Búsqueda exacta para obstetricos: doc={doc} alt={doc_alt}")
                cursor.execute("""
                    SELECT TOP 1
                        HCMWINGIN.HCCM00N256,
                        HCMWINGIN.HCCM00N255,
                        PLA.GDENOMBRE AS aseguradora,
                        DX.DIACODIGO + ' ' + DX.DIANOMBRE AS diagnostico,
                        HCMWINGIN.HCCM00N80 AS g,
                        HCMWINGIN.HCCM00N81 AS p,
                        HCMWINGIN.HCCM00N82 AS c,
                        HCMWINGIN.HCCM00N83 AS a
                    FROM GENPACIEN
                    LEFT JOIN ADNINGRESO ON ADNINGRESO.GENPACIEN = GENPACIEN.OID
                    LEFT JOIN HCNFOLIO ON HCNFOLIO.ADNINGRESO = ADNINGRESO.OID
                    LEFT JOIN HCMWINGIN ON HCMWINGIN.HCNFOLIO = HCNFOLIO.OID
                    LEFT JOIN GENDETCON AS PLA ON ADNINGRESO.GENDETCON = PLA.OID
                    LEFT JOIN HCNDIAPAC AS DIAP ON HCNFOLIO.OID = DIAP.HCNFOLIO
                    LEFT JOIN GENDIAGNO AS DX ON DIAP.GENDIAGNO = DX.OID
                    WHERE GENPACIEN.PACNUMDOC IN (%s, %s)
                    ORDER BY HCNFOLIO.OID DESC
                """, [doc, doc_alt])
                row = cursor.fetchone()
                
                # 3. Solo si falla, probar búsqueda normalizada (más lenta pero flexible), también en una sola ronda.
                if not row:
                    logger.info(f"🔍 [DGEMPRES03] Búsqueda exacta falló, intentando normalizada para doc={doc} alt={doc_alt}")
                    cursor.execute("""
                        SELECT TOP 1
                            HCMWINGIN.HCCM00N256,
                            HCMWINGIN.HCCM00N255,
                            PLA.GDENOMBRE AS aseguradora,
                            DX.DIACODIGO + ' ' + DX.DIANOMBRE AS diagnostico,
                            HCMWINGIN.HCCM00N80 AS g,
                            HCMWINGIN.HCCM00N81 AS p,
                            HCMWINGIN.HCCM00N82 AS c,
                            HCMWINGIN.HCCM00N83 AS a
                        FROM GENPACIEN
                        LEFT JOIN ADNINGRESO ON ADNINGRESO.GENPACIEN = GENPACIEN.OID
                        LEFT JOIN HCNFOLIO ON HCNFOLIO.ADNINGRESO = ADNINGRESO.OID
                        LEFT JOIN HCMWINGIN ON HCMWINGIN.HCNFOLIO = HCNFOLIO.OID
                        LEFT JOIN GENDETCON AS PLA ON ADNINGRESO.GENDETCON = PLA.OID
                        LEFT JOIN HCNDIAPAC AS DIAP ON HCNFOLIO.OID = DIAP.HCNFOLIO
                        LEFT JOIN GENDIAGNO AS DX ON DIAP.GENDIAGNO = DX.OID
                        WHERE REPLACE(LTRIM(RTRIM(GENPACIEN.PACNUMDOC)), ' ', '') IN (%s, %s)
                        ORDER BY HCNFOLIO.OID DESC
                    """, [doc, doc_alt])
                    row = cursor.fetchone()
                if row:
                    eg = _to_int_or_none(row[0])
                    nc = _to_int_or_none(row[1])
                    aseguradora = (row[2] or "").strip() or None
                    diagnostico = (row[3] or "").strip() or None
                    g = _to_int_or_none(row[4])
                    p = _to_int_or_none(row[5])
                    c = _to_int_or_none(row[6])
                    a = _to_int_or_none(row[7])
                    
                    data = (eg, nc, aseguradora, diagnostico, g, p, c, a)
                    # Aumentar caché a 30 minutos (1800 seg) para mayor estabilidad en tablets
                    cache.set(cache_key, data, 1800)
                    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                    logger.info(f"   [DGEMPRES03] HCCM00N256={eg} HCCM00N255={nc} G={g} P={p} C={c} A={a} aseguradora={aseguradora!r} diagnostico={diagnostico!r} para doc={doc} (elapsed={elapsed_ms}ms)")
                    return data
                elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
                logger.info(f"   [DGEMPRES03] Sin datos obstétricos para doc={doc} (elapsed={elapsed_ms}ms)")
        except Exception as e:
            logger.warning(f"Error obteniendo obstétricos DGEMPRES03 para {doc}: {e}")
        return (None, None, None, None, None, None, None, None)
    
    def _sincronizar_paciente_desde_dgempres99(self, num_identificacion, num_folio=None):
        """
        Sincroniza un paciente desde DGEMPRES03 a la BD local.
        
        LÓGICA: Buscar directamente en HCMWINGIN (tabla principal)
        - Base de datos: DGEMPRES03
        - Tabla: HCMWINGIN
        - Campo de relación: HCNFOLIO (HCMWINGIN.HCNFOLIO = HCNFOLIO.OID)
        
        La consulta parte de HCMWINGIN y obtiene datos del paciente a través de los JOINs:
        - HCMWINGIN -> HCNFOLIO -> ADNINGRESO -> GENPACIEN
        
        Permite buscar por:
        - Cédula: usando GENPACIEN.PACNUMDOC
        - Número de folio: usando HCNFOLIO.OID
        
        Campos HCMWINGIN utilizados:
        - HCCM00N256: Edad gestacional
        - HCCM00N80: G (Gravidez)
        - HCCM00N81: P (Paridad)
        - HCCM00N82: C (Cesáreas)
        - HCCM00N83: A (Abortos)
        - HCCM03N191: Grupo sanguíneo
        - HCCM00N255: Controles prenatales
        
        IMPORTANTE: 
        - Usa conexión readonly a DGEMPRES03 mediante get_readonly_connection()
        - Todas las consultas a DGEMPRES03 deben usar .using('readonly') o connections['readonly']
        - Esto garantiza que la BD se mantenga como solo lectura
        """

        try:
            # Usar helper que garantiza conexión readonly a DGEMPRES03
            connection = get_readonly_connection()
            logger.info(f"🔌 Verificando conexión a DGEMPRES03...")
            logger.info(f"✅ Conexión establecida a DGEMPRES03 (readonly)")

            with connection.cursor() as cursor:

                # ==========================================================
                # 1️⃣ BUSCAR PACIENTE DIRECTAMENTE EN HCMWINGIN
                # ==========================================================
                
                # Construir WHERE clause según el parámetro proporcionado
                if num_folio:
                    # Buscar por número de folio (HCNFOLIO.OID)
                    try:
                        folio_oid = int(num_folio)
                        where_clause = "WHERE HCNFOLIO.OID = %s"
                        params = [folio_oid]
                        logger.info(f"🔎 Buscando paciente en HCMWINGIN por número de folio: {folio_oid}")
                    except ValueError:
                        logger.error(f"❌ Número de folio inválido: '{num_folio}'")
                        return (None, None)
                else:
                    # Buscar por cédula (PAC.PACNUMDOC)
                    doc = str(num_identificacion).strip()
                    doc_limpio = doc.replace(' ', '')
                    # Priorizar búsqueda exacta por índice
                    where_clause = "WHERE GENPACIEN.PACNUMDOC = %s"
                    params = [doc]
                    logger.info(f"🔎 Buscando paciente en HCMWINGIN por cédula (exacta): '{doc}'")

                # Consulta SQL basada en la estructura proporcionada
                # Parte de HCMWINGIN y obtiene datos del paciente a través de JOINs
                # GENDETCON (PLA): aseguradora; GENDIAGNO (DX) vía HCNDIAPAC: diagnóstico
                sql_paciente = f"""
                    SELECT TOP 1
                        GENPACIEN.OID,
                        GENPACIEN.PACNUMDOC,
                        GENPACIEN.GPANUMCAR,
                        LTRIM(RTRIM(
                            ISNULL(GENPACIEN.PACPRINOM,'') + ' ' +
                            ISNULL(GENPACIEN.PACSEGNOM,'') + ' ' +
                            ISNULL(GENPACIEN.PACPRIAPE,'') + ' ' +
                            ISNULL(GENPACIEN.PACSEGAPE,'')
                        )) AS nombres_completos,
                        GENPACIEN.GPAFECNAC,
                        HCMWINGIN.HCCM00N256,
                        HCMWINGIN.HCCM00N80 AS g,
                        HCMWINGIN.HCCM00N81 AS p,
                        HCMWINGIN.HCCM00N82 AS c,
                        HCMWINGIN.HCCM00N83 AS a,
                        HCMWINGIN.HCCM03N191 AS grupo_sanguineo,
                        HCMWINGIN.HCCM00N255,
                        PLA.GDENOMBRE AS aseguradora,
                        DX.DIACODIGO + ' ' + DX.DIANOMBRE AS diagnostico
                    FROM GENPACIEN
                    LEFT JOIN ADNINGRESO ON ADNINGRESO.GENPACIEN = GENPACIEN.OID
                    LEFT JOIN HCNFOLIO ON HCNFOLIO.ADNINGRESO = ADNINGRESO.OID
                    LEFT JOIN HCMWINGIN ON HCMWINGIN.HCNFOLIO = HCNFOLIO.OID
                    LEFT JOIN GENDETCON AS PLA ON ADNINGRESO.GENDETCON = PLA.OID
                    LEFT JOIN HCNDIAPAC AS DIAP ON HCNFOLIO.OID = DIAP.HCNFOLIO
                    LEFT JOIN GENDIAGNO AS DX ON DIAP.GENDIAGNO = DX.OID
                    {where_clause}
                    ORDER BY HCNFOLIO.OID DESC
                """
                cursor.execute(sql_paciente, params)
                pac_row = cursor.fetchone()

                # Solo si falla y no es folio, intentar búsqueda normalizada (más lenta pero flexible)
                if not pac_row and not num_folio:
                    logger.info(f"🔎 Búsqueda exacta falló, intentando búsqueda normalizada para '{doc_limpio}'")
                    cursor.execute("""
                        SELECT TOP 1
                            GENPACIEN.OID,
                            GENPACIEN.PACNUMDOC,
                            GENPACIEN.GPANUMCAR,
                            LTRIM(RTRIM(
                                ISNULL(GENPACIEN.PACPRINOM,'') + ' ' +
                                ISNULL(GENPACIEN.PACSEGNOM,'') + ' ' +
                                ISNULL(GENPACIEN.PACPRIAPE,'') + ' ' +
                                ISNULL(GENPACIEN.PACSEGAPE,'')
                            )) AS nombres_completos,
                            GENPACIEN.GPAFECNAC,
                            HCMWINGIN.HCCM00N256,
                            HCMWINGIN.HCCM00N80 AS g,
                            HCMWINGIN.HCCM00N81 AS p,
                            HCMWINGIN.HCCM00N82 AS c,
                            HCMWINGIN.HCCM00N83 AS a,
                            HCMWINGIN.HCCM03N191 AS grupo_sanguineo,
                            HCMWINGIN.HCCM00N255,
                            PLA.GDENOMBRE AS aseguradora,
                            DX.DIACODIGO + ' ' + DX.DIANOMBRE AS diagnostico
                        FROM GENPACIEN
                        LEFT JOIN ADNINGRESO ON ADNINGRESO.GENPACIEN = GENPACIEN.OID
                        LEFT JOIN HCNFOLIO ON HCNFOLIO.ADNINGRESO = ADNINGRESO.OID
                        LEFT JOIN HCMWINGIN ON HCMWINGIN.HCNFOLIO = HCNFOLIO.OID
                        LEFT JOIN GENDETCON AS PLA ON ADNINGRESO.GENDETCON = PLA.OID
                        LEFT JOIN HCNDIAPAC AS DIAP ON HCNFOLIO.OID = DIAP.HCNFOLIO
                        LEFT JOIN GENDIAGNO AS DX ON DIAP.GENDIAGNO = DX.OID
                        WHERE REPLACE(LTRIM(RTRIM(GENPACIEN.PACNUMDOC)), ' ', '') = %s
                        ORDER BY HCNFOLIO.OID DESC
                    """, [doc_limpio])
                    pac_row = cursor.fetchone()

                if not pac_row:
                    logger.info(f"ℹ️ El paciente {doc_limpio or num_folio} no existe en HCMWINGIN (Paciente Nuevo)")
                    return (None, None)
                else:
                    logger.info(f"✅ Paciente encontrado en HCMWINGIN con documento: '{pac_row[1] if pac_row else 'N/A'}'")

                pac_oid = pac_row[0]
                num_doc = pac_row[1]
                num_historia = pac_row[2]
                nombres = pac_row[3]
                fecha_nac = pac_row[4]
                edad_gestacional = pac_row[5]
                g = pac_row[6]
                p = pac_row[7]
                c = pac_row[8]
                a = pac_row[9]
                grupo_sangre = pac_row[10]
                n_controles = pac_row[11]
                aseguradora_dg = (pac_row[12] or "").strip() or None
                diagnostico_dg = (pac_row[13] or "").strip() or None

                logger.info(f"✅ Paciente encontrado en HCMWINGIN: {num_doc}")

                # Convertir fecha de nacimiento
                fecha_nac_obj = None
                if fecha_nac:
                    try:
                        from datetime import datetime
                        if isinstance(fecha_nac, str):
                            try:
                                fecha_nac_obj = datetime.strptime(fecha_nac.split()[0], '%Y-%m-%d').date()
                            except:
                                fecha_nac_obj = datetime.strptime(fecha_nac.split()[0], '%Y/%m/%d').date()
                        elif hasattr(fecha_nac, 'date'):
                            fecha_nac_obj = fecha_nac.date()
                        elif isinstance(fecha_nac, date):
                            fecha_nac_obj = fecha_nac
                    except Exception as e:
                        logger.warning(f'Error procesando fecha de nacimiento: {e}')

                # Convertir fecha de nacimiento
                fecha_nac_obj = None
                if fecha_nac:
                    try:
                        from datetime import datetime
                        if isinstance(fecha_nac, str):
                            try:
                                fecha_nac_obj = datetime.strptime(fecha_nac.split()[0], '%Y-%m-%d').date()
                            except:
                                fecha_nac_obj = datetime.strptime(fecha_nac.split()[0], '%Y/%m/%d').date()
                        elif hasattr(fecha_nac, 'date'):
                            fecha_nac_obj = fecha_nac.date()
                        elif isinstance(fecha_nac, date):
                            fecha_nac_obj = fecha_nac
                    except Exception as e:
                        logger.warning(f'Error procesando fecha de nacimiento: {e}')

                # Normalizar grupo sanguíneo
                tipo_sangre = None
                if grupo_sangre:
                    grupo_sangre_limpio = str(grupo_sangre).strip().upper()
                    # Mapear a los valores del modelo
                    if grupo_sangre_limpio in ['O+', 'O POS', 'O POSITIVO']:
                        tipo_sangre = 'O+'
                    elif grupo_sangre_limpio in ['O-', 'O NEG', 'O NEGATIVO']:
                        tipo_sangre = 'O-'
                    elif grupo_sangre_limpio in ['A+', 'A POS', 'A POSITIVO']:
                        tipo_sangre = 'A+'
                    elif grupo_sangre_limpio in ['A-', 'A NEG', 'A NEGATIVO']:
                        tipo_sangre = 'A-'
                    elif grupo_sangre_limpio in ['B+', 'B POS', 'B POSITIVO']:
                        tipo_sangre = 'B+'
                    elif grupo_sangre_limpio in ['B-', 'B NEG', 'B NEGATIVO']:
                        tipo_sangre = 'B-'
                    elif grupo_sangre_limpio in ['AB+', 'AB POS', 'AB POSITIVO']:
                        tipo_sangre = 'AB+'
                    elif grupo_sangre_limpio in ['AB-', 'AB NEG', 'AB NEGATIVO']:
                        tipo_sangre = 'AB-'

                # ==========================================================
                # 2️⃣ CREAR / ACTUALIZAR PACIENTE LOCAL
                # ==========================================================
                paciente, _ = Paciente.objects.update_or_create(
                    num_identificacion=num_doc.strip(),
                    defaults={
                        "num_historia_clinica": num_historia or f"HC-{num_doc}",
                        "nombres": nombres or "Sin nombre",
                        "fecha_nacimiento": fecha_nac_obj,
                        "tipo_sangre": tipo_sangre,
                    }
                )
                logger.info(f"✅ Paciente {'creado' if _ else 'actualizado'} en BD local con tipo_sangre: {tipo_sangre}")

                # ==========================================================
                # 3️⃣ BUSCAR ÚLTIMO INGRESO (OPCIONAL)
                # ==========================================================
                logger.info(f"🏥 Buscando último ingreso para paciente {num_doc}")

                try:
                    cursor.execute("""
                        SELECT TOP 1
                            EST.HESFECING,
                            PLA.GDENOMBRE,
                            DX.DIACODIGO + ' ' + DX.DIANOMBRE,
                            ING.AINCONSEC,
                            CAM.HCACODIGO
                        FROM ADNINGRESO ING
                        INNER JOIN HPNESTANC EST ON EST.ADNINGRES = ING.OID
                        LEFT JOIN HPNDEFCAM CAM ON EST.HPNDEFCAM = CAM.OID
                        LEFT JOIN GENDETCON PLA ON ING.GENDETCON = PLA.OID
                        LEFT JOIN HCNFOLIO FOL ON FOL.ADNINGRESO = ING.OID
                        LEFT JOIN HCNDIAPAC DIAP ON DIAP.HCNFOLIO = FOL.OID
                        LEFT JOIN GENDIAGNO DX ON DIAP.GENDIAGNO = DX.OID
                        WHERE ING.GENPACIEN = %s
                        ORDER BY EST.HESFECING DESC
                    """, (pac_oid,))
                except TypeError as e:
                    # Si hay error de formateo en debug, intentar ejecutar directamente
                    if 'not all arguments converted' in str(e):
                        # Fallback: cursor crudo pyodbc usa ? (solo si el wrapper falla)
                        cursor.cursor.execute("""
                            SELECT TOP 1
                                EST.HESFECING,
                                PLA.GDENOMBRE,
                                DX.DIACODIGO + ' ' + DX.DIANOMBRE,
                                ING.AINCONSEC,
                                CAM.HCACODIGO
                            FROM ADNINGRESO ING
                            INNER JOIN HPNESTANC EST ON EST.ADNINGRES = ING.OID
                            LEFT JOIN HPNDEFCAM CAM ON EST.HPNDEFCAM = CAM.OID
                            LEFT JOIN GENDETCON PLA ON ING.GENDETCON = PLA.OID
                            LEFT JOIN HCNFOLIO FOL ON FOL.ADNINGRESO = ING.OID
                            LEFT JOIN HCNDIAPAC DIAP ON DIAP.HCNFOLIO = FOL.OID
                            LEFT JOIN GENDIAGNO DX ON DIAP.GENDIAGNO = DX.OID
                            WHERE ING.GENPACIEN = ?
                            ORDER BY EST.HESFECING DESC
                        """, (pac_oid,))
                    else:
                        raise

                ing_row = cursor.fetchone()

                if ing_row:
                    logger.info(f"ℹ️ Paciente {num_doc} tiene ingreso")
                    # Nota: Si el modelo Paciente tiene estos campos, se pueden guardar aquí
                    # Por ahora solo logueamos la información
                else:
                    logger.info(f"ℹ️ Paciente {num_doc} SIN ingresos (válido)")

                # Los datos obstétricos ya fueron obtenidos en la consulta principal
                # No es necesario hacer otra consulta a HCMWINGIN
                logger.info(f"✅ Datos obstétricos obtenidos desde HCMWINGIN:")
                logger.info(f"   - Edad gestacional: {edad_gestacional}")
                logger.info(f"   - G: {g}, P: {p}, C: {c}, A: {a}")
                logger.info(f"   - Grupo sanguíneo: {grupo_sangre}")
                logger.info(f"   - Controles prenatales: {n_controles}")
                logger.info(f"   - Aseguradora (GENDETCON.GDENOMBRE): {aseguradora_dg}")
                logger.info(f"   - Diagnóstico (GENDIAGNO vía HCNDIAPAC): {diagnostico_dg}")

                def _to_int_or_none(val):
                    if val is None:
                        return None
                    try:
                        return int(float(val))
                    except (TypeError, ValueError):
                        return None

                extras = {
                    "edad_gestacional": _to_int_or_none(edad_gestacional),
                    "n_controles_prenatales": _to_int_or_none(n_controles),
                    "aseguradora": aseguradora_dg,
                    "diagnostico": diagnostico_dg,
                    "g": _to_int_or_none(g),
                    "p": _to_int_or_none(p),
                    "c": _to_int_or_none(c),
                    "a": _to_int_or_none(a),
                }
                return (paciente, extras)

        except Exception as e:
            logger.error(
                f"🔥 Error sincronizando paciente {num_identificacion}: {e}",
                exc_info=True
            )
            logger.error(f"   - Tipo de error: {type(e).__name__}")
            logger.error(f"   - Mensaje completo: {str(e)}")
            
            # Verificar si es un error de conexión
            error_str = str(e).lower()
            if 'connection' in error_str or 'timeout' in error_str or 'network' in error_str:
                logger.error("   ⚠️ Posible problema de conexión a DGEMPRES03")
            elif 'login' in error_str or 'authentication' in error_str:
                logger.error("   ⚠️ Posible problema de autenticación con DGEMPRES03")
            elif 'invalid' in error_str or 'syntax' in error_str:
                logger.error("   ⚠️ Posible error en la consulta SQL")
            
            return (None, None)
    
    @action(detail=False, methods=['get'], url_path='buscar-completo')
    def buscar_completo(self, request):
        """
        Endpoint consolidado que retorna toda la información del paciente,
        su formulario más reciente y sus mediciones en una sola respuesta.
        
        Si el paciente no existe en la BD local, lo busca en DGEMPRES03 y lo sincroniza.
        
        Uso: 
        - GET /api/pacientes/buscar-completo/?num_identificacion={cedula}
        - GET /api/pacientes/buscar-completo/?folio={numero_folio}
        
        Retorna:
        {
            "paciente": {...datos del paciente...},
            "formulario": {...formulario más reciente o null...},
            "mediciones": [...mediciones del formulario o []...]
        }
        """
        # Aceptar tanto 'num_identificacion' (cédula) como 'folio' o 'hcnfolio'
        num_identificacion = request.query_params.get('num_identificacion', None)
        num_folio = request.query_params.get('folio') or request.query_params.get('hcnfolio')
        # Si se requiere forzar consulta externa para refrescar obstétricos:
        # /api/pacientes/buscar-completo/?num_identificacion=...&forzar_externo=1
        forzar_externo = str(request.query_params.get('forzar_externo', '0')).strip().lower() in ('1', 'true', 'si', 'sí', 'yes')
        
        # Normalizar: convertir a string y limpiar espacios
        if num_identificacion:
            num_identificacion = str(num_identificacion).strip()
        if num_folio:
            num_folio = str(num_folio).strip()
        
        if not num_identificacion and not num_folio:
            return Response(
                {'error': 'Se requiere el parámetro num_identificacion o folio'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Intentar obtener respuesta completa de caché para mayor velocidad (TTL 10 seg).
        # forzar_externo pide explícitamente un dato fresco, así que no debe servirse
        # nunca desde este caché rápido.
        key_resp = f"resp_completa_{num_identificacion or num_folio}"
        resp_cached = None if forzar_externo else cache.get(key_resp)
        if resp_cached:
            logger.info(f"⚡ [Rapid Cache Hit] Respuesta completa servida para {num_identificacion or num_folio}")
            response = Response(resp_cached, status=status.HTTP_200_OK)
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
            return response

        try:
            extras = None
            # 1. Si se proporciona folio, buscar directamente en DGEMPRES03
            # Si se proporciona cédula, buscar primero en BD local
            if num_folio:
                # Buscar directamente en DGEMPRES03 por folio
                logger.info(f'🔍 [buscar-completo] Buscando paciente por folio {num_folio} en HCMWINGIN (DGEMPRES03)...')
                paciente, extras = self._sincronizar_paciente_desde_dgempres99(None, num_folio)
                if not paciente:
                    logger.error(f'❌ [buscar-completo] Paciente con folio {num_folio} NO encontrado en HCMWINGIN')
                    return Response(
                        {
                            'encontrado': False,
                            'mensaje': f'Paciente con folio {num_folio} no encontrado en HCMWINGIN. Verifique que exista registro obstétrico para ese folio.'
                        },
                        status=status.HTTP_200_OK
                    )
            else:
                # Buscar por cédula: primero en BD local, luego en DGEMPRES03
                extras = None
                logger.info(f'🔍 [buscar-completo] Buscando paciente {num_identificacion} en BD local...')
                try:
                    paciente = Paciente.objects.get(num_identificacion=num_identificacion)
                    logger.info(f'✅ [buscar-completo] Paciente encontrado en BD local: {paciente.id}')
                    # Estrategia local-first:
                    # - Por defecto, usar solo caché de obstétricos (respuesta rápida).
                    # - Consultar DGEMPRES03 en vivo solo si se fuerza por query param.
                    eg, nc, aseguradora_dg, diagnostico_dg, g, p, c, a = self._obtener_obstetricos_dgempres99(
                        paciente.num_identificacion,
                        only_cache=not forzar_externo
                    )
                    if forzar_externo:
                        logger.info(f'🔄 [buscar-completo] forzar_externo=1 para {num_identificacion}: consulta en vivo a DGEMPRES03')
                    else:
                        logger.info(f'⚡ [buscar-completo] local-first para {num_identificacion}: obstétricos solo desde caché')
                    if eg is not None or nc is not None or aseguradora_dg or diagnostico_dg or g is not None or p is not None or c is not None or a is not None:
                        extras = {
                            "edad_gestacional": eg,
                            "n_controles_prenatales": nc,
                            "aseguradora": aseguradora_dg,
                            "diagnostico": diagnostico_dg,
                            "g": g,
                            "p": p,
                            "c": c,
                            "a": a,
                        }
                except Paciente.DoesNotExist:
                    # 2. Si no existe en la BD local, buscar en DGEMPRES03 y sincronizar
                    logger.info(f'⚠️ [buscar-completo] Paciente {num_identificacion} no encontrado en BD local, buscando en HCMWINGIN (DGEMPRES03)...')
                    paciente, extras = self._sincronizar_paciente_desde_dgempres99(num_identificacion)
                    if not paciente:
                        logger.info(f'ℹ️ [buscar-completo] Paciente {num_identificacion} no registrado en HCMWINGIN (Flujo Paciente Nuevo)')
                        return Response(
                            {
                                'encontrado': False,
                                'mensaje': f'Paciente con documento {num_identificacion} no encontrado en el sistema externo. Puede proceder con el registro manual si es un paciente nuevo.'
                            },
                            status=status.HTTP_200_OK
                        )
                    logger.info(f'✅ [buscar-completo] Paciente sincronizado desde HCMWINGIN: {paciente.id}')
            
            # 3. Serializar datos del paciente
            paciente_serializer = PacienteSerializer(paciente)
            paciente_data = dict(paciente_serializer.data)

            # Fuente autoritativa: meows.Paciente — es la misma tabla que arma el HUB
            # (/atencion/api/datos-paciente-unificado/) al registrar/actualizar al paciente desde
            # Sala de Partos. Todos los módulos deben reflejar ESE dato, por eso se prioriza aquí
            # por encima de la consulta propia (más antigua, basada en caché) a DGEMPRES03 de más
            # abajo, que solo debe rellenar los huecos que el HUB no tenga.
            meows_p = None
            try:
                from meows.models import Paciente as MeowsPaciente
                meows_p = MeowsPaciente.objects.filter(
                    numero_documento=str(paciente.num_identificacion).strip()
                ).first()
            except Exception as e:
                logger.warning(f"No fue posible leer datos desde meows.Paciente (fuente del HUB): {e}")

            if meows_p:
                # Mapeo campo-del-HUB -> clave de respuesta centralizado en un solo lugar:
                # agregar un campo nuevo a meows.Paciente solo requiere una línea aquí, en
                # vez de arriesgarse a que quede sin copiar (bug detectado: "gestas" existía
                # en el modelo pero nunca se sobre-escribía en este bloque).
                campos_texto_desde_hub = {
                    "aseguradora": meows_p.aseguradora,
                    "tipo_sangre": meows_p.tipo_sangre,
                    "diagnostico": meows_p.diagnostico,
                    "cama": meows_p.cama,
                    "responsable": meows_p.responsable,
                    "nombre_acompanante": meows_p.nombre_acompanante,
                }
                for key, val in campos_texto_desde_hub.items():
                    if val:
                        paciente_data[key] = val

                campos_numericos_desde_hub = {
                    "edad_gestacional": meows_p.edad_gestacional,
                    "n_controles_prenatales": meows_p.n_controles_prenatales,
                    "gestas": meows_p.gestas,
                }
                for key, val in campos_numericos_desde_hub.items():
                    if val is not None:
                        paciente_data[key] = val
                # "g" es la clave histórica que el frontend de Trabajo de Parto todavía lee
                # para el campo G del bloque G_P_C_A_V_M; se mantiene sincronizada con
                # "gestas". partos/cesareas/abortos (p/c/a) no tienen columna equivalente en
                # meows.Paciente hoy, así que solo pueden venir del caché legacy (extras) más
                # abajo — no hay forma de reconciliarlos contra el HUB hasta que ese modelo
                # tenga esos campos.
                if meows_p.gestas is not None:
                    paciente_data["g"] = meows_p.gestas

            if extras:
                # La consulta propia a DGEMPRES03 (con caché) solo completa lo que el HUB
                # (meows.Paciente) todavía no tenía; nunca sobrescribe un dato ya confirmado ahí.
                for key, val in extras.items():
                    if val not in (None, "") and paciente_data.get(key) in (None, ""):
                        paciente_data[key] = val

            # Resolver aseguradora (nombre) -> aseguradora_id si existe en BD local
            nombre_aseg = paciente_data.get("aseguradora")
            if nombre_aseg:
                ase = resolver_aseguradora_por_nombre(nombre_aseg)
                if ase:
                    paciente_data["aseguradora_id"] = ase.id
            
            logger.info(f'✅ Paciente encontrado y serializado:')
            logger.info(f'   - ID: {paciente_data.get("id")}')
            logger.info(f'   - Documento: {paciente_data.get("num_identificacion")}')
            logger.info(f'   - Nombres: {paciente_data.get("nombres")}')
            logger.info(f'   - Edad gestacional (HCCM00N256): {paciente_data.get("edad_gestacional")}')
            logger.info(f'   - N° controles prenatales (HCCM00N255): {paciente_data.get("n_controles_prenatales")}')
            logger.info(f'   - Aseguradora (GENDETCON.GDENOMBRE): {paciente_data.get("aseguradora")}')
            logger.info(f'   - Diagnóstico (GENDIAGNO vía HCNDIAPAC): {paciente_data.get("diagnostico")}')
            
            # 4. Buscar el formulario más reciente del paciente
            formulario = Formulario.objects.filter(
                paciente=paciente
            ).select_related('paciente', 'aseguradora').first()
            
            # 5. Inicializar variables para formulario y mediciones
            formulario_data = None
            mediciones_data = []
            
            if formulario:
                logger.info(f'📋 Formulario encontrado: ID {formulario.id}')
                # 6. Serializar datos del formulario
                formulario_serializer = FormularioSerializer(formulario)
                formulario_data = formulario_serializer.data
                
                # 7. Obtener mediciones del formulario con optimización
                # Incluir item del parámetro para que esté disponible en el serializador
                mediciones = Medicion.objects.filter(
                    formulario=formulario
                ).select_related(
                    'formulario', 'parametro', 'parametro__item'
                ).prefetch_related(
                    'valores__campo'
                ).order_by('tomada_en')
                
                # 8. Serializar mediciones
                mediciones_serializer = MedicionSerializer(mediciones, many=True)
                mediciones_data = mediciones_serializer.data
                logger.info(f'📊 Mediciones encontradas: {len(mediciones_data)}')
            else:
                logger.info(f'ℹ️ No hay formulario para este paciente')
            
            # 10. Buscar biometría (consolidar última huella y última firma)
            huella_data = None
            try:
                from .models import Huella
                # Buscar por ID (OID) o por Cédula (num_identificacion)
                base_query = Q(paciente_id=str(paciente.id)) | Q(paciente_id=paciente.num_identificacion)
                
                # Obtener la captura más reciente que tenga huella (con archivo real en disco)
                reg_huella = _mas_reciente_con_archivo(Huella.objects.filter(base_query).exclude(imagen=''), 'imagen')
                # Obtener la captura más reciente que tenga firma (con archivo real en disco)
                reg_firma = _mas_reciente_con_archivo(Huella.objects.filter(base_query).exclude(imagen_firma=''), 'imagen_firma')
                
                if reg_huella or reg_firma:
                    huella_data = {
                        "id": reg_huella.id if reg_huella else (reg_firma.id if reg_firma else None),
                        "fecha": reg_huella.fecha.isoformat() if reg_huella else (reg_firma.fecha.isoformat() if reg_firma else None),
                        "imagen_huella": reg_huella.imagen.url if reg_huella and reg_huella.imagen else None,
                        "imagen_firma": reg_firma.imagen_firma.url if reg_firma and reg_firma.imagen_firma else None,
                        "usuario": reg_huella.usuario if reg_huella else (reg_firma.usuario if reg_firma else "Sistema")
                    }
                    if reg_huella: logger.info(f'🔐 Huella encontrada para paciente {paciente.num_identificacion}')
                    if reg_firma: logger.info(f'✍️ Firma encontrada para paciente {paciente.num_identificacion}')
            except Exception as e:
                logger.warning(f"Error al recuperar biometría en buscar_completo: {e}")

            # 9. Construir respuesta consolidada
            response_data = {
                'encontrado': True,
                'paciente': paciente_data,
                'formulario': formulario_data,
                'mediciones': mediciones_data,
                'huella': huella_data
            }
            
            # Guardar en caché rápida para evitar re-consultas en ráfaga (TTL 10 seg)
            key_resp = f"resp_completa_{num_identificacion or num_folio}"
            cache.set(key_resp, response_data, 10)

            response = Response(response_data, status=status.HTTP_200_OK)
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
            return response
            
        except Exception as e:
            logger.error(f'Error en buscar_completo: {e}', exc_info=True)
            return Response(
                {'error': f'Error al buscar información completa: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )



class FormularioViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar Formularios
    Permite CRUD completo sobre el modelo Formulario
    """
    queryset = Formulario.objects.select_related('paciente', 'aseguradora').all()
    serializer_class = FormularioSerializer
    lookup_field = 'id'
    
    def get_queryset(self):
        """
        Permite filtrar formularios por num_identificacion del paciente
        Ejemplo: /api/formularios/?paciente__num_identificacion=123456
        """
        queryset = Formulario.objects.select_related('paciente', 'aseguradora').all()
        
        # Filtrar por num_identificacion del paciente
        num_identificacion = self.request.query_params.get('paciente__num_identificacion', None)
        if num_identificacion:
            try:
                # Limpiar el valor del parámetro
                num_identificacion = num_identificacion.strip()
                queryset = queryset.filter(paciente__num_identificacion=num_identificacion)
            except Exception as e:
                logger.error(f"Error al filtrar formularios por num_identificacion '{num_identificacion}': {e}", exc_info=True)
                # Retornar queryset vacío en lugar de lanzar excepción
                return Formulario.objects.none()
        
        return queryset
    
    def list(self, request, *args, **kwargs):
        """
        Sobrescribe el método list para manejar errores mejor
        """
        try:
            return super().list(request, *args, **kwargs)
        except Exception as e:
            logger.error(f"Error en list de FormularioViewSet: {e}", exc_info=True)
            return Response(
                {'error': str(e), 'detail': 'Error al obtener formularios'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def get_serializer_class(self):
        """Retorna el serializador apropiado según la acción"""
        if self.action in ['create', 'update', 'partial_update']:
            return FormularioCreateSerializer
        return FormularioSerializer

    def perform_create(self, serializer):
        atencion_id = (
            self.request.data.get("atencion")
            or self.request.query_params.get("atencion")
            or ""
        )
        atencion_id = str(atencion_id).strip()
        if atencion_id.isdigit():
            serializer.save(atencion_id=int(atencion_id))
            return
        serializer.save()

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        atencion_id = (
            request.data.get("atencion")
            or request.query_params.get("atencion")
            or ""
        )
        atencion_id = str(atencion_id).strip()
        if atencion_id.isdigit() and isinstance(response.data, dict):
            response.data["redirect_url"] = f"/atencion/{atencion_id}/"
        return response
    
    @action(detail=True, methods=['get'])
    def mediciones(self, request, id=None):
        """Obtiene todas las mediciones de un formulario"""
        formulario = self.get_object()
        mediciones = Medicion.objects.filter(formulario=formulario).select_related(
            'formulario', 'parametro'
        ).prefetch_related('valores__campo')
        serializer = MedicionSerializer(mediciones, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def parametros(self, request, id=None):
        """Obtiene todos los parámetros asociados a un formulario"""
        formulario = self.get_object()
        parametros_formulario = FormularioItemParametro.objects.filter(
            formulario=formulario
        ).select_related('formulario', 'item', 'parametro')
        serializer = FormularioItemParametroSerializer(parametros_formulario, many=True)
        return Response(serializer.data)


class ItemViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar Items
    Permite CRUD completo sobre el modelo Item
    """
    queryset = Item.objects.all()
    serializer_class = ItemSerializer
    lookup_field = 'id'
    
    @action(detail=True, methods=['get'])
    def parametros(self, request, id=None):
        """Obtiene todos los parámetros de un item"""
        item = self.get_object()
        parametros = Parametro.objects.filter(item=item).select_related('item')
        serializer = ParametroSerializer(parametros, many=True)
        return Response(serializer.data)


class ParametroViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar Parámetros
    Permite CRUD completo sobre el modelo Parametro
    """
    queryset = Parametro.objects.select_related('item').all()
    serializer_class = ParametroSerializer
    lookup_field = 'id'
    
    @action(detail=True, methods=['get'])
    def campos(self, request, id=None):
        """Obtiene todos los campos de un parámetro"""
        parametro = self.get_object()
        campos = CampoParametro.objects.filter(parametro=parametro).select_related('parametro')
        serializer = CampoParametroSerializer(campos, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def mediciones(self, request, id=None):
        """Obtiene todas las mediciones de un parámetro"""
        parametro = self.get_object()
        mediciones = Medicion.objects.filter(parametro=parametro).select_related(
            'formulario', 'parametro'
        ).prefetch_related('valores__campo')
        serializer = MedicionSerializer(mediciones, many=True)
        return Response(serializer.data)


class CampoParametroViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar Campos de Parámetros
    Permite CRUD completo sobre el modelo CampoParametro
    """
    queryset = CampoParametro.objects.select_related('parametro').all()
    serializer_class = CampoParametroSerializer
    lookup_field = 'id'


class FormularioItemParametroViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar relaciones Formulario-Item-Parámetro
    Permite CRUD completo sobre el modelo FormularioItemParametro
    """
    queryset = FormularioItemParametro.objects.select_related(
        'formulario', 'item', 'parametro'
    ).all()
    serializer_class = FormularioItemParametroSerializer
    lookup_field = 'id'


class MedicionViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar Mediciones
    Permite CRUD completo sobre el modelo Medicion
    """
    queryset = Medicion.objects.select_related(
        'formulario', 'parametro'
    ).prefetch_related('valores__campo').all()
    serializer_class = MedicionSerializer
    lookup_field = 'id'
    
    def get_serializer_class(self):
        """Retorna el serializador apropiado según la acción"""
        if self.action in ['create', 'update', 'partial_update']:
            return MedicionCreateSerializer
        return MedicionSerializer
    
    @action(detail=True, methods=['get', 'post'])
    def valores(self, request, id=None):
        """Obtiene o crea valores de una medición"""
        medicion = self.get_object()
        
        if request.method == 'GET':
            valores = MedicionValor.objects.filter(medicion=medicion).select_related('medicion', 'campo')
            serializer = MedicionValorSerializer(valores, many=True, context={'medicion': medicion})

            return Response(serializer.data)
        
        elif request.method == 'POST':
            serializer = MedicionValorSerializer(data=request.data)
            if serializer.is_valid():
                serializer.save(medicion=medicion)
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MedicionValorViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar Valores de Mediciones
    Permite CRUD completo sobre el modelo MedicionValor
    """
    queryset = MedicionValor.objects.select_related('medicion', 'campo').all()
    serializer_class = MedicionValorSerializer
    lookup_field = 'id'


def obtener_texto_completo_select(parametro_id, campo_id, valor_guardado):
    """
    Obtiene el texto completo de una opción de select basándose en el valor guardado.
    Replica la lógica del formulario informativo para mostrar los valores completos.
    """
    if not valor_guardado:
        return valor_guardado
    
    # Mapeo de valores a textos completos según los selects del formulario
    mapeos = {
        # Frecuencia Cardíaca (parametro 2, campo 3)
        (2, 3): {
            "<40": "< 40 Bradicardia severa",
            "40-59": "40 – 59 Bradicardia",
            "60-100": "60 – 100 Normal",
            "101-120": "101 – 120 Taquicardia leve",
            "121-150": "121 – 150 Taquicardia",
            ">150": "> 150 Taquicardia severa"
        },
        # Frecuencia Respiratoria (parametro 3, campo 4)
        (3, 4): {
            "<8": "< 8 Bradipnea",
            "8-11": "8 – 11 FR baja",
            "12-20": "12 – 20 Normal",
            "21-30": "21 – 30 Taquipnea",
            ">30": "> 30 Distrés respiratorio"
        },
        # Temperatura (parametro 4, campo 5)
        (4, 5): {
            "<32.0": "< 32.0 Hipotermia profunda",
            "32.0-34.9": "32.0 – 34.9 Hipotermia moderada",
            "35.0-35.9": "35.0 – 35.9 Hipotermia leve",
            "36.0-37.4": "36.0 – 37.4 Normotermia",
            "37.5-37.9": "37.5 – 37.9 Febrícula",
            "38.0-38.9": "38.0 – 38.9 Fiebre",
            "39.0-40.9": "39.0 – 40.9 Hipertermia",
            ">=41.0": "≥ 41.0 Emergencia vital"
        },
        # Dinámica Uterina (parametro 5, campo 16)
        (5, 16): {
            "0": "0 Sin dinámica",
            "1-2": "1–2 Fase latente",
            "3-5": "3–5 Trabajo activo",
            ">5": "> 5 Taquisistolia"
        },
        # Intensidad (parametro 6, campo 17)
        (6, 17): {
            "<30": "< 30 Ineficaz",
            "30-60": "30 – 60 Normal",
            "61-90": "61 – 90 Fuerte",
            ">90": "> 90 Riesgo fetal"
        },
        # Contracciones (parametro 7, campo 9)
        (7, 9): {
            "0": "0 Ausente",
            "1": "1 Leve (+)",
            "2": "2 Moderada (++)",
            "3": "3 Fuerte (+++)",
            "4": "4 Hipertónica"
        },
        # Frecuencia Cardíaca Fetal (parametro 8, campo 6)
        (8, 6): {
            "<100": "< 100 Bradicardia severa",
            "100-109": "100 – 109 Bradicardia",
            "110-160": "110 – 160 Normal",
            "161-180": "161 – 180 Taquicardia",
            ">180": "> 180 Taquicardia severa"
        },
        # Movimientos Fetales (parametro 9, campo 10)
        (9, 10): {
            "0": "0 - Ausentes",
            "1": "1 - Disminuidos",
            "2": "2 - Presentes",
            "3": "3 - Exagerados"
        },
        # Presentación (parametro 10, campo 11) - Ya tienen el texto completo
        # Líquido Amniótico (parametro 13, campo 12) - Ya tienen el texto completo
        # Membranas Íntegras (parametro 11, campo 14) - Ya tienen el texto completo
        # Membranas Rotas (parametro 12, campo 15) - Ya tienen el texto completo
        # Dilatación (parametro 15, campo 7)
        (15, 7): {
            "0–3 Latente": "0–3 Latente",
            "4–6 Activa": "4–6 Activa",
            "7–9 Transición": "7–9 Transición",
            "10 Completa": "10 Completa"
        },
        # Categoría (parametro 18, campo 13) - Ya tienen el texto completo
        # Dosis (parametro 19, campo 20)
        (19, 20): {
            "0 No uso": "0 No uso",
            "1 – 5 Dosis baja": "1 – 5 Dosis baja",
            "6 – 20 Terapéutica": "6 – 20 Terapéutica",
            "> 20 Riesgo": "> 20 Riesgo"
        }
    }
    
    # Buscar el mapeo para este parámetro y campo
    mapeo = mapeos.get((parametro_id, campo_id))
    if mapeo:
        # Convertir valor_guardado a string si es necesario
        valor_str = str(valor_guardado).strip()
        
        # Buscar coincidencia exacta primero
        texto_completo = mapeo.get(valor_str)
        if texto_completo:
            return texto_completo
        
        # Si no hay coincidencia exacta, buscar por coincidencia parcial
        for valor_key, texto in mapeo.items():
            if valor_str in valor_key or valor_key in valor_str:
                return texto
        
        # Si el valor es numérico, intentar buscar en rangos
        try:
            valor_num = float(valor_str)
            for valor_key, texto in mapeo.items():
                # Buscar rangos como "101-120" o ">150" o "<40"
                if '-' in valor_key:
                    partes = valor_key.split('-')
                    if len(partes) == 2:
                        try:
                            min_val = float(partes[0].replace('<', '').replace('>', '').strip())
                            max_val = float(partes[1].replace('<', '').replace('>', '').strip())
                            if min_val <= valor_num <= max_val:
                                return texto
                        except (ValueError, AttributeError):
                            pass
                elif valor_key.startswith('>'):
                    try:
                        min_val = float(valor_key.replace('>', '').replace('=', '').strip())
                        if valor_num > min_val or (valor_key.startswith('>=') and valor_num >= min_val):
                            return texto
                    except (ValueError, AttributeError):
                        pass
                elif valor_key.startswith('<'):
                    try:
                        max_val = float(valor_key.replace('<', '').replace('=', '').strip())
                        if valor_num < max_val or (valor_key.startswith('<=') and valor_num <= max_val):
                            return texto
                    except (ValueError, AttributeError):
                        pass
        except (ValueError, TypeError):
            pass
    
    # Si no se encuentra mapeo, retornar el valor original
    return valor_guardado


@login_required_if_enabled
def vista_impresion_formulario(request, formulario_id):
    """
    Vista optimizada para impresión en formato A4 (HTML a PDF).
    """
    formulario = get_object_or_404(Formulario.objects.select_related('paciente', 'aseguradora'), id=formulario_id)
    
    # Obtener items, parámetros y campos
    items = Item.objects.prefetch_related('parametros__campos').all().order_by('id')
    
    # Obtener todas las mediciones del formulario
    mediciones_qs = Medicion.objects.filter(formulario=formulario).prefetch_related('valores__campo')
    
    # Organizar horas únicas (columnas) para el encabezado
    # Usar las fechas tal como vienen de la base de datos, sin conversión de zona horaria
    # para que coincidan con las que se muestran en el formulario web
    from django.utils import timezone
    horas_unicas = sorted(list(set(m.tomada_en for m in mediciones_qs)))[:10]
    # Asegurar que las fechas se mantengan en la zona horaria local (Colombia)
    # sin conversión adicional
    
    # Mapear mediciones para fácil acceso en el template: {param_id: {hora_iso: {campo_id: valor}}}
    # Usar el mismo formato de fecha que se usa en el formulario web
    grid_data = {}
    for m in mediciones_qs:
        p_id = m.parametro_id
        # Usar isoformat() para mantener consistencia con el formato de la API
        # Django ya maneja la conversión de zona horaria según USE_TZ y TIME_ZONE
        h_str = m.tomada_en.isoformat()
        
        if p_id not in grid_data:
            grid_data[p_id] = {}
        if h_str not in grid_data[p_id]:
            grid_data[p_id][h_str] = {}
            
        for v in m.valores.all():
            valor = ""
            # Priorizar valor_text sobre valor_number (para compatibilidad con datos antiguos)
            if v.valor_text:
                valor = v.valor_text
                # Si es un campo de tiempo (parametro-id="17", campo-id="19" o parametro-id="14", campo-id="18"), convertir a formato 12 horas
                if (p_id == 17 and v.campo_id == 19) or (p_id == 14 and v.campo_id == 18):
                    # El valor viene en formato "HH:MM" (24 horas), convertir a formato 12 horas
                    hora_match = re.match(r'^(\d{1,2}):(\d{2})$', valor)
                    if hora_match:
                        horas = int(hora_match.group(1))
                        minutos = hora_match.group(2)
                        ampm = 'p. m.' if horas >= 12 else 'a. m.'
                        horas = horas % 12
                        horas = horas if horas else 12  # Si es 0, mostrar 12
                        valor = f"{horas:02d}:{minutos} {ampm}"
                else:
                    # Para otros campos, buscar el texto completo del select
                    valor = obtener_texto_completo_select(p_id, v.campo_id, valor)
            elif v.valor_number is not None:
                # Compatibilidad con datos antiguos que puedan estar en valor_number
                valor = float(v.valor_number)
                if valor.is_integer(): valor = int(valor)
                valor = str(valor)
                # Intentar obtener el texto completo también para valores numéricos antiguos
                valor = obtener_texto_completo_select(p_id, v.campo_id, valor)
            elif v.valor_boolean is not None:
                valor = "SÍ" if v.valor_boolean else "NO"
                # Para campos booleanos, buscar el texto completo
                if p_id == 11 and v.campo_id == 14:
                    # Membranas íntegras
                    valor = "Sí - Bolsa amniótica íntegra" if v.valor_boolean else "No - Ya hubo ruptura"
                elif p_id == 12 and v.campo_id == 15:
                    # Membranas rotas
                    valor = "Sí – Espontánea o artificial" if v.valor_boolean else "No - Membranas aún íntegras"
                
            grid_data[p_id][h_str][v.campo_id] = valor

    # Recuperar biometría (huella y firma) de forma independiente
    from .models import Huella
    # Refinar búsqueda de biometría (mismo logic que pdf_utils)
    # 4. Biometría (HUELLA Y FIRMA)
    p = formulario.paciente
    ident = str(p.num_identificacion).strip()
    query_biometria = Q(paciente_id=ident) | Q(paciente_id=str(p.id))
    
    # Intentar también sin ceros a la izquierda si es numérico
    if ident.isdigit():
        query_biometria |= Q(paciente_id=str(int(ident)))
    
    reg_huella = _mas_reciente_con_archivo(Huella.objects.filter(query_biometria).exclude(imagen__exact='').exclude(imagen__isnull=True), 'imagen')
    reg_firma = _mas_reciente_con_archivo(Huella.objects.filter(query_biometria).exclude(imagen_firma__exact='').exclude(imagen_firma__isnull=True), 'imagen_firma')
    
    # Preparar URLs de logos y biometría (Absolutas)
    base_url = request.build_absolute_uri('/')[:-1]
    # Forzar localhost:8000 si estamos en el backend para que las imágenes se carguen bien desde el frontend
    if "8000" not in base_url and "8001" not in base_url:
        # Si es una IP externa o similar, se mantiene, pero si es localhost:8001 (frontend), hay que apuntar al 8000
        pass
    
    logo_hospital = f"{base_url}{settings.STATIC_URL}img/logo_hospital.png"
    logo_acreditacion = f"{base_url}{settings.STATIC_URL}img/logo_acreditacion.png"
    
    huella_img = f"{base_url}{reg_huella.imagen.url}" if reg_huella and reg_huella.imagen else ""
    firma_img = f"{base_url}{reg_firma.imagen_firma.url}" if reg_firma and reg_firma.imagen_firma else ""
    
    # Variables de compatibilidad para el template
    huella_display = "block" if huella_img else "none"
    firma_display = "block" if firma_img else "none"
    no_huella_display = "none" if huella_img else "block"
    no_firma_display = "none" if firma_img else "block"

    context = {
        'f': formulario,
        'p': formulario.paciente,
        'items': items,
        'horas': horas_unicas,
        'grid_data': grid_data,
        
        # Variables requeridas por impresion_formulario.html
        'LOGO_HOSPITAL': logo_hospital,
        'LOGO_ACREDITACION': logo_acreditacion,
        'CODIGO': formulario.codigo or "FRSPA-022",
        'VERSION': formulario.version or "01",
        'NUM_HOJA': formulario.num_hoja or 1,
        'FECHA_ELABORA': formulario.fecha_elabora.strftime('%d/%m/%Y') if formulario.fecha_elabora else "2 DE MARZO DEL 2018",
        
        'PACIENTE_NOMBRES': formulario.paciente.nombres,
        'PACIENTE_NUM_IDENTIFICACION': formulario.paciente.num_identificacion,
        'PACIENTE_NUM_HISTORIA_CLINICA': formulario.paciente.num_historia_clinica,
        'PACIENTE_TIPO_SANGRE': formulario.paciente.get_tipo_sangre_display() if formulario.paciente.tipo_sangre else "O+",
        
        'FORMULARIO_ASEGURADORA': formulario.aseguradora.nombre if formulario.aseguradora else "N/A",
        'FORMULARIO_EDAD_SNAPSHOT': formulario.edad_snapshot,
        'FORMULARIO_EDAD_GESTION': formulario.edad_gestion,
        'FORMULARIO_ESTADO': formulario.get_estado_display() if formulario.estado else "G0 - P0",
        'FORMULARIO_N_CONTROLES_PRENATALES': formulario.n_controles_prenatales,
        'FORMULARIO_DIAGNOSTICO': formulario.diagnostico or "Trabajo de parto espontáneo",
        'FORMULARIO_RESPONSABLE': formulario.responsable,
        
        'HUELLA_IMG': huella_img,
        'FIRMA_IMG': firma_img,
        'HUELLA_DISPLAY': huella_display,
        'FIRMA_DISPLAY': firma_display,
        'NO_HUELLA_DISPLAY': no_huella_display,
        'NO_FIRMA_DISPLAY': no_firma_display,
    }
    return render(request, 'clinico/impresion_formulario.html', context)


def generar_pdf_formulario(request, formulario_id):
    """
    Vista para generar y descargar el PDF de un formulario clínico.
    Delega la lógica a pdf_utils para mantener consistencia profesional.
    """
    from .models import Formulario
    from .pdf_utils import generar_pdf_formulario_clinico
    
    formulario = get_object_or_404(Formulario.objects.select_related("paciente", "aseguradora"), id=formulario_id)
    
    return generar_pdf_formulario_clinico(formulario)


@login_required_if_enabled
def preview_pdf_paciente(request, paciente_id):
    """
    Vista de prueba para ver los datos que se incluirán en el PDF
    """
    from django.shortcuts import get_object_or_404
    
    paciente = get_object_or_404(Paciente, id=paciente_id)
    
    formularios = Formulario.objects.filter(paciente=paciente).select_related(
        'aseguradora'
    ).prefetch_related(
        'parametros_formulario__item',
        'parametros_formulario__parametro__campos'
    )
    
    # Preparar datos para mostrar
    datos_paciente = {
        'id': paciente.id,
        'nombres': paciente.nombres,
        'num_identificacion': paciente.num_identificacion,
        'num_historia_clinica': paciente.num_historia_clinica,
        'fecha_nacimiento': paciente.fecha_nacimiento.strftime('%d/%m/%Y') if paciente.fecha_nacimiento else None,
        'tipo_sangre': paciente.get_tipo_sangre_display() if paciente.tipo_sangre else None,
    }
    
    datos_formularios = []
    for formulario in formularios:
        # Obtener items únicos
        items_dict = {}
        for fip in formulario.parametros_formulario.select_related('item', 'parametro').prefetch_related('parametro__campos').all():
            item = fip.item
            if item.id not in items_dict:
                items_dict[item.id] = {'item': item, 'parametros': []}
            items_dict[item.id]['parametros'].append(fip.parametro)
        
        # Preparar datos de items y parámetros
        items_data = []
        for item_id, item_data in items_dict.items():
            item = item_data['item']
            parametros_data = []
            
            for parametro in item_data['parametros']:
                campos_data = []
                campos = parametro.campos.all()
                
                for campo in campos:
                    valor = MedicionValor.objects.filter(
                        medicion__formulario=formulario,
                        campo=campo
                    ).select_related('medicion', 'campo').first()
                    
                    # Obtener el valor según el tipo
                    if valor:
                        if valor.valor_number is not None:
                            texto_valor = str(valor.valor_number)
                        elif valor.valor_text:
                            texto_valor = valor.valor_text
                        elif valor.valor_boolean is not None:
                            texto_valor = 'Sí' if valor.valor_boolean else 'No'
                        elif valor.valor_json:
                            texto_valor = str(valor.valor_json)
                        else:
                            texto_valor = "—"
                    else:
                        texto_valor = "—"
                    
                    campos_data.append({
                        'nombre': campo.nombre,
                        'valor': texto_valor,
                        'unidad': campo.unidad or '',
                    })
                
                parametros_data.append({
                    'nombre': parametro.nombre,
                    'campos': campos_data,
                })
            
            items_data.append({
                'nombre': item.nombre,
                'parametros': parametros_data,
            })
        
        datos_formularios.append({
            'id': formulario.id,
            'codigo': formulario.codigo,
            'version': formulario.version,
            'fecha_elabora': formulario.fecha_elabora.strftime('%d/%m/%Y') if formulario.fecha_elabora else None,
            'fecha_actualizacion': formulario.fecha_actualizacion.strftime('%d/%m/%Y %H:%M') if formulario.fecha_actualizacion else None,
            'num_hoja': formulario.num_hoja,
            'aseguradora': formulario.aseguradora.nombre if formulario.aseguradora else None,
            'diagnostico': formulario.diagnostico,
            'edad_snapshot': formulario.edad_snapshot,
            'edad_gestion': formulario.edad_gestion,
            'estado': formulario.get_estado_display() if formulario.estado else None,
            'n_controles_prenatales': formulario.n_controles_prenatales,
            'responsable': formulario.responsable,
            'items': items_data,
        })
    
    context = {
        'paciente': datos_paciente,
        'formularios': datos_formularios,
        'paciente_id': paciente_id,
    }
    
    return render(request, 'preview_pdf.html', context)


@login_required_if_enabled
def generar_pdf_paciente(request, paciente_id):
    paciente = Paciente.objects.get(id=paciente_id)
    
    formularios = Formulario.objects.filter(paciente=paciente).select_related(
        'aseguradora'
    ).prefetch_related(
        'parametros_formulario__item',
        'parametros_formulario__parametro__campos'
    )
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="paciente_{paciente.id}.pdf"'
    
    p = canvas.Canvas(response, pagesize=A4)
    width, height = A4
    y = height - 40
    
    # ===== ENCABEZADO =====
    p.setFont("Helvetica-Bold", 16)
    p.drawCentredString(width / 2, y, "FORMULARIO CLÍNICO")
    y -= 40
    
    # ===== DATOS PACIENTE =====
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, "Datos del Paciente")
    y -= 20
    
    p.setFont("Helvetica", 10)
    p.drawString(40, y, f"Nombre: {paciente.nombres}")
    y -= 15
    
    p.drawString(40, y, f"Documento: {paciente.num_identificacion}")
    y -= 15
    
    p.drawString(40, y, f"Historia clinica: {paciente.num_historia_clinica}")
    y -= 15
    
    if paciente.fecha_nacimiento:
        p.drawString(40, y, f"Fecha de Nacimiento: {paciente.fecha_nacimiento.strftime('%d/%m/%Y')}")
        y -= 15
    
    if paciente.tipo_sangre:
        p.drawString(40, y, f"Tipo de Sangre: {paciente.get_tipo_sangre_display()}")
        y -= 15
    
    y -= 20
    
    # ===== FORMULARIOS =====
    for formulario in formularios:
        p.setFont("Helvetica-Bold", 12)
        p.drawString(40, y, f"Formulario: {formulario.codigo} v{formulario.version}")
        y -= 15
        
        p.setFont("Helvetica", 10)
        # Datos del formulario desde la tabla
        if formulario.fecha_elabora:
            p.drawString(40, y, f"Fecha de Elaboración: {formulario.fecha_elabora.strftime('%d/%m/%Y')}")
            y -= 15
        
        if formulario.fecha_actualizacion:
            p.drawString(40, y, f"Fecha de Actualización: {formulario.fecha_actualizacion.strftime('%d/%m/%Y %H:%M')}")
            y -= 15
        
        p.drawString(40, y, f"Número de Hoja: {formulario.num_hoja}")
        y -= 15
        
        if formulario.aseguradora:
            p.drawString(40, y, f"Aseguradora: {formulario.aseguradora.nombre}")
            y -= 15
        
        if formulario.diagnostico:
            p.drawString(40, y, f"Diagnóstico: {formulario.diagnostico}")
            y -= 15
        
        if formulario.edad_snapshot is not None:
            p.drawString(40, y, f"Edad Snapshot: {formulario.edad_snapshot} años")
            y -= 15
        
        if formulario.edad_gestion is not None:
            p.drawString(40, y, f"Edad Gestación: {formulario.edad_gestion} semanas")
            y -= 15
        
        if formulario.estado:
            estado_display = formulario.get_estado_display()
            p.drawString(40, y, f"Estado: {estado_display}")
            y -= 15
        
        if formulario.n_controles_prenatales is not None:
            p.drawString(40, y, f"Número de Controles Prenatales: {formulario.n_controles_prenatales}")
            y -= 15
        
        if formulario.responsable:
            p.drawString(40, y, f"Responsable: {formulario.responsable}")
            y -= 15
        
        y -= 10
        
        # Obtener items únicos a través de parametros_formulario
        items_dict = {}
        for fip in formulario.parametros_formulario.select_related('item', 'parametro').prefetch_related('parametro__campos').all():
            item = fip.item
            if item.id not in items_dict:
                items_dict[item.id] = {'item': item, 'parametros': []}
            items_dict[item.id]['parametros'].append(fip.parametro)
        
        # ===== ITEMS =====
        for item_id, item_data in items_dict.items():
            item = item_data['item']
            p.setFont("Helvetica-Bold", 11)
            p.drawString(60, y, f"- {item.nombre}")
            y -= 15
            
            # ===== PARÁMETROS =====
            for parametro in item_data['parametros']:
                p.setFont("Helvetica", 10)
                p.drawString(80, y, f"{parametro.nombre}:")
                y -= 15
                
                # ===== CAMPOS / VALORES =====
                campos = parametro.campos.all()
                for campo in campos:
                    valor = MedicionValor.objects.filter(
                        medicion__formulario=formulario,
                        campo=campo
                    ).select_related('medicion', 'campo').first()
                    
                    # Obtener el valor según el tipo
                    if valor:
                        if valor.valor_number is not None:
                            texto_valor = str(valor.valor_number)
                        elif valor.valor_text:
                            texto_valor = valor.valor_text
                        elif valor.valor_boolean is not None:
                            texto_valor = 'Sí' if valor.valor_boolean else 'No'
                        elif valor.valor_json:
                            texto_valor = str(valor.valor_json)
                        else:
                            texto_valor = "—"
                    else:
                        texto_valor = "—"
                    
                    unidad = campo.unidad or ''
                    if unidad:
                        texto_completo = f"{campo.nombre}: {texto_valor} {unidad}"
                    else:
                        texto_completo = f"{campo.nombre}: {texto_valor}"
                    
                    p.drawString(100, y, texto_completo)
                    y -= 15
                    
                    # Control de paginación
                    if y < 60:
                        p.showPage()
                        y = height - 40
            
            y -= 10
        
        y -= 20
    
    # ===== BIOMETRÍA (Al final del historial) =====
    from .pdf_utils import seccion_biometria
    from .models import Huella
    from django.db.models import Q
    
    ident = str(paciente.num_identificacion).strip()
    query_biometria = Q(paciente_id=ident) | Q(paciente_id=str(paciente.id))
    if ident.isdigit():
        query_biometria |= Q(paciente_id=str(int(ident)))
        
    reg_huella = _mas_reciente_con_archivo(Huella.objects.filter(query_biometria).exclude(imagen__exact='').exclude(imagen__isnull=True), 'imagen')
    reg_firma = _mas_reciente_con_archivo(Huella.objects.filter(query_biometria).exclude(imagen_firma__exact='').exclude(imagen_firma__isnull=True), 'imagen_firma')
    
    if reg_huella or reg_firma:
        y -= 20
        y = seccion_biometria(p, reg_huella, reg_firma, 40, y, width)
        
    p.showPage()
    p.save()
    
    return response


@login_required_if_enabled
@csrf_exempt
def guardar_huella(request):
    """
    Recibe la huella y/o firma desde la App Android.
    """
    if request.method == "POST":
        try:
            body_unicode = request.body.decode('utf-8')
            print(f"--- DATOS RECIBIDOS DESDE TABLET ---\n{body_unicode}\n----------------------------------")
            
            data = json.loads(body_unicode)
            
            # Extraer campos con más flexibilidad en los nombres
            paciente_id = data.get("paciente_id") or data.get("paciente") or data.get("cc") or data.get("num_identificacion")
            formulario_id = data.get("formulario_id") or data.get("formulario")
            template = data.get("template")
            imagen_b64 = data.get("imagen") or data.get("imagen_huella") or data.get("huella")
            firma_b64 = data.get("firma") or data.get("imagen_firma") or data.get("firma_paciente")
            usuario = data.get("usuario", "Sistema")

            if not paciente_id:
                # Si no viene paciente_id, intentamos buscarlo en el texto si el JSON viene deformado
                import re
                match = re.search(r'"paciente_id"\s*:\s*"(\d+)"', body_unicode)
                if match:
                    paciente_id = match.group(1)
                    print(f"Extraído paciente_id mediante Regex: {paciente_id}")

            if not paciente_id:
                return JsonResponse({
                    "status": "error", 
                    "message": "Falta paciente_id. Recibido: " + str(data)
                }, status=400)

            # Crear el registro base
            registro = Huella.objects.create(
                paciente_id=paciente_id,
                formulario_id=formulario_id,
                template=template,
                usuario=usuario
            )

            # Decodificar y guardar la imagen de la huella
            if imagen_b64:
                if ';base64,' in imagen_b64:
                    _, imgstr = imagen_b64.split(';base64,')
                else:
                    imgstr = imagen_b64
                
                archivo = ContentFile(base64.b64decode(imgstr), name=f"huella_{paciente_id}.png")
                registro.imagen.save(f"huella_{paciente_id}.png", archivo, save=True)

            # Decodificar y guardar la imagen de la firma (si existe)
            if firma_b64:
                if ';base64,' in firma_b64:
                    _, firmastr = firma_b64.split(';base64,')
                else:
                    firmastr = firma_b64
                
                archivo_firma = ContentFile(base64.b64decode(firmastr), name=f"firma_{paciente_id}.png")
                registro.imagen_firma.save(f"firma_{paciente_id}.png", archivo_firma, save=True)

            return JsonResponse({"status": "ok", "message": "Guardado exitoso", "id": registro.id})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)
    return JsonResponse({"status": "error", "message": "Método no permitido"}, status=405)


@login_required_if_enabled
def consulta_huella(request, paciente_id):
    """
    Consulta la última huella capturada para un paciente.
    Utilizado por el polling de JavaScript.
    """
    try:
        # Buscar por ID o por Cédula (algunos logs sugieren que paciente_id puede ser cèdula)
        from django.db.models import Q
        from .models import Paciente
        
        # Si el paciente_id es numérico, intentamos buscar el paciente para obtener su cédula también
        query = Q(paciente_id=str(paciente_id))
        try:
            pac = Paciente.objects.get(id=paciente_id)
            query |= Q(paciente_id=pac.num_identificacion)
        except:
            pass
            
        # Consolidar la huella más reciente y la firma más reciente
        # (pueden venir en registros diferentes o en el mismo)
        reg_huella = _mas_reciente_con_archivo(Huella.objects.filter(query).exclude(imagen=''), 'imagen')
        reg_firma = _mas_reciente_con_archivo(Huella.objects.filter(query).exclude(imagen_firma=''), 'imagen_firma')
        
        if reg_huella or reg_firma:
            data = {
                "status": "ok",
                "paciente_id": paciente_id,
                "fecha": reg_huella.fecha.isoformat() if reg_huella else reg_firma.fecha.isoformat(),
                "imagen_huella": reg_huella.imagen.url if reg_huella and reg_huella.imagen else None,
                "imagen_firma": reg_firma.imagen_firma.url if reg_firma and reg_firma.imagen_firma else None,
                "usuario": reg_huella.usuario if reg_huella else reg_firma.usuario
            }
            response = JsonResponse(data)
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
            return response
        else:
            response = JsonResponse({"status": "pending", "message": "No se encontró biometría para este paciente"}, status=200)
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
            return response
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)

@login_required_if_enabled
@csrf_exempt
def vincular_huella(request):
    """
    Asocia las últimas capturas (huella/firma) de un paciente con un formulario ID.
    Útil cuando se captura la biometría antes de que el formulario tenga un ID (nuevo formulario).
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            paciente_id = data.get("paciente_id")
            formulario_id = data.get("formulario_id")

            if not paciente_id or not formulario_id:
                return JsonResponse({"status": "error", "message": "Falta paciente_id o formulario_id"}, status=400)

            # Buscar las huellas del paciente que no tengan formulario_id o las más recientes
            # y vincularlas al formulario actual
            huellas = Huella.objects.filter(paciente_id=paciente_id).order_by('-fecha')[:5]
            
            pudieron_vincular = 0
            for h in huellas:
                if not h.formulario_id:
                    h.formulario_id = formulario_id
                    h.save()
                    pudieron_vincular += 1

            return JsonResponse({
                "status": "ok", 
                "message": f"Vinculadas {pudieron_vincular} capturas al formulario {formulario_id}"
            })
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)
    return JsonResponse({"status": "error", "message": "Método no permitido"}, status=405)
    
@login_required_if_enabled
def ver_huella(request, documento):
    """
    Vista para visualizar la huella en una Card de Bootstrap.
    """
    huella = Huella.objects.filter(paciente_id=documento).order_by('-fecha').first()
    
    return render(request, "registros/huella.html", {
        "huella": huella
    })
