import logging
from django.views.generic import TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
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

from .models import (
    RegistroParto, ControlFetocardia,
    ControlRecienNacido, GlucometriaRecienNacido,
    ControlPostpartoInmediato, ControlSangrado,
    ControlGlobo, ControlSutura, recalcular_estados_sangrado,
    IntentoLoginFallido
)
from .serializers import (
    RegistroPartoSerializer, RegistroPartoListSerializer,
    ControlFetocardiaSerializer, ControlRecienNacidoSerializer,
    ControlPostpartoSerializer, ControlSangradoSerializer, GlucometriaSerializer,
    ControlGloboSerializer, ControlSuturaSerializer,
)
from .pdf_generator import generar_pdf_registro
from .responsables import (
    firma_sesion, registrar_participacion, responsables_para_api, valores_modelo,
    bitacora_registro_y_rn, registrar_cambios, responsables_por_seccion,
)
from .sala_partos_db import listar_pacientes_sala_partos
from obstetriciaunificador.models import AtencionParto
from sistema_obstetrico.auth_utils import login_required_if_enabled, nombre_profesional_sesion
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
        # 2026-09-24: ingreso elegido en el selector de ingresos (vacío = actual).
        from obstetriciaunificador.ingresos import limpiar_numero_ingreso
        context["ingreso_param"] = limpiar_numero_ingreso(self.request.GET.get("ingreso"))
        # API base: en sistema_obstetrico la API fetal está en /fetal/api/
        context["api_base_url"] = self.request.build_absolute_uri("/fetal/api")
        # Nombre del profesional en sesión (login DGH, o el usuario local
        # autenticado si no hay dgh_info -- ver nombre_profesional_sesion),
        # para autocompletar el responsable de la firma.
        context["profesional_nombre_sesion"] = nombre_profesional_sesion(self.request)

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


# "Guardar Registro Completo" no puede cerrar el registro antes de que termine
# la vigilancia posparto. 2026-09-23: la regla ya NO es por reloj (6 horas
# desde que se creó el registro -- ej. creado a las 6 a. m. se habilitaba a
# las 12 m. aunque faltaran controles), sino por el propio cronograma: el
# cierre se permite cuando ya está guardado el ÚLTIMO control posparto, el de
# las 6 horas después del parto (minuto 360 del cronograma 15/30/60 --
# PP_MINUTOS en formulario.html). El botón se bloquea en pantalla con la
# misma regla, pero esto es lo que de verdad lo impide.
MINUTO_ULTIMO_CONTROL_POSPARTO = 360

# 2026-09-30: tampoco se cierra sin el Control del recién nacido mínimo y su
# huella plantar (PDF). Mismos campos que marca con * la card del formulario
# (RN_OBLIGATORIOS_CIERRE en formulario.html).
CAMPOS_RN_OBLIGATORIOS_CIERRE = [
    ('genero', 'género'),
    ('peso', 'peso'),
    ('talla', 'talla'),
    ('apgar_1min', "APGAR al 1'"),
    ('apgar_5min', "APGAR a los 5'"),
]


def _faltantes_recien_nacido(registro):
    rn = ControlRecienNacido.objects.filter(registro=registro).first()
    faltan = [
        etiqueta for campo, etiqueta in CAMPOS_RN_OBLIGATORIOS_CIERRE
        if rn is None or getattr(rn, campo) in (None, '')
    ]
    if rn is None or not rn.huella_pdf:
        faltan.append('huella plantar (PDF)')
    return faltan


# 2026-10-06: la tabla de signos vitales posparto (controles_postparto) ya no
# está en el formulario, así que el control de las 6 h es el de la vigilancia:
# Sangrado, Globo de seguridad y Sutura deben tener guardado su control del
# minuto 360. Los registros antiguos con controles_postparto al 360 siguen
# valiendo.
VIGILANCIA_CIERRE = [
    ('controles_sangrado', 'Sangrado cuantificado'),
    ('controles_globo', 'Globo de seguridad'),
    ('controles_sutura', 'Sutura y heridas'),
]


def _faltantes_control_6h(registro):
    """Lista de las tarjetas de vigilancia sin control del minuto 360
    (vacía si ya se puede cerrar por esta regla)."""
    if registro.controles_postparto.filter(minuto_control__gte=MINUTO_ULTIMO_CONTROL_POSPARTO).exists():
        return []
    faltan = []
    for relacion, etiqueta in VIGILANCIA_CIERRE:
        controles = getattr(registro, relacion)
        if not controles.filter(minuto_control__gte=MINUTO_ULTIMO_CONTROL_POSPARTO).exists():
            ultimo = controles.order_by('-minuto_control').first()
            faltan.append(f'{etiqueta} (último: {ultimo.minuto_control} min)' if ultimo else f'{etiqueta} (sin controles)')
    return faltan


