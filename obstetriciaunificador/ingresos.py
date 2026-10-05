"""
Consulta de registros por número de ingreso (2026-09-24).

En MEOWS, Trabajo de Parto y Control Posparto hay un selector con los
ingresos de la paciente; al elegir uno se ven SOLO los registros de ese
ingreso (en solo consulta si ya cerró). Este módulo es la parte común:

1. La lista de ingresos sale de Dinámica (ADNINGRESO). Si Dinámica no
   responde, o para las pacientes locales de prueba, se usan los ingresos que
   ya conoce la app (AtencionParto.numero_ingreso) -- sin modificarlos.

2. Cada registro se asigna a un ingreso, de la regla más segura a la menos:
   a) Tomas MEOWS traídas de Dinámica: su folio (Medicion.dinamica_folio)
      dice exactamente a qué ingreso pertenecen.
   b) El número de ingreso guardado en su atención -- siempre que la fecha del
      registro sea compatible con ese ingreso (las atenciones antiguas sin
      número se "adoptaron" para el ingreso vigente y pueden traer registros
      de ingresos anteriores).
   c) La fecha y hora CLÍNICA del registro: el ingreso de urgencias u
      hospitalización dentro de cuyas fechas cae (si cae en dos, el más
      reciente) o, si fue hasta 24 h antes de un ingreso, ese ingreso (triaje).
   d) Si no cae en ninguno: "Triajes sin ingreso" o "Registros sin ingreso
      asociado". Nunca se esconde un registro.
   Es un cálculo de solo lectura: no modifica ningún registro.

3. Edición: un ingreso se puede editar mientras está en curso y hasta
   settings.INGRESO_HORAS_GRACIA_EDICION horas después del egreso (notas
   tardías). Después queda en solo consulta; un administrador sí puede
   corregir. Si Dinámica no responde, nunca se bloquea la atención.
"""
import logging
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

# 2026-10-02: 'triaje' = solo las tomas MEOWS de origen triaje (pantalla de Triaje).
MODULOS = ('meows', 'trabajo_parto', 'control_posparto', 'triaje')
CLAVE_TRIAJE_SIN_INGRESO = 'triaje-sin-ingreso'
CLAVE_SIN_INGRESO = 'sin-ingreso'
# 2026-10-05: la visita a triaje EN CURSO (paciente que volvió y aún no tiene
# ingreso). Antes, sin ingreso actual se mostraban TODAS las tomas: una
# paciente que egresó el 02/10 y volvió a triaje el 05/10 veía las dos
# visitas mezcladas.
CLAVE_TRIAJE_ACTUAL = 'triaje-actual'
CLAVES_ESPECIALES = (CLAVE_TRIAJE_ACTUAL, CLAVE_TRIAJE_SIN_INGRESO, CLAVE_SIN_INGRESO)
# Tomas de triaje sin ingreso separadas por más que esto = visitas distintas.
HUECO_ENTRE_VISITAS_TRIAJE = timedelta(hours=24)
# La última visita sin ingreso es "Triaje actual" si tiene tomas así de recientes.
VIGENCIA_TRIAJE_ACTUAL = timedelta(hours=24)

# Las tomas de triaje se registran ANTES del ingreso formal.
MARGEN_TRIAJE_ANTES = timedelta(hours=24)
# Registros digitados un poco después de la salida.
MARGEN_DESPUES_EGRESO = timedelta(hours=1)
# Un ingreso sin egreso registrado en Dinámica se considera "en curso" solo si
# es el más reciente; si es más viejo que esto, se muestra "sin egreso registrado".
DIAS_MAX_EN_CURSO_SIN_EGRESO = 60
_CACHE_SEGUNDOS = 120
# 2026-09-24: la lista de ingresos se recuerda poco (solo para no consultar
# Dinámica varias veces en una misma pantalla) y además se descarta en
# cuanto la app se entera de un ingreso nuevo -- ver ingresos_de_paciente.
_CACHE_INGRESOS_SEGUNDOS = 30

