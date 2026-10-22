"""
2026-10-21: Control Posparto PENDIENTES -- registros abiertos (sin "Guardar
Registro Completo" y sin anular), con lo que les falta y el estado del egreso.

En producción solo 3 de cada 10 registros llegaban a la NAS: se quedaban a
medias entre turnos y, pasadas 24 h del egreso, ya no se podían completar en
pantalla. Este panel deja a la vista lo pendiente y avisa (contador en el
menú) cuando la paciente ya egresó y todavía hay tiempo de completarlo.
"""
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

DIAS_POR_DEFECTO = 15
_CACHE_ESTADO_SEGUNDOS = 120
_CACHE_RESUMEN_SEGUNDOS = 60
# 2026-10-21 (v2): el contador = cantidad de tarjetas del panel (antes contaba
# con otra regla y podía no coincidir con lo que se ve).
CLAVE_RESUMEN = 'posparto_pendientes_resumen_v8'  # v8: sin enlace al registro si la cédula no coincide con el ingreso


def _horas_gracia():
    return getattr(settings, 'INGRESO_HORAS_GRACIA_EDICION', 24)


def _estado_ingreso(numero):
    """consultar_estado_ingreso con caché corta (se pide uno por registro)."""
    from frecuenciafetal.sala_partos_db import consultar_estado_ingreso
    if not numero:
        return None
    clave = f'posparto_pendiente_estado:{numero}'
    estado = cache.get(clave)
    if estado is None:
        try:
            estado = consultar_estado_ingreso(numero) or {}
        except Exception:
            estado = {}
        cache.set(clave, estado, _CACHE_ESTADO_SEGUNDOS if estado else 30)
    return estado or None


