from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import IntegrityError
from django.db.models import Q
from django.contrib import messages
from django.conf import settings
from meows.models import Paciente, Formulario, Parametro, Medicion, MedicionValor, RangoParametro, Hpnestanc, Genpacien
from obstetriciaunificador.models import AtencionParto
from meows.services.meows import calcular_score_desde_bd
from meows.services.grid import construir_grid_meows
# Importación diferida del generador PDF para evitar errores de WeasyPrint al iniciar
# from meows.generador_pdf_meows import generar_pdf_meows
import json
from django.views.decorators.cache import never_cache
from datetime import date, datetime, timedelta
from django.utils import timezone
from django.utils.timesince import timesince
from sistema_obstetrico.auth_utils import login_required_if_enabled, nombre_profesional_sesion


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


# Si la última lectura automática de Dinámica es más vieja que esto, ya no se
# usa para prellenar una medición manual nueva (podría inducir a error), pero
# igual se muestra como referencia informativa. Ver crear_medicion_meows.
VENTANA_PRELLENADO_DINAMICA_HORAS = 6

# 2026-09-09: a pedido, Dinámica pasa a ser la ÚNICA fuente de mediciones
# MEOWS (todo llega por la sincronización automática) — ya no debe poder
# crearse ni corregirse una medición a mano desde la interfaz. Se bloquea
# aquí, en el punto de entrada único de ambas rutas ('crear_meows' y
# 'editar_meows'), en vez de borrar la vista: si algún día falla la
# sincronización con Dinámica y hace falta un respaldo manual temporal,
# basta con volver a poner esto en True — el resto del código ya está listo.
PERMITIR_CREACION_MANUAL_MEOWS = False