TIPOS_TEXTO = {
    'hospitalizacion': 'Hospitalización',
    'urgencias': 'Urgencias',
    'consulta': 'Consulta externa',
    'desconocido': '',
}


def _aware(valor):
    if valor is None:
        return None
    if not isinstance(valor, datetime):
        valor = datetime.combine(valor, time.min)
    if timezone.is_naive(valor):
        # Dinámica guarda hora local de Bogotá sin zona.
        return timezone.make_aware(valor, timezone.get_current_timezone())
    return valor


def _gracia():
    return timedelta(hours=getattr(settings, 'INGRESO_HORAS_GRACIA_EDICION', 24))


def limpiar_numero_ingreso(valor):
    """Solo dígitos (o una clave especial): nunca se usa un valor del usuario
    tal cual para ubicar carpetas."""
    valor = str(valor or '').strip()
    if valor in CLAVES_ESPECIALES:
        return valor
    return valor if valor.isdigit() else ''


# ---------------------------------------------------------------------------
# Ingresos de la paciente
# ---------------------------------------------------------------------------
def _calcular_ventanas(ingresos):
    """Agrega a cada ingreso 'clinico', 'fin' (hasta cuándo le pertenecen los
    registros; None = abierto) y 'en_curso'."""
    ahora = timezone.now()
    clinicos = sorted(
        (i for i in ingresos if not i['anulado'] and i['tipo'] != 'consulta' and i['fecha_ingreso']),
        key=lambda i: i['fecha_ingreso'],
    )
    for i in ingresos:
        i['clinico'] = False
        i['fin'] = _aware(i['fecha_egreso']) + MARGEN_DESPUES_EGRESO if i['fecha_egreso'] else None
        i['en_curso'] = False
    for pos, i in enumerate(clinicos):
        i['clinico'] = True
        siguiente = clinicos[pos + 1] if pos + 1 < len(clinicos) else None
        if i['fecha_egreso'] is None:
            # Sin egreso: le pertenece todo hasta que empieza el siguiente ingreso.
            i['fin'] = siguiente['fecha_ingreso'] if siguiente else None
            i['en_curso'] = (
                siguiente is None
                and ahora - i['fecha_ingreso'] <= timedelta(days=DIAS_MAX_EN_CURSO_SIN_EGRESO)
            )


