
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from .models import AtencionParto

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter

from meows.models import Medicion, Paciente as MeowsPaciente  # noqa: F401
from frecuenciafetal.models import ControlFetocardia, RegistroParto
from trabajoparto.models import Formulario, Paciente as TrabajoPartoPaciente
from sistema_obstetrico.auth_utils import login_required_if_enabled


def get_patient_timeline(documento):
    """
    Construye la línea de vida cronológica cruzando datos de MEOWS, Fetal y Parto.
    Se basa en el número de identificación del paciente.
    """
    from meows.models import Medicion
    from frecuenciafetal.models import RegistroParto
    from trabajoparto.models import Formulario, Medicion as PartoMedicion, MedicionValor as PartoMedicionValor
    from django.db.models import Q
    from django.utils import timezone

    # Consultar datos de todas las fuentes
    meows = Medicion.objects.filter(paciente__numero_documento=documento).order_by("-fecha_hora")
    fetal = RegistroParto.objects.filter(identificacion=documento).order_by("-created_at")
    parto_formularios = Formulario.objects.filter(paciente__num_identificacion=documento)

    timeline = []

    # 1. Agregar MEOWS
    for m in meows:
        color_map = {
            "BLANCO": "#3b82f6", "VERDE": "#10b981",
            "AMARILLO": "#f59e0b", "ROJO": "#ef4444",
        }
        m_color = color_map.get(m.meows_riesgo, "#312e81")
        timeline.append({
            "tipo": "MEOWS",
            "fecha": m.fecha_hora.isoformat() if m.fecha_hora else None,
            "titulo": "🩺 MONITOREO MEOWS",
            "detalle": f"Riesgo: {m.meows_riesgo} | Puntaje: {m.meows_total}",
            "color": m_color,
            "icon": "activity"
        })

    # 2. Agregar FETAL
    for f in fetal:
        timeline.append({
            "tipo": "FETAL",
            "fecha": f.created_at.isoformat() if f.created_at else None,
            "titulo": "❤️ CONTROL FETAL",
            "detalle": f"EG: {f.edad_gestacional} Sem - Registro de monitoreo fetal.",
            "color": "#ec4899",
            "icon": "baby"
        })

    # 3. Agregar PARTO: una entrada por cada RONDA de mediciones (marca de
    # tiempo real en la que se registraron parámetros), no una por Formulario
    # completo — el Formulario es un único registro para toda la atención,
    # así que iterar sobre él ocultaba todas las rondas salvo la más reciente.
    rondas_parto = (
        PartoMedicion.objects.filter(formulario__in=parto_formularios)
        .exclude(tomada_en__isnull=True)
        .values_list("tomada_en", flat=True)
        .distinct()
    )
    for tomada_en in rondas_parto:
        dilatacion = (
            PartoMedicionValor.objects.filter(
                medicion__formulario__in=parto_formularios,
                medicion__tomada_en=tomada_en,
                medicion__parametro__nombre="Dilatación",
                valor_number__isnull=False,
            )
            .values_list("valor_number", flat=True)
            .first()
        )
        detalle = f"Dilatación: {float(dilatacion):g} cm" if dilatacion is not None else "Control de trabajo de parto registrado"
        timeline.append({
            "tipo": "PARTO",
            "fecha": tomada_en.isoformat() if tomada_en else None,
            "titulo": "👶 TRABAJO DE PARTO",
            "detalle": detalle,
            "color": "#8b5cf6",
            "icon": "clipboard-list"
        })

    # Ordenar por fecha (desc) y prioridad de tipo para empates.
    # Además, eliminar entradas duplicadas exactas para limpiar la visualización.
    from datetime import datetime

    tipo_prioridad = {"MEOWS": 0, "FETAL": 1, "PARTO": 2}

    def _parse_fecha(value):
        if not value:
            return datetime.min
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return datetime.min

    timeline_ordenada = sorted(
        timeline,
        key=lambda x: (
            _parse_fecha(x.get("fecha")),
            -tipo_prioridad.get(x.get("tipo", ""), 99),
        ),
        reverse=True,
    )

    timeline_limpia = []
    vistos = set()
    for item in timeline_ordenada:
        firma = (
            item.get("tipo", ""),
            item.get("fecha", ""),
            item.get("titulo", ""),
            item.get("detalle", ""),
        )
        if firma in vistos:
            continue
        vistos.add(firma)
        timeline_limpia.append(item)

    return timeline_limpia


