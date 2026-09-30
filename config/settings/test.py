"""
Fast, isolated settings for pytest. Uses in-memory SQLite.
"""
from .base import *  # noqa: F401,F403
import environ

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

# CI can exercise the same suite on a disposable PostgreSQL database.
if os.getenv('TEST_DATABASE_URL'):
    DATABASES = {'default': environ.Env().db('TEST_DATABASE_URL')}

# Legacy role journeys are isolated from MFA; dedicated MFA tests explicitly enable it.
REQUIRE_ADMIN_MFA = False

# Setup enforcement has dedicated regressions; existing fixtures retain legacy defaults.
REQUIRE_SERVICE_SETUP = False
