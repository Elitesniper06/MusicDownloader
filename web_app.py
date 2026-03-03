# ============================================================================
# web_app.py — Servidor web con interfaz responsive (Flask + SocketIO)
# ============================================================================
#  - Imports pesados diferidos (Flask siempre responde)
#  - Sesiones aisladas por usuario (cada uno ve solo sus descargas)
# ============================================================================

import os
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO

print(f"[boot] Python {sys.version}", flush=True)
print(f"[boot] CWD = {os.getcwd()}", flush=True)

# ── Flask App ──────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "music-dl-2024")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

print("[boot] Flask + SocketIO creados OK", flush=True)

# ── Directorios ────────────────────────────────────────────────────
SERVER_TEMP = str(Path(tempfile.gettempdir()) / "MusicDownloaderTemp")
os.makedirs(SERVER_TEMP, exist_ok=True)

# ── Estado POR SESIÓN ──────────────────────────────────────────────
# Cada Socket.IO sid tiene su propio estado aislado
_sessions = {}   # { sid: { downloading, stop_requested, temp_dir } }
_sessions_lock = threading.Lock()


def _get_session(sid: str) -> dict:
    """Obtiene o crea el estado de una sesión."""
    with _sessions_lock:
        if sid not in _sessions:
            sess_dir = os.path.join(SERVER_TEMP, sid.replace("/", "_"))
            os.makedirs(sess_dir, exist_ok=True)
            _sessions[sid] = {
                "downloading": False,
                "stop_requested": False,
                "temp_dir": sess_dir,
            }
        return _sessions[sid]


def _remove_session(sid: str):
    with _sessions_lock:
        _sessions.pop(sid, None)


# ── Imports pesados diferidos ──────────────────────────────────────
_heavy_modules = {}
_import_error = None


def _load_heavy():
    global _import_error
    if _import_error:
        return False
    if _heavy_modules:
        return True
    try:
        from config import (
            SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET,
            DEEZER_ARL, SLSKD_API_URL, SLSKD_API_KEY,
        )
        from spotify_utils import is_spotify_url, get_tracks_from_spotify_url
        from downloader import download_track, is_youtube_url, get_youtube_info

        _heavy_modules.update({
            "SPOTIFY_CLIENT_ID": SPOTIFY_CLIENT_ID,
            "SPOTIFY_CLIENT_SECRET": SPOTIFY_CLIENT_SECRET,
            "DEEZER_ARL": DEEZER_ARL,
            "SLSKD_API_URL": SLSKD_API_URL,
            "SLSKD_API_KEY": SLSKD_API_KEY,
            "is_spotify_url": is_spotify_url,
            "get_tracks_from_spotify_url": get_tracks_from_spotify_url,
            "download_track": download_track,
            "is_youtube_url": is_youtube_url,
            "get_youtube_info": get_youtube_info,
        })
        print("[boot] Heavy modules loaded OK", flush=True)
        return True
    except Exception as exc:
        _import_error = str(exc)
        import traceback
        traceback.print_exc()
        print(f"[boot] HEAVY IMPORT FAILED: {exc}", flush=True)
        return False


def _log_to(sid: str, message: str):
    """Envía log SOLO al usuario con este sid."""
    socketio.emit("log", {"message": message}, to=sid)


# ── SocketIO events ───────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    sid = request.sid
    _get_session(sid)
    print(f"[ws] Connected: {sid}", flush=True)


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    sess = _get_session(sid)
    sess["stop_requested"] = True
    _remove_session(sid)
    print(f"[ws] Disconnected: {sid}", flush=True)


# ── Rutas HTTP ─────────────────────────────────────────────────────
@app.errorhandler(404)
def handle_404(e):
    return jsonify({"error": "Not Found", "path": request.path}), 404


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "modules_loaded": bool(_heavy_modules),
        "error": _import_error,
    })


@app.route("/api/status")
def api_status():
    return jsonify({
        "modules_loaded": bool(_heavy_modules),
        "import_error": _import_error,
        "active_sessions": len(_sessions),
    })


# ── SocketIO actions (llamadas desde el cliente JS) ───────────────
@socketio.on("start_download")
def handle_start_download(data):
    """El cliente pide iniciar descarga. Data = { url: str }."""
    sid = request.sid
    sess = _get_session(sid)

    if not _load_heavy():
        _log_to(sid, f"❌ Módulos no disponibles: {_import_error}")
        return

    if sess["downloading"]:
        _log_to(sid, "⚠️ Ya tienes una descarga en curso.")
        return

    url = (data or {}).get("url", "").strip()
    if not url:
        _log_to(sid, "❌ URL vacía.")
        return

    sess["downloading"] = True
    sess["stop_requested"] = False

    thread = threading.Thread(
        target=_download_worker,
        args=(sid, url, sess),
        daemon=True,
    )
    thread.start()


