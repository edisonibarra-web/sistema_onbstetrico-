"""
Generador de PDF para el formato FRSPA-007 - Control Fetocardia y Postparto
Estructura ordenada tipo plantilla hospitalaria.
"""
import io
from reportlab.lib import colors, utils
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, KeepTogether, PageBreak
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from django.conf import settings

from .models import estado_sangrado as _estado_sangrado

# Dimensiones A4: 21 x 29.7 cm. Márgenes 1.3cm = 18.4 x 27.1 cm útil (deja borde visible en toda la hoja)
MARGIN = 1.3 * cm
ANCHO_UTIL = A4[0] - 2 * MARGIN
# Factor de escala respecto al ancho de referencia (19.2cm) con el que se diseñaron las tablas.
ESCALA = ANCHO_UTIL / (19.2 * cm)
BORDE = 0.8
COLOR_BORDE = colors.HexColor('#475569')
COLOR_HEADER = colors.HexColor('#0e7490')
COLOR_LABEL = colors.HexColor('#f1f5f9')
COLOR_TEXTO = colors.HexColor('#1e293b')


def _get_logo_path(filename):
    return settings.BASE_DIR / 'media' / 'img' / filename


def _safe_str(val):
    if val is None:
        return ''
    if hasattr(val, 'strftime'):
        return str(val)
    return str(val)


def _fix_mojibake_text(value):
    text = _safe_str(value)
    if not text:
        return ''
    # Corrige casos típicos: "MarÝa", "Gonzßlez", "JosÃ©", etc.
    if not any(ch in text for ch in ('Ã', 'Â', 'Ä', 'Ë', 'Ï', 'Ö', 'Ü', 'Ý', 'ß')):
        return text
    for src_enc in ('latin-1', 'cp1252'):
        try:
            repaired = text.encode(src_enc, errors='strict').decode('utf-8', errors='strict')
            if repaired:
                return repaired
        except Exception:
            continue
    return text


def _checkbox(marcado):
    """Casilla pequeña con borde para imprimir y marcar a mano, o con 'X' cuando
    el dato ya se conoce (registro real diligenciado)."""
    tbl = Table([['X' if marcado else '']], colWidths=[0.35*cm], rowHeights=[0.35*cm])
    tbl.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), BORDE, COLOR_BORDE),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    return tbl



