from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import IntegrityError
from django.db.models import Q
from django.contrib import messages
from django.conf import settings
from meows.models import Paciente, Formulario, Parametro, Medicion, MedicionValor, RangoParametro, Hpnestanc
from obstetriciaunificador.models import AtencionParto
from meows.services.meows import calcular_score_desde_bd
from meows.services.grid import construir_grid_meows
# Importación diferida del generador PDF para evitar errores de WeasyPrint al iniciar
# from meows.generador_pdf_meows import generar_pdf_meows
import json
import base64
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache
from django.core.files.base import ContentFile
from meows.models import FirmaPaciente
from datetime import date, datetime
from django.utils import timezone
from sistema_obstetrico.auth_utils import login_required_if_enabled


@login_required_if_enabled
def abrir_meows_desde_atencion(request, doc=None):
    """
    Entrada desde la vista unificada: resuelve paciente por documento
    y redirige a la vista de creación MEOWS conservando atencion/doc.
    """
    atencion_id = (request.GET.get("atencion") or "").strip()
    documento = (doc or request.GET.get("doc") or "").strip()
    if not documento:
        return redirect("/")

    paciente = Paciente.objects.filter(numero_documento=documento).first()
    if not paciente:
        paciente = Paciente.objects.create(
            numero_documento=documento,
            nombres="N/A",
            apellidos="N/A",
            sexo="F",
        )

    query = f"?doc={documento}"
    if atencion_id:
        query += f"&atencion={atencion_id}"
    return redirect(f"/meows/nuevo/{paciente.id}/{query}")


@login_required_if_enabled
def abrir_historial_meows_desde_documento(request, doc=None):
    """
    Entrada desde otros módulos (ej. Trabajo de Parto): resuelve el paciente
    MEOWS por número de documento y redirige a su cuadrícula de historial
    clínico. Si el paciente aún no tiene registro en MEOWS, se crea uno
    vacío (mismo comportamiento que abrir_meows_desde_atencion) y el
    historial simplemente se muestra sin mediciones.
    """
    atencion_id = (request.GET.get("atencion") or "").strip()
    documento = (doc or request.GET.get("doc") or "").strip()
    if not documento:
        return redirect("/")

    paciente = Paciente.objects.filter(numero_documento=documento).first()
    if not paciente:
        paciente = Paciente.objects.create(
            numero_documento=documento,
            nombres="N/A",
            apellidos="N/A",
            sexo="F",
        )

    query = f"?doc={documento}"
    if atencion_id:
        query += f"&atencion={atencion_id}"
    return redirect(f"/meows/historial/{paciente.id}/{query}")


