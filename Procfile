web: gunicorn nexus.wsgi:application --bind 0.0.0.0:$PORT
worker: celery -A nexus worker --loglevel=info --pool=solo