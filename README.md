# Music Downloader Pro (Desktop)

Descarga musica en la mejor calidad posible desde Spotify, YouTube y YouTube Music usando una interfaz grafica de escritorio con CustomTkinter.

---

## Caracteristicas

- Soporte multi-fuente: Spotify (canciones, albumes, playlists), YouTube y YouTube Music.
- Arquitectura de fallback de calidad:
  - Plan A: FLAC lossless via Deezer (requiere cookie ARL) o Soulseek.
  - Plan B: mejor calidad disponible via yt-dlp (opus/AAC/MP3).
- Metadatos completos: portada, titulo, artista, album, numero de pista e ISRC.
- Interfaz de escritorio para descargar directamente a cualquier carpeta (por ejemplo, un pendrive).

---

## Requisitos

| Requisito | Version minima |
|-----------|----------------|
| Python    | 3.10+          |
| FFmpeg    | cualquiera     |

FFmpeg es obligatorio para conversion y procesamiento de audio.

---

## Instalacion

### Windows (automatico)

Ejecuta:

```bat
instalar.bat
```

### Manual (Windows / macOS / Linux)

```bash
# 1. Clonar el repositorio
git clone https://github.com/Elitesniper06/MusicDownloader.git
cd MusicDownloader

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Instalar FFmpeg
#    Windows:  winget install FFmpeg
#    macOS:    brew install ffmpeg
#    Linux:    sudo apt install ffmpeg
```

---

## Configuracion

Crea o edita el archivo config.py con tus credenciales:

```python
# Spotify API - https://developer.spotify.com/dashboard
SPOTIFY_CLIENT_ID = "TU_CLIENT_ID"
SPOTIFY_CLIENT_SECRET = "TU_CLIENT_SECRET"

# Deezer - Cookie arl de deezer.com
DEEZER_ARL = "TU_COOKIE_ARL"

# Soulseek (opcional) - https://github.com/slskd/slskd
SLSKD_API_URL = "http://localhost:5030"
SLSKD_API_KEY = "TU_API_KEY"
```

config.py esta en .gitignore. No subas credenciales reales al repositorio.

---

## Uso

Ejecuta la app de escritorio:

```bash
python app.py
```

Pasos:

1. Pega una URL de Spotify, YouTube o YouTube Music.
2. Selecciona la carpeta destino.
3. Pulsa DESCARGAR.

---

## Estructura del proyecto

```text
MusicDownloader/
|- app.py              # Interfaz grafica de escritorio
|- downloader.py       # Motor de descarga (Plan A/B)
|- spotify_utils.py    # Extraccion de metadatos desde Spotify
|- deezer_api.py       # Cliente para Deezer
|- settings.py         # Lectura de configuracion
|- config.py           # Credenciales locales (no versionar)
|- requirements.txt    # Dependencias Python
|- instalar.bat        # Instalacion automatica en Windows
|- iniciar.bat         # Inicio rapido de la app
|- compilar.bat        # Build de ejecutable con PyInstaller
`- MusicDownloaderPro.spec
```

---

## Dependencias principales

- yt-dlp
- spotipy
- customtkinter
- mutagen
- pycryptodome
- requests
- Pillow

---

## Licencia

Proyecto de uso personal. Respeta los terminos de servicio de Spotify, Deezer y YouTube.
