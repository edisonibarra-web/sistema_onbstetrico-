# Estructura de Templates

Esta carpeta contiene todos los templates HTML de la aplicación Django.

## Estructura de Carpetas

```
templates/
├── base/              # Plantillas base reutilizables
│   └── base.html      # Plantilla base principal
├── clinico/           # Templates específicos de la app clinico
│   └── formulario_trabajo_parto.html
└── css/               # CSS específico de templates (legacy - usar static/css/)
```

## Uso

### En tus vistas Django:

```python
from django.shortcuts import render

def mi_vista(request):
    return render(request, 'clinico/formulario_trabajo_parto.html', {
        'context': 'data'
    })
```

### En tus templates:

```django
{% extends "base/base.html" %}
{% load static %}

{% block content %}
    <h1>Mi contenido</h1>
    <link rel="stylesheet" href="{% static 'css/style.css' %}">
{% endblock %}
```

## Notas

- Los archivos estáticos (CSS, JS, imágenes) deben ir en la carpeta `static/` en la raíz del proyecto
- Usa `{% load static %}` al inicio de tus templates para cargar archivos estáticos
- Usa `{% static 'ruta/al/archivo.css' %}` para referenciar archivos estáticos