def get_meows_trazabilidad(documento):
    """
    Serie de tiempo del puntaje total MEOWS (resumen) más una serie por cada
    signo vital individual (TA sistólica/diastólica, FC, FR, Temperatura,
    SpO2, Glasgow, FCF). El puntaje agregado oculta cuál signo vital concreto
    está mejorando o empeorando, así que se desglosa igual que se hizo con
    Trabajo de Parto.
    """
    from meows.models import Medicion, MedicionValor

    color_map = {
        "BLANCO": "#3b82f6",
        "VERDE": "#22c55e",
        "AMARILLO": "#eab308",
        "ROJO": "#ef4444",
    }

    mediciones = (
        Medicion.objects.filter(paciente__numero_documento=documento)
        .exclude(fecha_hora__isnull=True)
        .order_by("fecha_hora")
    )

    labels, valores, colores = [], [], []
    for m in mediciones:
        fecha_local = timezone.localtime(m.fecha_hora) if timezone.is_aware(m.fecha_hora) else m.fecha_hora
        labels.append(fecha_local.strftime("%d/%m %H:%M"))
        valores.append(m.meows_total)
        colores.append(color_map.get(m.meows_riesgo, "#64748b"))

    # Desglose por signo vital individual
    valores_qs = (
        MedicionValor.objects.filter(medicion__paciente__numero_documento=documento)
        .exclude(medicion__fecha_hora__isnull=True)
        .select_related("medicion", "parametro")
        .order_by("medicion__fecha_hora")
    )

    paleta = ["#dc2626", "#ea580c", "#0891b2", "#7c3aed", "#059669", "#2563eb", "#db2777", "#ca8a04"]
    labels_vitales, labels_vistos = [], set()
    series_por_parametro = {}

    for v in valores_qs:
        fecha_local = timezone.localtime(v.medicion.fecha_hora) if timezone.is_aware(v.medicion.fecha_hora) else v.medicion.fecha_hora
        etiqueta = fecha_local.strftime("%d/%m %H:%M")
        if etiqueta not in labels_vistos:
            labels_vistos.add(etiqueta)
            labels_vitales.append(etiqueta)

        try:
            numero = float(v.valor)
        except (TypeError, ValueError):
            continue

        nombre_parametro = v.parametro.nombre
        if nombre_parametro not in series_por_parametro:
            color = paleta[len(series_por_parametro) % len(paleta)]
            series_por_parametro[nombre_parametro] = {
                "parametro": nombre_parametro,
                "unidad": v.parametro.unidad or "",
                "color": color,
                "valores": {},
            }
        series_por_parametro[nombre_parametro]["valores"][etiqueta] = numero

    series_vitales = []
    for info in series_por_parametro.values():
        series_vitales.append({
            "parametro": info["parametro"],
            "unidad": info["unidad"],
            "color": info["color"],
            "data": [info["valores"].get(etiqueta) for etiqueta in labels_vitales],
        })

    return {
        "labels": labels,
        "valores": valores,
        "colores": colores,
        "vitales": {"labels": labels_vitales, "series": series_vitales},
    }


def get_parto_trazabilidad(documento):
    """
    Trazabilidad de Trabajo de Parto: una serie por cada parámetro numérico
    registrado (Frecuencia, Duración, Intensidad, FCF, Dilatación, Borramiento,
    etc.), todas compartiendo el mismo eje de tiempo, para graficar la
    evolución completa (no solo un parámetro aislado).
    """
    from trabajoparto.models import MedicionValor

    valores_qs = (
        MedicionValor.objects.filter(
            valor_number__isnull=False,
            medicion__formulario__paciente__num_identificacion=documento,
        )
        .select_related("medicion", "medicion__parametro", "campo")
        .order_by("medicion__tomada_en")
    )

    paleta = ["#0891b2", "#db2777", "#7c3aed", "#d97706", "#16a34a", "#2563eb", "#e11d48", "#0d9488"]

    labels = []
    labels_vistos = set()
    series_por_parametro = {}

    for v in valores_qs:
        tomada_en = v.medicion.tomada_en
        fecha_local = timezone.localtime(tomada_en) if timezone.is_aware(tomada_en) else tomada_en
        etiqueta = fecha_local.strftime("%d/%m %H:%M")
        if etiqueta not in labels_vistos:
            labels_vistos.add(etiqueta)
            labels.append(etiqueta)

        nombre_parametro = v.medicion.parametro.nombre
        if nombre_parametro not in series_por_parametro:
            color = paleta[len(series_por_parametro) % len(paleta)]
            series_por_parametro[nombre_parametro] = {
                "parametro": nombre_parametro,
                "unidad": v.medicion.parametro.unidad or "",
                "color": color,
                "valores": {},
            }
        series_por_parametro[nombre_parametro]["valores"][etiqueta] = float(v.valor_number)

    series = []
    for info in series_por_parametro.values():
        series.append({
            "parametro": info["parametro"],
            "unidad": info["unidad"],
            "color": info["color"],
            "data": [info["valores"].get(etiqueta) for etiqueta in labels],
        })

    return {"labels": labels, "series": series}