@never_cache
@login_required_if_enabled
def crear_medicion_meows(request, paciente_id=None, medicion_id=None):
    """
    Vista para crear una nueva medición MEOWS para un paciente, o para editar
    una medición ya guardada (cuando se llega con medicion_id, vía la URL
    'editar_meows') y así poder corregir un error humano sin crear un
    registro duplicado.

    Deshabilitada por defecto (ver PERMITIR_CREACION_MANUAL_MEOWS arriba):
    Dinámica es ahora la única fuente de mediciones.
    """
    if not PERMITIR_CREACION_MANUAL_MEOWS:
        messages.info(
            request,
            "El registro manual de MEOWS está deshabilitado: todas las mediciones "
            "se sincronizan automáticamente desde Dinámica.",
        )
        # Ruta literal (no reverse por nombre): 'meows.urls' está incluido dos
        # veces en el proyecto (/meows/... y /fetal/meows/..., mismo nombre de
        # URL en ambos) y reverse() puede devolver cualquiera de los dos. Con
        # la ruta fija, el redirect siempre cae en el prefijo canónico.
        if medicion_id:
            return redirect(f"/meows/resultado/{medicion_id}/")
        return redirect(f"/meows/historial/{paciente_id}/")

    atencion_id = request.GET.get("atencion")

    medicion_editar = None
    if medicion_id:
        medicion_editar = get_object_or_404(Medicion, id=medicion_id)
        paciente = medicion_editar.paciente
    else:
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

    # En modo edición, prellenar cada parámetro con su valor ya guardado
    # (usado por formulario.html vía parametro.valor_actual) para poder
    # revisarlo y corregirlo en vez de reingresarlo todo desde cero.
    ultima_lectura_dinamica = None
    if medicion_editar:
        valores_existentes = {
            v.parametro_id: v.valor
            for v in medicion_editar.valores.all()
        }
        for p in parametros:
            p.valor_actual = valores_existentes.get(p.id, '')
    else:
        for p in parametros:
            p.valor_actual = ''

        # Medición nueva (no edición): si esta paciente ya tiene lecturas
        # automáticas de Dinámica, se usan para prellenar las cards en vez de
        # dejarlas en blanco — el personal revisa/ajusta en vez de digitar
        # todo desde cero — y se muestra un aviso con la antigüedad del dato,
        # así se sabe si vale la pena esperar el próximo ciclo automático en
        # vez de registrar manual. Ver conversación sobre "activar" estas
        # cards en vez de dejarlas huérfanas del flujo de Dinámica.
        ultima_medicion_dinamica = (
            Medicion.objects.filter(paciente=paciente, origen='dinamica')
            .order_by('-fecha_hora')
            .first()
        )
        if ultima_medicion_dinamica:
            valores_dinamica = {
                v.parametro_id: v.valor
                for v in ultima_medicion_dinamica.valores.all()
            }
            antiguedad = timezone.now() - ultima_medicion_dinamica.fecha_hora
            es_reciente = antiguedad <= timedelta(hours=VENTANA_PRELLENADO_DINAMICA_HORAS)

            if es_reciente:
                for p in parametros:
                    if p.id in valores_dinamica:
                        p.valor_actual = valores_dinamica[p.id]

            ultima_lectura_dinamica = {
                "fecha_hora": ultima_medicion_dinamica.fecha_hora,
                "hace": timesince(ultima_medicion_dinamica.fecha_hora),
                "es_reciente": es_reciente,
                "riesgo": ultima_medicion_dinamica.meows_riesgo,
                "valores": [
                    {
                        "codigo": p.codigo,
                        "nombre": p.nombre,
                        "unidad": p.unidad,
                        "valor": valores_dinamica[p.id],
                    }
                    for p in parametros if p.id in valores_dinamica
                ],
                # Códigos que trae la lectura de Dinámica, para resaltar en la
                # grilla de cards de abajo cuáles corresponden a este dato
                # (sin importar si alcanzó a precargarse o no).
                "codigos": [p.codigo for p in parametros if p.id in valores_dinamica],
            }

    if request.method == "POST":
        atencion_id = (request.POST.get("atencion") or request.GET.get("atencion") or "").strip()
        # Obtener el número de documento del formulario
        nuevo_numero_doc = request.POST.get('numero_documento', '').strip()
        if not nuevo_numero_doc:
            messages.error(request, 'El número de documento es requerido.')
            return render(request, "meows/formulario.html", {
                "paciente": paciente,
                "parametros": parametros,
                "medicion": medicion_editar,
            })

        # Fecha y hora del monitoreo (registro manual).
        fecha_monitoreo_str = request.POST.get('fecha_monitoreo', '').strip()
        hora_monitoreo_str = request.POST.get('hora_monitoreo', '').strip()

        if not fecha_monitoreo_str or not hora_monitoreo_str:
            messages.error(request, 'La fecha y hora del monitoreo son requeridas.')
            return render(request, "meows/formulario.html", {
                "paciente": paciente,
                "parametros": parametros,
                "medicion": medicion_editar,
            })

        try:
            fecha_hora_monitoreo_naive = datetime.strptime(
                f"{fecha_monitoreo_str} {hora_monitoreo_str}", "%Y-%m-%d %H:%M"
            )
        except ValueError:
            messages.error(request, 'La fecha u hora del monitoreo no tienen un formato válido.')
            return render(request, "meows/formulario.html", {
                "paciente": paciente,
                "parametros": parametros,
                "medicion": medicion_editar,
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
                "parametros": parametros,
                "medicion": medicion_editar,
            })

        atencion = None
        if atencion_id:
            try:
                atencion = AtencionParto.objects.get(id=atencion_id)
            except Exception:
                atencion = None

        from meows.services.meows import calcular_meows

        # Se junta primero el diccionario {codigo: valor} desde el POST, SIN
        # tocar la base de datos todavía, para poder calcular_meows() antes de
        # crear/actualizar cada MedicionValor — así cada uno se guarda ya con
        # su propio puntaje individual (antes se guardaba solo el total en
        # Medicion, dejando MedicionValor.puntaje siempre en NULL y la columna
        # "Puntaje"/"Estado" de la vista de resultado siempre en "-").
        valores_dict = {}
        for parametro in parametros:
            valor = request.POST.get(parametro.codigo)
            if valor:
                valores_dict[parametro.codigo] = valor

        resultados_meows = calcular_meows(valores_dict)
        puntajes_por_codigo = resultados_meows["puntajes"]

        if medicion_editar:
            # Editar: se corrige el mismo registro (no se crea uno nuevo).
            medicion = medicion_editar
            medicion.paciente = paciente
            medicion.atencion = atencion
            medicion.fecha_hora = fecha_hora_monitoreo
            medicion.save()

            codigos_enviados = []
            for parametro in parametros:
                valor = valores_dict.get(parametro.codigo)
                if valor:
                    MedicionValor.objects.update_or_create(
                        medicion=medicion,
                        parametro=parametro,
                        defaults={
                            "valor": valor,
                            "puntaje": puntajes_por_codigo.get(parametro.codigo),
                        },
                    )
                    codigos_enviados.append(parametro.id)
            # Si un parámetro que antes tenía valor se dejó en blanco al
            # corregir, se elimina su valor anterior en vez de dejarlo obsoleto.
            medicion.valores.exclude(parametro_id__in=codigos_enviados).delete()
        else:
            # Crear la medición
            medicion = Medicion.objects.create(
                paciente=paciente,
                formulario=formulario,
                atencion=atencion,
                fecha_hora=fecha_hora_monitoreo,
            )

            # Crear los valores de medición, cada uno con su puntaje individual
            for parametro in parametros:
                valor = valores_dict.get(parametro.codigo)
                if valor:
                    MedicionValor.objects.create(
                        medicion=medicion,
                        parametro=parametro,
                        valor=valor,
                        puntaje=puntajes_por_codigo.get(parametro.codigo),
                    )

        # meows_total, meows_riesgo y meows_mensaje ya vienen de resultados_meows,
        # calculado arriba antes de guardar los MedicionValor.
        medicion.meows_total = resultados_meows["meows_total"]
        medicion.meows_riesgo = resultados_meows["meows_riesgo"]
        medicion.meows_mensaje = resultados_meows["meows_mensaje"]
        # Notifica en el sidebar (toast + sonido) igual que las mediciones
        # importadas de Dinámica: solo Amarillo/Rojo interrumpen con alerta,
        # a pedido de enfermería (2026-09-09) — ver la misma regla en
        # sincronizar_signos_vitales_dinamica.py:disparar_alerta().
        campos_a_guardar = ["meows_total", "meows_riesgo", "meows_mensaje"]
        if resultados_meows["meows_riesgo"] in ("AMARILLO", "ROJO"):
            medicion.alerta_pendiente = True
            medicion.alerta_generada_en = timezone.now()
            campos_a_guardar += ["alerta_pendiente", "alerta_generada_en"]
        medicion.save(update_fields=campos_a_guardar)

        if medicion_editar:
            # Al corregir un registro existente, volver a su detalle para
            # confirmar visualmente el valor ya corregido.
            messages.success(request, 'Registro MEOWS actualizado exitosamente.')
            return redirect("ver_meows", medicion_id=medicion.id)

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
        "medicion": medicion_editar,
        "ultima_lectura_dinamica": ultima_lectura_dinamica,
        "atencion_id": request.GET.get("atencion") or (medicion_editar.atencion_id if medicion_editar else None),
        "documento": request.GET.get("doc") or paciente.numero_documento,
        "profesional_nombre_sesion": nombre_profesional_sesion(request),
    })


