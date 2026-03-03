# wsgi.py — Punto de entrada para gunicorn en producción
from web_app import app, socketio

if __name__ == "__main__":
    socketio.run(app)
