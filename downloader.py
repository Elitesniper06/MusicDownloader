# ============================================================================
# downloader.py — Motor de descarga con arquitectura Fallback (Plan A / B)
# ============================================================================

import os
import re
import json
import shutil
import tempfile
import traceback
from pathlib import Path
from typing import Callable, Optional

import requests

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

try:
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TRCK
    from mutagen.oggopus import OggOpus
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False


def _find_ffmpeg_path() -> Optional[str]:
    """
    Busca la ruta de FFmpeg en el sistema.
    En Windows, winget puede instalar ffmpeg pero la terminal actual
    no tiene el PATH actualizado. Esta función lee el PATH directamente
    del registro del sistema para encontrarlo.
    """
    # 1. Probar si ya está en el PATH actual
    if shutil.which("ffmpeg"):
        return os.path.dirname(shutil.which("ffmpeg"))

    # 2. En Windows, leer el PATH del registro del sistema
    if os.name == "nt":
        try:
            import winreg
            # Leer PATH de máquina
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            ) as key:
                machine_path = winreg.QueryValueEx(key, "Path")[0]

            # Leer PATH de usuario
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Environment"
            ) as key:
                user_path = winreg.QueryValueEx(key, "Path")[0]

            full_path = machine_path + ";" + user_path
            for entry in full_path.split(";"):
                entry = entry.strip()
                if entry and os.path.isfile(os.path.join(entry, "ffmpeg.exe")):
                    return entry
        except Exception:
            pass

        # 3. Buscar en ubicaciones comunes de winget
        winget_base = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Microsoft", "WinGet", "Packages",
        )
        if os.path.isdir(winget_base):
            for pkg_dir in os.listdir(winget_base):
                if "ffmpeg" in pkg_dir.lower():
                    bin_candidates = [
                        os.path.join(winget_base, pkg_dir, d, "bin")
                        for d in os.listdir(os.path.join(winget_base, pkg_dir))
                        if os.path.isdir(os.path.join(winget_base, pkg_dir, d, "bin"))
                    ]
                    for bin_path in bin_candidates:
                        if os.path.isfile(os.path.join(bin_path, "ffmpeg.exe")):
                            return bin_path

    return None


# Cache global para no buscar ffmpeg en cada descarga
_FFMPEG_PATH: Optional[str] = _find_ffmpeg_path()


def _find_cookies_file() -> Optional[str]:
    """
    Busca un archivo cookies.txt para autenticación con YouTube.
    Prioridad:
      1. Variable de entorno YOUTUBE_COOKIES_FILE
      2. cookies.txt en el directorio del proyecto
    """
    # 1. Variable de entorno
    env_path = os.environ.get("YOUTUBE_COOKIES_FILE", "")
    if env_path and os.path.isfile(env_path):
        return env_path

    # 2. cookies.txt junto a este script
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
    if os.path.isfile(local_path):
        return local_path

    return None


_COOKIES_FILE: Optional[str] = _find_cookies_file()


# ============================================================================
# PLAN A — Descarga FLAC real vía Deezer (usando ARL) o Soulseek (slskd API)
# ============================================================================

