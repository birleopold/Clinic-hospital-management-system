"""Build public static assets without runtime database access or secrets.

Use only for collectstatic during image construction. The runtime continues to
use config.settings.prod and its complete security/configuration validation.
"""
from .base import *  # noqa: F401,F403

DEBUG = False
STORAGES = {
    **STORAGES,
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