def ingresos_de_paciente(doc, fresco=False):
    """
    ([ingreso, ...] del más reciente al más antiguo, dinamica_ok, numero_actual).
    Cada ingreso: {'numero', 'fecha_ingreso', 'fecha_egreso', 'tipo',
    'anulado', 'fuente' ('dinamica'|'app'), 'clinico', 'fin', 'en_curso'}.

    fresco=True: consulta Dinámica sin usar lo recordado (las pantallas que
    deciden DÓNDE se guarda: hoja de Trabajo de Parto, registro posparto...).
    Aunque no sea fresco, lo recordado se descarta si la app ya conoce un
    ingreso de la paciente que no está en esa lista (lo registró Sala de
    Partos, el triaje o la sincronización -- incluso desde otro proceso).
    """
    from frecuenciafetal.sala_partos_db import consultar_ingreso_paciente, consultar_ingresos_paciente
    from .models import AtencionParto

    doc = (doc or '').strip()
    if not doc:
        return [], False, ''
    clave = f'ingresos_paciente:{doc}'
    guardado = None if fresco else cache.get(clave)
    if guardado is not None:
        conocidos = {i['numero'] for i in guardado[0]}
        nuevos = (AtencionParto.objects.filter(paciente=doc).exclude(numero_ingreso='')
                  .exclude(numero_ingreso__in=conocidos).exists())
        if not nuevos:
            return guardado

    try:
        filas = consultar_ingresos_paciente(doc)
    except Exception as exc:
        logger.warning('No se pudieron consultar los ingresos de la paciente en Dinámica: %s', exc)
        filas = None
    dinamica_ok = filas is not None

    ingresos = [
        {
            'numero': f['numero_ingreso'],
            'fecha_ingreso': _aware(f['fecha_ingreso']),
            'fecha_egreso': _aware(f['fecha_egreso']),
            'tipo': f['tipo'],
            'anulado': f['anulado'],
            'fuente': 'dinamica',
        }
        for f in filas or []
    ]
    conocidos = {i['numero'] for i in ingresos}
    for atencion in AtencionParto.objects.filter(paciente=doc).exclude(numero_ingreso='').order_by('fecha_inicio'):
        if atencion.numero_ingreso in conocidos:
            continue
        conocidos.add(atencion.numero_ingreso)
        ingresos.append({
            'numero': atencion.numero_ingreso,
            'fecha_ingreso': atencion.fecha_ingreso_dinamica or atencion.fecha_inicio,
            'fecha_egreso': None,
            'tipo': 'desconocido',
            'anulado': False,
            'fuente': 'app',
        })
    minimo = _aware(datetime(1900, 1, 1))
    ingresos.sort(key=lambda i: (i['fecha_ingreso'] or minimo, i['numero']), reverse=True)
    _calcular_ventanas(ingresos)

    actual = ''
    if dinamica_ok:
        try:
            info = consultar_ingreso_paciente(doc)
            actual = info['numero_ingreso'] if info else ''
        except Exception:
            actual = ''
    if not actual:
        actual = next((i['numero'] for i in ingresos if i['en_curso']), '')
    if not actual and not dinamica_ok and ingresos:
        actual = ingresos[0]['numero']

    resultado = (ingresos, dinamica_ok, actual)
    cache.set(clave, resultado, _CACHE_INGRESOS_SEGUNDOS)
    return resultado


def olvidar_ingresos_de_paciente(doc):
    cache.delete(f'ingresos_paciente:{(doc or "").strip()}')


# ---------------------------------------------------------------------------
# Asignación de registros
# ---------------------------------------------------------------------------
def _compatible(t, ingreso):
    """¿La fecha del registro es razonable para ese ingreso? (regla b)."""
    if t is None or ingreso['fecha_ingreso'] is None or ingreso['fuente'] == 'app':
        return True
    inicio = ingreso['fecha_ingreso'] - MARGEN_TRIAJE_ANTES
    fin = ingreso['fin']
    if fin is not None:
        fin = fin + _gracia()
    return t >= inicio and (fin is None or t <= fin)


def asignar_ingreso(t, ingresos, numero_guardado='', numero_folio='', es_triaje=False):
    por_numero = {i['numero']: i for i in ingresos}
    if numero_folio and numero_folio in por_numero:
        return numero_folio
    if numero_guardado and numero_guardado in por_numero and _compatible(t, por_numero[numero_guardado]):
        return numero_guardado
    if t is not None:
        clinicos = [i for i in ingresos if i['clinico']]
        dentro = [i for i in clinicos if i['fecha_ingreso'] <= t and (i['fin'] is None or t <= i['fin'])]
        if dentro:
            return max(dentro, key=lambda i: i['fecha_ingreso'])['numero']
        antes = [i for i in clinicos if i['fecha_ingreso'] - MARGEN_TRIAJE_ANTES <= t < i['fecha_ingreso']]
        if antes:
            return min(antes, key=lambda i: i['fecha_ingreso'])['numero']
    if numero_guardado and numero_guardado in por_numero:
        return numero_guardado  # sin fecha útil: se respeta lo guardado
    return CLAVE_TRIAJE_SIN_INGRESO if es_triaje else CLAVE_SIN_INGRESO


def _folios_a_ingreso(doc, folios):
    from frecuenciafetal.sala_partos_db import consultar_ingresos_de_folios

    folios = {f for f in folios if f is not None}
    if not folios:
        return {}
    clave = f'folios_ingreso:{doc}:{len(folios)}:{max(folios)}'
    guardado = cache.get(clave)
    if guardado is None:
        guardado = consultar_ingresos_de_folios(folios)
        if guardado:
            cache.set(clave, guardado, _CACHE_SEGUNDOS)
    return guardado


