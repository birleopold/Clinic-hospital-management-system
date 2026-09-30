"""Restore a verified SQLite/media bundle into a NEW private drill directory."""

import hashlib
import json
import shutil
import sqlite3
import tarfile
from pathlib import Path, PurePosixPath
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Verify hashes and restore SQLite/media into a new isolated directory. Never replaces the running database."

    def add_arguments(self, parser):
        parser.add_argument("bundle")
        parser.add_argument("destination")
        parser.add_argument("--max-media-bytes", type=int, default=5 * 1024**3)

    def handle(self, *args, **options):
        source = Path(options["bundle"]).resolve()
        dest = Path(options["destination"]).resolve()
        if dest.exists():
            raise CommandError("Destination must be a new directory.")
        try:
            manifest = json.loads((source / "manifest.json").read_text())
        except (OSError, ValueError) as exc:
            raise CommandError("Unreadable backup manifest.") from exc
        if not manifest.get("engine", "").endswith("sqlite3"):
            raise CommandError(
                "This isolated drill supports SQLite. Use the PostgreSQL restore CI job/runbook for PostgreSQL dumps."
            )
        expected = {"database.sqlite3", "media.tar.gz"}
        if set(manifest.get("files", {})) != expected:
            raise CommandError("Unexpected manifest file list.")
        for name in expected:
            file = source / name
            if not file.is_file() or file.is_symlink():
                raise CommandError("Backup files must be regular files.")
            with file.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != manifest["files"][name]:
                raise CommandError(f"Checksum mismatch: {name}")
        # Validate the archive before creating any output. Never follow links or paths out of media/.
        with tarfile.open(source / "media.tar.gz", "r:gz") as archive:
            members = archive.getmembers()
            if sum(m.size for m in members) > options["max_media_bytes"]:
                raise CommandError("Media archive exceeds the configured size limit.")
            seen = set()
            for member in members:
                path = PurePosixPath(member.name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or not path.parts
                    or path.parts[0] != "media"
                    or not (member.isfile() or member.isdir())
                    or member.name in seen
                ):
                    raise CommandError("Unsafe or duplicate media archive member.")
                seen.add(member.name)
            dest.mkdir(parents=True, mode=0o700)
            restored = dest / "database.sqlite3"
            shutil.copyfile(source / "database.sqlite3", restored)
            restored.chmod(0o600)
            with sqlite3.connect(restored.as_uri() + "?mode=ro", uri=True) as db:
                db.execute("PRAGMA trusted_schema=OFF")
                if (
                    db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or db.execute("PRAGMA foreign_key_check").fetchone()
                ):
                    raise CommandError(
                        "Restored database failed integrity verification."
                    )
                counts = {}
                for table in (
                    "demographics_patient",
                    "encounters_encounter",
                    "billing_invoice",
                    "inventory_stockmovement",
                ):
                    if db.execute(
                        "SELECT 1 FROM sqlite_master WHERE type=? AND name=?",
                        ("table", table),
                    ).fetchone():
                        counts[table] = db.execute(
                            f'SELECT COUNT(*) FROM "{table}"'
                        ).fetchone()[0]
            for member in members:
                target = dest.joinpath(*PurePosixPath(member.name).parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with archive.extractfile(member) as content, target.open(
                        "xb"
                    ) as out:
                        shutil.copyfileobj(content, out)
                    target.chmod(0o600)
        report = {
            "database_integrity": "ok",
            "hashes_verified": True,
            "media_entries": len(members),
            "row_counts": counts,
            "operational_acceptance": "Staff must verify representative workflows before a production recovery.",
        }
        path = dest / "restore-report.json"
        path.write_text(json.dumps(report, indent=2))
        path.chmod(0o600)
        self.stdout.write(json.dumps(report))
