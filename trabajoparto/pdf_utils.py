from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch, cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.utils import ImageReader
from datetime import datetime
from django.http import HttpResponse
from django.conf import settings
from django.utils.timezone import localtime
from django.db.models import Q
import os
import logging
import tempfile
from PIL import Image

# Configurar logger básico
logger = logging.getLogger(__name__)


def encabezado(c, formulario, ancho, y_inicial):
    """
    Dibuja el encabezado institucional del PDF con logo, título y metadatos.
    Estructura idéntica al formato físico FRSPA-022 avalado por Calidad:
    Logo | Título | (CÓDIGO/VERSIÓN + FECHA DE ELABORACIÓN/ACTUALIZACIÓN + HOJA) | Logo Acreditación.
    """
    from django.contrib.staticfiles import finders
    from reportlab.platypus import Table, TableStyle, Paragraph, Image, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    styles = getSampleStyleSheet()

    # Estilos específicos para el encabezado
    estilo_titulo = ParagraphStyle(
        'TituloPDF',
        parent=styles['Normal'],
        fontSize=10.5,
        fontName='Helvetica-Bold',
        alignment=1,
        leading=12,
    )

    estilo_meta_label = ParagraphStyle(
        'MetaLabelPDF',
        parent=styles['Normal'],
        fontSize=6.5,
        fontName='Helvetica-Bold',
        alignment=0,
        leading=7.5,
    )

    estilo_meta_valor = ParagraphStyle(
        'MetaValorPDF',
        parent=styles['Normal'],
        fontSize=6.5,
        fontName='Helvetica',
        alignment=0,
        leading=7.5,
    )

    estilo_hoja = ParagraphStyle(
        'HojaPDF',
        parent=styles['Normal'],
        fontSize=6.5,
        fontName='Helvetica-Bold',
        alignment=1,
        leading=7.5,
    )

    # 1. Logos (buscados vía el finder de estáticos de Django, funciona sin importar la app)
    logo_hospital_path = finders.find('img/logo_hospital.png')
    logo_acreditacion_path = finders.find('img/logo_acreditacion.png')

    # 2. Preparar CONTENIDO
    # Logo Hospital (Izquierda)
    col_logo = []
    if logo_hospital_path:
        try:
            img_h = Image(logo_hospital_path, width=3.2*cm, height=1.14*cm)
            col_logo.append(img_h)
        except:
            col_logo.append(Paragraph("LOGO HOSPITAL", estilo_meta_valor))
    else:
        col_logo.append(Paragraph("LOGO HOSPITAL", estilo_meta_valor))

    # Título (Centro)
    col_titulo = [
        Paragraph("<b>CONTROL DE TRABAJO DE PARTO</b>", estilo_titulo),
    ]

    # 3. Anchos de columnas del encabezado (calculados antes de armar la grilla anidada de metadatos)
    ancho_util = ancho - 2*cm # Margen de 1cm a cada lado
    col_widths = [ancho_util * 0.24, ancho_util * 0.32, ancho_util * 0.32, ancho_util * 0.12]
    ancho_meta = col_widths[2]  # ocupa el 100% de la celda para que las líneas lleguen al borde

    # Metadatos del control documental: grilla CÓDIGO/VERSIÓN | FECHA DE ELABORACIÓN/ACTUALIZACIÓN + HOJA
    # Son metadatos FIJOS del formato avalado por Calidad (no varían por paciente/registro),
    # por lo que se fijan como constantes en vez de leerse de formulario.codigo/version.
    codigo_formato = 'FRSPA-022'
    version_formato = '01'
    fecha_elaboracion_formato = '2 DE MARZO DE 2018'
    fecha_actualizacion_formato = '2 DE MARZO DE 2018'

    data_meta = [
        [Paragraph('<b>CÓDIGO:</b>', estilo_meta_label), Paragraph('<b>FECHA DE ELABORACIÓN:</b>', estilo_meta_label)],
        [Paragraph(codigo_formato, estilo_meta_valor), Paragraph(fecha_elaboracion_formato, estilo_meta_valor)],
        [Paragraph('<b>VERSIÓN:</b>', estilo_meta_label), Paragraph('<b>FECHA DE ACTUALIZACIÓN:</b>', estilo_meta_label)],
        [Paragraph(version_formato, estilo_meta_valor), Paragraph(fecha_actualizacion_formato, estilo_meta_valor)],
        [Paragraph('<b>HOJA: 1 DE: 1</b>', estilo_hoja), ''],
    ]
    tabla_meta = Table(data_meta, colWidths=[ancho_meta * 0.5, ancho_meta * 0.5])
    tabla_meta.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('SPAN', (0, 4), (1, 4)),
        ('ALIGN', (0, 4), (1, 4), 'CENTER'),
        # Delimitadores: línea vertical entre CÓDIGO/VERSIÓN y las fechas, y línea horizontal
        # entre el bloque CÓDIGO y el bloque VERSIÓN, igual que el formato avalado
        ('LINEAFTER', (0, 0), (0, 3), 0.6, colors.black),
        ('LINEBELOW', (0, 1), (1, 1), 0.6, colors.black),
        ('LINEABOVE', (0, 4), (1, 4), 0.6, colors.black),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
    ]))
    col_meta = [tabla_meta]

    # Logo de Acreditación (Extrema Derecha)
    col_cert = []
    if logo_acreditacion_path:
        try:
            img_a = Image(logo_acreditacion_path, width=1.5*cm, height=1.5*cm)
            col_cert.append(img_a)
        except:
            pass

    # 4. Construir TABLA de encabezado
    data = [[col_logo, col_titulo, col_meta, col_cert]]
    tabla = Table(data, colWidths=col_widths)

    tabla.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (2, 0), (2, 0), 'CENTER'),
        ('ALIGN', (3, 0), (3, 0), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        # Sin padding en la celda de metadatos: la tabla anidada llena la celda completa
        # para que sus líneas queden a ras de los bordes izquierdo y derecho.
        ('LEFTPADDING', (2, 0), (2, 0), 0),
        ('RIGHTPADDING', (2, 0), (2, 0), 0),
        ('TOPPADDING', (2, 0), (2, 0), 0),
        ('BOTTOMPADDING', (2, 0), (2, 0), 0),
    ]))

    # Dibujar la tabla en el canvas
    w_t, h_t = tabla.wrap(ancho_util, 4*cm)
    tabla.drawOn(c, 1*cm, y_inicial - h_t)

    return y_inicial - h_t

