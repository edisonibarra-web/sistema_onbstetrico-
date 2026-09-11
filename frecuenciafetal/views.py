import logging
from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator

# 2026-09-10: logging en vez de print() para la ruta de autenticación /
# integración con Dinámica. REGLA: nunca registrar contraseñas, hashes,
# tokens ni datos clínicos de pacientes.
logger = logging.getLogger('frecuenciafetal.auth')
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db.models import Q
import base64
from django.core.files.base import ContentFile

from .models import (
    RegistroParto, ControlFetocardia,
    ControlRecienNacido, GlucometriaRecienNacido,
    ControlPostpartoInmediato, ControlSangrado, HuellaBebe, FirmaPaciente, Huella,
    IntentoLoginFallido
)
from .serializers import (
    RegistroPartoSerializer, RegistroPartoListSerializer,
    ControlFetocardiaSerializer, ControlRecienNacidoSerializer,
    ControlPostpartoSerializer, ControlSangradoSerializer, GlucometriaSerializer, FirmaPacienteSerializer
)
from .pdf_generator import generar_pdf_registro
from .sala_partos_db import listar_pacientes_sala_partos
from obstetriciaunificador.models import AtencionParto
from sistema_obstetrico.auth_utils import login_required_if_enabled
from meows.services.grid import construir_grid_meows, obtener_paciente_meows_por_documento


@method_decorator(never_cache, name='dispatch')
@method_decorator(ensure_csrf_cookie, name='dispatch')
@method_decorator(login_required_if_enabled, name='dispatch')
class FormularioRegistroView(TemplateView):
    """Vista para renderizar el formulario FRSPA-007"""
    template_name = 'registros/formulario.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["atencion_id"] = self.request.GET.get("atencion")
        context["documento"] = self.request.GET.get("doc")
        # API base: en sistema_obstetrico la API fetal está en /fetal/api/
        context["api_base_url"] = self.request.build_absolute_uri("/fetal/api")
        # Nombre del profesional en sesión (login DGH), para autocompletar el responsable de la firma.
        context["profesional_nombre_sesion"] = self.request.session.get('dgh_info', {}).get('nombre_completo') or ''

        # Línea de Tiempo Clínica MEOWS: se recalcula en cada carga de esta página, así que
        # cualquier medición nueva registrada en el módulo MEOWS aparece aquí automáticamente.
        meows_paciente = obtener_paciente_meows_por_documento(context["documento"])
        if meows_paciente:
            grid_parametros, columnas = construir_grid_meows(meows_paciente)
        else:
            grid_parametros, columnas = [], []
        context["meows_paciente"] = meows_paciente
        context["grid_parametros"] = grid_parametros
        context["columnas"] = columnas
        return context


@never_cache
@login_required_if_enabled
def captura_huella(request):
    """Vista para renderizar el formulario de captura"""
    return render(request, "captura_huella.html")


