# 🎵 Music Downloader Pro

Descarga música en la **mejor calidad posible** desde Spotify, YouTube y YouTube Music.  
Disponible como **aplicación de escritorio** (GUI con CustomTkinter) y como **aplicación web** (Flask).

---

## ✨ Características

- 🎧 **Soporte multi-fuente**: Spotify (canciones, álbumes, playlists), YouTube y YouTube Music.
- 🏆 **Arquitectura de fallback de calidad**:
  - **Plan A**: FLAC lossless vía Deezer (requiere cookie ARL) o Soulseek.
  - **Plan B**: Mejor calidad disponible vía `yt-dlp` (opus/AAC/MP3).
- 🖼️ **Metadatos completos**: portada, título, artista, álbum, número de pista e ISRC.
- 🖥️ **Interfaz gráfica de escritorio** — descarga directamente a un pendrive u otra carpeta.
- 🌐 **Interfaz web** — accesible desde el navegador; descarga los archivos vía ZIP.
- ☁️ **Desplegable en la nube** — configuración lista para Render.com.

---

## 📋 Requisitos

| Requisito | Versión mínima |
|-----------|---------------|
| Python    | 3.10+         |
| FFmpeg    | cualquiera    |

> **FFmpeg es obligatorio** para que `yt-dlp` pueda convertir y mezclar el audio.

---

## 🚀 Instalación

### Windows (automático)

```bat
instalar.bat
```

El script verifica Python, instala las dependencias y comprueba si FFmpeg está disponible.

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

## ⚙️ Configuración

Copia el archivo de ejemplo y rellena tus credenciales:

```bash
cp config.py.example config.py
```

Edita `config.py`:

```python
# Spotify API — https://developer.spotify.com/dashboard
SPOTIFY_CLIENT_ID     = "TU_CLIENT_ID"
SPOTIFY_CLIENT_SECRET = "TU_CLIENT_SECRET"

# Deezer — Cookie "arl" de deezer.com (F12 → Application → Cookies)
DEEZER_ARL = "TU_COOKIE_ARL"

# Soulseek (opcional) — https://github.com/slskd/slskd
SLSKD_API_URL = "http://localhost:5030"
SLSKD_API_KEY = "TU_API_KEY"
```

> ⚠️ `config.py` está en `.gitignore` — **nunca lo subas a GitHub**.

### Obtener credenciales

- **Spotify**: crea una app en el [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) y copia el *Client ID* y *Client Secret*.
- **Deezer ARL**: inicia sesión en [deezer.com](https://www.deezer.com), abre las DevTools (F12), ve a *Application → Cookies* y copia el valor de la cookie `arl`.

---

## ▶️ Uso

### Aplicación de escritorio

```bash
python app.py
```

1. Pega la URL de Spotify, YouTube o YouTube Music.
2. Selecciona la carpeta destino (p. ej. tu pendrive).
3. Pulsa **DESCARGAR**.

### Aplicación web

```bash
python web_app.py
```

Abre tu navegador en [http://localhost:5000](http://localhost:5000).  
Los archivos descargados se sirven desde el servidor; puedes descargarlos individualmente o como ZIP.

---

## ☁️ Despliegue en Render.com

El repositorio incluye `render.yaml` y `build.sh` listos para usarse.

1. Crea un nuevo servicio web en [Render](https://render.com) apuntando a este repositorio.
2. Render detectará `render.yaml` automáticamente.
3. Configura las variables de entorno en el dashboard de Render:
   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`
   - `DEEZER_ARL`

---

## 🗂️ Estructura del proyecto

```
MusicDownloader/
├── app.py            # Interfaz gráfica de escritorio (CustomTkinter)
├── web_app.py        # Servidor web (Flask + SSE)
├── downloader.py     # Motor de descarga (Plan A/B con fallback)
├── spotify_utils.py  # Extracción de metadatos desde Spotify
├── deezer_api.py     # Cliente para la API de Deezer
├── config.py.example # Plantilla de configuración de credenciales
├── requirements.txt  # Dependencias Python
├── instalar.bat      # Script de instalación para Windows
├── build.sh          # Script de build para Render.com
├── render.yaml       # Configuración de despliegue en Render.com
├── Procfile          # Comando de inicio para plataformas PaaS
├── static/           # Assets estáticos (CSS, JS) de la web
└── templates/        # Plantillas HTML de Flask
```

---

## 📦 Dependencias principales

| Paquete         | Uso                                      |
|-----------------|------------------------------------------|
| `yt-dlp`        | Descarga de YouTube / YouTube Music      |
| `spotipy`       | API de Spotify                           |
| `customtkinter` | Interfaz gráfica de escritorio           |
| `flask`         | Servidor web                             |
| `mutagen`       | Escritura de metadatos en archivos audio |
| `pycryptodome`  | Descifrado de streams de Deezer          |
| `requests`      | Peticiones HTTP                          |
| `gunicorn`      | Servidor WSGI para producción            |

---

## 📄 Licencia

Este proyecto es de uso personal. Respeta los términos de servicio de Spotify, Deezer y YouTube al utilizarlo.