@never_cache
@login_required_if_enabled
def crear_medicion_meows(request, paciente_id):
    """
    Vista para crear una nueva medición MEOWS para un paciente.
    """
    atencion_id = request.GET.get("atencion")
    paciente = get_object_or_404(Paciente, id=paciente_id)
    
    # Obtener o crear formulario MEOWS
    formulario, _ = Formulario.objects.get_or_create(
        codigo="MEOWS",
        defaults={
            'nombre': 'Sistema de Alerta Temprana Obstétrico',
            'version': '1.0',
            'activo': True
        }
    )
    
    parametros = Parametro.objects.filter(activo=True).order_by("orden")

    if request.method == "POST":
        atencion_id = (request.POST.get("atencion") or request.GET.get("atencion") or "").strip()
        # Obtener el número de documento del formulario
        nuevo_numero_doc = request.POST.get('numero_documento', '').strip()
        if not nuevo_numero_doc:
            messages.error(request, 'El número de documento es requerido.')
            return render(request, "meows/formulario.html", {
                "paciente": paciente,
                "parametros": parametros
            })

        # Fecha y hora del monitoreo (registro manual).
        fecha_monitoreo_str = request.POST.get('fecha_monitoreo', '').strip()
        hora_monitoreo_str = request.POST.get('hora_monitoreo', '').strip()

        if not fecha_monitoreo_str or not hora_monitoreo_str:
            messages.error(request, 'La fecha y hora del monitoreo son requeridas.')
            return render(request, "meows/formulario.html", {
                "paciente": paciente,
                "parametros": parametros
            })

        try:
            fecha_hora_monitoreo_naive = datetime.strptime(
                f"{fecha_monitoreo_str} {hora_monitoreo_str}", "%Y-%m-%d %H:%M"
            )
        except ValueError:
            messages.error(request, 'La fecha u hora del monitoreo no tienen un formato válido.')
            return render(request, "meows/formulario.html", {
                "paciente": paciente,
                "parametros": parametros
            })

        fecha_hora_monitoreo = timezone.make_aware(
            fecha_hora_monitoreo_naive, timezone.get_current_timezone()
        )

        # Separar nombre completo en nombres y apellidos
        nombre_completo = request.POST.get('nombre_completo', '').strip()
        if nombre_completo:
            partes = nombre_completo.split(maxsplit=1)
            nombres_nuevo = partes[0] if len(partes) >= 1 else ''
            apellidos_nuevo = partes[1] if len(partes) >= 2 else ''
        else:
            nombres_nuevo = request.POST.get('nombres', '')
            apellidos_nuevo = request.POST.get('apellidos', '')
        
        # Buscar si ya existe un paciente con este número de documento
        paciente_existente = Paciente.objects.filter(numero_documento=nuevo_numero_doc).first()
        
        if paciente_existente:
            # Si existe un paciente con este documento, usar ese paciente (NO reemplazar el de la URL)
            paciente = paciente_existente
            # Actualizar solo los campos que vienen del formulario
            if nombre_completo:
                paciente.nombres = nombres_nuevo
                paciente.apellidos = apellidos_nuevo
        else:
            # Si NO existe, crear un nuevo paciente (NO actualizar el paciente de la URL)
            paciente = Paciente.objects.create(
                numero_documento=nuevo_numero_doc,
                nombres=nombres_nuevo or 'N/A',
                apellidos=apellidos_nuevo or 'N/A',
                sexo='F',  # Valor por defecto cuando no viene desde sistema externo
            )
        
        # Actualizar campos opcionales (tanto si es existente como si es nuevo)


        paciente.aseguradora = request.POST.get('aseguradora', '')
        paciente.cama = request.POST.get('cama', '')
        fecha_nacimiento = request.POST.get('fecha_nacimiento')
        paciente.fecha_nacimiento = fecha_nacimiento if fecha_nacimiento else None
        fecha_ingreso = request.POST.get('fecha_ingreso')
        paciente.fecha_ingreso = fecha_ingreso if fecha_ingreso else None
        paciente.responsable = request.POST.get('responsable', '')
        
        try:
            paciente.save()
        except IntegrityError as e:
            messages.error(request, 'Error al guardar los datos del paciente. El número de documento ya existe.')
            return render(request, "meows/formulario.html", {
                "paciente": paciente,
                "parametros": parametros
            })
        
        atencion = None
        if atencion_id:
            try:
                atencion = AtencionParto.objects.get(id=atencion_id)
            except Exception:
                atencion = None

        # Crear la medición
        medicion = Medicion.objects.create(
            paciente=paciente,
            formulario=formulario,
            atencion=atencion,
            fecha_hora=fecha_hora_monitoreo,
        )

        # Crear los valores de medición
        from meows.services.meows import calcular_meows
        valores_dict = {}
        for parametro in parametros:
            valor = request.POST.get(parametro.codigo)
            if valor:
                MedicionValor.objects.create(
                    medicion=medicion,
                    parametro=parametro,
                    valor=valor
                )
                valores_dict[parametro.codigo] = valor

        # Calcular score total, riesgo y mensaje
        resultados_meows = calcular_meows(valores_dict)
        medicion.meows_total = resultados_meows["meows_total"]
        medicion.meows_riesgo = resultados_meows["meows_riesgo"]
        medicion.meows_mensaje = resultados_meows["meows_mensaje"]
        medicion.save(update_fields=["meows_total", "meows_riesgo", "meows_mensaje"])

        # Notificar éxito
        messages.success(request, 'Registro MEOWS guardado exitosamente.')

        # Mantenerse en la misma vista de formulario luego de guardar.
        query_parts = []
        if atencion_id:
            query_parts.append(f"atencion={atencion_id}")
        if paciente.numero_documento:
            query_parts.append(f"doc={paciente.numero_documento}")

        query_string = f"?{'&'.join(query_parts)}" if query_parts else ""
        return redirect(f"/meows/nuevo/{paciente.id}/{query_string}")

    return render(request, "meows/formulario.html", {
        "paciente": paciente,
        "parametros": parametros,
        "atencion_id": request.GET.get("atencion"),
        "documento": request.GET.get("doc"),
        "profesional_nombre_sesion": request.session.get('dgh_info', {}).get('nombre_completo') or '',
    })


