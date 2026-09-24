"""
Envío de los formatos finales (PDF) de cada módulo al repositorio clínico.

Estructura en el repositorio (la misma que ya usan los demás aplicativos del
hospital en la NAS, verificada el 2026-09-23 sobre /repositorio_clinico):

    <base>/<cédula>/<número de ingreso>/otros_<formato>_<cédula>_<consecutivo>.pdf

    ej. repositorio_clinico/1007736561/1812342/otros_escala_meows_1007736561_1.pdf

- <número de ingreso> = ADNINGRESO.AINCONSEC de Dinámica.
- En cada ingreso se registran varios formatos (de este y otros aplicativos),
  así que antes de crear una carpeta se BUSCA una existente que coincida con la
  cédula / el ingreso. La comparación tolera espacios, puntos, guiones y
  mayúsculas (en la NAS hay carpetas como " 26081510286891", con un espacio
  al inicio).
- Nunca se sobrescribe un archivo: si el formato se vuelve a finalizar en el
  mismo ingreso, se guarda con el siguiente consecutivo.

Modo (settings.REPOSITORIO_MODO):
- "local": pruebas en el equipo local -- misma estructura en
  settings.REPOSITORIO_LOCAL_DIR, sin tocar la NAS.
- "nas":   producción -- FTP a la NAS (settings.REPO_FTP_*).
"""
import ftplib
import io
import logging
import os
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# formato (clave interna) -> parte del nombre del archivo en el repositorio.
FORMATOS = {
    'meows': 'escala_meows',
    'trabajo_parto': 'trabajo_de_parto',
    'control_posparto': 'control_posparto_inmediato',
    'triaje': 'triaje_obstetrico',
}
PREFIJO_CATEGORIA = 'otros'

_RE_CARACTERES_INVALIDOS = re.compile(r'[\\/:*?"<>|\s]')
_RE_IGNORAR_AL_COMPARAR = re.compile(r'[\s.\-_]')


class RepositorioError(Exception):
    pass


def _limpiar(valor):
    """Cédula / ingreso seguros para usar como nombre de carpeta o archivo."""
    return _RE_CARACTERES_INVALIDOS.sub('', str(valor or '').strip())


def _normalizar(nombre):
    return _RE_IGNORAR_AL_COMPARAR.sub('', str(nombre or '')).upper()


def buscar_carpeta(nombres_existentes, objetivo):
    """Nombre REAL de la carpeta existente que corresponde a `objetivo`
    (coincidencia exacta primero, luego normalizada), o None."""
    if objetivo in nombres_existentes:
        return objetivo
    clave = _normalizar(objetivo)
    coincidencias = sorted(n for n in nombres_existentes if _normalizar(n) == clave)
    return coincidencias[0] if coincidencias else None


def siguiente_consecutivo(nombres_archivos, slug, cedula):
    patron = re.compile(
        rf'^{re.escape(PREFIJO_CATEGORIA)}_{re.escape(slug)}_{re.escape(cedula)}_(\d+)\.pdf$',
        re.IGNORECASE,
    )
    usados = [int(m.group(1)) for m in map(patron.match, nombres_archivos) if m]
    return max(usados, default=0) + 1


