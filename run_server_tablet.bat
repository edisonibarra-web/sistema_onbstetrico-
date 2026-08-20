@echo off
REM Servidor para acceso desde tablet en la red local
REM Ejecuta: python manage.py runserver 0.0.0.0:8000
REM En la tablet usar: http://<IP_PC>:8000/

cd /d "%~dp0"

echo.
echo ========================================
echo  Servidor para Tablet (red local)
echo ========================================
echo.
echo 1. Obtener IP del PC: ipconfig (buscar "IPv4")
echo 2. En la tablet: http://[IP_PC]:8000/
echo 3. Si fallan POST: verificar firewall del PC
echo.
echo Iniciando en 0.0.0.0:8000 ...
echo ========================================
echo.

python manage.py runserver 0.0.0.0:8000
