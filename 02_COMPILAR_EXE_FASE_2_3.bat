@echo off
title Compilar Fase 2.3 - Control Combustible Diesel
cd /d "%~dp0"

echo ======================================================
echo   CONTROL DE COMBUSTIBLE DIESEL
echo   FASE 2.3 - COMPILACION LIMPIA WINDOWS
echo ======================================================
echo.
echo Se usara Python 3.12 para evitar errores de Python 3.14.
echo.
pause

echo Limpiando compilaciones antiguas...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del ControlCombustibleDiesel_Fase_2_3.spec 2>nul

echo.
echo Instalando requisitos en Python 3.12...
py -3.12 -m pip install --upgrade pip
py -3.12 -m pip install streamlit pandas altair openpyxl pywebview pyinstaller

echo.
echo Compilando EXE portable...
py -3.12 -m PyInstaller ^
  --noconfirm ^
  --onedir ^
  --windowed ^
  --name ControlCombustibleDiesel_Fase_2_3 ^
  --add-data "app.py;." ^
  --add-data "data;data" ^
  --collect-all streamlit ^
  --collect-all altair ^
  --collect-all pywebview ^
  --hidden-import=webview ^
  --hidden-import=webview.platforms.edgechromium ^
  --hidden-import=webview.platforms.winforms ^
  launcher_desktop_2_3.py

echo.
echo ======================================================
echo COMPILACION FINALIZADA
echo ======================================================
echo.
echo Revise la carpeta:
echo dist\ControlCombustibleDiesel_Fase_2_3
echo.
pause
