@echo off
REM ============================================================================
REM  Compilar Music Downloader Pro en un .exe portable
REM ============================================================================
REM  Requisitos: Python + pip install pyinstaller
REM  FFmpeg se incluye automaticamente desde la instalacion de winget
REM ============================================================================

echo.
echo  ========================================
echo   Compilando Music Downloader Pro...
echo  ========================================
echo.

REM Buscar FFmpeg
set "FFMPEG_DIR="
for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*") do (
    for /d %%S in ("%%D\ffmpeg-*\bin") do (
        if exist "%%S\ffmpeg.exe" set "FFMPEG_DIR=%%S"
    )
)

if not defined FFMPEG_DIR (
    echo  ERROR: No se encontro FFmpeg. Instala con: winget install ffmpeg
    pause
    exit /b 1
)

echo   FFmpeg encontrado en: %FFMPEG_DIR%
echo.

set "ICON_ARGS="
if exist "app.ico" (
    set "ICON_ARGS=--icon app.ico --add-data app.ico;."
    echo   Icono personalizado detectado: app.ico
) else (
    echo   AVISO: No se encontro app.ico. El .exe usara icono por defecto.
)
echo.

pyinstaller ^
    --noconfirm ^
    --onedir ^
    --windowed ^
    --name "MusicDownloaderPro" ^
    --add-data "deezer_api.py;." ^
    --add-data "spotify_utils.py;." ^
    --add-data "settings.py;." ^
    --add-data "downloader.py;." ^
    --add-data "config.py.example;." ^
    --add-binary "%FFMPEG_DIR%\ffmpeg.exe;ffmpeg" ^
    --add-binary "%FFMPEG_DIR%\ffprobe.exe;ffmpeg" ^
    --collect-all customtkinter ^
    --hidden-import spotipy ^
    --hidden-import mutagen ^
    --hidden-import yt_dlp ^
    --hidden-import requests ^
    --hidden-import Crypto ^
    %ICON_ARGS% ^
    app.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo  ========================================
    echo   COMPILACION EXITOSA!
    echo  ========================================
    echo.
    echo   El ejecutable esta en:
    echo   dist\MusicDownloaderPro\
    echo.
    echo   Comprime esa carpeta en ZIP y enviala.
    echo   Tu amigo solo tiene que descomprimir y
    echo   ejecutar MusicDownloaderPro.exe
    echo.
    pause
) else (
    echo.
    echo   ERROR: La compilacion fallo.
    pause
)