def _intentar_cerrar_registro(instance, request):
    """
    Cierra el ciclo (completado_en/completado_por) si ya está registrado el
    control posparto de las 6 horas (MINUTO_ULTIMO_CONTROL_POSPARTO).
    Devuelve un mensaje de advertencia (str) si NO se pudo cerrar por eso, o
    None si se cerró ahora mismo (o ya estaba cerrado de antes -- no es un
    error volver a intentarlo, simplemente no hace nada).
    """
    if instance.completado_en is not None:
        return None

    from django.utils import timezone

    faltan_6h = _faltantes_control_6h(instance)
    if faltan_6h:
        return (
            'Aún no se puede cerrar el registro: falta el control de las 6 horas '
            f'después del parto (minuto {MINUTO_ULTIMO_CONTROL_POSPARTO}) en '
            f'{"; ".join(faltan_6h)}.'
        )

    # 2026-09-30: la hora de parto también es obligatoria (es además la hora
    # de nacimiento que imprime el PDF en "Control del recién nacido").
    pendientes = []
    # 2026-10-06: el nombre del acompañante es obligatorio para cerrar (el
    # formulario lo marca con * y no habilita el botón sin él).
    if not (instance.nombre_acompanante or '').strip():
        pendientes.append('en "Datos de la paciente" falta el nombre del acompañante')
    if not instance.hora_parto:
        pendientes.append('en "Características del parto" falta la hora de parto')
    faltan_rn = _faltantes_recien_nacido(instance)
    if faltan_rn:
        pendientes.append(f'en "Control del recién nacido" falta {", ".join(faltan_rn)}')
    if pendientes:
        return f'Aún no se puede cerrar el registro: {"; ".join(pendientes)}.'

    # 2026-09-25: cierre ATÓMICO -- solo cierra si nadie lo cerró todavía
    # (antes: leer y luego guardar; dos pestañas cerrando a la vez enviaban
    # el formato dos veces). Solo quien lo cerró de verdad lo envía.
    completado_en = timezone.now()
    completado_por = nombre_profesional_sesion(request)
    cerrados = RegistroParto.objects.filter(pk=instance.pk, completado_en__isnull=True).update(
        completado_en=completado_en, completado_por=completado_por,
    )
    if cerrados:
        instance.completado_en, instance.completado_por = completado_en, completado_por
        instance._cerrado_ahora = True
    else:
        instance.refresh_from_db(fields=['completado_en', 'completado_por'])
    return None


def _cerrar_y_enviar_a_repositorio(instance, request, data):
    """
    Intenta el cierre del ciclo y, si el registro se cerró AHORA, envía el
    formato final (PDF FRSPA-007) al repositorio clínico (NAS / carpeta local
    de pruebas). Un fallo del envío no deshace el cierre: queda registrado en
    DocumentoRepositorio y se informa en data['repositorio'] para reintentar
    desde /atencion/api/repositorio/enviar/.
    """
    advertencia_cierre = _intentar_cerrar_registro(instance, request)
    if advertencia_cierre:
        data['advertencia_cierre'] = advertencia_cierre
        return
    data['completado_en'] = instance.completado_en
    data['completado_por'] = instance.completado_por
    if not getattr(instance, '_cerrado_ahora', False):
        return  # ya estaba cerrado (o lo cerró otra pestaña justo antes): no se reenvía

    from obstetriciaunificador.repositorio import (
        RepositorioError, enviar_control_posparto, resumen_envio,
    )
    try:
        documento = enviar_control_posparto(
            instance, usuario=nombre_profesional_sesion(request),
        )
        data['repositorio'] = resumen_envio(documento)
    except RepositorioError as exc:  # SinCambiosError = ya está en el repositorio (ok)
        data['repositorio'] = {'ok': getattr(exc, 'documento', None) is not None, 'mensaje': str(exc)}
    except Exception as exc:  # p. ej. error generando el PDF
        logger.exception('Error enviando FRSPA-007 al repositorio')
        data['repositorio'] = {'ok': False, 'mensaje': f'Error generando el PDF: {exc}'}

