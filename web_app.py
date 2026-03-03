# ============================================================================
# web_app.py — Servidor web con interfaz responsive (Flask + SocketIO)
# ============================================================================
#  ESTRATEGIA: crear Flask app + registrar rutas INMEDIATAMENTE,
#  y diferir los imports pesados (downloader, spotify, deezer) a cuando
#  se necesiten.  Así la web SIEMPRE responde aunque algo falle al importar.
# ============================================================================

import os
import sys
import socket
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO

print(f"[boot] Python {sys.version}", flush=True)
print(f"[boot] CWD = {os.getcwd()}", flush=True)

# ── Flask App (se crea PRIMERO, antes de cualquier import pesado) ──
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "music-dl-2024")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

print("[boot] Flask + SocketIO creados OK", flush=True)

# ── Estado global ──────────────────────────────────────────────────
DEFAULT_FOLDER = str(Path.home() / "Music" / "MusicDownloader")
SERVER_TEMP = str(Path(tempfile.gettempdir()) / "MusicDownloaderTemp")
os.makedirs(SERVER_TEMP, exist_ok=True)

state = {
    "downloading": False,
    "stop_requested": False,
    "dest_folder": DEFAULT_FOLDER,
    "to_device": False,
}

# ── Imports pesados diferidos ──────────────────────────────────────
_heavy_modules = {}          # cache de modulos cargados
_import_error = None         # primer error de import, si hubo


def _load_heavy():
    """Importa downloader, spotify_utils, config la primera vez que se llaman."""
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


def log_to_client(message: str):
    socketio.emit("log", {"message": message})


# ── Rutas (registradas SIEMPRE) ───────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    loaded = bool(_heavy_modules)
    return jsonify({"status": "ok", "modules_loaded": loaded, "error": _import_error})


@app.route("/api/status")
def api_status():
    return jsonify({
        "downloading": state["downloading"],
        "dest_folder": state["dest_folder"],
        "modules_loaded": bool(_heavy_modules),
        "import_error": _import_error,
    })


@app.route("/api/set_folder", methods=["POST"])
def api_set_folder():
    data = request.json or {}
    folder = data.get("folder", "").strip()
    if folder:
        state["dest_folder"] = folder
        return jsonify({"ok": True, "folder": folder})
    return jsonify({"ok": False, "error": "Carpeta vacía"}), 400


@app.route("/api/download", methods=["POST"])
def api_download():
    if not _load_heavy():
        return jsonify({"ok": False, "error": f"Módulos no disponibles: {_import_error}"}), 500

    if state["downloading"]:
        return jsonify({"ok": False, "error": "Ya hay una descarga en curso."}), 409

    data = request.json or {}
    url = data.get("url", "").strip()
    folder = data.get("folder", "").strip()

    if not url:
        return jsonify({"ok": False, "error": "URL vacía."}), 400

    if folder:
        state["dest_folder"] = folder

    state["to_device"] = True
    actual_folder = SERVER_TEMP
    os.makedirs(actual_folder, exist_ok=True)

    state["downloading"] = True
    state["stop_requested"] = False

    thread = threading.Thread(
        target=_download_worker,
        args=(url, actual_folder),
        daemon=True,
    )
    thread.start()

    return jsonify({"ok": True, "message": "Descarga iniciada."})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    if state["downloading"]:
        state["stop_requested"] = True
        log_to_client("⚠️ Deteniendo tras la canción actual...")
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "No hay descarga en curso."}), 400


@app.route("/api/download_file/<path:filename>")
def api_download_file(filename):
    for folder in [state["dest_folder"], SERVER_TEMP]:
        full_path = os.path.join(folder, filename)
        if os.path.isfile(full_path):
            return send_from_directory(folder, filename, as_attachment=True)
    return jsonify({"error": "Archivo no encontrado"}), 404


@app.route("/api/download_zip/<path:filename>")
def api_download_zip(filename):
    full_path = os.path.join(SERVER_TEMP, filename)
    if os.path.isfile(full_path):
        return send_from_directory(SERVER_TEMP, filename, as_attachment=True)
    return jsonify({"error": "ZIP no encontrado"}), 404


# ── Worker de descarga ─────────────────────────────────────────────
def _download_worker(url: str, dest: str):
    m = _heavy_modules  # alias corto
    try:
        socketio.emit("download_started")
        log_to_client("🚀 Descargando...")

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
                log_to_client(f"❌ Error Spotify: {e}")
                return

        elif m["is_youtube_url"](url):
            try:
                tracks = m["get_youtube_info"](url)
            except Exception as e:
                log_to_client(f"❌ Error YouTube: {e}")
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
            log_to_client("❌ No se encontraron canciones.")
            return

        total = len(tracks)
        success = 0
        fail = 0

        for i, track in enumerate(tracks, 1):
            if state["stop_requested"]:
                log_to_client(f"\n⛔ Detenida por el usuario ({i-1}/{total}).")
                break

            socketio.emit("progress", {"current": i, "total": total})

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
                log_callback=log_to_client,
            )

            if result:
                success += 1
                session_files.append(result)
                import shutil
                dst_folder = state["dest_folder"]
                os.makedirs(dst_folder, exist_ok=True)
                dst_path = os.path.join(dst_folder, os.path.basename(result))
                try:
                    shutil.copy2(result, dst_path)
                except Exception:
                    pass
                filename = os.path.basename(result)
                socketio.emit("file_ready", {"filename": filename})
            else:
                fail += 1

        log_to_client(
            f"\n🏁 Listo — ✅ {success}/{total}"
            + (f" ❌ {fail}" if fail else "")
        )

        if success == 1 and session_files:
            socketio.emit("batch_complete", {
                "count": 1,
                "single_filename": os.path.basename(session_files[0]),
            })
        elif success > 1 and session_files:
            zip_name = f"music_{int(time.time())}.zip"
            zip_path = os.path.join(SERVER_TEMP, zip_name)
            try:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
                    for fpath in session_files:
                        zf.write(fpath, os.path.basename(fpath))
                log_to_client(f"📦 ZIP creado con {success} canciones")
                socketio.emit("batch_complete", {
                    "count": success,
                    "zip_filename": zip_name,
                })
            except Exception as ze:
                log_to_client(f"⚠️ No se pudo crear ZIP: {ze}")

    except Exception as e:
        log_to_client(f"\n❌ Error crítico: {e}")
        import traceback
        log_to_client(traceback.format_exc())

    finally:
        state["downloading"] = False
        state["stop_requested"] = False
        socketio.emit("download_finished")


# ── Pre-cargar módulos pesados en background ───────────────────────
threading.Thread(target=_load_heavy, daemon=True).start()

# ── Punto de entrada (solo dev local) ──────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"  [DEV] Starting on 0.0.0.0:{port} ...", flush=True)
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
