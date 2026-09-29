"""
Production settings. Use environment variables (see docs/ROADMAP.md).
"""
from pathlib import Path
import environ
from django.core.exceptions import ImproperlyConfigured

# Load before base so Celery and integration settings also see .env values.
environ.Env.read_env(Path(__file__).resolve().parents[2] / '.env')
from .base import *  # noqa: F401,F403,E402

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_SECURE_SSL_REDIRECT=(bool, True),
    DJANGO_USE_X_FORWARDED_PROTO=(bool, False),
)

DEBUG = False
if env('DJANGO_DEBUG'):
    raise ImproperlyConfigured('Use local settings for debugging; production requires DJANGO_DEBUG=0.')
SECRET_KEY = env('DJANGO_SECRET_KEY')
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith(('django-insecure-', 'change-me')):
    raise ImproperlyConfigured('DJANGO_SECRET_KEY must be a strong, unique secret of at least 50 characters.')

_hosts = env.str('DJANGO_ALLOWED_HOSTS', default='')
ALLOWED_HOSTS = [h.strip() for h in _hosts.split(',') if h.strip()]
if not ALLOWED_HOSTS or '*' in ALLOWED_HOSTS:
    raise ValueError('DJANGO_ALLOWED_HOSTS must be set in production (comma-separated).')

DATABASES = {
    'default': env.db('DATABASE_URL')
}
CSRF_TRUSTED_ORIGINS = env.list('DJANGO_CSRF_TRUSTED_ORIGINS', default=[])
SECURE_HSTS_SECONDS = env.int('DJANGO_SECURE_HSTS_SECONDS', default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False)
SECURE_HSTS_PRELOAD = env.bool('DJANGO_SECURE_HSTS_PRELOAD', default=False)
SECURE_REFERRER_POLICY = 'same-origin'

if not DEBUG:
    SECURE_SSL_REDIRECT = env('DJANGO_SECURE_SSL_REDIRECT')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    if env('DJANGO_USE_X_FORWARDED_PROTO'):
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Static files: WhiteNoise after SecurityMiddleware
MIDDLEWARE = list(MIDDLEWARE)
if 'whitenoise.middleware.WhiteNoiseMiddleware' not in MIDDLEWARE:
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}
