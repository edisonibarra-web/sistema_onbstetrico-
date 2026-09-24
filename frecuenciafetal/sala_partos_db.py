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


# "Embarazo de 38.4 semanas", "embarazo de 39,1 semanas", "Embrazo de 15 semanas
# mas 5 dias", "emb de 38 semanas", "Embarazo de 24 semanas más 6 días",
# "embarazo de 40 por ecografía", "EG: 38 sem". En la notación clínica local
# "38.4" = 38 semanas + 4 días (no 38,4 semanas decimales).
_RE_EG_TEXTO = re.compile(
    r'(?:\bemb\w*\s+de|\bgestaci\w*\s+de|\bEG\s*[:=]?)\s*'
    r'(\d{1,2})(?:\s*[.,]\s*(\d))?'
    r'(?:\s*sem\w*)?'
    r'(?:\s*(?:m.s|\+|y|,)?\s*(\d)\s*d.as?\b)?',
    re.IGNORECASE,
)
_EG_MIN_SEMANAS = 4
_EG_MAX_SEMANAS = 42  # exclusivo: >= 42 semanas se trata como dato inválido


def _a_fecha(val):
    if val is None:
        return None
    return val.date() if hasattr(val, 'date') else val


def calcular_edad_gestacional(analisis, fum, fecha_folio):
    """
    Edad gestacional documentada en la HC de ingreso gineco-obstétrica
    (HCMWINGIN). Devuelve (semanas:int|None, dias:int|None).

    OJO: HCCM00N256, que se usaba antes, NO es la edad gestacional -- en el
    catálogo de Dinámica (HCNCAMTHC) es "SEMANA INICIO" (semana en que inició
    controles prenatales). El campo "Edad gestacional" del formulario
    (HCCM03N193) llega vacío en la práctica. Por eso:

    1. Se lee del análisis del médico (HCCM03N43), donde siempre se escribe
       "1. Embarazo de X semanas..." (datado por ecografía -- la fuente más
       confiable).
    2. Si no está, se calcula desde la FUM (HCCM05N79) hasta la fecha del folio,
       solo si da un valor plausible: la FUM en Dinámica suele traer la fecha
       del día por defecto o un año mal digitado (FUM en el futuro).

    Es la EG a la fecha del folio de ingreso, no se proyecta a hoy (en
    pacientes ya en puerperio dejaría de tener sentido).
    """
    if analisis:
        for m in _RE_EG_TEXTO.finditer(str(analisis)):
            semanas = int(m.group(1))
            dias = m.group(2) or m.group(3)
            dias = int(dias) if dias is not None else 0
            if _EG_MIN_SEMANAS <= semanas < _EG_MAX_SEMANAS and dias <= 6:
                return semanas, dias

    fum_d, folio_d = _a_fecha(fum), _a_fecha(fecha_folio)
    if fum_d and folio_d:
        total_dias = (folio_d - fum_d).days
        semanas, dias = divmod(total_dias, 7)
        if total_dias > 0 and _EG_MIN_SEMANAS <= semanas < _EG_MAX_SEMANAS:
            return semanas, dias

    return None, None


def formatear_edad_gestacional(semanas, dias):
    """'38 sem 4 d' / '38 sem' / None."""
    if semanas is None:
        return None
    return f'{semanas} sem {dias} d' if dias else f'{semanas} sem'


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


_RE_DX_OBSTETRICO = re.compile(r'^\s*(O|Z3[2-9])', re.IGNORECASE)


