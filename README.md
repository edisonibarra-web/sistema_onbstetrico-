# Sistema Obstetrico

Sistema web desarrollado con Django para la gestion y seguimiento de procesos obstetricos.

## Modulos principales

- Frecuencia Fetal
- MEOWS
- Trabajo de Parto
- Obstetricia Unificador

## Tecnologias

- Python 3.11
- Django 5.2.11
- Django REST Framework
- SQL Server
- mssql-django
- pyodbc
- Docker
- Docker Compose

## Ejecucion con Docker

Desde esta carpeta:

    sistema_obstetrico\

Levantar el sistema:

    docker compose up -d

Ver el estado:

    docker compose ps

Consultar los logs:

    docker compose logs --tail=50 web

Acceder al sistema:

    http://localhost:8000/login/

Detener los servicios:

    docker compose down

## Variables de entorno

Las variables de entorno se mantienen en el archivo .env local.

Este archivo no debe ser enviado al repositorio.

Para configurar un nuevo entorno, utilizar .env.example como referencia.

## Desarrollo

El proyecto utiliza un volumen Docker para reflejar los cambios del codigo local dentro del contenedor:

    .:/app

Los cambios realizados desde VS Code pueden ser detectados por Django automaticamente durante el desarrollo.

## Git

La configuracion Docker esta versionada en el repositorio:

- Dockerfile
- docker-compose.yml
- .dockerignore
- requirements.txt

Las credenciales y archivos sensibles permanecen excluidos mediante .gitignore y .dockerignore.
