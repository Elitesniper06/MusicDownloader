"""
web_app.py — Versión web de Music Downloader.

Usa Flask como servidor + Server-Sent Events (SSE) para enviar logs
en tiempo real al navegador. Los archivos descargados se almacenan
en una carpeta temporal del servidor y luego se sirven como descarga
al usuario a través del navegador.

Ejecutar:
    python web_app.py

Luego abrir:  http://localhost:5000
Para exponer a internet: usar ngrok, Cloudflare Tunnel, o desplegar en un VPS.
"""

import os
import re
import uuid
import shutil
import threading
import tempfile
import zipfile
import time
from queue import Queue, Empty
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    Response,
    send_file,
    abort,
)

# ── Credenciales: leer de variables de entorno (obligatorio en Render) ──
# En local, intenta importar config.py; en la nube, usa env vars.
try:
    from config import (
        SPOTIFY_CLIENT_ID,
        SPOTIFY_CLIENT_SECRET,
        DEEZER_ARL,
        SLSKD_API_URL,
        SLSKD_API_KEY,
    )
except ImportError:
    SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
    SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    DEEZER_ARL = os.environ.get("DEEZER_ARL", "")
    SLSKD_API_URL = os.environ.get("SLSKD_API_URL", "")
    SLSKD_API_KEY = os.environ.get("SLSKD_API_KEY", "")

from spotify_utils import is_spotify_url, get_tracks_from_spotify_url
from downloader import (
    download_track,
    is_youtube_url,
    get_youtube_info,
)

# ═══════════════════════════════════════════════════════════════════════
# APP FLASK
# ═══════════════════════════════════════════════════════════════════════

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB máx. para uploads

# ── Asegurar que ffmpeg esté en el PATH (para Render) ──
_ffmpeg_home = os.path.join(os.path.expanduser("~"), "ffmpeg")
if os.path.isdir(_ffmpeg_home):
    os.environ["PATH"] = _ffmpeg_home + os.pathsep + os.environ.get("PATH", "")

# Almacén en memoria de sesiones de descarga activas
# Clave: job_id (str) → Valor: dict con estado y cola de mensajes
_jobs: dict[str, dict] = {}

# Carpeta base para almacenar descargas temporales del servidor
DOWNLOADS_BASE = os.path.join(tempfile.gettempdir(), "musicdl_web")
os.makedirs(DOWNLOADS_BASE, exist_ok=True)

# Carpeta para almacenar el archivo de cookies subido
COOKIES_DIR = os.path.join(DOWNLOADS_BASE, "_cookies")
os.makedirs(COOKIES_DIR, exist_ok=True)
COOKIES_FILE = os.path.join(COOKIES_DIR, "cookies.txt")  # ruta fija


# ═══════════════════════════════════════════════════════════════════════
# RUTAS — PÁGINAS
# ═══════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """Página principal con la interfaz del downloader."""
    return render_template("index.html")


@app.route("/health")
def health():
    """Endpoint de salud — para verificar que la app funciona en Render."""
    import shutil
    ffmpeg_ok = shutil.which("ffmpeg") is not None
    return jsonify({
        "status": "ok",
        "ffmpeg": ffmpeg_ok,
        "spotify_configured": bool(SPOTIFY_CLIENT_ID),
        "deezer_configured": bool(DEEZER_ARL),
    })


