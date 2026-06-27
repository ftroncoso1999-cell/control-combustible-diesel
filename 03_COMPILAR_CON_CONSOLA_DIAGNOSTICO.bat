@echo off
title Compilar con consola diagnostico - Fase 2.3
cd /d "%~dp0"

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del ControlCombustibleDiesel_Fase_2_3.spec 2>nul

py -3.12 -m PyInstaller ^
  --noconfirm ^
  --onedir ^
  --console ^
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

pause
