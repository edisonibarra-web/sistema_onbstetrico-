"""
Servicio para cargar parámetros MEOWS desde el archivo congelado.
Contiene la lógica de negocio para la carga de datos.
"""
from meows.models import ParametroMEOWS, Parametro
from meows.meows_params import MEOWS_PARAMETROS


def cargar_parametros_meows():
    """
    Carga los parámetros MEOWS desde el archivo congelado.
    Carga en ambos modelos: ParametroMEOWS (legacy) y Parametro (nuevo).
    
    Returns:
        tuple: (cargados, existentes) - Cantidad de parámetros nuevos y existentes
    """
    cargados = 0
    existentes = 0
    
    for p in MEOWS_PARAMETROS:
        # Cargar en ParametroMEOWS (legacy)
        parametro_legacy, created_legacy = ParametroMEOWS.objects.get_or_create(
            codigo=p["codigo"],
            defaults={
                "nombre": p["nombre"],
                "unidad": p["unidad"],
                "orden": p["orden"],
            }
        )
        if not created_legacy:
            cambios_legacy = []
            if parametro_legacy.nombre != p["nombre"]:
                parametro_legacy.nombre = p["nombre"]
                cambios_legacy.append("nombre")
            if parametro_legacy.unidad != p["unidad"]:
                parametro_legacy.unidad = p["unidad"]
                cambios_legacy.append("unidad")
            if parametro_legacy.orden != p["orden"]:
                parametro_legacy.orden = p["orden"]
                cambios_legacy.append("orden")
            if cambios_legacy:
                parametro_legacy.save(update_fields=cambios_legacy)
        
        # Cargar en Parametro (nuevo modelo genérico)
        parametro, created = Parametro.objects.get_or_create(
            codigo=p["codigo"],
            defaults={
                "nombre": p["nombre"],
                "unidad": p["unidad"],
                "orden": p["orden"],
                "activo": True,
            }
        )
        if not created:
            cambios = []
            if parametro.nombre != p["nombre"]:
                parametro.nombre = p["nombre"]
                cambios.append("nombre")
            if parametro.unidad != p["unidad"]:
                parametro.unidad = p["unidad"]
                cambios.append("unidad")
            if parametro.orden != p["orden"]:
                parametro.orden = p["orden"]
                cambios.append("orden")
            if not parametro.activo:
                parametro.activo = True
                cambios.append("activo")
            if cambios:
                parametro.save(update_fields=cambios)
        
        if created:
            cargados += 1
        else:
            existentes += 1
    
    return cargados, existentes