@never_cache
@login_required_if_enabled
def ver_meows(request, medicion_id):
    """
    Vista para mostrar el resultado de una medición MEOWS.
    """
    medicion = get_object_or_404(Medicion, id=medicion_id)

    return render(request, "meows/resultado.html", {
        "medicion": medicion,
        "valores": medicion.valores.select_related("parametro").order_by("parametro__orden"),
        "atencion_id": medicion.atencion_id,
        "documento": medicion.paciente.numero_documento,
    })


@require_http_methods(["GET"])
def api_rangos_meows(request):
    """
    API endpoint para obtener los rangos MEOWS desde la base de datos.
    Retorna JSON con los rangos organizados por código de parámetro.
    """
    rangos_dict = {}
    
    # Obtener todos los parámetros activos
    parametros = Parametro.objects.filter(activo=True)
    
    for parametro in parametros:
        # Obtener rangos activos del parámetro, ordenados
        rangos = RangoParametro.objects.filter(
            parametro=parametro,
            activo=True
        ).order_by('orden', 'valor_min')
        
        rangos_dict[parametro.codigo] = [
            {
                'min': float(rango.valor_min),
                'max': float(rango.valor_max),
                'score': rango.score
            }
            for rango in rangos
        ]
    
    return JsonResponse(rangos_dict, json_dumps_params={'ensure_ascii': False})


