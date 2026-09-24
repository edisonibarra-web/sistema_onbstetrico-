from django.db import models

class AtencionParto(models.Model):
    paciente = models.CharField(max_length=100, blank=True, default='')  # vacío hasta guardar datos en la card
    fecha_inicio = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=20, default="activo")
    # Ingreso de Dinámica al que pertenece esta atención (ADNINGRESO.AINCONSEC,
    # el "número de ingreso" que también nombra la carpeta del paciente en el
    # repositorio clínico/NAS). Antes la atención se reutilizaba para siempre
    # por cédula; ahora hay una atención por ingreso -- ver
    # obstetriciaunificador.repositorio.resolver_atencion_ingreso_activo.
    numero_ingreso = models.CharField(max_length=30, blank=True, default='', db_index=True)
    fecha_ingreso_dinamica = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Atencion {self.id} - {self.paciente}"


class DocumentoRepositorio(models.Model):
    """
    Bitácora de cada formato final (PDF) enviado al repositorio clínico (NAS),
    exitoso o no -- para auditoría y para poder reintentar un envío fallido.
    """
    ESTADO_ENVIADO = 'enviado'
    ESTADO_ERROR = 'error'

    atencion = models.ForeignKey(
        AtencionParto, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='documentos_repositorio',
    )
    cedula = models.CharField(max_length=50, db_index=True)
    numero_ingreso = models.CharField(max_length=30, blank=True, default='')
    formato = models.CharField(max_length=60)
    # id del registro de origen en el módulo (Formulario de Trabajo de Parto,
    # RegistroParto de Control Posparto...), vacío para MEOWS (va por ingreso).
    referencia = models.CharField(max_length=64, blank=True, default='')
    modo = models.CharField(max_length=10)  # 'local' | 'nas'
    estado = models.CharField(max_length=10, db_index=True)
    nombre_archivo = models.CharField(max_length=255, blank=True, default='')
    ruta = models.CharField(max_length=500, blank=True, default='')
    tamano_bytes = models.PositiveIntegerField(null=True, blank=True)
    detalle_error = models.TextField(blank=True, default='')
    enviado_por = models.CharField(max_length=255, blank=True, default='')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Documento enviado al repositorio'
        verbose_name_plural = 'Documentos enviados al repositorio'

    def __str__(self):
        return f"{self.formato} {self.cedula}/{self.numero_ingreso} ({self.estado})"
