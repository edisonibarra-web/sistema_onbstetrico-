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

Duplicados (2026-09-25):
- El consecutivo se calcula y el archivo se escribe bajo un bloqueo por
  <cédula, ingreso, formato> (bloqueo_envio) y la escritura falla si el
  nombre ya existe -- dos envíos simultáneos nunca caen en el mismo nombre.
- Los envíos AUTOMÁTICOS (triaje, MEOWS al egreso) revisan "¿ya se envió?"
  DENTRO de un bloqueo: aunque la sincronización y la apertura del tablero
  coincidan, solo uno envía.
- Los envíos MANUALES (Finalizar / Reenviar) guardan la huella del contenido
  (huella_contenido): si no cambió nada desde el último envío de ese mismo
  registro, no se guarda otra copia idéntica (SinCambiosError) salvo que el
  usuario lo confirme (forzar=True).

Modo (settings.REPOSITORIO_MODO):
- "local": pruebas en el equipo local -- misma estructura en
  settings.REPOSITORIO_LOCAL_DIR, sin tocar la NAS.
- "nas":   producción -- FTP a la NAS (settings.REPO_FTP_*).
"""
import ftplib
import hashlib
import io
import logging
import os
import re
import threading
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection
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


class SinCambiosError(RepositorioError):
    """El formato no cambió desde su último envío: no se guarda otra copia
    idéntica. `documento` es ese último envío (DocumentoRepositorio)."""

    def __init__(self, documento):
        self.documento = documento
        fecha = timezone.localtime(documento.creado_en)
        por = f' por {documento.enviado_por}' if documento.enviado_por else ''
        super().__init__(
            'No hay cambios desde el último envío: el repositorio ya tiene este mismo '
            f'formato ({documento.nombre_archivo}, enviado el {fecha:%d/%m/%Y a las %I:%M %p}{por}). '
            'No se guardó otra copia.'
        )


class _ArchivoYaExiste(Exception):
    """guardar() encontró el nombre ocupado: se prueba el siguiente consecutivo."""


# ---------------------------------------------------------------------------
# Bloqueo entre procesos (workers del servidor web + sincronización con
# Dinámica). En SQL Server: sp_getapplock de la sesión -- lo ven todos los
# procesos que usan la misma base, y se libera solo si la conexión se cae.
# En otro motor (pruebas) queda un bloqueo dentro del proceso.
# ---------------------------------------------------------------------------
ESPERA_BLOQUEO_SEGUNDOS = 90
_bloqueos_locales = {}
_bloqueos_locales_guardia = threading.Lock()


@contextmanager
def bloqueo_envio(clave, espera_segundos=ESPERA_BLOQUEO_SEGUNDOS):
    """
    Bloqueo exclusivo por `clave`. Entrega True si se obtuvo; con
    espera_segundos=0 entrega False (sin esperar) si otro proceso lo tiene.
    Si se espera y no se obtiene, lanza RepositorioError.
    """
    recurso = ('sistema_obstetrico.repositorio|' + clave)[:255]
    if connection.vendor == 'microsoft':
        with connection.cursor() as cursor:
            cursor.execute(
                "SET NOCOUNT ON; DECLARE @r int; "
                "EXEC @r = sp_getapplock @Resource = %s, @LockMode = 'Exclusive', "
                "@LockOwner = 'Session', @LockTimeout = %s; SELECT @r;",
                [recurso, int(espera_segundos * 1000)],
            )
            obtenido = cursor.fetchone()[0] >= 0
        if not obtenido:
            if espera_segundos:
                raise RepositorioError(
                    'Hay otro envío de este mismo formato en curso; espere unos segundos e intente de nuevo.'
                )
            yield False
            return
        try:
            yield True
        finally:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "EXEC sp_releaseapplock @Resource = %s, @LockOwner = 'Session';", [recurso],
                    )
            except Exception:  # conexión caída: SQL Server ya lo liberó
                logger.warning('No se pudo liberar el bloqueo %s', recurso, exc_info=True)
        return

    with _bloqueos_locales_guardia:
        candado = _bloqueos_locales.setdefault(recurso, threading.RLock())
    if espera_segundos:
        obtenido = candado.acquire(timeout=espera_segundos)
    else:
        obtenido = candado.acquire(blocking=False)
    if not obtenido:
        if espera_segundos:
            raise RepositorioError(
                'Hay otro envío de este mismo formato en curso; espere unos segundos e intente de nuevo.'
            )
        yield False
        return
    try:
        yield True
    finally:
        candado.release()


# ---------------------------------------------------------------------------
# Huella del CONTENIDO de un PDF: el texto de cada página + las imágenes
# (firmas, logos), sin la fecha/hora de generación que los generadores
# estampan en cada descarga ("Generado: 25/09/2026 09:17:02" en Trabajo de
# Parto; "Fecha de generación: 25/09/2026 Hora: 09:29 AM" en MEOWS). Dos PDF
# del mismo registro sin cambios dan la misma huella aunque se generen en
# momentos distintos.
# ---------------------------------------------------------------------------
_RE_MARCAS_GENERACION = (
    re.compile(r'Generado:\s*\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(:\d{2})?'),
    re.compile(r'Fecha de generaci\S*n:\s*\d{1,2}/\d{1,2}/\d{4}\s*Hora:\s*\d{1,2}:\d{2}\s*[AaPp]\.?\s*[Mm]\.?'),
)


def huella_contenido(pdf_bytes):
    """SHA-256 del contenido del PDF, o '' si no se pudo leer (en ese caso
    no se compara: se envía como siempre)."""
    try:
        from pypdf import PdfReader
        lector = PdfReader(io.BytesIO(pdf_bytes))
        h = hashlib.sha256()
        for pagina in lector.pages:
            texto = pagina.extract_text() or ''
            for patron in _RE_MARCAS_GENERACION:
                texto = patron.sub('', texto)
            h.update(texto.encode('utf-8', 'replace'))
            h.update(b'\x00')
            for imagen in pagina.images:
                h.update(hashlib.sha256(imagen.data).digest())
            h.update(b'\x01')
        return h.hexdigest()
    except Exception:
        logger.warning('No se pudo calcular la huella del PDF', exc_info=True)
        return ''


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

    def existe(self, ruta):
        return self.raiz.joinpath(*ruta).is_dir()

    def listar(self, ruta):
        """(carpetas, archivos) en `ruta` (lista de segmentos relativa a la base)."""
        p = self.raiz.joinpath(*ruta)
        carpetas, archivos = [], []
        for entrada in os.scandir(p):
            (carpetas if entrada.is_dir() else archivos).append(entrada.name)
        return carpetas, archivos

    def crear_carpeta(self, ruta):
        self.raiz.joinpath(*ruta).mkdir(parents=False, exist_ok=True)

    def leer(self, ruta, nombre):
        return self.raiz.joinpath(*ruta, nombre).read_bytes()

    def guardar(self, ruta, nombre, contenido):
        """Escribe el archivo SIN reemplazar uno existente (_ArchivoYaExiste)."""
        destino = self.raiz.joinpath(*ruta, nombre)
        if destino.exists():
            raise _ArchivoYaExiste(nombre)
        temporal = destino.with_name(f'{nombre}.{os.getpid()}.{threading.get_ident()}.part')
        temporal.write_bytes(contenido)
        try:
            try:
                os.link(temporal, destino)  # atómico: falla si ya existe
            except FileExistsError:
                raise _ArchivoYaExiste(nombre)
            except OSError:
                # Sistema de archivos sin enlaces duros: creación exclusiva.
                try:
                    with open(destino, 'xb') as archivo:
                        archivo.write(contenido)
                except FileExistsError:
                    raise _ArchivoYaExiste(nombre)
        finally:
            try:
                temporal.unlink()
            except OSError:
                pass
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

    def existe(self, ruta):
        """¿Existe la carpeta exacta? Sin listar la carpeta padre."""
        actual = self.ftp.pwd()
        try:
            self.ftp.cwd(self._ruta(ruta))
            return True
        except ftplib.error_perm:
            return False
        finally:
            try:
                self.ftp.cwd(actual)
            except Exception:
                pass

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

    def leer(self, ruta, nombre):
        buffer = io.BytesIO()
        self.ftp.retrbinary(f'RETR {self._ruta(ruta, nombre)}', buffer.write)
        return buffer.getvalue()

    def _existe_archivo(self, ruta_completa):
        try:
            self.ftp.voidcmd('TYPE I')  # SIZE no se permite en modo ASCII en algunos servidores
            self.ftp.size(ruta_completa)
            return True
        except ftplib.error_perm:
            return False

    def guardar(self, ruta, nombre, contenido):
        """Sube el archivo SIN reemplazar uno existente (_ArchivoYaExiste).
        El RENAME del FTP reemplazaría el destino, así que se revisa justo
        antes (el bloqueo de guardar_en_repositorio evita que otro envío de
        esta app lo cree en medio)."""
        destino = self._ruta(ruta, nombre)
        if self._existe_archivo(destino):
            raise _ArchivoYaExiste(nombre)
        temporal = f'{destino}.{os.getpid()}.part'
        self.ftp.storbinary(f'STOR {temporal}', io.BytesIO(contenido))
        if self._existe_archivo(destino):
            try:
                self.ftp.delete(temporal)
            except ftplib.all_errors:
                pass
            raise _ArchivoYaExiste(nombre)
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
    Devuelve el nombre REAL (el existente si ya había una).

    2026-09-24: primero se prueba el nombre EXACTO (una sola operación). Solo
    si no existe se lista la carpeta padre para la búsqueda tolerante -- antes
    se listaba siempre, y la raíz del repositorio tiene una carpeta por cada
    paciente del hospital (lento en cada envío)."""
    if destino.existe([*ruta_padre, nombre]):
        return nombre
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
    # 2026-09-25: consecutivo + escritura bajo bloqueo (dos envíos simultáneos
    # del mismo formato calculaban el mismo número y el segundo reemplazaba
    # al primero). Además guardar() nunca reemplaza: si el nombre ya existe
    # (p. ej. lo creó otro aplicativo), se prueba el siguiente.
    with bloqueo_envio(f'archivo|{cedula_l}|{ingreso_l}|{slug}'), _destino() as destino:
        carpeta_paciente = _asegurar_carpeta(destino, [], cedula_l)
        carpeta_ingreso = _asegurar_carpeta(destino, [carpeta_paciente], ingreso_l)
        ruta = [carpeta_paciente, carpeta_ingreso]
        _, archivos = destino.listar(ruta)
        consecutivo = siguiente_consecutivo(archivos, slug, cedula_l)
        for _intento in range(20):
            nombre = f'{PREFIJO_CATEGORIA}_{slug}_{cedula_l}_{consecutivo}.pdf'
            try:
                ruta_final = destino.guardar(ruta, nombre, pdf_bytes)
                break
            except _ArchivoYaExiste:
                consecutivo += 1
        else:
            raise RepositorioError('No se encontró un consecutivo libre para el archivo.')
        return {
            'modo': destino.modo,
            'ruta': ruta_final,
            'nombre_archivo': nombre,
            'tamano_bytes': len(pdf_bytes),
        }


