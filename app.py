# ============================================================================
# app.py — Interfaz gráfica principal (CustomTkinter)
# ============================================================================
# Ejecutar con:  python app.py
# ============================================================================

import os
import sys
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

# ── Módulos internos ───────────────────────────────────────────────
from config import (
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    DEEZER_ARL,
    SLSKD_API_URL,
    SLSKD_API_KEY,
)
from spotify_utils import is_spotify_url, get_tracks_from_spotify_url
from downloader import (
    download_track,
    is_youtube_url,
    get_youtube_info,
)


# ============================================================================
#  CONFIGURACIÓN DE LA VENTANA
# ============================================================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_TITLE = "🎵 Music Downloader Pro"
APP_WIDTH = 780
APP_HEIGHT = 620


class MusicDownloaderApp(ctk.CTk):
    """Ventana principal de la aplicación."""

    def __init__(self):
        super().__init__()

        # ── Ventana ────────────────────────────────────────────────
        self.title(APP_TITLE)
        self.geometry(f"{APP_WIDTH}x{APP_HEIGHT}")
        self.minsize(650, 550)
        self.resizable(True, True)

        # ── Estado ─────────────────────────────────────────────────
        self._dest_folder: str = ""
        self._is_downloading: bool = False
        self._stop_requested: bool = False

        # ── Construir UI ───────────────────────────────────────────
        self._build_ui()

    # ================================================================
    # CONSTRUCCIÓN DE LA INTERFAZ
    # ================================================================

    def _build_ui(self):
        # Grid principal
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)  # Área de log expandible

        # ── Título ─────────────────────────────────────────────────
        title_label = ctk.CTkLabel(
            self,
            text="🎵 Music Downloader Pro",
            font=ctk.CTkFont(size=26, weight="bold"),
        )
        title_label.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="w")

        subtitle_label = ctk.CTkLabel(
            self,
            text="Descarga música en la mejor calidad posible a tu pendrive",
            font=ctk.CTkFont(size=13),
            text_color="gray",
        )
        subtitle_label.grid(row=1, column=0, padx=20, pady=(0, 15), sticky="w")

        # ── Frame de URL ───────────────────────────────────────────
        url_frame = ctk.CTkFrame(self, fg_color="transparent")
        url_frame.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="ew")
        url_frame.grid_columnconfigure(0, weight=1)

        url_label = ctk.CTkLabel(
            url_frame,
            text="🔗 URL (Spotify / YouTube / YouTube Music):",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        url_label.grid(row=0, column=0, sticky="w", pady=(0, 5))

        self.url_entry = ctk.CTkEntry(
            url_frame,
            placeholder_text="Pega aquí la URL de la canción, álbum o playlist...",
            height=40,
            font=ctk.CTkFont(size=13),
        )
        self.url_entry.grid(row=1, column=0, sticky="ew")

        # ── Frame de destino ───────────────────────────────────────
        dest_frame = ctk.CTkFrame(self, fg_color="transparent")
        dest_frame.grid(row=3, column=0, padx=20, pady=(0, 10), sticky="ew")
        dest_frame.grid_columnconfigure(1, weight=1)

        self.browse_btn = ctk.CTkButton(
            dest_frame,
            text="📁 Seleccionar Carpeta / Pendrive",
            command=self._browse_folder,
            width=240,
            height=38,
            font=ctk.CTkFont(size=13),
        )
        self.browse_btn.grid(row=0, column=0, padx=(0, 10))

        self.dest_label = ctk.CTkLabel(
            dest_frame,
            text="⚠️ Ninguna carpeta seleccionada",
            font=ctk.CTkFont(size=12),
            text_color="#FF9500",
            anchor="w",
        )
        self.dest_label.grid(row=0, column=1, sticky="w")

        # ── Área de log ────────────────────────────────────────────
        self.log_textbox = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(family="Consolas", size=12),
            state="disabled",
            wrap="word",
            fg_color="#1a1a2e",
            border_width=1,
            border_color="#333355",
        )
        self.log_textbox.grid(row=4, column=0, padx=20, pady=(5, 10), sticky="nsew")

        # ── Frame inferior (progreso + botón de descarga) ──────────
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.grid(row=5, column=0, padx=20, pady=(0, 10), sticky="ew")
        bottom_frame.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(
            bottom_frame, mode="indeterminate", height=6
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, 15))
        self.progress_bar.set(0)

        self.download_btn = ctk.CTkButton(
            bottom_frame,
            text="⬇️  DESCARGAR",
            command=self._on_download_click,
            width=200,
            height=45,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#1DB954",          # Verde Spotify
            hover_color="#1AA34A",
        )
        self.download_btn.grid(row=0, column=1, padx=(0, 8))

        self.stop_btn = ctk.CTkButton(
            bottom_frame,
            text="⏹  PARAR",
            command=self._on_stop_click,
            width=120,
            height=45,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#cc3333",
            hover_color="#aa2222",
            state="disabled",
        )
        self.stop_btn.grid(row=0, column=2)

        # ── Créditos ──────────────────────────────────────────────
        credits_label = ctk.CTkLabel(
            self,
            text="Plan A: FLAC (Deezer/Soulseek)  →  Plan B: Mejor calidad (yt-dlp)",
            font=ctk.CTkFont(size=11),
            text_color="#555577",
        )
        credits_label.grid(row=6, column=0, padx=20, pady=(0, 10))

    # ================================================================
    # ACCIONES DE LA INTERFAZ
    # ================================================================

    def _browse_folder(self):
        """Abre un diálogo para seleccionar la carpeta destino (pendrive)."""
        folder = filedialog.askdirectory(title="Selecciona la carpeta de destino (Pendrive)")
        if folder:
            self._dest_folder = folder
            self.dest_label.configure(
                text=f"📂 {folder}",
                text_color="#1DB954",
            )
            self._log(f"Carpeta destino: {folder}")

    def _on_download_click(self):
        """Valida y lanza la descarga en un hilo separado."""
        if self._is_downloading:
            self._log("⚠️ Ya hay una descarga en curso. Espera a que termine.")
            return

        url = self.url_entry.get().strip()
        if not url:
            self._log("❌ Error: Pega una URL antes de descargar.")
            return

        if not self._dest_folder:
            self._log("❌ Error: Selecciona una carpeta de destino.")
            return

        if not os.path.isdir(self._dest_folder):
            self._log("❌ Error: La carpeta de destino no existe o no es accesible.")
            return

        # Lanzar descarga en hilo separado para no bloquear la GUI
        self._is_downloading = True
        self._stop_requested = False
        self.download_btn.configure(state="disabled", text="⏳ Descargando...")
        self.stop_btn.configure(state="normal")
        self.progress_bar.start()

        thread = threading.Thread(
            target=self._download_worker,
            args=(url,),
            daemon=True,
        )
        thread.start()

    def _on_stop_click(self):
        """Solicita detener la descarga en curso."""
        if self._is_downloading:
            self._stop_requested = True
            self.stop_btn.configure(state="disabled", text="⏹ Parando...")
            self._log("⚠️ Deteniendo tras la canción actual...")

    def _download_worker(self, url: str):
        """Ejecuta la descarga en un hilo en segundo plano."""
        try:
            self._log(f"\n🚀 Descargando → {self._dest_folder}")

            tracks_to_download = []

            # ── 1. Analizar la URL ─────────────────────────────────
            if is_spotify_url(url):
                try:
                    tracks_to_download = get_tracks_from_spotify_url(
                        url,
                        client_id=SPOTIFY_CLIENT_ID,
                        client_secret=SPOTIFY_CLIENT_SECRET,
                    )
                except ImportError as e:
                    self._log(f"❌ {e}")
                    return
                except ValueError as e:
                    self._log(f"❌ {e}")
                    return
                except Exception as e:
                    self._log(f"❌ Error al obtener datos de Spotify: {e}")
                    return

            elif is_youtube_url(url):
                try:
                    tracks_to_download = get_youtube_info(url)
                except Exception as e:
                    self._log(f"❌ Error al obtener datos de YouTube: {e}")
                    return

            else:
                tracks_to_download = [{
                    "title": "Desconocido",
                    "artist": "Desconocido",
                    "album": "",
                    "track_number": 0,
                    "cover_url": "",
                    "isrc": None,
                    "youtube_url": url,
                }]

            if not tracks_to_download:
                self._log("❌ No se encontraron canciones para descargar.")
                return

            # ── 2. Descargar cada track ────────────────────────────
            total = len(tracks_to_download)
            success_count = 0
            fail_count = 0

            for i, track in enumerate(tracks_to_download, 1):
                if self._stop_requested:
                    self._log(f"\n⛔ Descarga detenida por el usuario ({i-1}/{total}).")
                    break

                result = download_track(
                    title=track.get("title", "Unknown"),
                    artist=track.get("artist", "Unknown"),
                    album=track.get("album", ""),
                    dest_folder=self._dest_folder,
                    cover_url=track.get("cover_url", ""),
                    track_number=track.get("track_number", 0),
                    isrc=track.get("isrc"),
                    youtube_url=track.get("youtube_url"),
                    deezer_arl=DEEZER_ARL,
                    slskd_api_url=SLSKD_API_URL,
                    slskd_api_key=SLSKD_API_KEY,
                    log_callback=self._log,
                )

                if result:
                    success_count += 1
                else:
                    fail_count += 1

            # ── 3. Resumen final ───────────────────────────────────
            self._log(f"\n🏁 Listo — ✅ {success_count}/{total}" + (f" ❌ {fail_count}" if fail_count else ""))

        except Exception as e:
            self._log(f"\n❌ Error crítico inesperado: {e}")
            import traceback
            self._log(traceback.format_exc())

        finally:
            # Restaurar estado de la GUI (desde el hilo principal)
            self.after(0, self._download_finished)

    def _download_finished(self):
        """Restaura la interfaz tras la descarga."""
        self._is_downloading = False
        self._stop_requested = False
        self.download_btn.configure(state="normal", text="⬇️  DESCARGAR")
        self.stop_btn.configure(state="disabled", text="⏹  PARAR")
        self.progress_bar.stop()
        self.progress_bar.set(0)

    # ================================================================
    # LOG
    # ================================================================

    def _log(self, message: str):
        """
        Escribe un mensaje en el área de log.
        Es thread-safe: usa self.after() para escribir desde el hilo principal.
        """
        def _write():
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert("end", message + "\n")
            self.log_textbox.see("end")  # Auto-scroll
            self.log_textbox.configure(state="disabled")

        # Si estamos en el hilo principal, escribir directamente
        # Si no, programar la escritura en el hilo principal
        self.after(0, _write)


# ============================================================================
# PUNTO DE ENTRADA
# ============================================================================

def main():
    """Inicia la aplicación."""
    print(f"Iniciando Music Downloader Pro...")
    print("Cierra esta ventana de terminal para detener la aplicacion.\n")

    app = MusicDownloaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
