# Clinic / Hospital Management System

A Django application for outpatient clinic operations: registration, appointments, service queues, encounters, laboratory orders, pharmacy, stock, procurement, billing and reporting. The UI uses Django templates and HTMX; the REST API uses Django REST Framework and JWT/session authentication.

**Status:** development / pilot software. Core workflows exist, but this is not a validated production clinical system. Read the [audit](docs/AUDIT.md) before using real patient data and the [research-based feature plan](docs/OPERATIONS_ROADMAP.md) for the next milestones.

## Integrated clinic suite

Open `/suite/` for the staff workspace, patient history, laboratory review, stock operations, finance controls, referral tracking and inpatient basics. Existing module screens remain connected through the shared navigation. Read [the suite release and upgrade guide](docs/SUITE_RELEASE.md) before migrating existing data. External integrations and advanced roadmap items remain explicitly tracked there.

## Existing modules

| Area | Implemented capability |
| --- | --- |
| Accounts | Staff roles, facilities, departments and staff profiles |
| Registration | Patient demographics, contact/insurance fields, consent records, phone-based duplicate warnings in the UI |
| Appointments | Clinician availability, time off, scheduling and service queues |
| Encounters | Visit notes, vitals, diagnoses, visit-linked prescriptions and orders |
| Laboratory | Orders, free-text results and attachments; structured samples and result approval are not implemented |
| Pharmacy | Prescriptions, dispensing and backorders; stock safety/concurrency work remains |
| Inventory | Items, batches, movements, suppliers, purchase orders, goods receipts, CSV/XLSX imports |
| Billing | Price lists, automatic order/dispense invoice lines, cancellation credits, cash payments and cash sessions |
| Reports | Revenue, patient counts, service mix, CSV/XLSX exports and optional PDF printing |
| Audit | Request metadata and model histories; request audit records are read-only in Django admin |
| Integrations | Celery setup and placeholder SMS/MoMo backends; no live payment/SMS provider is connected |
| Patient portal | Expiring signed links; individual link revocation and result-release approval still need implementation |

## Requirements

- Python **3.11 or 3.12** recommended (tested locally on 3.12; CI is configured for both).
- Django **5.2 LTS** and DRF **3.16**. Dependency ranges are in `requirements-core.txt`.
- SQLite for local development. Use PostgreSQL for production transaction/locking behavior.
- Redis only if you run Celery tasks. Basic synchronous screens do not require Redis.
- No Node build step is required. HTMX currently loads from a CDN, so offline use needs a locally hosted asset.

## Local setup

```bash
git clone https://github.com/birleopold/Clinic-hospital-management-system.git
cd Clinic-hospital-management-system
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# Linux / macOS
source .venv/bin/activate
```

Then run:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements-core.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and sign in with the username/password you created. The default settings module is `config.settings.local`. Local setup does not require a `.env` file; `.env` loading is provided by production settings.

For PDF generation, use `python -m pip install -r requirements.txt`. Without the optional PDF dependencies, browser printing and CSV/XLSX exports remain available but PDF requests return an error. Some PDF dependencies may need platform-specific build tools.

## First-time configuration

1. Sign in to `/admin/` as the superuser. Create a **Facility** and any departments.
2. Create each user's account and choose the appropriate role. Roles include `admin`, `reception`, `nurse`, `clinician`, `lab`, `pharmacy`, `cashier`, `manager` and `store`.
3. Create a **StaffProfile** for each non-superuser and assign a facility. Unassigned staff cannot access patient-scoped records. The `admin` role alone does not bypass facility scoping; only a superuser does.
4. Configure the clinic name, receipt paper, active price list and service/item prices in admin. Configure clinician availability before booking appointments.
5. Register patients using an assigned staff account so facility assignment is automatic. If importing existing patients/encounters, assign their facilities explicitly before ordinary staff use them.

For a disposable demonstration only:

```bash
python manage.py seed_demo
python manage.py seed_demo_flow
```

These commands add sample prices/stock and a sample patient/visit. Re-running the flow adds new billable activity. Demo records have no facility by default and are visible to the superuser; assign them a facility to demonstrate staff workflows. Do not run these commands on a live clinic database.

## Useful routes