def _clasificar_tipo_paciente(ant_gineco, ant_obst, diagnostico, tiene_dx_obstetrico, gestante):
    """
    Clasifica la paciente como 'obstetrica' o 'ginecologica' (o 'sin_clasificar').

    Fuente principal: los checks que enfermería marca en la HC de ingreso
    gineco-obstétrica de Dinámica (INGINO -> tabla HCMWINGIN):
      - HCCM07N317 "ANT. OBSTETRICOS: ACTIVAR SI LO DESEA DILIGENCIAR"
      - HCCM07N311 "ANT. GINECOLOGICOS: ACTIVAR SI LO DESEA DILIGENCIAR"
    (mapeados vía HCNCAMTHC, HCNTIPHIS=57). En la BD de pruebas son
    mutuamente excluyentes y coinciden con el diagnóstico CIE-10.

    Si ambos están marcados, o ninguno (no hay HCMWINGIN), decide el
    diagnóstico: cualquier CIE-10 del capítulo O o Z32-Z39 en la admisión,
    o el ingreso marcado como gestante (AINGESTAN), => obstétrica.
    """
    obst_por_dx = bool(tiene_dx_obstetrico) or bool(gestante) or bool(
        diagnostico and _RE_DX_OBSTETRICO.match(diagnostico)
    )
    if ant_obst and not ant_gineco:
        return 'obstetrica'
    if ant_gineco and not ant_obst:
        return 'ginecologica'
    if ant_obst and ant_gineco:
        return 'obstetrica' if obst_por_dx or not diagnostico else 'ginecologica'
    if obst_por_dx:
        return 'obstetrica'
    return 'sin_clasificar'


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
            'tipo_paciente': 'obstetrica',
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
        MW_DATA.analisis_eg,
        MW_DATA.fum,
        MW_DATA.fecha_folio_ingreso,
        MW_DATA.G_gestas,
        MW_DATA.P,
        MW_DATA.C,
        MW_DATA.A,
        MW_DATA.controles_prenatales,
        MW_DATA.ant_gineco,
        MW_DATA.ant_obst,
        ING.AINGESTAN AS gestante,
        CASE WHEN EXISTS (
            SELECT 1
            FROM HCNFOLIO AS FOL3
            INNER JOIN HCNDIAPAC AS DIAP3 ON DIAP3.HCNFOLIO = FOL3.OID
            INNER JOIN GENDIAGNO AS DX3 ON DIAP3.GENDIAGNO = DX3.OID
            WHERE FOL3.ADNINGRESO = ING.OID
              AND (LEFT(DX3.DIACODIGO, 1) = 'O'
                   OR LEFT(DX3.DIACODIGO, 3) BETWEEN 'Z32' AND 'Z39')
        ) THEN 1 ELSE 0 END AS tiene_dx_obstetrico,
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
            -- Edad gestacional: ver calcular_edad_gestacional()
            LEFT(MW.HCCM03N43, 500) AS analisis_eg,
            MW.HCCM05N79 AS fum,
            FOL2.HCFECFOL AS fecha_folio_ingreso,
            COALESCE(MW.HCCM01N318, MW.HCCM00N80) AS G_gestas,
            COALESCE(MW.HCCM01N319, MW.HCCM00N81) AS P,
            COALESCE(MW.HCCM01N320, MW.HCCM00N82) AS C,
            COALESCE(MW.HCCM01N321, MW.HCCM00N83) AS A,
            MW.HCCM00N255 AS controles_prenatales,
            -- Checks de enfermería "ANT. GINECOLOGICOS" / "ANT. OBSTETRICOS"
            -- (ver _clasificar_tipo_paciente)
            MW.HCCM07N311 AS ant_gineco,
            MW.HCCM07N317 AS ant_obst
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
        eg_sem, eg_dias = calcular_edad_gestacional(
            r.get('analisis_eg'), r.get('fum'), r.get('fecha_folio_ingreso'),
        )
        gestas_raw = r.get('G_gestas')
        acudiente = (r.get('nombre_acudiente') or '').strip()

        out.append({
            'nombre_paciente': nombre or None,
            'identificacion': ident or None,
            'edad_gestacional': eg_sem,
            'edad_gestacional_texto': formatear_edad_gestacional(eg_sem, eg_dias),
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
            'tipo_paciente': _clasificar_tipo_paciente(
                r.get('ant_gineco'), r.get('ant_obst'), r.get('diagnostico'),
                r.get('tiene_dx_obstetrico'), r.get('gestante'),
            ),
            'origen': 'sala_partos',
        })
    return out[:limit]


def consultar_ingreso_paciente(cedula):
    """
    Ingreso de Dinámica al que pertenecen los formatos de la paciente:
    el ingreso ACTIVO (estancia sin fecha de salida, HPNESTANC.HESFECSAL IS
    NULL) y, si ya no hay ninguno activo (p. ej. se dio de alta minutos antes
    de finalizar el formato), el ingreso más reciente.

    Devuelve {'numero_ingreso': str (ADNINGRESO.AINCONSEC), 'fecha_ingreso':
    datetime, 'activo': bool} o None (sin conexión / sin ingresos).
    AINCONSEC es el número que nombra la carpeta del ingreso en el
    repositorio clínico (NAS).
    """
    cedula = (cedula or '').strip()
    if not cedula or 'readonly' not in settings.DATABASES:
        return None
    sql = """
    SELECT TOP 1
        ING.AINCONSEC,
        ING.AINFECING,
        CASE WHEN EXISTS (
            SELECT 1 FROM HPNESTANC AS EST
            WHERE EST.ADNINGRES = ING.OID AND EST.HESFECSAL IS NULL
        ) THEN 1 ELSE 0 END AS activo
    FROM ADNINGRESO AS ING
    INNER JOIN GENPACIEN AS PAC ON ING.GENPACIEN = PAC.OID
    WHERE PAC.PACNUMDOC = %s
    ORDER BY activo DESC, ING.AINFECING DESC, ING.OID DESC
    """
    with connections['readonly'].cursor() as cursor:
        cursor.execute(sql, [cedula])
        row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    return {
        'numero_ingreso': str(row[0]).strip(),
        'fecha_ingreso': row[1],
        'activo': bool(row[2]),
    }


def consultar_aseguradora_paciente(cedula):
    """
    Aseguradora (GENDETCON.GDENOMBRE) del ingreso MÁS RECIENTE de la paciente
    en Dinámica, o None si no tiene ingresos / no hay conexión. Usada para
    prellenar el triaje de una paciente que ya estuvo antes en el hospital.
    """
    cedula = (cedula or '').strip()
    if not cedula or 'readonly' not in settings.DATABASES:
        return None
    sql = """
    SELECT TOP 1 PLA.GDENOMBRE
    FROM ADNINGRESO AS ING
    INNER JOIN GENPACIEN AS PAC ON ING.GENPACIEN = PAC.OID
    INNER JOIN GENDETCON AS PLA ON ING.GENDETCON = PLA.OID
    WHERE PAC.PACNUMDOC = %s
    ORDER BY ING.AINFECING DESC, ING.OID DESC
    """
    try:
        with connections['readonly'].cursor() as cursor:
            cursor.execute(sql, [cedula])
            row = cursor.fetchone()
    except Exception:
        return None
    nombre = (row[0] or '').strip() if row else ''
    return nombre or None