def _situacion(registro):
    """('urgente'|'en_atencion'|'bloqueado'|'sin_datos_ingreso', texto, horas_restantes, egreso, limite).
    limite = hasta cuándo se puede completar en pantalla (egreso + horas de gracia)."""
    from obstetriciaunificador.ingresos import _aware
    numero = (getattr(registro.atencion, 'numero_ingreso', '') or '').strip()
    estado = _estado_ingreso(numero)
    if not estado:
        return 'sin_datos_ingreso', 'Sin dato del ingreso en Dinámica', None, None, None
    if estado.get('anulado'):
        return 'bloqueado', 'Ingreso anulado', None, None, None
    egreso = _aware(estado.get('fecha_egreso'))
    if egreso is None:
        return 'en_atencion', 'Paciente en atención', None, None, None
    limite = egreso + timedelta(hours=_horas_gracia())
    restante = limite - timezone.now()
    if restante.total_seconds() > 0:
        horas = max(1, int(restante.total_seconds() // 3600))
        return ('urgente', f'Egresó el {timezone.localtime(egreso):%d/%m %I:%M %p}. '
                           f'Quedan {horas} h para completarlo', horas, egreso, limite)
    return 'bloqueado', (f'Egresó el {timezone.localtime(egreso):%d/%m/%Y}: pasaron {_horas_gracia()} h, '
                         'solo el administrador puede completarlo'), None, egreso, limite


def _cedula_no_coincide(registro):
    """2026-10-22: texto si el ingreso del registro es de otra cédula en Dinámica."""
    from frecuenciafetal.views import ingreso_de_otra_paciente
    numero = (getattr(registro.atencion, 'numero_ingreso', '') or '').strip()
    if not numero:
        return ''
    clave = f'posparto_pendiente_cedula:{numero}:{registro.identificacion}'
    texto = cache.get(clave)
    if texto is None:
        texto = ingreso_de_otra_paciente(registro.atencion, registro.identificacion) or ''
        cache.set(clave, texto, _CACHE_ESTADO_SEGUNDOS)
    return texto.replace(' No se creó el registro: verifique la cédula.', '')


ORDEN = {'urgente': 0, 'en_atencion': 1, 'sin_datos_ingreso': 2, 'bloqueado': 3}


def registros_pendientes(dias=DIAS_POR_DEFECTO):
    """[{...}] de los registros abiertos CON DATOS de los últimos `dias` días,
    los más urgentes primero (egresados que aún se pueden completar).
    2026-10-21: los vacíos (sin datos del parto, controles ni recién nacido) no
    se listan: lo que interesa son los registros diligenciados que no llegaron
    a la NAS. Los vacíos se pueden anular desde el formulario."""
    from frecuenciafetal.models import RegistroParto
    from frecuenciafetal.views import registro_sin_datos_clinicos, requisitos_cierre

    desde = timezone.now() - timedelta(days=dias)
    registros = (RegistroParto.objects.filter(completado_en__isnull=True, anulado_en__isnull=True, created_at__gte=desde)
                 .select_related('atencion').order_by('created_at'))
    filas = []
    for r in registros:
        if registro_sin_datos_clinicos(r):
            continue
        requisitos = requisitos_cierre(r)
        faltan = [q['texto'] for q in requisitos if not q['ok']]
        situacion, texto, horas, egreso, limite = _situacion(r)
        # 2026-10-21: una sola categoría por registro (color de la tarjeta y
        # recuadro del resumen): gris > verde > rojo > azul.
        # 2026-10-21: una sola categoría por registro (color de la tarjeta y
        # recuadro del resumen): gris > verde > rojo > morado > azul. Un registro
        # completo también vence a las 24 h del egreso (después: administrador).
        if situacion == 'bloqueado':
            categoria = 'bloqueado'
        elif not faltan:
            categoria = 'completo'
        else:
            categoria = situacion
        filas.append({
            'id': str(r.pk),
            'paciente': r.nombre_paciente,
            'cedula': r.identificacion,
            'ingreso': getattr(r.atencion, 'numero_ingreso', '') or '',
            'atencion_id': r.atencion_id,
            'creado': timezone.localtime(r.created_at),
            'creado_por': r.creado_por or '',
            'completos': len(requisitos) - len(faltan),
            'total': len(requisitos),
            'faltan': faltan,
            'situacion': situacion,
            'situacion_texto': texto,
            'categoria': categoria,
            'egreso': egreso,
            'limite': limite,
            'listo': not faltan,
            'horas_restantes': horas,
            'cedula_no_coincide': _cedula_no_coincide(r),
        })
    filas.sort(key=lambda f: (ORDEN[f['situacion']], f['horas_restantes'] or 0, f['creado']))
    return filas


def _url_registro(f):
    from urllib.parse import urlencode
    params = {'doc': f['cedula']}
    if f['atencion_id']:
        params['atencion'] = f['atencion_id']
    if f['ingreso']:
        params['ingreso'] = f['ingreso']
    return '/fetal/?' + urlencode(params)


def resumen_pendientes():
    """Para el contador del menú y la alerta del encabezado (con caché):
    total = las tarjetas que muestra el panel (mismos días por defecto);
    urgentes = las rojas (egresaron y aún se pueden completar), con su detalle."""
    resumen = cache.get(CLAVE_RESUMEN)
    if resumen is None:
        filas = registros_pendientes()
        # Alerta del encabezado: toda egresada con plazo corriendo (dentro de las
        # 24 h), le falten datos o solo falte guardar. Ordenadas por lo que queda.
        rojas = sorted((f for f in filas if f['situacion'] == 'urgente'),
                       key=lambda f: f['limite'] or timezone.now())
        resumen = {
            'urgentes': len(rojas),
            'total': len(filas),
            # 2026-10-21: los de más de 24 h (gris) solo los ve el administrador.
            'total_personal': sum(1 for f in filas if f['categoria'] != 'bloqueado'),
            # 2026-10-21: aviso del menú = registros completos a los que solo les
            # falta "Guardar Registro Completo" (las egresadas van en el encabezado).
            'completos': sum(1 for f in filas if f['categoria'] == 'completo'),
            'detalle_urgentes': [
                {'paciente': f['paciente'], 'cedula': f['cedula'], 'ingreso': f['ingreso'],
                 'horas_restantes': f['horas_restantes'], 'url': '/fetal/pendientes/' if f['cedula_no_coincide'] else _url_registro(f),
                 'egreso_texto': f'{timezone.localtime(f["egreso"]):%d/%m/%Y %I:%M %p}' if f['egreso'] else '',
                 'completo': f['listo'],
                 'limite_ts': f['limite'].timestamp() if f['limite'] else None}
                for f in rojas[:15]
            ],
        }
        cache.set(CLAVE_RESUMEN, resumen, _CACHE_RESUMEN_SEGUNDOS)
    return resumen
