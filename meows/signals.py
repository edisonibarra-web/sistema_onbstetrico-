"""
Signals de Django para ejecutar automáticamente el motor MEOWS.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from meows.models import Medicion, MedicionValor
from meows.services.meows import calcular_meows
from meows.services.meows_integration import obtener_valores_clinicos


@receiver(post_save, sender=MedicionValor)
def ejecutar_meows(sender, instance, **kwargs):
    """
    Signal que se ejecuta cuando se guarda un MedicionValor.
    Recalcula automáticamente el puntaje MEOWS y actualiza la Medicion.
    
    Args:
        sender: Modelo que envió el signal (MedicionValor)
        instance: Instancia del MedicionValor guardado
        **kwargs: Argumentos adicionales del signal
    """
    medicion = instance.medicion
    
    # Obtener todos los valores clínicos de la medición
    valores = obtener_valores_clinicos(medicion)
    
    # Validar que estén todos los parámetros necesarios para MEOWS
    # MEOWS requiere: fc, ta_sys, fr, temp, spo2, glasgow (6 parámetros)
    parametros_requeridos = {"fc", "ta_sys", "fr", "temp", "spo2", "glasgow"}
    parametros_presentes = set(valores.keys())
    
    # Solo calcular si tenemos al menos los parámetros requeridos
    if len(parametros_presentes & parametros_requeridos) < len(parametros_requeridos):
        # No hay suficientes parámetros, no calcular MEOWS aún
        return
    
    # Ejecutar el motor MEOWS
    resultado = calcular_meows(valores)
    
    # Actualizar puntajes individuales en MedicionValor
    puntajes = resultado.get("puntajes", {})
    for mv in medicion.valores.select_related("parametro").all():
        codigo = mv.parametro.codigo
        if codigo in puntajes:
            # Actualizar puntaje sin disparar signal (usar update directo)
            MedicionValor.objects.filter(id=mv.id).update(
                puntaje=puntajes[codigo]
            )
    
    # Guardar resultados en Medicion
    # Usar update directo para evitar recursión infinita
    Medicion.objects.filter(id=medicion.id).update(
        meows_total=resultado["meows_total"],
        meows_riesgo=resultado["meows_riesgo"],
        meows_mensaje=resultado["meows_mensaje"],
    )

