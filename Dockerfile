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

# Puerto
ENV PORT=10000
EXPOSE 10000

# Ejecutar directamente con Flask-SocketIO + eventlet
CMD ["python", "web_app.py"]