def asignar_mediciones_meows(doc, ingresos, solo_triaje=False):
    """{clave de ingreso: [id de Medicion MEOWS, ...]} -- solo_triaje: solo
    las tomas registradas en Triaje (origen='triaje')."""
    from meows.models import Medicion

    tomas = Medicion.objects.filter(paciente__numero_documento=doc)
    if solo_triaje:
        tomas = tomas.filter(origen='triaje')
    filas = list(
        tomas
        .order_by('fecha_hora')
        .values('id', 'fecha_hora', 'origen', 'dinamica_folio', 'atencion__numero_ingreso')
    )
    # Sin ingresos de Dinámica (sin conexión) no hay a qué ingreso llevar un folio.
    folios = {}
    if any(i['fuente'] == 'dinamica' for i in ingresos):
        folios = _folios_a_ingreso(doc, [f['dinamica_folio'] for f in filas if f['origen'] == 'dinamica'])
    grupos = {}
    for f in filas:
        clave = asignar_ingreso(
            f['fecha_hora'], ingresos,
            numero_guardado=f['atencion__numero_ingreso'] or '',
            numero_folio=folios.get(f['dinamica_folio'], '') if f['dinamica_folio'] is not None else '',
            es_triaje=f['origen'] == 'triaje',
        )
        grupos.setdefault(clave, []).append(f['id'])
    _separar_triaje_actual(grupos, {f['id']: f['fecha_hora'] for f in filas})
    return grupos


def _separar_triaje_actual(grupos, fecha_por_id):
    """2026-10-05: de las tomas de triaje sin ingreso, la última visita
    (tomas a menos de HUECO_ENTRE_VISITAS_TRIAJE entre sí) pasa a
    CLAVE_TRIAJE_ACTUAL si sigue vigente; las visitas anteriores se quedan en
    "Triajes sin ingreso"."""
    ids = sorted(grupos.get(CLAVE_TRIAJE_SIN_INGRESO, []), key=lambda i: fecha_por_id[i])
    if not ids or timezone.now() - fecha_por_id[ids[-1]] > VIGENCIA_TRIAJE_ACTUAL:
        return
    inicio = len(ids) - 1
    while inicio > 0 and fecha_por_id[ids[inicio]] - fecha_por_id[ids[inicio - 1]] <= HUECO_ENTRE_VISITAS_TRIAJE:
        inicio -= 1
    grupos[CLAVE_TRIAJE_ACTUAL] = ids[inicio:]
    if inicio:
        grupos[CLAVE_TRIAJE_SIN_INGRESO] = ids[:inicio]
    else:
        del grupos[CLAVE_TRIAJE_SIN_INGRESO]


def asignar_registros_posparto(doc, ingresos):
    """{clave de ingreso: [id de RegistroParto, ...]} -- por la fecha en que
    se abrió el registro (durante el parto)."""
    from frecuenciafetal.models import RegistroParto

    grupos = {}
    for f in (RegistroParto.objects.filter(identificacion=doc).order_by('created_at')
              .values('id', 'created_at', 'atencion__numero_ingreso')):
        clave = asignar_ingreso(f['created_at'], ingresos, numero_guardado=f['atencion__numero_ingreso'] or '')
        grupos.setdefault(clave, []).append(f['id'])
    return grupos


