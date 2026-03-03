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

# Ejecutar directamente con Python (Flask-SocketIO maneja el servidor)
CMD ["python", "web_app.py"]
