@echo off
echo ============================================
echo   Music Downloader Pro - Instalacion
echo ============================================
echo.

REM Verificar que Python esta instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no esta instalado o no esta en el PATH.
    echo Descargalo de https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] Instalando dependencias de Python...
pip install -r requirements.txt
echo.

echo [2/3] Verificando FFmpeg...
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [AVISO] FFmpeg no esta instalado o no esta en el PATH.
    echo.
    echo FFmpeg es NECESARIO para que yt-dlp convierta audio.
    echo.
    echo Opciones para instalar FFmpeg:
    echo   1. winget install FFmpeg  (si tienes winget)
    echo   2. choco install ffmpeg   (si tienes Chocolatey)
    echo   3. Descargalo de https://ffmpeg.org/download.html
    echo      y anade la carpeta bin al PATH del sistema.
    echo.
) else (
    echo [OK] FFmpeg encontrado.
)

echo [3/3] Todo listo.
echo.
echo ============================================
echo   Para ejecutar la aplicacion:
echo     python app.py
echo ============================================
echo.
pause