@login_required_if_enabled
def dashboard(request):
    """
    2026-09-09: la vista de bienvenida (tarjeta "Sistema Obstétrico Unificado"
    + las 3 features) se movió a la pantalla de login (ver frecuenciafetal/
    templates/frecuenciafetal/login.html) -- ya no tiene sentido repetirla
    después de iniciar sesión. Esta ruta ('/atencion/', raíz del sitio tras
    home() en sistema_obstetrico/urls.py) ahora entra directo a Sala de
    Partos, que es lo que la propia pantalla de bienvenida ya le pedía hacer
    al usuario ("Use Sala de Partos para identificar a la paciente").
    Se deja esta vista (en vez de apuntar la URL raíz directo a sala_de_partos
    en urls.py) para no tener que tocar las 2 rutas que ya apuntan aquí
    (sistema_obstetrico/urls.py:home y obstetriciaunificador/urls.py:'').
    """
    return redirect("sala_de_partos")


@login_required_if_enabled
def manual_usuario(request):
    """
    Manual de Usuario: guía paso a paso de cómo usar cada módulo del sistema.
    """
    return render(request, "obstetricia/manual_usuario.html", {
        "is_manual": True,
        "title": "Manual de Usuario | Sistema Obstétrico Unificado"
    })


@login_required_if_enabled
def atencion_detalle(request, id):
    atencion = get_object_or_404(AtencionParto, id=id)

    # Integración por identificador textual mientras se define FK real entre apps.
    identificador = (atencion.paciente or "").strip()

    # 1. MEOWS: Buscar por atención, y si no hay, por identificación
    meows = Medicion.objects.filter(atencion=atencion).select_related("paciente", "formulario")
    if not meows.exists() and identificador:
        if identificador.isdigit():
            meows = Medicion.objects.filter(paciente__numero_documento=identificador).select_related("paciente", "formulario")
        else:
            meows = Medicion.objects.filter(Q(paciente__nombres__icontains=identificador) | Q(paciente__apellidos__icontains=identificador)).select_related("paciente", "formulario")

    # 2. FETAL: Buscar por atención, y si no hay, por identificación
    fetal = RegistroParto.objects.filter(atencion=atencion)
    if not fetal.exists() and identificador:
        if identificador.isdigit():
            fetal = RegistroParto.objects.filter(identificacion=identificador)
        else:
            fetal = RegistroParto.objects.filter(nombre_paciente__icontains=identificador)

    # 3. PARTO: Buscar por atención, y si no hay, por identificación
    parto = Formulario.objects.filter(atencion=atencion).select_related("paciente")
    if not parto.exists() and identificador:
        if identificador.isdigit():
            parto = Formulario.objects.filter(paciente__num_identificacion=identificador).select_related("paciente")
        else:
            parto = Formulario.objects.filter(paciente__nombres__icontains=identificador).select_related("paciente")

    # CONSTRUCCIÓN DE LA LÍNEA DE TIEMPO UNIFICADA
    timeline = []

    # 1. Agregar MEOWS
    for m in meows:
        # Color dinámico según el riesgo MEOWS
        color_map = {
            "BLANCO": "#3b82f6",     # Azul
            "VERDE": "#10b981",      # Verde
            "AMARILLO": "#f59e0b",   # Amarillo/Naranja
            "ROJO": "#ef4444",       # Rojo
        }
        m_color = color_map.get(m.meows_riesgo, "#312e81") # Indigo por defecto

        timeline.append({
            "tipo": "MEOWS",
            "fecha": m.fecha_hora,
            "obj": m,
            "icon": "activity",
            "color": m_color
        })

    # 2. Agregar FETAL (RegistroParto)
    for f in fetal:
        timeline.append({
            "tipo": "FETAL",
            "fecha": f.created_at,
            "obj": f,
            "icon": "baby",
            "color": "#ec4899"
        })

    # 3. Agregar PARTO (Formulario)
    for p in parto:
        timeline.append({
            "tipo": "PARTO",
            "fecha": p.created_at,
            "obj": p,
            "icon": "clipboard-list",
            "color": "#8b5cf6"
        })

    # Ordenar por fecha descendente (lo más reciente arriba)
    timeline = sorted(timeline, key=lambda x: x["fecha"] if x["fecha"] else timezone.now(), reverse=True)

    # Calcular Estado Global según el riesgo MEOWS más alto encontrado
    estado_global = "ESTABLE"
    riesgos_encontrados = set(meows.values_list("meows_riesgo", flat=True))
    if "ROJO" in riesgos_encontrados:
        estado_global = "CRÍTICO"
    elif "AMARILLO" in riesgos_encontrados:
        estado_global = "ALERTA"

    # Determinar si hay un paciente vinculado
    has_paciente = bool(atencion.paciente)

    return render(request, "obstetricia/detalle.html", {
        "atencion": atencion,
        "meows": meows,
        "fetal": fetal,
        "parto": parto,
        "timeline": timeline,
        "estado_global": estado_global,
        "has_paciente": has_paciente
    })