def asignar_controles_trabajo_parto(doc, ingresos):
    """
    {clave de ingreso: {id de Formulario: [id de Medicion, ...]}}.
    Cada CONTROL (medición) se asigna por su hora: una hoja antigua que se
    siguió usando en un reingreso aparece en los dos ingresos, cada uno con
    sus propios controles. Una hoja sin controles se ubica por su creación.
    """
    from trabajoparto.models import Formulario, Medicion

    hojas = {
        f['id']: f for f in
        Formulario.objects.filter(paciente__num_identificacion=doc)
        .values('id', 'created_at', 'atencion__numero_ingreso')
    }
    grupos = {}
    con_controles = set()
    for m in (Medicion.objects.filter(formulario_id__in=list(hojas))
              .order_by('tomada_en').values('id', 'formulario_id', 'tomada_en')):
        hoja = hojas[m['formulario_id']]
        clave = asignar_ingreso(m['tomada_en'], ingresos, numero_guardado=hoja['atencion__numero_ingreso'] or '')
        grupos.setdefault(clave, {}).setdefault(m['formulario_id'], []).append(m['id'])
        con_controles.add(m['formulario_id'])
    for hoja_id, hoja in hojas.items():
        if hoja_id not in con_controles:
            clave = asignar_ingreso(hoja['created_at'], ingresos, numero_guardado=hoja['atencion__numero_ingreso'] or '')
            grupos.setdefault(clave, {}).setdefault(hoja_id, [])
    return grupos


def conteos_ingreso_actual(doc):
    """
    2026-10-05: contadores y estado de la tarjeta de Sala de Partos, SOLO del
    ingreso actual -- lo mismo que muestra cada módulo al abrirlo (selector de
    ingresos). Antes se contaba todo el historial: una paciente con tomas en
    ingresos anteriores salía con "MEOWS 2" y al abrir el formato no había
    nada, y un ROJO de hace meses la dejaba en CRÍTICO para siempre.
    Sin ingreso actual (triaje sin ingreso, Dinámica caída) se cuenta todo,
    como antes.
    """
    from frecuenciafetal.models import RegistroParto
    from meows.models import Medicion
    from trabajoparto.models import Formulario

    ingresos, _, actual = ingresos_de_paciente(doc)
    grupos_meows = asignar_mediciones_meows(doc, ingresos)
    if actual:
        mediciones = Medicion.objects.filter(id__in=grupos_meows.get(actual, []))
        fetal = len(asignar_registros_posparto(doc, ingresos).get(actual, []))
        parto = len(asignar_controles_trabajo_parto(doc, ingresos).get(actual, {}))
    elif CLAVE_TRIAJE_ACTUAL in grupos_meows:
        # Volvió a triaje sin ingreso: solo esta visita (lo de ingresos
        # anteriores ya no cuenta, ver CLAVE_TRIAJE_ACTUAL).
        mediciones = Medicion.objects.filter(id__in=grupos_meows[CLAVE_TRIAJE_ACTUAL])
        fetal = parto = 0
    else:
        mediciones = Medicion.objects.filter(paciente__numero_documento=doc)
        fetal = RegistroParto.objects.filter(identificacion=doc).count()
        parto = Formulario.objects.filter(paciente__num_identificacion=doc).count()
    riesgos = set(mediciones.values_list('meows_riesgo', flat=True))
    estado = 'CRÍTICO' if 'ROJO' in riesgos else 'ALERTA' if 'AMARILLO' in riesgos else 'ESTABLE'
    return {
        'mediciones_count': mediciones.count(),
        'fetal_count': fetal,
        'parto_count': parto,
        'estado_global': estado,
    }


def asignar_registros(doc, modulo, ingresos):
    if modulo == 'meows':
        return asignar_mediciones_meows(doc, ingresos)
    if modulo == 'triaje':
        return asignar_mediciones_meows(doc, ingresos, solo_triaje=True)
    if modulo == 'control_posparto':
        return asignar_registros_posparto(doc, ingresos)
    if modulo == 'trabajo_parto':
        return asignar_controles_trabajo_parto(doc, ingresos)
    raise ValueError(f'Módulo desconocido: {modulo}')


