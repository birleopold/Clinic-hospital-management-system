# Backup and restore

Operational guidance for **UG HMS** databases and static/media files. Adapt retention and tooling to your clinic’s IT policy and hosting environment.

## What to protect

| Asset | Typical location | Notes |
|-------|------------------|--------|
| Primary database | `DATABASE_URL` / `NAME` in Django settings | Authoritative clinical and financial data |
| Uploaded media | `MEDIA_ROOT` if used | Forms, scans, exports |
| Configuration secrets | Env / secret manager | Not in git; required for restore |

## SQLite (development / small pilots)

1. The command uses the SQLite backup API to capture a consistent database snapshot, including committed WAL data. Coordinate media backups separately; a database snapshot is not a synchronized media snapshot.
2. Create the database snapshot:

   ```bash
   python manage.py backup_snapshot /path/to/backups/hms-$(date +%F).sqlite3
   ```

   On Windows PowerShell you can pass an explicit path, for example:

   ```powershell
   python manage.py backup_snapshot C:\backups\hms-2026-05-13.sqlite3
   ```

3. **Restore**: stop the app, replace the SQLite file with the backup copy, start the app, run `python manage.py migrate` if the schema on disk is older than the code.

## PostgreSQL (recommended production)

1. Use **`pg_dump`** for logical backups (portable, version-aware). Example:

   ```bash
   pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" -Fc -f /secure/backups/hms-$(date +%F).dump
   ```

2. Optional: run the bundled command (requires `pg_dump` on `PATH` and the configured database password, `PGPASSWORD` or `.pgpass`):

   ```bash
   python manage.py backup_snapshot /secure/backups/hms.dump --pgdump
   ```

3. **Restore** (example with custom format):

   ```bash
   pg_restore -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" --clean --if-exists /secure/backups/hms.dump
   ```

   Test restores on a **non-production** database regularly.

## Media and static files

- **Media**: mirror `MEDIA_ROOT` with your object store or filesystem backup (rsync, cloud snapshot, vendor backup).
- **Static**: regenerated with `collectstatic`; backup is optional if you can rebuild from the same code version.

## Rotation and offsite

- Keep **daily** backups for at least 7–30 days, **weekly** longer, per policy.
- Store at least one copy **offsite** or in a different cloud region from production.
- Encrypt backups at rest; restrict access to backup credentials.

## Verification

- Monthly (or after major releases): restore to a staging DB, run `migrate`, smoke-test login and a patient lookup.
- Document who performs backups, where they are stored, and the **RPO/RTO** targets for your organisation.

## Deletion workflow (DPPA-oriented)

Archiving or deleting patient rows after `Patient.data_retention_until` (or clinic SOP) is **not automated** in this codebase. Use admin/legal process, then manual or scripted deletion in line with your policy; keep audit logs of any bulk operations.