def generar_pdf_registro(registro, es_plantilla=False):
    """Genera PDF FRSPA-007 con estructura ordenada.

    Si es_plantilla=True, los campos sin diligenciar se dejan realmente vacíos
    (sin guiones "—" ni valores por defecto) para poder imprimir el formato y
    llenarlo a mano.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=MARGIN,
        leftMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN
    )
    elements = []
    # 2026-10-06: responsables de cada paso (renglón debajo de cada sección).
    resp_pasos = _responsables_pasos(registro, es_plantilla)
    styles = getSampleStyleSheet()

    # ========== ENCABEZADO (formato de control documental FRSPA-007) ==========
    logo_h = _get_logo_path('logo_hospital.png')
    logo_a = _get_logo_path('logo_acreditacion.png')

    estilo_hospital_nombre = ParagraphStyle(
        name='HospitalNombre', alignment=TA_CENTER, fontName='Helvetica-Bold',
        fontSize=6.5, leading=7.5, spaceBefore=2
    )
    celda_logo_h = []
    try:
        if logo_h.exists():
            celda_logo_h.append(Image(str(logo_h), width=1.6*cm, height=1.2*cm))
    except Exception:
        pass
    celda_logo_h.append(Paragraph(
        'HOSPITAL<br/>UNIVERSITARIO<br/><font size="5">DEPARTAMENTAL DE NARIÑO</font>',
        estilo_hospital_nombre
    ))

    estilo_titulo_doc = ParagraphStyle(
        name='TituloDocumento', alignment=TA_CENTER, fontName='Helvetica-Bold',
        fontSize=9, leading=11
    )
    celda_titulo = Paragraph(
        'CONTROL DE PUERPERIO INMEDIATO',
        estilo_titulo_doc
    )

    estilo_meta_label = ParagraphStyle(name='MetaLabel', alignment=TA_CENTER, fontName='Helvetica', fontSize=6.5, leading=7.5)
    estilo_meta_valor = ParagraphStyle(name='MetaValor', alignment=TA_CENTER, fontName='Helvetica-Bold', fontSize=7, leading=8)

    data_meta = [
        [Paragraph('CÓDIGO:', estilo_meta_label), Paragraph('FECHA DE ELABORACIÓN:', estilo_meta_label)],
        [Paragraph('FRSPA-007', estilo_meta_valor), Paragraph('27 DE NOVIEMBRE DE 2023', estilo_meta_valor)],
        [Paragraph('VERSIÓN:', estilo_meta_label), Paragraph('FECHA DE ACTUALIZACIÓN:', estilo_meta_label)],
        [Paragraph('01', estilo_meta_valor), Paragraph('27 DE NOVIEMBRE DE 2023', estilo_meta_valor)],
        [Paragraph('HOJA: 1 DE: 1', estilo_meta_valor), ''],
    ]
    tbl_meta = Table(data_meta, colWidths=[2.8*cm*ESCALA, 4.6*cm*ESCALA])
    tbl_meta.setStyle(TableStyle([
        ('SPAN', (0, 4), (1, 4)),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_BORDE),
    ]))

    celda_logo_a = []
    try:
        if logo_a.exists():
            celda_logo_a.append(Image(str(logo_a), width=1.9*cm, height=1.9*cm))
    except Exception:
        pass

    tbl_head = Table(
        [[celda_logo_h, celda_titulo, tbl_meta, celda_logo_a]],
        colWidths=[2.6*cm*ESCALA, 6.8*cm*ESCALA, 7.4*cm*ESCALA, 2.4*cm*ESCALA]
    )
    tbl_head.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('ALIGN', (2, 0), (2, 0), 'CENTER'),
        ('ALIGN', (3, 0), (3, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (2, 0), (2, 0), 0),
        ('RIGHTPADDING', (2, 0), (2, 0), 0),
        ('TOPPADDING', (2, 0), (2, 0), 0),
        ('BOTTOMPADDING', (2, 0), (2, 0), 0),
        ('BOX', (0, 0), (-1, -1), BORDE, COLOR_BORDE),
        ('LINEAFTER', (0, 0), (0, 0), BORDE, COLOR_BORDE),
        ('LINEAFTER', (1, 0), (1, 0), BORDE, COLOR_BORDE),
        ('LINEAFTER', (2, 0), (2, 0), BORDE, COLOR_BORDE),
    ]))
    elements.append(tbl_head)
    elements.append(Spacer(1, 0.3*cm))

    # ========== DATOS DE LA PACIENTE ==========
    if es_plantilla:
        edad_str, gestas_str, acomp_str = '', '', ''
    else:
        edad_str = f"{registro.edad_gestacional} sem" if registro.edad_gestacional else '—'
        gestas_str = _safe_str(registro.gestas)
        acomp_str = _safe_str(registro.nombre_acompanante) or '—'
    data_pac = [
        ['Nombre completo:', _safe_str(registro.nombre_paciente), 'N° Identificación:', _safe_str(registro.identificacion)],
        ['Edad Gestacional:', edad_str, 'Gestas:', gestas_str],
        ['Acompañante:', acomp_str, '', ''],
    ]
    tbl_pac = Table([['DATOS DE LA PACIENTE', '', '', '']] + data_pac, colWidths=[4.5*cm*ESCALA, 5.1*cm*ESCALA, 4.5*cm*ESCALA, 5.1*cm*ESCALA])
    tbl_pac.setStyle(TableStyle([
        ('SPAN', (0, 0), (-1, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('BACKGROUND', (0, 1), (0, -1), COLOR_LABEL),
        ('BACKGROUND', (2, 1), (2, -1), COLOR_LABEL),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 1), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('BOX', (0, 0), (-1, -1), BORDE, COLOR_BORDE),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
    ]))
    elements.append(tbl_pac)
    elements.append(Spacer(1, 0.28*cm))

    # ========== CARACTERÍSTICAS DEL PARTO ==========
    # Checklist de Sí/No: cada opción real del sistema queda marcable a mano
    # (plantilla en blanco) o con "X" ya marcada cuando el registro es real.
    # Solo incluye los campos que el formulario web recoge actualmente
    # (tipo de parto, episiotomía y alumbramiento); no hay UI para
    # gemelar/mellizos/trillizos, parto/neonato atendido por, ni valoración
    # por pediatra, así que esos campos ya no se imprimen aquí.

    def _fila_opcion(etiqueta, valor_actual, valor_opcion):
        marcado_si = (not es_plantilla) and valor_actual == valor_opcion
        marcado_no = (not es_plantilla) and valor_actual is not None and valor_actual != valor_opcion
        return [etiqueta, _checkbox(marcado_si), 'Sí', _checkbox(marcado_no), 'No', '']

    def _fila_booleana(etiqueta, valor_actual):
        marcado_si = (not es_plantilla) and bool(valor_actual)
        marcado_no = (not es_plantilla) and not bool(valor_actual)
        return [etiqueta, _checkbox(marcado_si), 'Sí', _checkbox(marcado_no), 'No', '']

    # 2026-10-06: episiotomía None = "No aplica" (ni Sí ni No).
    def _fila_booleana_na(etiqueta, valor_actual):
        no_aplica = (not es_plantilla) and valor_actual is None
        marcado_si = (not es_plantilla) and valor_actual is True
        marcado_no = (not es_plantilla) and valor_actual is False
        return [etiqueta, _checkbox(marcado_si), 'Sí', _checkbox(marcado_no), 'No',
                'No aplica' if no_aplica else '']

    cw_part = [5.5*cm*ESCALA, 1.3*cm*ESCALA, 1.7*cm*ESCALA, 1.3*cm*ESCALA, 1.7*cm*ESCALA, 7.7*cm*ESCALA]

    estilo_tipo_label = ParagraphStyle(name='TipoLabel', fontName='Helvetica-Bold', fontSize=7, leading=9, alignment=TA_LEFT)
    tipo_cell = Paragraph('Tipo de parto:', estilo_tipo_label)

    # Hora de parto: registro manual (no viene de Dinámica ni se calcula),
    # la enfermera la diligencia igual que tipo de parto/episiotomía.
    hora_parto_str = ''
    if not es_plantilla:
        hora_parto_str = registro.hora_parto.strftime('%H:%M') if registro.hora_parto else '—'

    # Desgarro: registro manual igual que tipo de parto/hora de parto. Si es
    # Grado III, se agrega la subclasificación A/B/C entre paréntesis.
    desgarro_str = ''
    if not es_plantilla:
        if registro.desgarro:
            desgarro_str = registro.get_desgarro_display()
            if registro.desgarro == 'GRADO_III' and registro.desgarro_subgrado:
                desgarro_str += f" ({registro.desgarro_subgrado})"
        else:
            desgarro_str = '—'

    data_part = [
        ['CARACTERÍSTICAS DEL PARTO', '', '', '', '', ''],
        [tipo_cell, '', '', '', '', ''],
        _fila_opcion('   Vaginal', registro.tipo_parto, 'VAGINAL'),
        _fila_opcion('   Cesárea', registro.tipo_parto, 'CESAREA'),
        _fila_opcion('   Instrumentado', registro.tipo_parto, 'INSTRUMENTADO'),
        _fila_booleana_na('Episiotomía:', registro.episiotomia),
        ['Alumbramiento:', '', '', '', '', ''],
        _fila_booleana('   Activo', registro.tipo_alumbramiento in ('DIRIGIDO', 'MANUAL')),
        ['Hora de parto:', hora_parto_str, '', '', '', ''],
        ['Desgarro:', desgarro_str, '', '', '', ''],
    ]
    fila_subtitulo_alumbramiento = 6
    fila_hora_parto = len(data_part) - 2
    fila_desgarro = len(data_part) - 1
    tbl_part = Table(data_part, colWidths=cw_part)
    tbl_part.setStyle(TableStyle([
        ('SPAN', (0, 0), (-1, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('SPAN', (0, 1), (-1, 1)),
        ('SPAN', (0, fila_subtitulo_alumbramiento), (-1, fila_subtitulo_alumbramiento)),
        ('BACKGROUND', (0, 1), (-1, 1), COLOR_LABEL),
        ('BACKGROUND', (0, fila_subtitulo_alumbramiento), (-1, fila_subtitulo_alumbramiento), COLOR_LABEL),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('FONTNAME', (0, fila_subtitulo_alumbramiento), (-1, fila_subtitulo_alumbramiento), 'Helvetica-Bold'),
        ('SPAN', (1, fila_hora_parto), (-1, fila_hora_parto)),
        ('FONTNAME', (0, fila_hora_parto), (0, fila_hora_parto), 'Helvetica-Bold'),
        ('ALIGN', (1, fila_hora_parto), (1, fila_hora_parto), 'LEFT'),
        ('SPAN', (1, fila_desgarro), (-1, fila_desgarro)),
        ('FONTNAME', (0, fila_desgarro), (0, fila_desgarro), 'Helvetica-Bold'),
        ('ALIGN', (1, fila_desgarro), (1, fila_desgarro), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (2, 0), (2, -1), 'LEFT'),
        ('ALIGN', (4, 0), (4, -1), 'LEFT'),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('BOX', (0, 0), (-1, -1), BORDE, COLOR_BORDE),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
    ]))
    elements.append(tbl_part)
    _agregar_responsables(elements, resp_pasos, 'parto')
    elements.append(Spacer(1, 0.28*cm))

    # ========== CONTROL DEL RECIÉN NACIDO ==========
    # 2026-09-30: a pedido, justo debajo de "Características del parto".
    rn = _recien_nacido(registro, es_plantilla)
    ubicacion_huella = {}  # la llena _TablaConHuella al dibujarse
    elements.append(KeepTogether(_tabla_recien_nacido(registro, rn, es_plantilla, ubicacion_huella)))
    _agregar_responsables(elements, resp_pasos, 'recien_nacido')
    elements.append(Spacer(1, 0.28*cm))

    # ========== CONTROL FETOCARDIA ==========
    # Diseño transpuesto (parámetros en filas, controles en columnas), igual
    # a como está diagramado el formato físico del hospital: FECHA / HORA /
    # FETOCARDIA por columna, y RESPONSABLE como campo único al final.
    NUM_CONTROLES_FC = 14
    fcs = [] if es_plantilla else list(registro.controles_fetocardia.all().order_by('fecha', 'hora'))
    fcs_pad = (fcs + [None]*NUM_CONTROLES_FC)[:NUM_CONTROLES_FC]

    def _campo_fc(fc, attr):
        if fc is None:
            return '' if es_plantilla else '—'
        valor = getattr(fc, attr)
        if valor is None or valor == '':
            return '—'
        if attr == 'fecha' and hasattr(valor, 'strftime'):
            return valor.strftime('%d/%m/%y')
        if attr == 'hora' and hasattr(valor, 'strftime'):
            return valor.strftime('%H:%M')
        return _safe_str(valor) or '—'

    # Responsable(s) del apartado (no por cada columna de control). 2026-09-28:
    # si varias personas tomaron fetocardia, van todas (firma automática).
    responsable_fc = ''
    if not es_plantilla:
        nombres_fc = []
        for fc in fcs:
            nombre = _safe_str(getattr(fc, 'registrado_por', '') or fc.responsable).strip()
            if nombre and nombre not in nombres_fc:
                nombres_fc.append(nombre)
        responsable_fc = ', '.join(nombres_fc) or '—'

    data_fc = [
        ['FECHA'] + [_campo_fc(fc, 'fecha') for fc in fcs_pad],
        ['HORA'] + [_campo_fc(fc, 'hora') for fc in fcs_pad],
        ['FETOCARDIA (lpm)'] + [_campo_fc(fc, 'fetocardia') for fc in fcs_pad],
        ['RESPONSABLE'] + [responsable_fc] + ['']*(NUM_CONTROLES_FC - 1),
    ]
    fila_responsable_fc = len(data_fc) - 1

    ancho_label_fc = 2.6*cm
    ancho_dato_fc = (ANCHO_UTIL - ancho_label_fc) / NUM_CONTROLES_FC
    cw_fc = [ancho_label_fc] + [ancho_dato_fc]*NUM_CONTROLES_FC
    fila_tit_fc = ['CONTROL DE FETOCARDIA DURANTE EL EXPULSIVO'] + ['']*NUM_CONTROLES_FC
    tbl_fc = Table([fila_tit_fc] + data_fc, colWidths=cw_fc, repeatRows=1)
    tbl_fc.setStyle(TableStyle([
        ('SPAN', (0, 0), (-1, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BACKGROUND', (0, 1), (0, -1), COLOR_LABEL),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('FONTSIZE', (0, 1), (0, -1), 7),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('FONTSIZE', (1, 1), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('BOX', (0, 0), (-1, -1), BORDE, COLOR_BORDE),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('SPAN', (1, fila_responsable_fc + 1), (-1, fila_responsable_fc + 1)),
        ('ALIGN', (1, fila_responsable_fc + 1), (-1, fila_responsable_fc + 1), 'LEFT'),
    ]))
    elements.append(tbl_fc)
    _agregar_responsables(elements, resp_pasos, 'fetocardia')
    elements.append(Spacer(1, 0.28*cm))

    # ========== GUÍA DE PARÁMETROS Y SEMÁFORO DE ALERTA (POSPARTO INMEDIATO) ==========
    # 2026-09-11: movida para ir justo debajo de "Control de Fetocardia durante
    # el Expulsivo" (a pedido explícito) -- antes iba después de la Línea de
    # Tiempo Clínica MEOWS, casi al final del documento.
    # Refleja las 3 cards de la vista "Globo de seguridad / Sangrado cuantificado /
    # Sutura y heridas", que hasta ahora no se imprimían en el PDF aunque ya
    # existen como campos del modelo y del formulario.
    COLOR_ESTADO_HEX = {'NORMAL': '#059669', 'VIGILAR': '#d97706', 'ALERTA': '#dc2626'}
    estilo_valor_param = ParagraphStyle(name='ValorParam', fontName='Helvetica', fontSize=7, leading=9, alignment=TA_LEFT)

    def _fila_valor_simple(etiqueta, valor):
        texto = valor if (valor or es_plantilla) else '—'
        return [etiqueta, Paragraph(texto, estilo_valor_param)]

    def _fila_estado(etiqueta, valor_str, estado):
        if estado and not es_plantilla:
            hexcolor = COLOR_ESTADO_HEX.get(estado, '#1e293b')
            texto = f"{valor_str} &nbsp;&nbsp;<font color='{hexcolor}'><b>[{estado}]</b></font>"
        else:
            texto = valor_str if (valor_str or es_plantilla) else '—'
        return [etiqueta, Paragraph(texto, estilo_valor_param)]

    if es_plantilla:
        globo_display = ''
        sutura_display = ''
        sangrado_valor_str = ''
        estado_sangrado = None
    else:
        globo_display = registro.get_globo_seguridad_display() if registro.globo_seguridad else ''
        sutura_display = registro.get_sutura_heridas_display() if registro.sutura_heridas else ''
        sangrado_valor_str = f"{registro.sangrado_cuantificado_cc} c.c." if registro.sangrado_cuantificado_cc is not None else ''
        estado_sangrado = _estado_sangrado(registro.sangrado_cuantificado_cc, registro.tipo_parto)

    data_param = [
        ['GUÍA DE PARÁMETROS Y SEMÁFORO DE ALERTA', ''],
        _fila_valor_simple('Globo de seguridad:', globo_display),
        _fila_estado('Sangrado cuantificado:', sangrado_valor_str, estado_sangrado),
        _fila_valor_simple('Sutura y heridas:', sutura_display),
    ]
    ancho_lbl_param = 4.5*cm*ESCALA
    cw_param = [ancho_lbl_param, ANCHO_UTIL - ancho_lbl_param]
    tbl_param = Table(data_param, colWidths=cw_param)
    tbl_param.setStyle(TableStyle([
        ('SPAN', (0, 0), (-1, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('BACKGROUND', (0, 1), (0, -1), COLOR_LABEL),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('BOX', (0, 0), (-1, -1), BORDE, COLOR_BORDE),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
    ]))
    elements.append(tbl_param)
    elements.append(Spacer(1, 0.28*cm))

    # ========== CONTROLES DE VIGILANCIA POSPARTO (2026-10-06) ==========
    # Historial de los controles de Sangrado, Globo de seguridad y Sutura
    # (cronograma 15/30/60 min hasta 6 h). El control del minuto 360 de los
    # tres es el que habilita el cierre (views._faltantes_control_6h).
    elements.append(_tabla_vigilancia_posparto(registro, es_plantilla))
    _agregar_responsables(elements, resp_pasos, 'vigilancia')
    elements.append(Spacer(1, 0.28*cm))

    # ========== CONTROL POSPARTO INMEDIATO (MEOWS) ==========
    # Refleja el grid clínico MEOWS embebido en esta misma página bajo el título
    # "Control Posparto Inmediato" (meows/_timeline_grid.html), usando la misma
    # fuente de datos (construir_grid_meows) para que el PDF coincida siempre
    # con lo que se ve en pantalla.
    #
    # 2026-09-11: la línea de tiempo MEOWS debe verse aunque la paciente NO
    # tenga todavía un RegistroParto guardado en este módulo (expulsivo /
    # pos-parto inmediato) -- a pedido explícito, "no importa si no tiene un
    # registro guardado, la línea de tiempo MEOWS debe reflejarse en el PDF".
    # Antes esto dependía de `es_plantilla`: una plantilla en blanco (sin
    # registro guardado) nunca mostraba MEOWS, sin importar si ya se conocía
    # el documento de la paciente. Ahora solo depende de si se conoce el
    # documento (`registro.identificacion`), venga o no de un registro real.
    from meows.services.grid import construir_grid_meows, obtener_paciente_meows_por_documento

    documento_para_meows = (registro.identificacion or '').strip()
    meows_paciente = obtener_paciente_meows_por_documento(documento_para_meows) if documento_para_meows else None
    if meows_paciente:
        grid_parametros_meows, columnas_meows = construir_grid_meows(meows_paciente)
    else:
        grid_parametros_meows, columnas_meows = [], []

    if not columnas_meows:
        tit_meows_vacio = Table(
            [['CONTROL POSPARTO INMEDIATO (MEOWS)'], ['' if not documento_para_meows else 'Sin mediciones MEOWS registradas']],
            colWidths=[ANCHO_UTIL]
        )
        tit_meows_vacio.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('BOX', (0, 0), (-1, -1), BORDE, COLOR_BORDE),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ]))
        elements.append(tit_meows_vacio)
    else:
        COLOR_SCORE_MARCADO = {
            0: (colors.HexColor('#e2e8f0'), colors.HexColor('#1e293b')),
            1: (colors.HexColor('#16a34a'), colors.white),
            2: (colors.HexColor('#d97706'), colors.white),
            3: (colors.HexColor('#dc2626'), colors.white),
        }
        COLOR_SCORE_LIGHT = {
            0: (colors.HexColor('#eef1f5'), colors.HexColor('#64748b')),
            1: (colors.HexColor('#86efac'), colors.HexColor('#14532d')),
            2: (colors.HexColor('#fcd34d'), colors.HexColor('#78350f')),
            3: (colors.HexColor('#fca5a5'), colors.HexColor('#7f1d1d')),
        }
        COLOR_RIESGO_MEOWS = {
            'BLANCO': colors.HexColor('#94a3b8'), 'VERDE': colors.HexColor('#22c55e'),
            'AMARILLO': colors.HexColor('#eab308'), 'ROJO': colors.HexColor('#ef4444'),
        }

        # textColor blanco explícito: al ir dentro de un Paragraph, el texto
        # no hereda el TEXTCOLOR blanco que la TableStyle le da a la fila del
        # encabezado (fondo azul oscuro #0c4a6e) -- sin esto quedaba en negro,
        # casi ilegible sobre ese fondo.
        estilo_meows_col = ParagraphStyle(name='MeowsCol', fontName='Helvetica-Bold', fontSize=5, leading=5.8, alignment=TA_CENTER, textColor=colors.white)
        estilo_meows_param = ParagraphStyle(name='MeowsParam', fontName='Helvetica-Bold', fontSize=5.5, leading=6.5, alignment=TA_LEFT)
        estilo_meows_total = ParagraphStyle(name='MeowsTotal', fontName='Helvetica-Bold', fontSize=5.5, leading=6.5, alignment=TA_CENTER, textColor=colors.white)

        # 2026-09-11: con muchas horas registradas (>10-12) la tabla ya no
        # cabía en el ancho de la hoja A4 -- el ancho de columna se calculaba
        # dividiendo el espacio disponible entre TODAS las columnas pero con
        # un piso de 0.9cm que, pasado cierto número de columnas, hacía que
        # la tabla completa se saliera de la página y quedara cortada/
        # desbordada. Se pagina igual que el PDF MEOWS independiente
        # (meows/generador_pdf_meows.py, MEDICIONES_POR_PAGINA=10): una tabla
        # nueva cada N horas, cada una repitiendo PARÁMETRO/VALOR/PUNTAJE, en
        # vez de una sola tabla imposible de encajar.
        #
        # 2026-09-14: comprimido más (columnas más angostas, fuente/padding
        # más chico) para que quepan más horas por página -- a pedido
        # explícito, para que una medición con muchas horas registradas
        # genere menos hojas en total.
        MEOWS_COLS_POR_PAGINA = 16
        ancho_param_m = 2.3*cm
        ancho_valor_m = 1.0*cm
        # 2026-10-06: 0.9cm no alcanzaba para "PUNTAJE" (se salía del margen derecho).
        ancho_punt_m = 1.3*cm
        ancho_fijo_m = ancho_param_m + ancho_valor_m + ancho_punt_m

        total_cols_meows = len(columnas_meows)
        rangos_meows = [
            (i, min(i + MEOWS_COLS_POR_PAGINA, total_cols_meows))
            for i in range(0, total_cols_meows, MEOWS_COLS_POR_PAGINA)
        ]

        for pagina_idx, (ini, fin) in enumerate(rangos_meows):
            columnas_pagina = columnas_meows[ini:fin]
            n_cols_pagina = len(columnas_pagina)
            ancho_col_m = (ANCHO_UTIL - ancho_fijo_m) / n_cols_pagina
            cw_meows = [ancho_param_m, ancho_valor_m] + [ancho_col_m]*n_cols_pagina + [ancho_punt_m]

            header_meows = ['PARÁMETRO', 'VALOR'] + [
                Paragraph(f"{c['hora'].strftime('%d/%m/%y')}<br/>{c['hora'].strftime('%H:%M')}", estilo_meows_col)
                for c in columnas_pagina
            ] + ['PUNTAJE']

            data_meows = [header_meows]
            grupos_meows = []  # (fila_inicio, fila_fin) para SPAN de la columna PARÁMETRO
            celdas_color_meows = []  # (col, row, color_fondo, color_texto)
            fila_idx = 2  # 0=título, 1=header_meows

            for parametro in grid_parametros_meows:
                filas = parametro['filas']
                inicio_grupo = fila_idx
                for i, fila in enumerate(filas):
                    etiqueta = Paragraph(parametro['nombre'], estilo_meows_param) if i == 0 else ''
                    fila_row = [etiqueta, fila['label']]
                    for col_idx, celda in enumerate(fila['celdas'][ini:fin]):
                        marcado = celda['marcado']
                        fila_row.append('●' if marcado else '')
                        color_bg, color_txt = (COLOR_SCORE_MARCADO if marcado else COLOR_SCORE_LIGHT)[fila['score']]
                        celdas_color_meows.append((2 + col_idx, fila_idx, color_bg, color_txt))
                    fila_row.append(str(fila['score']))
                    data_meows.append(fila_row)
                    fila_idx += 1
                fin_grupo = fila_idx - 1
                if fin_grupo > inicio_grupo:
                    grupos_meows.append((inicio_grupo, fin_grupo))

            fila_total_meows = ['Puntaje total MEOWS', '']
            for c in columnas_pagina:
                riesgo = (c['riesgo'] or 'BLANCO').upper()
                puntaje_txt = c['score_total'] if c['score_total'] is not None else '-'
                fila_total_meows.append(Paragraph(f"<b>{puntaje_txt}</b><br/>{riesgo}", estilo_meows_total))
            fila_total_meows.append('')
            data_meows.append(fila_total_meows)
            fila_idx_total = fila_idx

            titulo_txt = 'CONTROL POSPARTO INMEDIATO (MEOWS)'
            if len(rangos_meows) > 1:
                titulo_txt += f' — página {pagina_idx + 1} de {len(rangos_meows)}'
            fila_titulo_meows = [titulo_txt] + ['']*(len(cw_meows) - 1)
            tbl_meows = Table([fila_titulo_meows] + data_meows, colWidths=cw_meows, repeatRows=2)
            estilo_meows = [
                ('SPAN', (0, 0), (-1, 0)),
                ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#0c4a6e')),
                ('TEXTCOLOR', (0, 1), (-1, 1), colors.white),
                ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 1), (-1, 1), 5.5),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (1, 2), (1, -2), 'CENTER'),
                ('ALIGN', (2, 2), (-1, -1), 'CENTER'),
                ('FONTSIZE', (0, 2), (-1, -1), 5.5),
                ('TOPPADDING', (0, 0), (-1, -1), 1),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                ('LEFTPADDING', (0, 0), (-1, -1), 1.5),
                ('RIGHTPADDING', (0, 0), (-1, -1), 1.5),
                ('BOX', (0, 0), (-1, -1), BORDE, COLOR_BORDE),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('BACKGROUND', (0, fila_idx_total), (-1, fila_idx_total), colors.HexColor('#0c4a6e')),
                ('TEXTCOLOR', (0, fila_idx_total), (1, fila_idx_total), colors.white),
                ('FONTNAME', (0, fila_idx_total), (1, fila_idx_total), 'Helvetica-Bold'),
                ('SPAN', (0, fila_idx_total), (1, fila_idx_total)),
            ]
            for inicio_grupo, fin_grupo in grupos_meows:
                estilo_meows.append(('SPAN', (0, inicio_grupo), (0, fin_grupo)))
            for col, row, bg, txt in celdas_color_meows:
                estilo_meows.append(('BACKGROUND', (col, row), (col, row), bg))
                estilo_meows.append(('TEXTCOLOR', (col, row), (col, row), txt))
            for col_idx, c in enumerate(columnas_pagina):
                riesgo = (c['riesgo'] or 'BLANCO').upper()
                color_riesgo = COLOR_RIESGO_MEOWS.get(riesgo, colors.HexColor('#94a3b8'))
                estilo_meows.append(('BACKGROUND', (2 + col_idx, fila_idx_total), (2 + col_idx, fila_idx_total), color_riesgo))
            tbl_meows.setStyle(TableStyle(estilo_meows))
            if pagina_idx > 0:
                elements.append(PageBreak())
            elements.append(tbl_meows)

    elements.append(Spacer(1, 0.28*cm))

    # ========== RESPONSABLE DEL REGISTRO ==========
    # 2026-09-14: se eliminó la captura de firma/huella biométrica (imagen
    # dibujada, huella digital, firma profesional en base64) a pedido
    # explícito, antes de salir a producción. Solo queda el nombre en texto
    # del responsable, que siempre se imprime cuando existe.
    # 2026-09-28: el formato lo diligencian por lo general dos o más personas;
    # la firma es automática (profesional en sesión) y aquí van TODAS, con lo
    # que hizo cada una -- ver frecuenciafetal/responsables.py.
    responsables = []
    if not es_plantilla and getattr(registro, 'pk', None) is not None:
        from .responsables import resumen_responsables
        try:
            responsables = resumen_responsables(registro)
        except Exception:
            responsables = []
    tiene_responsable = bool((registro.nombre_firma_paciente or registro.profesional_nombre or '').strip())
    if responsables:
        from django.utils import timezone as _tz

        def _hora(dt):
            return _tz.localtime(dt).strftime('%d/%m/%y %I:%M %p') if dt else ''

        elements.append(Spacer(1, 0.4*cm))
        estilo_celda = ParagraphStyle(name='RespCelda', fontSize=7.5, leading=9.5, fontName='Helvetica')
        estilo_nombre = ParagraphStyle(name='RespNombre', fontSize=8, leading=10, fontName='Helvetica-Bold')
        filas = [['PARTICIPANTES Y CIERRE DEL REGISTRO', '', '', ''],
                 ['#', 'PROFESIONAL', 'QUÉ DILIGENCIÓ', 'DESDE – HASTA']]
        for i, r in enumerate(responsables, start=1):
            desde, hasta = _hora(r['desde']), _hora(r['hasta'])
            tiempo = f'{desde} – {hasta}' if desde and hasta and desde != hasta else (desde or hasta)
            filas.append([
                str(i),
                Paragraph(_fix_mojibake_text(r['nombre']) or '—', estilo_nombre),
                Paragraph(' · '.join(r['detalle']), estilo_celda),
                Paragraph(tiempo, estilo_celda),
            ])
        cw = [0.8*cm, 6.2*cm, ANCHO_UTIL - 0.8*cm - 6.2*cm - 4.6*cm, 4.6*cm]
        tbl_resp = Table(filas, colWidths=cw, repeatRows=2)
        tbl_resp.setStyle(TableStyle([
            ('SPAN', (0, 0), (-1, 0)),
            ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8.5),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('BACKGROUND', (0, 1), (-1, 1), COLOR_LABEL),
            ('FONTSIZE', (0, 1), (-1, 1), 7),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('FONTSIZE', (0, 2), (0, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('BOX', (0, 0), (-1, -1), BORDE, COLOR_BORDE),
            ('INNERGRID', (0, 1), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ]))
        elements.append(tbl_resp)
        elements.append(Paragraph(
            "<font size='6.5' color='#64748b'>Firma automática: cada profesional queda registrado con el usuario "
            "con el que inició sesión al guardar su parte del formato.</font>", styles['Normal']))
    elif tiene_responsable:
        elements.append(Spacer(1, 0.5*cm))

        col_firma = []
        sig_name = (_fix_mojibake_text(registro.nombre_firma_paciente) or "").strip()
        prof_name = (_fix_mojibake_text(registro.profesional_nombre) or "").strip()
        final_name = sig_name or prof_name or "—"

        col_firma.append(Paragraph(f"<b>{final_name}</b>", styles['Normal']))
        col_firma.append(Paragraph("<font size='7' color='#64748b'>RESPONSABLE</font>", styles['Normal']))

        data_firmas = [[col_firma]]
        tbl_firmas = Table(data_firmas, colWidths=[ANCHO_UTIL])
        tbl_firmas.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('LINEABOVE', (0, 0), (0, 0), 0.5, colors.black),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(tbl_firmas)
    else:
        # 2026-09-14: antes esto era "elif es_plantilla" -- un registro REAL
        # ya guardado (es_plantilla=False) que todavía no tuviera firma,
        # huella ni nombre de responsable capturado no entraba en ninguna de
        # las dos ramas, así que la sección de responsable/firma
        # desaparecía por completo del PDF, sin ningún aviso. Ahora, sin
        # importar si es un registro real o la plantilla en blanco, si no
        # hay nada capturado todavía se imprime igual la caja para firmar a
        # mano -- la sección nunca queda ausente.
        elements.append(Spacer(1, 0.4*cm))
        estilo_firma_label = ParagraphStyle(
            name='FirmaLabel', fontSize=7.5, fontName='Helvetica-Bold', textColor=colors.HexColor('#1e293b')
        )
        ancho_firma_label = 5.5*cm
        tbl_firma_vacia = Table(
            [
                ['FIRMA DEL RESPONSABLE', ''],
                ['', ''],
                [Paragraph('Nombre completo del responsable:', estilo_firma_label), ''],
                [Paragraph('Fecha y hora:', estilo_firma_label), ''],
            ],
            colWidths=[ancho_firma_label, ANCHO_UTIL - ancho_firma_label],
            rowHeights=[None, 2.0*cm, None, None],
        )
        tbl_firma_vacia.setStyle(TableStyle([
            ('SPAN', (0, 0), (-1, 0)),
            ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, 0), 4),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
            ('SPAN', (0, 1), (-1, 1)),
            ('LINEBELOW', (0, 1), (-1, 1), 0.8, colors.black),
            ('VALIGN', (0, 2), (0, -1), 'BOTTOM'),
            ('LINEBELOW', (1, 2), (1, -1), 0.6, colors.HexColor('#94a3b8')),
            ('TOPPADDING', (0, 2), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 2), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('BOX', (0, 0), (-1, -1), BORDE, COLOR_BORDE),
        ]))
        elements.append(tbl_firma_vacia)

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    if rn is not None and rn.huella_pdf:
        pdf_bytes = _incrustar_huella(pdf_bytes, registro, rn, ubicacion_huella)
    return pdf_bytes


# ---------------------------------------------------------------------------
# 2026-10-06: "Responsables:" debajo de Fetocardia, Parto, Vigilancia y
# Recién nacido (quién registró / corrigió / eliminó qué; sin valores).
# ---------------------------------------------------------------------------

def _responsables_pasos(registro, es_plantilla):
    if es_plantilla or getattr(registro, 'pk', None) is None:
        return {}
    try:
        from .responsables import responsables_por_seccion
        return responsables_por_seccion(registro)
    except Exception:
        return {}


def _agregar_responsables(elements, resp_pasos, seccion):
    filas = resp_pasos.get(seccion) or []
    if not filas:
        return
    from xml.sax.saxutils import escape
    estilo = ParagraphStyle(name=f'Resp_{seccion}', fontName='Helvetica', fontSize=6.5, leading=8.2,
                            textColor=colors.HexColor('#334155'), alignment=TA_LEFT)
    partes = [
        f"<b>{escape(_fix_mojibake_text(r['nombre']))}</b> ({escape('; '.join(r['detalle']))})"
        for r in filas
    ]
    tbl = Table([[Paragraph('<b>Responsables:</b> ' + ' &nbsp;·&nbsp; '.join(partes), estilo)]], colWidths=[ANCHO_UTIL])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(tbl)


# ---------------------------------------------------------------------------
# 2026-10-06: Controles de vigilancia posparto (Sangrado, Globo de seguridad y
# Sutura y heridas), una fila por minuto del cronograma 15/30/60 hasta 6 h.
# ---------------------------------------------------------------------------

MINUTOS_VIGILANCIA = [15, 30, 45, 60, 75, 90, 105, 120, 150, 180, 240, 300, 360]
ESTADO_CORTO = {
    'NORMAL': 'Normal', 'ALERTA': 'Alerta', 'VIGILAR': 'Vigilar',
    'HEMATOMA': 'Alerta: hematoma', 'INFECCION': 'Alerta: infección', 'NO_APLICA': 'No aplica',
}
COLOR_ESTADO_VIGILANCIA = {
    'NORMAL': '#059669', 'VIGILAR': '#d97706', 'ALERTA': '#dc2626',
    'HEMATOMA': '#dc2626', 'INFECCION': '#dc2626', 'NO_APLICA': '#64748b',
}


def _tabla_vigilancia_posparto(registro, es_plantilla):
    hay_registro = not es_plantilla and getattr(registro, 'pk', None) is not None
    sangrado = {c.minuto_control: c for c in registro.controles_sangrado.all()} if hay_registro else {}
    globo = {c.minuto_control: c for c in registro.controles_globo.all()} if hay_registro else {}
    sutura = {c.minuto_control: c for c in registro.controles_sutura.all()} if hay_registro else {}
    # Siempre el cronograma completo (para diligenciar a mano en la
    # plantilla) más cualquier minuto fuera de él que se haya guardado.
    minutos = sorted(set(MINUTOS_VIGILANCIA) | set(sangrado) | set(globo) | set(sutura))

    estilo_celda = ParagraphStyle(name='VigCelda', fontName='Helvetica', fontSize=6.5, leading=8, alignment=TA_CENTER)
    estilo_sub = ParagraphStyle(name='VigSub', fontName='Helvetica-Bold', fontSize=6.3, leading=7.5,
                                alignment=TA_CENTER, textColor=colors.white)

    def estado(codigo):
        if not codigo:
            return ''
        color = COLOR_ESTADO_VIGILANCIA.get(codigo, '#1e293b')
        return Paragraph(f"<font color='{color}'><b>{ESTADO_CORTO.get(codigo, codigo)}</b></font>", estilo_celda)

    def hora(control):
        return control.hora.strftime('%H:%M') if control and control.hora else ''

    acumulado = 0
    filas = [
        ['CONTROLES DE VIGILANCIA POSPARTO (cada 15 min las primeras 2 h, cada 30 min la hora siguiente y cada hora hasta 6 h)'] + [''] * 8,
        ['', 'SANGRADO CUANTIFICADO', '', '', '', 'GLOBO DE SEGURIDAD', '', 'SUTURA Y HERIDAS', ''],
        [Paragraph(t, estilo_sub) for t in ('Control', 'Hora', 'c.c.', 'Acumulado', 'Semáforo', 'Hora', 'Estado', 'Hora', 'Estado')],
    ]
    for minuto in minutos:
        s, g, su = sangrado.get(minuto), globo.get(minuto), sutura.get(minuto)
        if s:
            acumulado += s.cc
        etiqueta = f"{minuto} min" + (' (6 h)' if minuto == 360 else '')
        filas.append([
            etiqueta,
            hora(s), f"{s.cc}" if s else '', f"{acumulado}" if s else '', estado(s.estado if s else None),
            hora(g), estado(g.estado if g else None),
            hora(su), estado(su.estado if su else None),
        ])

    ancho = ANCHO_UTIL
    cw_fijas = [1.7*cm, 1.15*cm, 1.15*cm, 1.55*cm, 1.75*cm, 1.15*cm, 0, 1.15*cm, 0]
    resto = (ancho - sum(cw_fijas)) / 2
    cw = [w or resto for w in cw_fijas]
    tbl = Table(filas, colWidths=cw, repeatRows=3)
    fila_360 = 3 + minutos.index(360) if 360 in minutos else None
    estilo = [
        ('SPAN', (0, 0), (-1, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('SPAN', (0, 1), (0, 2)),
        ('SPAN', (1, 1), (4, 1)),
        ('SPAN', (5, 1), (6, 1)),
        ('SPAN', (7, 1), (8, 1)),
        ('BACKGROUND', (0, 1), (-1, 2), colors.HexColor('#0c4a6e')),
        ('TEXTCOLOR', (0, 1), (-1, 2), colors.white),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, 1), 6.8),
        ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 3), (0, -1), COLOR_LABEL),
        ('FONTNAME', (0, 3), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 3), (-1, -1), 6.5),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('BOX', (0, 0), (-1, -1), BORDE, COLOR_BORDE),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        # Separadores más marcados entre Sangrado | Globo | Sutura.
        ('LINEBEFORE', (5, 1), (5, -1), BORDE, COLOR_BORDE),
        ('LINEBEFORE', (7, 1), (7, -1), BORDE, COLOR_BORDE),
        ('LINEBEFORE', (1, 1), (1, -1), BORDE, COLOR_BORDE),
    ]
    if fila_360 is not None:
        # El control de las 6 h es el que habilita el cierre: se resalta.
        estilo.append(('BACKGROUND', (0, fila_360), (-1, fila_360), colors.HexColor('#ecfeff')))
        estilo.append(('BACKGROUND', (0, fila_360), (0, fila_360), colors.HexColor('#cffafe')))
    tbl.setStyle(TableStyle(estilo))
    return tbl


# ---------------------------------------------------------------------------
# 2026-09-30: Control del recién nacido + huella plantar.
# Misma distribución del formato físico: datos a la izquierda (una sola tabla
# en cuadrícula etiqueta | valor | etiqueta | valor, cada valor como Paragraph
# para que ajuste en varias líneas sin desbordarse) y el recuadro HUELLA a la
# derecha, ocupando todas las filas. La huella (PDF escaneado) se incrusta
# DENTRO de ese recuadro después de construir el documento: _TablaConHuella
# registra al dibujarse la posición exacta del recuadro en la página, y
# _incrustar_huella pone ahí la primera hoja de la huella (vectorial, escalada).
# ---------------------------------------------------------------------------

ANCHO_HUELLA = 5.4 * cm
MARGEN_HUELLA = 0.18 * cm


def _recien_nacido(registro, es_plantilla):
    if es_plantilla or getattr(registro, 'pk', None) is None:
        return None
    from .models import ControlRecienNacido
    return ControlRecienNacido.objects.filter(registro_id=registro.pk).first()


def _hora_nacimiento(registro, rn):
    """Hora de nacimiento = hora de parto. Registros anteriores al 2026-09-30
    pudieron guardar una hora de nacimiento propia: si existe, se respeta."""
    if rn is not None and rn.hora_nacimiento:
        return rn.hora_nacimiento
    return getattr(registro, 'hora_parto', None)


class _TablaConHuella(Table):
    """Table que, al dibujarse, guarda en `ubicacion` la página y el
    rectángulo absoluto (en puntos) de la celda HUELLA (última columna, todas
    las filas de datos)."""

    def __init__(self, *args, ubicacion=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._ubicacion = ubicacion if ubicacion is not None else {}

    def draw(self):
        super().draw()
        x0, x1 = self._colpositions[-2], self._colpositions[-1]
        y_arriba, y_abajo = self._rowpositions[1], self._rowpositions[-1]
        ax, ay = self.canv.absolutePosition(x0, y_abajo)
        self._ubicacion.update({
            'pagina': self.canv.getPageNumber(),
            'x': ax, 'y': ay, 'ancho': x1 - x0, 'alto': y_arriba - y_abajo,
        })


def _tabla_recien_nacido(registro, rn, es_plantilla, ubicacion):
    estilo_lbl = ParagraphStyle(name='RNLbl', fontName='Helvetica-Bold', fontSize=7, leading=8.6,
                                textColor=colors.HexColor('#334155'))
    estilo_val = ParagraphStyle(name='RNVal', fontName='Helvetica', fontSize=7.5, leading=9.2,
                                textColor=COLOR_TEXTO)
    estilo_huella = ParagraphStyle(name='RNHuella', fontName='Helvetica', fontSize=7, leading=9,
                                   alignment=TA_CENTER, textColor=colors.HexColor('#94a3b8'))
    vacio = '' if es_plantilla else '—'

    def txt(valor, sufijo=''):
        if valor is None or valor == '':
            return vacio
        if hasattr(valor, 'strftime'):
            return valor.strftime('%H:%M')
        if hasattr(valor, 'normalize'):  # Decimal: 2495.00 -> 2495
            valor = format(valor.normalize(), 'f')
        return f"{_fix_mojibake_text(valor)}{sufijo}"

    def v(attr, sufijo=''):
        return txt(None if rn is None else getattr(rn, attr, None), sufijo)

    def sino(attr):
        """[X] Sí  [ ] No -- sin marcar ninguna si no hay dato (o plantilla)."""
        valor = None if rn is None else getattr(rn, attr, None)
        si = 'X' if valor is True else '&nbsp;&nbsp;'
        no = 'X' if valor is False else '&nbsp;&nbsp;'
        return f"[{si}] Sí &nbsp;&nbsp; [{no}] No"

    def marca(attr, opcion):
        valor = None if rn is None else getattr(rn, attr, None)
        return 'X' if valor == opcion else '&nbsp;&nbsp;'

    def check(attr):
        return 'X' if (rn is not None and getattr(rn, attr, False)) else '&nbsp;&nbsp;'

    L = lambda t: Paragraph(t, estilo_lbl)
    V = lambda t: Paragraph(t if t else '&nbsp;', estilo_val)

    glucos = ''
    if rn is not None:
        glucos = ' &nbsp;·&nbsp; '.join(
            f"{g.hora:%H:%M} → {format(g.resultado.normalize(), 'f')} mg/dL"
            for g in rn.glucometrias.order_by('hora')
        )
    parto_atendido = '' if es_plantilla else (_fix_mojibake_text(registro.parto_atendido_por) or '—')
    apgar = (f"1': <b>{v('apgar_1min')}</b> &nbsp; 5': <b>{v('apgar_5min')}</b> &nbsp; "
             f"10': <b>{v('apgar_10min')}</b>")
    oxi = lambda a, b: f"Pre: <b>{v(a, '%')}</b> &nbsp; Pos: <b>{v(b, '%')}</b>"
    # 2026-10-01: tomas de las 12, 24 y 48 h (ta_* = 12 h, ta24_*, ta48_*).
    # 2026-10-02: + al nacimiento (tanac_*) y FC al nacimiento.
    ta = lambda p: (f"MSD: <b>{v(p + '_msd')}</b> &nbsp; MSI: <b>{v(p + '_msi')}</b> &nbsp; "
                    f"MID: <b>{v(p + '_mid')}</b> &nbsp; MIIZ: <b>{v(p + '_miiz')}</b>")

    # Filas de datos: [etiqueta, valor, etiqueta, valor]; None en la 3a
    # posición = el valor ocupa las 3 columnas (texto largo).
    datos = [
        ['Hora de nacimiento', txt(_hora_nacimiento(registro, rn)), 'Pasa a UCI neonatal', sino('pasa_uci_neonatal')],
        ['Causa', v('causa_uci'), None, None],
        ['Género', f"[{marca('genero', 'M')}] M &nbsp; [{marca('genero', 'F')}] F &nbsp; [{marca('genero', 'I')}] I",
         'Peso', v('peso', ' g')],
        ['Talla', v('talla', ' cm'), 'Perímetro cefálico', v('pc', ' cm')],
        ['Perímetro torácico', v('pt', ' cm'), 'Perímetro abdominal', v('p_abd', ' cm')],
        ['APGAR', apgar, 'TSH tomada', sino('tsh_tomada')],
        ['Hemoclasificación', v('hemoclasificacion'), 'Vacunas', f"[{check('vacuna_hb')}] HB &nbsp; [{check('vacuna_bcg')}] BCG"],
        ['Líquido amniótico', v('caracteristicas_liquido_amniotico'), None, None],
        ['Lavado gástrico', sino('lavado_gastrico'), 'Elimina', sino('lavado_elimina')],
        ['Meconio', sino('meconio'), 'Valorado por pediatra antes del egreso', sino('valorado_pediatra')],
        ['Oximetría al nacer', oxi('oximetria_nacimiento_preductal', 'oximetria_nacimiento_posductal'),
         'Oximetría a las 12 h', oxi('oximetria_12h_preductal', 'oximetria_12h_posductal')],
        ['TA neonato al nacer', ta('tanac'), None, None],
        ['FC al nacer', v('fc_nacimiento', ' lpm'), None, None],
        ['Al nacimiento: TA 12 h', ta('tanac12'), None, None],
        ['Al nacimiento: TA 24 h', ta('tanac24'), None, None],
        ['Al nacimiento: TA 48 h', ta('tanac48'), None, None],
        ['TA neonato 12 h', ta('ta'), None, None],
        ['TA neonato 24 h', ta('ta24'), None, None],
        ['TA neonato 48 h', ta('ta48'), None, None],
        ['Glucometrías', glucos or ('No aplica' if rn is not None and rn.glucometrias_no_aplica else vacio), None, None],
        ['Parto atendido por', parto_atendido, 'Neonato atendido por', v('neonato_atendido_por')],
    ]

    if rn is not None and rn.huella_pdf:
        celda_huella = ''  # la huella se incrusta aquí después (_incrustar_huella)
    elif es_plantilla:
        celda_huella = ''  # recuadro vacío para tomar la huella en tinta
    else:
        celda_huella = Paragraph('Sin huella cargada', estilo_huella)

    filas = [['CONTROL DEL RECIÉN NACIDO', '', '', '', 'HUELLA PLANTAR']]
    estilos = [
        ('SPAN', (0, 0), (3, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (3, 0), 9),
        ('FONTSIZE', (4, 0), (4, 0), 7.5),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3.2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.2),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('BOX', (0, 0), (-1, -1), BORDE, COLOR_BORDE),
        ('INNERGRID', (0, 1), (3, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('LINEBEFORE', (4, 0), (4, -1), BORDE, COLOR_BORDE),
    ]
    for i, (l1, v1, l2, v2) in enumerate(datos, start=1):
        if l2 is None:
            filas.append([L(l1), V(v1), '', '', ''])
            estilos.append(('SPAN', (1, i), (3, i)))
        else:
            filas.append([L(l1), V(v1), L(l2), V(v2), ''])
        estilos.append(('BACKGROUND', (0, i), (0, i), COLOR_LABEL))
        if l2 is not None:
            estilos.append(('BACKGROUND', (2, i), (2, i), COLOR_LABEL))
    ultima = len(filas) - 1
    filas[1][4] = celda_huella
    estilos += [('SPAN', (4, 1), (4, ultima)), ('VALIGN', (4, 1), (4, ultima), 'MIDDLE')]

    ancho_datos = ANCHO_UTIL - ANCHO_HUELLA
    cw = [ancho_datos * f for f in (0.20, 0.30, 0.22, 0.28)] + [ANCHO_HUELLA]
    tbl = _TablaConHuella(filas, colWidths=cw, ubicacion=ubicacion)
    tbl.setStyle(TableStyle(estilos))
    return [tbl]


def _pagina_huella(rn):
    """Hojas del PDF de la huella (lista vacía si no se puede leer)."""
    import logging
    from pypdf import PdfReader
    try:
        with rn.huella_pdf.open('rb') as f:
            paginas = list(PdfReader(io.BytesIO(f.read())).pages)
        for p in paginas:
            p.transfer_rotation_to_content()
        return paginas
    except Exception:
        logging.getLogger(__name__).exception('No se pudo leer el PDF de la huella del RN (rn %s)', rn.pk)
        return []


def _encajar(pagina_destino, pagina_huella, x, y, ancho, alto):
    """Pone pagina_huella escalada y centrada dentro del rectángulo (x, y, ancho, alto)."""
    from pypdf import Transformation
    caja = pagina_huella.mediabox
    w, h = float(caja.width), float(caja.height)
    escala = min(ancho / w, alto / h)
    tx = x + (ancho - w * escala) / 2 - float(caja.left) * escala
    ty = y + (alto - h * escala) / 2 - float(caja.bottom) * escala
    pagina_destino.merge_transformed_page(pagina_huella, Transformation().scale(escala, escala).translate(tx, ty))


def _texto_en_rect(pagina_destino, x, y, ancho, alto, texto):
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas as rl_canvas
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(float(pagina_destino.mediabox.width), float(pagina_destino.mediabox.height)))
    c.setFont('Helvetica-Bold', 7)
    c.setFillColor(colors.HexColor('#b91c1c'))
    for i, linea in enumerate(texto.split('\n')):
        c.drawCentredString(x + ancho / 2, y + alto / 2 - i * 9, linea)
    c.showPage()
    c.save()
    buf.seek(0)
    pagina_destino.merge_page(PdfReader(buf).pages[0])


def _incrustar_huella(pdf_bytes, registro, rn, ubicacion):
    """Incrusta la primera hoja de la huella dentro del recuadro HUELLA. Si el
    PDF de la huella trae más hojas (máx. 3), las adicionales van al final
    con el mismo encabezado de identificación (_anexar_hojas_huella)."""
    from pypdf import PdfReader, PdfWriter

    escritor = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    paginas = _pagina_huella(rn)
    if ubicacion.get('pagina'):
        destino = escritor.pages[ubicacion['pagina'] - 1]
        x = ubicacion['x'] + MARGEN_HUELLA
        y = ubicacion['y'] + MARGEN_HUELLA
        ancho = ubicacion['ancho'] - 2 * MARGEN_HUELLA
        alto = ubicacion['alto'] - 2 * MARGEN_HUELLA
        if paginas:
            _encajar(destino, paginas[0], x, y, ancho, alto)
            if len(paginas) > 1:
                _texto_en_rect(destino, x, y - alto / 2 + 10, ancho, alto,
                               f'+{len(paginas) - 1} hoja(s) adicional(es) al final')
        else:
            _texto_en_rect(destino, x, y, ancho, alto, 'No se pudo incluir\nla huella. Verifíquela\nen el sistema.')
    else:
        # No debería pasar (la tabla siempre se dibuja); por si acaso, todas al final.
        _anexar_hojas_huella(escritor, registro, rn, paginas)
        paginas = []
    if len(paginas) > 1:
        _anexar_hojas_huella(escritor, registro, rn, paginas[1:], desde=2, total=len(paginas))
    salida = io.BytesIO()
    escritor.write(salida)
    return salida.getvalue()


def _anexar_hojas_huella(escritor, registro, rn, paginas, desde=1, total=None):
    """Hojas adicionales de la huella al final, con encabezado de identificación."""
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas as rl_canvas
    from django.utils import timezone

    total = total or len(paginas)
    ancho_pag, alto_pag = A4
    caja_x, caja_y = MARGIN, MARGIN
    caja_w = ancho_pag - 2 * MARGIN
    caja_h = alto_pag - 2 * MARGIN - 3.2 * cm
    subida = ''
    if rn.huella_subida_en:
        subida = f"Cargada por {rn.huella_subida_por or '—'} el {timezone.localtime(rn.huella_subida_en):%d/%m/%Y %I:%M %p}"
    for n, pagina in enumerate(paginas, start=desde):
        buf = io.BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=A4)
        y = alto_pag - MARGIN
        c.setFillColor(COLOR_HEADER)
        c.rect(MARGIN, y - 0.75 * cm, caja_w, 0.75 * cm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont('Helvetica-Bold', 10)
        c.drawCentredString(ancho_pag / 2, y - 0.52 * cm,
                            f'HUELLA PLANTAR DEL RECIÉN NACIDO · FRSPA-007 (hoja {n} de {total})')
        c.setFillColor(COLOR_TEXTO)
        c.setFont('Helvetica-Bold', 8)
        c.drawString(MARGIN, y - 1.35 * cm, f"Madre: {_fix_mojibake_text(registro.nombre_paciente)}")
        c.drawRightString(MARGIN + caja_w, y - 1.35 * cm, f"Identificación: {_safe_str(registro.identificacion)}")
        c.setFont('Helvetica', 7.5)
        c.drawRightString(MARGIN + caja_w, y - 1.9 * cm, subida)
        c.setStrokeColor(COLOR_BORDE)
        c.setLineWidth(BORDE)
        c.rect(caja_x, caja_y, caja_w, caja_h, stroke=1, fill=0)
        c.showPage()
        c.save()
        buf.seek(0)
        base = PdfReader(buf).pages[0]
        _encajar(base, pagina, caja_x + 0.3 * cm, caja_y + 0.3 * cm, caja_w - 0.6 * cm, caja_h - 0.6 * cm)
        escritor.add_page(base)