def seccion_biometria(c, reg_huella, reg_firma, x, y, ancho, responsable_nombre=""):
    """
    Dibuja la sección de biometría (huella y firma del paciente) y el área del responsable.
    """
    from reportlab.platypus import Table, TableStyle, Paragraph, Image, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    
    styles = getSampleStyleSheet()
    
    estilo_label = ParagraphStyle(
        'LabelBiometria',
        parent=styles['Normal'],
        fontSize=8,
        fontName='Helvetica-Bold',
        alignment=1,
    )
    
    estilo_sub = ParagraphStyle(
        'SubBiometria',
        parent=styles['Normal'],
        fontSize=7,
        fontName='Helvetica',
        alignment=1,
    )

    # 1. Preparar Huella (COMENTADO POR SOLICITUD DEL USUARIO)
    """
    huella_content = [Spacer(1, 40)]
    if reg_huella and reg_huella.imagen:
        try:
            path_h = reg_huella.imagen.path
            if os.path.exists(path_h):
                img_h = Image(path_h, width=2.5*cm, height=3*cm)
                huella_content = [img_h]
            else:
                huella_content = [Paragraph("<i>Huella no disponible en sistema</i>", estilo_sub)]
        except Exception as e:
            logger.error(f"Error cargando imagen de huella: {e}")
            huella_content = [Paragraph("<i>Error al cargar huella</i>", estilo_sub)]
    else:
        huella_content = [Spacer(1, 10), Paragraph("<i>Huella no registrada</i>", estilo_sub), Spacer(1, 10)]
    """

    # 2. Preparar Firma Responsable (Antes etiquetada como Firma Paciente)
    firma_responsable_content = [Spacer(1, 40)]
    if reg_firma and reg_firma.imagen_firma:
        try:
            path_f = reg_firma.imagen_firma.path
            if os.path.exists(path_f):
                img_f = Image(path_f, width=4.5*cm, height=2.5*cm)
                firma_responsable_content = [img_f]
            else:
                firma_responsable_content = [Paragraph("<i>Firma no disponible en sistema</i>", estilo_sub)]
        except Exception as e:
            logger.error(f"Error cargando imagen de firma: {e}")
            firma_responsable_content = [Paragraph("<i>Error al cargar firma</i>", estilo_sub)]
    else:
        firma_responsable_content = [Spacer(1, 10), Paragraph("<i>Firma no registrada</i>", estilo_sub), Spacer(1, 10)]

    # 3. Preparar Datos del Responsable
    responsable_content = [
        Spacer(1, 40),
        Paragraph(f"<b>{responsable_nombre.upper() if responsable_nombre else '—'}</b>", estilo_label),
        Paragraph("RESPONSABLE DEL REGISTRO", estilo_sub)
    ]

    # 4. Construir Tabla (Ahora de 2 columnas: Firma y Nombre del Responsable)
    ancho_util = ancho - 2*cm
    data = [
        [firma_responsable_content, responsable_content],
        [Paragraph("FIRMA DEL RESPONSABLE", estilo_label), Paragraph("NOMBRE DEL RESPONSABLE", estilo_label)]
    ]
    
    col_widths = [ancho_util * 0.50, ancho_util * 0.50]
    tabla = Table(data, colWidths=col_widths)
    
    tabla.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('LINEABOVE', (0, 1), (-1, 1), 0.5, colors.black), # Línea de firma
        ('TOPPADDING', (0, 1), (-1, 1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))

    w_t, h_t = tabla.wrap(ancho_util, 8*cm)
    
    # Si no cabe en la página actual, retornar un valor que indique salto de página (manejado por el llamador)
    if y - h_t < 1*cm:
        return -1 # Indica que no hay espacio
        
    tabla.drawOn(c, 1*cm, y - h_t)
    return y - h_t


