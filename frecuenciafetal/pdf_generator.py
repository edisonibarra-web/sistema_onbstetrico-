"""
Generador de PDF para el formato FRSPA-007 - Control Fetocardia y Postparto
Estructura ordenada tipo plantilla hospitalaria.
"""
import io
import base64
import os
from reportlab.lib import colors, utils
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from .models import (
    FirmaPaciente, Huella
)
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, KeepTogether, PageBreak
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from django.conf import settings

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

    cw_part = [5.5*cm*ESCALA, 1.3*cm*ESCALA, 1.7*cm*ESCALA, 1.3*cm*ESCALA, 1.7*cm*ESCALA, 7.7*cm*ESCALA]

    estilo_tipo_label = ParagraphStyle(name='TipoLabel', fontName='Helvetica-Bold', fontSize=7, leading=9, alignment=TA_LEFT)
    tipo_cell = Paragraph('Tipo de parto:', estilo_tipo_label)

    data_part = [
        ['CARACTERÍSTICAS DEL PARTO', '', '', '', '', ''],
        [tipo_cell, '', '', '', '', ''],
        _fila_opcion('   Vaginal', registro.tipo_parto, 'VAGINAL'),
        _fila_opcion('   Cesárea', registro.tipo_parto, 'CESAREA'),
        _fila_opcion('   Instrumentado', registro.tipo_parto, 'INSTRUMENTADO'),
        _fila_booleana('Episiotomía:', registro.episiotomia),
        ['Alumbramiento:', '', '', '', '', ''],
        _fila_booleana('   Activo', registro.tipo_alumbramiento in ('DIRIGIDO', 'MANUAL')),
    ]
    fila_subtitulo_alumbramiento = 6
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

    # Responsable único para todo el apartado (no por cada columna de control).
    responsable_fc = ''
    if not es_plantilla:
        responsable_fc = next((_safe_str(fc.responsable) for fc in fcs if fc.responsable), '') or '—'

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

    def _estado_sangrado(cc, tipo_parto):
        if cc is None:
            return None
        umbral = 1000 if tipo_parto == 'CESAREA' else 500
        if cc >= umbral:
            return 'ALERTA'
        if cc < 250:
            return 'NORMAL'
        return 'VIGILAR'

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
        estilo_meows_col = ParagraphStyle(name='MeowsCol', fontName='Helvetica-Bold', fontSize=5.5, leading=6.5, alignment=TA_CENTER, textColor=colors.white)
        estilo_meows_param = ParagraphStyle(name='MeowsParam', fontName='Helvetica-Bold', fontSize=6, leading=7, alignment=TA_LEFT)
        estilo_meows_total = ParagraphStyle(name='MeowsTotal', fontName='Helvetica-Bold', fontSize=6, leading=7, alignment=TA_CENTER, textColor=colors.white)

        # 2026-09-11: con muchas horas registradas (>10-12) la tabla ya no
        # cabía en el ancho de la hoja A4 -- el ancho de columna se calculaba
        # dividiendo el espacio disponible entre TODAS las columnas pero con
        # un piso de 0.9cm que, pasado cierto número de columnas, hacía que
        # la tabla completa se saliera de la página y quedara cortada/
        # desbordada. Se pagina igual que el PDF MEOWS independiente
        # (meows/generador_pdf_meows.py, MEDICIONES_POR_PAGINA=10): una tabla
        # nueva cada 10 horas, cada una repitiendo PARÁMETRO/VALOR/PUNTAJE,
        # en vez de una sola tabla imposible de encajar.
        MEOWS_COLS_POR_PAGINA = 10
        ancho_param_m = 3.0*cm
        ancho_valor_m = 1.5*cm
        ancho_punt_m = 1.1*cm
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
                ('FONTSIZE', (0, 1), (-1, 1), 6),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (1, 2), (1, -2), 'CENTER'),
                ('ALIGN', (2, 2), (-1, -1), 'CENTER'),
                ('FONTSIZE', (0, 2), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
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

    # ========== FIRMA DEL RESPONSABLE + BIOMETRÍA ==========
    tiene_huella_paciente = bool(registro.identificacion) and FirmaPaciente.objects.filter(
        paciente_id=registro.identificacion.replace('.', '').replace('-', '')
    ).exists()
    # Antes solo se imprimía este bloque si había imagen de firma dibujada o huella;
    # si el responsable solo alcanzó a escribir su nombre (sin dibujar la firma en el
    # pad), no se imprimía nada, ni siquiera el nombre. Ahora también se imprime con
    # el nombre solo, para que el responsable y su nombre siempre queden en el PDF.
    #
    # 2026-09-11: `nombre_firma_paciente` ahora también puede llegar precargado
    # desde el campo "RESPONSABLE DEL REGISTRO" aunque el registro todavía no
    # se haya guardado (ver descargar_pdf_plantilla en views.py) -- a pedido
    # explícito, el responsable debe quedar integrado en el PDF aunque
    # todavía no haya una firma real dibujada, y sin mostrar una caja de
    # firma en blanco simulando un espacio para firmar a mano que no existe.
    tiene_firma_real = bool(registro.firma_paciente or tiene_huella_paciente or registro.fecha_hora_firma)
    tiene_responsable = bool((registro.nombre_firma_paciente or registro.profesional_nombre or '').strip())
    if tiene_firma_real or tiene_responsable:
        elements.append(Spacer(1, 0.5*cm))
        
        # Firma Manuscrita
        img_manuscrita = None
        if registro.firma_paciente:
            try:
                # 1. Intentar por path físico si existe
                if os.path.exists(registro.firma_paciente.path):
                    img_manuscrita = Image(registro.firma_paciente.path, width=5.0*cm, height=2.0*cm, kind='proportional')
                else:
                    # 2. Fallback memoria
                    registro.firma_paciente.open('rb')
                    img_bytes = io.BytesIO(registro.firma_paciente.read())
                    registro.firma_paciente.close()
                    img_manuscrita = Image(img_bytes, width=5.0*cm, height=2.0*cm, kind='proportional')
            except Exception as e_sig:
                print(f"Error cargando firma manuscrita Fetal: {e_sig}")
                img_manuscrita = None

        # Huella Biométrica
        img_biometrica = None
        id_numerica = registro.identificacion.replace('.', '').replace('-', '')
        
        # 1. Buscar en FirmaPaciente vinculada al formulario
        huella_obj = FirmaPaciente.objects.filter(formulario=registro).order_by('-fecha').first()
        
        # 2. Si no hay, buscar en FirmaPaciente por ID de paciente
        if not huella_obj:
            huella_obj = FirmaPaciente.objects.filter(paciente_id=id_numerica).order_by('-fecha').first()
            
        if huella_obj and huella_obj.imagen_huella:
            try:
                # Intentar por path físico si existe
                if os.path.exists(huella_obj.imagen_huella.path):
                    img_biometrica = Image(huella_obj.imagen_huella.path, width=2.5*cm, height=3.0*cm, kind='proportional')
                else:
                    # Fallback memoria
                    huella_obj.imagen_huella.open('rb')
                    img_bytes = io.BytesIO(huella_obj.imagen_huella.read())
                    huella_obj.imagen_huella.close()
                    img_biometrica = Image(img_bytes, width=2.5*cm, height=3.0*cm, kind='proportional')
            except Exception as e_huella:
                print(f"Error cargando huella biométrica Fetal: {e_huella}")
                img_biometrica = None
        
        # 3. Si aún no hay, buscar en el modelo Huella (capturas directas Android)
        if not img_biometrica:
            huella_raw = Huella.objects.filter(documento=registro.identificacion).order_by('-fecha').first()
            if not huella_raw:
                # Reintentar con ID numérica por si acaso
                huella_raw = Huella.objects.filter(documento=id_numerica).order_by('-fecha').first()
                
            if huella_raw and huella_raw.imagen_huella:
                try:
                    try:
                        huella_path = huella_raw.imagen_huella.path
                        img_biometrica = Image(huella_path, width=2.5*cm, height=3.0*cm, kind='proportional')
                    except Exception:
                        huella_raw.imagen_huella.open('rb')
                        img_bytes = io.BytesIO(huella_raw.imagen_huella.read())
                        huella_raw.imagen_huella.close()
                        img_biometrica = Image(img_bytes, width=2.5*cm, height=3.0*cm, kind='proportional')
                except Exception:
                    pass

        fecha_firma = registro.fecha_hora_firma.strftime('%d/%m/%Y %H:%M') if registro.fecha_hora_firma else (huella_obj.fecha.strftime('%d/%m/%Y %H:%M') if huella_obj else '—')
        
        # Organizar en tabla
        col_firma = []
        if img_manuscrita:
            col_firma.append(img_manuscrita)
        sig_name = (_fix_mojibake_text(registro.nombre_firma_paciente) or "").strip()
        prof_name = (_fix_mojibake_text(registro.profesional_nombre) or "").strip()
        final_name = sig_name or prof_name or "—"

        col_firma.append(Paragraph(f"<b>{final_name}</b>", styles['Normal']))
        # Solo se rotula "FIRMA DEL RESPONSABLE" cuando de verdad hay una firma,
        # huella o fecha de firma real -- si únicamente se conoce el nombre del
        # responsable (aún sin firmar), se etiqueta "RESPONSABLE" a secas para
        # no dar a entender que existe una firma que todavía no existe.
        etiqueta_firma = f"FIRMA DEL RESPONSABLE — {fecha_firma}" if tiene_firma_real else "RESPONSABLE"
        col_firma.append(Paragraph(f"<font size='7' color='#64748b'>{etiqueta_firma}</font>", styles['Normal']))

        col_biometria = []
        if img_biometrica:
            col_biometria.append(img_biometrica)
            col_biometria.append(Paragraph("<font size='7' color='#64748b'>HUELLA BIOMÉTRICA</font>", ParagraphStyle(name='CenterGray', parent=styles['Normal'], alignment=TA_CENTER)))

        data_firmas = [[col_firma, col_biometria]]
        tbl_firmas = Table(data_firmas, colWidths=[13.2*cm*ESCALA, 6.0*cm*ESCALA])
        tbl_firmas.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ('LINEABOVE', (0, 0), (0, 0), 0.5, colors.black),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(tbl_firmas)
    elif es_plantilla:
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

    # ========== FIRMA PROFESIONAL (DGH) ==========
    if registro.firma_profesional_base64:
        elements.append(Spacer(1, 0.5*cm))
        try:
            b64 = registro.firma_profesional_base64
            if ',' in b64:
                b64 = b64.split(',')[1]
            img_bytes = io.BytesIO(base64.b64decode(b64))
            img_prof = Image(img_bytes, width=5.0*cm, height=2.0*cm, kind='proportional')
            
            # Bloque de Validación similar a MEOWS
            elements.append(Spacer(1, 0.4*cm))
            valid_estilo = ParagraphStyle('ValidProf', parent=styles['Normal'], fontSize=8.5, fontName='Helvetica-Bold')
            valid_texto = (
                f"<b>VALIDACIÓN DE DILIGENCIAMIENTO (PROFESIONAL RESPONSABLE)</b><br/>"
                f"Responsable: {registro.profesional_nombre or '—'} | ID: {registro.profesional_identificacion or '—'} | T.P.: {registro.profesional_tarjeta_pro or '—'}<br/>"
                f"Fecha de Registro: {registro.created_at.strftime('%d/%m/%Y %H:%M')}"
            )
            
            data_prof = [
                [img_prof, ''],
                [Paragraph(valid_texto, valid_estilo), '']
            ]
            tbl_prof = Table(data_prof, colWidths=[6.0*cm*ESCALA, 13.2*cm*ESCALA])
            tbl_prof.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f1f5f9')),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LINEABOVE', (0, 0), (-1, -1), 0.5, colors.black),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ]))
            elements.append(tbl_prof)
        except Exception as e:
            elements.append(Paragraph(f"<font size='7' color='red'>Error al cargar firma profesional: {str(e)}</font>", styles['Normal']))

    doc.build(elements)
    return buffer.getvalue()
