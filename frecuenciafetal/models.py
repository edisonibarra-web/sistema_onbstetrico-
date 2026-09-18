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
    # 2026-09-18: de vuelta a 2 opciones (Normal/Alerta) con texto corto --
    # "Alerta" activa el semáforo rojo de la tarjeta (ver .semaforo-select
    # con data-val="ALERTA" en el CSS de formulario.html).
    GLOBO_SEGURIDAD_CHOICES = [
        ('NORMAL', 'Normal: útero firme y contraído'),
        ('ALERTA', 'Alerta: útero blando, relajado, atonía'),
    ]
    SUTURA_HERIDAS_CHOICES = [
        ('NORMAL', 'Normal: bordes afrontados, dolor tolerable, sin cambios de coloración'),
        ('HEMATOMA', 'Alerta: hematoma (masa violácea, tensa, dolor intenso)'),
        ('INFECCION', 'Alerta: (eritema, calor local, edema, secreción purulenta)'),
    ]
    DESGARRO_CHOICES = [
        ('GRADO_I', 'Grado I'),
        ('GRADO_II', 'Grado II'),
        ('GRADO_III', 'Grado III'),
        ('GRADO_IV', 'Grado IV'),
    ]
    # Subclasificación obligatoria solo cuando desgarro == GRADO_III.
    DESGARRO_SUBGRADO_CHOICES = [
        ('A', 'A'),
        ('B', 'B'),
        ('C', 'C'),
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
    hora_parto = models.TimeField(blank=True, null=True, verbose_name="Hora de Parto")
    tipo_parto = models.CharField(max_length=20, choices=PARTO_CHOICES, blank=True, null=True)
    episiotomia = models.BooleanField(default=False, verbose_name="Episiotomía")
    tipo_alumbramiento = models.CharField(
        max_length=20, choices=ALUMBRAMIENTO_CHOICES, blank=True, null=True
    )
    desgarro = models.CharField(
        max_length=20, choices=DESGARRO_CHOICES, blank=True, null=True,
        verbose_name="Desgarro"
    )
    desgarro_subgrado = models.CharField(
        max_length=5, choices=DESGARRO_SUBGRADO_CHOICES, blank=True, null=True,
        verbose_name="Subclasificación del desgarro Grado III (A/B/C)"
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

    # 2026-09-14: se eliminó la captura de firma/huella biométrica (imagen
    # dibujada, firma del profesional en base64) a pedido explícito, antes de
    # salir a producción. `nombre_firma_paciente` se conserva -- es el nombre
    # en texto de "RESPONSABLE DEL REGISTRO" (dato clínico normal, no
    # biometría), y sigue siendo lo que se imprime en el PDF.
    nombre_firma_paciente = models.CharField(max_length=200, blank=True, null=True, verbose_name="Nombre del Responsable del Registro")

    # Datos del profesional responsable (DGH) -- solo identificación en texto,
    # sin la firma capturada (ver nota arriba).
    profesional_nombre = models.CharField(max_length=200, blank=True, null=True)
    profesional_identificacion = models.CharField(max_length=50, blank=True, null=True)
    profesional_tarjeta_pro = models.CharField(max_length=50, blank=True, null=True)

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


ESTADO_SANGRADO_CHOICES = [
    ('NORMAL', 'NORMAL'),
    ('VIGILAR', 'VIGILAR'),
    ('ALERTA', 'ALERTA'),
]


def estado_sangrado(cc, tipo_parto):
    """Semáforo de alerta por sangrado cuantificado, según el total
    acumulado (c.c.) y el tipo de parto. Fuente única de verdad para el PDF
    (`pdf_generator.generar_pdf_registro`) y para el `estado` guardado por
    cada `ControlSangrado` (ver `recalcular_estados_sangrado` en views.py).
    """
    if cc is None:
        return None
    umbral = 1000 if tipo_parto == 'CESAREA' else 500
    if cc >= umbral:
        return 'ALERTA'
    if cc < 250:
        return 'NORMAL'
    return 'VIGILAR'


def recalcular_estados_sangrado(registro):
    """Recalcula y persiste el `estado` (semáforo) de cada `ControlSangrado`
    de este registro, en orden de `minuto_control`, según el acumulado hasta
    ese punto inclusive. Se llama tras crear, editar o borrar cualquier
    control de sangrado del registro -- así una corrección a un control
    temprano también actualiza el estado guardado de los controles
    posteriores (queda trazabilidad de en qué control se cruzó un umbral).
    """
    acumulado = 0
    for control in registro.controles_sangrado.order_by('minuto_control'):
        acumulado += control.cc
        nuevo_estado = estado_sangrado(acumulado, registro.tipo_parto)
        if control.estado != nuevo_estado:
            control.estado = nuevo_estado
            control.save(update_fields=['estado'])


class ControlSangrado(models.Model):
    """
    Control periódico de cuantificación gravimétrica del sangrado postparto
    (cada 15 min las primeras 2h, cada 30 min la hora siguiente y cada hora
    hasta completar 6h). Persistido individualmente para poder consultarlo y
    corregirlo después de guardado, en vez de solo conservar la suma total.
    """
    registro = models.ForeignKey(
        RegistroParto,
        on_delete=models.CASCADE,
        related_name='controles_sangrado'
    )
    minuto_control = models.PositiveSmallIntegerField(
        verbose_name="Minuto del control (cronograma 15/30/60)"
    )
    hora = models.TimeField(verbose_name="Hora del control")
    cc = models.PositiveIntegerField(verbose_name="Sangrado cuantificado en este control (c.c.)")
    # Semáforo (Normal/Vigilar/Alerta) que tenía el acumulado justo en este
    # control -- se calcula en el backend (ver `estado_sangrado` arriba y
    # `recalcular_estados_sangrado` en views.py), nunca lo manda el cliente,
    # para que quede trazabilidad de en qué control exacto se cruzó un umbral.
    estado = models.CharField(
        max_length=20, choices=ESTADO_SANGRADO_CHOICES, blank=True, null=True,
        verbose_name="Estado del semáforo en este control"
    )

    class Meta:
        verbose_name = "Control de Sangrado"
        verbose_name_plural = "Controles de Sangrado"
        ordering = ['minuto_control']
        unique_together = ('registro', 'minuto_control')

    def __str__(self):
        return f"Sangrado {self.cc}cc - min {self.minuto_control}"


class ControlGlobo(models.Model):
    """Control periódico del globo de seguridad (mismo cronograma que
    ControlSangrado: 15/30/60 min hasta completar 6h)."""
    registro = models.ForeignKey(
        RegistroParto,
        on_delete=models.CASCADE,
        related_name='controles_globo'
    )
    minuto_control = models.PositiveSmallIntegerField(
        verbose_name="Minuto del control (cronograma 15/30/60)"
    )
    hora = models.TimeField(verbose_name="Hora del control")
    estado = models.CharField(
        max_length=20, choices=RegistroParto.GLOBO_SEGURIDAD_CHOICES,
        verbose_name="Estado del globo de seguridad en este control"
    )

    class Meta:
        verbose_name = "Control de Globo de Seguridad"
        verbose_name_plural = "Controles de Globo de Seguridad"
        ordering = ['minuto_control']
        unique_together = ('registro', 'minuto_control')

    def __str__(self):
        return f"Globo {self.estado} - min {self.minuto_control}"


class ControlSutura(models.Model):
    """Control periódico de sutura y heridas (mismo cronograma que
    ControlSangrado: 15/30/60 min hasta completar 6h)."""
    registro = models.ForeignKey(
        RegistroParto,
        on_delete=models.CASCADE,
        related_name='controles_sutura'
    )
    minuto_control = models.PositiveSmallIntegerField(
        verbose_name="Minuto del control (cronograma 15/30/60)"
    )
    hora = models.TimeField(verbose_name="Hora del control")
    estado = models.CharField(
        max_length=20, choices=RegistroParto.SUTURA_HERIDAS_CHOICES,
        verbose_name="Estado de sutura y heridas en este control"
    )

    class Meta:
        verbose_name = "Control de Sutura y Heridas"
        verbose_name_plural = "Controles de Sutura y Heridas"
        ordering = ['minuto_control']
        unique_together = ('registro', 'minuto_control')

    def __str__(self):
        return f"Sutura {self.estado} - min {self.minuto_control}"


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

    # 2026-09-14: se eliminó la captura de huella plantar del recién nacido
    # (foto/base64) a pedido explícito, antes de salir a producción.

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

# 2026-09-14: se eliminaron HuellaBebe, FirmaPaciente y Huella (modelos de
# captura de huella/firma biométrica) a pedido explícito, antes de salir a
# producción.


class IntentoLoginFallido(models.Model):
    """
    2026-09-09 — HALLAZGO DE SEGURIDAD "fuerza bruta sin límite": login_view
    (ver views.py) no tenía ningún límite de intentos, lo que permitía probar
    contraseñas de forma automatizada contra un usuario conocido, además de
    generar carga extra sobre la base de datos de Dinámica en cada intento.

    Este modelo guarda cada intento de login FALLIDO (no exitoso) por IP, para
    poder frenar con una demora temporal a quien acumule demasiados fallos en
    poco tiempo (ver _demasiados_intentos/_registrar_intento_fallido en
    views.py). Se eligió bloquear por IP y no por cuenta/usuario a propósito:
    bloquear por cuenta abriría una puerta para que alguien bloquee a una
    enfermera real a propósito solo fallando su usuario repetidas veces --
    algo especialmente peligroso en un sistema clínico donde esa cuenta puede
    necesitarse de urgencia. Bloquear por IP sigue frenando un ataque
    automatizado sin ese riesgo.

    Se guarda en la base de datos (no en el cache en memoria del proceso)
    para que el límite funcione igual sin importar cuántos procesos/workers
    esté corriendo el servidor, y para que sobreviva un reinicio del
    contenedor.
    """
    ip = models.GenericIPAddressField()
    username = models.CharField(max_length=150, blank=True, default="")
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Intento de login fallido"
        verbose_name_plural = "Intentos de login fallidos"
        indexes = [models.Index(fields=["ip", "creado"])]

    def __str__(self):
        return f"{self.ip} -> '{self.username}' ({self.creado:%Y-%m-%d %H:%M:%S})"
