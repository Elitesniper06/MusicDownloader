FROM python:3.12-slim

# Instalar ffmpeg (necesario para yt-dlp)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar requirements primero (cache de Docker)
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

# Copiar el resto del código
COPY . .

# Verificar que los archivos están
RUN echo "=== Files in /app ===" && ls -la && echo "=== Templates ===" && ls -la templates/

# Puerto (Render inyecta PORT como variable de entorno)
ENV PORT=10000
EXPOSE 10000

# Usar gunicorn (servidor de producción) con threading + WebSocket
# -w 1: un solo worker (necesario para SocketIO con estado en memoria)
# --threads 100: hilos para concurrencia
# -b 0.0.0.0:$PORT: escuchar en todas las interfaces
CMD gunicorn -w 1 --threads 100 -b 0.0.0.0:$PORT --timeout 120 web_app:app