@require_http_methods(["POST"])
def api_calcular_score(request):
    """
    API endpoint para calcular el score de un valor específico.
    """
    import json
    
    try:
        data = json.loads(request.body)
        codigo_parametro = data.get('parametro')
        valor = float(data.get('valor'))
        
        # Calcular score desde base de datos
        score = calcular_score_desde_bd(codigo_parametro, valor)
        
        return JsonResponse({
            'success': True,
            'score': score,
            'parametro': codigo_parametro,
            'valor': valor
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


def _obtener_estancia_activa_gineco(numero_documento):
    """
    Obtiene la estancia activa de Ginecobstetricia para un documento.
    Retorna None si no existe o si la consulta externa está deshabilitada.
    """
    from django.conf import settings
    if not getattr(settings, 'HABILITAR_BD_EXTERNA', True):
        return None
    try:
        estancia = (
            Hpnestanc.objects.using('readonly')
            .filter(
                ADNINGRES__GENPACIEN__PACNUMDOC=numero_documento,
                HESFECSAL__isnull=True,
            )
            .filter(
                Q(HPNDEFCAM__HPNSUBGRU__HSUNOMBRE__icontains='HOSPITALIZACION GINECOBSTETRICIA') |
                Q(HPNDEFCAM__HPNSUBGRU__HSUNOMBRE__icontains='CUIDADO INTERMEDIO GINECOBSTETRICI')
            )
            .select_related(
                'ADNINGRES__GENDETCON',
                'ADNINGRES__HPNDEFCAM',
                'HPNDEFCAM',
                'HPNDEFCAM__HPNSUBGRU',
            )
            .order_by('-HESFECING')
            .first()
        )
    except Exception:
        # Fuera de la red hospitalaria puede fallar; retornar None en silencio.
        return None

    if not estancia:
        return None

    cama_estancia = estancia.HPNDEFCAM.HCACODIGO if estancia.HPNDEFCAM else ''
    cama_ingreso = estancia.ADNINGRES.HPNDEFCAM.HCACODIGO if estancia.ADNINGRES and estancia.ADNINGRES.HPNDEFCAM else ''
    fecha_ingreso_dt = estancia.HESFECING or (estancia.ADNINGRES.AINFECING if estancia.ADNINGRES else None)
    aseguradora = estancia.ADNINGRES.GENDETCON.GDENOMBRE if estancia.ADNINGRES and estancia.ADNINGRES.GENDETCON else ''
    genpacien = estancia.ADNINGRES.GENPACIEN if estancia.ADNINGRES and estancia.ADNINGRES.GENPACIEN else None
    fecha_nacimiento_dt = genpacien.GPAFECNAC.date() if genpacien and genpacien.GPAFECNAC else None
    edad = None
    if fecha_nacimiento_dt:
        hoy = date.today()
        edad = hoy.year - fecha_nacimiento_dt.year - ((hoy.month, hoy.day) < (fecha_nacimiento_dt.month, fecha_nacimiento_dt.day))

    tipo_documento = None
    if genpacien:
        tipo_documento = {1: 'CC', 2: 'TI', 3: 'CE', 4: 'RC', 5: 'PA'}.get(genpacien.PACTIPDOC, 'CC')

    return {
        'cama': cama_estancia or cama_ingreso or '',
        'aseguradora': aseguradora or '',
        'fecha_ingreso_dt': fecha_ingreso_dt,
        'fecha_nacimiento_dt': fecha_nacimiento_dt,
        'edad': edad,
        'tipo_documento': tipo_documento,
    }


@login_required_if_enabled
@require_http_methods(["GET"])
def api_buscar_paciente(request):
    """
    API endpoint para buscar un paciente por número de documento.
    Retorna los datos del paciente en formato JSON.
    Si no existe localmente, busca en la base de datos externa (Genpacien).
    """
    numero_documento = request.GET.get('documento', '').strip()
    
    if not numero_documento:
        return JsonResponse({
            'success': False,
            'error': 'Número de documento requerido'
        }, status=400)

    # Buscar biometría (Firma y Huella independientes para asegurar visualización completa)
    # Buscamos por documento original y por documento sin ceros (lstrip) por si acaso
    documento_limpio = numero_documento.lstrip('0') or '0'
    IDs_busqueda = [numero_documento]
    if documento_limpio != numero_documento:
        IDs_busqueda.append(documento_limpio)
        
    # Intentar en FirmaPaciente (meows) - SOLAMENTE EN ESTE MÓDULO como solicitó el usuario
    huella_reciente = FirmaPaciente.objects.filter(paciente_id__in=IDs_busqueda).exclude(imagen_huella=None).exclude(imagen_huella='').order_by('-fecha').first()
    firma_reciente = FirmaPaciente.objects.filter(paciente_id__in=IDs_busqueda).exclude(imagen_firma=None).exclude(imagen_firma='').order_by('-fecha').first()
    
    import os
    
    huella_url = None
    if huella_reciente and huella_reciente.imagen_huella:
        try:
            if os.path.exists(huella_reciente.imagen_huella.path):
                huella_url = huella_reciente.imagen_huella.url
        except Exception:
            pass

    firma_url = None
    if firma_reciente and firma_reciente.imagen_firma:
        try:
            if os.path.exists(firma_reciente.imagen_firma.path):
                firma_url = firma_reciente.imagen_firma.url
        except Exception:
            pass
            
    biometria_data = {
        'imagen_huella': huella_url,
        'imagen_firma': firma_url,
    }

    try:
        # 1) PRIORIDAD: buscar localmente (clinico_meows), sin consultar externa.
        paciente = Paciente.objects.get(numero_documento=numero_documento)

        return JsonResponse({
            'success': True,
            'origen': 'local',
            'paciente': {
                'id': paciente.id,
                'nombre_completo': f"{paciente.nombres} {paciente.apellidos}".strip(),
                'numero_documento': paciente.numero_documento,
                'edad': paciente.edad if paciente.edad else None,
                'aseguradora': paciente.aseguradora if paciente.aseguradora else '',
                'cama': paciente.cama if paciente.cama else '',
                'fecha_ingreso': paciente.fecha_ingreso.strftime('%Y-%m-%d') if paciente.fecha_ingreso else '',
                'responsable': paciente.responsable if paciente.responsable else '',
                'tipo_documento': None,
                'nombres': paciente.nombres,
                'apellidos': paciente.apellidos,
                'sexo': paciente.sexo,
                'fecha_nacimiento': paciente.fecha_nacimiento.strftime('%Y-%m-%d') if paciente.fecha_nacimiento else '',
                'biometria': biometria_data,
            }
        }, json_dumps_params={'ensure_ascii': False})
        
    except Paciente.DoesNotExist:
        # 2) Solo si NO existe localmente, intentar externa (DGEMPRES).
        estancia_activa = _obtener_estancia_activa_gineco(numero_documento)
        if not estancia_activa:
            return JsonResponse({
                'success': False,
                'error': 'Paciente no encontrado localmente y no pertenece al área Hospitalización Ginecobstetricia'
            }, status=404)

        # 3. Intentar buscar en externa (Genpacien)
        try:
            paciente_temp = Paciente(numero_documento=numero_documento)
            paciente_temp.poblar_datos_basicos()
            
            if paciente_temp.nombres: # Si encontró datos
                return JsonResponse({
                    'success': True,
                    'origen': 'externo',
                    'paciente': {
                        'id': None, # No guardado aun
                        'nombre_completo': f"{paciente_temp.nombres} {paciente_temp.apellidos}".strip(),
                        'numero_documento': paciente_temp.numero_documento,
                        'edad': (estancia_activa['edad'] if estancia_activa and estancia_activa['edad'] is not None else paciente_temp.edad),
                        'aseguradora': (estancia_activa['aseguradora'] if estancia_activa else '') or paciente_temp.aseguradora,
                        'cama': (estancia_activa['cama'] if estancia_activa else '') or paciente_temp.cama,
                        'fecha_ingreso': (estancia_activa['fecha_ingreso_dt'].strftime('%Y-%m-%d') if estancia_activa and estancia_activa['fecha_ingreso_dt'] else ''),
                        'responsable': paciente_temp.responsable,
                        'tipo_documento': (estancia_activa['tipo_documento'] if estancia_activa and estancia_activa['tipo_documento'] else paciente_temp.tipo_documento),
                        'nombres': paciente_temp.nombres,
                        'apellidos': paciente_temp.apellidos,
                        'sexo': paciente_temp.sexo,
                        'fecha_nacimiento': (
                            estancia_activa['fecha_nacimiento_dt'].strftime('%Y-%m-%d')
                            if estancia_activa and estancia_activa['fecha_nacimiento_dt']
                            else (paciente_temp.fecha_nacimiento.strftime('%Y-%m-%d') if paciente_temp.fecha_nacimiento else '')
                        ),
                        'biometria': biometria_data,
                    }
                }, json_dumps_params={'ensure_ascii': False})
        except Exception:
            # Ignorar errores de conexión externa y continuar con fallback local.
            pass

        # 3. Fallback: Intentar búsqueda local más flexible (sin ceros iniciales, etc.)
        try:
            documento_limpio = numero_documento.lstrip('0') or '0'
            # Evitar buscar si es igual al original para no repetir
            if documento_limpio != numero_documento:
                paciente = Paciente.objects.filter(numero_documento__endswith=documento_limpio).first()
                
                if paciente:
                    return JsonResponse({
                        'success': True,
                        'origen': 'local_fuzzy',
                        'paciente': {
                            'id': paciente.id,
                            'nombre_completo': f"{paciente.nombres} {paciente.apellidos}".strip(),
                            'numero_documento': paciente.numero_documento,
                            'edad': paciente.edad if paciente.edad else None,
                            'aseguradora': paciente.aseguradora if paciente.aseguradora else '',
                            'cama': paciente.cama if paciente.cama else '',
                            'fecha_ingreso': paciente.fecha_ingreso.strftime('%Y-%m-%d') if paciente.fecha_ingreso else '',
                            'responsable': paciente.responsable if paciente.responsable else '',
                            'tipo_documento': None,
                            'nombres': paciente.nombres,
                            'apellidos': paciente.apellidos,
                            'sexo': paciente.sexo,
                            'fecha_nacimiento': paciente.fecha_nacimiento.strftime('%Y-%m-%d') if paciente.fecha_nacimiento else '',
                            'biometria': biometria_data,
                        }
                    }, json_dumps_params={'ensure_ascii': False})
        except Exception:
            pass
        
        return JsonResponse({
            'success': False,
            'error': 'Paciente no encontrado'
        }, status=404)

    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc() if settings.DEBUG else None
        }, status=500)