# ============================================================================
# TRIAJE: registro manual de signos vitales ANTES del ingreso en Dinámica
# ============================================================================
# 2026-09-18: en triaje se toman signos vitales de gestantes que todavía NO
# tienen ingreso formal (sin Adningreso no existe Hcnfolio, así que Dinámica
# no tiene nada que sincronizar). Este flujo es DELIBERADAMENTE independiente
# de PERMITIR_CREACION_MANUAL_MEOWS / crear_medicion_meows -- ese flag sigue
# protegiendo el registro de Dinámica exactamente como hoy, sin cambios. Las
# mediciones de triaje se guardan con origen='triaje' (nunca 'manual' ni
# 'dinamica') y solo se ofrecen mientras la paciente no tenga estancia activa
# en Nexus -- en cuanto Dinámica la recibe, este flujo deja de aplicarle (ver
# _obtener_estancia_activa_gineco más abajo, reutilizada sin cambios).

def _buscar_prefill_triaje(numero_documento):
    """
    Busca datos de una paciente para prellenar un registro de triaje, SIN
    exigir ingreso/estancia activa (a diferencia de api_buscar_paciente, que
    está pensado para pacientes ya admitidas). Prioridad:
      1) meows.Paciente local -- ya la vimos antes, en cualquier contexto.
      2) Genpacien (Nexus) por documento -- registrada en el hospital aunque
         nunca haya tenido una atención clínica formal (ej. segundo embarazo,
         ya existe desde una atención anterior).
    Devuelve un dict con lo encontrado, o None si no hay nada en ningún lado
    (paciente nueva de verdad: todo se digita a mano).
    """
    numero_documento = (numero_documento or '').strip()
    if not numero_documento:
        return None

    paciente_local = Paciente.objects.filter(numero_documento=numero_documento).first()
    if paciente_local:
        return {
            'origen': 'local',
            'paciente_id': paciente_local.id,
            'nombres': paciente_local.nombres,
            'apellidos': paciente_local.apellidos,
            'sexo': paciente_local.sexo,
            'fecha_nacimiento': paciente_local.fecha_nacimiento,
        }

    if not getattr(settings, 'HABILITAR_BD_EXTERNA', True):
        return None

    try:
        ext = Genpacien.objects.using('readonly').filter(PACNUMDOC=numero_documento).first()
    except Exception:
        ext = None

    if not ext:
        return None

    seg_nom = f" {ext.PACSEGNOM}" if ext.PACSEGNOM else ""
    seg_ape = f" {ext.PACSEGAPE}" if ext.PACSEGAPE else ""
    return {
        'origen': 'nexus',
        'paciente_id': None,
        'nombres': f"{ext.PACPRINOM}{seg_nom}".strip(),
        'apellidos': f"{ext.PACPRIAPE}{seg_ape}".strip(),
        'sexo': 'M' if ext.GPASEXPAC == 1 else ('F' if ext.GPASEXPAC == 2 else ''),
        'fecha_nacimiento': ext.GPAFECNAC.date() if ext.GPAFECNAC else None,
    }


@login_required_if_enabled
@require_http_methods(["GET"])
def api_buscar_paciente_triaje(request):
    """
    Búsqueda de paciente para iniciar un registro de TRIAJE: a diferencia de
    api_buscar_paciente (que exige ingreso/estancia activa), esta es
    justamente para la paciente que todavía no lo tiene. Revisa local
    (meows.Paciente) y luego Nexus (Genpacien) directo por documento, sin
    pasar por _obtener_estancia_activa_gineco.
    """
    numero_documento = request.GET.get('documento', '').strip()
    if not numero_documento:
        return JsonResponse({'success': False, 'error': 'Número de documento requerido'}, status=400)

    datos = _buscar_prefill_triaje(numero_documento)
    if not datos:
        return JsonResponse({'success': True, 'encontrado': False})

    return JsonResponse({
        'success': True,
        'encontrado': True,
        'origen': datos['origen'],
        'paciente': {
            'id': datos['paciente_id'],
            'nombres': datos['nombres'],
            'apellidos': datos['apellidos'],
            'sexo': datos['sexo'],
            'fecha_nacimiento': datos['fecha_nacimiento'].strftime('%Y-%m-%d') if datos['fecha_nacimiento'] else '',
        },
    }, json_dumps_params={'ensure_ascii': False})


@login_required_if_enabled
def abrir_triaje(request, doc=None):
    """
    Punto de entrada para iniciar (o continuar) un registro de triaje: dado
    un documento, resuelve o crea el Paciente local (prellenado desde Nexus
    si existe) y redirige al formulario de captura de triaje. Espejo de
    abrir_meows_desde_atencion, pero sin depender de que exista ingreso.
    """
    documento = (doc or request.GET.get("doc") or "").strip()
    if not documento:
        return redirect("/")

    if _obtener_estancia_activa_gineco(documento):
        # Ya tiene ingreso activo: Dinámica la cubre, no se abre triaje para
        # no competir con esa fuente.
        messages.info(request, "Esta paciente ya tiene ingreso activo: sus mediciones se registran desde Dinámica.")
        return redirect(f"/meows/crear/{documento}/")

    paciente = Paciente.objects.filter(numero_documento=documento).first()
    if not paciente:
        datos = _buscar_prefill_triaje(documento)
        if datos and datos['origen'] == 'nexus':
            paciente = Paciente.objects.create(
                numero_documento=documento,
                nombres=datos['nombres'] or 'N/A',
                apellidos=datos['apellidos'] or 'N/A',
                sexo=datos['sexo'] or 'F',
                fecha_nacimiento=datos['fecha_nacimiento'],
            )
        else:
            paciente = Paciente.objects.create(
                numero_documento=documento,
                nombres="N/A",
                apellidos="N/A",
                sexo="F",
            )

    return redirect(f"/meows/triaje/nuevo/{paciente.id}/")