def plan_a_download(
    title: str,
    artist: str,
    album: str,
    dest_folder: str,
    deezer_arl: str = "",
    slskd_api_url: str = "",
    slskd_api_key: str = "",
    isrc: str = None,
    log_callback: Callable[[str], None] = print,
) -> Optional[str]:
    """
    PLAN A: Intenta descargar en FLAC real (lossless).

    Estrategia de prioridad:
      1. Deezer (si hay ARL configurado)
      2. Soulseek vía slskd (si hay credentials configuradas)

    Devuelve la ruta del archivo descargado, o None si falla.

    ─────────────────────────────────────────────────────────────────
    NOTA PARA EL USUARIO:
    Para que el Plan A funcione necesitas configurar al menos UNA de
    estas opciones en config.py:

    Opción 1 - Deezer ARL:
      → Necesitas cuenta Deezer HiFi/Premium
      → Obtén la cookie "arl" desde tu navegador (F12 → Cookies)
      → Pégala en config.py como DEEZER_ARL

    Opción 2 - Soulseek (slskd):
      → Instala slskd: https://github.com/slskd/slskd
      → Configura las credenciales en config.py
    ─────────────────────────────────────────────────────────────────
    """

    # ── Intento 1: Deezer ──────────────────────────────────────────
    if deezer_arl:
        try:
            result = _download_from_deezer(
                title=title,
                artist=artist,
                album=album,
                dest_folder=dest_folder,
                arl=deezer_arl,
                isrc=isrc,
                log_callback=log_callback,
            )
            if result and os.path.exists(result):
                return result
        except Exception as e:
            log_callback(f"⚠️ Deezer falló: {e}")

    # ── Intento 2: Soulseek vía slskd ─────────────────────────────
    if slskd_api_url and slskd_api_key:
        try:
            result = _download_from_soulseek(
                title=title,
                artist=artist,
                dest_folder=dest_folder,
                api_url=slskd_api_url,
                api_key=slskd_api_key,
                log_callback=log_callback,
            )
            if result and os.path.exists(result):
                return result
        except Exception as e:
            log_callback(f"⚠️ Soulseek falló: {e}")

    return None


def _download_from_deezer(
    title: str,
    artist: str,
    album: str,
    dest_folder: str,
    arl: str,
    isrc: str = None,
    log_callback: Callable[[str], None] = print,
) -> Optional[str]:
    """
    Descarga un track en FLAC (o MP3 320) vía la API privada de Deezer.
    Requiere cookie ARL de una cuenta Deezer (idealmente HiFi/Premium para FLAC).
    """
    from deezer_api import DeezerAPI

    dz = DeezerAPI(arl=arl, log=log_callback)

    # Autenticarse
    log_callback("   Autenticando con Deezer...")
    if not dz.login():
        log_callback("   ❌ ARL inválida o expirada. Renueva tu cookie en config.py.")
        return None

    # Buscar y descargar
    result = dz.search_and_download(
        title=title,
        artist=artist,
        dest_folder=dest_folder,
        isrc=isrc,
        album=album,
    )

    return result


def _download_from_soulseek(
    title: str,
    artist: str,
    dest_folder: str,
    api_url: str,
    api_key: str,
    log_callback: Callable[[str], None] = print,
) -> Optional[str]:
    """
    ╔══════════════════════════════════════════════════════════════════╗
    ║  DESCARGA VÍA SOULSEEK (slskd API REST)                       ║
    ║                                                                ║
    ║  Usa la API REST de slskd para buscar y descargar FLAC         ║
    ║  desde la red P2P de Soulseek.                                 ║
    ║                                                                ║
    ║  REQUISITOS:                                                   ║
    ║  1. slskd corriendo localmente (Docker o instalación directa)  ║
    ║     → https://github.com/slskd/slskd                          ║
    ║  2. API key configurada en slskd                               ║
    ║                                                                ║
    ║  FLUJO:                                                        ║
    ║  1. POST /api/v0/searches → iniciar búsqueda                  ║
    ║  2. GET  /api/v0/searches/{id} → obtener resultados            ║
    ║  3. Filtrar por archivos .flac                                 ║
    ║  4. POST /api/v0/transfers/downloads → iniciar descarga        ║
    ║  5. Esperar a que termine y mover archivo a dest_folder        ║
    ╚══════════════════════════════════════════════════════════════════╝
    """

    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    search_query = f"{artist} {title} flac"
    log_callback(f"   Buscando en Soulseek: \"{search_query}\"")

    try:
        # 1. Iniciar búsqueda
        search_resp = requests.post(
            f"{api_url}/api/v0/searches",
            headers=headers,
            json={"searchText": search_query},
            timeout=10,
        )
        search_resp.raise_for_status()
        search_data = search_resp.json()
        search_id = search_data.get("id")

        if not search_id:
            log_callback("   No se pudo iniciar la búsqueda en slskd.")
            return None

        log_callback(f"   Búsqueda iniciada (ID: {search_id}), esperando resultados...")

        # ──────────────────────────────────────────────────────────
        # AQUÍ VA LA LÓGICA DE POLLING Y DESCARGA
        # ──────────────────────────────────────────────────────────
        # El flujo completo sería:
        #
        # import time
        # time.sleep(10)  # Dar tiempo a que lleguen resultados
        #
        # results_resp = requests.get(
        #     f"{api_url}/api/v0/searches/{search_id}",
        #     headers=headers, timeout=30,
        # )
        # results = results_resp.json()
        #
        # # Filtrar archivos .flac de los resultados
        # flac_files = [f for f in results.get("files", [])
        #               if f["filename"].lower().endswith(".flac")]
        #
        # if not flac_files:
        #     return None
        #
        # # Seleccionar el mejor resultado (mayor bitrate/tamaño)
        # best_file = max(flac_files, key=lambda f: f.get("size", 0))
        #
        # # Iniciar descarga
        # dl_resp = requests.post(
        #     f"{api_url}/api/v0/transfers/downloads/{best_file['username']}",
        #     headers=headers,
        #     json={"filename": best_file["filename"]},
        # )
        #
        # # Esperar y mover el archivo descargado a dest_folder
        # ...

        raise NotImplementedError(
            "Descarga Soulseek pendiente de implementar. "
            "Configura slskd y descomenta el código."
        )

    except requests.RequestException as e:
        log_callback(f"   Error de conexión con slskd: {e}")
        return None


