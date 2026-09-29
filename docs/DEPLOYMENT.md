# Deployment and upgrade guide

This guide describes configuration, not production certification. Resolve the release blockers in [AUDIT.md](AUDIT.md) before using live clinical data.

## Updating an existing checkout

Back up the database and media, test the upgrade against a restored staging copy, and stop application writes for the deployment window. Use Python 3.11/3.12 for the tested runtime path.

```bash
git pull --ff-only origin main
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python -m pytest -q
```

Use `requirements-core.txt` if PDF exports are not needed. Set `DJANGO_SETTINGS_MODULE=config.settings.prod` in the web server, worker and management-command environment before production operations. Restart web/worker processes after updating dependencies. The WSGI/ASGI entrypoints default to local settings if that environment variable is omitted.

### Behavior changes in the September 2026 audit release

- Django moves from 4.2 to 5.2 LTS; related DRF/filter/schema/guardian dependencies are updated. The full dependency file now includes the core file to avoid drift.
- Non-superusers **must have a StaffProfile with a facility** for patient-scoped reads/writes. Audit existing accounts and backfill legitimate patient/encounter facilities; unassigned records remain visible only to superusers.
- The new `audit.0001_initial` migration creates the request audit table. If your installation previously created that table with `migrate --run-syncdb`, inspect its schema first; only use Django's `--fake-initial` migration procedure after verifying it matches. Do not blindly fake migrations.
- Existing payment/dispense records cannot be rewritten through the API. No refund/correction endpoint is provided yet. Payment amounts cannot exceed the outstanding balance.
- Procurement approvals/cancellations/closing and goods-receipt posting now require POST plus CSRF tokens. Update external clients that used GET.
- Logout uses POST, matching Django 5.2.
- Production no longer silently falls back to SQLite or allows debug mode. `DATABASE_URL` is required.

## Environment

Copy `.env.example` to `.env` for production, fill in values, and restrict its filesystem permissions. Process environment variables take precedence over `.env` values. Generate a key locally with:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Keep the output private. Production rejects placeholder/weak secrets.

| Variable | Requirement/default |
| --- | --- |
| `DJANGO_SETTINGS_MODULE` | Set to `config.settings.prod` |
| `DJANGO_SECRET_KEY` | Required strong unique key, at least 50 characters |
| `DJANGO_ALLOWED_HOSTS` | Required comma-separated hostnames, without schemes; no `*` |
| `DATABASE_URL` | Required; PostgreSQL recommended |
| `DJANGO_DEBUG` | Must be `0` in production |
| `DJANGO_SECURE_SSL_REDIRECT` | Defaults to true; only disable for a deliberately isolated non-TLS staging setup |
| `DJANGO_USE_X_FORWARDED_PROTO` | Enable only when a trusted proxy strips user-supplied headers and sets the correct HTTPS header |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Optional comma-separated origins with schemes, e.g. `https://clinic.example.com` |
| `DJANGO_SECURE_HSTS_SECONDS` | Starts at 0; enable after verifying HTTPS, subdomains and recovery procedures |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Redis URLs; loaded from `.env` before base settings |
| `INTEGRATIONS_SMS_BACKEND`, `INTEGRATIONS_MOMO_BACKEND` | Dotted backend class paths; defaults are no-op placeholders |

Run `python manage.py check --deploy --settings=config.settings.prod`. HSTS warnings are expected until you configure an appropriate policy. `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` and `DJANGO_SECURE_HSTS_PRELOAD` default to false; enable them only when all relevant subdomains and the preload commitment are supported. Configure logging/alerts for audit persistence failures.

## Infrastructure and data protection

- Use a production WSGI/ASGI server, HTTPS reverse proxy and a process supervisor. Restrict database/Redis access to the application network.
- WhiteNoise serves collected static files. **Do not expose all of `MEDIA_ROOT` publicly**: order attachments may contain patient information. Protected authenticated downloads remain a release blocker.
- Portal links are bearer credentials. Redact their token paths in proxy/access logs; application audit redaction alone cannot sanitize upstream logs. Add per-link revocation and controlled result release before offering the portal publicly.
- Django admin is a privileged back-office interface and does not automatically inherit the custom API/UI facility filters. Limit access to trusted administrators; do not grant broad model permissions to branch staff.
- Inventory currently has a shared stock pool, not per-facility stock locations. Do not treat patient scoping as full multi-tenant isolation.
- Run backups with least-privileged infrastructure credentials and perform a restore drill. Keep sensitive exports outside the web root and out of Git.
- Review login throttling, private file storage, clinical validation, pharmacy/stock concurrency and dependency security advisories before a production launch.

## Rollback

Keep the previous code revision and a matching database/media backup. Test rollback on staging. Reverting code alone may not revert database migrations or business transactions; do not delete live clinical or financial records to make a rollback work.

References: [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/), [Django 5.2 release notes](https://docs.djangoproject.com/en/5.2/releases/5.2/), [DRF 3.16 compatibility](https://www.django-rest-framework.org/community/3.16-announcement/).