# 2026-09-30: huella plantar del recién nacido (PDF escaneado). Un escaneo
# de una hoja en buena resolución pesa 1-3 MB; 10 MB deja margen sin
# permitir archivos desproporcionados.
HUELLA_RN_MAX_BYTES = 10 * 1024 * 1024
HUELLA_RN_MAX_PAGINAS = 3
# 2026-10-05: la huella también se puede tomar como foto con la cámara de la
# tablet/celular. La foto se convierte aquí a un PDF de una página, así todo
# lo demás (visor, PDF del registro, repositorio) sigue recibiendo un PDF.
HUELLA_RN_FOTO_LADO_MAX = 2400  # px del lado mayor; legible y liviana


def _foto_a_pdf_huella(archivo):
    """Si `archivo` es una imagen (JPEG/PNG/WebP), devuelve (ContentFile PDF,
    None); si no es imagen, (archivo, None) sin tocarlo; si es una imagen
    que no se puede leer, (None, mensaje de error)."""
    import io
    from django.core.files.base import ContentFile
    from PIL import Image, ImageOps, UnidentifiedImageError

    if archivo is None or archivo.size == 0 or archivo.size > HUELLA_RN_MAX_BYTES:
        return archivo, None  # _validar_pdf_huella da el mensaje
    archivo.seek(0)
    if archivo.read(1024).lstrip().startswith(b'%PDF-'):
        archivo.seek(0)
        return archivo, None
    archivo.seek(0)
    try:
        imagen = Image.open(archivo)
        if imagen.format not in ('JPEG', 'PNG', 'WEBP', 'MPO'):
            archivo.seek(0)
            return archivo, None
        imagen = ImageOps.exif_transpose(imagen)  # foto de celular: respeta la orientación
        imagen.thumbnail((HUELLA_RN_FOTO_LADO_MAX, HUELLA_RN_FOTO_LADO_MAX))
        imagen = imagen.convert('RGB')
        salida = io.BytesIO()
        imagen.save(salida, format='PDF', resolution=200.0, quality=85)
    except (UnidentifiedImageError, Image.DecompressionBombError):
        archivo.seek(0)
        return archivo, None
    except Exception:
        return None, 'La foto está dañada o no se puede leer. Tómela de nuevo.'
    return ContentFile(salida.getvalue(), name='huella.pdf'), None


def _validar_pdf_huella(archivo):
    """Devuelve un mensaje de error (str) o None si el archivo es un PDF válido.
    No se confía en la extensión ni en el Content-Type que manda el navegador:
    se revisa la firma %PDF- y que pypdf pueda abrirlo."""
    if archivo is None:
        return 'No se recibió ningún archivo.'
    if archivo.size == 0:
        return 'El archivo está vacío.'
    if archivo.size > HUELLA_RN_MAX_BYTES:
        return f'El PDF pesa {archivo.size / 1024 / 1024:.1f} MB; el máximo es {HUELLA_RN_MAX_BYTES // 1024 // 1024} MB.'
    archivo.seek(0)
    if not archivo.read(1024).lstrip().startswith(b'%PDF-'):
        archivo.seek(0)
        return 'El archivo no es una foto válida. Tome la foto de la huella con la cámara.'
    archivo.seek(0)
    try:
        from pypdf import PdfReader
        lector = PdfReader(archivo)
        if lector.is_encrypted:
            return 'El PDF está protegido con contraseña; súbalo sin protección.'
        paginas = len(lector.pages)
    except Exception:
        return 'El PDF está dañado o no se puede leer.'
    finally:
        archivo.seek(0)
    if paginas == 0:
        return 'El PDF no tiene páginas.'
    if paginas > HUELLA_RN_MAX_PAGINAS:
        return f'El PDF tiene {paginas} páginas; la huella debe venir en máximo {HUELLA_RN_MAX_PAGINAS}.'
    return None