# ============================================================================
# PLAN B — Mejor calidad disponible vía yt-dlp (YouTube Music)
# ============================================================================

class YTDLPLogger:
    """Logger personalizado para yt-dlp que redirige a nuestro log_callback."""

    def __init__(self, callback: Callable[[str], None]):
        self.callback = callback

    def debug(self, msg):
        # Silenciar mensajes de debug
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        self.callback(f"❌ {msg.strip()}")


def plan_b_download(
    title: str,
    artist: str,
    album: str = "",
    dest_folder: str = ".",
    cover_url: str = "",
    track_number: int = 0,
    youtube_url: str = None,
    log_callback: Callable[[str], None] = print,
) -> Optional[str]:
    """
    PLAN B: Descarga la mejor calidad de audio disponible desde YouTube Music
    usando yt-dlp. Inserta metadatos y carátula.

    - Si youtube_url se proporciona, descarga directamente de esa URL.
    - Si no, busca "{artist} - {title}" en YouTube Music.

    Formatos de salida posibles (en orden de preferencia de yt-dlp):
      → m4a (AAC ~256kbps) — más común
      → opus (~160kbps) — alta calidad perceptual
      → webm/ogg
    
    Devuelve la ruta del archivo descargado, o None si falla.
    """
    if not YTDLP_AVAILABLE:
        log_callback("❌ [Plan B] yt-dlp no está instalado. Ejecuta: pip install yt-dlp")
        return None

    # Construir la query de búsqueda o usar URL directa
    if youtube_url:
        search_target = youtube_url
    else:
        search_query = f"{artist} - {title}"
        search_target = f"ytsearch1:{search_query}"

    # Nombre de archivo seguro
    safe_title = _sanitize_filename(f"{artist} - {title}")
    output_template = os.path.join(dest_folder, f"{safe_title}.%(ext)s")

    # Opciones de yt-dlp para máxima calidad de audio
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": False,
        "logger": YTDLPLogger(log_callback),
        "writethumbnail": True,           # Descargar thumbnail
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",   # Preferir m4a (AAC)
                "preferredquality": "0",   # Máxima calidad (sin re-encode si es posible)
            },
            {
                "key": "FFmpegMetadata",   # Insertar metadatos
                "add_metadata": True,
            },
            {
                "key": "EmbedThumbnail",   # Incrustar thumbnail en el archivo
            },
        ],
        "prefer_ffmpeg": True,
        # Simular cliente Android Music para evitar detección de bots
        "extractor_args": {"youtube": {"player_client": ["android_music"]}},
        # Metadatos que yt-dlp pasará a FFmpeg
        "parse_metadata": [
            f":{_escape_metadata(title)}:%(meta_title)s",
            f":{_escape_metadata(artist)}:%(meta_artist)s",
        ],
    }

    # Indicar la ruta de FFmpeg si fue encontrada automáticamente
    if _FFMPEG_PATH:
        ydl_opts["ffmpeg_location"] = _FFMPEG_PATH

    # Usar cookies.txt si existe para evitar bloqueo de YouTube
    if _COOKIES_FILE:
        ydl_opts["cookiefile"] = _COOKIES_FILE
        log_callback("   🍪 Usando cookies.txt para autenticación.")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_target, download=True)

            # Si fue una búsqueda, info puede estar dentro de "entries"
            if "entries" in info:
                info = info["entries"][0]

            log_callback(
                f"   ⬇️ Descargando YouTube: {info.get('title', title)} "
                f"({info.get('abr', '?')}kbps)"
            )

        # Buscar el archivo descargado
        downloaded_file = _find_downloaded_file(dest_folder, safe_title)

        if downloaded_file:
            # Escribir metadatos adicionales con mutagen
            _write_metadata(
                filepath=downloaded_file,
                title=title,
                artist=artist,
                album=album,
                track_number=track_number,
                cover_url=cover_url,
                log_callback=log_callback,
            )
            size_mb = os.path.getsize(downloaded_file) / (1024 * 1024)
            log_callback(f"   ✅ {os.path.basename(downloaded_file)} ({size_mb:.1f} MB)")
            return downloaded_file
        else:
            log_callback("❌ Archivo no encontrado tras descarga.")
            return None

    except yt_dlp.utils.DownloadError as e:
        log_callback(f"❌ Error: {e}")
        return None
    except Exception as e:
        log_callback(f"❌ Error: {e}")
        return None