@never_cache
@login_required_if_enabled
def crear_medicion_triaje(request, paciente_id=None, medicion_id=None):
    """
    Captura de signos vitales de TRIAJE (antes del ingreso). Misma lógica de
    captura y cálculo de score que crear_medicion_meows (reutiliza
    calcular_meows tal cual, mismo Formulario "MEOWS"), pero guarda siempre
    con origen='triaje' y NUNCA depende de PERMITIR_CREACION_MANUAL_MEOWS --
    ese flag sigue protegiendo exclusivamente el flujo de Dinámica.
    """
    medicion_editar = None
    if medicion_id:
        medicion_editar = get_object_or_404(Medicion, id=medicion_id, origen='triaje')
        paciente = medicion_editar.paciente
    else:
        paciente = get_object_or_404(Paciente, id=paciente_id)

    if _obtener_estancia_activa_gineco(paciente.numero_documento):
        messages.info(request, "Esta paciente ya tiene ingreso activo: sus mediciones se registran desde Dinámica.")
        return redirect(f"/meows/historial/{paciente.id}/")

    formulario, _ = Formulario.objects.get_or_create(
        codigo="MEOWS",
        defaults={
            'nombre': 'Sistema de Alerta Temprana Obstétrico',
            'version': '1.0',
            'activo': True,
        }
    )
    parametros = Parametro.objects.filter(activo=True).order_by("orden")

    if medicion_editar:
        valores_existentes = {v.parametro_id: v.valor for v in medicion_editar.valores.all()}
        for p in parametros:
            p.valor_actual = valores_existentes.get(p.id, '')
    else:
        for p in parametros:
            p.valor_actual = ''

    if request.method == "POST":
        nuevo_numero_doc = request.POST.get('numero_documento', '').strip()
        if not nuevo_numero_doc:
            messages.error(request, 'El número de documento es requerido.')
            return render(request, "meows/formulario_triaje.html", {
                "paciente": paciente, "parametros": parametros, "medicion": medicion_editar,
            })

        fecha_monitoreo_str = request.POST.get('fecha_monitoreo', '').strip()
        hora_monitoreo_str = request.POST.get('hora_monitoreo', '').strip()
        if not fecha_monitoreo_str or not hora_monitoreo_str:
            messages.error(request, 'La fecha y hora del monitoreo son requeridas.')
            return render(request, "meows/formulario_triaje.html", {
                "paciente": paciente, "parametros": parametros, "medicion": medicion_editar,
            })
        try:
            fecha_hora_monitoreo_naive = datetime.strptime(
                f"{fecha_monitoreo_str} {hora_monitoreo_str}", "%Y-%m-%d %H:%M"
            )
        except ValueError:
            messages.error(request, 'La fecha u hora del monitoreo no tienen un formato válido.')
            return render(request, "meows/formulario_triaje.html", {
                "paciente": paciente, "parametros": parametros, "medicion": medicion_editar,
            })
        fecha_hora_monitoreo = timezone.make_aware(fecha_hora_monitoreo_naive, timezone.get_current_timezone())

        nombre_completo = request.POST.get('nombre_completo', '').strip()
        if nombre_completo:
            partes = nombre_completo.split(maxsplit=1)
            nombres_nuevo = partes[0] if len(partes) >= 1 else ''
            apellidos_nuevo = partes[1] if len(partes) >= 2 else ''
        else:
            nombres_nuevo = request.POST.get('nombres', '')
            apellidos_nuevo = request.POST.get('apellidos', '')

        paciente_existente = Paciente.objects.filter(numero_documento=nuevo_numero_doc).first()
        if paciente_existente:
            paciente = paciente_existente
            if nombre_completo:
                paciente.nombres = nombres_nuevo
                paciente.apellidos = apellidos_nuevo
        else:
            paciente = Paciente.objects.create(
                numero_documento=nuevo_numero_doc,
                nombres=nombres_nuevo or 'N/A',
                apellidos=apellidos_nuevo or 'N/A',
                sexo='F',
            )

        fecha_nacimiento = request.POST.get('fecha_nacimiento')
        if fecha_nacimiento:
            paciente.fecha_nacimiento = fecha_nacimiento
        if request.POST.get('responsable'):
            paciente.responsable = request.POST.get('responsable')
        # 2026-09-23: la tarjeta de Triaje ahora también pide aseguradora y
        # fecha de ingreso (llegada de la paciente).
        if 'aseguradora' in request.POST:
            paciente.aseguradora = (request.POST.get('aseguradora') or '').strip()[:200]
        fecha_ingreso = (request.POST.get('fecha_ingreso') or '').strip()
        if fecha_ingreso:
            try:
                paciente.fecha_ingreso = datetime.strptime(fecha_ingreso, "%Y-%m-%d").date()
            except ValueError:
                pass
        try:
            paciente.save()
        except IntegrityError:
            messages.error(request, 'Error al guardar los datos del paciente. El número de documento ya existe.')
            return render(request, "meows/formulario_triaje.html", {
                "paciente": paciente, "parametros": parametros, "medicion": medicion_editar,
            })

        from meows.services.meows import calcular_meows
        valores_dict = {}
        for parametro in parametros:
            valor = request.POST.get(parametro.codigo)
            if valor:
                valores_dict[parametro.codigo] = valor
        resultados_meows = calcular_meows(valores_dict)
        puntajes_por_codigo = resultados_meows["puntajes"]

        if medicion_editar:
            medicion = medicion_editar
            medicion.paciente = paciente
            medicion.fecha_hora = fecha_hora_monitoreo
            medicion.save()
            codigos_enviados = []
            for parametro in parametros:
                valor = valores_dict.get(parametro.codigo)
                if valor:
                    MedicionValor.objects.update_or_create(
                        medicion=medicion, parametro=parametro,
                        defaults={"valor": valor, "puntaje": puntajes_por_codigo.get(parametro.codigo)},
                    )
                    codigos_enviados.append(parametro.id)
            medicion.valores.exclude(parametro_id__in=codigos_enviados).delete()
        else:
            medicion = Medicion.objects.create(
                paciente=paciente, formulario=formulario, atencion=None,
                fecha_hora=fecha_hora_monitoreo, origen='triaje',
                registrado_por=(nombre_profesional_sesion(request) or '')[:255] or None,
            )
            for parametro in parametros:
                valor = valores_dict.get(parametro.codigo)
                if valor:
                    MedicionValor.objects.create(
                        medicion=medicion, parametro=parametro, valor=valor,
                        puntaje=puntajes_por_codigo.get(parametro.codigo),
                    )

        medicion.meows_total = resultados_meows["meows_total"]
        medicion.meows_riesgo = resultados_meows["meows_riesgo"]
        medicion.meows_mensaje = resultados_meows["meows_mensaje"]
        campos_a_guardar = ["meows_total", "meows_riesgo", "meows_mensaje"]
        if resultados_meows["meows_riesgo"] in ("AMARILLO", "ROJO"):
            medicion.alerta_pendiente = True
            medicion.alerta_generada_en = timezone.now()
            campos_a_guardar += ["alerta_pendiente", "alerta_generada_en"]
        medicion.save(update_fields=campos_a_guardar)

        if medicion_editar:
            messages.success(request, 'Registro de triaje actualizado exitosamente.')
            return redirect("ver_meows", medicion_id=medicion.id)

        messages.success(request, 'Registro de triaje guardado exitosamente.')
        return redirect(f"/meows/triaje/nuevo/{paciente.id}/")

    # 2026-09-23: si la paciente no tiene aseguradora registrada aquí pero ya
    # estuvo antes en el hospital, se sugiere la de su último ingreso en
    # Dinámica (se guarda al registrar el triaje). Si no hay registros, el
    # campo queda vacío para digitarlo a mano.
    aseguradora_dinamica = None
    if not (paciente.aseguradora or '').strip() and getattr(settings, 'HABILITAR_BD_EXTERNA', True):
        from frecuenciafetal.sala_partos_db import consultar_aseguradora_paciente
        aseguradora_dinamica = consultar_aseguradora_paciente(paciente.numero_documento)

    return render(request, "meows/formulario_triaje.html", {
        "paciente": paciente,
        "parametros": parametros,
        "medicion": medicion_editar,
        "documento": paciente.numero_documento,
        "profesional_nombre_sesion": nombre_profesional_sesion(request),
        "aseguradora_dinamica": aseguradora_dinamica,
    })


