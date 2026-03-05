"""App settings loaded from environment variables with optional local fallback."""

import os

try:
    import config as _local_config
except Exception:  # pragma: no cover - local file is optional
    _local_config = None


def _get_setting(name: str, default: str = "") -> str:
    """Read setting from env var first, then optional local config.py."""
    value = os.getenv(name)
    if value is not None:
        return value

    if _local_config is not None:
        return getattr(_local_config, name, default)

    return default


SPOTIFY_CLIENT_ID = _get_setting("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = _get_setting("SPOTIFY_CLIENT_SECRET")
DEEZER_ARL = _get_setting("DEEZER_ARL")
SLSKD_API_URL = _get_setting("SLSKD_API_URL", "http://localhost:5030")
SLSKD_API_KEY = _get_setting("SLSKD_API_KEY")

# Web runtime settings
DOWNLOAD_WORKDIR = _get_setting("DOWNLOAD_WORKDIR", "tmp_downloads")
JOB_TTL_SECONDS = int(_get_setting("JOB_TTL_SECONDS", "21600"))
MAX_LOG_LINES = int(_get_setting("MAX_LOG_LINES", "600"))
MAX_TRACKS_PER_JOB = int(_get_setting("MAX_TRACKS_PER_JOB", "250"))
PORT = int(_get_setting("PORT", "5000"))