# ============================================================================
# FUNCIÓN PRINCIPAL DE DESCARGA (Orquestador)
# ============================================================================

def download_track(
    title: str,
    artist: str,
    album: str = "",
    dest_folder: str = ".",
    cover_url: str = "",
    track_number: int = 0,
    isrc: str = None,
    youtube_url: str = None,
    deezer_arl: str = "",
    slskd_api_url: str = "",
    slskd_api_key: str = "",
    log_callback: Callable[[str], None] = print,
) -> Optional[str]:
    """
    Orquestador principal. Intenta Plan A → Plan B.

    Retorna la ruta del archivo descargado, o None si todo falla.
    """
    log_callback(f"\n📀 {artist} — {title}")

    # ── Plan A: FLAC real ──────────────────────────────────────────
    result = plan_a_download(
        title=title,
        artist=artist,
        album=album,
        dest_folder=dest_folder,
        deezer_arl=deezer_arl,
        slskd_api_url=slskd_api_url,
        slskd_api_key=slskd_api_key,
        isrc=isrc,
        log_callback=log_callback,
    )

    if result:
        return result

    # ── Plan B: yt-dlp (fallback) ──────────────────────────────────
    log_callback("   ↪ Fallback: YouTube Music...")
    result = plan_b_download(
        title=title,
        artist=artist,
        album=album,
        dest_folder=dest_folder,
        cover_url=cover_url,
        track_number=track_number,
        youtube_url=youtube_url,
        log_callback=log_callback,
    )

    if result:
        return result

    log_callback("❌ No se pudo descargar la canción con ningún método.")
    return None


# ============================================================================
# UTILIDADES INTERNAS
# ============================================================================

def _sanitize_filename(name: str) -> str:
    """Elimina caracteres no permitidos en nombres de archivo de Windows."""
    # Reemplazar caracteres inválidos
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    # Eliminar puntos y espacios al final
    name = name.rstrip(". ")
    # Limitar longitud
    if len(name) > 200:
        name = name[:200]
    return name


def _escape_metadata(value: str) -> str:
    """Escapa caracteres especiales para metadatos de yt-dlp."""
    return value.replace(":", "\\:")


