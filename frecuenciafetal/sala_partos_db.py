"""
Motor único de "pacientes activas" (áreas gineco-obstétricas) contra la BD
readonly del hospital (DGEMPRES_NEXUS). Solo lectura.

Reutilizado por MEOWS, Trabajo de Parto y Frecuencia Fetal/Sala de Partos
para evitar que cada módulo mantenga su propia consulta divergente contra
las mismas tablas.
"""
import re

from django.db import connections
from django.conf import settings

_RE_GRUPO_LETRA = re.compile(r'\b(AB|A|B|O)\b')
_RE_GRUPO_POSITIVO = re.compile(r'POSITIVO|\bPOS\b|\+')
_RE_GRUPO_NEGATIVO = re.compile(r'NEGATIVO|\bNEG\b|-')


def _normalizar_grupo_sanguineo(val):
    """
    Normaliza el grupo sanguíneo a formato O+/O-/A+/A-/B+/B-/AB+/AB- (el que usan
    los formularios). En HCMWINGIN el campo es texto libre capturado a mano
    ("O positivo", "o+", "AB+ sin presencia de hemoclasificación", "O RH POSITIVO",
    "O POS", etc.), así que se busca la letra y el signo por separado (en vez de
    exigir que estén contiguos) para no fallar cuando hay palabras intermedias
    como "RH".
    """
    if not val:
        return None
    texto = str(val).strip().upper()
    m_letra = _RE_GRUPO_LETRA.search(texto)
    if not m_letra:
        return None
    if _RE_GRUPO_NEGATIVO.search(texto):
        signo = '-'
    elif _RE_GRUPO_POSITIVO.search(texto):
        signo = '+'
    else:
        return None
    return f'{m_letra.group(1)}{signo}'


def _normalizar_edad_gestacional(val):
    """Convierte valor de edad gestacional a semanas (preservando decimales si existen)."""
    if val is None:
        return None
    try:
        f = float(str(val).replace(',', '.').split()[0])
        # Si es un número entero (ej: 38.0), devolver como int
        if f == int(f):
            return int(f)
        return round(f, 1) # Preservar un decimal (ej: 38.5)
    except (ValueError, IndexError, TypeError):
        return None


def _normalizar_gestas(val):
    """Convierte G (gestas) a entero, preservando el valor real (incluido 0) o
    None si no hay dato — no se fuerza un mínimo de 1, para no ocultar un dato
    faltante como si fuera un embarazo real."""
    if val is None:
        return None
    try:
        return int(round(float(val)))
    except (ValueError, TypeError):
        return None


def _listar_pacientes_activos_fallback_local(query=None, limit=50):
    """
    Respaldo para pruebas/desarrollo sin conexión a la BD hospitalaria (readonly).
    Lista pacientes que YA existen en la BD local de Django (trabajoparto.Paciente,
    con datos de ejemplo cargados por las migraciones de seed, ej. cédula
    1234567890), mapeados al mismo formato que devuelve la consulta externa,
    para que MEOWS, Trabajo de Parto y Frecuencia Fetal sigan siendo usables
    en pruebas cuando no hay VPN/red hacia el hospital.
    """
    from django.db.models import Q
    from trabajoparto.models import Paciente as TrabajoPartoPaciente

    qs = TrabajoPartoPaciente.objects.all().order_by('nombres')
    if query and query.strip():
        q = query.strip()
        qs = qs.filter(
            Q(num_identificacion__icontains=q) | Q(nombres__icontains=q)
        )

    out = []
    for paciente in qs[:limit]:
        formulario = paciente.formularios.order_by('-fecha_actualizacion').first()
        out.append({
            'nombre_paciente': paciente.nombres or None,
            'identificacion': paciente.num_identificacion or None,
            'edad_gestacional': getattr(formulario, 'edad_gestion', None),
            'gestas': getattr(formulario, 'gestas', None),
            'partos': getattr(formulario, 'partos', None),
            'cesareas': getattr(formulario, 'cesareas', None),
            'abortos': getattr(formulario, 'abortos', None),
            'fecha_nacimiento': paciente.fecha_nacimiento,
            'nombre_acompanante': None,
            'area': 'PRUEBAS (sin conexión a BD hospitalaria)',
            'folio': None,
            'numero_cama': None,
            'numero_ingreso': None,
            'historia_clinica': paciente.num_historia_clinica,
            'aseguradora': getattr(getattr(formulario, 'aseguradora', None), 'nombre', None),
            'diagnostico': getattr(formulario, 'diagnostico', None),
            'edad_anos': getattr(formulario, 'edad_snapshot', None),
            'fecha_ingreso': getattr(formulario, 'fecha_elabora', None),
            'grupo_sanguineo': paciente.tipo_sangre,
            'controles_prenatales': getattr(formulario, 'n_controles_prenatales', None),
            'origen': 'local_pruebas',
        })
    return out


