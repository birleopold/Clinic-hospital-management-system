# UG HMS — Roadmap

This roadmap turns the audit into sequenced work: **harden first**, then **trust & data**, then **Uganda/MoH alignment**, then **integrations & scale**.

## Phase A — Foundation & hardening

| ID | Deliverable | Status |
|----|-------------|--------|
| A1 | `store` role on `User` (aligned with inventory UI) | Done |
| A2 | `config.settings.test` + `pytest` + billing/order smoke tests | Done |
| A3 | `prod.py`: env-based `SECRET_KEY`, hosts, DB, HTTPS flags, WhiteNoise | Done |
| A4 | `STATIC_ROOT` + CI workflow (`pytest`) | Done |
| A5 | Document `DJANGO_*` / `DATABASE_URL` in deploy notes (below) | Done |
| A6 | `.env.example` for production template | Done |

**Deploy notes (production)**  
Set at minimum: `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` (comma-separated), `DATABASE_URL` (PostgreSQL recommended). Optional: `DJANGO_SECURE_SSL_REDIRECT=1` behind TLS, `DJANGO_USE_X_FORWARDED_PROTO=1` behind a reverse proxy. Run `collectstatic` before release when using WhiteNoise.

## Phase B — Trust, RBAC, and multi-facility

| ID | Deliverable | Status |
|----|-------------|--------|
| B1 | **django-guardian** enabled (`INSTALLED_APPS` + `ObjectPermissionBackend`) for future per-object rules | Done |
| B2 | **Facility FK** on `Patient` and `Encounter`; `common.facility_scope` filters on DRF + key UI views | Done |
| B3 | Backup/restore runbook; rotation for DB and media | Done |
| B4 | Consent / retention fields and export deletion workflow (DPPA-oriented) | Done |

See [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md) for procedures and `python manage.py backup_snapshot`. Patient consent and optional `data_retention_until` are on `Patient`; bulk deletion remains a manual/policy step.

**Facility scoping rules**

- If `user.staff_profile.facility` is set, list/detail views and APIs restrict to that `facility_id` (via `patient__facility_id` or `encounter__facility_id` as appropriate).
- **Superusers** and users **without** a facility on their staff profile still see **all** rows (migration / head-office mode).
- New patients created in UI or via API receive the creator’s facility when none is supplied.
- Run `python manage.py migrate` after pull: new columns + **guardian** tables. If exactly one `Facility` exists in the DB, existing patients are backfilled to it.

## Phase C — Uganda MoH / HMIS

| ID | Deliverable | Status |
|----|-------------|--------|
| C0 | Starter: `export_operational_csv` management command (daily aggregates CSV) | Done |
| C1 | HMIS-oriented monthly CSV bundle (`export_hmis_monthly`) | Done |
| C2 | Aggregates: OPD visits, diagnoses mix, service revenue by code (in monthly bundle) | Done |
| C3 | Diagnosis `coding_system` (ICD-10 / WHO-MoH / local) for register alignment | Done |

Reference: [HMIS_EXPORTS.md](HMIS_EXPORTS.md) for column dictionaries. [UgandaEMR reporting](https://mets-programme.gitbook.io/ugandaemr-documentation/reporting/ugandaemr_reports) remains a checklist, not a mandate to replicate OpenMRS.

## Phase D — Integrations & async

| ID | Deliverable | Status |
|----|-------------|--------|
| D1 | `integrations` app: SMS + MoMo backends (`NoOp*`, `LogSmsBackend`, `SandboxMoMoBackend`) via `get_sms_backend()` / `get_momo_backend()` | Done |
| D2 | Celery app (`config/celery.py`), broker settings, `integrations.health_ping` sample task (beat schedules TBD) | Done |
| D3 | Read-only FHIR NDJSON export (`export_fhir_ndjson`) | Done |

**Celery / Redis:** set `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` (defaults `redis://127.0.0.1:6379/0`). Run worker: `celery -A config worker -l info`. **SMS/MoMo:** override `INTEGRATIONS_SMS_BACKEND` / `INTEGRATIONS_MOMO_BACKEND` with dotted paths to backend classes (see `apps.integrations.backends`).

## Phase E — Hospital track

| ID | Deliverable | Status |
|----|-------------|--------|
| E+ | IPD/beds, theatre, referrals, vaccination campaigns | Planned (see `IMPLEMENTATION_PLAN.md` “Ongoing”) |

---

## Principles

- **Ledger**: keep financial corrections as new lines / explicit `source_ref` (already started for order cancellation).
- **API-first**: new features expose DRF + OpenAPI, UI consumes the same rules where practical.
- **One deployable path**: SQLite for dev/tests; PostgreSQL + static via WhiteNoise for production.
