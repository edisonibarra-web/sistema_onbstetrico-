from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError


class EstadoFormulario(models.TextChoices):
    G = "g", "G"
    P = "p", "P"
    C = "c", "C"
    A = "a", "A"
    V = "v", "V"
    M = "m", "M"


class TipoSangre(models.TextChoices):
    O_POS = "O+", "O+"
    O_NEG = "O-", "O-"
    A_POS = "A+", "A+"
    A_NEG = "A-", "A-"
    B_POS = "B+", "B+"
    B_NEG = "B-", "B-"
    AB_POS = "AB+", "AB+"
    AB_NEG = "AB-", "AB-"


class TipoValor(models.TextChoices):
    NUMBER = "number", "number"
    TEXT = "text", "text"
    BOOLEAN = "boolean", "boolean"
    JSON = "json", "json"


class Aseguradora(models.Model):
    nombre = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["nombre"]
        db_table = "aseguradora"

    def __str__(self):
        return self.nombre


class Paciente(models.Model):
    num_historia_clinica = models.CharField(max_length=255, unique=True)
    num_identificacion = models.CharField(max_length=255, unique=True)
    nombres = models.CharField(max_length=255)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    tipo_sangre = models.CharField(
        max_length=3, choices=TipoSangre.choices, null=True, blank=True
    )

    class Meta:
        ordering = ["nombres"]
        db_table = "paciente"

    def __str__(self):
        return f"{self.nombres} ({self.num_identificacion})"


class Formulario(models.Model):
    atencion = models.ForeignKey(
        "obstetricia.AtencionParto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="formularios_trabajoparto",
    )
    codigo = models.CharField(max_length=255)
    version = models.CharField(max_length=50)
    fecha_elabora = models.DateField()
    fecha_actualizacion = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    num_hoja = models.PositiveIntegerField()

    aseguradora = models.ForeignKey(
        Aseguradora, null=True, blank=True, on_delete=models.SET_NULL, related_name="formularios"
    )
    paciente = models.ForeignKey(
        Paciente, on_delete=models.CASCADE, related_name="formularios"
    )

    diagnostico = models.TextField(null=True, blank=True)
    edad_snapshot = models.PositiveIntegerField(null=True, blank=True)
    edad_gestion = models.PositiveIntegerField(null=True, blank=True)
    estado = models.CharField(max_length=1, choices=EstadoFormulario.choices)
    n_controles_prenatales = models.PositiveIntegerField(null=True, blank=True)
    responsable = models.CharField(max_length=255)

    # Antecedentes obstétricos (G/P/C/A). Ya se consultaban desde DGEMPRES03
    # (HCMWINGIN) en _obtener_obstetricos_dgempres99 pero no se persistían.
    gestas = models.PositiveIntegerField(null=True, blank=True, verbose_name="Gestas (G)")
    partos = models.PositiveIntegerField(null=True, blank=True, verbose_name="Partos (P)")
    cesareas = models.PositiveIntegerField(null=True, blank=True, verbose_name="Cesáreas (C)")
    abortos = models.PositiveIntegerField(null=True, blank=True, verbose_name="Abortos (A)")

    class Meta:
        ordering = ["-fecha_actualizacion"]
        db_table = "formulario"
        indexes = [
            models.Index(fields=["paciente"], name="idx_formulario_paciente"),
            models.Index(fields=["aseguradora"], name="idx_formulario_aseguradora"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(num_hoja__gt=0),
                name="num_hoja_positivo"
            ),
            models.CheckConstraint(
                check=models.Q(edad_snapshot__gte=0) | models.Q(edad_snapshot__isnull=True),
                name="edad_snapshot_no_negativa"
            ),
            models.CheckConstraint(
                check=models.Q(edad_gestion__gte=0) | models.Q(edad_gestion__isnull=True),
                name="edad_gestion_no_negativa"
            ),
            models.CheckConstraint(
                check=models.Q(n_controles_prenatales__gte=0) | models.Q(n_controles_prenatales__isnull=True),
                name="n_controles_no_negativo"
            ),
        ]

    def __str__(self):
        return f"{self.codigo} v{self.version} hoja {self.num_hoja}"


class Item(models.Model):
    codigo = models.CharField(max_length=255, unique=True)
    nombre = models.CharField(max_length=255)

    class Meta:
        ordering = ["codigo"]
        db_table = "item"

    def __str__(self):
        return self.nombre