@require_http_methods(["GET"])
@login_required_if_enabled
def api_datos_paciente_unificado(request):
    """
    Devuelve datos del paciente para poblar MEOWS, Frecuencia Fetal y Trabajo de Parto.
    Busca en meows.Paciente y trabajoparto.Paciente.
    Uso: GET /atencion/api/datos-paciente-unificado/?doc=123456
    """
    doc = (request.GET.get("doc") or request.GET.get("num_identificacion") or "").strip()
    if not doc:
        return JsonResponse({"ok": False, "error": "Parámetro doc requerido"}, status=400)

    from datetime import date

    # 1. Buscar en meows.Paciente
    meows_p = MeowsPaciente.objects.filter(numero_documento=doc).first()
    if meows_p:
        edad = None
        if meows_p.fecha_nacimiento:
            today = date.today()
            edad = today.year - meows_p.fecha_nacimiento.year - (
                (today.month, today.day) < (meows_p.fecha_nacimiento.month, meows_p.fecha_nacimiento.day)
            )
        fn = meows_p.fecha_nacimiento
        response = JsonResponse({
            "ok": True,
            "encontrado": True,
            "nombre_completo": f"{meows_p.nombres} {meows_p.apellidos}".strip(),
            "nombre_paciente": f"{meows_p.nombres} {meows_p.apellidos}".strip(),
            "nombres": meows_p.nombres,
            "num_identificacion": meows_p.numero_documento,
            "identificacion": meows_p.numero_documento,
            "num_historia_clinica": meows_p.num_historia_clinica or "",
            "fecha_nacimiento": fn.strftime("%Y-%m-%d") if fn else None,
            "edad": edad,
            "aseguradora": meows_p.aseguradora or "",
            "cama": meows_p.cama or "",
            "fecha_ingreso": meows_p.fecha_ingreso.strftime("%Y-%m-%d") if meows_p.fecha_ingreso else None,
            "responsable": meows_p.responsable or "",
            "tipo_sangre": meows_p.tipo_sangre or "",
            "nombre_acompanante": meows_p.nombre_acompanante or "",
            "edad_gestacional": meows_p.edad_gestacional,
            "gestas": meows_p.gestas,
            "diagnostico": meows_p.diagnostico or "",
            "n_controles_prenatales": meows_p.n_controles_prenatales,
            "atencion_id": AtencionParto.objects.filter(paciente=doc).order_by("-fecha_inicio").values_list("id", flat=True).first(),
            "mediciones_count": Medicion.objects.filter(paciente__numero_documento=doc).count(),
            "fetal_count": RegistroParto.objects.filter(identificacion=doc).count(),
            "parto_count": Formulario.objects.filter(paciente__num_identificacion=doc).count(),
            "estado_global": "CRÍTICO" if Medicion.objects.filter(paciente__numero_documento=doc, meows_riesgo="ROJO").exists() else "ALERTA" if Medicion.objects.filter(paciente__numero_documento=doc, meows_riesgo="AMARILLO").exists() else "ESTABLE",
            "timeline": get_patient_timeline(doc),
            "meows_trazabilidad": get_meows_trazabilidad(doc),
            "parto_trazabilidad": get_parto_trazabilidad(doc)
        })
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        return response

    # 2. Fallback: trabajoparto.Paciente
    tp_p = TrabajoPartoPaciente.objects.filter(num_identificacion=doc).first()
    if tp_p:
        edad = None
        if tp_p.fecha_nacimiento:
            today = date.today()
            edad = today.year - tp_p.fecha_nacimiento.year - (
                (today.month, today.day) < (tp_p.fecha_nacimiento.month, tp_p.fecha_nacimiento.day)
            )
        fn = tp_p.fecha_nacimiento
        response = JsonResponse({
            "ok": True,
            "encontrado": True,
            "nombre_completo": tp_p.nombres or "",
            "nombre_paciente": tp_p.nombres or "",
            "nombres": tp_p.nombres or "",
            "num_identificacion": tp_p.num_identificacion,
            "identificacion": tp_p.num_identificacion,
            "num_historia_clinica": tp_p.num_historia_clinica or "",
            "fecha_nacimiento": fn.strftime("%Y-%m-%d") if fn else None,
            "edad": edad,
            "aseguradora": "",
            "cama": "",
            "fecha_ingreso": None,
            "responsable": "",
            "tipo_sangre": tp_p.tipo_sangre or "",
            "nombre_acompanante": "",
            "edad_gestacional": None,
            "gestas": None,
            "diagnostico": "",
            "n_controles_prenatales": None,
            "atencion_id": AtencionParto.objects.filter(paciente=doc).order_by("-fecha_inicio").values_list("id", flat=True).first(),
            "mediciones_count": Medicion.objects.filter(paciente__numero_documento=doc).count(),
            "fetal_count": RegistroParto.objects.filter(identificacion=doc).count(),
            "parto_count": Formulario.objects.filter(paciente__num_identificacion=doc).count(),
            "estado_global": "CRÍTICO" if Medicion.objects.filter(paciente__numero_documento=doc, meows_riesgo="ROJO").exists() else "ALERTA" if Medicion.objects.filter(paciente__numero_documento=doc, meows_riesgo="AMARILLO").exists() else "ESTABLE",
            "timeline": get_patient_timeline(doc),
            "meows_trazabilidad": get_meows_trazabilidad(doc),
            "parto_trazabilidad": get_parto_trazabilidad(doc)
        })
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        return response

    response = JsonResponse({"ok": True, "encontrado": False, "mensaje": "Paciente no encontrado"})
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


