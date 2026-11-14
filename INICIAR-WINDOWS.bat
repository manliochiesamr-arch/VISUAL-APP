@echo off
setlocal
cd /d "%~dp0"
title Visuales - prueba en PC
echo.
echo  ===== VISUALES - prueba en PC =====
echo.
if not exist tools mkdir tools

rem ---------- 1. uv: trae su propio Python 3.12 portable, no toca el Python de la PC ----------
if exist "tools\uv\uv.exe" goto uv_ok
echo Descargando uv, solo la primera vez...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; $z=Join-Path $env:TEMP 'uv-visuales.zip'; Invoke-WebRequest 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' -OutFile $z; Expand-Archive $z -DestinationPath 'tools\uv' -Force; Remove-Item $z"
if not exist "tools\uv\uv.exe" (
  echo ERROR: no se pudo descargar uv. Revisa la conexion a internet.
  pause
  exit /b
)
:uv_ok
set "UV=%~dp0tools\uv\uv.exe"
set "UV_PYTHON_INSTALL_DIR=%~dp0tools\python"
set "UV_CACHE_DIR=%~dp0tools\cache"
echo [ok] uv

rem ---------- 2. ffmpeg portable ----------
if exist "tools\ffmpeg\bin\ffmpeg.exe" goto ffmpeg_local
where ffmpeg >nul 2>nul && goto ffmpeg_ok
echo Descargando ffmpeg, unos 100 MB, solo la primera vez...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; $z=Join-Path $env:TEMP 'ffmpeg-visuales.zip'; Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $z; Expand-Archive $z -DestinationPath 'tools\ffx' -Force; $d=Get-ChildItem 'tools\ffx' -Directory | Select-Object -First 1; Move-Item $d.FullName 'tools\ffmpeg'; Remove-Item 'tools\ffx' -Recurse -Force; Remove-Item $z"
if not exist "tools\ffmpeg\bin\ffmpeg.exe" (
  echo ERROR: no se pudo descargar ffmpeg. Revisa la conexion a internet.
  pause
  exit /b
)
:ffmpeg_local
set "PATH=%~dp0tools\ffmpeg\bin;%PATH%"
:ffmpeg_ok
echo [ok] ffmpeg

rem ---------- 3. Entorno Python 3.12 + librerias ----------
rem visuales-ok2: se agrego PyOpenGL (render gl2, el mismo de la Pi 3)
if exist ".venv\visuales-ok2.txt" goto venv_ok
if exist ".venv\Scripts\python.exe" goto venv_libs
if exist ".venv" rmdir /s /q ".venv"
echo Preparando Python 3.12 y librerias, la primera vez tarda un poco...
"%UV%" venv .venv --python 3.12
if errorlevel 1 goto venv_err
:venv_libs
"%UV%" pip install --python ".venv\Scripts\python.exe" -r requirements.txt
if errorlevel 1 goto venv_err
echo ok> ".venv\visuales-ok2.txt"
:venv_ok
echo [ok] Python y librerias

rem ---------- 4. Arrancar ----------
echo.
echo  MODO TEST: la red y el pendrive de la Pi estan simulados.
echo  Se abre una ventana con la salida de video y el control en el navegador.
echo  Para el iPhone usa la direccion que aparece abajo. Si Windows pregunta por el firewall, permitir en red privada.
echo  Para salir: Esc en la ventana de video, o cerrar esta ventana.
echo.
rem el navegador lo abre la app, en el puerto que haya quedado libre (8080, o 8081... si hay otra app)
rem los videos y shows viven fuera de la carpeta del programa: sobreviven a actualizaciones
set "VISUALES_DATA=%USERPROFILE%\visuales-datos"
if exist "%~dp0datos\library.json" if not exist "%VISUALES_DATA%\library.json" (
  echo Moviendo tus videos a %VISUALES_DATA% ...
  move "%~dp0datos" "%VISUALES_DATA%" >nul
)
echo  Videos y shows guardados en: %VISUALES_DATA%
echo  Pendrive simulado: copia videos a %VISUALES_DATA%\pendrive\mi-pendrive
".venv\Scripts\python.exe" -m visuales --test %*
echo.
echo Visuales se cerro.
pause
exit /b

:venv_err
echo.
echo ERROR preparando Python o las librerias. Mandame una captura de esta ventana.
pause
exit /b