@method_decorator(never_cache, name='dispatch')
class RegistroPartoViewSet(viewsets.ModelViewSet):
    queryset = RegistroParto.objects.all().order_by('-created_at')
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_serializer_class(self):
        if self.action == 'list':
            return RegistroPartoListSerializer
        return RegistroPartoSerializer

    def perform_create(self, serializer):
        serializer.save()

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        atencion_param = request.data.get("atencion") or request.query_params.get("atencion")

        # Intentar obtener el objeto AtencionParto si se provee el ID
        atencion_obj = None
        if atencion_param:
            try:
                atencion_obj = AtencionParto.objects.get(id=atencion_param)
                data["atencion"] = atencion_obj.id
            except (AtencionParto.DoesNotExist, ValueError):
                pass

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        
        # Guardar pasando el objeto atencion explícitamente si existe
        if atencion_obj:
            instance = serializer.save(atencion=atencion_obj)
        else:
            instance = serializer.save()

        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['get', 'post'], url_path='huella-pie')
    def upload_huella_pie(self, request, pk=None):
        """
        GET: devuelve la huella del pie en base64 para visualización.
        POST: sube la huella (archivo o base64).
        """
        registro = self.get_object()
        try:
            control_rn = ControlRecienNacido.objects.get(registro=registro)
        except ControlRecienNacido.DoesNotExist:
            if request.method == 'GET':
                return Response({'huella_base64': None}, status=status.HTTP_200_OK)
            return Response({'error': 'No existe control recién nacido.'}, status=status.HTTP_404_NOT_FOUND)

        if request.method == 'GET':
            b64 = getattr(control_rn, 'huella_pie_base64', None) or None
            if not b64 and control_rn.huella_pie:
                try:
                    control_rn.huella_pie.open('rb')
                    b64 = 'data:image/jpeg;base64,' + base64.b64encode(control_rn.huella_pie.read()).decode('ascii')
                    control_rn.huella_pie.close()
                except Exception:
                    b64 = None
            return Response({'huella_base64': b64}, status=status.HTTP_200_OK)

        # POST: subir huella
        # Opción 1: imagen base64 desde canvas del frontend
        if 'huella_base64' in request.data:
            b64_data = request.data['huella_base64']
            # Limpiar el prefijo data:image/...;base64,
            if ',' in b64_data:
                b64_data = b64_data.split(',')[1]
            image_data = base64.b64decode(b64_data)
            file_name = f"huella_{str(registro.identificacion).replace(' ', '_')}_{registro.id}.png"
            control_rn.huella_pie = ContentFile(image_data, name=file_name)
            control_rn.huella_pie_base64 = request.data['huella_base64']
            control_rn.save()
            return Response(
                {'message': 'Huella guardada correctamente', 'id': str(registro.id)},
                status=status.HTTP_200_OK
            )

        # Opción 2: archivo de imagen subido directamente
        if 'huella_pie' in request.FILES:
            control_rn.huella_pie = request.FILES['huella_pie']
            control_rn.save()
            return Response(
                {'message': 'Huella guardada correctamente', 'id': str(registro.id)},
                status=status.HTTP_200_OK
            )

        return Response(
            {'error': 'No se recibió imagen. Envíe huella_base64 o huella_pie.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    @action(detail=True, methods=['get'], url_path='pdf')
    def descargar_pdf(self, request, pk=None):
        """Genera y descarga el PDF del registro FRSPA-007"""
        import re
        from django.http import HttpResponse

        registro = self.get_object()
        try:
            pdf_bytes = generar_pdf_registro(registro)
            if not isinstance(pdf_bytes, bytes):
                pdf_bytes = bytes(pdf_bytes) if pdf_bytes else b''
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            nom = (registro.nombre_paciente or '')[:20].strip()
            nom = re.sub(r'[\s]+', '_', nom)
            nom = re.sub(r'[\\/:*?"<>|]', '', nom) or 'paciente'
            ident = (registro.identificacion or '').strip()
            ident = re.sub(r'[\\/:*?"<>|\s]', '', ident) or 'sin_id'
            filename_ascii = f"FRSPA-007_{ident}_{nom}.pdf"
            response['Content-Disposition'] = f'attachment; filename="{filename_ascii}"'
            response['Content-Length'] = str(len(pdf_bytes))
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            return response
        except Exception as e:
            return Response(
                {'error': f'Error al generar PDF: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='pdf-plantilla')
    def descargar_pdf_plantilla(self, request):
        """Genera el PDF FRSPA-007 con los campos vacíos (plantilla en blanco),
        sin necesidad de haber guardado un registro previamente.

        2026-09-11: si la paciente ya está identificada en pantalla (documento
        en la URL o en el campo de identificación) aunque todavía no se haya
        guardado ningún registro de este formulario, se recibe ese documento
        por query param para poder mostrar igual la Línea de Tiempo Clínica
        MEOWS -- lo único que necesita esa sección es saber de quién es (ver
        generar_pdf_registro). El resto del formulario sigue en blanco.

        También se recibe (opcional) el nombre de quien está diligenciando
        el formulario ahora mismo -- campo "RESPONSABLE DEL REGISTRO" en
        pantalla -- para que quede integrado en el PDF sin necesidad de
        haber guardado ya una firma. Se manda en `nombre_firma_paciente`
        porque es el mismo campo que usa generar_pdf_registro para decidir
        si el responsable ya quedó identificado (ver ese archivo).
        """
        import re
        from django.http import HttpResponse

        documento = (request.query_params.get('documento') or '').strip()
        nombre = (request.query_params.get('nombre') or '').strip()
        responsable = (request.query_params.get('responsable') or '').strip()
        registro_vacio = RegistroParto(
            nombre_paciente=nombre,
            identificacion=documento,
            nombre_firma_paciente=responsable,
            edad_gestacional=None,
            gestas=1,
        )
        try:
            pdf_bytes = generar_pdf_registro(registro_vacio, es_plantilla=True)
            if not isinstance(pdf_bytes, bytes):
                pdf_bytes = bytes(pdf_bytes) if pdf_bytes else b''
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename="FRSPA-007_plantilla.pdf"'
            response['Content-Length'] = str(len(pdf_bytes))
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'
            return response
        except Exception as e:
            return Response(
                {'error': f'Error al generar PDF: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='buscar')
    def buscar(self, request):
        """Búsqueda rápida por nombre o identificación (documento)"""
        query = (request.query_params.get('q', '') or '').strip()
        if not query:
            return Response([])
        qs = self.queryset.filter(
            Q(nombre_paciente__icontains=query) | Q(identificacion__icontains=query)
        ).distinct()[:20]
        serializer = RegistroPartoListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='sala-partos')
    def sala_partos(self, request):
        """
        Lista pacientes en Sala de Partos desde DGEMPRES03 (readonly).
        q: opcional; filtra por nombre o identificación.
        Devuelve datos para autocompletar el formulario (nombre, identificación, edad gestacional, gestas).
        """
        query = (request.query_params.get('q', '') or '').strip()
        try:
            data = listar_pacientes_sala_partos(query=query if query else None)
            return Response(data)
        except Exception as e:
            return Response(
                {'error': str(e), 'detail': 'No se pudo conectar a la base de datos de consulta.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

    @action(detail=False, methods=['get'], url_path='mi-firma')
    def mi_firma(self, request):
        """
        Obtiene la firma digital del médico logueado desde DGH (readonly).
        Si no hay sesión o firma, devuelve 200 con firma_b64: null para no generar 404 en consola.
        """
        from django.db import connections
        dgh_info = request.session.get('dgh_info', {})
        codigo_medico = dgh_info.get('codigo_medico')
        
        if not codigo_medico:
            return Response({'firma_b64': None, 'message': 'No hay profesional en sesión.'}, status=status.HTTP_200_OK)
        
        sql = "SELECT GMEFIRMADI FROM GENMEDICO WHERE GMECODIGO = %s"
        try:
            with connections['readonly'].cursor() as cursor:
                cursor.execute(sql, [codigo_medico])
                row = cursor.fetchone()
                if row and row[0]:
                    import base64
                    firma_b64 = base64.b64encode(row[0]).decode('utf-8')
                    return Response({
                        'firma_b64': 'data:image/png;base64,' + firma_b64,
                        'nombre': dgh_info.get('nombre_completo'),
                        'identificacion': dgh_info.get('identificacion'),
                        'tarjeta_pro': dgh_info.get('tarjeta_pro')
                    })
                return Response({'firma_b64': None, 'message': 'El profesional no tiene firma registrada en DGH.'})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@method_decorator(never_cache, name='dispatch')
class ControlFetocardiaViewSet(viewsets.ModelViewSet):
    serializer_class = ControlFetocardiaSerializer

    def get_queryset(self):
        registro_id = self.kwargs.get('registro_pk')
        return ControlFetocardia.objects.filter(registro_id=registro_id)

    def perform_create(self, serializer):
        registro = get_object_or_404(RegistroParto, pk=self.kwargs['registro_pk'])
        atencion_id = (
            self.request.data.get("atencion")
            or self.request.query_params.get("atencion")
            or ""
        )
        atencion_id = str(atencion_id).strip()
        if atencion_id.isdigit():
            try:
                atencion = AtencionParto.objects.get(id=atencion_id)
                if registro.atencion_id != atencion.id:
                    registro.atencion = atencion
                    registro.save(update_fields=["atencion"])
            except Exception:
                pass
        serializer.save(registro=registro)

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

    # Nota: antes esta vista bloqueaba update/partial_update con un 405
    # ("solo se puede agregar nuevos"). Se permite editar deliberadamente
    # para poder corregir un error humano en un control ya guardado; el
    # comportamiento por defecto de ModelViewSet (PUT/PATCH actualiza la
    # fila existente) ya hace exactamente eso.


@method_decorator(never_cache, name='dispatch')
class ControlRecienNacidoViewSet(viewsets.ModelViewSet):
    serializer_class = ControlRecienNacidoSerializer

    def get_queryset(self):
        registro_id = self.kwargs.get('registro_pk')
        return ControlRecienNacido.objects.filter(registro_id=registro_id)

    def perform_create(self, serializer):
        registro = get_object_or_404(RegistroParto, pk=self.kwargs['registro_pk'])
        atencion_id = (
            self.request.data.get("atencion")
            or self.request.query_params.get("atencion")
            or ""
        )
        atencion_id = str(atencion_id).strip()
        if atencion_id.isdigit():
            try:
                atencion = AtencionParto.objects.get(id=atencion_id)
                if registro.atencion_id != atencion.id:
                    registro.atencion = atencion
                    registro.save(update_fields=["atencion"])
            except Exception:
                pass
        serializer.save(registro=registro)

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


@method_decorator(never_cache, name='dispatch')
class ControlPostpartoViewSet(viewsets.ModelViewSet):
    serializer_class = ControlPostpartoSerializer

    def get_queryset(self):
        registro_id = self.kwargs.get('registro_pk')
        return ControlPostpartoInmediato.objects.filter(registro_id=registro_id)

    def perform_create(self, serializer):
        registro = get_object_or_404(RegistroParto, pk=self.kwargs['registro_pk'])
        atencion_id = (
            self.request.data.get("atencion")
            or self.request.query_params.get("atencion")
            or ""
        )
        atencion_id = str(atencion_id).strip()
        if atencion_id.isdigit():
            try:
                atencion = AtencionParto.objects.get(id=atencion_id)
                if registro.atencion_id != atencion.id:
                    registro.atencion = atencion
                    registro.save(update_fields=["atencion"])
            except Exception:
                pass
        serializer.save(registro=registro)

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

    # Nota: antes esta vista bloqueaba update/partial_update con un 405
    # ("solo se puede agregar nuevos"). Se permite editar deliberadamente
    # para poder corregir un error humano en un control ya guardado; el
    # comportamiento por defecto de ModelViewSet (PUT/PATCH actualiza la
    # fila existente) ya hace exactamente eso.


@method_decorator(never_cache, name='dispatch')
class ControlSangradoViewSet(viewsets.ModelViewSet):
    """
    Controles periódicos de cuantificación gravimétrica del sangrado. A
    diferencia de fetocardia/postparto, nace ya "edit-safe": el
    comportamiento por defecto de ModelViewSet permite PATCH/PUT para
    corregir un control guardado.
    """
    serializer_class = ControlSangradoSerializer

    def get_queryset(self):
        registro_id = self.kwargs.get('registro_pk')
        return ControlSangrado.objects.filter(registro_id=registro_id)

    def perform_create(self, serializer):
        registro = get_object_or_404(RegistroParto, pk=self.kwargs['registro_pk'])
        serializer.save(registro=registro)


@login_required_if_enabled
def guardar_huella_bebe(request):
    if request.method == "POST":
        import json
        from django.http import JsonResponse
        from django.core.files.base import ContentFile
        import base64

        try:
            data = json.loads(request.body)
            imagen = data["imagen"]
            bebe_id = data["bebe_id"]
            tipo = data["tipo"]

            format, imgstr = imagen.split(";base64,")
            file = ContentFile(
                base64.b64decode(imgstr),
                name=f"huella_bebe_{bebe_id}_{tipo}.png"
            )

            HuellaBebe.objects.create(
                bebe_id=bebe_id,
                tipo=tipo,
                imagen=file
            )

            return JsonResponse({"ok": True})
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=400)
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=400)
    return JsonResponse({"ok": False, "error": "Método no permitido"}, status=405)


@never_cache
@login_required_if_enabled
def guardar_firma_digital(request):
    """
    Guarda la firma manuscrita digital del responsable.
    Espera JSON con { registro_id: UUID, firma: "data:image/png;base64,..." }
    """
    if request.method == "POST":
        import json
        from django.http import JsonResponse
        from django.core.files.base import ContentFile
        import base64

        from django.utils import timezone

        try:
            data = json.loads(request.body)
            firma_b64 = data.get("firma")
            registro_id = data.get("registro_id")
            nombre_responsable = data.get("nombre_responsable", "")

            if not firma_b64 or not registro_id:
                return JsonResponse({"ok": False, "error": "Faltan datos (firma o registro_id)"}, status=400)

            registro = get_object_or_404(RegistroParto, pk=registro_id)

            # Decodificar imagen
            if "," in firma_b64:
                header, imgstr = firma_b64.split(";base64,")
            else:
                imgstr = firma_b64

            image_data = base64.b64decode(imgstr)
            file_name = f"firma_{str(registro.identificacion).replace(' ', '_')}_{registro.id}.png"
            
            # Guardar en el modelo
            registro.firma_paciente.save(file_name, ContentFile(image_data), save=False)
            registro.nombre_firma_paciente = nombre_responsable
            registro.fecha_hora_firma = timezone.now()
            registro.save()

            return JsonResponse({"ok": True, "message": "Firma del responsable guardada correctamente"})
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=400)

    return JsonResponse({"ok": False, "error": "Método no permitido"}, status=405)



# --- Límite de intentos de login (ver IntentoLoginFallido en models.py) ---
# Ventana y umbral elegidos para frenar un script de fuerza bruta (que
# necesita cientos/miles de intentos por minuto para ser útil) sin ser tan
# estrictos que un grupo de personas detrás de la misma IP/NAT del hospital
# quede bloqueado por errores normales de tipeo.
_LOGIN_VENTANA_MINUTOS = 15
_LOGIN_MAX_INTENTOS = 6
_LOGIN_RETENCION_HORAS = 24


def _ip_cliente(request):
    """IP de origen del request, tolerando estar detrás de un proxy/balanceador."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR') or '0.0.0.0'


def _demasiados_intentos_login(ip):
    from django.utils import timezone
    from datetime import timedelta
    limite = timezone.now() - timedelta(minutes=_LOGIN_VENTANA_MINUTOS)
    return IntentoLoginFallido.objects.filter(ip=ip, creado__gte=limite).count() >= _LOGIN_MAX_INTENTOS


def _registrar_intento_login_fallido(ip, username):
    from django.utils import timezone
    from datetime import timedelta
    IntentoLoginFallido.objects.create(ip=ip, username=(username or '')[:150])
    # Limpieza barata: aprovecha este mismo write para no acumular filas viejas
    # para siempre (no hay un cron/management command aparte para esto).
    corte = timezone.now() - timedelta(hours=_LOGIN_RETENCION_HORAS)
    IntentoLoginFallido.objects.filter(creado__lt=corte).delete()


def login_view(request):
    # Nota: se usa la ruta explícita '/atencion/sala-de-partos/' (no el
    # nombre de URL) porque hoy existe más de un urlpattern llamado 'home'
    # sin namespace (raíz del proyecto y frecuenciafetal/urls.py), y
    # reverse('home') resolvería de forma ambigua.
    # 2026-09-09: se cambió el destino por defecto de '/atencion/' a
    # '/atencion/sala-de-partos/' -- la pantalla de bienvenida que vivía en
    # '/atencion/' se movió al login (ver login.html) y esa ruta ahora solo
    # redirige a Sala de Partos de todas formas (ver obstetriciaunificador/
    # views.py:dashboard); apuntar aquí directo ahorra ese salto intermedio.
    if request.user.is_authenticated:
        return redirect('/atencion/sala-de-partos/')

    error = None
    next_url = request.GET.get('next', '/atencion/sala-de-partos/')

    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        next_url = request.POST.get('next', '/atencion/sala-de-partos/')
        ip = _ip_cliente(request)

        if _demasiados_intentos_login(ip):
            # 2026-09-09: límite de intentos (hallazgo "fuerza bruta sin
            # límite") -- por IP, no por cuenta, a propósito (ver docstring
            # de IntentoLoginFallido en models.py).
            error = (
                "Demasiados intentos fallidos desde esta red. Espere unos "
                "minutos e intente de nuevo."
            )
        else:
            from django.contrib.auth import authenticate, login
            # dgh_connection_error: lo marca DGHBackend en el propio request
            # cuando el fallo fue por no poder conectarse a Dinámica (ver
            # auth_dgh.py), para distinguirlo de una contraseña realmente
            # incorrecta -- son dos situaciones distintas y el mensaje al
            # usuario debe ser distinto (aquí no tiene sentido, por ejemplo,
            # decirle "conserve su cuenta local como respaldo" si su clave sí
            # era correcta pero Dinámica no respondió).
            request.dgh_connection_error = False
            user = authenticate(request, username=u, password=p)
            if user:
                login(request, user)
                return redirect(next_url)
            elif getattr(request, 'dgh_connection_error', False):
                # 2026-09-10: mensaje institucional, sin tecnicismos (no
                # menciona SQL, IP, tablas ni "sin conexión" literal). El
                # detalle técnico ya quedó en el log (ver auth_dgh.py).
                error = (
                    "No fue posible validar las credenciales institucionales en "
                    "este momento. Intente nuevamente en unos minutos. Si el "
                    "problema continúa, use una cuenta local de este sistema (si "
                    "tiene una creada como respaldo) o comuníquese con Sistemas."
                )
                logger.warning("Login no verificable: Dinámica Gerencial no respondió.")
                # No cuenta como intento fallido real: no fue un error de
                # contraseña, fue Dinámica sin responder -- no hay que
                # penalizar a alguien que sí tecleó bien su clave.
            else:
                error = "Usuario o contraseña incorrectos en Dinámica Gerencial."
                _registrar_intento_login_fallido(ip, u)

    return render(request, 'frecuenciafetal/login.html', {'error': error, 'next': next_url})


def _usuario_existe_en_dinamica(username):
    """
    Consulta de SOLO LECTURA a GENUSUARIO (nunca escribe) para saber si ya
    existe un usuario ACTIVO con ese nombre en Dinámica. Se usa exclusivamente
    para bloquear el auto-registro local (ver registro_usuario_view) sobre un
    username que ya pertenece a una cuenta real de Dinámica — sin este chequeo,
    cualquiera podría "reservar" localmente el nombre de un usuario real del
    hospital y hacerse pasar por él dentro de esta app (aunque nunca podría
    tocar Dinámica mismo con esa cuenta local). Si la consulta a Dinámica
    falla por cualquier motivo, se asume que SÍ existe (fail-safe: bloquea el
    registro en vez de arriesgarse a crear un duplicado silencioso).
    """
    from django.db import connections
    try:
        with connections['readonly'].cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM GENUSUARIO WHERE USUNOMBRE = %s AND USUESTADO = 1",
                [username],
            )
            return cursor.fetchone() is not None
    except Exception:
        logger.warning(
            "No se pudo verificar el usuario contra Dinámica Gerencial durante el "
            "registro; se bloquea el alta por precaución."
        )
        return True


def registro_usuario_view(request):
    """
    Registro de cuenta LOCAL para quien no tiene (o cree no tener) usuario en
    Dinámica Gerencial.

    2026-09-09: a propósito, esto NUNCA escribe en la base de datos de
    Dinámica (GENUSUARIO/GENUSUWEB) — la cuenta se crea SOLO en el modelo
    User de Django, igual que ya hace DGHBackend para las cuentas validadas
    contra Dinámica (ver frecuenciafetal/auth_dgh.py). Se decidió así porque
    escribir directamente en el ERP del hospital desde fuera de su propia
    interfaz es un riesgo mucho mayor que mantener un registro local aparte:
    no sabemos qué triggers, validaciones o relaciones con roles/permisos
    (GENROL, GENUSUROL) exige Dinámica para una cuenta nueva, y un registro a
    medias podría dejar una cuenta "rota" en el sistema central del hospital.

    Por eso mismo, un username que ya exista como usuario ACTIVO en
    GENUSUARIO queda bloqueado aquí (ver _usuario_existe_en_dinamica): si
    alguien ya tiene cuenta real en Dinámica, DEBE entrar con esa cuenta por
    el login normal (frecuenciafetal.auth_dgh.DGHBackend) — el registro local
    es solo para quien de verdad no tiene ninguna cuenta en Dinámica todavía.

    Se recomienda (no se obliga) usar el mismo usuario/clave que en Dinámica:
    si esa persona llega a tener cuenta real allá más adelante con el MISMO
    username, DGHBackend reutiliza el mismo registro de Django al validarla
    (ver User.objects.get_or_create en auth_dgh.py) — la transición es
    transparente, sin necesidad de otro registro.
    """
    if request.user.is_authenticated:
        return redirect('/atencion/sala-de-partos/')

    error = None
    next_url = request.GET.get('next', '/atencion/sala-de-partos/')

    if request.method == 'POST':
        from django.contrib.auth.models import User, Group

        username = (request.POST.get('username') or '').strip()
        nombre_completo = (request.POST.get('nombre_completo') or '').strip()
        password = request.POST.get('password') or ''
        password2 = request.POST.get('password2') or ''
        next_url = request.POST.get('next', '/atencion/sala-de-partos/')

        if not username or not nombre_completo or not password:
            error = "Complete usuario, nombre completo y contraseña."
        elif len(password) < 6:
            error = "La contraseña debe tener al menos 6 caracteres."
        elif password != password2:
            error = "Las contraseñas no coinciden."
        elif User.objects.filter(username__iexact=username).exists() or _usuario_existe_en_dinamica(username):
            # 2026-09-09 -- hallazgo "enumeración de usuarios vía /registro/":
            # antes había un mensaje distinto para "ya existe localmente" y
            # "ya existe en Dinámica", lo que permitía a cualquiera (sin
            # necesitar contraseña) usar este formulario como oráculo para
            # averiguar qué usernames de Dinámica son válidos y están
            # activos -- información útil para luego dirigir un ataque de
            # fuerza bruta contra esas cuentas confirmadas. Se une en un solo
            # mensaje genérico que no revela cuál de los dos casos ocurrió.
            # (El `or` de Python evalúa de izquierda a derecha y se detiene
            # en el primero que sea True, así que la consulta a Dinámica de
            # _usuario_existe_en_dinamica ni siquiera se ejecuta cuando ya
            # existe localmente.)
            error = (
                "No fue posible crear la cuenta con ese usuario. Si ya tiene acceso "
                "(en este sistema o en Dinámica Gerencial), use el login normal en "
                "vez de registrarse aquí."
            )
        else:
            user = User.objects.create_user(username=username, password=password)
            user.first_name = nombre_completo
            user.is_staff = False
            user.save()
            # Marca de auditoría: distingue a simple vista (ej. en el admin de
            # Django) las cuentas creadas por este registro local de las que
            # vienen de Dinámica vía DGHBackend (esas nunca quedan en este grupo).
            grupo_local, _ = Group.objects.get_or_create(name='Registro local (no Dinámica)')
            user.groups.add(grupo_local)

            from django.contrib.auth import login
            # dgh_info mínimo: solo el nombre que la persona diligenció, para
            # que "profesional_nombre_sesion" (usado en varios encabezados,
            # ver meows/views.py y trabajoparto/views.py) no quede vacío. El
            # resto de campos (codigo_medico, tarjeta_pro, etc.) se dejan sin
            # poner — ya están manejados con gracia como ausentes en el resto
            # del sistema (ver ControlFetocardiaViewSet.mi_firma).
            request.session['dgh_info'] = {'nombre_completo': nombre_completo}
            # Con AUTHENTICATION_BACKENDS teniendo 2 entradas (DGHBackend +
            # ModelBackend), login() exige saber cuál backend "certificó" a
            # este user -- se especifica ModelBackend a mano porque esta
            # cuenta se acaba de crear con create_user(), nunca pasó por
            # DGHBackend.authenticate().
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect(next_url)

    return render(request, 'frecuenciafetal/registro.html', {
        'error': error,
        'next': next_url,
    })


@require_http_methods(["GET", "POST"])
def logout_view(request):
    """
    2026-09-10: el cierre de sesión ahora se hace por POST + CSRF (el botón del
    encabezado, header_formatos.html, es un <form method="post">).

    Un GET a /logout/ YA NO cierra la sesión: solo redirige. Así se cierra el
    vector de "logout forzado por CSRF" (una página maliciosa con
    <img src="/logout/"> ya no puede desloguear al usuario), sin romper ningún
    enlace ni marcador viejo — un GET simplemente rebota de vuelta a la app.
    """
    from django.contrib.auth import logout
    if request.method == 'POST':
        logout(request)
    return redirect('/')
@login_required_if_enabled
@csrf_exempt
def guardar_huella(request):
    """
    API para recibir la huella biométrica del paciente (Simplificada).
    """
    import json
    import base64
    import datetime
    from django.http import JsonResponse
    from django.core.files.base import ContentFile
    from .models import Huella

    if request.method == "POST":
        try:
            import json
            import base64
            from django.core.files.base import ContentFile
            
            # Android envía JSON, por lo tanto leemos el body
            data = json.loads(request.body)

            documento = data.get("paciente_id")
            template = data.get("template")
            imagen = data.get("imagen_huella") # Campo que envía Android
            usuario = data.get("usuario") or "SYSTEM"

            # Preparar la instancia (sin guardar aún para manejar el ImageField)
            huella = Huella(
                documento=documento,
                template=template,
                usuario=usuario
            )

            if imagen:
                # Decodificar imagen base64
                img_str = str(imagen)
                if ';base64,' in img_str:
                    img_str = img_str.split(';base64,')[1]
                
                try:
                    imagen_bytes = base64.b64decode(img_str)
                    # Guardar archivo de imagen
                    huella.imagen_huella.save(
                        f"huella_{str(documento).replace(' ', '_')}.png",
                        ContentFile(imagen_bytes),
                        save=False
                    )
                except Exception as b64err:
                    print(f"Error decodificando Base64: {b64err}")

            # Guardar definitivamente en la base de datos
            huella.save()
            
            return JsonResponse({
                "status": "ok", 
                "message": "Huella guardada correctamente",
                "id": huella.id
            })
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)

    elif request.method == "GET":
        documento = request.GET.get("paciente_id")
        registro = Huella.objects.filter(documento=documento).order_by('-fecha').first()
        if registro:
            return JsonResponse({
                "status": "ok",
                "documento": registro.documento,
                "url_imagen": registro.imagen_huella.url if registro.imagen_huella else None
            })
        return JsonResponse({"status": "error", "message": "No encontrado"}, status=404)

    return JsonResponse({"status": "error", "message": "Método no permitido"}, status=405)


@login_required_if_enabled
def ultima_huella(request, documento):
    """
    API para devolver la última huella capturada para un paciente (Simplificada).
    """
    from .models import Huella
    from django.http import JsonResponse

    registro = Huella.objects.filter(documento=documento).order_by('-fecha').first()

    if not registro:
        return JsonResponse({"status": "no", "message": "No hay huella para este paciente"})

    return JsonResponse({
        "status": "ok",
        "documento": registro.documento,
        "template": registro.template,
        "imagen_huella": registro.imagen_huella.url if registro.imagen_huella else "",
        "usuario": registro.usuario,
        "fecha": registro.fecha.strftime("%d-%m-%Y %H:%M")
    })

@login_required_if_enabled
def ver_huella(request, documento):
    """
    Vista para visualizar la huella en una Card de Bootstrap.
    """
    from .models import Huella
    huella = Huella.objects.filter(documento=documento).order_by('-fecha').first()
    
    return render(request, "registros/huella.html", {
        "huella": huella
    })