@login_required_if_enabled
@require_http_methods(["GET"])
def api_pacientes_activos(request):
    """
    Lista pacientes activas en áreas gineco-obstétricas (Ginecobstetricia,
    Sala de Partos, Cuidado Intermedio Ginecobstetricia, o cualquier ingreso
    marcado como gestante). Usa el motor único compartido con Trabajo de
    Parto y Frecuencia Fetal (frecuenciafetal.sala_partos_db) en vez de una
    consulta propia, para no duplicar la lógica de "pacientes activas".
    """
    if not getattr(settings, 'HABILITAR_BD_EXTERNA', True):
        return JsonResponse({
            'success': True,
            'count': 0,
            'pacientes': [],
            'message': 'Consulta externa desactivada por configuración.'
        })

    from frecuenciafetal.sala_partos_db import listar_pacientes_sala_partos

    limite = request.GET.get('limit', '50')
    try:
        limite = max(1, min(int(limite), 200))
    except ValueError:
        limite = 50

    try:
        activos = listar_pacientes_sala_partos(limit=limite)
        pacientes = [
            {
                'numero_documento': p['identificacion'],
                'nombre_completo': p['nombre_paciente'] or '',
                'aseguradora': p['aseguradora'] or '',
                'cama': p['numero_cama'] or '',
                'area': p['area'] or '',
                'fecha_ingreso': p['fecha_ingreso'].strftime('%Y-%m-%d %H:%M') if p['fecha_ingreso'] else '',
            }
            for p in activos
            if p['identificacion']
        ]
        return JsonResponse({
            'success': True,
            'count': len(pacientes),
            'pacientes': pacientes,
        }, json_dumps_params={'ensure_ascii': False})
    except Exception:
        return JsonResponse({
            'success': True,  # Cambiado a True para que el frontend no falle
            'count': 0,
            'pacientes': [],
            'message': 'No se pudo conectar con la base de datos externa en este momento.'
        })


