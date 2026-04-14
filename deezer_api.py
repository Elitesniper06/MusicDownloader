# ============================================================================
# deezer_api.py — Cliente de la API privada de Deezer para descarga FLAC
# ============================================================================
# Usa la API GW (gateway) de Deezer para autenticarse con la cookie ARL
# y descargar audio en FLAC (lossless) o MP3 320kbps.
# ============================================================================

import hashlib
import os
from typing import Callable, Optional

import requests

try:
    from Crypto.Cipher import Blowfish  # pycryptodome
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# ── Constantes ────────────────────────────────────────────────────
DEEZER_GW_URL = "https://www.deezer.com/ajax/gw-light.php"
DEEZER_MEDIA_URL = "https://media.deezer.com/v1/get_url"
DEEZER_PUBLIC_API = "https://api.deezer.com"

# Clave para derivar la key de Blowfish (constante pública de la API)
_BF_SECRET = "g4el58wc0zvf9na1"


class DeezerAPI:
    """Cliente para la API privada (GW) de Deezer."""

    def __init__(self, arl: str, log: Callable[[str], None] = print):
        self.arl = arl
        self.log = log
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        })
        self.session.cookies.set("arl", arl, domain=".deezer.com")
        self.api_token: str = ""
        self.license_token: str = ""
        self.user_id: int = 0
        self.country: str = ""

    # ================================================================
    # AUTENTICACIÓN
    # ================================================================

    def login(self) -> bool:
        """
        Autentica la sesión con la cookie ARL.
        Retorna True si el login fue exitoso.
        """
        if not CRYPTO_AVAILABLE:
            raise ImportError(
                "Se necesita pycryptodome para descifrar audio de Deezer.\n"
                "Instálalo con: pip install pycryptodome"
            )

        data = self._gw_call("deezer.getUserData")
        if not data:
            return False

        user = data.get("USER", {})
        self.user_id = user.get("USER_ID", 0)
        self.api_token = data.get("checkForm", "")
        self.license_token = (
            user.get("OPTIONS", {}).get("license_token", "")
        )
        self.country = data.get("COUNTRY", "")

        if not self.user_id or self.user_id == 0:
            self.log("   ❌ ARL inválida o expirada. Renueva tu cookie ARL.")
            return False

        user_name = user.get("BLOG_NAME", "Usuario")
        plan = user.get("OPTIONS", {}).get("license_token", "")
        can_hq = user.get("OPTIONS", {}).get("web_hq", False)
        can_lossless = user.get("OPTIONS", {}).get("web_lossless", False)

        quality = "FLAC" if can_lossless else "HQ 320kbps" if can_hq else "MP3 128kbps"
        self.log(f"   ✅ Deezer conectado ({quality})")

        return True

    # ================================================================
    # BÚSQUEDA
    # ================================================================

    def search_track(self, query: str, limit: int = 10) -> list[dict]:
        """
        Busca canciones en Deezer (API pública).
        Retorna lista de resultados con id, title, artist, album, etc.
        """
        try:
            resp = self.session.get(
                f"{DEEZER_PUBLIC_API}/search",
                params={"q": query, "limit": limit},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as e:
            self.log(f"   Error en búsqueda Deezer: {e}")
            return []

    def search_by_isrc(self, isrc: str) -> Optional[dict]:
        """Busca una canción por su código ISRC (búsqueda exacta)."""
        try:
            resp = self.session.get(
                f"{DEEZER_PUBLIC_API}/2.0/track/isrc:{isrc}",
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("id"):
                    return data
        except Exception:
            pass
        return None

    # ================================================================
    # INFORMACIÓN DE TRACK (API privada GW)
    # ================================================================

    def get_track_info(self, track_id: int) -> dict:
        """Obtiene información detallada del track vía API GW."""
        data = self._gw_call("song.getData", {"sng_id": str(track_id)})
        return data or {}

    # ================================================================
    # DESCARGA
    # ================================================================

    def get_download_url(
        self, track_token: str, preferred_format: str = "FLAC"
    ) -> tuple[str, str]:
        """
        Obtiene la URL de descarga cifrada para un track.

        Args:
            track_token: Token del track (de song.getData -> TRACK_TOKEN)
            preferred_format: "FLAC", "MP3_320", o "MP3_128"

        Returns:
            Tupla (url, format_obtained)
        """
        # Definir formatos por preferencia descendente
        if preferred_format == "FLAC":
            formats = [
                {"cipher": "BF_CBC_STRIPE", "format": "FLAC"},
                {"cipher": "BF_CBC_STRIPE", "format": "MP3_320"},
                {"cipher": "BF_CBC_STRIPE", "format": "MP3_128"},
            ]
        elif preferred_format == "MP3_320":
            formats = [
                {"cipher": "BF_CBC_STRIPE", "format": "MP3_320"},
                {"cipher": "BF_CBC_STRIPE", "format": "MP3_128"},
            ]
        else:
            formats = [
                {"cipher": "BF_CBC_STRIPE", "format": "MP3_128"},
            ]

        try:
            resp = self.session.post(
                DEEZER_MEDIA_URL,
                json={
                    "license_token": self.license_token,
                    "media": [{"type": "FULL", "formats": formats}],
                    "track_tokens": [track_token],
                },
                timeout=20,
            )
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:
            raise ConnectionError(f"Error obteniendo URL de descarga: {e}")

        # Parsear respuesta
        data_list = result.get("data", [])
        if not data_list:
            raise ValueError("Respuesta vacía de media API")

        first = data_list[0]

        # Verificar errores
        errors = first.get("errors", [])
        if errors:
            error_msgs = [
                f"{e.get('type', '?')}: {e.get('message', '?')}"
                for e in errors
            ]
            raise ValueError(f"Error Deezer media: {'; '.join(error_msgs)}")

        media_list = first.get("media", [])
        if not media_list:
            raise ValueError("No hay media disponible para este track")

        media = media_list[0]
        sources = media.get("sources", [])
        if not sources:
            raise ValueError("No hay sources de descarga")

        url = sources[0].get("url", "")
        fmt = media.get("format", "UNKNOWN")

        if not url:
            raise ValueError("URL de descarga vacía")

        return url, fmt

    def download_track(
        self,
        track_id: int,
        download_url: str,
        output_path: str,
        chunk_callback: Callable[[int, int], None] = None,
    ) -> str:
        """
        Descarga y descifra un track de Deezer.

        Args:
            track_id: ID numérico del track (para generar la clave BF)
            download_url: URL cifrada obtenida de get_download_url
            output_path: Ruta de destino del archivo
            chunk_callback: Callback opcional (bytes_descargados, bytes_totales)

        Returns:
            Ruta del archivo descargado
        """
        # Descargar el stream cifrado
        resp = self.session.get(download_url, stream=True, timeout=30)
        resp.raise_for_status()

        total_size = int(resp.headers.get("Content-Length", 0))
        downloaded = 0

        # Generar clave Blowfish para este track
        bf_key = self._get_blowfish_key(track_id)

        with open(output_path, "wb") as f:
            chunk_index = 0
            buffer = b""

            for data in resp.iter_content(chunk_size=8192):
                buffer += data

                # Procesamos en bloques de 2048 bytes
                while len(buffer) >= 2048:
                    chunk = buffer[:2048]
                    buffer = buffer[2048:]

                    # Cada 3er bloque de 2048 bytes está cifrado con BF-CBC
                    if chunk_index % 3 == 0:
                        cipher = Blowfish.new(
                            bf_key, Blowfish.MODE_CBC, b"\x00\x01\x02\x03\x04\x05\x06\x07"
                        )
                        chunk = cipher.decrypt(chunk)

                    f.write(chunk)
                    chunk_index += 1
                    downloaded += 2048

                    if chunk_callback and total_size:
                        chunk_callback(min(downloaded, total_size), total_size)

            # Escribir lo que quede en el buffer (último fragmento incompleto)
            if buffer:
                f.write(buffer)

        return output_path

    # ================================================================
    # FLUJO COMPLETO: buscar + descargar
    # ================================================================

    def search_and_download(
        self,
        title: str,
        artist: str,
        dest_folder: str,
        isrc: str = None,
        cover_url: str = "",
        album: str = "",
        track_number: int = 0,
    ) -> Optional[str]:
        """
        Flujo completo: busca un track y lo descarga en la mejor calidad.

        Returns:
            Ruta del archivo descargado, o None si falla.
        """
        # ── 1. Buscar el track ─────────────────────────────────────
        track_api_data = None

        # Intentar primero por ISRC (más preciso)
        if isrc:
            track_api_data = self.search_by_isrc(isrc)

        # Si no, buscar por texto con múltiples estrategias
        if not track_api_data:
            track_api_data = self._smart_search(title, artist)

        if not track_api_data:
            self.log("   ❌ Sin resultados en Deezer con ninguna estrategia.")
            return None

        track_id = track_api_data["id"]

        # ── 2. Obtener info detallada (necesitamos TRACK_TOKEN) ────
        gw_info = self.get_track_info(track_id)

        if not gw_info:
            self.log("   ❌ No se pudo obtener info del track desde GW API.")
            return None

        track_token = gw_info.get("TRACK_TOKEN", "")
        if not track_token:
            self.log("   ❌ Track sin token de descarga (puede estar geo-bloqueado).")
            return None

        # Info para metadatos
        dz_title = gw_info.get("SNG_TITLE", title)
        dz_artist = gw_info.get("ART_NAME", artist)
        dz_album = gw_info.get("ALB_TITLE", album)
        dz_track_num = int(gw_info.get("TRACK_NUMBER", track_number) or 0)
        dz_cover_id = gw_info.get("ALB_PICTURE", "")

        if dz_cover_id:
            cover_url = f"https://e-cdns-images.dzcdn.net/images/cover/{dz_cover_id}/1200x1200-000000-80-0-0.jpg"

        # ── 3. Obtener URL de descarga ─────────────────────────────
        try:
            download_url, fmt = self.get_download_url(track_token, "FLAC")
        except Exception as e:
            self.log(f"   ❌ Error obteniendo URL: {e}")
            return None

        # Determinar extensión del archivo
        ext = ".flac" if fmt == "FLAC" else ".mp3"

        # ── 4. Descargar y descifrar ───────────────────────────────
        safe_name = _sanitize_filename(f"{dz_artist} - {dz_title}")
        output_path = os.path.join(dest_folder, f"{safe_name}{ext}")

        self.log(f"   ⬇️ Descargando {fmt}: {dz_artist} - {dz_title}")

        try:
            self.download_track(
                track_id=track_id,
                download_url=download_url,
                output_path=output_path,
            )
        except Exception as e:
            self.log(f"   ❌ Error en descarga: {e}")
            # Limpiar archivo parcial
            if os.path.exists(output_path):
                os.remove(output_path)
            return None

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1024:
            self.log("   ❌ Archivo descargado está vacío o corrupto.")
            if os.path.exists(output_path):
                os.remove(output_path)
            return None

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        self.log(f"   ✅ {safe_name}{ext} ({size_mb:.1f} MB)")

        # ── 5. Escribir metadatos ──────────────────────────────────
        self._write_tags(
            filepath=output_path,
            title=dz_title,
            artist=dz_artist,
            album=dz_album,
            track_number=dz_track_num,
            cover_url=cover_url,
        )

        return output_path

    # ================================================================
    # MÉTODOS INTERNOS
    # ================================================================

    def _gw_call(self, method: str, params: dict = None) -> Optional[dict]:
        """Llama a la API GW (gateway) de Deezer."""
        try:
            resp = self.session.post(
                DEEZER_GW_URL,
                params={
                    "method": method,
                    "input": "3",
                    "api_version": "1.0",
                    "api_token": self.api_token or "null",
                },
                json=params or {},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("error"):
                self.log(f"   ⚠️ Error GW API ({method}): {data['error']}")
                return None

            return data.get("results")
        except Exception as e:
            self.log(f"   Error llamando a GW API ({method}): {e}")
            return None

    def _smart_search(self, title: str, artist: str) -> Optional[dict]:
        """
        Busca un track en Deezer con múltiples estrategias.
        Limpia separadores como 'x', 'feat', '&', etc. y prueba
        varias combinaciones hasta encontrar un resultado.
        """
        # Limpiar el artista: quitar "x", "feat.", "&", "ft." entre nombres
        clean_artist = re.sub(
            r"\s*[x×&]\s*|\s+feat\.?\s+|\s+ft\.?\s+|\s+y\s+",
            " ", artist, flags=re.IGNORECASE,
        ).strip()
        # Extraer solo el primer artista
        first_artist = re.split(r"[,/]", clean_artist)[0].strip()

        # Lista de queries a intentar (de más específica a más general)
        queries = []

        # 1. Búsqueda avanzada con track: y artist:
        queries.append(f'track:"{title}" artist:"{first_artist}"')

        # 2. Solo título y primer artista
        queries.append(f"{first_artist} {title}")

        # 3. Artista limpio completo + título
        if clean_artist != first_artist:
            queries.append(f"{clean_artist} {title}")

        # 4. Solo el título (último recurso)
        queries.append(title)

        # Eliminar duplicados manteniendo orden
        seen = set()
        unique_queries = []
        for q in queries:
            q_lower = q.lower().strip()
            if q_lower not in seen:
                seen.add(q_lower)
                unique_queries.append(q)

        for query in unique_queries:
            results = self.search_track(query, limit=5)
            if results:
                return results[0]

        return None

    @staticmethod
    def _get_blowfish_key(track_id: int) -> bytes:
        """
        Genera la clave Blowfish de 16 bytes para descifrar un track.
        Se deriva del MD5 del track_id XOR con la constante secreta.
        """
        id_md5 = hashlib.md5(str(track_id).encode("ascii")).hexdigest()
        key = bytes(
            ord(id_md5[i]) ^ ord(id_md5[i + 16]) ^ ord(_BF_SECRET[i])
            for i in range(16)
        )
        return key

    def _write_tags(
        self,
        filepath: str,
        title: str,
        artist: str,
        album: str = "",
        track_number: int = 0,
        cover_url: str = "",
    ):
        """Escribe metadatos en el archivo descargado."""
        ext = os.path.splitext(filepath)[1].lower()

        try:
            # Descargar carátula
            cover_data = None
            if cover_url:
                try:
                    resp = requests.get(cover_url, timeout=15)
                    if resp.status_code == 200:
                        cover_data = resp.content
                except Exception:
                    pass

            if ext == ".flac":
                from mutagen.flac import FLAC, Picture

                audio = FLAC(filepath)
                audio["title"] = title
                audio["artist"] = artist
                if album:
                    audio["album"] = album
                if track_number:
                    audio["tracknumber"] = str(track_number)
                if cover_data:
                    pic = Picture()
                    pic.type = 3  # Cover (front)
                    pic.mime = "image/jpeg"
                    pic.data = cover_data
                    audio.add_picture(pic)
                audio.save()

            elif ext == ".mp3":
                from mutagen.mp3 import MP3
                from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, APIC

                audio = MP3(filepath)
                if audio.tags is None:
                    audio.add_tags()
                audio.tags.add(TIT2(encoding=3, text=[title]))
                audio.tags.add(TPE1(encoding=3, text=[artist]))
                if album:
                    audio.tags.add(TALB(encoding=3, text=[album]))
                if track_number:
                    audio.tags.add(TRCK(encoding=3, text=[str(track_number)]))
                if cover_data:
                    audio.tags.add(APIC(
                        encoding=3, mime="image/jpeg",
                        type=3, data=cover_data,
                    ))
                audio.save()

        except Exception as e:
            self.log(f"   ⚠️ Error escribiendo metadatos: {e}")


def _sanitize_filename(name: str) -> str:
    """Elimina caracteres no válidos para nombres de archivo Windows."""
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = name.rstrip(". ")
    return name[:200] if len(name) > 200 else name


# Necesitamos re aquí también
import re
