@echo off
REM Sistema Obstetrico Unificado - MEOWS, Frecuencia Fetal, Trabajo de Parto, Panel de Atencion
REM Ejecutar desde esta carpeta para tener /fetal/, /parto/, /atencion/, /meows/

cd /d "%~dp0"

echo.
echo ========================================
echo  Sistema Obstetrico Unificado
echo ========================================
echo  Panel:    http://127.0.0.1:8000/atencion/1/
echo  MEOWS:    http://127.0.0.1:8000/meows/
echo  Fetal:    http://127.0.0.1:8000/fetal/
echo  Parto:    http://127.0.0.1:8000/parto/
echo ========================================
echo.

if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python manage.py runserver

pause
