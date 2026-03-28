@echo off
REM Script de inicio automático para MusicDownloader

REM Verifica si Python está instalado
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Python no está instalado. Por favor, instala Python 3.8 o superior y vuelve a intentarlo.
    pause
    exit /b
)

REM Cambia a la ruta absoluta del proyecto
cd /d "%~dp0"

REM Instala dependencias si es necesario
pip install -r requirements.txt

REM Busca app.py en la carpeta actual y subcarpetas y lo ejecuta
for /r %%f in (app.py) do (
    echo Ejecutando %%f
    python "%%f"
    goto fin
)
echo No se encontró app.py en el proyecto.
:fin
pause
