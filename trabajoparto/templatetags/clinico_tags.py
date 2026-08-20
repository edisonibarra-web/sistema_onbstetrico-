from django import template
from datetime import datetime
from django.utils import timezone
import re

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """
    Filtro para obtener un valor de un diccionario por su clave.
    Uso en template: {{ mi_dict|get_item:mi_key }}
    """
    if dictionary:
        return dictionary.get(key)
    return None

@register.filter
def get_val(dictionary, key):
    """Alias de get_item para brevedad"""
    if dictionary:
        return dictionary.get(key, "")
    return ""

@register.filter
def hora_12h(value):
    """
    Convierte una hora en formato 24 horas a formato 12 horas con AM/PM.
    Si es datetime, incluye también la fecha completa.
    Acepta datetime, time, o string en formato "HH:MM" o ISO datetime string.
    Replica el formato usado en el formulario web (toLocaleString).
    """
    if not value:
        return ""
    
    # Si es un string ISO datetime (viene de la API o de isoformat())
    if isinstance(value, str):
        # Intentar parsear como ISO datetime string
        try:
            from datetime import datetime
            # Intentar parsear como ISO datetime
            if 'T' in value or len(value) > 10:
                # Es un datetime ISO string
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
                # Convertir a zona horaria local de Colombia si es necesario
                if timezone.is_aware(dt):
                    # Convertir a zona horaria de Colombia (America/Bogota)
                    # Django ya tiene configurada la zona horaria en settings
                    dt = timezone.localtime(dt)
                fecha = dt.strftime('%d/%m/%Y')
                horas = dt.hour
                minutos = dt.minute
                ampm = 'p. m.' if horas >= 12 else 'a. m.'
                horas_12 = horas % 12
                horas_12 = horas_12 if horas_12 else 12
                return f"{fecha}, {horas_12:02d}:{minutos:02d} {ampm}"
            else:
                # Es solo hora en formato "HH:MM"
                hora_match = re.match(r'^(\d{1,2}):(\d{2})$', value)
                if hora_match:
                    horas = int(hora_match.group(1))
                    minutos = hora_match.group(2)
                    ampm = 'p. m.' if horas >= 12 else 'a. m.'
                    horas_12 = horas % 12
                    horas_12 = horas_12 if horas_12 else 12
                    return f"{horas_12:02d}:{minutos:02d} {ampm}"
        except (ValueError, AttributeError):
            # Si falla el parseo, retornar el valor original
            pass
    
    # Si es un objeto datetime (tiene día, mes, año)
    if hasattr(value, 'day') and hasattr(value, 'hour') and hasattr(value, 'minute'):
        # Asegurar que esté en la zona horaria correcta
        if timezone.is_aware(value):
            # Convertir a zona horaria local de Colombia (Django ya tiene configurada la zona horaria)
            value = timezone.localtime(value)
        fecha = value.strftime('%d/%m/%Y')
        horas = value.hour
        minutos = value.minute
        ampm = 'p. m.' if horas >= 12 else 'a. m.'
        horas_12 = horas % 12
        horas_12 = horas_12 if horas_12 else 12
        return f"{fecha}, {horas_12:02d}:{minutos:02d} {ampm}"
    # Si es un objeto time (solo hora y minuto)
    elif hasattr(value, 'hour') and hasattr(value, 'minute'):
        horas = value.hour
        minutos = value.minute
        ampm = 'p. m.' if horas >= 12 else 'a. m.'
        horas_12 = horas % 12
        horas_12 = horas_12 if horas_12 else 12
        return f"{horas_12:02d}:{minutos:02d} {ampm}"
    
    return str(value)

