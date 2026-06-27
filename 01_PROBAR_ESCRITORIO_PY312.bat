@echo off
title Probar Fase 2.3 - Control Combustible Diesel
cd /d "%~dp0"

echo ======================================================
echo   FASE 2.3 - PRUEBA MODO ESCRITORIO
echo ======================================================
echo.
echo Esta prueba usa Python 3.12.
echo.

py -3.12 -m pip install streamlit pandas altair openpyxl pywebview pyinstaller
py -3.12 launcher_desktop_2_3.py

pause