@socketio.on("stop_download")
def handle_stop_download():
    sid = request.sid
    sess = _get_session(sid)
    if sess["downloading"]:
        sess["stop_requested"] = True
        _log_to(sid, "⚠️ Deteniendo tras la canción actual...")


# ── Rutas de descarga de archivos ─────────────────────────────────
@app.route("/api/download_file/<path:filename>")
def api_download_file(filename):
    """Busca el archivo en cualquier carpeta de sesión."""
    for sid_dir in _iter_session_dirs():
        full = os.path.join(sid_dir, filename)
        if os.path.isfile(full):
            return send_from_directory(sid_dir, filename, as_attachment=True)
    full = os.path.join(SERVER_TEMP, filename)
    if os.path.isfile(full):
        return send_from_directory(SERVER_TEMP, filename, as_attachment=True)
    return jsonify({"error": "Archivo no encontrado"}), 404


@app.route("/api/download_zip/<path:filename>")
def api_download_zip(filename):
    for sid_dir in _iter_session_dirs():
        full = os.path.join(sid_dir, filename)
        if os.path.isfile(full):
            return send_from_directory(sid_dir, filename, as_attachment=True)
    full = os.path.join(SERVER_TEMP, filename)
    if os.path.isfile(full):
        return send_from_directory(SERVER_TEMP, filename, as_attachment=True)
    return jsonify({"error": "ZIP no encontrado"}), 404


def _iter_session_dirs():
    """Devuelve todos los directorios de sesión activos."""
    with _sessions_lock:
        return [s["temp_dir"] for s in _sessions.values()]


# ── Worker de descarga (aislado por sid) ───────────────────────────
def _download_worker(sid: str, url: str, sess: dict):
    m = _heavy_modules
    dest = sess["temp_dir"]
    log = lambda msg: _log_to(sid, msg)

    try:
        socketio.emit("download_started", to=sid)
        log("🚀 Descargando...")

        tracks = []
        session_files = []

        if m["is_spotify_url"](url):
            try:
                tracks = m["get_tracks_from_spotify_url"](
                    url,
                    client_id=m["SPOTIFY_CLIENT_ID"],
                    client_secret=m["SPOTIFY_CLIENT_SECRET"],
                )
            except Exception as e:
                log(f"❌ Error Spotify: {e}")
                return

        elif m["is_youtube_url"](url):
            try:
                tracks = m["get_youtube_info"](url)
            except Exception as e:
                log(f"❌ Error YouTube: {e}")
                return

        else:
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
            log("❌ No se encontraron canciones.")
            return

        total = len(tracks)
        success = 0
        fail = 0

        for i, track in enumerate(tracks, 1):
            if sess["stop_requested"]:
                log(f"\n⛔ Detenida por el usuario ({i-1}/{total}).")
                break

            socketio.emit("progress", {"current": i, "total": total}, to=sid)

            result = m["download_track"](
                title=track.get("title", "Unknown"),
                artist=track.get("artist", "Unknown"),
                album=track.get("album", ""),
                dest_folder=dest,
                cover_url=track.get("cover_url", ""),
                track_number=track.get("track_number", 0),
                isrc=track.get("isrc"),
                youtube_url=track.get("youtube_url"),
                deezer_arl=m["DEEZER_ARL"],
                slskd_api_url=m["SLSKD_API_URL"],
                slskd_api_key=m["SLSKD_API_KEY"],
                log_callback=log,
            )

            if result:
                success += 1
                session_files.append(result)
                filename = os.path.basename(result)
                socketio.emit("file_ready", {"filename": filename}, to=sid)
            else:
                fail += 1

        log(
            f"\n🏁 Listo — ✅ {success}/{total}"
            + (f" ❌ {fail}" if fail else "")
        )

        if success == 1 and session_files:
            socketio.emit("batch_complete", {
                "count": 1,
                "single_filename": os.path.basename(session_files[0]),
            }, to=sid)
        elif success > 1 and session_files:
            zip_name = f"music_{int(time.time())}.zip"
            zip_path = os.path.join(dest, zip_name)
            try:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
                    for fpath in session_files:
                        zf.write(fpath, os.path.basename(fpath))
                log(f"📦 ZIP creado con {success} canciones")
                socketio.emit("batch_complete", {
                    "count": success,
                    "zip_filename": zip_name,
                }, to=sid)
            except Exception as ze:
                log(f"⚠️ No se pudo crear ZIP: {ze}")

    except Exception as e:
        log(f"\n❌ Error crítico: {e}")
        import traceback
        log(traceback.format_exc())

    finally:
        sess["downloading"] = False
        sess["stop_requested"] = False
        socketio.emit("download_finished", to=sid)


# ── Pre-cargar módulos pesados en background ───────────────────────
threading.Thread(target=_load_heavy, daemon=True).start()

# ── Punto de entrada ──────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[boot] Starting on 0.0.0.0:{port} ...", flush=True)
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
