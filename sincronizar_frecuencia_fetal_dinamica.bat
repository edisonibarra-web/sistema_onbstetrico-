@echo off
REM Corre el job de sincronizacion de Frecuencia Cardiaca Fetal (card FETAL de
REM Trabajo de Parto) desde Dinamica (ver trabajoparto/management/commands/
REM sincronizar_frecuencia_fetal_dinamica.py). Mismo signo vital que ya trae
REM MEOWS (FETOCARDIO), para no obligar a la enfermera a digitarlo dos veces.
REM Pensado para registrarse en el Programador de Tareas de Windows, NO para
REM ejecutarse a mano en una ventana interactiva (aunque tambien sirve para
REM probarlo manualmente).
REM
REM Como registrarlo en el Programador de Tareas (una sola vez):
REM
REM   schtasks /create /tn "Trabajo de Parto - Sincronizar Frec. Cardiaca Fetal" ^
REM     /tr "\"%~f0\"" /sc minute /mo 2 /ru "%USERNAME%"
REM
REM Para quitarla despues:
REM   schtasks /delete /tn "Trabajo de Parto - Sincronizar Frec. Cardiaca Fetal" /f

cd /d "%~dp0"

if not exist "logs" mkdir "logs"

set LOGFILE=logs\sync_fetal_dinamica_%date:~-4,4%%date:~-7,2%%date:~-10,2%.log

echo [%date% %time%] Iniciando sincronizacion >> "%LOGFILE%"
venv\Scripts\python.exe manage.py sincronizar_frecuencia_fetal_dinamica >> "%LOGFILE%" 2>&1
echo [%date% %time%] Fin (codigo salida %errorlevel%) >> "%LOGFILE%"
