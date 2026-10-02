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


# 2026-10-02: ingresos activos sin cama (urgencias) y pacientes de Triaje.
AREA_SIN_CAMA = 'SIN CAMA ASIGNADA'
# Solo urgencias u hospitalización (las consultas externas nunca registran
# egreso) y de los últimos días: hay urgencias viejas que nunca se cerraron.
# Una paciente de Triaje cuya urgencia pase de esto sin cama sigue en Triaje.
DIAS_MAX_INGRESO_SIN_CAMA = 3
DIAS_TRIAJE_RECIENTE = 30
MAX_DOCUMENTOS_TRIAJE = 1000


def _documentos_con_triaje_reciente():
    """Documentos con tomas de triaje en esta app en los últimos
    DIAS_TRIAJE_RECIENTE días (si tienen ingreso activo, se listan
    aunque Dinámica no los marque como gestantes)."""
    from datetime import timedelta
    from django.utils import timezone
    try:
        from meows.models import Medicion
        desde = timezone.now() - timedelta(days=DIAS_TRIAJE_RECIENTE)
        docs = (
            Medicion.objects.filter(origen='triaje', fecha_hora__gte=desde)
            .order_by().values_list('paciente__numero_documento', flat=True).distinct()
        )
        return sorted({str(d).strip() for d in docs if str(d or '').strip()})[:MAX_DOCUMENTOS_TRIAJE]
    except Exception:
        return []