class Parametro(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="parametros")
    codigo = models.CharField(max_length=255)
    nombre = models.CharField(max_length=255)
    unidad = models.CharField(max_length=50, null=True, blank=True)
    orden = models.PositiveIntegerField(default=1)
    activo = models.BooleanField(default=True)

    class Meta:
        unique_together = ("item", "codigo")
        ordering = ["item_id", "orden", "id"]
        db_table = "parametro"
        indexes = [
            models.Index(fields=["item"], name="idx_parametro_item"),
        ]

    def __str__(self):
        return f"{self.item.codigo} - {self.codigo}"


class FormularioItemParametro(models.Model):
    formulario = models.ForeignKey(
        Formulario, on_delete=models.CASCADE, related_name="parametros_formulario"
    )
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="formularios_items")
    parametro = models.ForeignKey(
        Parametro, on_delete=models.CASCADE, related_name="formularios_parametro"
    )
    requerido = models.BooleanField(default=False)

    class Meta:
        unique_together = ("formulario", "parametro")
        db_table = "formulario_item_parametro"

    def clean(self):
        # Validación: el parámetro debe pertenecer al item
        if self.parametro and self.item and self.parametro.item_id != self.item_id:
            raise ValidationError(
                "El parámetro debe pertenecer al item especificado."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.formulario_id} - {self.parametro_id}"


class CampoParametro(models.Model):
    parametro = models.ForeignKey(
        Parametro, on_delete=models.CASCADE, related_name="campos"
    )
    codigo = models.CharField(max_length=255)
    nombre = models.CharField(max_length=255)
    tipo_valor = models.CharField(max_length=10, choices=TipoValor.choices)
    unidad = models.CharField(max_length=50, null=True, blank=True)
    orden = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ("parametro", "codigo")
        ordering = ["parametro_id", "orden", "id"]
        db_table = "campo_parametro"

    def __str__(self):
        return f"{self.parametro_id} - {self.codigo}"


class Medicion(models.Model):
    formulario = models.ForeignKey(
        Formulario, on_delete=models.CASCADE, related_name="mediciones"
    )
    parametro = models.ForeignKey(
        Parametro, on_delete=models.CASCADE, related_name="mediciones"
    )
    tomada_en = models.DateTimeField()
    observacion = models.TextField(null=True, blank=True)

    class Meta:
        unique_together = ("formulario", "parametro", "tomada_en")
        ordering = ["-tomada_en"]
        db_table = "medicion"
        indexes = [
            models.Index(fields=["formulario", "parametro", "tomada_en"], name="idx_medicion_form_param_time"),
        ]

    def __str__(self):
        return f"{self.formulario_id}-{self.parametro_id} @ {self.tomada_en}"


class MedicionValor(models.Model):
    medicion = models.ForeignKey(
        Medicion, on_delete=models.CASCADE, related_name="valores"
    )
    campo = models.ForeignKey(
        CampoParametro, on_delete=models.CASCADE, related_name="valores"
    )
    valor_number = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    valor_text = models.TextField(null=True, blank=True)
    valor_boolean = models.BooleanField(null=True, blank=True)
    valor_json = models.JSONField(null=True, blank=True)

    class Meta:
        unique_together = ("medicion", "campo")
        db_table = "medicion_valor"
        indexes = [
            models.Index(fields=["medicion"], name="idx_valor_medicion"),
            models.Index(fields=["campo"], name="idx_valor_campo"),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(valor_number__isnull=False) &
                    models.Q(valor_text__isnull=True) &
                    models.Q(valor_boolean__isnull=True) &
                    models.Q(valor_json__isnull=True)
                ) | (
                    models.Q(valor_number__isnull=True) &
                    models.Q(valor_text__isnull=False) &
                    models.Q(valor_boolean__isnull=True) &
                    models.Q(valor_json__isnull=True)
                ) | (
                    models.Q(valor_number__isnull=True) &
                    models.Q(valor_text__isnull=True) &
                    models.Q(valor_boolean__isnull=False) &
                    models.Q(valor_json__isnull=True)
                ) | (
                    models.Q(valor_number__isnull=True) &
                    models.Q(valor_text__isnull=True) &
                    models.Q(valor_boolean__isnull=True) &
                    models.Q(valor_json__isnull=False)
                ),
                name="valor_unico_tipo",
            )   
        ]



class Huella(models.Model):
    paciente_id = models.CharField(max_length=50)
    formulario_id = models.CharField(max_length=50, null=True, blank=True)
    template = models.TextField(null=True, blank=True)  # Datos biométricos
    imagen = models.ImageField(upload_to="huellas_biometricas/", null=True, blank=True)
    imagen_firma = models.ImageField(upload_to="firmas/", null=True, blank=True)
    usuario = models.CharField(max_length=50)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "huella"
        ordering = ["-fecha"]

    def __str__(self):
        return f"Huella {self.paciente_id} - {self.fecha}"
