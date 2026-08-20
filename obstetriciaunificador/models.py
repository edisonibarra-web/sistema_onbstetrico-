from django.db import models

class AtencionParto(models.Model):
    paciente = models.CharField(max_length=100, blank=True, default='')  # vacío hasta guardar datos en la card
    fecha_inicio = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=20, default="activo")

    def __str__(self):
        return f"Atencion {self.id} - {self.paciente}"
# Create your models here.