@login_required_if_enabled
@require_http_methods(["GET"])
def api_pacientes_triaje(request):
    """
    Lista pacientes con un registro de TRIAJE abierto: tienen al menos una
    Medicion(origen='triaje') y AHORA MISMO no tienen estancia activa en
    Nexus. En cuanto Dinámica las recibe (ingreso real), dejan de aparecer
    aquí solas -- no hace falta "cerrar" el triaje a mano; su historial de
    triaje queda de todos modos en su línea de tiempo MEOWS.
    """
    pacientes_ids = (
        Medicion.objects.filter(origen='triaje')
        .values_list('paciente_id', flat=True)
        .distinct()
    )
    pacientes = Paciente.objects.filter(id__in=pacientes_ids)

    resultado = []
    for p in pacientes:
        if _obtener_estancia_activa_gineco(p.numero_documento):
            continue
        ultima = (
            Medicion.objects.filter(paciente=p, origen='triaje')
            .order_by('-fecha_hora')
            .first()
        )
        resultado.append({
            'paciente_id': p.id,
            'numero_documento': p.numero_documento,
            'nombre_completo': f"{p.nombres} {p.apellidos}".strip(),
            'ultima_medicion': ultima.fecha_hora.isoformat() if ultima else None,
            'ultimo_riesgo': ultima.meows_riesgo if ultima else None,
            'url_continuar': f"/meows/triaje/nuevo/{p.id}/",
            'url_historial': f"/meows/historial/{p.id}/",
        })

    resultado.sort(key=lambda r: r['ultima_medicion'] or '', reverse=True)
    return JsonResponse(
        {'success': True, 'count': len(resultado), 'pacientes': resultado},
        json_dumps_params={'ensure_ascii': False},
    )


