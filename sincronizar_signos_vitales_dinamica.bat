@echo off
REM Corre el job de sincronizacion de signos vitales desde Dinamica (ver
REM meows/management/commands/sincronizar_signos_vitales_dinamica.py).
REM Pensado para registrarse en el Programador de Tareas de Windows, NO para
REM ejecutarse a mano en una ventana interactiva (aunque tambien sirve para
REM probarlo manualmente).
REM
REM Como registrarlo en el Programador de Tareas (una sola vez), cada 5 minutos:
REM
REM   schtasks /create /tn "MEOWS - Sincronizar signos vitales Dinamica" ^
REM     /tr "\"%~f0\"" /sc minute /mo 5 /ru "%USERNAME%"
REM
REM Ajusta /mo 5 a la frecuencia que decidan. Para quitarla despues:
REM   schtasks /delete /tn "MEOWS - Sincronizar signos vitales Dinamica" /f

cd /d "%~dp0"

if not exist "logs" mkdir "logs"

set LOGFILE=logs\sync_dinamica_%date:~-4,4%%date:~-7,2%%date:~-10,2%.log

echo [%date% %time%] Iniciando sincronizacion >> "%LOGFILE%"
venv\Scripts\python.exe manage.py sincronizar_signos_vitales_dinamica >> "%LOGFILE%" 2>&1
echo [%date% %time%] Fin (codigo salida %errorlevel%) >> "%LOGFILE%"