@require_http_methods(["POST"])
@login_required_if_enabled
def guardar_datos_paciente_card(request, atencion_id):
    """
    Guarda los datos básicos y clínicos de la card de paciente.
    Crea/actualiza meows.Paciente y actualiza AtencionParto.paciente.
    Para pacientes nuevos: este es el único punto de ingreso.
    """
    import json
    from django.db import IntegrityError

    atencion = get_object_or_404(AtencionParto, id=atencion_id)

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    num_identificacion = (data.get("num_identificacion") or "").strip()
    if not num_identificacion:
        return JsonResponse({"ok": False, "error": "Identificación es requerida"}, status=400)

    nombres_completos = (data.get("nombres") or "").strip()
    partes = nombres_completos.split(maxsplit=1) if nombres_completos else ["", ""]
    nombres = partes[0] or "N/A"
    apellidos = partes[1] if len(partes) > 1 else "N/A"

    num_hc = (data.get("num_historia_clinica") or "").strip() or f"HC-{num_identificacion}"

    try:
        paciente, created = MeowsPaciente.objects.get_or_create(
            numero_documento=num_identificacion,
            defaults={
                "nombres": nombres,
                "apellidos": apellidos,
                "sexo": (data.get("sexo") or "F")[:1] or "F",
                "aseguradora": (data.get("aseguradora") or "")[:200],
                "cama": (data.get("cama") or "")[:50],
                "responsable": (data.get("responsable") or "")[:200],
                "nombre_acompanante": (data.get("nombre_acompanante") or "")[:200],
                "tipo_sangre": (data.get("tipo_sangre") or "")[:5],
                "diagnostico": (data.get("diagnostico") or "").strip(),
                "num_historia_clinica": num_hc[:50],
            }
        )
    except IntegrityError as exc:
        return JsonResponse({"ok": False, "error": f"No se pudo crear el paciente: {exc}"}, status=400)
    if not created:
        paciente.nombres = nombres
        paciente.apellidos = apellidos
        paciente.sexo = (data.get("sexo") or paciente.sexo or "F")[:1]

    paciente.aseguradora = (data.get("aseguradora") or "")[:200]
    paciente.cama = (data.get("cama") or "")[:50]
    paciente.responsable = (data.get("responsable") or "")[:200]
    paciente.diagnostico = (data.get("diagnostico") or "").strip()
    paciente.num_historia_clinica = num_hc[:50]
    paciente.nombre_acompanante = (data.get("nombre_acompanante") or "")[:200]
    paciente.tipo_sangre = (data.get("tipo_sangre") or "")[:5]
    eg = data.get("edad_gestacional")
    paciente.edad_gestacional = int(eg) if eg is not None and str(eg).strip() else None
    g = data.get("gestas")
    paciente.gestas = int(g) if g is not None and str(g).strip() else None
    ncp = data.get("n_controles_prenatales")
    paciente.n_controles_prenatales = int(ncp) if ncp is not None and str(ncp).strip() else None

    from datetime import datetime
    fn = data.get("fecha_nacimiento")
    if fn:
        try:
            paciente.fecha_nacimiento = datetime.strptime(str(fn)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            paciente.fecha_nacimiento = None
    else:
        paciente.fecha_nacimiento = None

    fi = data.get("fecha_ingreso")
    if fi:
        try:
            paciente.fecha_ingreso = datetime.strptime(str(fi)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            paciente.fecha_ingreso = None
    else:
        paciente.fecha_ingreso = None

    try:
        paciente.save()
    except IntegrityError:
        return JsonResponse({"ok": False, "error": "Error al guardar paciente (documento duplicado)"}, status=400)

    # Sincronizar también en trabajoparto.Paciente (para Frecuencia Fetal y Trabajo de Parto)
    nombres_tp = f"{nombres} {apellidos}".strip() or "N/A"
    tipo_sangre = (data.get("tipo_sangre") or "")[:3] or None
    try:
        tp_paciente, created = TrabajoPartoPaciente.objects.get_or_create(
            num_identificacion=num_identificacion,
            defaults={
                "num_historia_clinica": num_hc[:255],
                "nombres": nombres_tp[:255],
                "fecha_nacimiento": paciente.fecha_nacimiento,
                "tipo_sangre": tipo_sangre,
            }
        )
        if not created:
            tp_paciente.nombres = nombres_tp[:255]
            tp_paciente.fecha_nacimiento = paciente.fecha_nacimiento
            tp_paciente.tipo_sangre = tipo_sangre or tp_paciente.tipo_sangre
            tp_paciente.save()
    except IntegrityError:
        pass

    atencion.paciente = num_identificacion
    atencion.save(update_fields=["paciente"])

    return JsonResponse({
        "ok": True,
        "mensaje": "Datos guardados correctamente",
        "documento": num_identificacion,
    })


@require_http_methods(["POST"])
@login_required_if_enabled
def registrar_atencion_desde_sala_partos(request):
    """
    Registra (o reutiliza) la atención local de un paciente ACTIVO en Sala de Partos
    (DGEMPRES_NEXUS, solo lectura), usando los datos ya confirmados que trae la lista de
    activos, para poder abrir directamente los 3 módulos sin pasar por el formulario
    manual de "paciente no registrado".
    Uso: POST /atencion/api/registrar-desde-sala-partos/  body: item de listar_pacientes_sala_partos().
    """
    import json
    from datetime import datetime
    from django.db import IntegrityError

    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    doc = (data.get("identificacion") or "").strip()
    if not doc:
        return JsonResponse({"ok": False, "error": "Identificación es requerida"}, status=400)

    nombre_completo = (data.get("nombre_paciente") or "").strip()
    partes = nombre_completo.split(maxsplit=1) if nombre_completo else ["", ""]
    nombres = partes[0] or "N/A"
    apellidos = partes[1] if len(partes) > 1 else "N/A"
    num_hc = (str(data.get("historia_clinica") or "")).strip() or f"HC-{doc}"

    def _parse_fecha(value):
        if not value:
            return None
        try:
            return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    def _parse_int(value):
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    try:
        paciente, _creado = MeowsPaciente.objects.get_or_create(
            numero_documento=doc,
            defaults={"nombres": nombres, "apellidos": apellidos, "sexo": "F"},
        )
    except IntegrityError as exc:
        return JsonResponse({"ok": False, "error": f"No se pudo registrar el paciente: {exc}"}, status=400)

    paciente.nombres = nombres
    paciente.apellidos = apellidos
    paciente.aseguradora = (data.get("aseguradora") or "")[:200]
    paciente.cama = str(data.get("numero_cama") or "")[:50]
    paciente.num_historia_clinica = num_hc[:50]
    paciente.diagnostico = (data.get("diagnostico") or "").strip()
    paciente.tipo_sangre = (data.get("grupo_sanguineo") or "")[:5]
    paciente.nombre_acompanante = (data.get("nombre_acompanante") or "")[:200]
    paciente.edad_gestacional = _parse_int(data.get("edad_gestacional"))
    paciente.gestas = _parse_int(data.get("gestas"))
    paciente.n_controles_prenatales = _parse_int(data.get("controles_prenatales"))
    paciente.fecha_ingreso = _parse_fecha(data.get("fecha_ingreso"))
    paciente.fecha_nacimiento = _parse_fecha(data.get("fecha_nacimiento"))

    try:
        paciente.save()
    except IntegrityError:
        return JsonResponse({"ok": False, "error": "Error al guardar paciente (documento duplicado)"}, status=400)

    # Sincronizar también en trabajoparto.Paciente (para Frecuencia Fetal y Trabajo de Parto)
    try:
        tp_paciente, tp_creado = TrabajoPartoPaciente.objects.get_or_create(
            num_identificacion=doc,
            defaults={
                "num_historia_clinica": num_hc[:255],
                "nombres": (nombre_completo or nombres)[:255],
                "fecha_nacimiento": paciente.fecha_nacimiento,
                "tipo_sangre": (data.get("grupo_sanguineo") or None),
            }
        )
        if not tp_creado:
            tp_paciente.nombres = (nombre_completo or tp_paciente.nombres)[:255]
            tp_paciente.fecha_nacimiento = paciente.fecha_nacimiento
            tp_paciente.tipo_sangre = data.get("grupo_sanguineo") or tp_paciente.tipo_sangre
            tp_paciente.save()
    except IntegrityError:
        pass

    atencion = AtencionParto.objects.filter(paciente=doc).order_by("-fecha_inicio").first()
    if not atencion:
        atencion = AtencionParto.objects.create(paciente=doc)

    return JsonResponse({"ok": True, "atencion_id": atencion.id, "documento": doc})


@login_required_if_enabled
def pdf_atencion(request, id):
    """
    Genera una Historia Clínica Obstétrica Unificada ensamblando los PDFs
    originales de cada módulo (MEOWS, Fetal, Parto) en un solo documento.
    Mantiene el diseño, tablas y biometría original de cada formato.
    """
    from PyPDF2 import PdfWriter, PdfReader
    import io
    from django.http import HttpResponse
    from obstetriciaunificador.models import AtencionParto
    
    # Importar generadores originales
    from meows.generador_pdf_meows import generar_pdf_meows
    from frecuenciafetal.pdf_generator import generar_pdf_registro
    from trabajoparto.pdf_utils import generar_pdf_formulario_clinico
    
    # Modelos para búsqueda
    from meows.models import Medicion
    from frecuenciafetal.models import RegistroParto
    from trabajoparto.models import Formulario

    atencion = get_object_or_404(AtencionParto, id=id)
    doc_override = (request.GET.get("doc") or "").strip()
    documento_objetivo = doc_override or (atencion.paciente or "").strip()

    # Si llega doc y existe una atención más coherente para ese documento, usarla para metadatos/filename.
    if doc_override:
        atencion_doc = AtencionParto.objects.filter(paciente=doc_override).order_by("-fecha_inicio").first()
        if atencion_doc:
            atencion = atencion_doc
    writer = PdfWriter()
    has_content = False

    # 1. --- MÓDULO MEOWS ---
    from meows.models import Paciente as PacienteMeows
    # Si llega doc por querystring, filtrar EXCLUSIVAMENTE por documento para evitar
    # mezclar registros de otra atención/paciente (caso crítico reportado).
    if doc_override:
        mediciones_qs = Medicion.objects.filter(
            paciente__numero_documento=documento_objetivo
        ).order_by("fecha_hora")
    else:
        mediciones_qs = Medicion.objects.filter(
            atencion=atencion
        ).order_by("fecha_hora")

    if mediciones_qs.exists():
        try:
            paciente_meows = PacienteMeows.objects.get(numero_documento=documento_objetivo)
        except (PacienteMeows.DoesNotExist, PacienteMeows.MultipleObjectsReturned):
            paciente_meows = mediciones_qs.first().paciente

        response_meows = generar_pdf_meows(paciente_meows, list(mediciones_qs))
        if isinstance(response_meows, HttpResponse):
            pdf_file = io.BytesIO(response_meows.content)
            reader = PdfReader(pdf_file)
            for page in reader.pages:
                writer.add_page(page)
            has_content = True

    # 2. --- MÓDULO CONTROL FETAL ---
    if doc_override:
        registros_fetal = RegistroParto.objects.filter(
            identificacion=documento_objetivo
        ).order_by("created_at")
    else:
        registros_fetal = RegistroParto.objects.filter(
            atencion=atencion
        ).order_by("created_at")

    for reg in registros_fetal:
        pdf_bytes = generar_pdf_registro(reg)
        if pdf_bytes:
            pdf_file = io.BytesIO(pdf_bytes)
            reader = PdfReader(pdf_file)
            for page in reader.pages:
                writer.add_page(page)
            has_content = True

    # 3. --- MÓDULO TRABAJO DE PARTO ---
    if doc_override:
        formularios_parto = Formulario.objects.filter(
            paciente__num_identificacion=documento_objetivo
        ).order_by("fecha_actualizacion")
    else:
        formularios_parto = Formulario.objects.filter(
            atencion=atencion
        ).order_by("fecha_actualizacion")

    for form in formularios_parto:
        response_parto = generar_pdf_formulario_clinico(form)
        if isinstance(response_parto, HttpResponse):
            pdf_file = io.BytesIO(response_parto.content)
            reader = PdfReader(pdf_file)
            for page in reader.pages:
                writer.add_page(page)
            has_content = True

    # 4. --- CASO SIN CONTENIDO ---
    if not has_content:
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.pagesizes import A4
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        elements = [
            Paragraph("HISTORIA CLÍNICA OBSTÉTRICA UNIFICADA", styles['Title']),
            Spacer(1, 20),
            Paragraph(f"No se encontraron registros clínicos cargados para la atención #{id}.", styles['Normal']),
            Paragraph(f"Paciente (ID): {documento_objetivo or atencion.paciente}", styles['Normal']),
            Spacer(1, 10),
            Paragraph("Por favor, registre datos en los módulos MEOWS, Fetal o Parto para generar el reporte completo.", styles['Italic'])
        ]
        doc.build(elements)
        buffer.seek(0)
        return HttpResponse(buffer.read(), content_type='application/pdf')

    # Salida final unificada ensamblada
    final_buffer = io.BytesIO()
    writer.write(final_buffer)
    final_buffer.seek(0)
    
    response = HttpResponse(final_buffer.read(), content_type='application/pdf')
    filename = f"HC_Obstetrica_{documento_objetivo or atencion.paciente}_{id}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required_if_enabled
def sala_de_partos(request):
    """
    Vista 'Sala de Partos': Hub para buscar pacientes y acceder a módulos.
    """
    return render(request, "obstetricia/sala_de_partos.html", {
        "is_dashboard": False,  # No es dashboard general
        "title": "Sala de Partos"
    })