def listar_pacientes_sala_partos(query=None, limit=50):
    """
    Lista las pacientes actualmente internadas (HESFECSAL IS NULL) en áreas
    gineco-obstétricas: Hospitalización Ginecobstetricia, Sala de Partos,
    Cuidado Intermedio Ginecobstetricia (HSUCODIGO '0304'/'0305'/'0307'),
    más cualquier ingreso marcado como gestante (ADNINGRESO.AINGESTAN = 1)
    sin importar la sala física en la que esté (cubre, p. ej., una gestante
    aún en observación de urgencias antes de trasladarla a piso gineco).

    query: opcional; filtra por nombre, identificación (documento) o texto de diagnóstico.
    limit: máximo de filas a devolver (por defecto 50).
    """
    if 'readonly' not in settings.DATABASES:
        return _listar_pacientes_activos_fallback_local(query=query, limit=limit)

    sql = """
    SELECT
        EST.HESFECING AS fecha_ingreso,
        PLA.GDENOMBRE AS aseguradora,
        PAC.GPANUMCAR AS historia_clinica,
        PAC.PACNUMDOC AS identificacion,
        RTRIM(ISNULL(PAC.PACPRINOM,'') + ' ' + ISNULL(PAC.PACSEGNOM,'') + ' ' + ISNULL(PAC.PACPRIAPE,'') + ' ' + ISNULL(PAC.PACSEGAPE,'')) AS nombre_paciente,
        PAC.GPAFECNAC AS fecha_nacimiento,
        RTRIM(ISNULL(ING.AIPRNOMACU,'') + ' ' + ISNULL(ING.AISENOMACU,'') + ' ' + ISNULL(ING.AIPRAPEACU,'') + ' ' + ISNULL(ING.AISEAPEACU,'')) AS nombre_acudiente,
        SUB.HSUNOMBRE AS area,
        FOL_DATA.folio,
        FOL_DATA.diagnostico,
        DATEDIFF(YEAR, PAC.GPAFECNAC, GETDATE()) AS edad_anos,
        MW_DATA.grupo_sanguineo,
        MW_DATA.edad_gestacional_raw,
        MW_DATA.G_gestas,
        MW_DATA.P,
        MW_DATA.C,
        MW_DATA.A,
        MW_DATA.controles_prenatales,
        ING.AINCONSEC AS numero_ingreso,
        CAM.HCACODIGO AS numero_cama
    FROM HPNESTANC AS EST
    INNER JOIN HPNDEFCAM AS CAM ON EST.HPNDEFCAM = CAM.OID
    INNER JOIN HPNGRUPOS AS GRP ON CAM.HPNGRUPOS = GRP.OID
    INNER JOIN HPNSUBGRU AS SUB ON CAM.HPNSUBGRU = SUB.OID
    INNER JOIN ADNINGRESO AS ING ON EST.ADNINGRES = ING.OID
    INNER JOIN GENPACIEN AS PAC ON ING.GENPACIEN = PAC.OID
    INNER JOIN GENDETCON AS PLA ON ING.GENDETCON = PLA.OID
    OUTER APPLY (
        SELECT TOP 1
            FOL.OID AS folio,
            (SELECT TOP 1 DX.DIACODIGO + ' ' + DX.DIANOMBRE
             FROM HCNDIAPAC AS DIAP
             INNER JOIN GENDIAGNO AS DX ON DIAP.GENDIAGNO = DX.OID
             WHERE DIAP.HCNFOLIO = FOL.OID
             ORDER BY DIAP.OID ASC) AS diagnostico
        FROM HCNFOLIO AS FOL
        WHERE FOL.ADNINGRESO = ING.OID
        ORDER BY FOL.OID DESC
    ) AS FOL_DATA
    OUTER APPLY (
        -- El formulario de ingreso obstétrico (HCMWINGIN) no siempre queda en el folio
        -- más reciente de la admisión (pueden crearse folios de seguimiento después sin
        -- repetirlo) — se busca el HCMWINGIN más reciente entre TODOS los folios de la
        -- admisión, en vez de limitarse al folio más nuevo, para no perder estos datos.
        SELECT TOP 1
            MW.HCCM03N191 AS grupo_sanguineo,
            MW.HCCM00N256 AS edad_gestacional_raw,
            MW.HCCM00N80 AS G_gestas,
            MW.HCCM00N81 AS P,
            MW.HCCM00N82 AS C,
            MW.HCCM00N83 AS A,
            MW.HCCM00N255 AS controles_prenatales
        FROM HCNFOLIO AS FOL2
        INNER JOIN HCMWINGIN AS MW ON MW.HCNFOLIO = FOL2.OID
        WHERE FOL2.ADNINGRESO = ING.OID
        ORDER BY FOL2.OID DESC
    ) AS MW_DATA
    WHERE EST.HESFECSAL IS NULL
      AND (
          SUB.HSUCODIGO IN ('0304', '0305', '0307')
          OR ING.AINGESTAN = 1
      )
    """
    params = []
    if query and query.strip():
        sql += """
      AND (
          PAC.PACNUMDOC LIKE %s
          OR ISNULL(PAC.PACPRINOM,'') + ' ' + ISNULL(PAC.PACSEGNOM,'') + ' ' + ISNULL(PAC.PACPRIAPE,'') + ' ' + ISNULL(PAC.PACSEGAPE,'') LIKE %s
          OR ISNULL(PAC.PACPRIAPE,'') + ' ' + ISNULL(PAC.PACSEGAPE,'') LIKE %s
          OR FOL_DATA.diagnostico LIKE %s
      )
        """
        q = '%' + query.strip() + '%'
        params = [q, q, q, q]

    sql += " ORDER BY EST.HESFECING DESC"

    try:
        with connections['readonly'].cursor() as cursor:
            cursor.execute(sql, params)
            columns = [col[0] for col in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception as e:
        # Sin conexión a la BD hospitalaria (ej. sin VPN/red del hospital): se
        # cae a los pacientes de prueba ya sembrados en la BD local de Django
        # (trabajoparto.Paciente, ej. cédula 1234567890) para no bloquear
        # las pruebas del sistema cuando no hay acceso a DGEMPRES_NEXUS.
        try:
            fallback = _listar_pacientes_activos_fallback_local(query=query, limit=limit)
        except Exception:
            fallback = []
        if fallback:
            return fallback
        raise RuntimeError(f'Error al consultar la base readonly: {e}') from e

    # Mapear a formato unificado, usado por MEOWS, Trabajo de Parto y Frecuencia Fetal
    out = []
    for r in rows:
        nombre = (r.get('nombre_paciente') or '').strip()
        ident = (r.get('identificacion') or '').strip()
        eg_raw = r.get('edad_gestacional_raw')
        gestas_raw = r.get('G_gestas')
        acudiente = (r.get('nombre_acudiente') or '').strip()

        out.append({
            'nombre_paciente': nombre or None,
            'identificacion': ident or None,
            'edad_gestacional': _normalizar_edad_gestacional(eg_raw),
            'gestas': _normalizar_gestas(gestas_raw),
            'partos': r.get('P'),
            'cesareas': r.get('C'),
            'abortos': r.get('A'),
            'fecha_nacimiento': r.get('fecha_nacimiento'),
            'nombre_acompanante': acudiente or None,
            'area': r.get('area'),
            'folio': r.get('folio'),
            'numero_cama': r.get('numero_cama'),
            'numero_ingreso': r.get('numero_ingreso'),
            'historia_clinica': r.get('historia_clinica'),
            'aseguradora': r.get('aseguradora'),
            'diagnostico': r.get('diagnostico'),
            'edad_anos': r.get('edad_anos'),
            'fecha_ingreso': r.get('fecha_ingreso'),
            'grupo_sanguineo': _normalizar_grupo_sanguineo(r.get('grupo_sanguineo')),
            'controles_prenatales': r.get('controles_prenatales'),
            'origen': 'sala_partos',
        })
    return out[:limit]
