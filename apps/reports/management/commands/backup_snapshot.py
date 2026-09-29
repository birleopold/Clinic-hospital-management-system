import os
import sqlite3
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Snapshot the database: copy SQLite file, or run pg_dump for PostgreSQL (--pgdump).'

    def add_arguments(self, parser):
        parser.add_argument(
            'output',
            nargs='?',
            help='Destination path (required for SQLite or when using --pgdump).',
        )
        parser.add_argument(
            '--pgdump',
            action='store_true',
            help='Run pg_dump -Fc for the default PostgreSQL database.',
        )

    def handle(self, *args, **options):
        output = options.get('output')
        db = settings.DATABASES['default']
        engine = db['ENGINE']

        if 'sqlite' in engine:
            if not output:
                raise CommandError('SQLite: provide output path, e.g. backups/hms.sqlite3')
            src_path = Path(db['NAME'])
            if not src_path.is_file():
                raise CommandError(f'SQLite database file not found: {src_path}')
            dest = Path(output)
            if dest.resolve() == src_path.resolve():
                raise CommandError('Backup destination must differ from the live database.')
            dest.parent.mkdir(parents=True, exist_ok=True)
            # SQLite's backup API includes committed WAL data and a consistent snapshot.
            with sqlite3.connect(src_path) as source, sqlite3.connect(dest) as target:
                source.backup(target)
            self.stdout.write(self.style.SUCCESS(f'Backed up {src_path} -> {dest}'))
            return

        if 'postgresql' in engine or engine.endswith('postgis'):
            if not options['pgdump']:
                self.stdout.write(
                    'PostgreSQL detected. See docs/BACKUP_AND_RESTORE.md, or run:\n'
                    '  python manage.py backup_snapshot /path/to/hms.dump --pgdump'
                )
                return
            if not output:
                raise CommandError('Provide output path for pg_dump.')
            host = db.get('HOST') or 'localhost'
            port = str(db.get('PORT') or '5432')
            user = db.get('USER') or ''
            name = db.get('NAME') or ''
            dest = Path(output)
            dest.parent.mkdir(parents=True, exist_ok=True)
            cmd = [
                'pg_dump',
                '-h',
                host,
                '-p',
                port,
                '-U',
                user,
                '-d',
                name,
                '-Fc',
                '-f',
                str(dest),
            ]
            env = os.environ.copy()
            if db.get('PASSWORD'):
                env['PGPASSWORD'] = db['PASSWORD']
            try:
                subprocess.run(cmd, check=True, env=env)
            except FileNotFoundError as exc:
                raise CommandError('pg_dump not found on PATH') from exc
            except subprocess.CalledProcessError as exc:
                raise CommandError(f'pg_dump failed with exit code {exc.returncode}') from exc
            self.stdout.write(self.style.SUCCESS(f'Wrote PostgreSQL custom-format dump to {dest}'))
            return

        raise CommandError(f'Unsupported database engine: {engine}')