# ---------------------------------------------------------------------------
# Fecha de inicio de uso de la app
# ---------------------------------------------------------------------------
def fecha_inicio_app():
    configurada = getattr(settings, 'FECHA_INICIO_APP', '')
    if configurada:
        try:
            return _aware(datetime.strptime(configurada, '%Y-%m-%d'))
        except ValueError:
            logger.warning('FECHA_INICIO_APP=%r no es una fecha AAAA-MM-DD; se ignora.', configurada)
    guardada = cache.get('fecha_inicio_app')
    if guardada is not None:
        return guardada
    from django.db.models import Min
    from frecuenciafetal.models import RegistroParto
    from meows.models import Medicion
    from trabajoparto.models import Formulario
    from .models import AtencionParto

    candidatas = [
        AtencionParto.objects.aggregate(m=Min('fecha_inicio'))['m'],
        RegistroParto.objects.aggregate(m=Min('created_at'))['m'],
        Formulario.objects.aggregate(m=Min('created_at'))['m'],
        # Las tomas de Dinámica pueden traer fechas anteriores a la app: solo
        # cuentan las registradas aquí (triaje / manuales).
        Medicion.objects.exclude(origen='dinamica').aggregate(m=Min('fecha_hora'))['m'],
    ]
    fecha = min((c for c in candidatas if c is not None), default=timezone.now())
    cache.set('fecha_inicio_app', fecha, 3600)
    return fecha


# ---------------------------------------------------------------------------
# Edición permitida
# ---------------------------------------------------------------------------
def editable_hasta(ingreso):
    """None = sin límite (en curso / sin egreso); si no, el momento en que el
    ingreso pasa a solo consulta."""
    if ingreso is None or not ingreso.get('fecha_egreso'):
        return None
    return ingreso['fecha_egreso'] + _gracia()


def es_editable(ingreso):
    hasta = editable_hasta(ingreso)
    return hasta is None or timezone.now() <= hasta


def _es_administrador(usuario):
    return bool(usuario and getattr(usuario, 'is_authenticated', False)
                and (usuario.is_superuser or usuario.is_staff))


def motivo_bloqueo_edicion(atencion, usuario=None, creado_en=None):
    """
    None si se puede guardar sobre `atencion`; si no, el mensaje para el
    usuario. Bloquea solo cuando Dinámica CONFIRMA que el ingreso egresó hace
    más del período de gracia -- ante cualquier duda (sin conexión, sin
    número de ingreso) se permite, para no frenar la atención.

    `creado_en`: cuándo se creó el registro. Si fue DESPUÉS de cerrar el
    ingreso (egreso + gracia), no puede ser de ese ingreso -- quedó ligado a
    una atención equivocada (p. ej. se creó con Dinámica sin respuesta) -- y
    no se bloquea.
    """
    from frecuenciafetal.sala_partos_db import consultar_estado_ingreso

    if atencion is None or not (atencion.numero_ingreso or '').strip() or _es_administrador(usuario):
        return None
    numero = atencion.numero_ingreso.strip()
    clave = f'estado_ingreso:{numero}'
    estado = cache.get(clave)
    if estado is None:
        try:
            estado = consultar_estado_ingreso(numero)
        except Exception:
            estado = None
        # Sin respuesta de Dinámica no se bloquea (y se vuelve a preguntar pronto).
        cache.set(clave, estado or {}, _CACHE_SEGUNDOS if estado else 30)
        estado = estado or {}
    fecha_egreso = _aware(estado.get('fecha_egreso'))
    if fecha_egreso is None or timezone.now() <= fecha_egreso + _gracia():
        return None
    if creado_en is not None and creado_en > fecha_egreso + _gracia():
        return None
    horas = getattr(settings, 'INGRESO_HORAS_GRACIA_EDICION', 24)
    return (
        f'El ingreso {numero} egresó el {timezone.localtime(fecha_egreso):%d/%m/%Y %I:%M %p}. '
        f'Pasadas {horas} h del egreso sus registros quedan en solo consulta; '
        'si hace falta una corrección, solicítela a un administrador.'
    )


