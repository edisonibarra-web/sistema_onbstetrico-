@echo off
REM Corre el job de sincronizacion de signos vitales desde Dinamica (ver
REM meows/management/commands/sincronizar_signos_vitales_dinamica.py).
REM Pensado para registrarse en el Programador de Tareas de Windows, NO para
REM ejecutarse a mano en una ventana interactiva (aunque tambien sirve para
REM probarlo manualmente).
REM
REM Como registrarlo en el Programador de Tareas (una sola vez):
REM
REM   schtasks /create /tn "MEOWS - Sincronizar signos vitales Dinamica" ^
REM     /tr "\"%~f0\"" /sc minute /mo 5 /ru "%USERNAME%"
REM
REM Actualmente registrada en /mo 2 (cada 2 minutos) mientras se prueban las
REM alertas de cerca. Volver a /mo 5 (o mas) para uso normal, para no golpear
REM Nexus con tanta frecuencia. Para quitarla despues:
REM   schtasks /delete /tn "MEOWS - Sincronizar signos vitales Dinamica" /f

cd /d "%~dp0"

if not exist "logs" mkdir "logs"

set LOGFILE=logs\sync_dinamica_%date:~-4,4%%date:~-7,2%%date:~-10,2%.log

echo [%date% %time%] Iniciando sincronizacion >> "%LOGFILE%"
venv\Scripts\python.exe manage.py sincronizar_signos_vitales_dinamica >> "%LOGFILE%" 2>&1
echo [%date% %time%] Fin (codigo salida %errorlevel%) >> "%LOGFILE%"
