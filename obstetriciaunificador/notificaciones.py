"""
Campana "NAS" (2026-09-24): a quién se le muestra cada envío al repositorio.

Cada profesional ve solo los envíos de SUS PACIENTES: aquellas en las que
registró algo en los últimos DIAS_ACTIVIDAD días, reconocido por su nombre
(el mismo que queda en cada registro):
  - MEOWS: quien digitó la toma en Dinámica (responsable_dinamica) o quien la
    registró en Triaje (registrado_por).
  - Trabajo de Parto: responsable de cada control (Medicion.responsable) o de
    la hoja (Formulario.responsable).
  - Control Posparto: responsable de los controles de fetocardia y posparto,
    y quien cerró o firmó el registro.
  - Los formatos que la misma persona envió a mano.
Ven todos: los administradores (is_staff / is_superuser) y los usuarios del
grupo GRUPO_VER_TODAS (p. ej. jefes de enfermería que entran con Dinámica:
a esas cuentas el login les quita is_staff en cada ingreso, ver auth_dgh).

La sesión no trae el área/servicio del profesional (ver auth_dgh: solo
nombre, código médico, tarjeta, tipo e identificación), por eso el criterio
es por paciente atendida y no por área.

2026-09-24 -- HALLAZGO (revisión): el nombre del login (GENUSUARIO.USUDESCRI)
y el que Dinámica pone en las tomas (GENMEDICO.GMENOMCOM) son campos
distintos y pueden tener las palabras en otro orden (verificado con un
usuario real: 4 de 4 palabras iguales, orden distinto). Por eso:
  1) se comparan como CONJUNTO de palabras, sin títulos (Enf., Dr...);
  2) además del nombre del login se usa el GMENOMCOM del profesional, buscado
     en Dinámica con su código médico (queda guardado en la sesión).
"""
import logging
import re
import unicodedata
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

DIAS_ACTIVIDAD = 15  # 2026-09-24: antes 7, ampliado a pedido
_CACHE_SEGUNDOS = 60
GRUPO_VER_TODAS = 'Ve todas las notificaciones NAS'
_TITULOS = {'ENF', 'ENFERMERA', 'ENFERMERO', 'DR', 'DRA', 'DOCTOR', 'DOCTORA', 'LIC', 'AUX', 'JEFE', 'MD'}
# Mínimo de palabras para aceptar que un nombre "contenga" al otro (p. ej.
# uno con segundo apellido y otro sin él). Con menos, solo coincidencia exacta.
_MIN_PALABRAS_CONTENIDO = 3