class BloqueoIngresoCerradoMixin:
    """
    2026-09-24: un ingreso que egresó hace más de
    settings.INGRESO_HORAS_GRACIA_EDICION horas queda en SOLO CONSULTA --
    se rechaza cualquier escritura sobre sus registros (el selector de
    ingresos ya lo bloquea en pantalla; esto es lo que de verdad lo impide).
    Crear un registro NUEVO no se bloquea. Ante cualquier duda (Dinámica sin
    respuesta, sin número de ingreso) se permite: nunca frenar la atención.
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return
        registro_id = kwargs.get('registro_pk') or (kwargs.get('pk') if isinstance(self, RegistroPartoViewSet) else None)
        if not registro_id:
            return
        registro = RegistroParto.objects.select_related('atencion').filter(pk=registro_id).first()
        if registro is None:
            return
        from obstetriciaunificador.ingresos import motivo_bloqueo_edicion
        motivo = motivo_bloqueo_edicion(registro.atencion, request.user, creado_en=registro.created_at)
        if motivo:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(motivo)



class ParticipacionEnEdicionMixin:
    """2026-09-28: corregir un control ya guardado también cuenta como haber
    diligenciado el registro (el control conserva a quien lo registró). Solo
    si de verdad cambió algo: al guardar, el formulario reenvía todos los
    controles ya guardados aunque nadie los haya tocado.
    2026-10-06: la corrección y la eliminación quedan además en la bitácora
    del paso (bitacora_seccion / bitacora_etiqueta)."""
    bitacora_seccion = None

    def bitacora_etiqueta(self, instance):
        minuto = getattr(instance, 'minuto_control', None)
        return f'control {minuto} min' if minuto is not None else 'control'

    def perform_update(self, serializer):
        antes = valores_modelo(serializer.instance)
        super().perform_update(serializer)
        if valores_modelo(serializer.instance) != antes:
            registrar_participacion(serializer.instance.registro, self.request)
            if self.bitacora_seccion:
                registrar_cambios(serializer.instance.registro, self.request, self.bitacora_seccion,
                                  [('correccion', self.bitacora_etiqueta(serializer.instance))])

    def perform_destroy(self, instance):
        registro, etiqueta = instance.registro, self.bitacora_etiqueta(instance)
        super().perform_destroy(instance)
        registrar_participacion(registro, self.request)
        if self.bitacora_seccion:
            registrar_cambios(registro, self.request, self.bitacora_seccion, [('eliminacion', etiqueta)])


@method_decorator(never_cache, name='dispatch')
class RegistroPartoViewSet(BloqueoIngresoCerradoMixin, viewsets.ModelViewSet):
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

        response_data = self.get_serializer(instance).data

        # 2026-09-22: el flujo normal (por-atencion, ver esa acción más
        # abajo) ya debería encontrar y continuar un registro existente por
        # documento antes de llegar a crear uno nuevo -- si aun así se llega
        # aquí y ya existía otro registro FRSPA-007 para la misma paciente,
        # es una señal de que algo se saltó ese flujo (ej. un enlace viejo
        # sin ?doc=/?atencion=, o dos personas guardando por primera vez casi
        # al mismo tiempo). No se bloquea la creación -- solo se avisa, para
        # que quien lo diligenció revise si correspondía continuar el
        # anterior en vez de crear uno aparte.
        identificacion = (data.get("identificacion") or "").strip()
        if identificacion:
            duplicado = RegistroParto.objects.filter(
                identificacion=identificacion
            ).exclude(id=instance.id).order_by('-created_at').first()
            if duplicado:
                from django.utils import timezone
                fecha_local = timezone.localtime(duplicado.created_at)
                response_data['advertencia_duplicado'] = (
                    f"Ya existía un registro FRSPA-007 para esta paciente "
                    f"(creado {fecha_local:%d/%m/%Y %H:%M}). Se creó uno "
                    f"nuevo -- revise si correspondía continuar el anterior "
                    f"en vez de crear uno aparte."
                )

        # 2026-09-22: "completar" solo debería llegar en un PUT/PATCH sobre
        # un registro ya existente (el botón "Guardar Registro Completo" no
        # se habilita hasta que ya hay un registro guardado, ni antes de las
        # HORAS_MINIMAS_PARA_COMPLETAR) -- se maneja igual aquí por si acaso
        # llega en la creación misma, para no dejar un registro "completo" a
        # medias sin su sello de cierre.
        registrar_participacion(instance, request)
        # 2026-10-06: bitácora por paso de lo que llegó ya en la creación.
        bitacora_registro_y_rn(instance, request, None, self._foto_registro(instance))
        if bool(request.data.get('completar')):
            _cerrar_y_enviar_a_repositorio(instance, request, response_data)
        response_data['responsables'] = responsables_para_api(instance)
        response_data['responsables_secciones'] = responsables_por_seccion(instance)

        return Response(response_data)

    def update(self, request, *args, **kwargs):
        # 2026-10-06: HALLAZGO -- el formulario viejo guardaba con PUT la
        # pantalla COMPLETA; una pestaña abierta desde antes (campos vacíos)
        # borraba lo que otra persona ya había guardado (se perdió el recién
        # nacido). El formulario actual envía PATCH solo con lo que cambió.
        # Un PUT completo ya no se acepta: una pantalla vieja falla con este
        # aviso en vez de sobrescribir datos.
        if not kwargs.get('partial', False):
            return Response(
                {'detail': 'Esta pantalla tiene una versión anterior del formulario. Recargue la página (F5) '
                           'para seguir guardando: no se guardó nada para no sobrescribir datos ya guardados.'},
                status=status.HTTP_409_CONFLICT,
            )
        completar = bool(request.data.get('completar'))
        response = super().update(request, *args, **kwargs)
        # 2026-09-22: el cierre del ciclo ("Guardar Registro Completo") es un
        # paso APARTE del guardado normal de campos -- primero corre el PUT
        # de siempre (con lo que esa pantalla tenga en ese momento), y solo
        # si viene el flag explícito se intenta el cierre después. Así ningún
        # autoguardado ni corrección desde la Vista Previa (que reutilizan el
        # mismo submitForm() sin este flag) puede cerrar el registro por
        # accidente -- ver formulario.html, solo el botón "Guardar Registro
        # Completo" lo manda.
        if response.status_code == 200:
            instance = self.get_object()
            # 2026-09-28: el autoguardado reenvía todo aunque nadie haya
            # cambiado nada -- solo cuenta como participante quien de verdad
            # cambió algo (o cerró el registro).
            if getattr(self, '_hubo_cambios', False) or completar:
                registrar_participacion(instance, request)
            if completar:
                _cerrar_y_enviar_a_repositorio(instance, request, response.data)
            response.data['responsables'] = responsables_para_api(instance)
            response.data['responsables_secciones'] = responsables_por_seccion(instance)
        return response

    @staticmethod
    def _foto_registro(registro):
        # 2026-09-30: el recién nacido viaja dentro del PUT del registro
        # (autoguardado), así que también cuenta para saber si hubo cambios.
        rn = ControlRecienNacido.objects.filter(registro_id=registro.pk).first()
        glucos = list(rn.glucometrias.values_list('hora', 'resultado').order_by('hora', 'id')) if rn else []
        return valores_modelo(registro), valores_modelo(rn), glucos

    def perform_update(self, serializer):
        antes = self._foto_registro(serializer.instance)
        super().perform_update(serializer)
        despues = self._foto_registro(serializer.instance)
        self._hubo_cambios = despues != antes
        if self._hubo_cambios:
            # 2026-10-06: qué campos de Parto / Recién nacido tocó quien guarda.
            bitacora_registro_y_rn(serializer.instance, self.request, antes, despues)

    @action(detail=True, methods=['get'], url_path='responsables')
    def responsables(self, request, pk=None):
        """2026-09-28: quiénes diligenciaron el registro y qué hizo cada uno
        (liviano: la pantalla lo refresca después de cada guardado).
        2026-10-06: + 'secciones', los responsables de cada paso."""
        registro = self.get_object()
        return Response({
            'general': responsables_para_api(registro),
            'secciones': responsables_por_seccion(registro),
        })

    @action(detail=True, methods=['get', 'post', 'delete'], url_path='huella-rn')
    def huella_rn(self, request, pk=None):
        """
        2026-09-30: huella plantar del recién nacido, subida como PDF escaneado.
          GET    -> el PDF (inline, para verlo embebido en el formulario).
          POST   -> sube/reemplaza (multipart, campo "archivo").
          DELETE -> la quita.
        El archivo nunca se sirve por /media/: solo por aquí, con la misma
        autenticación del resto de la API. Subir o quitar queda bloqueado en
        un ingreso de solo consulta (BloqueoIngresoCerradoMixin) y con el
        registro ya cerrado ("Guardar Registro Completo").
        """
        from django.http import FileResponse, Http404
        from django.utils import timezone

        registro = self.get_object()
        rn = ControlRecienNacido.objects.filter(registro=registro).first()

        if request.method == 'GET':
            if rn is None or not rn.huella_pdf:
                raise Http404('Este registro no tiene huella cargada.')
            try:
                archivo = rn.huella_pdf.open('rb')
            except (FileNotFoundError, OSError):
                logger.error('Huella del RN registrada pero el archivo no existe en disco (registro %s).', registro.pk)
                raise Http404('El archivo de la huella no se encontró en el servidor.')
            response = FileResponse(archivo, content_type='application/pdf')
            response['Content-Disposition'] = 'inline; filename="huella_recien_nacido.pdf"'
            response['X-Content-Type-Options'] = 'nosniff'
            # Se muestra embebida (iframe) en el propio formulario.
            response['X-Frame-Options'] = 'SAMEORIGIN'
            response['Cache-Control'] = 'no-store'
            return response

        if registro.completado_en is not None:
            return Response(
                {'error': 'El registro ya está cerrado: no se puede cambiar la huella.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if request.method == 'DELETE':
            if rn is not None and rn.huella_pdf:
                rn.huella_pdf.delete(save=False)
                rn.huella_pdf = None
                rn.huella_subida_por = ''
                rn.huella_subida_en = None
                rn.save(update_fields=['huella_pdf', 'huella_subida_por', 'huella_subida_en'])
                registrar_participacion(registro, request)
                registrar_cambios(registro, request, 'recien_nacido', [('eliminacion', 'Huella plantar')])
            return Response({'tiene_huella': False})

        archivo, error = _foto_a_pdf_huella(request.FILES.get('archivo'))
        error = error or _validar_pdf_huella(archivo)
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

        if rn is None:
            rn = ControlRecienNacido.objects.create(registro=registro, **firma_sesion(request))
        anterior = rn.huella_pdf.name if rn.huella_pdf else None
        rn.huella_pdf.save('huella.pdf', archivo, save=False)
        rn.huella_subida_por = nombre_profesional_sesion(request)[:255]
        rn.huella_subida_en = timezone.now()
        rn.save(update_fields=['huella_pdf', 'huella_subida_por', 'huella_subida_en'])
        if anterior and anterior != rn.huella_pdf.name:
            rn.huella_pdf.storage.delete(anterior)
        registrar_participacion(registro, request)
        registrar_cambios(registro, request, 'recien_nacido',
                          [('correccion' if anterior else 'registro', 'Huella plantar')])
        return Response({
            'tiene_huella': True,
            'huella_subida_por': rn.huella_subida_por,
            'huella_subida_en': rn.huella_subida_en,
        })

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
        # 2026-09-28: el responsable ya no se escribe a mano -- sale de la sesión.
        responsable = nombre_profesional_sesion(request)
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

    @action(detail=False, methods=['get'], url_path='por-atencion')
    def por_atencion(self, request):
        """Busca el RegistroParto más reciente de una atención (o, si no
        hay coincidencia por atencion_id, por documento) para repoblar el
        formulario FRSPA-007 al reabrirlo -- así los datos ya guardados en
        una visita anterior a esta misma atención (p.ej. controles postparto
        de un rango de minutos ya diligenciado) no aparecen en blanco.
        """
        atencion_id = (request.query_params.get('atencion') or '').strip()
        documento = (request.query_params.get('documento') or '').strip()
        registro = None
        # 2026-09-24: selector de ingresos -- el registro del ingreso elegido
        # (?ingreso=; sin él, el actual), no "el más reciente de la paciente":
        # en un reingreso no debe abrirse el registro del ingreso anterior.
        if documento:
            try:
                from obstetriciaunificador.ingresos import resumen_ingresos
                resumen, grupos = resumen_ingresos(documento, 'control_posparto', request.query_params.get('ingreso') or '', fresco=True)
            except Exception:
                resumen, grupos = None, {}
            if resumen and resumen['elegido']:
                ids = grupos.get(resumen['elegido'], [])
                registro = self.queryset.filter(id__in=ids).order_by('-created_at').first()
                if registro is None:
                    return Response({'encontrado': False, 'solo_consulta': resumen['solo_consulta']})
                data = RegistroPartoSerializer(registro).data
                data['encontrado'] = True
                data['solo_consulta'] = resumen['solo_consulta']
                return Response(data)
        if atencion_id.isdigit():
            registro = self.queryset.filter(atencion_id=atencion_id).order_by('-created_at').first()
        if registro is None and documento:
            registro = self.queryset.filter(identificacion=documento).order_by('-created_at').first()
        if registro is None:
            return Response({'encontrado': False})
        data = RegistroPartoSerializer(registro).data
        data['encontrado'] = True
        return Response(data)

    @action(detail=False, methods=['get'], url_path='sala-partos')
    def sala_partos(self, request):
        """
        Lista pacientes en Sala de Partos desde DGEMPRES03 (readonly).
        q: opcional; filtra por nombre, identificación o número de ingreso.
        Devuelve datos para autocompletar el formulario (nombre, identificación, edad gestacional, gestas).
        """
        query = (request.query_params.get('q', '') or '').strip()
        try:
            # 2026-10-02: sin el tope de 50 (ninguna paciente activa debe quedar fuera).
            data = listar_pacientes_sala_partos(query=query if query else None, limit=1000)
            return Response(data)
        except Exception as e:
            return Response(
                {'error': str(e), 'detail': 'No se pudo conectar a la base de datos de consulta.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

    # 2026-09-14: se eliminó mi_firma() (auto-completar la firma del médico
    # leyendo GENMEDICO.GMEFIRMADI desde Dinámica) a pedido explícito, antes
    # de salir a producción -- ya no se captura ni se muestra ninguna firma
    # como imagen en este módulo.


@method_decorator(never_cache, name='dispatch')
class ControlFetocardiaViewSet(ParticipacionEnEdicionMixin, BloqueoIngresoCerradoMixin, viewsets.ModelViewSet):
    serializer_class = ControlFetocardiaSerializer

    bitacora_seccion = 'fetocardia'

    def bitacora_etiqueta(self, instance):
        hora = instance.hora.strftime('%H:%M') if hasattr(instance.hora, 'strftime') else str(instance.hora or '')[:5]
        return f'toma {hora}'.strip()

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
        serializer.save(registro=registro, **firma_sesion(self.request, con_responsable=True))
        registrar_participacion(registro, self.request)

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
class ControlRecienNacidoViewSet(ParticipacionEnEdicionMixin, BloqueoIngresoCerradoMixin, viewsets.ModelViewSet):
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
        serializer.save(registro=registro, **firma_sesion(self.request))
        registrar_participacion(registro, self.request)

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
class ControlPostpartoViewSet(ParticipacionEnEdicionMixin, BloqueoIngresoCerradoMixin, viewsets.ModelViewSet):
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
        serializer.save(registro=registro, **firma_sesion(self.request, con_responsable=True))
        registrar_participacion(registro, self.request)

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


def _guardar_control_minuto(serializer, **extra):
    """2026-10-06: guarda un control de vigilancia; si otro guardado del mismo
    minuto llegó justo a la vez (ambos pasaron la validación del serializer),
    responde 400 'minuto_ocupado' en vez de un 500 por IntegrityError."""
    from django.db import IntegrityError, transaction
    from rest_framework.exceptions import ValidationError
    try:
        with transaction.atomic():
            return serializer.save(**extra)
    except IntegrityError:
        minuto = serializer.validated_data.get('minuto_control')
        raise ValidationError(
            {'minuto_control': [f'El control del minuto {minuto} ya está registrado.']},
            code='minuto_ocupado',
        )


@method_decorator(never_cache, name='dispatch')
class ControlSangradoViewSet(ParticipacionEnEdicionMixin, BloqueoIngresoCerradoMixin, viewsets.ModelViewSet):
    """
    Controles periódicos de cuantificación gravimétrica del sangrado. A
    diferencia de fetocardia/postparto, nace ya "edit-safe": el
    comportamiento por defecto de ModelViewSet permite PATCH/PUT para
    corregir un control guardado.
    """
    serializer_class = ControlSangradoSerializer

    bitacora_seccion = 'vigilancia'

    def bitacora_etiqueta(self, instance):
        return f'Sangrado {instance.minuto_control} min'

    def get_queryset(self):
        registro_id = self.kwargs.get('registro_pk')
        return ControlSangrado.objects.filter(registro_id=registro_id)

    def perform_create(self, serializer):
        registro = get_object_or_404(RegistroParto, pk=self.kwargs['registro_pk'])
        _guardar_control_minuto(serializer, registro=registro, **firma_sesion(self.request))
        registrar_participacion(registro, self.request)
        # El `estado` (semáforo) de cada control se calcula en el backend
        # según el acumulado hasta ese punto -- nunca lo manda el cliente.
        # recalcular_estados_sangrado reconsulta las filas desde la BD (para
        # recalcular también los controles posteriores), así que la instancia
        # de este serializer queda desactualizada -- se refresca para que la
        # respuesta HTTP de este POST ya traiga el estado correcto.
        recalcular_estados_sangrado(registro)
        serializer.instance.refresh_from_db()

    def perform_update(self, serializer):
        antes = valores_modelo(serializer.instance)
        serializer.save()
        if valores_modelo(serializer.instance) != antes:
            registrar_participacion(serializer.instance.registro, self.request)
            registrar_cambios(serializer.instance.registro, self.request, self.bitacora_seccion,
                              [('correccion', self.bitacora_etiqueta(serializer.instance))])
        recalcular_estados_sangrado(serializer.instance.registro)
        serializer.instance.refresh_from_db()

    def perform_destroy(self, instance):
        registro, etiqueta = instance.registro, self.bitacora_etiqueta(instance)
        instance.delete()
        registrar_participacion(registro, self.request)
        registrar_cambios(registro, self.request, self.bitacora_seccion, [('eliminacion', etiqueta)])
        # Borrar un control cambia el acumulado de todos los posteriores.
        recalcular_estados_sangrado(registro)


@method_decorator(never_cache, name='dispatch')
class ControlGloboViewSet(ParticipacionEnEdicionMixin, BloqueoIngresoCerradoMixin, viewsets.ModelViewSet):
    """Controles periódicos del globo de seguridad. El `estado` es el valor
    elegido directamente por quien registra (no se deriva de nada más),
    a diferencia de ControlSangrado."""
    serializer_class = ControlGloboSerializer

    bitacora_seccion = 'vigilancia'

    def bitacora_etiqueta(self, instance):
        return f'Globo de seguridad {instance.minuto_control} min'

    def get_queryset(self):
        registro_id = self.kwargs.get('registro_pk')
        return ControlGlobo.objects.filter(registro_id=registro_id)

    def perform_create(self, serializer):
        registro = get_object_or_404(RegistroParto, pk=self.kwargs['registro_pk'])
        _guardar_control_minuto(serializer, registro=registro, **firma_sesion(self.request))
        registrar_participacion(registro, self.request)


@method_decorator(never_cache, name='dispatch')
class ControlSuturaViewSet(ParticipacionEnEdicionMixin, BloqueoIngresoCerradoMixin, viewsets.ModelViewSet):
    """Controles periódicos de sutura y heridas. El `estado` es el valor
    elegido directamente por quien registra (no se deriva de nada más),
    a diferencia de ControlSangrado."""
    serializer_class = ControlSuturaSerializer

    bitacora_seccion = 'vigilancia'

    def bitacora_etiqueta(self, instance):
        return f'Sutura y heridas {instance.minuto_control} min'

    def get_queryset(self):
        registro_id = self.kwargs.get('registro_pk')
        return ControlSutura.objects.filter(registro_id=registro_id)

    def perform_create(self, serializer):
        registro = get_object_or_404(RegistroParto, pk=self.kwargs['registro_pk'])
        _guardar_control_minuto(serializer, registro=registro, **firma_sesion(self.request))
        registrar_participacion(registro, self.request)


# 2026-09-14: se eliminaron guardar_huella_bebe() y guardar_firma_digital()
# (captura de huella plantar del recién nacido y firma manuscrita del
# responsable) a pedido explícito, antes de salir a producción.


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
            # 2026-09-14: HALLAZGO -- "RESPONSABLE" salía precargado con el
            # nombre de la persona ANTERIOR que había iniciado sesión en ese
            # mismo navegador (ej. admin veía "DEISY CAROLINA FLOREZ..."),
            # incluso siendo un usuario distinto. Causa: dgh_info solo lo
            # escribe DGHBackend.authenticate() cuando la cuenta SÍ valida
            # contra Dinámica (ver auth_dgh.py) -- una cuenta local/admin
            # (autenticada por ModelBackend) nunca lo toca, así que
            # login(request, user) NO limpia por sí solo lo que hubiera
            # quedado en la sesión de un login DGH anterior en el mismo
            # navegador (login() rota la clave de sesión por seguridad, pero
            # no borra las claves ya presentes en request.session). Se limpia
            # aquí, ANTES de authenticate(): si este login SÍ es por DGH,
            # DGHBackend lo vuelve a poblar con el dato correcto y fresco
            # dentro de su propio authenticate(); si es una cuenta local,
            # queda vacío (el campo ya contempla ese caso -- ver el título
            # del input "si queda vacío, diligéncielo manualmente").
            request.session.pop('dgh_info', None)
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
                    "problema continúa, comuníquese con el área de Sistemas."
                )
                logger.warning("Login no verificable: Dinámica Gerencial no respondió.")
                # No cuenta como intento fallido real: no fue un error de
                # contraseña, fue Dinámica sin responder -- no hay que
                # penalizar a alguien que sí tecleó bien su clave.
            else:
                error = "Usuario o contraseña incorrectos en Dinámica Gerencial."
                _registrar_intento_login_fallido(ip, u)

    return render(request, 'frecuenciafetal/login.html', {'error': error, 'next': next_url})


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
# 2026-09-14: se eliminaron guardar_huella(), ultima_huella() y ver_huella()
# (captura/consulta de huella biométrica vía app Android) a pedido explícito,
# antes de salir a producción -- frecuenciafetal.models.Huella ya no existe.
