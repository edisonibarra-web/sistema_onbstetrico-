from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.utils.decorators import method_decorator
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
    ControlPostpartoInmediato, HuellaBebe, FirmaPaciente, Huella
)
from .serializers import (
    RegistroPartoSerializer, RegistroPartoListSerializer,
    ControlFetocardiaSerializer, ControlRecienNacidoSerializer,
    ControlPostpartoSerializer, GlucometriaSerializer, FirmaPacienteSerializer
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
        sin necesidad de haber guardado un registro previamente."""
        import re
        from django.http import HttpResponse

        registro_vacio = RegistroParto(
            nombre_paciente='',
            identificacion='',
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

    def update(self, request, *args, **kwargs):
        return Response(
            {'detail': 'No se permite editar registros de fetocardia ya guardados. Solo se puede agregar nuevos.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    def partial_update(self, request, *args, **kwargs):
        return Response(
            {'detail': 'No se permite editar registros de fetocardia ya guardados. Solo se puede agregar nuevos.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )


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

    def update(self, request, *args, **kwargs):
        return Response(
            {'detail': 'No se permite editar controles postparto ya guardados. Solo se puede agregar nuevos.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    def partial_update(self, request, *args, **kwargs):
        return Response(
            {'detail': 'No se permite editar controles postparto ya guardados. Solo se puede agregar nuevos.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

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


def login_view(request):
    # Nota: se usa la ruta explícita '/atencion/' (no el nombre de URL 'home') porque hoy existe
    # más de un urlpattern llamado 'home' sin namespace (raíz del proyecto y frecuenciafetal/urls.py),
    # y reverse('home') resolvería de forma ambigua.
    if request.user.is_authenticated:
        return redirect('/atencion/')

    error = None
    next_url = request.GET.get('next', '/atencion/')

    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        next_url = request.POST.get('next', '/atencion/')

        from django.contrib.auth import authenticate, login
        user = authenticate(request, username=u, password=p)
        if user:
            login(request, user)
            return redirect(next_url)
        else:
            error = "Usuario o contraseña incorrectos en Dinámica Gerencial."

    return render(request, 'frecuenciafetal/login.html', {'error': error, 'next': next_url})


def logout_view(request):
    from django.contrib.auth import logout
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
