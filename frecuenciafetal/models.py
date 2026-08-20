from django.db import models
import uuid
from obstetriciaunificador.models import AtencionParto

class RegistroParto(models.Model):
    """Modelo principal del formato FRSPA-007"""
    atencion = models.ForeignKey(
        AtencionParto,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registros_fetal",
    )

    GENERO_CHOICES = [('M', 'Masculino'), ('F', 'Femenino'), ('I', 'Indeterminado')]
    PARTO_CHOICES = [
        ('VAGINAL', 'Vaginal'),
        ('INSTRUMENTADO', 'Instrumentado'),
        ('CESAREA', 'Cesárea'),
    ]
    ALUMBRAMIENTO_CHOICES = [
        ('ESPONTANEO', 'Espontáneo'),
        ('DIRIGIDO', 'Dirigido'),
        ('MANUAL', 'Manual'),
    ]
    GLOBO_SEGURIDAD_CHOICES = [
        ('NORMAL', 'Normal: útero firme y contraído, altura ±1cm del ombligo'),
        ('ALERTA', 'Alerta: útero blando, relajado o desviado (atonía), fondo uterino por encima del ombligo'),
    ]
    SUTURA_HERIDAS_CHOICES = [
        ('NORMAL', 'Normal: bordes afrontados, sin secreción, dolor tolerable, sin cambios de coloración'),
        ('HEMATOMA', 'Alerta: hematoma (masa violácea, tensa, dolor intenso, rectal, vaginal, insoportable)'),
        ('INFECCION', 'Alerta: infección (eritema, calor local, edema, secreción purulenta)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Datos de la paciente
    nombre_paciente = models.CharField(max_length=200, verbose_name="Nombre de la Paciente")
    identificacion = models.CharField(max_length=50, verbose_name="Identificación")
    edad_gestacional = models.SmallIntegerField(
        verbose_name="Edad Gestacional (semanas)"
    )
    gestas = models.SmallIntegerField(verbose_name="Gestas", default=1)
    nombre_acompanante = models.CharField(
        max_length=200, blank=True, null=True,
        verbose_name="Nombre del Acompañante en el Parto"
    )

    # Datos del parto
    tipo_parto = models.CharField(max_length=20, choices=PARTO_CHOICES, blank=True, null=True)
    episiotomia = models.BooleanField(default=False, verbose_name="Episiotomía")
    tipo_alumbramiento = models.CharField(
        max_length=20, choices=ALUMBRAMIENTO_CHOICES, blank=True, null=True
    )
    parto_atendido_por = models.CharField(max_length=200, blank=True, null=True)

    # Guía de parámetros y semáforo de alerta (posparto inmediato)
    globo_seguridad = models.CharField(
        max_length=20, choices=GLOBO_SEGURIDAD_CHOICES, blank=True, null=True,
        verbose_name="Globo de seguridad (evolución de la altura uterina)"
    )
    sangrado_cuantificado_cc = models.PositiveIntegerField(
        blank=True, null=True, verbose_name="Sangrado cuantificado (c.c.)"
    )
    sutura_heridas = models.CharField(
        max_length=20, choices=SUTURA_HERIDAS_CHOICES, blank=True, null=True,
        verbose_name="Sutura y heridas (descarte de hematomas e infección)"
    )

    # Firma digital del responsable
    firma_paciente = models.ImageField(
        upload_to='firmas/',
        blank=True, null=True,
        verbose_name="Firma del Responsable"
    )
    nombre_firma_paciente = models.CharField(max_length=200, blank=True, null=True, verbose_name="Nombre del Responsable que firma")
    fecha_hora_firma = models.DateTimeField(blank=True, null=True)

    # Datos del profesional responsable (DGH)
    profesional_nombre = models.CharField(max_length=200, blank=True, null=True)
    profesional_identificacion = models.CharField(max_length=50, blank=True, null=True)
    profesional_tarjeta_pro = models.CharField(max_length=50, blank=True, null=True)
    firma_profesional_base64 = models.TextField(blank=True, null=True, verbose_name="Firma del Profesional (Base64)")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Registro de Parto"
        verbose_name_plural = "Registros de Parto"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.nombre_paciente} - {self.identificacion}"


class ControlFetocardia(models.Model):
    """Control de fetocardia durante el expulsivo"""
    registro = models.ForeignKey(
        RegistroParto,
        on_delete=models.CASCADE,
        related_name='controles_fetocardia'
    )
    fecha = models.DateField(verbose_name="Fecha")
    hora = models.TimeField(verbose_name="Hora")
    fetocardia = models.SmallIntegerField(
        verbose_name="Fetocardia (lpm)"
    )
    responsable = models.CharField(max_length=200, blank=True, default='', verbose_name="Responsable")

    class Meta:
        verbose_name = "Control de Fetocardia"
        verbose_name_plural = "Controles de Fetocardia"
        ordering = ['fecha', 'hora']

    def __str__(self):
        return f"Fetocardia {self.fetocardia} lpm - {self.fecha} {self.hora}"


class ControlRecienNacido(models.Model):
    """Datos del recién nacido"""
    GENERO_CHOICES = [('M', 'Masculino'), ('F', 'Femenino'), ('I', 'Indeterminado')]

    registro = models.OneToOneField(
        RegistroParto,
        on_delete=models.CASCADE,
        related_name='control_recien_nacido'
    )
    hora_nacimiento = models.TimeField(verbose_name="Hora de Nacimiento")
    pasa_uci_neonatal = models.BooleanField(default=False, verbose_name="Pasa a UCI Neonatal")
    causa_uci = models.TextField(blank=True, null=True, verbose_name="Causa UCI")

    genero = models.CharField(max_length=1, choices=GENERO_CHOICES)
    peso = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name="Peso (g)"
    )
    talla = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name="Talla (cm)"
    )
    pc = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True,
        verbose_name="Perímetro Cefálico (cm)"
    )
    pt = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True,
        verbose_name="Perímetro Torácico (cm)"
    )
    p_abd = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True,
        verbose_name="Perímetro Abdominal (cm)"
    )

    # APGAR
    apgar_1min = models.SmallIntegerField(
        verbose_name="APGAR 1 minuto"
    )
    apgar_5min = models.SmallIntegerField(
        verbose_name="APGAR 5 minutos"
    )
    apgar_10min = models.SmallIntegerField(
        blank=True, null=True,
        verbose_name="APGAR 10 minutos"
    )
    tsh = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True,
        verbose_name="TSH"
    )
    hemoclasificacion = models.CharField(
        max_length=10, blank=True, null=True,
        verbose_name="Hemoclasificación"
    )
    vacuna_hb = models.BooleanField(default=False, verbose_name="Vacuna HB")
    vacuna_bcg = models.BooleanField(default=False, verbose_name="Vacuna BCG")

    # Líquido amniótico
    caracteristicas_liquido_amniotico = models.TextField(
        blank=True, null=True,
        verbose_name="Características del Líquido Amniótico"
    )

    # Lavado gástrico
    lavado_gastrico = models.BooleanField(default=False, verbose_name="Lavado Gástrico")
    lavado_elimina = models.BooleanField(default=False, verbose_name="Elimina")
    meconio = models.BooleanField(default=False, verbose_name="Meconio")

    # Oximetría
    oximetria_nacimiento_preductal = models.SmallIntegerField(
        blank=True, null=True,
        verbose_name="Oximetría al Nacimiento Preductal (%)"
    )
    oximetria_nacimiento_posductal = models.SmallIntegerField(
        blank=True, null=True,
        verbose_name="Oximetría al Nacimiento Posductal (%)"
    )
    oximetria_12h_preductal = models.SmallIntegerField(
        blank=True, null=True,
        verbose_name="Oximetría 12h Preductal (%)"
    )
    oximetria_12h_posductal = models.SmallIntegerField(
        blank=True, null=True,
        verbose_name="Oximetría 12h Posductal (%)"
    )

    # Tensión arterial neonato
    ta_msd = models.CharField(max_length=20, blank=True, null=True, verbose_name="TA MSD")
    ta_msi = models.CharField(max_length=20, blank=True, null=True, verbose_name="TA MSI")
    ta_mid = models.CharField(max_length=20, blank=True, null=True, verbose_name="TA MID")
    ta_miiz = models.CharField(max_length=20, blank=True, null=True, verbose_name="TA MIIZ")

    neonato_atendido_por = models.CharField(max_length=200, blank=True, null=True)
    valorado_pediatra = models.BooleanField(default=False, verbose_name="Valorado por Pediatra antes del Egreso")

    # Huella del pie del recién nacido (imagen)
    huella_pie = models.ImageField(
        upload_to='huellas_pie/%Y/%m/',
        blank=True, null=True,
        verbose_name="Huella del Pie del Recién Nacido"
    )
    # Alternativamente como base64 para captura directa desde dispositivo
    huella_pie_base64 = models.TextField(
        blank=True, null=True,
        verbose_name="Huella del Pie (Base64)"
    )

    class Meta:
        verbose_name = "Control del Recién Nacido"

    def __str__(self):
        return f"RN de {self.registro.nombre_paciente}"