def datos_paciente(c, formulario, x, y):
    """
    Datos del paciente (ESTRUCTURA)
    Dibuja los datos del paciente en el PDF usando una tabla organizada.
    """
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    
    styles = getSampleStyleSheet()
    p = formulario.paciente
    
    estilo_label = ParagraphStyle(
        'LabelPaciente',
        parent=styles['Normal'],
        fontSize=8,
        fontName='Helvetica-Bold',
        leading=10,
    )
    
    estilo_valor = ParagraphStyle(
        'ValorPaciente',
        parent=styles['Normal'],
        fontSize=9,
        fontName='Helvetica',
        leading=11,
    )

    data = [
        [Paragraph("<b>PACIENTE:</b>", estilo_label), Paragraph(p.nombres or "—", estilo_valor), 
         Paragraph("<b>IDENTIFICACIÓN:</b>", estilo_label), Paragraph(p.num_identificacion or "—", estilo_valor)],
        [Paragraph("<b>H. CLÍNICA:</b>", estilo_label), Paragraph(p.num_historia_clinica or "—", estilo_valor), 
         Paragraph("<b>EDAD:</b>", estilo_label), Paragraph(f"{formulario.edad_snapshot or '—'} AÑOS", estilo_valor)],
        [Paragraph("<b>ASEGURADORA:</b>", estilo_label), Paragraph(formulario.aseguradora.nombre if formulario.aseguradora else "—", estilo_valor), 
         Paragraph("<b>GRUPO SANGUÍNEO:</b>", estilo_label), Paragraph(p.tipo_sangre or "—", estilo_valor)],
        [Paragraph("<b>EDAD GESTACIONAL:</b>", estilo_label), Paragraph(f"{formulario.edad_gestion or '—'} SEMANAS", estilo_valor), 
         Paragraph("<b>G_P_C_A_V_M:</b>", estilo_label), Paragraph(formulario.get_estado_display() if formulario.estado else "—", estilo_valor)],
        [Paragraph("<b>N° CONTROLES P.:</b>", estilo_label), Paragraph(str(formulario.n_controles_prenatales or "—"), estilo_valor), 
         Paragraph("<b>FECHA NACIMIENTO:</b>", estilo_label), Paragraph(p.fecha_nacimiento.strftime('%d/%m/%Y') if p.fecha_nacimiento else "—", estilo_valor)],
        [Paragraph("<b>DIAGNÓSTICO:</b>", estilo_label), Paragraph(formulario.diagnostico or "—", estilo_valor), "", ""]
    ]

    # Usar ancho de carta (letter) en horizontal (landscape) o A4 si se prefiere. 
    # El generador principal usa SimpleDocTemplate(A4). 
    ancho_util = A4[0] - 2*cm
    col_widths = [ancho_util * 0.20, ancho_util * 0.30, ancho_util * 0.20, ancho_util * 0.30]
    
    tabla = Table(data, colWidths=col_widths)
    tabla.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.gray),
        ('SPAN', (1, 5), (3, 5)), # Expandir diagnóstico
        ('BACKGROUND', (0, 0), (0, -1), colors.whitesmoke),
        ('BACKGROUND', (2, 0), (2, -1), colors.whitesmoke),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))

    w_t, h_t = tabla.wrap(ancho_util, 10*cm)
    tabla.drawOn(c, 1*cm, y - h_t)
    
    return y - h_t - 0.5*cm



