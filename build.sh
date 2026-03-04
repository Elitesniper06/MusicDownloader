#!/usr/bin/env bash
# build.sh — Script de build para Render.com
# Instala dependencias Python + ffmpeg (necesario para yt-dlp)

set -o errexit  # Salir ante cualquier error

echo "══ Instalando dependencias Python ══"
pip install --upgrade pip
pip install -r requirements.txt

echo "══ Instalando ffmpeg ══"
# Descargar binario estático de ffmpeg (no requiere root/apt)
FFMPEG_DIR="$HOME/ffmpeg"
mkdir -p "$FFMPEG_DIR"

if [ ! -f "$FFMPEG_DIR/ffmpeg" ]; then
    echo "Descargando ffmpeg estático..."
    curl -L "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" -o /tmp/ffmpeg.tar.xz
    tar -xf /tmp/ffmpeg.tar.xz -C /tmp/
    cp /tmp/ffmpeg-*-amd64-static/ffmpeg "$FFMPEG_DIR/ffmpeg"
    cp /tmp/ffmpeg-*-amd64-static/ffprobe "$FFMPEG_DIR/ffprobe"
    chmod +x "$FFMPEG_DIR/ffmpeg" "$FFMPEG_DIR/ffprobe"
    rm -rf /tmp/ffmpeg* 
    echo "ffmpeg instalado en $FFMPEG_DIR"
else
    echo "ffmpeg ya existe en $FFMPEG_DIR"
fi

# Añadir al PATH para que yt-dlp lo encuentre
export PATH="$FFMPEG_DIR:$PATH"

echo "══ Build completado ══"
