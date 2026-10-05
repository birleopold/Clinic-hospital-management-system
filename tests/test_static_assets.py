"""The initial HTML and its shell assets must describe the same UI generation."""
import gzip
import hashlib
import io
import json
import os
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from django.templatetags.static import static
from whitenoise.storage import CompressedManifestStaticFilesStorage

from common.staticfiles import ContentVersionedStaticFilesStorage


class PageAssets(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.stylesheets = []
        self.body = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.stylesheets.append(attrs)
        if tag == "body":
            self.body = attrs


def test_local_asset_url_is_content_versioned_not_time_or_browser_dependent(settings, tmp_path):
    settings.DEBUG = True
    source = tmp_path / "source"
    source.mkdir()
    asset = source / "shell.css"
    asset.write_text("body{color:red}")
    settings.STATICFILES_DIRS = [source]
    settings.STATIC_ROOT = tmp_path / "collected"
    storage = ContentVersionedStaticFilesStorage()
    first = storage.url("shell.css")
    assert first == storage.url("shell.css")
    assert parse_qs(urlsplit(first).query)["v"] == [hashlib.sha256(asset.read_bytes()).hexdigest()[:16]]
    # Updating bytes must change the URL even if timestamps/length are preserved.
    stamp = asset.stat()
    asset.write_text("body{color:tan}")
    os.utime(asset, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert asset.stat().st_size == stamp.st_size
    assert storage.url("shell.css") != first
    assert storage.url("shell.css") == storage.url("shell.css")


def test_local_asset_url_can_read_collected_files_and_preserve_missing_file_behavior(settings, tmp_path):
    settings.DEBUG = False
    settings.STATICFILES_DIRS = []
    settings.STATIC_ROOT = tmp_path
    (tmp_path / "collected.css").write_text("body{margin:0}")
    storage = ContentVersionedStaticFilesStorage()
    assert "?v=" in storage.url("collected.css")
    assert storage.url("absent.css") == "/static/absent.css"


def test_review_asset_version_matches_served_collection_not_different_source(settings, tmp_path):
    source = tmp_path / "source"
    collected = tmp_path / "collected"
    source.mkdir()
    collected.mkdir()
    (source / "shell.css").write_text("body{color:red}")
    (collected / "shell.css").write_text("body{color:tan}")
    settings.STATICFILES_DIRS = [source]
    settings.STATIC_ROOT = collected
    settings.DEBUG = False
    expected = hashlib.sha256((collected / "shell.css").read_bytes()).hexdigest()[:16]
    assert parse_qs(urlsplit(ContentVersionedStaticFilesStorage().url("shell.css")).query)["v"] == [expected]


@pytest.mark.django_db
def test_anonymous_shell_uses_one_blocking_canonical_stylesheet(client, settings):
    settings.DEBUG = True
    response = client.get("/accounts/login/")
    assert response.status_code == 200
    assets = PageAssets(response.content.decode())
    assert assets.stylesheets == [{"rel": "stylesheet", "href": static("css/workspace.css")}]
    assert "v" in parse_qs(urlsplit(assets.stylesheets[0]["href"]).query)
    assert "workspace-shell" not in assets.body.get("class", "")
    html = response.content.decode()
    assert html.index("css/workspace.css") < html.index("<script") < html.index("</head>")


@pytest.mark.django_db
@pytest.mark.parametrize("route", ["/suite/", "/accounts/control/", "/suite/tasks/", "/accounts/mfa/enroll/"])
def test_first_authenticated_response_and_navigation_use_same_complete_shell(client, settings, route):
    from apps.accounts.models import User

    settings.DEBUG = True
    client.force_login(User.objects.create_user(username="shell-review", role="admin", is_superuser=True))
    # No warm-up/reload is performed before inspecting the first route response.
    first = client.get(route)
    assert first.status_code == 200
    first_assets = PageAssets(first.content.decode())
    assert "workspace-shell" in first_assets.body["class"]
    assert first_assets.stylesheets == [{"rel": "stylesheet", "href": static("css/workspace.css")}]
    next_assets = PageAssets(client.get("/suite/").content.decode())
    reloaded_assets = PageAssets(client.get(route).content.decode())
    assert first_assets.stylesheets == next_assets.stylesheets == reloaded_assets.stylesheets


def test_shell_styles_are_self_contained_and_not_registered_with_offline_worker():
    css = (settings.BASE_DIR / "static/css/workspace.css").read_text()
    for selector in (".visually-hidden", ".workspace-topbar", ".workspace-shell header.workspace-sidebar", ".workspace-shell main", ".navigation-group", "@media print", "@media(max-width:1100px)"):
        assert selector in css
    assert "@import" not in css
    assert not (settings.BASE_DIR / "static/css/legacy-shell.css").exists()
    assert not (settings.BASE_DIR / "static/css/suite.css").exists()
    worker = (settings.BASE_DIR / "static/js/offline-sw.js").read_text()
    assert "workspace.css" not in worker
    assert "'/offline/'" in worker


def test_image_build_collects_a_production_compatible_manifest(tmp_path):
    from config.settings.static_build import STORAGES

    assert STORAGES["staticfiles"]["BACKEND"] == "whitenoise.storage.CompressedManifestStaticFilesStorage"
    with override_settings(DEBUG=False, STATIC_ROOT=tmp_path, STORAGES=STORAGES):
        call_command("collectstatic", interactive=False, verbosity=0, stdout=io.StringIO())
        manifest = json.loads((tmp_path / "staticfiles.json").read_text())
        name = manifest["paths"]["css/workspace.css"]
        assert name != "css/workspace.css"
        assert static("css/workspace.css") == "/static/" + name
        assert (tmp_path / name).read_bytes() == (settings.BASE_DIR / "static/css/workspace.css").read_bytes()
        # Compressed and identity encodings cannot ship different UI generations.
        assert gzip.decompress((tmp_path / (name + ".gz")).read_bytes()) == (tmp_path / name).read_bytes()
        assert CompressedManifestStaticFilesStorage().url("css/workspace.css") == "/static/" + name
    dockerfile = (settings.BASE_DIR / "deploy/tenants/Dockerfile").read_text()
    assert "collectstatic --noinput --settings=config.settings.static_build" in dockerfile