def normalizar_nombre(nombre):
    """Mayúsculas, sin tildes y con un solo espacio: 'Enf.  Laura Gómez' ->
    'ENF. LAURA GOMEZ'. Los nombres se escriben distinto en cada módulo."""
    texto = unicodedata.normalize('NFKD', str(nombre or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', texto).strip().upper()


def palabras_nombre(nombre):
    """Conjunto de palabras del nombre, sin puntuación ni títulos."""
    palabras = re.findall(r'[A-Z0-9Ñ]+', normalizar_nombre(nombre))
    return frozenset(p for p in palabras if p not in _TITULOS and len(p) > 1)


def mismo_profesional(a, b):
    """¿Dos nombres (ya en palabras) son la misma persona? Mismas palabras en
    cualquier orden, o uno contenido en el otro si el corto tiene al menos
    _MIN_PALABRAS_CONTENIDO palabras."""
    if not a or not b:
        return False
    if a == b:
        return True
    corto, largo = (a, b) if len(a) <= len(b) else (b, a)
    return len(corto) >= _MIN_PALABRAS_CONTENIDO and corto <= largo


def es_administrador(usuario):
    return bool(
        usuario and getattr(usuario, 'is_authenticated', False)
        and (usuario.is_staff or usuario.is_superuser or usuario.groups.filter(name=GRUPO_VER_TODAS).exists())
    )


def nombres_del_profesional(request):
    """Nombres con los que puede aparecer el profesional en sesión en los
    registros: el del login y el de GENMEDICO (Dinámica), si tiene código."""
    from sistema_obstetrico.auth_utils import nombre_profesional_sesion

    nombres = {nombre_profesional_sesion(request)}
    info = request.session.get('dgh_info') or {}
    codigo = str(info.get('codigo_medico') or '').strip()
    if codigo:
        nombre_medico = info.get('nombre_medico_dinamica')
        if nombre_medico is None:
            nombre_medico = _nombre_medico_dinamica(codigo)
            if nombre_medico is not None:  # None = Dinámica sin respuesta: se reintenta luego
                info['nombre_medico_dinamica'] = nombre_medico
                request.session['dgh_info'] = info
        if nombre_medico:
            nombres.add(nombre_medico)
    return [n for n in nombres if n]


def _nombre_medico_dinamica(codigo):
    """GENMEDICO.GMENOMCOM del código médico; '' si no existe; None si
    Dinámica no respondió."""
    from django.conf import settings
    from django.db import connections
    from frecuenciafetal.sala_partos_db import dinamica_disponible

    if 'readonly' not in settings.DATABASES or not dinamica_disponible():
        return None
    try:
        with connections['readonly'].cursor() as cursor:
            cursor.execute('SELECT TOP 1 GMENOMCOM FROM GENMEDICO WHERE GMECODIGO = %s', [str(codigo)])
            fila = cursor.fetchone()
    except Exception as exc:
        logger.warning('No se pudo consultar GENMEDICO para la campana NAS: %s', exc)
        return None
    return (fila[0] or '').strip() if fila else ''


def documentos_del_profesional(nombres, dias=DIAS_ACTIVIDAD):
    """Documentos (cédulas) de las pacientes en las que el profesional (con
    cualquiera de sus `nombres`) registró algo en los últimos `dias` días."""
    from frecuenciafetal.models import (
        ControlFetocardia, ControlPostpartoInmediato, ParticipacionRegistroParto, RegistroParto,
    )
    from meows.models import Medicion as MedicionMeows
    from trabajoparto.models import Formulario, Medicion as MedicionParto

    if isinstance(nombres, str):
        nombres = [nombres]
    objetivos = [p for p in (palabras_nombre(n) for n in nombres) if p]
    if not objetivos:
        return set()
    clave = 'nas_docs_profesional:' + '|'.join(sorted(' '.join(sorted(o)) for o in objetivos)) + f':{dias}'
    guardado = cache.get(clave)
    if guardado is not None:
        return guardado

    desde = timezone.now() - timedelta(days=dias)
    # .order_by() antes de .distinct(): SQL Server no admite ORDER BY de campos
    # fuera del DISTINCT (los modelos tienen orden por defecto).
    fuentes = [
        MedicionMeows.objects.filter(fecha_hora__gte=desde)
        .values_list('paciente__numero_documento', 'responsable_dinamica', 'registrado_por'),
        MedicionParto.objects.filter(tomada_en__gte=desde)
        .values_list('formulario__paciente__num_identificacion', 'responsable'),
        Formulario.objects.filter(fecha_actualizacion__gte=desde)
        .values_list('paciente__num_identificacion', 'responsable'),
        ControlFetocardia.objects.filter(fecha__gte=desde.date())
        .values_list('registro__identificacion', 'responsable'),
        ControlPostpartoInmediato.objects.filter(fecha__gte=desde.date())
        .values_list('registro__identificacion', 'responsable'),
        RegistroParto.objects.filter(updated_at__gte=desde)
        .values_list('identificacion', 'completado_por', 'profesional_nombre', 'nombre_firma_paciente'),
        # 2026-09-28: cada profesional que diligenció parte del FRSPA-007.
        ParticipacionRegistroParto.objects.filter(ultima_vez__gte=desde)
        .values_list('registro__identificacion', 'profesional'),
    ]
    documentos = set()
    comparados = {}
    for filas in fuentes:
        for documento, *nombres_fila in filas.order_by().distinct():
            if not documento:
                continue
            for nombre in nombres_fila:
                if not nombre:
                    continue
                if nombre not in comparados:
                    palabras = palabras_nombre(nombre)
                    comparados[nombre] = any(mismo_profesional(palabras, o) for o in objetivos)
                if comparados[nombre]:
                    documentos.add(str(documento).strip())
                    break
    cache.set(clave, documentos, _CACHE_SEGUNDOS)
    return documentos


def envio_propio(enviado_por, nombres):
    palabras = palabras_nombre(enviado_por)
    return any(mismo_profesional(palabras, palabras_nombre(n)) for n in nombres)
