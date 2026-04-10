# ============================================================
# SETTINGS ADDITIONS — add these to your settings.py
# ============================================================

# --- Installed apps (add to INSTALLED_APPS) ---
# 'rest_framework',
# 'rest_framework.authtoken',
# 'knowledgebase',

# --- DRF config ---
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# --- Celery (Railway Redis) ---
# CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
# CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
# CELERY_ACCEPT_CONTENT = ['json']
# CELERY_TASK_SERIALIZER = 'json'

# --- File storage ---
# MEDIA_URL = '/media/'
# MEDIA_ROOT = BASE_DIR / 'media'

# --- Gemini API key ---
# GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

# --- pgvector: make sure your DB is PostgreSQL with pgvector extension ---
# Run this once in psql: CREATE EXTENSION IF NOT EXISTS vector;


# ============================================================
# requirements.txt
# ============================================================
"""
django>=4.2
djangorestframework
celery
redis
psycopg2-binary
pgvector
google-generativeai
pdfplumber
PyPDF2
python-decouple
gunicorn
whitenoise
"""


# ============================================================
# celery.py — create this at project root (same level as settings.py)
# ============================================================
"""
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'your_project.settings')

app = Celery('your_project')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
"""


# ============================================================
# Railway deployment checklist
# ============================================================
# 1. Set env vars: GEMINI_API_KEY, SECRET_KEY, DATABASE_URL, REDIS_URL
# 2. Add pgvector extension: Railway PostgreSQL supports it natively
#    Run migration after enabling: python manage.py migrate
# 3. Start command: gunicorn your_project.wsgi:application
# 4. Worker: celery -A your_project worker --loglevel=info
#    (Add as a separate Railway service or use Procfile)
#
# Procfile:
#   web: gunicorn your_project.wsgi:application --bind 0.0.0.0:$PORT
#   worker: celery -A your_project worker --loglevel=info


# ============================================================
# pgvector migration — add to a new migration file
# ============================================================
# from pgvector.django import VectorExtension
#
# class Migration(migrations.Migration):
#     operations = [
#         VectorExtension(),   # must run BEFORE any model with VectorField
#         migrations.CreateModel(...)
#     ]