@login_required_if_enabled
def historial_meows_paciente(request, paciente_id):
    """
    Vista para mostrar el historial de mediciones MEOWS de un paciente como
    una cuadrícula clínica: una fila por cada banda de valores posibles de
    cada parámetro (coloreada según el puntaje configurado en RangoParametro)
    y una columna por cada medición registrada, marcando la celda real de
    cada toma. Solo muestra las mediciones del paciente identificado por
    paciente_id.
    """
    paciente = get_object_or_404(Paciente, id=paciente_id)

    grid_parametros, columnas = construir_grid_meows(paciente)

    documento = request.GET.get("doc") or paciente.numero_documento
    atencion_id = request.GET.get("atencion")
    if not atencion_id and documento:
        # Si no viene por la URL, buscamos la atención activa más reciente de este paciente
        # para no perder el contexto (permite desplegar los módulos en el sidebar).
        atencion = AtencionParto.objects.filter(paciente=documento).order_by('-fecha_inicio').first()
        if atencion:
            atencion_id = atencion.id

    return render(request, "meows/historial.html", {
        "paciente": paciente,
        "grid_parametros": grid_parametros,
        "columnas": columnas,
        "atencion_id": atencion_id,
        "documento": documento,
    })


@login_required_if_enabled
def generar_pdf_meows_paciente(request, paciente_id):
    """
    Vista para generar el PDF MEOWS de un paciente con todas sus mediciones.
    Replica exactamente el formato físico del documento.
    """
    # Importación diferida para evitar errores al iniciar el servidor
    from meows.generador_pdf_meows import generar_pdf_meows
    
    paciente = get_object_or_404(Paciente, id=paciente_id)
    
    # Obtener todas las mediciones del paciente ordenadas por fecha (más antiguas primero)
    mediciones_qs = Medicion.objects.filter(
        paciente=paciente
    ).select_related('formulario').prefetch_related(
        'valores__parametro'
    ).order_by("fecha_hora")
    
    if not mediciones_qs.exists():
        messages.error(request, 'El paciente no tiene mediciones registradas para generar el PDF.')
        return redirect('historial_meows', paciente_id=paciente_id)
    
    # Materializar una sola vez para evitar reevaluaciones del queryset durante la generación.
    mediciones = list(mediciones_qs)

    # Generar el PDF
    # Generar el PDF
    return generar_pdf_meows(paciente, mediciones)


