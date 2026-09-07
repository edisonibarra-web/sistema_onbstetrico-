# ============================================================================
#  SISTEMA OBSTÉTRICO — Imagen Docker
#  Módulos: MEOWS, Frecuencia Fetal, Trabajo de Parto, Obstetricia Unificador.
# ============================================================================
# Base Debian (no Alpine): pyodbc/mssql-django necesitan el driver ODBC real
# de Microsoft para hablar con SQL Server, y ese driver solo se distribuye
# empaquetado para distros como Debian/Ubuntu — en Alpine (musl) no instala.
# "bookworm" fijo (no solo "slim") porque el repositorio de Microsoft se
# agrega más abajo apuntando explícitamente a Debian 12 (bookworm).
FROM python:3.11-slim-bookworm

# No generar .pyc y no bufferizar stdout/stderr, para ver los logs en vivo
# con `docker logs` en vez de que se queden atascados en el buffer de Python.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# ----------------------------------------------------------------------------
# Dependencias de sistema operativo
# ----------------------------------------------------------------------------
# - unixodbc/unixodbc-dev + msodbcsql18: driver ODBC de Microsoft para SQL
#   Server, requerido por pyodbc/mssql-django para conectar contra las DOS
#   bases del proyecto (la local "unificada_partos" y la "DGEMPRES_NEXUS" de
#   solo lectura de Dinámica Gerencial/SYAC).
# - libcairo2-dev + pkg-config: reportlab/svglib/rlPyCairo/pyHanko usan Cairo
#   para renderizar gráficos vectoriales (firmas, PDFs); pycairo no trae un
#   wheel prearmado para Linux, así que necesita compilar contra Cairo.
# - build-essential: por si algún paquete de requirements.txt no trae wheel
#   prearmado para esta plataforma y necesita compilarse desde el código fuente.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        gnupg2 \
        unixodbc \
        unixodbc-dev \
        libcairo2-dev \
        pkg-config \
        build-essential \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -sSL https://packages.microsoft.com/config/debian/12/prod.list \
        -o /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get purge -y curl gnupg2 \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# ----------------------------------------------------------------------------
# Dependencias de Python
# ----------------------------------------------------------------------------
# Se copia primero SOLO requirements.txt para aprovechar la cache de capas de
# Docker: mientras las dependencias no cambien, este paso (el más lento) no
# se vuelve a ejecutar aunque cambie el código de la app más abajo.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ----------------------------------------------------------------------------
# Código de la aplicación
# ----------------------------------------------------------------------------
# (.dockerignore excluye venv/, .env, db.sqlite3, logs/ y demás archivos que
# no deben viajar dentro de la imagen).
COPY . .

WORKDIR /app

EXPOSE 8000

# Servidor de desarrollo de Django. Sirve para levantar y probar la imagen;
# antes de pasar a producción real, esto debe cambiar por un servidor WSGI
# como gunicorn detrás de un proxy (nginx), que es lo que Django recomienda
# para no exponer `runserver` fuera de un entorno de desarrollo.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
