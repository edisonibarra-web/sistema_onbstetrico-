# Helpers para resolver aseguradora por nombre (DGEMPRES03 / formulario)

def normalizar_aseguradora(s):
    """Normaliza nombre para comparación: minúsculas, palabras ordenadas, sin espacios extra."""
    if not s or not isinstance(s, str):
        return ""
    return " ".join(sorted(s.lower().split())).strip()


def resolver_aseguradora_por_nombre(nombre):
    """Devuelve Aseguradora si existe por nombre (iexact o matching normalizado). None si no."""
    from trabajoparto.models import Aseguradora
    if not nombre or not isinstance(nombre, str):
        return None
    n = nombre.strip()
    if not n:
        return None
    ase = Aseguradora.objects.filter(nombre__iexact=n).first()
    if ase:
        return ase
    key = normalizar_aseguradora(n)
    if not key:
        return None
    for a in Aseguradora.objects.all():
        if normalizar_aseguradora(a.nombre) == key:
            return a
    return None


def get_or_create_aseguradora_by_nombre(nombre):
    """Obtiene o crea Aseguradora por nombre. Devuelve (aseguradora, created)."""
    from trabajoparto.models import Aseguradora
    if not nombre or not isinstance(nombre, str):
        return (None, False)
    n = nombre.strip()
    if not n:
        return (None, False)
    ase = resolver_aseguradora_por_nombre(n)
    if ase:
        return (ase, False)
    ase, created = Aseguradora.objects.get_or_create(nombre=n, defaults={})
    return (ase, created)
