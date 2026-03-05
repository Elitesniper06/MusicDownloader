# MusicDownloader Web - Deploy

This repository now includes a web version that keeps the same download pipeline:

- Input URL: Spotify, YouTube, or YouTube Music
- Track extraction from Spotify/YouTube metadata
- Plan A: Deezer/Soulseek (when configured)
- Plan B fallback: yt-dlp
- Real-time job logs
- Final ZIP download for end users

## 1) Local run

```bash
pip install -r requirements.txt
python web_app.py
```

Open `http://localhost:5000`.

## 2) Production config

Set these environment variables in your hosting provider:

- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `DEEZER_ARL` (optional)
- `SLSKD_API_URL` (optional)
- `SLSKD_API_KEY` (optional)
- `JOB_TTL_SECONDS` (optional, default `21600`)
- `MAX_TRACKS_PER_JOB` (optional, default `250`)
- `MAX_LOG_LINES` (optional, default `600`)

Do not commit real secrets. Use `config.py.example` only as template.

## 3) Render deploy

This project includes:

- `render.yaml`
- `build.sh`
- Start command: `gunicorn web_app:app`

Deploy steps:

1. Push this repo to GitHub.
2. In Render, create a **Blueprint** from the repo.
3. Set secret env vars in Render dashboard.
4. Deploy.

## 4) Important runtime notes

- Soulseek (`slskd`) usually runs in private/local networks. In public cloud hosts it may not be reachable unless you expose it securely.
- Jobs are stored in server disk temporarily (`tmp_downloads`) and auto-cleaned after TTL.
- Heavy traffic requires rate limiting and persistent queue/storage (Redis + worker) for production scale.
