# wsgi.py — Punto de entrada alternativo para gunicorn
from web_app import app, socketio  # noqa: F401

# gunicorn importa 'app' desde este módulo
# CMD: gunicorn -w 1 --threads 100 -b 0.0.0.0:$PORT wsgi:app