# ═══════════════════════════════════════════════════════════════════════
# RUTAS — API
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/download", methods=["POST"])
def api_start_download():
    """
    Inicia una descarga asíncrona.
    Body JSON: {"url": "https://...", "dest_folder": "/ruta/opcional"}
    Retorna: {"job_id": "uuid-..."}
    """
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    custom_dest = (data.get("dest_folder") or "").strip()
    cookies_browser = (data.get("cookies_browser") or "").strip()

    if not url:
        return jsonify({"error": "Falta la URL"}), 400

    # Crear job
    job_id = str(uuid.uuid4())[:12]

    # Carpeta destino: la personalizada (si es válida) o la temporal por defecto
    if custom_dest and os.path.isdir(custom_dest):
        job_folder = custom_dest
        use_custom_dest = True
    else:
        job_folder = os.path.join(DOWNLOADS_BASE, job_id)
        os.makedirs(job_folder, exist_ok=True)
        use_custom_dest = False

    job = {
        "id": job_id,
        "url": url,
        "folder": job_folder,
        "queue": Queue(),         # Cola de mensajes SSE
        "status": "running",      # running | done | error | stopped
        "files": [],              # Archivos descargados
        "created_at": time.time(),
        "stop_requested": False,  # Señal de parada
        "custom_dest": use_custom_dest,
        "cookies_browser": cookies_browser,
    }
    _jobs[job_id] = job

    # Lanzar descarga en hilo
    thread = threading.Thread(
        target=_download_worker,
        args=(job,),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/stop/<job_id>", methods=["POST"])
def api_stop_download(job_id: str):
    """Solicita la parada de un job en curso."""
    job = _jobs.get(job_id)
    if not job:
        abort(404)

    job["stop_requested"] = True
    return jsonify({"ok": True, "message": "Parada solicitada"})


@app.route("/api/upload-cookies", methods=["POST"])
def api_upload_cookies():
    """
    Sube un archivo cookies.txt (formato Netscape) para que yt-dlp
    pueda autenticarse en YouTube y evitar la detección de bots.
    """
    if "file" not in request.files:
        return jsonify({"error": "No se envió ningún archivo"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Archivo vacío"}), 400

    f.save(COOKIES_FILE)
    return jsonify({"ok": True, "message": "Cookies guardadas correctamente"})


@app.route("/api/cookies-status")
def api_cookies_status():
    """Devuelve si hay un archivo de cookies guardado."""
    exists = os.path.isfile(COOKIES_FILE)
    return jsonify({"has_cookies": exists})


@app.route("/api/delete-cookies", methods=["POST"])
def api_delete_cookies():
    """Elimina el archivo de cookies guardado."""
    if os.path.isfile(COOKIES_FILE):
        os.remove(COOKIES_FILE)
    return jsonify({"ok": True})


@app.route("/api/browse-folder", methods=["POST"])
def api_browse_folder():
    """
    Abre el explorador de archivos nativo (tkinter) para seleccionar
    una carpeta. Solo funciona cuando el servidor corre en local.
    Retorna: {"folder": "C:\\Users\\...\\Music"} o {"folder": ""}
    """
    selected = _open_folder_dialog()
    return jsonify({"folder": selected or ""})


def _open_folder_dialog() -> str:
    """Abre un diálogo nativo de selección de carpeta usando tkinter."""
    result = {"path": ""}

    def _run():
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()            # Ocultar ventana principal
            root.attributes("-topmost", True)  # Traer al frente
            folder = filedialog.askdirectory(
                title="Seleccionar Carpeta / Pendrive",
            )
            result["path"] = folder or ""
            root.destroy()
        except Exception:
            result["path"] = ""

    # tkinter necesita correr en un hilo separado si Flask corre en otro
    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=120)  # Máximo 2 minutos para que el usuario elija
    return result["path"]


@app.route("/api/stream/<job_id>")
def api_stream(job_id: str):
    """
    Endpoint SSE — envía los mensajes de log en tiempo real.
    El frontend se conecta aquí con EventSource.
    """
    job = _jobs.get(job_id)
    if not job:
        abort(404)

    def event_stream():
        while True:
            try:
                msg = job["queue"].get(timeout=30)
            except Empty:
                # Enviar keepalive para mantener la conexión
                yield ":\n\n"
                continue

            if msg is None:
                # Señal de fin
                yield f"event: done\ndata: {job['status']}\n\n"
                break

            # Escapar saltos de línea para SSE
            safe = msg.replace("\n", "\\n")
            yield f"data: {safe}\n\n"

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/files/<job_id>")
def api_list_files(job_id: str):
    """Lista los archivos descargados de un job."""
    job = _jobs.get(job_id)
    if not job:
        abort(404)

    files = []
    for f in job.get("files", []):
        if os.path.exists(f):
            files.append({
                "name": os.path.basename(f),
                "size_mb": round(os.path.getsize(f) / (1024 * 1024), 2),
            })
    return jsonify({"files": files, "status": job["status"]})


@app.route("/api/download-file/<job_id>/<filename>")
def api_download_file(job_id: str, filename: str):
    """Descarga un archivo individual al navegador del usuario."""
    job = _jobs.get(job_id)
    if not job:
        abort(404)

    filepath = os.path.join(job["folder"], filename)
    if not os.path.exists(filepath):
        abort(404)

    return send_file(
        filepath,
        as_attachment=True,
        download_name=filename,
    )


@app.route("/api/download-zip/<job_id>")
def api_download_zip(job_id: str):
    """Empaqueta todos los archivos del job en un ZIP y lo envía."""
    job = _jobs.get(job_id)
    if not job or not job.get("files"):
        abort(404)

    zip_path = os.path.join(job["folder"], f"MusicDownloader_{job_id}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in job["files"]:
            if os.path.exists(f):
                zf.write(f, os.path.basename(f))

    return send_file(
        zip_path,
        as_attachment=True,
        download_name=f"MusicDownloader_{job_id}.zip",
    )


# ═══════════════════════════════════════════════════════════════════════
# WORKER DE DESCARGA (corre en hilo)
# ═══════════════════════════════════════════════════════════════════════

def _download_worker(job: dict):
    """Ejecuta la cadena completa de descarga."""
    q: Queue = job["queue"]
    url = job["url"]
    dest = job["folder"]

    # Cookies: archivo subido o leer del navegador configurado
    cookies_file = COOKIES_FILE if os.path.isfile(COOKIES_FILE) else ""
    cookies_browser = job.get("cookies_browser", "")  # ej: "chrome", "firefox", "edge"

    def log(msg: str):
        q.put(msg)

    try:
        tracks = []

        # ── 1. Analizar URL ────────────────────────────────────────
        if is_spotify_url(url):
            log("🔗 Enlace de Spotify detectado — Extrayendo metadatos…")
            try:
                tracks = get_tracks_from_spotify_url(
                    url,
                    client_id=SPOTIFY_CLIENT_ID,
                    client_secret=SPOTIFY_CLIENT_SECRET,
                )
            except Exception as e:
                log(f"❌ Error Spotify: {e}")
                log("↪ Se intentará con yt-dlp directamente…")
                tracks = [{
                    "title": "Desconocido",
                    "artist": "Desconocido",
                    "album": "",
                    "track_number": 0,
                    "cover_url": "",
                    "isrc": None,
                    "youtube_url": url,
                }]

        elif is_youtube_url(url):
            log("🔗 Enlace de YouTube detectado…")
            try:
                tracks = get_youtube_info(url, cookies_file=cookies_file, cookies_from_browser=cookies_browser)
            except Exception as e:
                log(f"❌ Error YouTube: {e}")
                tracks = [{
                    "title": "Desconocido",
                    "artist": "Desconocido",
                    "album": "",
                    "track_number": 0,
                    "cover_url": "",
                    "isrc": None,
                    "youtube_url": url,
                }]
        else:
            log("🔗 URL genérica — se pasará a yt-dlp.")
            tracks = [{
                "title": "Desconocido",
                "artist": "Desconocido",
                "album": "",
                "track_number": 0,
                "cover_url": "",
                "isrc": None,
                "youtube_url": url,
            }]

        if not tracks:
            log("⚠️ No se encontraron canciones.")
            job["status"] = "error"
            q.put(None)
            return

        total = len(tracks)
        log(f"📋 {total} canción(es) en cola.\n")

        # ── 2. Descargar cada pista ────────────────────────────────
        ok = 0
        fail = 0
        for i, track in enumerate(tracks, 1):
            # ── Comprobar parada solicitada ──
            if job.get("stop_requested"):
                log("\n⛔ Descarga detenida por el usuario.")
                job["status"] = "stopped"
                break

            label = f"{track.get('artist', '?')} — {track.get('title', '?')}"
            log(f"── [{i}/{total}] {label} ──")

            try:
                result = download_track(
                    title=track.get("title", "Unknown"),
                    artist=track.get("artist", "Unknown"),
                    album=track.get("album", ""),
                    dest_folder=dest,
                    cover_url=track.get("cover_url", ""),
                    track_number=track.get("track_number", 0),
                    isrc=track.get("isrc"),
                    youtube_url=track.get("youtube_url"),
                    deezer_arl=DEEZER_ARL,
                    slskd_api_url=SLSKD_API_URL,
                    slskd_api_key=SLSKD_API_KEY,
                    log_callback=log,
                    cookies_file=cookies_file,
                    cookies_from_browser=cookies_browser,
                )
                if result and os.path.exists(result):
                    job["files"].append(result)
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                log(f"❌ Error: {e}")
                fail += 1

        # ── 3. Resumen ────────────────────────────────────────────
        if job["status"] != "stopped":
            log(f"\n🏁 Listo — ✅ {ok}/{total}" + (f"  ❌ {fail} errores" if fail else ""))
            job["status"] = "done" if ok > 0 else "error"
        else:
            log(f"\n🏁 Detenido — ✅ {ok} descargado(s)")

        # Si el usuario eligió carpeta personalizada, indicar ruta
        if job.get("custom_dest") and ok > 0:
            log(f"📂 Archivos guardados en: {dest}")

    except Exception as e:
        log(f"\n❌ Error crítico: {e}")
        job["status"] = "error"

    finally:
        q.put(None)  # Señal de fin para SSE


# ═══════════════════════════════════════════════════════════════════════
# LIMPIEZA PERIÓDICA (elimina jobs viejos > 1 hora)
# ═══════════════════════════════════════════════════════════════════════

def _cleanup_old_jobs():
    """Elimina carpetas de descargas con más de 1 hora."""
    while True:
        time.sleep(600)  # Cada 10 minutos
        now = time.time()
        to_delete = []
        for jid, job in list(_jobs.items()):
            if now - job.get("created_at", now) > 3600:
                to_delete.append(jid)

        for jid in to_delete:
            job = _jobs.pop(jid, None)
            if job and os.path.isdir(job.get("folder", "")):
                try:
                    shutil.rmtree(job["folder"])
                except Exception:
                    pass


# Lanzar limpieza en hilo daemon
threading.Thread(target=_cleanup_old_jobs, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  🎵 Music Downloader Web")
    print("  Abrir: http://localhost:5000")
    print("=" * 60)
    print()
    # debug=False para producción; threaded=True para manejar SSE + descargas
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
