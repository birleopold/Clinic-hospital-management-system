"""
Fast, isolated settings for pytest. Uses in-memory SQLite.
"""
from .base import *  # noqa: F401,F403

DEBUG = True
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}
ALLOWED_HOSTS = ['*', 'testserver']
