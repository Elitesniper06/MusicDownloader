import os
import shutil
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file

from downloader import download_track, get_youtube_info, is_youtube_url
from settings import (
    DEEZER_ARL,
    DOWNLOAD_WORKDIR,
    JOB_TTL_SECONDS,
    MAX_LOG_LINES,
    MAX_TRACKS_PER_JOB,
    PORT,
    SLSKD_API_KEY,
    SLSKD_API_URL,
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
)
from spotify_utils import get_tracks_from_spotify_url, is_spotify_url

BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / DOWNLOAD_WORKDIR
WORK_DIR.mkdir(parents=True, exist_ok=True)

AUDIO_EXTENSIONS = {".m4a", ".opus", ".ogg", ".webm", ".mp3", ".flac", ".wav"}


@dataclass
class DownloadJob:
    id: str
    url: str
    status: str = "queued"
    created_at: str = field(default_factory=lambda: _utc_now())
    finished_at: str = ""
    stop_requested: bool = False
    total_tracks: int = 0
    processed_tracks: int = 0
    success_count: int = 0
    fail_count: int = 0
    logs: list[str] = field(default_factory=list)
    work_dir: str = ""
    zip_path: str = ""
    completed_files: list[str] = field(default_factory=list)


app = Flask(__name__)
_jobs_lock = threading.RLock()
_jobs: dict[str, DownloadJob] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _add_log(job: DownloadJob, message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    with _jobs_lock:
        job.logs.append(f"[{timestamp}] {message}")
        if len(job.logs) > MAX_LOG_LINES:
            job.logs[:] = job.logs[-MAX_LOG_LINES:]


def _resolve_tracks(url: str) -> list[dict]:
    if is_spotify_url(url):
        return get_tracks_from_spotify_url(
            url,
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
        )

    if is_youtube_url(url):
        return get_youtube_info(url)

    return [
        {
            "title": "Unknown",
            "artist": "Unknown",
            "album": "",
            "track_number": 0,
            "cover_url": "",
            "isrc": None,
            "youtube_url": url,
        }
    ]


def _list_audio_files(folder: Path) -> list[Path]:
    files: list[Path] = []
    for file_path in folder.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in AUDIO_EXTENSIONS:
            files.append(file_path)
    return sorted(files)


def _create_zip(files: list[Path], destination_zip: Path) -> None:
    with zipfile.ZipFile(destination_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zipf:
        for file_path in files:
            zipf.write(file_path, arcname=file_path.name)


def _run_job(job_id: str) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.status = "running"

    _add_log(job, f"Starting download for URL: {job.url}")

    try:
        tracks_to_download = _resolve_tracks(job.url)
        if not tracks_to_download:
            _add_log(job, "No tracks were found for this URL.")
            with _jobs_lock:
                job.status = "failed"
            return

        if len(tracks_to_download) > MAX_TRACKS_PER_JOB:
            _add_log(
                job,
                f"Track list capped to {MAX_TRACKS_PER_JOB} items for this job.",
            )
            tracks_to_download = tracks_to_download[:MAX_TRACKS_PER_JOB]

        with _jobs_lock:
            job.total_tracks = len(tracks_to_download)

        output_dir = Path(job.work_dir) / "downloads"
        output_dir.mkdir(parents=True, exist_ok=True)

        for index, track in enumerate(tracks_to_download, start=1):
            with _jobs_lock:
                if job.stop_requested:
                    job.status = "cancelled"
                    _add_log(job, "Cancellation requested by user.")
                    break

            _add_log(
                job,
                f"Processing track {index}/{len(tracks_to_download)}: "
                f"{track.get('artist', 'Unknown')} - {track.get('title', 'Unknown')}",
            )

            result_path = download_track(
                title=track.get("title", "Unknown"),
                artist=track.get("artist", "Unknown"),
                album=track.get("album", ""),
                dest_folder=str(output_dir),
                cover_url=track.get("cover_url", ""),
                track_number=track.get("track_number", 0),
                isrc=track.get("isrc"),
                youtube_url=track.get("youtube_url"),
                deezer_arl=DEEZER_ARL,
                slskd_api_url=SLSKD_API_URL,
                slskd_api_key=SLSKD_API_KEY,
                log_callback=lambda msg: _add_log(job, msg),
            )

            with _jobs_lock:
                job.processed_tracks += 1
                if result_path:
                    job.success_count += 1
                    job.completed_files.append(os.path.basename(result_path))
                else:
                    job.fail_count += 1

        audio_files = _list_audio_files(output_dir)
        if audio_files:
            zip_path = Path(job.work_dir) / "music.zip"
            _create_zip(audio_files, zip_path)
            with _jobs_lock:
                job.zip_path = str(zip_path)
            _add_log(job, f"ZIP package created with {len(audio_files)} file(s).")
        else:
            _add_log(job, "No output audio files found to package.")

        with _jobs_lock:
            if job.status == "running":
                job.status = "completed" if job.success_count > 0 else "failed"

    except Exception as exc:
        _add_log(job, f"Critical error: {exc}")
        with _jobs_lock:
            job.status = "failed"

    finally:
        with _jobs_lock:
            job.finished_at = _utc_now()


def _cleanup_loop() -> None:
    while True:
        time.sleep(300)
        now = time.time()

        with _jobs_lock:
            removable_ids = []
            for job_id, job in _jobs.items():
                if not job.finished_at:
                    continue

                try:
                    finished_epoch = datetime.fromisoformat(job.finished_at).timestamp()
                except Exception:
                    finished_epoch = now

                if now - finished_epoch > JOB_TTL_SECONDS:
                    removable_ids.append(job_id)

            for job_id in removable_ids:
                job = _jobs.pop(job_id)
                try:
                    shutil.rmtree(job.work_dir, ignore_errors=True)
                except Exception:
                    pass


@app.get("/")
def index() -> Response:
    html = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>MusicDownloader Web</title>
  <style>
    :root {
      --bg0: #faf5ef;
      --bg1: #f0e4d5;
      --card: #fffaf2;
      --ink: #1d1f21;
      --muted: #5f6368;
      --accent: #14532d;
      --accent-2: #b45309;
      --danger: #b91c1c;
      --line: #d6c8b8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: "Trebuchet MS", "Segoe UI", sans-serif;
      background: radial-gradient(circle at 10% 10%, var(--bg1), var(--bg0) 55%);
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 16px;
    }
    .shell {
      width: min(980px, 100%);
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 20px 60px rgba(17, 24, 39, 0.12);
      overflow: hidden;
    }
    header {
      padding: 22px;
      background: linear-gradient(120deg, #f4e3cb, #e4f5e7);
      border-bottom: 1px solid var(--line);
    }
    h1 {
      margin: 0;
      font-size: clamp(24px, 4vw, 36px);
      letter-spacing: 0.3px;
    }
    header p {
      margin: 8px 0 0;
      color: var(--muted);
    }
    main { padding: 20px; display: grid; gap: 16px; }
    .row { display: grid; gap: 10px; }
    .controls {
      display: grid;
      grid-template-columns: 1fr auto auto;
      gap: 10px;
    }
    input[type=text] {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px 14px;
      background: white;
      font-size: 14px;
    }
    button {
      border: 0;
      border-radius: 12px;
      padding: 12px 16px;
      cursor: pointer;
      font-weight: 700;
    }
    #startBtn { background: var(--accent); color: white; }
    #cancelBtn { background: var(--danger); color: white; }
    #cancelBtn[disabled], #startBtn[disabled] { opacity: .5; cursor: not-allowed; }
    .stats {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }
    .chip {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: white;
      padding: 10px;
      text-align: center;
    }
    .chip .k { color: var(--muted); font-size: 12px; }
    .chip .v { font-size: 18px; margin-top: 4px; }
    .progress {
      height: 10px;
      background: #efe7dc;
      border-radius: 999px;
      overflow: hidden;
      border: 1px solid var(--line);
    }
    .progress > span {
      display: block;
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
      transition: width .35s ease;
    }
    pre {
      margin: 0;
      min-height: 260px;
      max-height: 360px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
      background: #111827;
      color: #d1d5db;
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
      line-height: 1.4;
    }
    .actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    a.download {
      display: inline-block;
      background: #1e3a8a;
      color: white;
      text-decoration: none;
      border-radius: 10px;
      padding: 10px 14px;
      font-weight: 700;
    }
    #statusText { color: var(--muted); font-weight: 600; }
    #folderBtn { background: #4338ca; color: white; }
    #folderBtn.active { background: #16a34a; }
    #autoBtn { background: #0369a1; color: white; }
    #autoBtn.active { background: #16a34a; }
    @media (max-width: 900px) {
      .controls { grid-template-columns: 1fr; }
      .stats { grid-template-columns: 1fr 1fr; }
    }
  </style>
</head>
<body>
  <div class=\"shell\">
    <header>
      <h1>MusicDownloader Web</h1>
      <p>Public URL downloads with Spotify, YouTube and YouTube Music support.</p>
    </header>
    <main>
      <div class=\"row\">
        <label for=\"urlInput\">Paste Spotify or YouTube URL</label>
        <div class=\"controls\">
          <input id=\"urlInput\" type=\"text\" placeholder=\"https://open.spotify.com/... or https://youtube.com/...\" />
          <button id=\"startBtn\">Start Download</button>
          <button id=\"cancelBtn\" disabled>Cancel</button>
        </div>
      </div>

      <div class=\"row\">
        <div class=\"controls\" style=\"grid-template-columns: auto auto 1fr;\">
          <button id=\"autoBtn\">Auto-download</button>
          <button id=\"folderBtn\">Custom Folder</button>
          <span id=\"folderLabel\" style=\"color: var(--muted); font-size: 13px;\">Click Auto-download to save to your Downloads folder, or Custom Folder for another location</span>
        </div>
      </div>

      <div class=\"stats\">
        <div class=\"chip\"><div class=\"k\">Status</div><div class=\"v\" id=\"statStatus\">idle</div></div>
        <div class=\"chip\"><div class=\"k\">Total</div><div class=\"v\" id=\"statTotal\">0</div></div>
        <div class=\"chip\"><div class=\"k\">Processed</div><div class=\"v\" id=\"statProcessed\">0</div></div>
        <div class=\"chip\"><div class=\"k\">Success</div><div class=\"v\" id=\"statSuccess\">0</div></div>
        <div class=\"chip\"><div class=\"k\">Fail</div><div class=\"v\" id=\"statFail\">0</div></div>
      </div>

      <div class=\"progress\"><span id=\"progressFill\"></span></div>

      <div class=\"actions\">
        <span id=\"statusText\">Ready.</span>
        <a id=\"downloadLink\" class=\"download\" href=\"#\" style=\"display:none\">Download ZIP</a>
      </div>

      <pre id=\"logBox\">No logs yet.</pre>
    </main>
  </div>

  <script>
    const urlInput = document.getElementById("urlInput");
    const startBtn = document.getElementById("startBtn");
    const cancelBtn = document.getElementById("cancelBtn");
    const logBox = document.getElementById("logBox");
    const downloadLink = document.getElementById("downloadLink");
    const statusText = document.getElementById("statusText");

    const statStatus = document.getElementById("statStatus");
    const statTotal = document.getElementById("statTotal");
    const statProcessed = document.getElementById("statProcessed");
    const statSuccess = document.getElementById("statSuccess");
    const statFail = document.getElementById("statFail");
    const progressFill = document.getElementById("progressFill");

    let currentJobId = null;
    let pollHandle = null;
    let dirHandle = null;
    let autoDownload = false;
    const savedFiles = new Set();

    function setBusy(isBusy) {
      startBtn.disabled = isBusy;
      cancelBtn.disabled = !isBusy;
    }

    function setStatusLine(text) {
      statusText.textContent = text;
    }

    function renderJob(job) {
      statStatus.textContent = job.status;
      statTotal.textContent = String(job.totalTracks);
      statProcessed.textContent = String(job.processedTracks);
      statSuccess.textContent = String(job.successCount);
      statFail.textContent = String(job.failCount);

      const pct = job.totalTracks > 0
        ? Math.round((job.processedTracks / job.totalTracks) * 100)
        : 0;
      progressFill.style.width = pct + "%";

      if (job.logs && job.logs.length > 0) {
        logBox.textContent = job.logs.join("\\n");
        logBox.scrollTop = logBox.scrollHeight;
      }

      const done = ["completed", "failed", "cancelled"].includes(job.status);
      if (done) {
        setBusy(false);
        if (pollHandle) {
          clearInterval(pollHandle);
          pollHandle = null;
        }
      }

      if (job.downloadUrl) {
        downloadLink.href = job.downloadUrl;
        downloadLink.style.display = "inline-block";
      } else {
        downloadLink.style.display = "none";
      }

      saveNewFiles(job);

      if (dirHandle) {
        document.getElementById("folderLabel").textContent =
          "Saving to: " + dirHandle.name + " (" + savedFiles.size + " saved)";
      } else if (autoDownload) {
        document.getElementById("folderLabel").textContent =
          "Auto-downloading to browser Downloads (" + savedFiles.size + " saved)";
      }

      setStatusLine("Job " + job.id + " is " + job.status + ".");
    }

    async function pollJob(jobId) {
      try {
        const res = await fetch(`/api/jobs/${jobId}`);
        if (!res.ok) {
          throw new Error("Failed to load job state");
        }
        const data = await res.json();
        renderJob(data);
      } catch (err) {
        setStatusLine(err.message);
      }
    }

    startBtn.addEventListener("click", async () => {
      const url = urlInput.value.trim();
      if (!url) {
        setStatusLine("Please enter a URL first.");
        return;
      }

      setBusy(true);
      savedFiles.clear();
      downloadLink.style.display = "none";
      logBox.textContent = "Preparing job...";
      setStatusLine("Creating job...");

      try {
        const res = await fetch("/api/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url })
        });

        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.error || "Could not create job");
        }

        const data = await res.json();
        currentJobId = data.id;
        setStatusLine("Job created: " + currentJobId);

        await pollJob(currentJobId);
        if (pollHandle) {
          clearInterval(pollHandle);
        }
        pollHandle = setInterval(() => pollJob(currentJobId), 2000);
      } catch (err) {
        setBusy(false);
        setStatusLine(err.message);
      }
    });

    cancelBtn.addEventListener("click", async () => {
      if (!currentJobId) {
        return;
      }
      try {
        await fetch(`/api/jobs/${currentJobId}/cancel`, { method: "POST" });
        setStatusLine("Cancellation requested.");
      } catch (err) {
        setStatusLine("Could not cancel current job.");
      }
    });

    document.getElementById("autoBtn").addEventListener("click", () => {
      autoDownload = !autoDownload;
      dirHandle = null;
      document.getElementById("folderBtn").classList.remove("active");
      if (autoDownload) {
        document.getElementById("autoBtn").classList.add("active");
        document.getElementById("folderLabel").textContent = "Auto-download ON — files save to your Downloads folder";
        document.getElementById("folderLabel").style.color = "var(--accent)";
      } else {
        document.getElementById("autoBtn").classList.remove("active");
        document.getElementById("folderLabel").textContent = "Auto-download OFF";
        document.getElementById("folderLabel").style.color = "var(--muted)";
      }
    });

    document.getElementById("folderBtn").addEventListener("click", async () => {
      if (!window.showDirectoryPicker) {
        setStatusLine("Your browser does not support folder selection. Use Auto-download instead.");
        return;
      }
      try {
        dirHandle = await window.showDirectoryPicker({ mode: "readwrite", startIn: "downloads" });
        autoDownload = false;
        document.getElementById("autoBtn").classList.remove("active");
        document.getElementById("folderBtn").classList.add("active");
        document.getElementById("folderLabel").textContent = "Saving to: " + dirHandle.name;
        document.getElementById("folderLabel").style.color = "var(--accent)";
      } catch (e) { /* user cancelled */ }
    });

    function triggerBrowserDownload(url, filename) {
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }

    async function saveNewFiles(job) {
      if (!job.completedFiles) return;
      if (!dirHandle && !autoDownload) return;
      for (const fname of job.completedFiles) {
        if (savedFiles.has(fname)) continue;
        savedFiles.add(fname);
        const fileUrl = "/api/jobs/" + job.id + "/files/" + encodeURIComponent(fname);
        if (autoDownload) {
          triggerBrowserDownload(fileUrl, fname);
          continue;
        }
        try {
          const resp = await fetch(fileUrl);
          if (!resp.ok) { savedFiles.delete(fname); continue; }
          const blob = await resp.blob();
          const fh = await dirHandle.getFileHandle(fname, { create: true });
          const w = await fh.createWritable();
          await w.write(blob);
          await w.close();
        } catch (e) {
          savedFiles.delete(fname);
        }
      }
    }
  </script>