class GlucometriaRecienNacido(models.Model):
    """Glucometrías del recién nacido"""
    control_rn = models.ForeignKey(
        ControlRecienNacido,
        on_delete=models.CASCADE,
        related_name='glucometrias'
    )
    hora = models.TimeField(verbose_name="Hora")
    resultado = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name="Resultado (mg/dL)"
    )

    class Meta:
        verbose_name = "Glucometría"
        verbose_name_plural = "Glucometrías"
        ordering = ['hora']


class ControlPostpartoInmediato(models.Model):
    """Control postparto inmediato - cada intervalo de tiempo"""
    INTERVALO_CHOICES = [
        (15, '15 min'), (30, '30 min'), (60, '60 min'),
    ]
    SANGRADO_CHOICES = [('NORMAL', 'Normal'), ('ABUNDANTE', 'Abundante')]
    INVOLUCION_CHOICES = [
        ('1CM_UMBILICAL', '1 cm umbilical'),
        ('2CM_UMBILICAL', '2 cm umbilical'),
    ]

    registro = models.ForeignKey(
        RegistroParto,
        on_delete=models.CASCADE,
        related_name='controles_postparto'
    )
    minuto_control = models.PositiveSmallIntegerField(verbose_name="Minuto del Control")
    fecha = models.DateField()
    hora = models.TimeField()

    # Control materno
    tension_arterial = models.CharField(max_length=20, blank=True, null=True)
    temperatura = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True,
        verbose_name="Temperatura (°C)"
    )
    pulso = models.SmallIntegerField(blank=True, null=True, verbose_name="Pulso (lpm)")
    respiracion = models.SmallIntegerField(
        blank=True, null=True, verbose_name="Respiración (rpm)"
    )
    saturacion = models.SmallIntegerField(
        blank=True, null=True, verbose_name="Saturación (%)"
    )

    # Sangrado vaginal
    sangrado_vaginal = models.CharField(
        max_length=20, choices=SANGRADO_CHOICES, blank=True, null=True
    )

    # Cuantificación gravimétrica vaginal (gramos)
    cuantificacion_gravimetrica_vaginal = models.IntegerField(
        blank=True, null=True, verbose_name="Cuantificación Gravimétrica Vaginal (g)"
    )

    # Involución uterina
    involucion_uterina = models.CharField(
        max_length=20, choices=INVOLUCION_CHOICES, blank=True, null=True
    )

    responsable = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        verbose_name = "Control Postparto Inmediato"
        verbose_name_plural = "Controles Postparto Inmediato"
        ordering = ['fecha', 'hora']