def _carpeta_ingreso(destino, cedula_l, ingreso_l):
    """Ruta REAL [carpeta cédula, carpeta ingreso] existente, o None.
    Prueba primero los nombres exactos (sin listar la raíz del repositorio)."""
    if destino.existe([cedula_l]):
        carpeta_paciente = cedula_l
    else:
        carpetas, _ = destino.listar([])
        carpeta_paciente = buscar_carpeta(carpetas, cedula_l)
    if carpeta_paciente is None:
        return None
    if destino.existe([carpeta_paciente, ingreso_l]):
        return [carpeta_paciente, ingreso_l]
    carpetas, _ = destino.listar([carpeta_paciente])
    carpeta_ingreso = buscar_carpeta(carpetas, ingreso_l)
    if carpeta_ingreso is None:
        return None
    return [carpeta_paciente, carpeta_ingreso]


def listar_documentos_ingreso(cedula, numero_ingreso):
    """
    Nombres de los archivos guardados en <cédula>/<ingreso> del repositorio
    -- los de esta app y los de cualquier otro aplicativo del hospital.
    [] si la carpeta no existe. Lanza excepción si el repositorio no responde.
    """
    cedula_l, ingreso_l = _limpiar(cedula), _limpiar(numero_ingreso)
    if not cedula_l or not ingreso_l.isdigit():
        return []
    with _destino() as destino:
        ruta = _carpeta_ingreso(destino, cedula_l, ingreso_l)
        if ruta is None:
            return []
        _, archivos = destino.listar(ruta)
    return sorted(a for a in archivos if not a.endswith('.part'))


