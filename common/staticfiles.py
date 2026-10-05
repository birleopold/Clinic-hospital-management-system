"""Content-versioned URLs for source assets in development and local reviews.

Production uses WhiteNoise's collected, content-hashed filenames instead. Keeping
the local URL tied to file bytes prevents current HTML from reusing an older CSS
or JavaScript response. This does not disable caching or require a browser reset.
"""
from hashlib import file_digest
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import StaticFilesStorage


class ContentVersionedStaticFilesStorage(StaticFilesStorage):
    def url(self, name):
        url = super().url(name)
        asset_name = urlsplit(name).path
        # runserver reads finder sources; non-debug review servers read STATIC_ROOT.
        # Never label an older collected response with the current source's hash.
        source = finders.find(asset_name) if settings.DEBUG else None
        if source is None:
            # A review server may serve collected files rather than source files.
            source = self.path(asset_name)
            if not Path(source).is_file():
                return url  # Preserve Django's normal missing-file/404 behavior.
        with open(source, "rb") as asset:
            version = file_digest(asset, "sha256").hexdigest()[:16]
        parts = urlsplit(url)
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "v"]
        query.append(("v", version))
        return urlunsplit(parts._replace(query=urlencode(query)))