@login_required_if_enabled
@require_http_methods(["GET"])
def api_alertas_pendientes_triaje(request):
    """
    Espejo de api_alertas_pendientes, pero SOLO para mediciones de triaje
    (origen='triaje') -- campana separada, nunca se mezcla con la de
    Dinámica. Ver iniciarSondeoAlertasMeows en sidebar.html (se invoca dos
    veces, una por cada campana, mismo mecanismo, distinto endpoint).
    """
    ventana_desde = timezone.now() - timedelta(minutes=VENTANA_ALERTA_MINUTOS)
    pendientes = list(
        Medicion.objects.filter(
            origen='triaje',
            alerta_pendiente=True,
            alerta_generada_en__gte=ventana_desde,
        )
        .select_related('paciente')
        .order_by('-fecha_hora')[:20]
    )
    alertas = [
        {
            'medicion_id': m.id,
            'paciente': f"{m.paciente.nombres} {m.paciente.apellidos}".strip(),
            'numero_documento': m.paciente.numero_documento,
            'riesgo': m.meows_riesgo,
            'mensaje': m.meows_mensaje,
            'fecha_hora': timezone.localtime(m.fecha_hora).strftime('%d/%m/%Y %I:%M %p'),
            'fecha_hora_iso': m.fecha_hora.isoformat(),
            'url': f"/meows/resultado/{m.id}/",
        }
        for m in pendientes
    ]
    return JsonResponse({'alertas': alertas}, json_dumps_params={'ensure_ascii': False})