# ---------------------------------------------------------------------------
# Destinos. Ambos exponen la misma interfaz mínima para que la lógica de
# búsqueda de carpetas / consecutivo sea UNA sola (y lo que se prueba en
# local sea exactamente lo que corre contra la NAS).
# ---------------------------------------------------------------------------
class _DestinoLocal:
    modo = 'local'

    def __init__(self):
        self.raiz = Path(settings.REPOSITORIO_LOCAL_DIR)
        self.raiz.mkdir(parents=True, exist_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def listar(self, ruta):
        """(carpetas, archivos) en `ruta` (lista de segmentos relativa a la base)."""
        p = self.raiz.joinpath(*ruta)
        carpetas, archivos = [], []
        for entrada in os.scandir(p):
            (carpetas if entrada.is_dir() else archivos).append(entrada.name)
        return carpetas, archivos

    def crear_carpeta(self, ruta):
        self.raiz.joinpath(*ruta).mkdir(parents=False, exist_ok=True)

    def guardar(self, ruta, nombre, contenido):
        destino = self.raiz.joinpath(*ruta, nombre)
        temporal = destino.with_name(nombre + '.part')
        temporal.write_bytes(contenido)
        os.replace(temporal, destino)
        return str(destino)


class _DestinoFTP:
    modo = 'nas'

    def __init__(self):
        if not (settings.REPO_FTP_HOST and settings.REPO_FTP_USER):
            raise RepositorioError('Faltan REPO_FTP_HOST / REPO_FTP_USER en el .env.')
        self.base = '/' + settings.REPO_FTP_BASE_PATH.strip('/')
        self.ftp = None

    def __enter__(self):
        clase = ftplib.FTP_TLS if settings.REPO_FTP_TLS else ftplib.FTP
        ftp = clase(timeout=settings.REPO_FTP_TIMEOUT)
        ftp.encoding = 'utf-8'
        ftp.connect(settings.REPO_FTP_HOST, settings.REPO_FTP_PORT)
        ftp.login(settings.REPO_FTP_USER, settings.REPO_FTP_PASSWORD)
        if settings.REPO_FTP_TLS:
            ftp.prot_p()
        self.ftp = ftp
        return self

    def __exit__(self, *exc):
        try:
            self.ftp.quit()
        except Exception:
            try:
                self.ftp.close()
            except Exception:
                pass
        return False

    def _ruta(self, ruta, nombre=None):
        partes = [self.base, *ruta] + ([nombre] if nombre else [])
        return '/'.join(p.strip('/') if i else p.rstrip('/') for i, p in enumerate(partes))

    def listar(self, ruta):
        carpetas, archivos = [], []
        # MLSD sin "facts": este servidor (Synology) rechaza OPTS MLST.
        for nombre, datos in self.ftp.mlsd(self._ruta(ruta)):
            if nombre in ('.', '..'):
                continue
            tipo = datos.get('type', '')
            if tipo == 'dir':
                carpetas.append(nombre)
            elif tipo == 'file':
                archivos.append(nombre)
        return carpetas, archivos

    def crear_carpeta(self, ruta):
        self.ftp.mkd(self._ruta(ruta))

    def guardar(self, ruta, nombre, contenido):
        destino = self._ruta(ruta, nombre)
        temporal = destino + '.part'
        self.ftp.storbinary(f'STOR {temporal}', io.BytesIO(contenido))
        self.ftp.rename(temporal, destino)
        subido = self.ftp.size(destino)
        if subido is not None and subido != len(contenido):
            raise RepositorioError(
                f'Tamaño en la NAS ({subido} B) distinto al generado ({len(contenido)} B).'
            )
        return destino


def _destino():
    if settings.REPOSITORIO_MODO == 'nas':
        return _DestinoFTP()
    if settings.REPOSITORIO_MODO == 'local':
        return _DestinoLocal()
    raise RepositorioError(
        f"REPOSITORIO_MODO='{settings.REPOSITORIO_MODO}' no válido (use 'local' o 'nas')."
    )


def _asegurar_carpeta(destino, ruta_padre, nombre):
    """Busca la carpeta `nombre` dentro de `ruta_padre` (tolerante) o la crea.
    Devuelve el nombre REAL (el existente si ya había una)."""
    carpetas, _ = destino.listar(ruta_padre)
    existente = buscar_carpeta(carpetas, nombre)
    if existente is not None:
        return existente
    destino.crear_carpeta([*ruta_padre, nombre])
    return nombre


def guardar_en_repositorio(pdf_bytes, cedula, numero_ingreso, formato):
    """
    Guarda el PDF en <base>/<cédula>/<ingreso>/ y devuelve
    {'modo', 'ruta', 'nombre_archivo', 'tamano_bytes'}. Lanza excepción si falla.
    """
    if formato not in FORMATOS:
        raise RepositorioError(f'Formato desconocido: {formato}')
    cedula_l, ingreso_l = _limpiar(cedula), _limpiar(numero_ingreso)
    if not cedula_l:
        raise RepositorioError('La paciente no tiene número de identificación.')
    if not ingreso_l:
        raise RepositorioError(
            'La paciente no tiene un número de ingreso en Dinámica: no se puede '
            'ubicar su carpeta en el repositorio.'
        )
    if not pdf_bytes:
        raise RepositorioError('El PDF generado está vacío.')

    slug = FORMATOS[formato]
    with _destino() as destino:
        carpeta_paciente = _asegurar_carpeta(destino, [], cedula_l)
        carpeta_ingreso = _asegurar_carpeta(destino, [carpeta_paciente], ingreso_l)
        ruta = [carpeta_paciente, carpeta_ingreso]
        _, archivos = destino.listar(ruta)
        consecutivo = siguiente_consecutivo(archivos, slug, cedula_l)
        nombre = f'{PREFIJO_CATEGORIA}_{slug}_{cedula_l}_{consecutivo}.pdf'
        ruta_final = destino.guardar(ruta, nombre, pdf_bytes)
        return {
            'modo': destino.modo,
            'ruta': ruta_final,
            'nombre_archivo': nombre,
            'tamano_bytes': len(pdf_bytes),
        }


def enviar_formato(pdf_bytes, *, cedula, numero_ingreso, formato,
                   atencion=None, referencia='', usuario=''):
    """
    Guarda el PDF en el repositorio y deja constancia en DocumentoRepositorio
    (también si falla). Nunca lanza excepción: el llamador revisa `.estado`.
    """
    from .models import DocumentoRepositorio

    registro = DocumentoRepositorio(
        atencion=atencion,
        cedula=_limpiar(cedula)[:50],
        numero_ingreso=_limpiar(numero_ingreso)[:30],
        formato=formato,
        referencia=str(referencia or '')[:64],
        modo=settings.REPOSITORIO_MODO[:10],
        enviado_por=(usuario or '')[:255],
    )
    try:
        resultado = guardar_en_repositorio(pdf_bytes, cedula, numero_ingreso, formato)
        registro.estado = DocumentoRepositorio.ESTADO_ENVIADO
        registro.modo = resultado['modo']
        registro.ruta = resultado['ruta'][:500]
        registro.nombre_archivo = resultado['nombre_archivo']
        registro.tamano_bytes = resultado['tamano_bytes']
        logger.info('Formato %s enviado al repositorio (%s): %s',
                    formato, registro.modo, registro.ruta)
    except Exception as exc:
        registro.estado = DocumentoRepositorio.ESTADO_ERROR
        registro.detalle_error = f'{type(exc).__name__}: {exc}'[:2000]
        logger.error('No se pudo enviar el formato %s al repositorio (%s): %s',
                     formato, settings.REPOSITORIO_MODO, registro.detalle_error)
    registro.save()
    return registro


# ---------------------------------------------------------------------------
# Ingreso activo <-> atención local
# ---------------------------------------------------------------------------
def resolver_atencion_ingreso(doc, crear=True):
    """
    Atención local (AtencionParto) correspondiente al ingreso de Dinámica de
    la paciente (el activo o, si ya egresó, el más reciente). Una atención por
    ingreso: si la paciente reingresa, se crea una atención nueva en vez de
    mezclar formatos de dos ingresos.

    Las atenciones creadas antes de existir numero_ingreso (vacío) se adoptan
    para el ingreso actual, así no se pierden sus registros.

    Si Dinámica no responde o la paciente no tiene ingreso (p. ej. triaje),
    se conserva el comportamiento anterior (la atención más reciente).
    Devuelve (atencion | None, info_ingreso | None).
    """
    from frecuenciafetal.sala_partos_db import consultar_ingreso_paciente
    from .models import AtencionParto

    doc = (doc or '').strip()
    if not doc:
        return None, None

    info = None
    try:
        info = consultar_ingreso_paciente(doc)
    except Exception as exc:
        logger.warning('No se pudo consultar el ingreso en Dinámica: %s', exc)

    qs = AtencionParto.objects.filter(paciente=doc).order_by('-fecha_inicio')
    if not info:
        atencion = qs.first()
        if atencion is None and crear:
            atencion = AtencionParto.objects.create(paciente=doc)
        return atencion, None

    ingreso = info['numero_ingreso']
    fecha_ingreso = info['fecha_ingreso']
    # Dinámica guarda hora local de Bogotá sin zona (igual que en
    # meows/services/dinamica_signos_vitales.py).
    if fecha_ingreso is not None and timezone.is_naive(fecha_ingreso):
        fecha_ingreso = timezone.make_aware(fecha_ingreso, timezone.get_current_timezone())
    info = {**info, 'fecha_ingreso': fecha_ingreso}
    atencion = qs.filter(numero_ingreso=ingreso).first()
    if atencion is None:
        atencion = qs.filter(numero_ingreso='').first()
        if atencion is not None:
            atencion.numero_ingreso = ingreso
            atencion.fecha_ingreso_dinamica = info['fecha_ingreso']
            atencion.save(update_fields=['numero_ingreso', 'fecha_ingreso_dinamica'])
        elif crear:
            atencion = AtencionParto.objects.create(
                paciente=doc,
                numero_ingreso=ingreso,
                fecha_ingreso_dinamica=info['fecha_ingreso'],
            )
    return atencion, info


def ingreso_para_envio(doc, atencion_origen=None):
    """(atención, número de ingreso) al que se debe asociar un formato: el de
    la atención del registro si ya lo tiene, o el ingreso actual en Dinámica."""
    if atencion_origen is not None and atencion_origen.numero_ingreso:
        return atencion_origen, atencion_origen.numero_ingreso
    atencion, _ = resolver_atencion_ingreso(doc)
    return atencion, (atencion.numero_ingreso if atencion else '')


# Las tomas MEOWS de triaje se registran ANTES del ingreso formal: se
# incluyen las de hasta este margen antes de la fecha de ingreso.
MARGEN_TRIAJE_ANTES_DEL_INGRESO = timedelta(hours=24)


def mediciones_meows_del_ingreso(doc, atencion):
    from meows.models import Medicion

    qs = Medicion.objects.filter(paciente__numero_documento=doc)
    if atencion is not None and atencion.fecha_ingreso_dinamica:
        qs = qs.filter(fecha_hora__gte=atencion.fecha_ingreso_dinamica - MARGEN_TRIAJE_ANTES_DEL_INGRESO)
    return qs.select_related('formulario').prefetch_related('valores__parametro').order_by('fecha_hora')


# ---------------------------------------------------------------------------
# Un envío por formato. Cada uno genera el PDF con el MISMO generador que usa
# su módulo para descargarlo (no hay un "segundo formato" distinto para la
# NAS). Lanzan RepositorioError si el formato no se puede enviar (validación);
# si se generó pero falló el guardado, devuelven el DocumentoRepositorio con
# estado='error'.
# ---------------------------------------------------------------------------
def _contenido_pdf(respuesta):
    """Los generadores devuelven bytes o un HttpResponse."""
    if isinstance(respuesta, (bytes, bytearray)):
        return bytes(respuesta)
    status = getattr(respuesta, 'status_code', 200)
    contenido = getattr(respuesta, 'content', b'')
    if status != 200:
        raise RepositorioError(contenido.decode('utf-8', 'replace')[:300] or f'HTTP {status}')
    return contenido


def enviar_meows(doc, usuario='', responsable=None, request=None):
    from meows.generador_pdf_meows import generar_pdf_meows
    from meows.models import Paciente as PacienteMeows

    doc = (doc or '').strip()
    paciente = PacienteMeows.objects.filter(numero_documento=doc).first()
    if paciente is None:
        raise RepositorioError('La paciente no está registrada en MEOWS.')
    atencion, ingreso = ingreso_para_envio(doc)
    mediciones = list(mediciones_meows_del_ingreso(doc, atencion))
    if not mediciones:
        raise RepositorioError('La paciente no tiene mediciones MEOWS en este ingreso.')
    if not responsable and request is not None:
        from meows.views import responsable_meows_default
        responsable = responsable_meows_default(request, paciente)
    pdf = _contenido_pdf(generar_pdf_meows(paciente, mediciones, responsable=responsable))
    return enviar_formato(pdf, cedula=doc, numero_ingreso=ingreso, formato='meows',
                          atencion=atencion, usuario=usuario)


def enviar_trabajo_parto(formulario, usuario=''):
    from trabajoparto.pdf_utils import generar_pdf_formulario_clinico

    doc = (formulario.paciente.num_identificacion or '').strip()
    atencion, ingreso = ingreso_para_envio(doc, formulario.atencion)
    if formulario.atencion_id is None and atencion is not None:
        formulario.atencion = atencion
        formulario.save(update_fields=['atencion'])
    pdf = _contenido_pdf(generar_pdf_formulario_clinico(formulario))
    return enviar_formato(pdf, cedula=doc, numero_ingreso=ingreso, formato='trabajo_parto',
                          atencion=atencion, referencia=formulario.pk, usuario=usuario)


def enviar_control_posparto(registro, usuario=''):
    from frecuenciafetal.pdf_generator import generar_pdf_registro

    if registro.completado_en is None:
        raise RepositorioError(
            'El registro aún no está cerrado ("Guardar Registro Completo"): '
            'solo se envían formatos finales.'
        )
    doc = (registro.identificacion or '').strip()
    atencion, ingreso = ingreso_para_envio(doc, registro.atencion)
    if registro.atencion_id is None and atencion is not None:
        registro.atencion = atencion
        registro.save(update_fields=['atencion'])
    pdf = _contenido_pdf(generar_pdf_registro(registro))
    return enviar_formato(pdf, cedula=doc, numero_ingreso=ingreso, formato='control_posparto',
                          atencion=atencion, referencia=registro.pk, usuario=usuario)


def resumen_envio(documento):
    """Respuesta JSON uniforme para el frontend."""
    ok = documento.estado == documento.ESTADO_ENVIADO
    destino = 'la carpeta local de pruebas' if documento.modo == 'local' else 'la NAS'
    return {
        'ok': ok,
        'estado': documento.estado,
        'modo': documento.modo,
        'numero_ingreso': documento.numero_ingreso,
        'nombre_archivo': documento.nombre_archivo,
        'ubicacion': f'{documento.cedula}/{documento.numero_ingreso}/{documento.nombre_archivo}' if ok else '',
        'mensaje': (
            f'Formato guardado en {destino}: {documento.cedula}/{documento.numero_ingreso}/{documento.nombre_archivo}'
            if ok else
            f'No se pudo guardar el formato en {destino}: {documento.detalle_error}'
        ),
    }


# ---------------------------------------------------------------------------
# Triaje: envío AUTOMÁTICO cuando la paciente recibe su ingreso.
#
# Las tomas de triaje (Medicion origen='triaje') se registran ANTES de que
# exista ingreso en Dinámica, así que en ese momento no hay carpeta
# <cédula>/<ingreso> donde guardarlas. En cuanto aparece el ingreso, se genera
# el PDF con esas tomas y se guarda en la carpeta de ESE ingreso -- una sola
# vez por ingreso. Lo disparan:
#   - la sincronización periódica con Dinámica (sincronizar_signos_vitales_dinamica),
#   - la apertura del tablero de la paciente en Sala de Partos,
#   - a mano: python manage.py enviar_triajes_pendientes
# ---------------------------------------------------------------------------
# Una toma de triaje pertenece a un ingreso si cae en esta ventana alrededor
# de la fecha del ingreso. Evita, p. ej., mandar el triaje de hoy a la carpeta
# de un ingreso de hace meses de una paciente que aún no ha sido ingresada.
VENTANA_TRIAJE_ANTES_DEL_INGRESO = timedelta(hours=24)
VENTANA_TRIAJE_DESPUES_DEL_INGRESO = timedelta(hours=6)
MAX_INTENTOS_FALLIDOS_TRIAJE = 5
RESPONSABLE_TRIAJE_AUTOMATICO = 'Envío automático al registrarse el ingreso (triaje)'


def responsable_reporte_triaje(mediciones):
    """Quienes registraron las tomas de triaje (Medicion.registrado_por), en
    orden de aparición; si ninguna lo tiene (tomas anteriores a ese campo),
    se aclara que el envío fue automático."""
    nombres = []
    for m in mediciones:
        nombre = (m.responsable_toma or '').strip()
        if nombre and nombre not in nombres:
            nombres.append(nombre)
    return ', '.join(nombres) or RESPONSABLE_TRIAJE_AUTOMATICO


def enviar_triaje_si_corresponde(doc):
    """
    Envía el formato de triaje de la paciente si ya tiene ingreso en Dinámica
    y aún no se envió para ese ingreso. Devuelve el DocumentoRepositorio del
    envío, o None si no correspondía enviar nada (sin triaje, sin ingreso,
    ya enviado, o demasiados intentos fallidos).
    """
    from meows.generador_pdf_meows import generar_pdf_meows
    from meows.models import Medicion
    from .models import DocumentoRepositorio

    doc = (doc or '').strip()
    if not doc:
        return None
    # Chequeo barato primero: la gran mayoría de pacientes no tiene triaje.
    triajes = Medicion.objects.filter(paciente__numero_documento=doc, origen='triaje')
    if not triajes.exists():
        return None

    atencion, info = resolver_atencion_ingreso(doc)
    if not info or atencion is None:
        return None  # sigue en triaje (sin ingreso todavía)
    ingreso = atencion.numero_ingreso
    fecha_ingreso = info['fecha_ingreso']
    if not ingreso or fecha_ingreso is None:
        return None

    previos = DocumentoRepositorio.objects.filter(cedula=_limpiar(doc), numero_ingreso=ingreso, formato='triaje')
    if previos.filter(estado=DocumentoRepositorio.ESTADO_ENVIADO).exists():
        return None
    if previos.filter(estado=DocumentoRepositorio.ESTADO_ERROR).count() >= MAX_INTENTOS_FALLIDOS_TRIAJE:
        return None

    mediciones = list(
        triajes.filter(
            fecha_hora__gte=fecha_ingreso - VENTANA_TRIAJE_ANTES_DEL_INGRESO,
            fecha_hora__lte=fecha_ingreso + VENTANA_TRIAJE_DESPUES_DEL_INGRESO,
        ).select_related('formulario', 'paciente').prefetch_related('valores__parametro').order_by('fecha_hora')
    )
    if not mediciones:
        return None  # el triaje no corresponde a este ingreso

    try:
        pdf = _contenido_pdf(generar_pdf_meows(
            mediciones[0].paciente, mediciones, responsable=responsable_reporte_triaje(mediciones),
        ))
    except Exception as exc:
        registro = DocumentoRepositorio.objects.create(
            atencion=atencion, cedula=_limpiar(doc)[:50], numero_ingreso=ingreso,
            formato='triaje', modo=settings.REPOSITORIO_MODO[:10],
            estado=DocumentoRepositorio.ESTADO_ERROR,
            detalle_error=f'Error generando el PDF: {type(exc).__name__}: {exc}'[:2000],
            enviado_por='automático',
        )
        logger.error('No se pudo generar el PDF de triaje de %s: %s', doc, exc)
        return registro
    return enviar_formato(pdf, cedula=doc, numero_ingreso=ingreso, formato='triaje',
                          atencion=atencion, usuario='automático')


def enviar_triajes_pendientes(dias=7):
    """
    Revisa las pacientes con tomas de triaje de los últimos `dias` días y
    envía las que ya tienen ingreso. Devuelve [(documento, DocumentoRepositorio)].
    """
    from meows.models import Medicion

    desde = timezone.now() - timedelta(days=dias)
    documentos = (
        Medicion.objects.filter(origen='triaje', fecha_hora__gte=desde)
        .order_by()  # sin el ordenamiento por defecto: SQL Server no admite ORDER BY fuera del DISTINCT
        .values_list('paciente__numero_documento', flat=True).distinct()
    )
    enviados = []
    for doc in documentos:
        try:
            resultado = enviar_triaje_si_corresponde(doc)
        except Exception as exc:  # p. ej. Dinámica no responde: se reintenta en la próxima pasada
            logger.warning('Triaje de %s no revisado: %s', doc, exc)
            continue
        if resultado is not None:
            enviados.append((doc, resultado))
    return enviados