| URL | Purpose |
| --- | --- |
| `/` | Dashboard |
| `/admin/` | Administrative configuration |
| `/patients` | Patient registration/list |
| `/appointments/schedule` | Calendar |
| `/queues` | Service queues |
| `/pharmacy` | Pharmacy board |
| `/inventory/stock` | Inventory |
| `/cashier` | Cash desk |
| `/api/docs/` | Interactive OpenAPI documentation |
| `/api/schema/` | API schema |
| `/api/auth/token/` | POST username/password to obtain JWT access/refresh tokens |
| `/api/auth/token/refresh/` | POST refresh token for a new access token |

Use `Authorization: Bearer <access-token>` for JWT API requests. Session-authenticated writes require CSRF protection. Payment and dispense APIs support creation/list/retrieval only; editing or deleting those ledger entries is disabled. Payments must be positive, within the outstanding invoice balance, and are assigned to the authenticated cashier's open session.

## Checks and tests

```bash
python -m pip check
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest -q
```

Tests use isolated SQLite by default. For a **disposable** PostgreSQL test instance, set `TEST_DATABASE_URL=postgres://USER:PASSWORD@localhost:5432/hms_test_base`; Django creates a separate test database and the user must have permission to create it. Never point test configuration at the live database. GitHub Actions is configured to run SQLite/PostgreSQL with Python 3.11/3.12.

## Production configuration and upgrades

Use the [deployment and upgrade guide](docs/DEPLOYMENT.md). Production settings require a strong secret, explicit hosts and `DATABASE_URL`. Debug mode and wildcard hosts are rejected; HTTPS redirect and secure cookies default on.

```bash
# Example for Linux; set these in your process manager as well.
export DJANGO_SETTINGS_MODULE=config.settings.prod
python manage.py check --deploy
python manage.py migrate --noinput
python manage.py collectstatic --noinput
```

Serve `config.wsgi:application` or `config.asgi:application` with an appropriate production server behind HTTPS. `runserver` is only for development. PostgreSQL, TLS termination, process supervision and private media delivery are deployment responsibilities; this repository does not install them automatically.

## Background work and exports

```bash
celery -A config worker -l info
python manage.py backup_snapshot backups/hms.sqlite3
python manage.py export_operational_csv --days 30 -o exports/operations.csv
python manage.py export_hmis_monthly --year 2026 --month 9 --output-dir exports/hmis
```

Create the `exports/` directory before writing individual output files. Use the same `DJANGO_SETTINGS_MODULE` as your app for production commands/workers. These management exports run with database-wide administrative access. HMIS-oriented CSVs are **not** official electronic submissions, and the minimal FHIR NDJSON export is **not** a complete FHIR server.

## Project layout

| Directory | Contents |
| --- | --- |
| `apps/` | Business modules, models, APIs, UI handlers and migrations |
| `common/` | Role permissions, facility scoping, scoped serializers and export helpers |
| `config/` | Settings, URLs, WSGI/ASGI and Celery |
| `templates/` | Server-rendered screens and print templates |
| `tests/` | Regression and operational checks |
| `docs/` | Audit, deployment, backup, reporting and feature plans |

## Documentation

- [Code audit and outstanding risks](docs/AUDIT.md)
- [Operations and feature research](docs/OPERATIONS_ROADMAP.md)
- [Deployment and upgrade instructions](docs/DEPLOYMENT.md)
- [Backup and restore](docs/BACKUP_AND_RESTORE.md)
- [HMIS exports](docs/HMIS_EXPORTS.md)
- [Earlier roadmap](docs/ROADMAP.md)

No project license has been selected in this repository. Confirm ownership and choose a license before distributing or incorporating third-party code. The research document links reference projects; their source code has not been copied into this project.

## Expanded suite

See [expanded workflows and deployment checks](docs/EXPANDED_SUITE.md) for patient merging, laboratory catalogs, inpatient rounds, coverage/co-pay, provider integrations, UI improvements and explicit remaining work.

The [specialty workflow release](docs/SPECIALTY_WORKFLOWS.md) adds theatre scheduling, maternity visits, vaccination administration records, rehabilitation and a follow-up dashboard.

The [care and recovery release](docs/CARE_AND_RECOVERY_RELEASE.md) adds vaccine stock/corrections, cold-chain quarantine, delivery/newborn records, theatre count verification, and isolated backup/restore checks. It also fixes the PostgreSQL backorder locking failure found by CI.