def obtener_valor(valor):
    """
    Obtiene el valor de MedicionValor según su tipo.
    """
    if valor.valor_number is not None:
        return str(valor.valor_number)
    if valor.valor_text is not None:
        return valor.valor_text
    if valor.valor_boolean is not None:
        return "Sí" if valor.valor_boolean else "No"
    if valor.valor_json is not None:
        return str(valor.valor_json)
    return ""


def seccion_grid_mediciones(c, formulario, x, y, ancho_total):
    """
    Dibuja el grid de mediciones estilo formulario (10 columnas de tiempo).
    Usa tablas de ReportLab para un acabado profesional.
    """
    from .models import Item, Medicion
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    
    styles = getSampleStyleSheet()
    estilo_celda = ParagraphStyle('CeldaGrid', parent=styles['Normal'], fontSize=7, alignment=1)
    estilo_header = ParagraphStyle('HeaderGrid', parent=styles['Normal'], fontSize=7, fontName='Helvetica-Bold', alignment=1)
    estilo_param = ParagraphStyle('ParamGrid', parent=styles['Normal'], fontSize=7, fontName='Helvetica-Bold', alignment=0)

    # 1. Obtener mediciones
    mediciones = Medicion.objects.filter(formulario=formulario).prefetch_related('valores__campo', 'parametro')
    horas_unicas = sorted(list(set(m.tomada_en for m in mediciones)))
    horas_mostrar = horas_unicas[:10]
    
    # 2. Definir anchos
    ancho_util = ancho_total - 2*cm
    col_param = ancho_util * 0.25
    col_hora = (ancho_util - col_param) / 10
    col_widths = [col_param] + [col_hora] * 10

    # 3. Dibujar Encabezado
    header_data = [["PARÁMETRO"] + [h.strftime('%H:%M') for h in horas_mostrar] + [""] * (10 - len(horas_mostrar))]
    t_header = Table(header_data, colWidths=col_widths)
    t_header.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3b82f6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
    ]))
    
    w_h, h_h = t_header.wrap(ancho_util, 1*cm)
    t_header.drawOn(c, 1*cm, y - h_h)
    y -= h_h

    # 4. Dibujar Filas
    # Solo parámetros activos: los que ya no están disponibles en el formulario
    # (ej. Controles Maternos, Membranas Rotas) se desactivaron en vez de
    # borrarse, así que se excluyen aquí para no imprimir secciones/filas
    # vacías e inalcanzables desde la interfaz.
    items = Item.objects.prefetch_related('parametros__campos').all().order_by('id')
    for item in items:
        parametros_activos = [p for p in item.parametros.all() if p.activo]
        if not parametros_activos:
            continue

        # Fila de Item (Sección)
        t_item = Table([[item.nombre.upper()]], colWidths=[ancho_util])
        t_item.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eff6ff')),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ]))
        w_i, h_i = t_item.wrap(ancho_util, 1*cm)
        
        if y - h_i < 2*cm:
            c.showPage()
            y = A4[1] - 2*cm # Reiniciar Y en nueva página
            
        t_item.drawOn(c, 1*cm, y - h_i)
        y -= h_i

        for param in parametros_activos:
            row_vals = [Paragraph(param.nombre, estilo_param)]
            
            for hora in horas_mostrar:
                med_h = next((m for m in mediciones if m.parametro_id == param.id and m.tomada_en == hora), None)
                if med_h:
                    vals_str = " / ".join(obtener_valor(v) for v in med_h.valores.all())
                    row_vals.append(Paragraph(vals_str, estilo_celda))
                else:
                    row_vals.append("")
            
            # Rellenar vacíos
            row_vals += [""] * (11 - len(row_vals))
            
            t_row = Table([row_vals], colWidths=col_widths)
            t_row.setStyle(TableStyle([
                ('GRID', (0, 0), (-1, -1), 0.3, colors.gray),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            
            w_r, h_r = t_row.wrap(ancho_util, 2*cm)
            if y - h_r < 1.5*cm:
                c.showPage()
                y = A4[1] - 2*cm
            
            t_row.drawOn(c, 1*cm, y - h_r)
            y -= h_r

    return y


def generar_pdf_formulario_clinico(formulario, response=None):
    """
    Genera un PDF del formulario clínico con toda su información.
    Estructura unificada y robusta.
    """
    from datetime import datetime
    from django.shortcuts import get_object_or_404
    from rest_framework.decorators import api_view, permission_classes
    from rest_framework.permissions import AllowAny
    from .models import Formulario, Huella

    if response is None:
        response = HttpResponse(content_type='application/pdf')
    
    nombre_archivo = f"formulario_{formulario.id}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    
    c = canvas.Canvas(response, pagesize=A4)
    ancho, alto = A4
    margen_x = 2*cm
    y = alto - 2*cm
    
    # 1. Encabezado
    y = encabezado(c, formulario, ancho, y)
    y -= 1.2*cm  # Ajuste para que encaje mejor con datos_paciente
    
    # 2. Datos del Paciente
    y = datos_paciente(c, formulario, margen_x, y)
    y -= 1*cm
    
    # 3. Grid de Mediciones (12 columnas / Horas)
    y = seccion_grid_mediciones(c, formulario, margen_x, y, ancho)
    y -= 1*cm
    
    # 4. Firma del Responsable (Basado en el formulario o en el paciente como respaldo)
    p = formulario.paciente
    
    # Intentar buscar firma asociada directamente a este formulario primero
    reg_firma = Huella.objects.filter(formulario_id=str(formulario.id)).exclude(imagen_firma__exact='').exclude(imagen_firma__isnull=True).order_by('-fecha').first()
    
    # Si no hay firma por formulario, buscar la última firma del paciente (fallback)
    if not reg_firma:
        ident = str(p.num_identificacion).strip()
        query_biometria = Q(paciente_id=ident) | Q(paciente_id=str(p.id))
        if ident.isdigit():
            query_biometria |= Q(paciente_id=str(int(ident)))
        reg_firma = Huella.objects.filter(query_biometria).exclude(imagen_firma__exact='').exclude(imagen_firma__isnull=True).order_by('-fecha').first()
    
    # La huella no se consulta ya que ha sido comentada en la sección_biometria
    reg_huella = None 
    
    # Forzar salto de página si queda poco espacio para la biometría (necesita ~6cm)
    if y < 6*cm:
        c.showPage()
        y = alto - 1*cm
        # Redibujar encabezado simple en nueva página si se desea
        y = encabezado(c, formulario, ancho, y)
        y -= 0.5*cm

    y = seccion_biometria(c, reg_huella, reg_firma, margen_x, y, ancho, responsable_nombre=formulario.responsable)
    
    # 5. Footer (en todas las páginas que se generen después o al final)
    # Nota: ReportLab dibuja en la página actual. Si queremos footer en todas, hay que usar canvas.Canvas.setPageCallBack o similar.
    # Por ahora, solo al final.
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    fecha_gen = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    txt_footer = f"ID Formulario: {formulario.id} - Generado: {fecha_gen}"
    c.drawCentredString(ancho/2, 1.5*cm, txt_footer)
    
    c.showPage()
    c.save()
    
    return response




