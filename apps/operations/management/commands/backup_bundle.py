"""Create a database/media bundle and verify SQLite restore without touching the live database."""

import hashlib
import json
import sqlite3
import tarfile
from pathlib import Path
from datetime import datetime, timezone
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create a private database/media backup bundle and integrity manifest."

    def add_arguments(self, parser):
        parser.add_argument("directory")

    def handle(self, *args, **options):
        folder = Path(options["directory"]).resolve()
        if folder.exists():
            raise CommandError(
                "Choose a new backup directory; existing backups are never overwritten."
            )
        folder.mkdir(parents=True, mode=0o700)
        sqlite = settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")
        database = folder / ("database.sqlite3" if sqlite else "database.dump")
        call_command("backup_snapshot", str(database), pgdump=not sqlite)
        if sqlite:
            with sqlite3.connect(database) as restored:
                if restored.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise CommandError("Backup integrity check failed.")
                if restored.execute("PRAGMA foreign_key_check").fetchone():
                    raise CommandError("Backup contains foreign-key inconsistencies.")
        media = Path(settings.MEDIA_ROOT)
        with tarfile.open(
            folder / "media.tar.gz", "w:gz", dereference=False
        ) as archive:
            if media.exists():
                archive.add(media, arcname="media")
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "engine": settings.DATABASES["default"]["ENGINE"],
            "sqlite_integrity_verified": sqlite,
            "files": {},
        }
        for file in (database, folder / "media.tar.gz"):
            file.chmod(0o600)
            with file.open("rb") as stream:
                manifest["files"][file.name] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
        (folder / "manifest.json").chmod(0o600)
        self.stdout.write(str(folder))