@never_cache
@login_required_if_enabled
def ver_meows(request, medicion_id):
    """
    Vista para mostrar el resultado de una medición MEOWS.
    """
    medicion = get_object_or_404(Medicion, id=medicion_id)

    # Ver el detalle de la alerta la da por atendida para TODOS los equipos/
    # usuarios, no solo para quien la abrió (antes esto solo se recordaba en
    # el sessionStorage del navegador que la abría, así que la misma alerta
    # reaparecía como nueva en cualquier otra pestaña o PC). Al apagar
    # alerta_pendiente aquí, api_alertas_pendientes deja de devolverla para
    # cualquiera desde el siguiente sondeo.
    if medicion.alerta_pendiente:
        medicion.alerta_pendiente = False
        medicion.alerta_vista_en = timezone.now()
        medicion.alerta_vista_por = request.user if request.user.is_authenticated else None
        medicion.save(update_fields=["alerta_pendiente", "alerta_vista_en", "alerta_vista_por"])

    # 2026-09-09: antes solo se listaban los MedicionValor que YA existían
    # para esta medición — si Dinámica no trajo, por ejemplo, Frecuencia
    # Cardíaca Fetal o Nivel de Conciencia en esa toma puntual, la card de ese
    # parámetro simplemente no aparecía (parecía que ni existiera en el
    # sistema). Ahora se recorren TODOS los parámetros activos y, al que le
    # falte valor, se le arma una card vacía ("Sin registrar") en vez de
    # omitirla — igual de completo que la Línea de Tiempo Clínica, que sí
    # muestra las 8 columnas siempre.
    valores_guardados = {
        v.parametro_id: v
        for v in medicion.valores.select_related("parametro")
    }
    valores = [
        valores_guardados.get(parametro.id)
        or MedicionValor(medicion=medicion, parametro=parametro, valor="", puntaje=None)
        for parametro in Parametro.objects.filter(activo=True).order_by("orden")
    ]

    # 2026-09-23: número de ingreso para la tarjeta "Información del Paciente"
    # (el de la atención de la medición, o el ingreso actual en Dinámica).
    numero_ingreso = ''
    if medicion.atencion_id and medicion.atencion.numero_ingreso:
        numero_ingreso = medicion.atencion.numero_ingreso
    else:
        try:
            from obstetriciaunificador.repositorio import resolver_atencion_ingreso
            atencion_ingreso, _ = resolver_atencion_ingreso(medicion.paciente.numero_documento, crear=False)
            if atencion_ingreso is not None:
                numero_ingreso = atencion_ingreso.numero_ingreso
        except Exception:
            pass  # Dinámica no disponible: la tarjeta muestra "—"

    return render(request, "meows/resultado.html", {
        "medicion": medicion,
        "valores": valores,
        "atencion_id": medicion.atencion_id,
        "documento": medicion.paciente.numero_documento,
        "numero_ingreso": numero_ingreso,
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

    # 2026-09-14: se eliminó la captura de firma/huella biométrica (a pedido
    # explícito, antes de salir a producción -- ver meows.models sin
    # FirmaPaciente). Se deja la clave 'biometria' en null por compatibilidad
    # con cualquier consumidor que todavía la lea, en vez de quitarla y
    # arriesgar un KeyError en el frontend.
    biometria_data = {
        'imagen_huella': None,
        'imagen_firma': None,
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


# Cuánto tiempo se sigue avisando una alerta a cualquier pantalla que sondee,
# desde que se disparó. No se "consume" al primero que pregunta (antes sí, y
# solo esa pantalla la veía) — ahora la ven todas las pantallas abiertas
# mientras estén dentro de esta ventana; pasado ese tiempo deja de aparecer
# como toast, pero el dato/riesgo sigue visible siempre en el historial.
#
# Antes en 10 minutos — subido a 24 horas (2026-09-07) tras confirmar un caso
# real: la tarea programada generó una alerta mientras el servidor local
# (runserver) estaba caído; para cuando alguien volvió a abrir el navegador
# ya habían pasado más de 10 minutos y la alerta nunca llegó a sonar/mostrarse,
# aunque el registro sí quedó guardado correctamente. El registro NUNCA se
# pierde (eso no depende de esta ventana, ver sincronizar_signos_vitales_
# dinamica.py), pero el aviso en vivo si no se atrapa a tiempo. Con 24h,
# cualquier corte razonable del servidor (una noche, un reinicio) sigue
# alcanzando a notificar apenas alguien vuelva a abrir una pantalla.
VENTANA_ALERTA_MINUTOS = 60 * 24


@login_required_if_enabled
@require_http_methods(["GET"])
def api_alertas_pendientes(request):
    """
    Sondeada periódicamente por el widget de alertas del sidebar (ver
    obstetricia/sidebar.html), en TODAS las pantallas abiertas. Devuelve las
    mediciones importadas de Dinámica con riesgo alto/intermedio disparadas
    en los últimos VENTANA_ALERTA_MINUTOS minutos — no se marcan como
    "entregadas" aquí; la deduplicación para no repetir el mismo sonido una
    y otra vez en la misma pantalla la hace el JS del cliente (recuerda qué
    IDs ya mostró, ver sidebar.html).
    """
    # BUG real encontrado 2026-09-08: esto ordenaba ASCENDENTE y cortaba a
    # 20 -> siempre devolvía las 20 alertas MÁS VIEJAS de la ventana, nunca
    # las recientes. Con cualquier atraso (p.ej. la tarea programada caída
    # un rato, o una tanda grande de Dinámica) las alertas nuevas —hasta una
    # ROJA real— quedaban enterradas y JAMÁS llegaban a mostrarse. Se
    # invierte a descendente para quedarnos con las 20 MÁS RECIENTES.
    ventana_desde = timezone.now() - timedelta(minutes=VENTANA_ALERTA_MINUTOS)
    pendientes = list(
        Medicion.objects.filter(
            # 2026-09-18: filtro explícito agregado al crear el origen
            # 'triaje' -- antes esto era un no-op (nada más que 'dinamica'
            # podía generar estas alertas). Sin este filtro, las alertas de
            # triaje se mezclarían aquí; tienen su propia campana separada,
            # ver api_alertas_pendientes_triaje.
            origen='dinamica',
            alerta_pendiente=True,
            alerta_generada_en__gte=ventana_desde,
        )
        .select_related('paciente')
        .order_by('-fecha_hora')[:20]
    )

    alertas = [
        {
            'medicion_id': m.id,
            'paciente': f"{m.paciente.nombres} {m.paciente.apellidos}".strip(),
            'numero_documento': m.paciente.numero_documento,
            'riesgo': m.meows_riesgo,
            'mensaje': m.meows_mensaje,
            'fecha_hora': timezone.localtime(m.fecha_hora).strftime('%d/%m/%Y %I:%M %p'),
            # Timestamp ISO además del texto ya formateado: el cliente lo usa
            # para ordenar el panel por hora REAL de la medición (más reciente
            # arriba), sin depender del orden en que cada tanda fue llegando —
            # ver agregarAlPanel/ordenarPanelPorFecha en obstetricia/sidebar.html.
            'fecha_hora_iso': m.fecha_hora.isoformat(),
            'url': f"/meows/resultado/{m.id}/",
        }
        for m in pendientes
    ]
    return JsonResponse({'alertas': alertas}, json_dumps_params={'ensure_ascii': False})


# Ventana de "corrección reciente" -- deliberadamente más corta que
# VENTANA_ALERTA_MINUTOS (24h): esto es solo para refrescar sola una
# pantalla que alguien tenga abierta AHORA MISMO, no un histórico a
# consultar después -- no tiene sentido recargar una pantalla por una
# corrección de hace varias horas.
VENTANA_CORRECCION_MINUTOS = 30


@login_required_if_enabled
@require_http_methods(["GET"])
def api_correcciones_recientes(request):
    """
    Señal SEPARADA de api_alertas_pendientes: mientras esa solo avisa de
    riesgo Amarillo/Rojo (para sonar la campana), esta avisa de CUALQUIER
    corrección de un valor ya sincronizado desde Dinámica (ver
    sincronizar_signos_vitales_dinamica.py, Medicion.ultima_correccion_en),
    sin importar el riesgo -- para que la Línea de Tiempo Clínica de esa
    paciente, si alguien la tiene abierta, se refresque sola y muestre el
    dato corregido. Sondeada desde obstetricia/sidebar.html, sin sonido ni
    aviso emergente (a diferencia de las alertas) -- es un refresco
    silencioso, no una notificación.
    """
    ventana_desde = timezone.now() - timedelta(minutes=VENTANA_CORRECCION_MINUTOS)
    corregidas = list(
        Medicion.objects.filter(
            origen='dinamica',
            ultima_correccion_en__gte=ventana_desde,
        )
        .select_related('paciente')
        .order_by('-ultima_correccion_en')[:20]
    )
    correcciones = [
        {
            'medicion_id': m.id,
            'numero_documento': m.paciente.numero_documento,
            'ultima_correccion_iso': m.ultima_correccion_en.isoformat(),
        }
        for m in corregidas
    ]
    return JsonResponse({'correcciones': correcciones}, json_dumps_params={'ensure_ascii': False})


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


def responsable_meows_mas_reciente(paciente):
    """
    2026-09-14: a pedido explícito -- MEOWS ya no se diligencia a mano, todas
    las mediciones llegan solas desde Dinámica (ver
    sincronizar_signos_vitales_dinamica), así que el profesional en sesión de
    ESTA app (quien tenga la pantalla abierta) casi nunca es quien de verdad
    hizo el registro en Dinámica -- puede ser una enfermera distinta con
    turno abierto acá mientras otra digita allá. El campo "RESPONSABLE DEL
    REPORTE" debe reflejar a quien SÍ lo hizo: se toma
    Medicion.responsable_dinamica (GENMEDICO.GMENOMCOM, ver
    meows/services/dinamica_signos_vitales.py) de la medición más reciente
    de este paciente, no nombre_profesional_sesion().
    """
    # 2026-09-23: también cuenta quien registró una toma de Triaje en la app
    # (Medicion.registrado_por), ver Medicion.responsable_toma.
    medicion = (
        Medicion.objects.filter(paciente=paciente)
        .filter(
            (Q(responsable_dinamica__isnull=False) & ~Q(responsable_dinamica=''))
            | (Q(registrado_por__isnull=False) & ~Q(registrado_por=''))
        )
        .order_by('-fecha_hora')
        .first()
    )
    return medicion.responsable_toma if medicion else ''


def responsable_meows_default(request, paciente):
    """
    Como responsable_meows_mas_reciente() de arriba, pero con respaldo para
    pacientes que todavía no tienen ningún registro de Dinámica -- el caso
    de Triaje (2026-09-22, a pedido explícito): antes de que exista ingreso
    no hay ningún GENMEDICO que traer de Dinámica, así que el campo
    quedaba vacío en la Línea de Tiempo Clínica aunque hubiera una sesión
    abierta. En ese caso puntual sí tiene sentido usar
    nombre_profesional_sesion() (quien tiene la pantalla abierta), porque es
    justamente quien registró el triaje a mano.
    """
    return responsable_meows_mas_reciente(paciente) or nombre_profesional_sesion(request)


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

    # 2026-09-22: a pedido, para diferenciar de un vistazo si esta paciente
    # todavía está en Triaje (sin ningún registro de Dinámica todavía) --
    # el título de la sección cambia a "Línea de Tiempo Triaje" en ese caso
    # (ver meows/_timeline_grid.html). En cuanto aparece una sola medición
    # de Dinámica (ya tuvo ingreso), vuelve a "Línea de Tiempo Clínica".
    todo_origen_triaje = bool(columnas) and all(c['origen'] != 'dinamica' for c in columnas)

    documento = request.GET.get("doc") or paciente.numero_documento
    atencion_id = request.GET.get("atencion")
    if not atencion_id and documento:
        # Si no viene por la URL, buscamos la atención activa más reciente de este paciente
        # para no perder el contexto (permite desplegar los módulos en el sidebar).
        atencion = AtencionParto.objects.filter(paciente=documento).order_by('-fecha_inicio').first()
        if atencion:
            atencion_id = atencion.id

    # 2026-09-23: número de ingreso de Dinámica (ADNINGRESO.AINCONSEC) para la
    # tarjeta "Información del Paciente" -- el de la atención si ya lo tiene,
    # o el ingreso actual de la paciente. Sin ingreso (Triaje) queda vacío.
    numero_ingreso = ''
    atencion_actual = (
        AtencionParto.objects.filter(id=atencion_id).first()
        if str(atencion_id or '').isdigit() else None
    )
    if atencion_actual is not None and atencion_actual.numero_ingreso:
        numero_ingreso = atencion_actual.numero_ingreso
    elif documento:
        try:
            from obstetriciaunificador.repositorio import resolver_atencion_ingreso
            atencion_ingreso, _ = resolver_atencion_ingreso(documento, crear=False)
            if atencion_ingreso is not None:
                numero_ingreso = atencion_ingreso.numero_ingreso
                atencion_id = atencion_id or atencion_ingreso.id
        except Exception:
            pass  # Dinámica no disponible: la tarjeta muestra "-"

    return render(request, "meows/historial.html", {
        "paciente": paciente,
        "grid_parametros": grid_parametros,
        "columnas": columnas,
        "atencion_id": atencion_id,
        "numero_ingreso": numero_ingreso,
        "documento": documento,
        "todo_origen_triaje": todo_origen_triaje,
        # 2026-09-14: el campo "RESPONSABLE DEL REPORTE" ya NO se precarga con
        # el profesional en sesión de esta app -- MEOWS se diligencia solo
        # desde Dinámica, así que se usa a quien realmente digitó la última
        # medición allá (ver responsable_meows_mas_reciente arriba). 2026-09-22:
        # salvo para Triaje, que sí se diligencia a mano y no tiene todavía
        # ningún registro de Dinámica del que tomar el nombre -- en ese caso
        # se usa el profesional en sesión (ver responsable_meows_default).
        "responsable_meows_default": responsable_meows_default(request, paciente),
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

    # Responsable = lo que quedó en el campo "Responsable" de la pantalla (se
    # precarga con quien digitó en Dinámica la medición más reciente, o con
    # el profesional en sesión si es un paciente de Triaje sin registros de
    # Dinámica aún -- ver responsable_meows_default, y es editable); si llega
    # vacío, se usa el mismo criterio de resguardo.
    responsable = (request.GET.get('responsable') or '').strip() or responsable_meows_default(request, paciente)
    return generar_pdf_meows(paciente, mediciones, responsable=responsable)


# 2026-09-14: se eliminaron guardar_huella() y ultima_huella() (captura de
# firma/huella biométrica) a pedido explícito, antes de salir a producción --
# dependían de meows.models.FirmaPaciente, que también se eliminó.