def convert_to_mp3(
    filepath: str,
    log_callback: Callable[[str], None] = print,
) -> Optional[str]:
    """
    Convierte cualquier archivo de audio a MP3 320 kbps CBR usando FFmpeg.

    - Conserva metadatos con -map_metadata 0
    - Usa tags ID3v2.3 para máxima compatibilidad
    - Elimina el archivo original tras la conversión exitosa
    - Si el archivo ya es .mp3, lo devuelve sin cambios

    Retorna la ruta del archivo MP3, o None si falla.
    """
    import subprocess

    if filepath.lower().endswith(".mp3"):
        log_callback("   ℹ️ El archivo ya es MP3, no se necesita conversión.")
        return filepath

    mp3_path = os.path.splitext(filepath)[0] + ".mp3"

    ffmpeg_cmd = "ffmpeg"
    if _FFMPEG_PATH:
        ffmpeg_cmd = os.path.join(_FFMPEG_PATH, "ffmpeg")

    cmd = [
        ffmpeg_cmd,
        "-i", filepath,
        "-codec:a", "libmp3lame",
        "-b:a", "320k",
        "-map_metadata", "0",
        "-id3v2_version", "3",
        "-y",
        mp3_path,
    ]

    log_callback(f"   🔄 Convirtiendo a MP3 320 kbps: {os.path.basename(filepath)}")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0 and os.path.exists(mp3_path):
            size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
            log_callback(
                f"   ✅ Convertido: {os.path.basename(mp3_path)} ({size_mb:.1f} MB)"
            )
            try:
                os.remove(filepath)
            except OSError:
                pass
            return mp3_path
        else:
            stderr_snippet = (result.stderr or "")[-300:]
            log_callback(f"   ❌ FFmpeg falló: {stderr_snippet}")
            return None
    except FileNotFoundError:
        log_callback("   ❌ FFmpeg no encontrado. Instálalo para convertir a MP3.")
        return None
    except subprocess.TimeoutExpired:
        log_callback("   ❌ Conversión a MP3 excedió el tiempo límite.")
        return None
    except Exception as e:
        log_callback(f"   ❌ Error al convertir a MP3: {e}")
        return None


def _find_downloaded_file(folder: str, base_name: str) -> Optional[str]:
    """Busca el archivo descargado en la carpeta destino."""
    audio_extensions = [".m4a", ".opus", ".ogg", ".webm", ".mp3", ".flac", ".wav"]

    for ext in audio_extensions:
        candidate = os.path.join(folder, f"{base_name}{ext}")
        if os.path.exists(candidate):
            return candidate

    # Búsqueda más flexible por si yt-dlp cambió el nombre
    for f in os.listdir(folder):
        f_lower = f.lower()
        if any(f_lower.endswith(ext) for ext in audio_extensions):
            if base_name.lower()[:30] in f_lower:
                return os.path.join(folder, f)

    return None


def _write_metadata(
    filepath: str,
    title: str,
    artist: str,
    album: str = "",
    track_number: int = 0,
    cover_url: str = "",
    log_callback: Callable[[str], None] = print,
) -> None:
    """Escribe metadatos y carátula en el archivo de audio usando mutagen."""
    if not MUTAGEN_AVAILABLE:
        log_callback("   ℹ️ mutagen no instalado, metadatos no escritos.")
        return

    ext = os.path.splitext(filepath)[1].lower()

    try:
        # Descargar carátula si hay URL
        cover_data = None
        if cover_url:
            try:
                resp = requests.get(cover_url, timeout=15)
                if resp.status_code == 200:
                    cover_data = resp.content
            except Exception:
                pass

        if ext == ".m4a":
            audio = MP4(filepath)
            audio["\xa9nam"] = [title]       # Título
            audio["\xa9ART"] = [artist]      # Artista
            if album:
                audio["\xa9alb"] = [album]   # Álbum
            if track_number:
                audio["trkn"] = [(track_number, 0)]  # Número de pista
            if cover_data:
                audio["covr"] = [
                    MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)
                ]
            audio.save()

        elif ext == ".flac":
            audio = FLAC(filepath)
            audio["title"] = title
            audio["artist"] = artist
            if album:
                audio["album"] = album
            if track_number:
                audio["tracknumber"] = str(track_number)
            if cover_data:
                from mutagen.flac import Picture
                pic = Picture()
                pic.type = 3  # Cover (front)
                pic.mime = "image/jpeg"
                pic.data = cover_data
                audio.add_picture(pic)
            audio.save()

        elif ext in (".opus", ".ogg"):
            audio = OggOpus(filepath)
            audio["title"] = [title]
            audio["artist"] = [artist]
            if album:
                audio["album"] = [album]
            if track_number:
                audio["tracknumber"] = [str(track_number)]
            # OggOpus soporta carátulas vía base64 en METADATA_BLOCK_PICTURE
            if cover_data:
                import base64
                from mutagen.flac import Picture
                pic = Picture()
                pic.type = 3
                pic.mime = "image/jpeg"
                pic.data = cover_data
                audio["metadata_block_picture"] = [
                    base64.b64encode(pic.write()).decode("ascii")
                ]
            audio.save()

        else:
            pass

    except Exception as e:
        log_callback(f"   ⚠️ Error escribiendo metadatos: {e}")