# ---------------------------------------------------------------------------
# Resumen para el selector
# ---------------------------------------------------------------------------
def _fmt(dt):
    return timezone.localtime(dt).strftime('%d/%m/%Y') if dt else ''


def _fmt_hora(dt):
    return timezone.localtime(dt).strftime('%d/%m/%Y %I:%M %p') if dt else ''


# Formatos del repositorio (repositorio.FORMATOS) que produce cada módulo.
FORMATOS_DEL_MODULO = {
    'meows': ('meows', 'triaje'),
    'trabajo_parto': ('trabajo_parto',),
    'control_posparto': ('control_posparto',),
    'triaje': ('triaje',),
}


def _detalle_registros(modulo, datos):
    if modulo == 'meows':
        n = len(datos)
        return n, f'{n} toma{"s" if n != 1 else ""} MEOWS'
    if modulo == 'triaje':
        n = len(datos)
        return n, f'{n} toma{"s" if n != 1 else ""} de triaje'
    if modulo == 'control_posparto':
        n = len(datos)
        return n, f'{n} registro{"s" if n != 1 else ""} posparto'
    hojas = len(datos)
    controles = sum(len(v) for v in datos.values())
    texto = f'{hojas} hoja{"s" if hojas != 1 else ""}'
    if controles:
        texto += f' · {controles} registro{"s" if controles != 1 else ""}'
    return hojas, texto