@login_required_if_enabled
@csrf_exempt
def guardar_huella(request):
    """
    Recibe la huella desde la App Android.
    """
    if request.method == "POST":
        try:
            # Intentar obtener datos de JSON (Android enviará JSON en el body)
            data = {}
            if request.body:
                data = json.loads(request.body)
            
            # --- TRASA SOLICITADA POR EL USUARIO ---
            print("\n" + "="*50)
            print(f"DATOS JSON RECIBIDOS: {list(data.keys())}")
            for key, value in data.items():
                length = len(str(value)) if value else 0
                print(f"Campo JSON: {key}, Longitud: {length}")
            
            # Mostrar si llegan archivos (multipart/form-data)
            archivos = list(request.FILES.keys())
            print(f"ARCHIVOS RECIBIDOS (FILES): {archivos}")
            print("="*50 + "\n")
            # --------------------------------------

            # Extraer campos del JSON
            paciente_id = data.get("paciente_id")
            formulario_id = data.get("formulario_id")
            template = data.get("template")
            
            # Soporte para ambas llaves: 'imagen' (web) o 'imagen_huella' (Android)
            imagen_b64 = data.get("imagen_huella") or data.get("imagen")
            firma_b64 = data.get("firma")
            usuario = data.get("usuario", "Sistema")
            
            print(f"DEBUG: paciente_id={paciente_id}, firma_b64_len={len(str(firma_b64)) if firma_b64 else 0}")

            if not paciente_id:
                return JsonResponse({"status": "error", "message": "paciente_id es requerido"}, status=400)

            # Crear o actualizar el registro biométrico (Module-specific logic)
            # Buscamos si ya existe para este paciente en este módulo para actualizarlo
            registro, created = FirmaPaciente.objects.update_or_create(
                paciente_id=str(paciente_id),
                defaults={
                    'formulario_id': str(formulario_id) if formulario_id else None,
                    'template_huella': template if template else "",
                    'usuario': str(usuario)
                }
            )

            # Decodificar y guardar la imagen de la huella
            if imagen_b64:
                try:
                    if ';base64,' in str(imagen_b64):
                        _, imgstr = str(imagen_b64).split(';base64,')
                    else:
                        imgstr = str(imagen_b64)
                    
                    archivo_huella = ContentFile(base64.b64decode(imgstr), name=f"huella_{paciente_id}.png")
                    # Para FileField/ImageField, el save() del campo ya hace el commit al modelo si save=True
                    registro.imagen_huella.save(f"huella_{paciente_id}.png", archivo_huella, save=True)
                except Exception as e_img:
                    print(f"Error procesando imagen_huella: {e_img}")
                    return JsonResponse({"status": "error", "message": f"Error en huella: {str(e_img)}"}, status=500)

            # Decodificar y guardar la imagen de la firma
            if firma_b64:
                try:
                    if ';base64,' in str(firma_b64):
                        _, imgstr = str(firma_b64).split(';base64,')
                    else:
                        imgstr = str(firma_b64)
                    
                    archivo_firma = ContentFile(base64.b64decode(imgstr), name=f"firma_{paciente_id}.png")
                    registro.imagen_firma.save(f"firma_{paciente_id}.png", archivo_firma, save=True)
                except Exception as e_sig:
                    print(f"Error procesando firma: {e_sig}")
                    return JsonResponse({"status": "error", "message": f"Error en firma: {str(e_sig)}"}, status=500)

            return JsonResponse({
                "status": "ok", 
                "message": "Datos biométricos guardados correctamente",
                "id": registro.id,
                "imagen_huella": registro.imagen_huella.url if registro.imagen_huella else None,
                "imagen_firma": registro.imagen_firma.url if registro.imagen_firma else None,
            })
            
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "JSON inválido"}, status=400)
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return JsonResponse({"status": "error", "message": str(e)}, status=500)
    
    return JsonResponse({"status": "error", "message": "Método no permitido"}, status=405)


