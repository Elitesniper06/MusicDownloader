# ============================================================================
# spotify_utils.py — Extracción de metadatos desde links de Spotify
# ============================================================================

import re
from typing import Optional

try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    SPOTIPY_AVAILABLE = True
except ImportError:
    SPOTIPY_AVAILABLE = False


def is_spotify_url(url: str) -> bool:
    """Detecta si una URL es de Spotify."""
    return bool(re.search(r"open\.spotify\.com/(track|album|playlist)/", url))


def extract_spotify_id(url: str) -> Optional[str]:
    """Extrae el ID del recurso de una URL de Spotify."""
    match = re.search(r"open\.spotify\.com/(?:track|album|playlist)/([a-zA-Z0-9]+)", url)
    return match.group(1) if match else None


def get_spotify_type(url: str) -> Optional[str]:
    """Determina si la URL es track, album o playlist."""
    match = re.search(r"open\.spotify\.com/(track|album|playlist)/", url)
    return match.group(1) if match else None


def create_spotify_client(client_id: str, client_secret: str) -> "spotipy.Spotify":
    """
    Crea un cliente de Spotify autenticado.
    Requiere que SPOTIFY_CLIENT_ID y SPOTIFY_CLIENT_SECRET estén configurados
    en config.py.
    """
    if not SPOTIPY_AVAILABLE:
        raise ImportError(
            "La librería 'spotipy' no está instalada. "
            "Ejecuta: pip install spotipy"
        )
    if not client_id or not client_secret:
        raise ValueError(
            "Debes configurar SPOTIFY_CLIENT_ID y SPOTIFY_CLIENT_SECRET en config.py.\n"
            "Visita https://developer.spotify.com/dashboard para obtenerlos."
        )

    auth_manager = SpotifyClientCredentials(
        client_id=client_id,
        client_secret=client_secret,
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def get_tracks_from_spotify_url(
    url: str, client_id: str, client_secret: str
) -> list[dict]:
    """
    Dada una URL de Spotify, devuelve una lista de dicts con:
      {
        "title": str,
        "artist": str,
        "album": str,
        "track_number": int,
        "duration_ms": int,
        "cover_url": str,          # URL de la portada (640px)
        "isrc": str | None,        # Código ISRC (útil para búsquedas exactas)
      }

    Soporta: tracks individuales, álbumes y playlists.
    """
    sp = create_spotify_client(client_id, client_secret)
    resource_type = get_spotify_type(url)
    resource_id = extract_spotify_id(url)

    if not resource_type or not resource_id:
        raise ValueError(f"URL de Spotify no válida: {url}")

    tracks_info = []

    if resource_type == "track":
        track = sp.track(resource_id)
        tracks_info.append(_parse_track(track))

    elif resource_type == "album":
        album = sp.album(resource_id)
        cover_url = _get_best_cover(album.get("images", []))
        results = sp.album_tracks(resource_id)
        all_items = results["items"]
        while results["next"]:
            results = sp.next(results)
            all_items.extend(results["items"])
        for item in all_items:
            info = _parse_track(item)
            info["album"] = album["name"]
            info["cover_url"] = cover_url
            tracks_info.append(info)

    elif resource_type == "playlist":
        results = sp.playlist_items(
            resource_id,
            fields="items(track(name,artists,album,duration_ms,external_ids,track_number)),next",
        )
        all_items = results["items"]
        while results["next"]:
            results = sp.next(results)
            all_items.extend(results["items"])
        for item in all_items:
            track = item.get("track")
            if track:
                tracks_info.append(_parse_track(track))

    return tracks_info


def _parse_track(track: dict) -> dict:
    """Extrae información relevante de un objeto track de la API de Spotify."""
    artists = ", ".join(a["name"] for a in track.get("artists", []))
    album_data = track.get("album") or {}
    album_name = album_data.get("name", "Unknown Album") if isinstance(album_data, dict) else str(album_data)
    images = album_data.get("images", []) if isinstance(album_data, dict) else []
    cover_url = _get_best_cover(images)
    isrc = None
    ext_ids = track.get("external_ids", {})
    if ext_ids:
        isrc = ext_ids.get("isrc")

    return {
        "title": track.get("name", "Unknown"),
        "artist": artists or "Unknown Artist",
        "album": album_name,
        "track_number": track.get("track_number", 1),
        "duration_ms": track.get("duration_ms", 0),
        "cover_url": cover_url,
        "isrc": isrc,
    }


def _get_best_cover(images: list[dict]) -> str:
    """Selecciona la imagen de portada con mayor resolución."""
    if not images:
        return ""
    # La API devuelve las imágenes de mayor a menor resolución
    return images[0].get("url", "")
