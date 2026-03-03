FROM python:3.12-slim

# Logs sin buffer — crítico para que Render muestre el output
ENV PYTHONUNBUFFERED=1

# Instalar ffmpeg (necesario para yt-dlp)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY . .

ENV PORT=10000
EXPOSE 10000

# gunicorn con 1 worker + threads (necesario para SocketIO in-memory)
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 100 --timeout 120 web_app:app