def is_youtube_url(url: str) -> bool:
    """Detecta si una URL es de YouTube/YouTube Music."""
    return bool(re.search(
        r"(youtube\.com/watch|youtu\.be/|youtube\.com/playlist|music\.youtube\.com)",
        url,
    ))


def get_youtube_info(url: str) -> list[dict]:
    """
    Extrae información de una URL de YouTube sin descargar.
    Devuelve lista de tracks con título y artista.
    """
    if not YTDLP_AVAILABLE:
        raise ImportError("yt-dlp no está instalado.")

    # Detectar si es una playlist o un video individual
    is_playlist = bool(re.search(
        r"youtube\.com/playlist\?list=|&list=[A-Za-z0-9_-]{10,}",
        url,
    ))

    if is_playlist:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
        }
        if _FFMPEG_PATH:
            ydl_opts["ffmpeg_location"] = _FFMPEG_PATH
        if _COOKIES_FILE:
            ydl_opts["cookiefile"] = _COOKIES_FILE

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        tracks = []
        for entry in info.get("entries", []):
            if entry:
                tracks.append(_parse_yt_info(entry))
        return tracks
    else:
        # Para videos individuales, extraer metadatos completos
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
        if _FFMPEG_PATH:
            ydl_opts["ffmpeg_location"] = _FFMPEG_PATH
        if _COOKIES_FILE:
            ydl_opts["cookiefile"] = _COOKIES_FILE

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if "entries" in info:
            info = info["entries"][0] if info["entries"] else {}

        return [_parse_yt_info(info)]


def _parse_yt_info(info: dict) -> dict:
    """Parsea la info de un video de YouTube a nuestro formato."""
    full_title = info.get("title", "Unknown")

    # yt-dlp a veces proporciona 'artist' y 'track' directamente
    yt_artist = info.get("artist") or info.get("creator") or ""
    yt_track = info.get("track") or ""
    yt_album = info.get("album") or ""

    if yt_artist and yt_track:
        # Metadatos directos de YouTube Music
        artist = yt_artist
        title = yt_track
    elif " - " in full_title:
        # Intentar separar "Artista - Título" del título del video
        parts = full_title.split(" - ", 1)
        artist = parts[0].strip()
        title = parts[1].strip()
    else:
        artist = info.get("uploader", "") or info.get("channel", "Unknown Artist")
        # Limpiar nombre del canal (quitar " - Topic", " VEVO", etc.)
        artist = re.sub(r"\s*-\s*Topic$", "", artist)
        artist = re.sub(r"VEVO$", "", artist).strip()
        title = full_title

    # Limpiar sufijos comunes del título
    title = re.sub(
        r"\s*\(?(Official\s*(Music\s*)?Video|Audio|Lyric(s)?\s*Video|Visualizer|HD|HQ)\)?\s*$",
        "", title, flags=re.IGNORECASE,
    ).strip()

    return {
        "title": title or "Unknown",
        "artist": artist or "Unknown Artist",
        "album": yt_album,
        "track_number": info.get("track_number") or 0,
        "duration_ms": (info.get("duration") or 0) * 1000,
        "cover_url": info.get("thumbnail", ""),
        "isrc": None,
        "youtube_url": info.get("url") or info.get("webpage_url", ""),
    }
