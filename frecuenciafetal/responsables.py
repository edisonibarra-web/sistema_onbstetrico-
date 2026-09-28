"""
2026-09-28: responsables del formato FRSPA-007 (Control Posparto Inmediato).

El formato lo diligencian por lo general dos o más personas. En vez de un
único campo "Responsable" escrito a mano (que la segunda persona pisaba), el
servidor firma solo cada cosa con el profesional en sesión:

- cada control (fetocardia, posparto, sangrado, globo, sutura, recién
  nacido) guarda registrado_por / registrado_en;
- el registro guarda creado_por (quien lo creó) y completado_por (quien lo
  cerró con "Guardar Registro Completo");
- ParticipacionRegistroParto lleva a TODOS los que escribieron algo.

resumen_responsables() arma, para la pantalla y el PDF, qué hizo cada uno.
"""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from sistema_obstetrico.auth_utils import nombre_profesional_sesion

logger = logging.getLogger(__name__)


def firma_sesion(request, con_responsable=False):
    """Campos de firma automática para guardar un control."""
    nombre = nombre_profesional_sesion(request)[:255] if request is not None else ''
    datos = {'registrado_por': nombre, 'registrado_en': timezone.now()}
    if con_responsable:
        datos['responsable'] = nombre[:200]
    return datos


def registrar_participacion(registro, request):
    """Deja constancia de que el profesional en sesión escribió en `registro`.
    Nunca rompe el guardado: ante cualquier error solo se registra en el log."""
    from .models import ParticipacionRegistroParto, RegistroParto

    if registro is None or getattr(registro, 'pk', None) is None:
        return
    try:
        nombre = (nombre_profesional_sesion(request) or '').strip()[:255]
        if not nombre:
            return
        ahora = timezone.now()
        usuario = getattr(getattr(request, 'user', None), 'username', '') or ''
        actualizadas = ParticipacionRegistroParto.objects.filter(
            registro_id=registro.pk, profesional=nombre,
        ).update(ultima_vez=ahora)
        if not actualizadas:
            try:
                with transaction.atomic():
                    ParticipacionRegistroParto.objects.create(
                        registro_id=registro.pk, profesional=nombre, usuario=usuario[:150],
                        primera_vez=ahora, ultima_vez=ahora,
                    )
            except IntegrityError:  # otra petición simultánea del mismo profesional
                pass
        if not (registro.creado_por or '').strip():
            RegistroParto.objects.filter(pk=registro.pk, creado_por='').update(creado_por=nombre)
            registro.creado_por = nombre
        # Compatibilidad: el campo de texto "Responsable del registro" (lo usan
        # listados y la campana NAS) queda con TODOS los participantes.
        nombres = list(
            ParticipacionRegistroParto.objects.filter(registro_id=registro.pk)
            .order_by('primera_vez').values_list('profesional', flat=True)
        )
        texto = ', '.join(nombres)[:200]
        if texto and texto != (registro.nombre_firma_paciente or ''):
            RegistroParto.objects.filter(pk=registro.pk).update(nombre_firma_paciente=texto)
            registro.nombre_firma_paciente = texto
    except Exception:
        logger.exception('No se pudo registrar la participación en el registro de parto')


def _rango_minutos(minutos):
    minutos = sorted(set(m for m in minutos if m is not None))
    if not minutos:
        return ''
    if len(minutos) == 1:
        return f'{minutos[0]} min'
    if len(minutos) <= 4:
        return ', '.join(str(m) for m in minutos) + ' min'
    return f'{minutos[0]} a {minutos[-1]} min'


