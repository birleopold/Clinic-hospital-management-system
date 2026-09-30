"""CI-only disposable PostgreSQL backup/restore drill. Refuses non-local servers.

Run after migrations using config.settings.test and TEST_DATABASE_URL pointing
at the ephemeral CI service. Production recovery uses the reviewed runbook.
"""

import os
import subprocess
import tempfile
from pathlib import Path
import sys
import django

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psycopg2
from psycopg2 import sql

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
django.setup()
from django.conf import settings
from django.db import connection

cfg = settings.DATABASES["default"]
if (
    connection.vendor != "postgresql"
    or cfg.get("HOST") not in ("localhost", "127.0.0.1")
    or not os.getenv("CI")
):
    raise SystemExit("Only run this drill against the disposable localhost CI service.")
connection.ensure_connection()
from apps.accounts.models import Facility
from apps.demographics.models import Patient
from apps.encounters.models import Encounter
from apps.billing.models import Invoice
from apps.inventory.models import InventoryItem, Batch, StockMovement

# Synthetic records ensure this tests data recovery, not merely schema restoration.
# The guard above prevents this script from running against non-local/non-CI servers.

if cfg["NAME"] != "hms":
    raise SystemExit("The CI source database must be named hms.")
facility = Facility.objects.create(name="Restore drill synthetic facility")
patient = Patient.objects.create(
    first_name="Synthetic", last_name="Restore drill", gender="O", facility=facility
)
Encounter.objects.create(patient=patient)
Invoice.objects.create(patient=patient, total_amount=10)
item = InventoryItem.objects.create(code="RESTORE-DRILL", name="Synthetic restore item")
batch = Batch.objects.create(item=item, quantity_on_hand=2)
StockMovement.objects.create(
    item=item, batch=batch, direction="in", quantity=2, reason="Synthetic drill"
)
target = "clinic_restore_drill"
# This script creates the target itself and never drops a pre-existing database.
admin = psycopg2.connect(
    dbname="postgres",
    user=cfg["USER"],
    password=cfg["PASSWORD"],
    host=cfg["HOST"],
    port=cfg.get("PORT") or 5432,
)
admin.autocommit = True
created = False
restored = None
try:
    with admin.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
        created = True
    env = os.environ.copy()
    env.update(
        PGHOST=cfg["HOST"],
        PGPORT=str(cfg.get("PORT") or 5432),
        PGUSER=cfg["USER"],
        PGPASSWORD=cfg["PASSWORD"],
    )
    with tempfile.TemporaryDirectory(prefix="clinic-restore-") as folder:
        dump = Path(folder) / "snapshot.dump"
        subprocess.run(
            ["pg_dump", "-Fc", "-d", cfg["NAME"], "-f", str(dump)], env=env, check=True
        )
        subprocess.run(
            [
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "-d",
                target,
                str(dump),
            ],
            env=env,
            check=True,
        )
        with psycopg2.connect(
            dbname=target,
            user=cfg["USER"],
            password=cfg["PASSWORD"],
            host=cfg["HOST"],
            port=cfg.get("PORT") or 5432,
        ) as restored:
            with connection.cursor() as original, restored.cursor() as copy:
                for table in (
                    "django_migrations",
                    "demographics_patient",
                    "encounters_encounter",
                    "billing_invoice",
                    "inventory_stockmovement",
                ):
                    query = sql.SQL("SELECT COUNT(*) FROM {}").format(
                        sql.Identifier(table)
                    )
                    original.execute(query)
                    copy.execute(query)
                    if original.fetchone() != copy.fetchone():
                        raise RuntimeError("Restored row count mismatch: " + table)
    print("PostgreSQL isolated restore and row-count checks passed.")
finally:
    if restored is not None:
        restored.close()
    if created:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target)))
    admin.close()