</body>
</html>
"""
    return Response(html, mimetype="text/html")


@app.post("/api/jobs")
def create_job():
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or "").strip()
    if not url:
        return jsonify({"error": "URL is required."}), 400

    job_id = uuid.uuid4().hex
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    job = DownloadJob(id=job_id, url=url, work_dir=str(job_dir))
    _add_log(job, "Job queued.")

    with _jobs_lock:
        _jobs[job_id] = job

    worker = threading.Thread(target=_run_job, args=(job_id,), daemon=True)
    worker.start()

    return jsonify({"id": job.id, "status": job.status}), 201


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404

        download_url = f"/download/{job.id}" if job.zip_path and os.path.exists(job.zip_path) else ""

        return jsonify(
            {
                "id": job.id,
                "url": job.url,
                "status": job.status,
                "createdAt": job.created_at,
                "finishedAt": job.finished_at,
                "totalTracks": job.total_tracks,
                "processedTracks": job.processed_tracks,
                "successCount": job.success_count,
                "failCount": job.fail_count,
                "logs": list(job.logs),
                "downloadUrl": download_url,
                "completedFiles": list(job.completed_files),
            }
        )


@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        if job.status in {"completed", "failed", "cancelled"}:
            return jsonify({"status": job.status}), 200

        job.stop_requested = True

    return jsonify({"status": "cancelling"}), 202


@app.get("/download/<job_id>")
def download_zip(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job or not job.zip_path:
            abort(404)
        zip_path = job.zip_path

    if not os.path.exists(zip_path):
        abort(404)

    return send_file(
        zip_path,
        as_attachment=True,
        download_name=f"music-{job_id[:8]}.zip",
        mimetype="application/zip",
    )


@app.get("/api/jobs/<job_id>/files/<filename>")
def get_file(job_id: str, filename: str):
    if os.sep in filename or "/" in filename or ".." in filename:
        abort(400)
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            abort(404)
        work_dir = job.work_dir
    file_path = os.path.join(work_dir, "downloads", filename)
    if not os.path.isfile(file_path):
        abort(404)
    return send_file(file_path, as_attachment=True, download_name=filename)


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


_cleanup_thread = threading.Thread(target=_cleanup_loop, daemon=True)
_cleanup_thread.start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
