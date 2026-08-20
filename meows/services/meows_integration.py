"""
Integración entre modelos y motor MEOWS.
Funciones utilitarias para convertir datos entre modelos y el motor de cálculo.
"""
from typing import Dict
from meows.models import Medicion


def obtener_valores_clinicos(medicion: Medicion) -> Dict:
    """
    Convierte los MedicionValor en un diccionario usable por MEOWS.
    
    Args:
        medicion: Instancia de Medicion
        
    Returns:
        dict: Diccionario con códigos de parámetros como keys y valores convertidos
              Ejemplo: {"fc": 120, "ta_sys": 85, "temp": 38.6, ...}
    """
    valores = {}
    
    for mv in medicion.valores.select_related("parametro").all():
        codigo = mv.parametro.codigo
        valor = mv.valor
        
        # Conversión de tipos según parámetro
        # Usamos códigos congelados - no hay lógica clínica, solo adaptación
        try:
            if codigo in ["fc", "ta_sys", "ta_dia", "fr", "spo2", "glasgow"]:
                valores[codigo] = int(valor)
            elif codigo == "temp":
                valores[codigo] = float(valor)
            else:
                # Si no es un parámetro conocido, intentar convertir a float
                valores[codigo] = float(valor)
        except (ValueError, TypeError):
            # Si no se puede convertir, omitir este parámetro
            continue
    
    return valores