def resumen_ingresos(doc, modulo, ingreso_elegido='', fresco=False):
    """Datos del selector de ingresos de `modulo` (JSON-serializable) y la
    asignación calculada, en una sola pasada."""
    from .models import DocumentoRepositorio
    from .repositorio import _limpiar

    ingresos, dinamica_ok, actual = ingresos_de_paciente(doc, fresco=fresco)
    grupos = asignar_registros(doc, modulo, ingresos)
    inicio_app = fecha_inicio_app()

    # Envíos al repositorio por ingreso: todos los formatos (para el selector)
    # y solo los de ESTE módulo (para el sello "Guardado en la NAS").
    formatos_modulo = FORMATOS_DEL_MODULO[modulo]
    nas, nas_modulo = {}, {}
    for d in (DocumentoRepositorio.objects.filter(cedula=_limpiar(doc))
              .order_by('creado_en').values('numero_ingreso', 'estado', 'creado_en', 'formato')):
        destinos = [nas] + ([nas_modulo] if d['formato'] in formatos_modulo else [])
        for tabla in destinos:
            info = tabla.setdefault(d['numero_ingreso'], {'enviados': 0, 'errores': 0, 'ultimo': None, 'ultimo_error': None})
            if d['estado'] == DocumentoRepositorio.ESTADO_ENVIADO:
                info['enviados'] += 1
                info['ultimo'] = d['creado_en']
            elif d['estado'] == DocumentoRepositorio.ESTADO_ENVIANDO:
                continue  # 2026-10-01: envío en curso / sin confirmar -- ni éxito ni error
            else:
                info['errores'] += 1
                info['ultimo_error'] = d['creado_en']

    opciones = []
    for i in ingresos:
        datos = grupos.get(i['numero'], {} if modulo == 'trabajo_parto' else [])
        n, detalle = _detalle_registros(modulo, datos)
        vacio_nas = {'enviados': 0, 'errores': 0, 'ultimo': None, 'ultimo_error': None}
        info_nas = nas.get(i['numero'], vacio_nas)
        info_mod = nas_modulo.get(i['numero'], vacio_nas)
        hasta = editable_hasta(i)
        antes_de_la_app = i['fecha_ingreso'] is not None and i['fecha_ingreso'] < inicio_app
        if n:
            texto_vacio = ''
            if antes_de_la_app:
                detalle += ' · parte en físico'
        elif antes_de_la_app:
            texto_vacio = 'Registros en físico (antes de la implementación de la app)'
        else:
            texto_vacio = 'Sin registros de este módulo en este ingreso'
        opciones.append({
            'numero': i['numero'],
            'fecha_ingreso': _fmt(i['fecha_ingreso']),
            'fecha_egreso': _fmt(i['fecha_egreso']),
            'tipo': i['tipo'],
            'tipo_texto': TIPOS_TEXTO.get(i['tipo'], ''),
            'anulado': i['anulado'],
            'en_curso': i['en_curso'],
            'es_actual': i['numero'] == actual,
            'registros': n,
            'detalle': detalle if n else texto_vacio,
            'vacio': not n,
            'nas_enviados': info_nas['enviados'],
            'nas_errores': info_nas['errores'],
            'nas_modulo_enviados': info_mod['enviados'],
            'nas_modulo_ultimo': _fmt_hora(info_mod['ultimo']),
            # Error pendiente: el último intento de este módulo falló y no hubo
            # un envío exitoso después.
            'nas_modulo_error': bool(info_mod['ultimo_error'] and (not info_mod['ultimo'] or info_mod['ultimo_error'] > info_mod['ultimo'])),
            'editable': es_editable(i),
            'editable_hasta': _fmt_hora(hasta),
            # Por defecto solo se listan los ingresos que interesan aquí; las
            # consultas externas, laboratorios y anulados quedan en "Ver todos".
            'relevante': bool(n or info_nas['enviados'] or info_nas['errores']
                              or (i['clinico'] and not i['anulado']) or i['numero'] == actual),
        })
    for clave, titulo in ((CLAVE_TRIAJE_ACTUAL, 'Triaje actual (sin ingreso)'),
                          (CLAVE_TRIAJE_SIN_INGRESO, 'Triajes sin ingreso'),
                          (CLAVE_SIN_INGRESO, 'Registros sin ingreso asociado')):
        datos = grupos.get(clave)
        if datos:
            n, detalle = _detalle_registros(modulo, datos)
            # El triaje en curso se sigue pudiendo corregir (los otros no).
            triaje_actual = clave == CLAVE_TRIAJE_ACTUAL and not actual
            opciones.append({
                'numero': clave, 'especial': True, 'titulo': titulo, 'registros': n,
                'detalle': detalle, 'vacio': False, 'relevante': True, 'editable': triaje_actual,
                'en_curso': triaje_actual, 'es_actual': triaje_actual, 'anulado': False,
                'fecha_ingreso': '', 'fecha_egreso': '', 'tipo': '', 'tipo_texto': '',
                'nas_enviados': 0, 'nas_errores': 0, 'nas_modulo_enviados': 0,
                'nas_modulo_ultimo': '', 'nas_modulo_error': False, 'editable_hasta': '',
            })

    elegido = limpiar_numero_ingreso(ingreso_elegido)
    numeros = {o['numero'] for o in opciones}
    if elegido not in numeros:
        # Sin ingreso actual: la visita a triaje en curso (no todo el historial).
        if actual in numeros:
            elegido = actual
        elif not actual and CLAVE_TRIAJE_ACTUAL in numeros:
            elegido = CLAVE_TRIAJE_ACTUAL
        else:
            elegido = ''
    seleccion = next((o for o in opciones if o['numero'] == elegido), None)
    triaje_en_curso = elegido == CLAVE_TRIAJE_ACTUAL and not actual
    return {
        'documento': doc,
        'modulo': modulo,
        'dinamica_ok': dinamica_ok,
        'actual': actual,
        'elegido': elegido,
        'es_actual': bool(elegido) and elegido == actual,
        'solo_consulta': bool(seleccion) and not triaje_en_curso and (elegido != actual or not seleccion['editable']),
        'seleccion': seleccion,
        'opciones': opciones,
        'inicio_app': _fmt(inicio_app),
        'horas_gracia': getattr(settings, 'INGRESO_HORAS_GRACIA_EDICION', 24),
        'destino_repositorio': 'la NAS' if settings.REPOSITORIO_MODO == 'nas' else 'la carpeta local de pruebas',
    }, grupos
