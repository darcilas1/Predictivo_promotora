@echo off
REM ============================================================
REM  run_orquestador_sabado.bat – RPA Predictivo Promotora SÁBADO
REM  Activa el entorno virtual y lanza el orquestador del sábado
REM ============================================================

REM Ir a la carpeta del proyecto
cd /d "%~dp0"

REM Activar el entorno virtual
call venv\Scripts\activate.bat

REM Ejecutar el orquestador del sábado
python orquestador_sabado.py

REM Mantener la ventana abierta al terminar
pause
