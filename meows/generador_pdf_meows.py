"""
Generador de PDF MEOWS usando ReportLab - Formato idéntico al formato físico
"""
from django.http import HttpResponse
from django.conf import settings
from django.contrib.staticfiles import finders
from django.utils import timezone
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.pdfgen import canvas
from io import BytesIO
from datetime import datetime
import os


def obtener_rangos_por_score(parametro_codigo):
    """
    Obtiene los rangos de valores organizados por score para un parámetro.
    Retorna un diccionario: {score: [(min, max), ...]}
    """
    from meows.models import Parametro, RangoParametro
    
    try:
        parametro = Parametro.objects.get(codigo=parametro_codigo, activo=True)
        rangos = RangoParametro.objects.filter(
            parametro=parametro,
            activo=True
        ).order_by('orden', 'valor_min')
        
        rangos_por_score = {}
        for rango in rangos:
            if rango.score not in rangos_por_score:
                rangos_por_score[rango.score] = []
            rangos_por_score[rango.score].append((float(rango.valor_min), float(rango.valor_max)))
        
        return rangos_por_score
    except Parametro.DoesNotExist:
        return {}


def obtener_color_score(score):
    """Retorna el color correspondiente al score"""
    colores = {
        0: colors.white,      # Blanco - 0 puntos
        1: colors.HexColor('#00b050'),  # Verde - 1 punto
        2: colors.HexColor('#ffff00'),  # Amarillo - 2 puntos
        3: colors.HexColor('#ff0000'),  # Rojo - 3 puntos
    }
    return colores.get(score, colors.white)


