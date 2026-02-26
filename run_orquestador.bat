@echo off
REM ============================================================
REM  run_orquestador.bat – RPA Predictivo Promotora
REM  Activa el entorno virtual y lanza el orquestador principal
REM ============================================================

REM Ir a la carpeta del proyecto
cd /d "%~dp0"

REM Activar el entorno virtual
call venv\Scripts\activate.bat

REM Ejecutar el orquestador
python orquestador.py

REM Mantener la ventana abierta al terminar (opcional)
pause