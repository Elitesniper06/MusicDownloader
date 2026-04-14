@echo off
setlocal
title FullCalidad - Inicio
REM Inicio todo-en-uno: prepara entorno y abre la app

REM Cambia a la ruta del proyecto
cd /d "%~dp0"

echo ============================================
echo   FullCalidad - Inicio automatico
echo ============================================
echo.

set "APP_FILE="
for /r %%f in (app.py) do (
    set "APP_FILE=%%f"
    goto :app_found
)

:app_found
if not defined APP_FILE (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('No se encontro app.py en la carpeta del proyecto.','FullCalidad',[System.Windows.Forms.MessageBoxButtons]::OK,[System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null"
    exit /b 1
)

REM Resolver comando Python para instalacion de paquetes
set "PY_CMD="
where py >nul 2>nul
if %errorlevel% EQU 0 (
    set "PY_CMD=py -3"
)

if not defined PY_CMD (
    where python >nul 2>nul
    if %errorlevel% EQU 0 (
        set "PY_CMD=python"
    )
)

if not defined PY_CMD (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Python no esta instalado o no esta en PATH. Instala Python 3.10+ y vuelve a intentar.','FullCalidad',[System.Windows.Forms.MessageBoxButtons]::OK,[System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null"
    exit /b 1
)

echo [1/3] Instalando/actualizando dependencias...
call %PY_CMD% -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('No se pudieron instalar dependencias de Python. Revisa tu conexion a internet e intenta de nuevo.','FullCalidad',[System.Windows.Forms.MessageBoxButtons]::OK,[System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null"
    exit /b 1
)
echo.

echo [2/3] Verificando FFmpeg...
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo FFmpeg no esta en PATH. Intentando instalar con winget...
    where winget >nul 2>nul
    if not errorlevel 1 (
        winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
    )

    where ffmpeg >nul 2>nul
    if errorlevel 1 (
        echo.
        echo [AVISO] FFmpeg no se pudo instalar automaticamente.
        echo         Algunas descargas/conversiones pueden fallar.
        echo         Puedes instalarlo manualmente con: winget install ffmpeg
    ) else (
        echo [OK] FFmpeg encontrado tras la instalacion.
    )
) else (
    echo [OK] FFmpeg encontrado.
)
echo.

echo [3/3] Abriendo aplicacion...

REM Abrir sin consola cuando sea posible
where pyw >nul 2>nul
if %errorlevel% EQU 0 (
    start "" /b pyw "%APP_FILE%"
    exit /b 0
)

where pythonw >nul 2>nul
if %errorlevel% EQU 0 (
    start "" /b pythonw "%APP_FILE%"
    exit /b 0
)

REM Ultimo fallback (abrira una consola)
start "" /b %PY_CMD% "%APP_FILE%"
exit /b 0