def generar_pdf_meows(paciente, mediciones):
    """
    Genera un PDF MEOWS con formato idéntico al formato físico usando ReportLab.
    
    Args:
        paciente: Instancia del modelo Paciente
        mediciones: QuerySet de Medicion ordenadas por fecha_hora
    
    Returns:
        HttpResponse con el PDF generado
    """
    if hasattr(mediciones, "exists"):
        if not mediciones.exists():
            return HttpResponse("No hay mediciones para generar el PDF", status=400)
        mediciones_iter = list(mediciones)
    else:
        if not mediciones:
            return HttpResponse("No hay mediciones para generar el PDF", status=400)
        mediciones_iter = list(mediciones)

    # La grilla pone una columna por medición en una sola página apaisada — con
    # pacientes muy monitoreadas (ahora que Dinámica importa automáticamente,
    # algunas ya acumulan decenas o cientos de registros) el ancho por columna
    # se vuelve negativo y ReportLab revienta con
    # "flowable given negative availWidth" (Error 500). En vez de recortar
    # mediciones (el PDF debe reflejar TODA la Línea de Tiempo Clínica), se
    # reparte la grilla en varias tablas de MEDICIONES_POR_PAGINA columnas
    # cada una, una por página, más abajo.
    MEDICIONES_POR_PAGINA = 10
    total_mediciones_paciente = len(mediciones_iter)
    
    # DEFINIR VARIABLES DE ANCHO AL INICIO para evitar errores de variable no definida
    ancho_puntos = 1.1*cm  # Valor por defecto - definir primero
    
    # Crear buffer para el PDF
    buffer = BytesIO()
    
    # Crear documento en formato landscape (horizontal)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=0.8*cm,
        leftMargin=0.8*cm,
        topMargin=0.8*cm,
        bottomMargin=0.8*cm
    )
    
    # Estilos
    styles = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle(
        'Titulo',
        parent=styles['Heading1'],
        fontSize=10,
        textColor=colors.black,
        alignment=1,  # Centrado
        spaceAfter=6,
    )
    estilo_normal = ParagraphStyle(
        'Normal',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.black,
    )
    estilo_datos = ParagraphStyle(
        'Datos',
        parent=styles['Normal'],
        fontSize=7,
        textColor=colors.black,
        alignment=1,  # Centrado
        leading=9,  # Espaciado entre líneas
    )
    estilo_valor_celda = ParagraphStyle(
        'ValorCelda',
        parent=styles['Normal'],
        fontSize=6.5,  # Reducido para evitar desbordamiento
        textColor=colors.black,
        alignment=1,  # Centrado
        leading=8,  # Espaciado entre líneas reducido
        spaceAfter=0,
        spaceBefore=0,
    )
    # Nombre del parámetro: envuelto en Paragraph (no texto plano) para que los
    # nombres largos (ej. "Saturación de oxígeno por oximetría de pulso") se
    # ajusten en varias líneas dentro de la columna en vez de desbordarse
    # sobre las celdas de valores contiguas.
    estilo_parametro_nombre = ParagraphStyle(
        'ParametroNombre',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=6.5,
        textColor=colors.black,
        alignment=0,  # Izquierda
        leading=7.5,
        spaceAfter=0,
        spaceBefore=0,
    )
    
    # Contenedor de elementos
    story = []
    
    # ===== ENCABEZADO PROFESIONAL (idéntico al formato FRSPA-026 avalado por Calidad) =====
    # Logo izquierdo: Hospital Universitario Departamental de Nariño E.S.E.
    logo_izq_path = finders.find('img/logo_hospital.png') or ''

    # Logo derecho: Sello de Acreditación en Salud
    logo_der_path = finders.find('img/logo_acreditacion.png') or ''
    
    # Estilos para el encabezado - aumentados para aprovechar el espacio ampliado
    estilo_titulo_principal = ParagraphStyle(
        'TituloPrincipal',
        parent=styles['Normal'],
        fontSize=10.5,
        textColor=colors.black,
        alignment=1,  # Centrado
        spaceAfter=1,
        spaceBefore=0,
        fontName='Helvetica-Bold',
        leading=12,
    )

    estilo_subtitulo_meows = ParagraphStyle(
        'SubtituloMeows',
        parent=styles['Normal'],
        fontSize=9.5,
        textColor=colors.black,
        alignment=1,  # Centrado
        spaceAfter=0,
        spaceBefore=0,
        fontName='Helvetica-Bold',
        leading=11,
    )
    
    estilo_codigo_version = ParagraphStyle(
        'CodigoVersion',
        parent=styles['Normal'],
        fontSize=8,  # Más grande
        textColor=colors.black,
        alignment=1,  # Centrado
        spaceAfter=0,
        spaceBefore=0,
        fontName='Helvetica',
        leading=10,
    )
    
    estilo_fechas = ParagraphStyle(
        'Fechas',
        parent=styles['Normal'],
        fontSize=7.5,  # Más grande
        textColor=colors.black,
        alignment=2,  # Derecha
        spaceAfter=2,
        spaceBefore=0,
        fontName='Helvetica',
        leading=9,
    )
    
    estilo_meta_label = ParagraphStyle(
        'MetaLabelMeows',
        parent=styles['Normal'],
        fontSize=7,
        textColor=colors.black,
        alignment=0,
        fontName='Helvetica-Bold',
        leading=7.5,
        spaceAfter=0,
        spaceBefore=0,
    )

    estilo_meta_valor = ParagraphStyle(
        'MetaValorMeows',
        parent=styles['Normal'],
        fontSize=7,
        textColor=colors.black,
        alignment=0,
        fontName='Helvetica',
        leading=7.5,
        spaceAfter=0,
        spaceBefore=0,
    )

    estilo_hoja = ParagraphStyle(
        'HojaMeows',
        parent=styles['Normal'],
        fontSize=7,
        textColor=colors.black,
        alignment=1,
        fontName='Helvetica-Bold',
        leading=7.5,
        spaceAfter=0,
        spaceBefore=0,
    )

    # Construir encabezado con estructura organizada y sin superposición
    encabezado_data = []

    # Columna izquierda - Logo del hospital (el logo ya incluye el nombre institucional)
    columna_izq = []
    if logo_izq_path and os.path.exists(logo_izq_path):
        try:
            img_izq = Image(logo_izq_path, width=3.6*cm, height=1.44*cm)
            columna_izq.append(img_izq)
        except:
            pass

    # Columna centro - Título del formato
    columna_centro = []
    titulo_principal = Paragraph(
        "<b>SISTEMA ALERTA TEMPRANA OBSTÉTRICO</b>",
        estilo_titulo_principal
    )
    columna_centro.append(titulo_principal)

    subtitulo_meows = Paragraph(
        "<b>(MEOWS)</b>",
        estilo_subtitulo_meows
    )
    columna_centro.append(subtitulo_meows)

    # Columna de metadatos - Grilla idéntica al formato FRSPA-026 avalado por Calidad:
    # CÓDIGO / FECHA DE ELABORACIÓN, VERSIÓN / FECHA DE ACTUALIZACIÓN, HOJA 1 DE 2
    ancho_total_util = landscape(A4)[0] - 1.6*cm
    col_widths_encabezado = [
        ancho_total_util * 0.24,  # logo
        ancho_total_util * 0.34,  # título
        ancho_total_util * 0.30,  # metadatos
        ancho_total_util * 0.12,  # logo acreditación
    ]
    ancho_meta = col_widths_encabezado[2]  # ocupa el 100% de la celda para que las líneas lleguen al borde

    data_meta = [
        [Paragraph('<b>CÓDIGO:</b>', estilo_meta_label), Paragraph('<b>FECHA DE ELABORACIÓN:</b>', estilo_meta_label)],
        [Paragraph('FRSPA-026', estilo_meta_valor), Paragraph('27 DE DICIEMBRE DE 2023', estilo_meta_valor)],
        [Paragraph('<b>VERSIÓN:</b>', estilo_meta_label), Paragraph('<b>FECHA DE ACTUALIZACIÓN:</b>', estilo_meta_label)],
        [Paragraph('01', estilo_meta_valor), Paragraph('27 DE DICIEMBRE DE 2023', estilo_meta_valor)],
        [Paragraph('<b>HOJA 1 DE 2</b>', estilo_hoja), ''],
    ]
    tabla_meta = Table(data_meta, colWidths=[ancho_meta * 0.5, ancho_meta * 0.5])
    tabla_meta.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('SPAN', (0, 4), (1, 4)),
        ('ALIGN', (0, 4), (1, 4), 'CENTER'),
        # Delimitadores: línea vertical entre CÓDIGO/VERSIÓN y las fechas, y línea horizontal
        # entre el bloque CÓDIGO y el bloque VERSIÓN, igual que el formato avalado.
        # La tabla ocupa el ancho completo de la celda (sin padding del contenedor), así
        # las líneas quedan a ras de los bordes izquierdo y derecho, sin espacios sueltos.
        ('LINEAFTER', (0, 0), (0, 3), 0.6, colors.black),
        ('LINEBELOW', (0, 1), (1, 1), 0.6, colors.black),
        ('LINEABOVE', (0, 4), (1, 4), 0.6, colors.black),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
    ]))
    columna_meta = [tabla_meta]

    # Columna derecha - Logo de acreditación
    columna_derecha = []
    if logo_der_path and os.path.exists(logo_der_path):
        try:
            img_der = Image(logo_der_path, width=1.5*cm, height=1.5*cm)
            columna_derecha.append(img_der)
        except:
            pass

    # Crear la fila principal con las cuatro columnas organizadas
    fila_superior = [columna_izq, columna_centro, columna_meta, columna_derecha]
    encabezado_data.append(fila_superior)

    tabla_encabezado = Table(encabezado_data, colWidths=col_widths_encabezado)
    tabla_encabezado.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#1f2937')),
        ('LINEAFTER', (0, 0), (0, -1), 0.8, colors.HexColor('#1f2937')),
        ('LINEAFTER', (1, 0), (1, -1), 0.8, colors.HexColor('#1f2937')),
        ('LINEAFTER', (2, 0), (2, -1), 0.8, colors.HexColor('#1f2937')),
        ('BACKGROUND', (0, 0), (-1, -1), colors.white),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('ALIGN', (2, 0), (2, 0), 'CENTER'),
        ('ALIGN', (3, 0), (3, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
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

    story.append(tabla_encabezado)
    story.append(Spacer(1, 0.4*cm))
    
    # ===== DATOS DEL PACIENTE =====
    # Estilo para datos del paciente - Tamaños reducidos para que quepa todo
    estilo_label_datos = ParagraphStyle(
        'LabelDatos',
        parent=styles['Normal'],
        fontSize=6.5,  # Reducido de 7 a 6.5
        textColor=colors.black,
        alignment=0,  # Izquierda
        fontName='Helvetica-Bold',
        leading=8,  # Espaciado reducido
        spaceAfter=0,
        spaceBefore=0,
    )
    
    estilo_valor_datos = ParagraphStyle(
        'ValorDatos',
        parent=styles['Normal'],
        fontSize=6.5,  # Reducido de 7 a 6.5
        textColor=colors.black,
        alignment=0,  # Izquierda
        fontName='Helvetica',
        leading=8,  # Espaciado reducido
        spaceAfter=0,
        spaceBefore=0,
    )
    
    # Preparar datos con Paragraph para mejor control de texto largo
    nombre_completo = f"{paciente.nombres} {paciente.apellidos}".strip() or '-'
    edad_texto = f"{paciente.edad} años" if paciente.edad else '-'
    aseguradora_texto = paciente.aseguradora or '-'
    cama_texto = paciente.cama or '-'
    identificacion_texto = paciente.numero_documento
    fecha_ingreso_texto = paciente.fecha_ingreso.strftime('%d/%m/%Y') if paciente.fecha_ingreso else '-'
    
    datos_paciente = [
        [
            Paragraph('NOMBRE<br/>COMPLETO', estilo_label_datos),  # Dividido en 2 líneas
            Paragraph(nombre_completo, estilo_valor_datos),
            Paragraph('EDAD', estilo_label_datos),
            Paragraph(edad_texto, estilo_valor_datos),
            Paragraph('ASEGURADORA', estilo_label_datos),
            Paragraph(aseguradora_texto, estilo_valor_datos)
        ],
        [
            Paragraph('CAMA', estilo_label_datos),
            Paragraph(cama_texto, estilo_valor_datos),
            Paragraph('IDENTIF.<br/>CACIÓN', estilo_label_datos),  # Dividido en 2 líneas
            Paragraph(identificacion_texto, estilo_valor_datos),
            Paragraph('FECHA DE<br/>INGRESO', estilo_label_datos),  # Dividido en 2 líneas
            Paragraph(fecha_ingreso_texto, estilo_valor_datos)
        ],
    ]
    
    # Mantener el mismo ancho útil que el resto del documento para alinear márgenes
    ancho_total_datos = landscape(A4)[0] - 1.6*cm

    # Distribución por proporción (suma 1.0) para ocupar todo el ancho del bloque
    # [label, valor, label, valor, label, valor]
    proporciones = [0.12, 0.23, 0.10, 0.16, 0.14, 0.25]
    anchos_datos = [ancho_total_datos * p for p in proporciones]

    # Crear tabla de datos ocupando el ancho completo
    tabla_datos = Table(datos_paciente, colWidths=anchos_datos)
    
    tabla_datos.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f3f4f6')),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#f3f4f6')),
        ('BACKGROUND', (4, 0), (4, -1), colors.HexColor('#f3f4f6')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#1f2937')),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#374151')),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),  # Padding reducido
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),  # Padding reducido
        ('TOPPADDING', (0, 0), (-1, -1), 5),  # Padding reducido
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),  # Padding reducido
        ('FONTSIZE', (0, 0), (-1, -1), 6.5),  # Tamaño de fuente reducido
    ]))
    
    story.append(tabla_datos)
    story.append(Spacer(1, 0.3*cm))

    # ===== ORGANIZAR MEDICIONES =====
    mediciones_agrupadas = []
    for medicion in mediciones_iter:
        # fecha_hora se guarda en UTC (aware); sin localtime() aquí el PDF
        # imprime la hora UTC en vez de la hora de Bogotá (mismo bug ya
        # corregido antes en meows/views.py api_alertas_pendientes).
        fecha_hora_local = timezone.localtime(medicion.fecha_hora)
        fecha_str = fecha_hora_local.strftime("%d/%m/%y")
        hora_str = fecha_hora_local.strftime("%I:%M %p")
        
        valores_dict = {}
        for valor_obj in medicion.valores.all():
            codigo = valor_obj.parametro.codigo
            valores_dict[codigo] = {
                'valor': valor_obj.valor,
                'puntaje': valor_obj.puntaje if valor_obj.puntaje is not None else 0,
                'parametro': valor_obj.parametro
            }
        
        mediciones_agrupadas.append({
            'fecha': fecha_str,
            'hora': hora_str,
            'medicion': medicion,
            'valores': valores_dict
        })
    
    # ===== GRILLA DE PARÁMETROS =====
    from meows.models import Parametro
    parametros = Parametro.objects.filter(activo=True).order_by('orden')

    # La Línea de Tiempo Clínica no recorta mediciones, así que el PDF
    # tampoco debe hacerlo: en vez de forzar todas las columnas en una sola
    # tabla (lo que revienta con "negative availWidth" apenas hay más de
    # ~10 mediciones), se reparte la grilla en tantas tablas — una por
    # página apaisada — como hagan falta para imprimir TODAS las mediciones.
    chunks_mediciones = [
        mediciones_agrupadas[i:i + MEDICIONES_POR_PAGINA]
        for i in range(0, len(mediciones_agrupadas), MEDICIONES_POR_PAGINA)
    ]
    total_paginas_grilla = len(chunks_mediciones)

    estilo_paginacion_grilla = ParagraphStyle(
        'PaginacionGrilla',
        parent=styles['Normal'],
        fontSize=7.5,
        textColor=colors.HexColor('#1e3a8a'),
        fontName='Helvetica-Bold',
        alignment=1,  # Centrado
        spaceAfter=4,
        spaceBefore=0,
    )

    for pagina_idx, mediciones_pagina in enumerate(chunks_mediciones):
        if pagina_idx > 0:
            story.append(PageBreak())

        if total_paginas_grilla > 1:
            inicio = pagina_idx * MEDICIONES_POR_PAGINA + 1
            fin = inicio + len(mediciones_pagina) - 1
            story.append(Paragraph(
                f"Mediciones {inicio}–{fin} de {total_mediciones_paciente} "
                f"(página {pagina_idx + 1} de {total_paginas_grilla})",
                estilo_paginacion_grilla
            ))

        # ===== CALCULAR ANCHOS DE COLUMNAS DE ESTA PÁGINA =====
        ancho_total = landscape(A4)[0] - 1.6*cm  # Menos márgenes
        num_mediciones = max(len(mediciones_pagina), 1)

        # Valores iniciales
        ancho_parametro = 2.9*cm  # Reducido más
        ancho_unidad = 0.8*cm  # Más compacto
        ancho_puntos = 0.85*cm  # Más reducido para evitar que se salga
        ancho_medicion = 2*cm  # Valor por defecto

        # Ancho disponible para las columnas de mediciones de esta página
        ancho_disponible = ancho_total - ancho_parametro - ancho_unidad - ancho_puntos
        ancho_medicion = ancho_disponible / num_mediciones

        # Asegurar un ancho mínimo de 2cm para cada medición (necesario para fecha/hora/valores)
        # — con el reparto por páginas (máx. MEDICIONES_POR_PAGINA columnas)
        # esto ya no debería activarse nunca, pero se conserva como resguardo.
        if ancho_medicion < 2*cm:
            ancho_medicion = 2*cm
            ancho_total_necesario = ancho_parametro + ancho_unidad + ancho_puntos + (ancho_medicion * num_mediciones)
            if ancho_total_necesario > ancho_total:
                ancho_parametro = 2.8*cm
                ancho_unidad = 0.8*cm
                ancho_disponible = ancho_total - ancho_parametro - ancho_unidad - ancho_puntos
                ancho_medicion = ancho_disponible / num_mediciones

        # Estilo para encabezado de fecha/hora — texto BLANCO: esta celda es un
        # Paragraph, así que ignora el TEXTCOLOR blanco que ya está puesto a nivel
        # de tabla para toda la fila de encabezado (ver 'TEXTCOLOR', (0,0), (-1,0)
        # más abajo) — un Paragraph siempre usa el color de su propio ParagraphStyle,
        # por eso quedaba en negro sobre el fondo azul oscuro y no se leía.
        estilo_encabezado_fecha = ParagraphStyle(
            'EncabezadoFecha',
            parent=styles['Normal'],
            fontSize=5.5,  # Fuente pequeña para que quepa
            textColor=colors.white,
            alignment=1,  # Centrado
            leading=6.5,  # Espaciado compacto
            spaceAfter=0,
            spaceBefore=0,
        )

        # Encabezado de la grilla - FECHA y HORA en encabezados separados por cada medición
        encabezado_grilla = ['PARÁMETRO', 'UNIDAD']
        for item in mediciones_pagina:
            encabezado_grilla.append(Paragraph(
                f"<b>FECHA</b><br/>{item['fecha']}<br/><b>HORA</b><br/>{item['hora']}",
                estilo_encabezado_fecha
            ))
        encabezado_grilla.append('PUNTOS')

        # Datos de la grilla
        datos_grilla = [encabezado_grilla]

        # Agregar filas de parámetros
        for parametro in parametros:
            fila = []

            # PARÁMETRO
            fila.append(Paragraph(parametro.nombre, estilo_parametro_nombre))

            # UNIDAD
            fila.append(parametro.unidad)

            # VALORES por medición - Mostrar valor y score
            for item in mediciones_pagina:
                valores_hora = item['valores']
                if parametro.codigo in valores_hora:
                    valor_data = valores_hora[parametro.codigo]
                    valor = str(valor_data['valor'])
                    score = valor_data['puntaje']
                    # Formato: valor en primera línea, score entre paréntesis en segunda línea
                    celda_texto = f"{valor}<br/><b>({score})</b>"
                    fila.append(Paragraph(celda_texto, estilo_valor_celda))
                else:
                    fila.append('')

            # PUNTOS (columna de referencia) - Crear sub-tabla con colores
            ancho_sub_tabla_puntos = max(ancho_puntos - 0.2*cm, 0.6*cm)
            puntos_tabla = Table([
                ['3'],
                ['2'],
                ['1'],
                ['0']
            ], colWidths=[ancho_sub_tabla_puntos], rowHeights=[0.28*cm, 0.28*cm, 0.28*cm, 0.28*cm])

            puntos_tabla.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, 0), obtener_color_score(3)),  # Rojo para 3
                ('BACKGROUND', (0, 1), (0, 1), obtener_color_score(2)),  # Amarillo para 2
                ('BACKGROUND', (0, 2), (0, 2), obtener_color_score(1)),  # Verde para 1
                ('BACKGROUND', (0, 3), (0, 3), obtener_color_score(0)),  # Blanco para 0
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 0.15, colors.black),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))

            fila.append(puntos_tabla)
            datos_grilla.append(fila)

        # Fila TOTAL - Mostrar total con riesgo/score asociado
        fila_total = ['TOTAL', '']
        for item in mediciones_pagina:
            medicion = item['medicion']
            total = medicion.meows_total if medicion.meows_total else 0
            riesgo_score = 0
            if medicion.meows_riesgo == "VERDE":
                riesgo_score = 1
            elif medicion.meows_riesgo == "AMARILLO":
                riesgo_score = 2
            elif medicion.meows_riesgo == "ROJO":
                riesgo_score = 3
            total_texto = f"<b>{total}</b><br/><b>({riesgo_score})</b>"
            estilo_total = ParagraphStyle(
                'TotalCelda',
                parent=estilo_valor_celda,
                fontSize=6.5,
                leading=8,
            )
            fila_total.append(Paragraph(total_texto, estilo_total))

        ancho_sub_tabla_puntos_total = max(ancho_puntos - 0.2*cm, 0.6*cm)
        puntos_tabla_total = Table([
            ['3'],
            ['2'],
            ['1'],
            ['0']
        ], colWidths=[ancho_sub_tabla_puntos_total], rowHeights=[0.28*cm, 0.28*cm, 0.28*cm, 0.28*cm])

        puntos_tabla_total.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, 0), obtener_color_score(3)),
            ('BACKGROUND', (0, 1), (0, 1), obtener_color_score(2)),
            ('BACKGROUND', (0, 2), (0, 2), obtener_color_score(1)),
            ('BACKGROUND', (0, 3), (0, 3), obtener_color_score(0)),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.15, colors.black),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))

        fila_total.append(puntos_tabla_total)
        datos_grilla.append(fila_total)

        # Anchos de columnas de esta página
        anchos_columnas = [ancho_parametro, ancho_unidad]
        for _ in mediciones_pagina:
            anchos_columnas.append(ancho_medicion)
        anchos_columnas.append(ancho_puntos)

        # Calcular altura de filas - debe ser suficiente para la sub-tabla de puntos (4 filas)
        altura_fila = 1.2*cm
        alturas_filas = [0.8*cm]
        for _ in range(len(parametros)):
            alturas_filas.append(altura_fila)
        alturas_filas.append(0.7*cm)

        # Crear tabla de grilla de esta página
        tabla_grilla = Table(datos_grilla, colWidths=anchos_columnas, rowHeights=alturas_filas, repeatRows=1)

        estilo_grilla = [
            # Encabezado
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 6),
            ('FONTSIZE', (0, 1), (-1, -2), 6.5),
            ('FONTSIZE', (0, -1), (-1, -1), 6.5),
            ('LEFTPADDING', (2, 1), (-2, -2), 2),
            ('RIGHTPADDING', (2, 1), (-2, -2), 2),
            ('TOPPADDING', (2, 1), (-2, -2), 2),
            ('BOTTOMPADDING', (2, 1), (-2, -2), 2),
            ('LEFTPADDING', (-1, 0), (-1, -1), 1),
            ('RIGHTPADDING', (-1, 0), (-1, -1), 1),
            ('TOPPADDING', (-1, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (-1, 0), (-1, -1), 1),
            ('ALIGN', (-1, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (-1, 0), (-1, -1), 'MIDDLE'),
            ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#1f2937')),
            ('INNERGRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#6b7280')),
            ('ALIGN', (0, 1), (0, -2), 'LEFT'),
            ('FONTNAME', (0, 1), (0, -2), 'Helvetica-Bold'),
            ('BACKGROUND', (0, 1), (0, -2), colors.HexColor('#f9fafb')),
            ('BACKGROUND', (1, 1), (1, -2), colors.HexColor('#f3f4f6')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#dbeafe')),
        ]

        # Aplicar colores según scores en las celdas de valores
        fila_idx = 1
        for parametro in parametros:
            col_idx = 2
            for item in mediciones_pagina:
                valores_hora = item['valores']
                if parametro.codigo in valores_hora:
                    valor_data = valores_hora[parametro.codigo]
                    score = valor_data['puntaje']
                    color = obtener_color_score(score)
                    estilo_grilla.append(('BACKGROUND', (col_idx, fila_idx), (col_idx, fila_idx), color))
                col_idx += 1
            fila_idx += 1

        # Colorear totales
        fila_total_idx = len(datos_grilla) - 1
        col_idx = 2
        for item in mediciones_pagina:
            medicion = item['medicion']
            riesgo_color = 0
            if medicion.meows_riesgo == "VERDE":
                riesgo_color = 1
            elif medicion.meows_riesgo == "AMARILLO":
                riesgo_color = 2
            elif medicion.meows_riesgo == "ROJO":
                riesgo_color = 3
            color = obtener_color_score(riesgo_color)
            estilo_grilla.append(('BACKGROUND', (col_idx, fila_total_idx), (col_idx, fila_total_idx), color))
            col_idx += 1

        tabla_grilla.setStyle(TableStyle(estilo_grilla))

        story.append(tabla_grilla)
        story.append(Spacer(1, 0.5*cm))

    # Ancho total disponible para la firma del responsable
    ancho_total_firma = landscape(A4)[0] - 1.6*cm

    # ===== FIRMA DEL RESPONSABLE (ENFERMERO) CON BIOMETRÍA =====
    # Intentar obtener la firma biométrica del responsable (el que diligencia)
    img_firma_bio = None
    try:
        # Búsqueda robusta de firma: documento, documento sin ceros, id interno y formulario_id
        from meows.models import FirmaPaciente
        from django.db.models import Q

        ids_busqueda = set()
        doc_paciente = str(getattr(paciente, "numero_documento", "") or "").strip()
        if doc_paciente:
            ids_busqueda.add(doc_paciente)
            doc_limpio = doc_paciente.lstrip('0') or '0'
            ids_busqueda.add(doc_limpio)
            if doc_paciente.isdigit():
                ids_busqueda.add(str(int(doc_paciente)))
        ids_busqueda.add(str(paciente.id))

        formularios_ids = {
            str(getattr(m, "formulario_id", "")).strip()
            for m in mediciones_iter
            if getattr(m, "formulario_id", None)
        }
        formularios_ids = {fid for fid in formularios_ids if fid}

        query_firma = Q(paciente_id__in=list(ids_busqueda))
        if formularios_ids:
            query_firma |= Q(formulario_id__in=list(formularios_ids))

        firma_obj = (
            FirmaPaciente.objects
            .filter(query_firma)
            .exclude(imagen_firma=None)
            .exclude(imagen_firma='')
            .order_by('-fecha')
            .first()
        )
        
        if firma_obj and firma_obj.imagen_firma:
            try:
                # 1. Intentar por path físico si existe
                if os.path.exists(firma_obj.imagen_firma.path):
                    img_firma_bio = Image(firma_obj.imagen_firma.path, width=4.5*cm, height=1.8*cm, kind='proportional')
                else:
                    # 2. Fallback memoria/storage (más lento)
                    firma_obj.imagen_firma.open('rb')
                    img_bytes_f = BytesIO(firma_obj.imagen_firma.read())
                    firma_obj.imagen_firma.close()
                    img_firma_bio = Image(img_bytes_f, width=4.5*cm, height=1.8*cm, kind='proportional')
            except Exception as e_img:
                # Si ambos fallan, no agregar la firma pero no romper el PDF
                print(f"Error al cargar firma biométrica: {e_img}")
                img_firma_bio = None
    except Exception as e:
        print(f"Error general buscando firma: {e}")
        pass

    fecha_actual = datetime.now().strftime("%d/%m/%Y")
    hora_actual = datetime.now().strftime("%I:%M %p")
    responsable = paciente.responsable if paciente.responsable else 'No especificado'
    
    estilo_firma = ParagraphStyle(
        'Firma',
        parent=styles['Normal'],
        fontSize=8.5,
        textColor=colors.black,
        alignment=0,
        leading=10,
        fontName='Helvetica-Bold',
    )
    
    firma_texto = (
        f'<b>Responsable del Registro MEOWS:</b> {responsable}  <br/>'
        f'<b>Fecha:</b> {fecha_actual}  '
        f'<b>Hora:</b> {hora_actual}'
    )
    
    # Celda con firma (si existe) + texto
    contenido_firma = []
    if img_firma_bio:
        contenido_firma.append(img_firma_bio)
    contenido_firma.append(Paragraph(f"<b>VALIDACIÓN DE REGISTRO</b><br/>{firma_texto}", estilo_firma))

    tabla_firma = Table([[contenido_firma]], colWidths=[ancho_total_firma])
    tabla_firma.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e5e7eb')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.black),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    
    story.append(tabla_firma)
    
    # Construir PDF
    doc.build(story)
    
    # Preparar respuesta
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    nombre_archivo = f"MEOWS_{paciente.numero_documento}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    
    return response