class HuellaBebe(models.Model):
    bebe_id = models.IntegerField()
    tipo = models.CharField(
        max_length=20,
        choices=[
            ("derecho", "Pie Derecho"),
            ("izquierdo", "Pie Izquierdo")
        ]
    )
    imagen = models.ImageField(upload_to="huellas_bebe/")
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Huella {self.tipo} - Bebe {self.bebe_id}"


class FirmaPaciente(models.Model):
    formulario = models.ForeignKey('RegistroParto', on_delete=models.CASCADE, null=True, blank=True, related_name='firmas')
    paciente_id = models.IntegerField()
    template_huella = models.TextField()
    imagen_huella = models.ImageField(upload_to="huellas/", null=True, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.CharField(max_length=100)

    def __str__(self):
        return f"Paciente {self.paciente_id} - Form {self.formulario} - {self.fecha}"

class Huella(models.Model):
    documento = models.CharField(max_length=50, verbose_name="Identificación del Paciente")
    template = models.TextField(verbose_name="Template de la Huella")
    imagen_huella = models.ImageField(upload_to="huellas_biometricas/", null=True, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.CharField(max_length=100, default="SYSTEM")

    class Meta:
        verbose_name = "Huella Biométrica"
        verbose_name_plural = "Huellas Biométricas"
        ordering = ['-fecha']

    def __str__(self):
        return f"Huella Paciente {self.documento} - {self.fecha}"