def resumen_responsables(registro):
    """
    [{'nombre', 'desde', 'hasta', 'detalle': [..], 'inicio': bool, 'cierre': bool}]
    en orden de participación. Para registros anteriores a la firma
    automática (sin participaciones), se reconstruye con lo que haya
    (responsable de cada control o el campo de texto del registro).
    """
    if registro is None or getattr(registro, 'pk', None) is None:
        return []
    personas = {}

    def persona(nombre):
        nombre = (nombre or '').strip()
        if not nombre:
            return None
        if nombre not in personas:
            personas[nombre] = {'nombre': nombre, 'desde': None, 'hasta': None, 'detalle': {},
                                'inicio': False, 'cierre': False}
        return personas[nombre]

    def tocar(p, momento):
        if p is None or momento is None:
            return
        p['desde'] = momento if p['desde'] is None else min(p['desde'], momento)
        p['hasta'] = momento if p['hasta'] is None else max(p['hasta'], momento)

    for part in registro.participaciones.all():
        p = persona(part.profesional)
        tocar(p, part.primera_vez)
        tocar(p, part.ultima_vez)

    def agregar(qs, etiqueta, con_minuto=True, respaldo_responsable=False):
        for c in qs:
            nombre = c.registrado_por or (getattr(c, 'responsable', '') if respaldo_responsable else '')
            p = persona(nombre)
            if p is None:
                continue
            tocar(p, c.registrado_en)
            p['detalle'].setdefault(etiqueta, []).append(getattr(c, 'minuto_control', None) if con_minuto else 1)

    agregar(registro.controles_fetocardia.all(), 'Fetocardia', con_minuto=False, respaldo_responsable=True)
    agregar(registro.controles_postparto.all(), 'Controles posparto', respaldo_responsable=True)
    agregar(registro.controles_sangrado.all(), 'Sangrado')
    agregar(registro.controles_globo.all(), 'Globo de seguridad')
    agregar(registro.controles_sutura.all(), 'Sutura y heridas')
    try:
        rn = registro.control_recien_nacido
    except Exception:
        rn = None
    if rn is not None:
        agregar([rn], 'Recién nacido', con_minuto=False)

    p = persona(registro.creado_por)
    if p is not None:
        p['inicio'] = True
        tocar(p, registro.created_at)
    p = persona(registro.completado_por)
    if p is not None:
        p['cierre'] = True
        tocar(p, registro.completado_en)

    if not personas:  # registro anterior a la firma automática
        for nombre in (registro.nombre_firma_paciente or registro.profesional_nombre or '').split(','):
            persona(nombre)

    salida = []
    for p in personas.values():
        detalle = []
        if p['inicio']:
            detalle.append('Inició el registro')
        for etiqueta, valores in p['detalle'].items():
            if etiqueta in ('Fetocardia',):
                detalle.append(f'{etiqueta}: {len(valores)} toma' + ('s' if len(valores) != 1 else ''))
            elif etiqueta == 'Recién nacido':
                detalle.append(etiqueta)
            else:
                rango = _rango_minutos(valores)
                detalle.append(f'{etiqueta}: {rango}' if rango else etiqueta)
        if p['cierre']:
            detalle.append('Cerró el registro')
        if not detalle:
            detalle.append('Datos del registro')
        salida.append({**p, 'detalle': detalle})
    ahora = timezone.now()
    salida.sort(key=lambda x: x['desde'] or ahora)
    return salida


def responsables_para_api(registro):
    return [
        {'nombre': r['nombre'], 'desde': r['desde'], 'hasta': r['hasta'], 'detalle': r['detalle']}
        for r in resumen_responsables(registro)
    ]


# Campos que no cuentan como "cambio" hecho por quien guarda (automáticos).
_CAMPOS_AUTOMATICOS = {'updated_at', 'created_at', 'registrado_en', 'registrado_por', 'estado',
                       'nombre_firma_paciente', 'creado_por', 'responsable'}


def valores_modelo(instancia):
    """Foto de los campos de `instancia` para saber si un guardado cambió algo
    (el autoguardado reenvía todo aunque nadie haya tocado nada)."""
    if instancia is None:
        return None
    return {
        f.attname: getattr(instancia, f.attname)
        for f in instancia._meta.concrete_fields
        if f.name not in _CAMPOS_AUTOMATICOS
    }