def listar_pacientes_sala_partos(query=None, limit=50):
    """
    Lista las pacientes actualmente internadas (HESFECSAL IS NULL) en áreas
    gineco-obstétricas: Hospitalización Ginecobstetricia, Sala de Partos,
    Cuidado Intermedio Ginecobstetricia (HSUCODIGO '0304'/'0305'/'0307'),
    más cualquier ingreso marcado como gestante (ADNINGRESO.AINGESTAN = 1)
    sin importar la sala física en la que esté (cubre, p. ej., una gestante
    aún en observación de urgencias antes de trasladarla a piso gineco).

    2026-10-02: para que ninguna paciente se pierda entre Triaje y Sala de
    Partos, también entran:
      - ingresos activos SIN cama asignada todavía: urgencias u
        hospitalización sin egreso, de los últimos DIAS_MAX_INGRESO_SIN_CAMA
        días y sin ninguna estancia registrada (area = AREA_SIN_CAMA);
      - cualquier ingreso activo con diagnóstico obstétrico (CIE-10 O00-O99:
        embarazo, parto, cesárea, puerperio; o Z32-Z39 salvo Z38, que es el
        del recién nacido), en cualquier área, de pacientes de 10 años o más;
      - cualquier ingreso activo de una paciente que pasó por Triaje en esta
        app (tomas de triaje de los últimos DIAS_TRIAJE_RECIENTE días).

    query: opcional; filtra por nombre, identificación (documento), número de
    ingreso o texto de diagnóstico.
    limit: máximo de filas a devolver (por defecto 50).
    """
    if 'readonly' not in settings.DATABASES:
        return _listar_pacientes_activos_fallback_local(query=query, limit=limit)

    docs_triaje = _documentos_con_triaje_reciente()

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
        DXO.tiene_dx_obstetrico,
        ING.AINCONSEC AS numero_ingreso,
        CAM.HCACODIGO AS numero_cama
    FROM (
        -- Estancias abiertas (paciente en cama)...
        SELECT E.ADNINGRES AS ingreso_oid, E.HESFECING, E.HPNDEFCAM
        FROM HPNESTANC AS E
        WHERE E.HESFECSAL IS NULL
        UNION ALL
        -- ...y ingresos activos que todavía no tienen cama (urgencias).
        SELECT I.OID, I.AINFECING, NULL
        FROM ADNINGRESO AS I
        WHERE I.AINFECEGRE IS NULL
          AND I.AINFECING >= DATEADD(DAY, -%s, GETDATE())
          AND (I.AINESTADO IS NULL OR I.AINESTADO <> %s)
          AND (I.AINTIPING = 2 OR I.AINURGCON = 0)
          AND NOT EXISTS (SELECT 1 FROM HPNESTANC AS E2 WHERE E2.ADNINGRES = I.OID)
    ) AS EST
    LEFT JOIN HPNDEFCAM AS CAM ON EST.HPNDEFCAM = CAM.OID
    LEFT JOIN HPNSUBGRU AS SUB ON CAM.HPNSUBGRU = SUB.OID
    INNER JOIN ADNINGRESO AS ING ON EST.ingreso_oid = ING.OID
    INNER JOIN GENPACIEN AS PAC ON ING.GENPACIEN = PAC.OID
    LEFT JOIN GENDETCON AS PLA ON ING.GENDETCON = PLA.OID
    OUTER APPLY (
        SELECT CASE WHEN EXISTS (
            SELECT 1
            FROM HCNFOLIO AS FOL3
            INNER JOIN HCNDIAPAC AS DIAP3 ON DIAP3.HCNFOLIO = FOL3.OID
            INNER JOIN GENDIAGNO AS DX3 ON DIAP3.GENDIAGNO = DX3.OID
            WHERE FOL3.ADNINGRESO = ING.OID
              AND (LEFT(DX3.DIACODIGO, 1) = 'O'
                   OR LEFT(DX3.DIACODIGO, 3) BETWEEN 'Z32' AND 'Z39')
        ) THEN 1 ELSE 0 END AS tiene_dx_obstetrico,
        -- Para INCLUIR en la lista: sin Z38 ("nacido vivo" es el código del
        -- recién nacido, no de la madre).
        CASE WHEN EXISTS (
            SELECT 1
            FROM HCNFOLIO AS FOL4
            INNER JOIN HCNDIAPAC AS DIAP4 ON DIAP4.HCNFOLIO = FOL4.OID
            INNER JOIN GENDIAGNO AS DX4 ON DIAP4.GENDIAGNO = DX4.OID
            WHERE FOL4.ADNINGRESO = ING.OID
              AND (LEFT(DX4.DIACODIGO, 1) = 'O'
                   OR (LEFT(DX4.DIACODIGO, 3) BETWEEN 'Z32' AND 'Z39' AND LEFT(DX4.DIACODIGO, 3) <> 'Z38'))
        ) THEN 1 ELSE 0 END AS dx_obstetrico_materno
    ) AS DXO
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
    WHERE (
          SUB.HSUCODIGO IN ('0304', '0305', '0307')
          OR ING.AINGESTAN = 1
          OR (DXO.dx_obstetrico_materno = 1 AND DATEDIFF(YEAR, PAC.GPAFECNAC, GETDATE()) >= 10)
          {filtro_triaje}
      )
    """
    params = [DIAS_MAX_INGRESO_SIN_CAMA, AINESTADO_ANULADO]
    if docs_triaje:
        sql = sql.replace('{filtro_triaje}', 'OR PAC.PACNUMDOC IN (' + ', '.join(['%s'] * len(docs_triaje)) + ')')
        params += docs_triaje
    else:
        sql = sql.replace('{filtro_triaje}', '')
    if query and query.strip():
        sql += """
      AND (
          PAC.PACNUMDOC LIKE %s
          OR CONVERT(varchar(30), ING.AINCONSEC) LIKE %s
          OR ISNULL(PAC.PACPRINOM,'') + ' ' + ISNULL(PAC.PACSEGNOM,'') + ' ' + ISNULL(PAC.PACPRIAPE,'') + ' ' + ISNULL(PAC.PACSEGAPE,'') LIKE %s
          OR ISNULL(PAC.PACPRIAPE,'') + ' ' + ISNULL(PAC.PACSEGAPE,'') LIKE %s
          OR FOL_DATA.diagnostico LIKE %s
      )
        """
        q = '%' + query.strip() + '%'
        params += [q, q, q, q, q]

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
            'area': r.get('area') or AREA_SIN_CAMA,
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


def paciente_en_sala_partos(cedula):
    """
    2026-09-24: ¿La paciente aparece HOY en la lista de Sala de Partos?
    MISMO criterio que listar_pacientes_sala_partos (estancia activa en
    Hospitalización/Sala de Partos/Cuidado Intermedio gineco -- HSUCODIGO
    0304/0305/0307 -- o ingreso marcado como gestante en cualquier área).

    Triaje lo usa para sacar de su lista a la paciente en cuanto pasa a Sala
    de Partos: antes Triaje usaba otro criterio (solo Hospitalización y
    Cuidado Intermedio) y una paciente en cama de Sala de Partos o gestante
    en observación de urgencias aparecía en las DOS listas a la vez.
    2026-10-02: con los criterios nuevos de la lista (ingreso activo sin cama,
    diagnóstico obstétrico, o paciente que pasó por Triaje en esta app).
    Devuelve None si Dinámica no respondió (no se sabe).
    """
    cedula = (cedula or '').strip()
    if not cedula or not dinamica_disponible():
        return None
    viene_de_triaje = 1 if cedula in _documentos_con_triaje_reciente() else 0
    sql = """
    SELECT TOP 1 1
    FROM (
        SELECT E.ADNINGRES AS ingreso_oid, E.HPNDEFCAM
        FROM HPNESTANC AS E
        WHERE E.HESFECSAL IS NULL
        UNION ALL
        SELECT I.OID, NULL
        FROM ADNINGRESO AS I
        WHERE I.AINFECEGRE IS NULL
          AND I.AINFECING >= DATEADD(DAY, -%s, GETDATE())
          AND (I.AINESTADO IS NULL OR I.AINESTADO <> %s)
          AND (I.AINTIPING = 2 OR I.AINURGCON = 0)
          AND NOT EXISTS (SELECT 1 FROM HPNESTANC AS E2 WHERE E2.ADNINGRES = I.OID)
    ) AS EST
    LEFT JOIN HPNDEFCAM AS CAM ON EST.HPNDEFCAM = CAM.OID
    LEFT JOIN HPNSUBGRU AS SUB ON CAM.HPNSUBGRU = SUB.OID
    INNER JOIN ADNINGRESO AS ING ON EST.ingreso_oid = ING.OID
    INNER JOIN GENPACIEN AS PAC ON ING.GENPACIEN = PAC.OID
    WHERE PAC.PACNUMDOC = %s
      AND (
          SUB.HSUCODIGO IN ('0304', '0305', '0307')
          OR ING.AINGESTAN = 1
          OR %s = 1
          OR (DATEDIFF(YEAR, PAC.GPAFECNAC, GETDATE()) >= 10 AND EXISTS (
              SELECT 1
              FROM HCNFOLIO AS FOL3
              INNER JOIN HCNDIAPAC AS DIAP3 ON DIAP3.HCNFOLIO = FOL3.OID
              INNER JOIN GENDIAGNO AS DX3 ON DIAP3.GENDIAGNO = DX3.OID
              WHERE FOL3.ADNINGRESO = ING.OID
                AND (LEFT(DX3.DIACODIGO, 1) = 'O'
                     OR (LEFT(DX3.DIACODIGO, 3) BETWEEN 'Z32' AND 'Z39' AND LEFT(DX3.DIACODIGO, 3) <> 'Z38'))
          ))
      )
    """
    try:
        with connections['readonly'].cursor() as cursor:
            cursor.execute(sql, [DIAS_MAX_INGRESO_SIN_CAMA, AINESTADO_ANULADO, cedula, viene_de_triaje])
            return cursor.fetchone() is not None
    except Exception as exc:
        _marcar_dinamica_caida(exc)
        return None


def consultar_ingreso_paciente(cedula):
    """
    Ingreso de Dinámica al que pertenecen los formatos de la paciente:
    el ingreso ACTIVO (estancia sin fecha de salida, HPNESTANC.HESFECSAL IS
    NULL) y, si ya no hay ninguno activo (p. ej. se dio de alta minutos antes
    de finalizar el formato), el ingreso más reciente. 2026-09-24: se
    ignoran los ingresos anulados y, a igual condición, se prefiere uno de
    urgencias/hospitalización antes que una consulta externa (Dinámica crea un
    ingreso por cada consulta, laboratorio, etc.).

    Devuelve {'numero_ingreso': str (ADNINGRESO.AINCONSEC), 'fecha_ingreso':
    datetime, 'activo': bool} o None (sin conexión / sin ingresos).
    AINCONSEC es el número que nombra la carpeta del ingreso en el
    repositorio clínico (NAS).
    """
    cedula = (cedula or '').strip()
    if not cedula or not dinamica_disponible():
        return None
    sql = """
    SELECT TOP 1
        ING.AINCONSEC,
        ING.AINFECING,
        CASE WHEN EXISTS (
            SELECT 1 FROM HPNESTANC AS EST
            WHERE EST.ADNINGRES = ING.OID AND EST.HESFECSAL IS NULL
        ) THEN 1 ELSE 0 END AS activo
        ,CASE WHEN ING.AINTIPING = 2 OR ING.AINURGCON = 0 THEN 1 ELSE 0 END AS clinico
    FROM ADNINGRESO AS ING
    INNER JOIN GENPACIEN AS PAC ON ING.GENPACIEN = PAC.OID
    WHERE PAC.PACNUMDOC = %s AND ING.AINESTADO <> %s
    ORDER BY activo DESC, clinico DESC, ING.AINFECING DESC, ING.OID DESC
    """
    try:
        with connections['readonly'].cursor() as cursor:
            cursor.execute(sql, [cedula, AINESTADO_ANULADO])
            row = cursor.fetchone()
    except Exception as exc:
        _marcar_dinamica_caida(exc)
        raise
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


# 2026-09-24: "cortocircuito" para las consultas de ingresos. Si Dinámica no
# responde, cada intento espera el timeout de conexión del driver (~15 s); sin
# esto, el selector de ingresos o un guardado quedarían esperando en cada
# consulta. Tras una falla de conexión se deja de intentar durante
# SEGUNDOS_PAUSA_DINAMICA y las funciones de abajo responden "sin conexión" al
# instante (la app sigue con los ingresos que ya conoce).
# (El motor de la conexión, sistema_obstetrico/db_readonly, aplica la misma
# pausa a TODA la app; esto solo evita llegar a intentarlo.)
from sistema_obstetrico.db_readonly.base import (  # noqa: E402
    CLAVE_DINAMICA_CAIDA as _CLAVE_DINAMICA_CAIDA, SEGUNDOS_PAUSA_DINAMICA,
)


def dinamica_disponible():
    from django.core.cache import cache
    return 'readonly' in settings.DATABASES and not cache.get(_CLAVE_DINAMICA_CAIDA)


def _marcar_dinamica_caida(exc):
    from django.core.cache import cache
    from django.db import OperationalError, InterfaceError
    if isinstance(exc, (OperationalError, InterfaceError)):
        cache.set(_CLAVE_DINAMICA_CAIDA, True, SEGUNDOS_PAUSA_DINAMICA)


# ADNINGRESO.AINESTADO: 2 = anulado (todos tienen ADFECANULA). Verificado el
# 2026-09-24 sobre el último año de ingresos.
AINESTADO_ANULADO = 2


def _tipo_ingreso(tipo_ingreso, urgencias_consulta):
    """ADNINGRESO.AINTIPING = 2 -> hospitalización; AINURGCON = 0 -> urgencias;
    el resto (AINTIPING 1 + AINURGCON 1/10...) son consultas externas,
    laboratorios, etc. (una paciente puede tener decenas). Verificado el
    2026-09-24: las hospitalizaciones tienen estancias y fecha de egreso; las
    consultas externas nunca tienen egreso."""
    if tipo_ingreso == 2:
        return 'hospitalizacion'
    if urgencias_consulta == 0:
        return 'urgencias'
    return 'consulta'


def consultar_estado_ingreso(numero_ingreso):
    """
    Estado de un ingreso de Dinámica (ADNINGRESO.AINCONSEC).

    2026-09-24: el egreso se toma de la fecha de egreso OFICIAL del ingreso
    (ADNINGRESO.AINFECEGRE, que Dinámica llena al registrar el egreso,
    ADNINGRESO.ADNEGRESO) y ya no de la última salida de las estancias:
    cubre también a las pacientes que nunca tuvieron cama.

    Devuelve {'activo': bool, 'fecha_egreso': datetime|None,
    'tiene_estancias': bool, 'anulado': bool, 'tipo': str}
    o None si no hay conexión o el ingreso no existe.
    """
    numero_ingreso = str(numero_ingreso or '').strip()
    if not numero_ingreso or not dinamica_disponible():
        return None
    sql = """
    SELECT
        ING.AINFECEGRE,
        ING.AINESTADO,
        ING.AINTIPING,
        ING.AINURGCON,
        (SELECT COUNT(*) FROM HPNESTANC AS EST WHERE EST.ADNINGRES = ING.OID) AS estancias
    FROM ADNINGRESO AS ING
    WHERE ING.AINCONSEC = %s
    """
    try:
        with connections['readonly'].cursor() as cursor:
            cursor.execute(sql, [numero_ingreso])
            row = cursor.fetchone()
    except Exception as exc:
        _marcar_dinamica_caida(exc)
        return None
    if not row:
        return None
    fecha_egreso, estado, tipo_ing, urg_con, estancias = row
    anulado = estado == AINESTADO_ANULADO
    return {
        'activo': fecha_egreso is None and not anulado,
        'fecha_egreso': fecha_egreso,
        'tiene_estancias': (estancias or 0) > 0,
        'anulado': anulado,
        'tipo': _tipo_ingreso(tipo_ing, urg_con),
    }


def consultar_ingresos_paciente(cedula):
    """
    TODOS los ingresos de la paciente en Dinámica, del más reciente al más
    antiguo: [{'numero_ingreso', 'fecha_ingreso', 'fecha_egreso', 'anulado',
    'tipo' ('hospitalizacion'|'urgencias'|'consulta'), 'estancia_abierta'}].
    Fechas tal cual vienen de Dinámica (hora local de Bogotá, sin zona).
    Devuelve None si no hay conexión (distinto de [] = sin ingresos).
    """
    cedula = (cedula or '').strip()
    if not cedula or not dinamica_disponible():
        return None
    sql = """
    SELECT
        ING.AINCONSEC,
        ING.AINFECING,
        ING.AINFECEGRE,
        ING.AINESTADO,
        ING.AINTIPING,
        ING.AINURGCON,
        CASE WHEN EXISTS (
            SELECT 1 FROM HPNESTANC AS EST
            WHERE EST.ADNINGRES = ING.OID AND EST.HESFECSAL IS NULL
        ) THEN 1 ELSE 0 END AS estancia_abierta
    FROM ADNINGRESO AS ING
    INNER JOIN GENPACIEN AS PAC ON ING.GENPACIEN = PAC.OID
    WHERE PAC.PACNUMDOC = %s
    ORDER BY ING.AINFECING DESC, ING.OID DESC
    """
    try:
        with connections['readonly'].cursor() as cursor:
            cursor.execute(sql, [cedula])
            rows = cursor.fetchall()
    except Exception as exc:
        _marcar_dinamica_caida(exc)
        return None
    return [
        {
            'numero_ingreso': str(r[0]).strip(),
            'fecha_ingreso': r[1],
            'fecha_egreso': r[2],
            'anulado': r[3] == AINESTADO_ANULADO,
            'tipo': _tipo_ingreso(r[4], r[5]),
            'estancia_abierta': bool(r[6]),
        }
        for r in rows if r[0] is not None
    ]


def consultar_ingresos_de_folios(folios):
    """{HCNFOLIO.OID: número de ingreso (AINCONSEC)} -- cada toma MEOWS traída
    de Dinámica guarda su folio (Medicion.dinamica_folio), y el folio sabe a
    qué ingreso pertenece: asignación exacta, sin depender de fechas.
    Devuelve {} si no hay conexión."""
    folios = sorted({int(f) for f in folios if f is not None})
    if not folios or not dinamica_disponible():
        return {}
    resultado = {}
    try:
        with connections['readonly'].cursor() as cursor:
            for i in range(0, len(folios), 500):
                lote = folios[i:i + 500]
                marcas = ', '.join(['%s'] * len(lote))
                cursor.execute(
                    f"""SELECT FOL.OID, ING.AINCONSEC FROM HCNFOLIO AS FOL
                    INNER JOIN ADNINGRESO AS ING ON FOL.ADNINGRESO = ING.OID
                    WHERE FOL.OID IN ({marcas})""",
                    lote,
                )
                resultado.update({int(f): str(n).strip() for f, n in cursor.fetchall() if n is not None})
    except Exception as exc:
        _marcar_dinamica_caida(exc)
        return {}
    return resultado




def documentos_con_ingreso_cerrado_desde(desde_por_documento):
    """
    2026-10-02: {documento: fecha (naive, hora de Bogotá)} -> set de los
    documentos que tienen en Dinámica un ingreso NO anulado que empezó en esa
    fecha o después y YA EGRESÓ. Triaje los quita de su lista: el triaje tuvo
    su ingreso y este terminó. (Los ingresos activos se ven en la lista de
    Sala de Partos, ver listar_pacientes_sala_partos.) Una sola consulta.
    None si no hay conexión.
    """
    docs = {str(d).strip(): f for d, f in desde_por_documento.items() if str(d or '').strip() and f is not None}
    if not docs:
        return set()
    if not dinamica_disponible():
        return None
    encontrados = set()
    try:
        with connections['readonly'].cursor() as cursor:
            lista = sorted(docs)
            for i in range(0, len(lista), 500):
                lote = lista[i:i + 500]
                marcas = ', '.join(['%s'] * len(lote))
                cursor.execute(
                    f"""SELECT PAC.PACNUMDOC, ING.AINFECING
                    FROM ADNINGRESO AS ING
                    INNER JOIN GENPACIEN AS PAC ON ING.GENPACIEN = PAC.OID
                    WHERE PAC.PACNUMDOC IN ({marcas})
                      AND ING.AINFECEGRE IS NOT NULL
                      AND (ING.AINESTADO IS NULL OR ING.AINESTADO <> %s)""",
                    [*lote, AINESTADO_ANULADO],
                )
                for doc, fecha_ingreso in cursor.fetchall():
                    doc = str(doc or '').strip()
                    if doc in docs and fecha_ingreso is not None and fecha_ingreso >= docs[doc]:
                        encontrados.add(doc)
    except Exception as exc:
        _marcar_dinamica_caida(exc)
        return None
    return encontrados
