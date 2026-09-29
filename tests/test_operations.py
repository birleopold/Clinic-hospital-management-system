import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError


def test_sqlite_backup_includes_committed_wal_data(tmp_path, monkeypatch):
    source = tmp_path / 'live.sqlite3'
    backup = tmp_path / 'copy.sqlite3'
    with sqlite3.connect(source) as connection:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE sample (value TEXT)')
        connection.execute("INSERT INTO sample VALUES ('committed')")
        connection.commit()
        monkeypatch.setitem(settings.DATABASES, 'default', {'ENGINE': 'django.db.backends.sqlite3', 'NAME': source})
        call_command('backup_snapshot', str(backup))
        with sqlite3.connect(backup) as restored:
            assert restored.execute('SELECT value FROM sample').fetchone() == ('committed',)
        with pytest.raises(CommandError, match='differ'):
            call_command('backup_snapshot', str(source))


def production_settings(overrides):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('DJANGO_', 'DATABASE_URL'))}
    env.update({
        'DJANGO_SECRET_KEY': 'test-only-strong-secret-0123456789abcdefghijklmnopqrstuvwxyz-ABCDE',
        'DJANGO_ALLOWED_HOSTS': 'clinic.example.com',
        'DATABASE_URL': 'sqlite:///:memory:',
    })
    env.update(overrides)
    return subprocess.run(
        [sys.executable, '-c', 'from config.settings.prod import DEBUG, SECURE_SSL_REDIRECT, SESSION_COOKIE_SECURE; assert not DEBUG; assert SECURE_SSL_REDIRECT; assert SESSION_COOKIE_SECURE'],
        cwd=Path(__file__).resolve().parents[1], env=env, text=True, capture_output=True,
    )


def test_production_has_secure_defaults():
    result = production_settings({})
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('overrides', [
    {'DJANGO_DEBUG': '1'}, {'DJANGO_SECRET_KEY': 'dev-secret-key'},
    {'DJANGO_ALLOWED_HOSTS': '*'}, {'DJANGO_ALLOWED_HOSTS': ''},
])
def test_production_rejects_unsafe_settings(overrides):
    assert production_settings(overrides).returncode != 0