@login_required_if_enabled
def ultima_huella(request, paciente_id):
    """
    Retorna la última huella capturada para un paciente (usado por el polling del frontend).
    """
    def _url_if_exists(field_file):
        if not field_file:
            return None
        try:
            # Evita devolver rutas rotas (archivo borrado o nombre legacy).
            if field_file.storage.exists(field_file.name):
                return field_file.url
        except Exception:
            return None
        return None

    huella_url = None
    huella_obj = None
    huella_qs = (
        FirmaPaciente.objects
        .filter(paciente_id=paciente_id)
        .exclude(imagen_huella=None)
        .exclude(imagen_huella='')
        .order_by('-fecha')
    )
    for obj in huella_qs:
        url = _url_if_exists(obj.imagen_huella)
        if url:
            huella_url = url
            huella_obj = obj
            break

    firma_url = None
    firma_obj = None
    firma_qs = (
        FirmaPaciente.objects
        .filter(paciente_id=paciente_id)
        .exclude(imagen_firma=None)
        .exclude(imagen_firma='')
        .order_by('-fecha')
    )
    for obj in firma_qs:
        url = _url_if_exists(obj.imagen_firma)
        if url:
            firma_url = url
            firma_obj = obj
            break

    if huella_url or firma_url:
        referencia = huella_obj or firma_obj
        return JsonResponse({
            "status": "ok",
            "paciente_id": paciente_id,
            "template": huella_obj.template_huella if huella_obj else "",
            "imagen_huella": huella_url,
            "imagen_firma": firma_url,
            "fecha": referencia.fecha.strftime('%Y-%m-%d %H:%M:%S') if referencia else None
        })
    return JsonResponse({"status": "error", "message": "No se encontró biometría válida"}, status=404)
