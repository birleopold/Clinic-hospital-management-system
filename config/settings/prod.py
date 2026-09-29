"""
Production settings. Use environment variables (see docs/ROADMAP.md).
"""
import environ

from .base import *  # noqa: F401,F403

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_SECURE_SSL_REDIRECT=(bool, False),
    DJANGO_USE_X_FORWARDED_PROTO=(bool, False),
)

environ.Env.read_env(BASE_DIR / '.env')

DEBUG = env('DJANGO_DEBUG')
SECRET_KEY = env('DJANGO_SECRET_KEY')

_hosts = env.str('DJANGO_ALLOWED_HOSTS', default='')
ALLOWED_HOSTS = [h.strip() for h in _hosts.split(',') if h.strip()]
if not ALLOWED_HOSTS:
    raise ValueError('DJANGO_ALLOWED_HOSTS must be set in production (comma-separated).')

_sqlite_path = str(BASE_DIR / 'db.sqlite3').replace('\\', '/')
DATABASES = {
    'default': env.db(
        'DATABASE_URL',
        default=f'sqlite:///{_sqlite_path}',
    )
}

if not DEBUG:
    SECURE_SSL_REDIRECT = env('DJANGO_SECURE_SSL_REDIRECT')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
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