def leer_documento_ingreso(cedula, numero_ingreso, nombre):
    """
    Contenido de un archivo de <cédula>/<ingreso>. Solo se entrega si el
    nombre está EXACTAMENTE en el listado de esa carpeta: nunca se arma una
    ruta con lo que escribe el usuario (evita pedir archivos de otra paciente).
    """
    cedula_l, ingreso_l = _limpiar(cedula), _limpiar(numero_ingreso)
    if not cedula_l or not ingreso_l.isdigit():
        raise RepositorioError('Documento no encontrado.')
    with _destino() as destino:
        ruta = _carpeta_ingreso(destino, cedula_l, ingreso_l)
        if ruta is None:
            raise RepositorioError('Documento no encontrado.')
        _, archivos = destino.listar(ruta)
        if nombre not in archivos or nombre.endswith('.part'):
            raise RepositorioError('Documento no encontrado.')
        return destino.leer(ruta, nombre)


def enviar_formato(pdf_bytes, *, cedula, numero_ingreso, formato,
                   atencion=None, referencia='', usuario='', huella=None):
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
        huella_contenido=(huella if huella is not None else huella_contenido(pdf_bytes or b''))[:64],
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
    para el ingreso actual, así no se pierden sus registros -- 2026-09-24:
    solo si la atención se abrió durante ese ingreso (o en las 24 h previas,
    triaje); una atención vieja de un ingreso anterior ya no se "adopta", se
    crea una nueva.

    Si Dinámica no responde se conserva el comportamiento anterior (la
    atención más reciente, o una nueva): así siguen funcionando las pacientes
    locales de prueba cuando la BD del hospital no está accesible.

    2026-09-24: si Dinámica SÍ responde y la paciente NO tiene ingreso (está en
    Triaje), ya no se crea una atención de Sala de Partos: Triaje y Sala de
    Partos son independientes, y esa atención vacía hacía aparecer en el menú
    los módulos MEOWS / Posparto / Trabajo de Parto de una paciente sin ingreso.
    Devuelve (atencion | None, info_ingreso | None).
    """
    from frecuenciafetal.sala_partos_db import consultar_ingreso_paciente, dinamica_disponible
    from .models import AtencionParto

    doc = (doc or '').strip()
    if not doc:
        return None, None

    info = None
    dinamica_respondio = False
    try:
        if dinamica_disponible():
            info = consultar_ingreso_paciente(doc)
            dinamica_respondio = True
    except Exception as exc:
        logger.warning('No se pudo consultar el ingreso en Dinámica: %s', exc)

    qs = AtencionParto.objects.filter(paciente=doc).order_by('-fecha_inicio')
    if not info:
        atencion = qs.first()
        if atencion is None and crear and not dinamica_respondio:
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
        # Ingreso nuevo para la app: el selector de ingresos debe verlo ya.
        from .ingresos import olvidar_ingresos_de_paciente
        olvidar_ingresos_de_paciente(doc)
        heredables = qs.filter(numero_ingreso='')
        if info['fecha_ingreso'] is not None:
            heredables = heredables.filter(fecha_inicio__gte=info['fecha_ingreso'] - MARGEN_TRIAJE_ANTES_DEL_INGRESO)
        atencion = heredables.first()
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


def mediciones_meows_del_ingreso(doc, atencion, hasta=None):
    """Tomas MEOWS del ingreso de `atencion`.

    2026-09-24: con la misma asignación que usa el selector de ingresos
    (obstetriciaunificador.ingresos: folio de Dinámica > atención > fecha), así
    el PDF de la NAS contiene exactamente lo que se ve al elegir ese ingreso.
    Si no se puede calcular (Dinámica sin respuesta), se usa el criterio
    anterior: desde 24 h antes de la fecha de ingreso (triaje) y, si se indica
    `hasta` (fecha de egreso), sin pasar de ahí."""
    from meows.models import Medicion

    qs = Medicion.objects.filter(paciente__numero_documento=doc)
    numero = (getattr(atencion, 'numero_ingreso', '') or '').strip()
    if numero:
        try:
            from .ingresos import asignar_mediciones_meows, ingresos_de_paciente
            ingresos, dinamica_ok, _ = ingresos_de_paciente(doc)
            if dinamica_ok and any(i['numero'] == numero for i in ingresos):
                ids = asignar_mediciones_meows(doc, ingresos).get(numero, [])
                return (Medicion.objects.filter(id__in=ids).select_related('formulario')
                        .prefetch_related('valores__parametro').order_by('fecha_hora'))
        except Exception as exc:
            logger.warning('Asignación de tomas por ingreso no disponible (%s); se usa la fecha.', exc)
    if atencion is not None and atencion.fecha_ingreso_dinamica:
        qs = qs.filter(fecha_hora__gte=atencion.fecha_ingreso_dinamica - MARGEN_TRIAJE_ANTES_DEL_INGRESO)
    if hasta is not None:
        qs = qs.filter(fecha_hora__lte=hasta)
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


def _enviar_manual(pdf, *, cedula, numero_ingreso, formato, atencion, referencia, usuario, forzar):
    """
    Envío por botón (Finalizar / Reenviar). Bajo un bloqueo por formato y
    registro: si el último envío EXITOSO de ese mismo registro en ese ingreso
    tiene el mismo contenido, no se guarda otra copia (SinCambiosError) --
    salvo forzar=True (el usuario confirmó que quiere otra copia). Con el
    bloqueo, dos clics simultáneos (dos pestañas) dejan un solo archivo.
    """
    from .models import DocumentoRepositorio

    huella = huella_contenido(pdf)
    cedula_l, ingreso_l = _limpiar(cedula), _limpiar(numero_ingreso)
    with bloqueo_envio(f'manual|{formato}|{cedula_l}|{ingreso_l}|{referencia}'):
        if huella and not forzar:
            ultimo = (
                DocumentoRepositorio.objects.filter(
                    cedula=cedula_l[:50], numero_ingreso=ingreso_l[:30], formato=formato,
                    referencia=str(referencia or '')[:64], estado=DocumentoRepositorio.ESTADO_ENVIADO,
                ).order_by('-creado_en', '-id').first()
            )
            if ultimo is not None and ultimo.huella_contenido == huella:
                raise SinCambiosError(ultimo)
        return enviar_formato(pdf, cedula=cedula, numero_ingreso=numero_ingreso, formato=formato,
                              atencion=atencion, referencia=referencia, usuario=usuario, huella=huella)


def enviar_meows(doc, usuario='', responsable=None, request=None, forzar=False):
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
    return _enviar_manual(pdf, cedula=doc, numero_ingreso=ingreso, formato='meows',
                          atencion=atencion, referencia='', usuario=usuario, forzar=forzar)


def enviar_trabajo_parto(formulario, usuario='', forzar=False):
    from trabajoparto.pdf_utils import generar_pdf_formulario_clinico

    doc = (formulario.paciente.num_identificacion or '').strip()
    atencion, ingreso = ingreso_para_envio(doc, formulario.atencion)
    if formulario.atencion_id is None and atencion is not None:
        formulario.atencion = atencion
        formulario.save(update_fields=['atencion'])
    pdf = _contenido_pdf(generar_pdf_formulario_clinico(formulario))
    return _enviar_manual(pdf, cedula=doc, numero_ingreso=ingreso, formato='trabajo_parto',
                          atencion=atencion, referencia=formulario.pk, usuario=usuario, forzar=forzar)


def enviar_control_posparto(registro, usuario='', forzar=False):
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
    return _enviar_manual(pdf, cedula=doc, numero_ingreso=ingreso, formato='control_posparto',
                          atencion=atencion, referencia=registro.pk, usuario=usuario, forzar=forzar)


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
    if _ya_enviado_o_agotado(previos, MAX_INTENTOS_FALLIDOS_TRIAJE):
        return None

    # 2026-09-25: la sincronización y la apertura del tablero pueden llegar
    # aquí al mismo tiempo: la revisión se repite DENTRO del bloqueo y, si
    # otro proceso ya está enviando este triaje, este no espera ni envía.
    with bloqueo_envio(f'auto|triaje|{_limpiar(doc)}|{ingreso}', espera_segundos=0) as obtenido:
        if not obtenido or _ya_enviado_o_agotado(previos, MAX_INTENTOS_FALLIDOS_TRIAJE):
            return None
        return _enviar_triaje(doc, atencion, ingreso, fecha_ingreso, triajes)


def _ya_enviado_o_agotado(previos, max_errores):
    from .models import DocumentoRepositorio

    if previos.filter(estado=DocumentoRepositorio.ESTADO_ENVIADO).exists():
        return True
    return previos.filter(estado=DocumentoRepositorio.ESTADO_ERROR).count() >= max_errores


def _enviar_triaje(doc, atencion, ingreso, fecha_ingreso, triajes):
    from meows.generador_pdf_meows import generar_pdf_meows
    from .models import DocumentoRepositorio

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


# ---------------------------------------------------------------------------
# MEOWS: envío AUTOMÁTICO al egreso de la paciente.
#
# Cuando el ingreso termina en Dinámica se genera el PDF MEOWS con las tomas
# de ESE ingreso y se guarda en su carpeta -- una sola vez por ingreso
# (DocumentoRepositorio.referencia = 'egreso'). 2026-09-24: el egreso es la
# fecha de egreso OFICIAL del ingreso (ADNINGRESO.AINFECEGRE), así también se
# envían las pacientes que nunca tuvieron cama; y se quitó el botón
# "Finalizar y enviar a repositorio" de MEOWS (a pedido): el envío es solo
# automático y cada envío aparece en la campana "NAS". Lo dispara la
# sincronización periódica con Dinámica, o a mano:
#   python manage.py enviar_pendientes_repositorio
# ---------------------------------------------------------------------------
REFERENCIA_EGRESO = 'egreso'
MAX_INTENTOS_FALLIDOS_EGRESO = 5
# Solo se revisan ingresos de los últimos N días (no todo el histórico).
# 2026-09-24: antes 30 -- una paciente con estancia de más de 30 días nunca
# se enviaba al egresar. Los ingresos ya enviados se descartan antes de
# consultar Dinámica, así que ampliar la ventana no agrega carga.
DIAS_REVISION_EGRESO = 180
# Tomas registradas hasta este margen después de la salida (registro tardío).
MARGEN_DESPUES_DEL_EGRESO = timedelta(hours=1)


def enviar_meows_al_egreso(atencion):
    """
    Envía el formato MEOWS del ingreso de `atencion` si ese ingreso ya egresó
    y aún no se envió. Devuelve el DocumentoRepositorio del envío, o None si
    no correspondía (sigue activo, ya enviado, sin tomas, sin conexión...).
    """
    from frecuenciafetal.sala_partos_db import consultar_estado_ingreso
    from meows.generador_pdf_meows import generar_pdf_meows
    from meows.models import Paciente as PacienteMeows
    from .models import DocumentoRepositorio

    doc = (atencion.paciente or '').strip()
    ingreso = (atencion.numero_ingreso or '').strip()
    if not doc or not ingreso:
        return None

    previos = DocumentoRepositorio.objects.filter(
        cedula=_limpiar(doc), numero_ingreso=ingreso, formato='meows', referencia=REFERENCIA_EGRESO,
    )
    if _ya_enviado_o_agotado(previos, MAX_INTENTOS_FALLIDOS_EGRESO):
        return None

    estado = consultar_estado_ingreso(ingreso)
    if not estado or estado.get('anulado') or not estado['fecha_egreso']:
        return None  # sigue en curso (o anulado / sin conexión)
    fecha_egreso = estado['fecha_egreso']
    if timezone.is_naive(fecha_egreso):
        fecha_egreso = timezone.make_aware(fecha_egreso, timezone.get_current_timezone())

    paciente = PacienteMeows.objects.filter(numero_documento=doc).first()
    if paciente is None:
        return None
    mediciones = list(mediciones_meows_del_ingreso(doc, atencion, hasta=fecha_egreso + MARGEN_DESPUES_DEL_EGRESO))
    if not mediciones:
        return None

    # 2026-09-25: dos sincronizaciones solapadas: solo una envía (ver triaje).
    with bloqueo_envio(f'auto|meows_egreso|{_limpiar(doc)}|{ingreso}', espera_segundos=0) as obtenido:
        if not obtenido or _ya_enviado_o_agotado(previos, MAX_INTENTOS_FALLIDOS_EGRESO):
            return None
        return _enviar_meows_egreso(doc, ingreso, atencion, paciente, mediciones)


def _enviar_meows_egreso(doc, ingreso, atencion, paciente, mediciones):
    from meows.generador_pdf_meows import generar_pdf_meows
    from .models import DocumentoRepositorio

    try:
        from meows.views import responsable_meows_mas_reciente
        responsable = responsable_meows_mas_reciente(paciente) or None
        pdf = _contenido_pdf(generar_pdf_meows(paciente, mediciones, responsable=responsable))
    except Exception as exc:
        logger.error('No se pudo generar el PDF MEOWS de egreso de %s/%s: %s', doc, ingreso, exc)
        return DocumentoRepositorio.objects.create(
            atencion=atencion, cedula=_limpiar(doc)[:50], numero_ingreso=ingreso,
            formato='meows', referencia=REFERENCIA_EGRESO, modo=settings.REPOSITORIO_MODO[:10],
            estado=DocumentoRepositorio.ESTADO_ERROR,
            detalle_error=f'Error generando el PDF: {type(exc).__name__}: {exc}'[:2000],
            enviado_por='automático (egreso)',
        )
    return enviar_formato(pdf, cedula=doc, numero_ingreso=ingreso, formato='meows',
                          atencion=atencion, referencia=REFERENCIA_EGRESO, usuario='automático (egreso)')


def enviar_meows_egresos_pendientes(dias=DIAS_REVISION_EGRESO):
    """Revisa las atenciones con ingreso de los últimos `dias` días y envía el
    MEOWS de las que ya egresaron. Devuelve [(documento, DocumentoRepositorio)]."""
    from django.db.models import Q
    from .models import AtencionParto

    desde = timezone.now() - timedelta(days=dias)
    from .models import DocumentoRepositorio
    ya_enviados = DocumentoRepositorio.objects.filter(
        formato='meows', referencia=REFERENCIA_EGRESO, estado=DocumentoRepositorio.ESTADO_ENVIADO,
    ).values('numero_ingreso')
    atenciones = (
        AtencionParto.objects.exclude(numero_ingreso='').exclude(paciente='')
        .exclude(numero_ingreso__in=ya_enviados)
        .filter(Q(fecha_ingreso_dinamica__gte=desde) | Q(fecha_ingreso_dinamica__isnull=True, fecha_inicio__gte=desde))
    )
    enviados = []
    for atencion in atenciones:
        try:
            resultado = enviar_meows_al_egreso(atencion)
        except Exception as exc:  # p. ej. Dinámica no responde: se reintenta en la próxima pasada
            logger.warning('MEOWS de egreso de %s no revisado: %s', atencion.paciente, exc)
            continue
        if resultado is not None:
            enviados.append((atencion.paciente, resultado))
    return enviados
