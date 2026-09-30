# Expanded clinic suite — 30 September 2026

This release extends the [initial suite](SUITE_RELEASE.md). It is an integrated application release, **not a claim of clinical certification, national reporting conformance or production acceptance**. The original [roadmap](OPERATIONS_ROADMAP.md) remains a design reference.

## Implemented workflows

| Area | Available behavior |
| --- | --- |
| Identity | Printable MRN/QR cards; confirmed duplicate review and privileged, audited merge; original patient and historical records retained; current records relinked; portal grants revoked; aliases redirect to the canonical patient. |
| Laboratory | Facility panels and analytes, configured units/reference ranges, received-specimen enforcement, accession QR labels, numeric validation, existing reviewer release, amendments and critical-result acknowledgment. |
| Inpatient | Existing beds/admissions/transfers/discharge plus time-bounded medication orders, due-dose rounds, stop orders and nursing care plans. Dose appropriateness remains the prescribing clinician's responsibility. |
| Stock | Package-to-base-unit conversion, reorder worklist and supplier-credit reconciliation, alongside location balances, controlled dispensing, receipts, transfers and reviewed stock counts. |
| Insurance | Verified member policies, dated code-specific/default percentage coverage, authorization requirements, per-line payer/co-pay snapshots, CSV claim allocations and idempotent remittance posting. Insurer electronic submissions are not implemented. |
| Payments | Durable MTN collection references, explicit request and authenticated status polling, amount/currency/reference matching and review of ambiguous/mismatched transactions. Insurance/mobile-money receipts are distinct from cash. Provider refunds require the original provider process. |
| Messaging | Africa's Talking SMS adapter, durable local send keys, signed-by-secret delivery endpoint and monotonic terminal delivery states. A timeout is held for reconciliation instead of risking a repeated send. |
| Access | Facility-scoped workspaces, archived-patient write rejection, system-superuser-only global Django admin, database-backed login throttling and private response caching controls. |
| Operations | Database/media backup bundles and hashes, SQLite integrity checks, health command, collection reconciliation and example systemd schedules. |
| Reporting | Facility-required FHIR/HMIS exports, CSV formula protection, approved-mapping readiness checks and a wrapper for an official supplied FHIR validator/implementation guide. |
| UI | Search and pagination, MRN labels, responsive workspaces/forms, keyboard-scrollable tables, stronger contrast and locally hosted assets. |

## Upgrade and operate

Back up the database/media before upgrading. Install `requirements-core.txt`, run `python manage.py migrate`, `python manage.py check`, and `python manage.py collectstatic --noinput`. Review facility assignments and role permissions before pilot use. Migrations add tables/columns; existing records are not automatically merged or assigned clinical reference ranges.

Configure secrets outside git using `.env.example`. The provider adapters deliberately do not require credentials for ordinary clinic operation. Confirm SMS consent and use synthetic accounts for commissioning. Core LAN workflows do not require internet, but this is **not offline browser synchronization**.

Commands:

```sh
python manage.py operations_health
python manage.py dispatch_reminders
python manage.py reconcile_collections
python manage.py backup_bundle /secure-backups/clinic-YYYY-MM-DD
python manage.py reporting_readiness --help
python manage.py validate_fhir_export --help
```

The examples under `deploy/systemd/` assume `/opt/clinic`, a `clinic` service user and `/etc/clinic.env`; adapt them to the installation. They are not automatically installed/enabled. Schedule backups on encrypted storage with off-host copies and a facility-approved retention policy. Restrict backup access: they contain patient data. PostgreSQL bundles require `pg_dump`; restore with `pg_restore` into a **separate disposable database**, restore media separately, check counts and sample workflows, then record the drill. SQLite integrity verification is not a substitute for a full operational restore drill.

For SMS, register `/integrations/sms/delivery/?token=<secret>` as the callback URL over HTTPS. Ensure reverse-proxy access logs omit query strings. Delivery callbacks require a configured secret of at least 32 characters. Provider acceptance does not mean handset delivery. The adapter uses local at-most-once keys, not provider-native idempotency: after an ambiguous timeout reconcile with provider support/dashboard before creating a replacement reminder. MTN uses authenticated polling; no unauthenticated success callback can credit an invoice. Sandbox success never creates a live ledger payment. Validate production credentials, currency and target environment with MTN before enabling collection requests.

## Validation and limitations

Original expanded-release verification: 112 tests passed on SQLite; two PostgreSQL-only contention tests were intentionally skipped there. The subsequent specialty release adds dedicated regression tests, a third PostgreSQL contention test and broader browser coverage; see [SPECIALTY_WORKFLOWS.md](SPECIALTY_WORKFLOWS.md). CI runs Python 3.11/3.12 with SQLite/PostgreSQL and executes those contention tests on PostgreSQL. Browser checks exercised home, results, insurance preparation, stock and medication-round pages; HTTP responses, JavaScript errors, desktop/mobile overflow and automated WCAG checks were checked. Manual assistive-technology testing and complete role-by-role staff acceptance remain necessary. The reusable browser script is `scripts/browser_smoke.cjs`; it requires Playwright, axe-core, a running disposable instance and staff test credentials.

Live provider transactions, official HL7 validation against the facility's chosen guide and a PostgreSQL restore drill have **not** been performed in this environment. Never use a public validation endpoint for patient records. The official validator can access terminology/package services; configure approved local/offline resources before using identifiable exports.

## Remaining work and decisions

See [CARE_AND_RECOVERY_RELEASE.md](CARE_AND_RECOVERY_RELEASE.md) for the latest delivered controls, verification and remaining scope.

- Facility staff must approve clinical catalogs, reference ranges, coverage contracts, identifiers, permissions and workflow acceptance scenarios.
- HMIS indicator mappings and national submission formats require approved current specifications and comparison with facility registers. Readiness checks do not certify those indicators.
- Insurer-specific electronic claim transport, automated original-provider refunds and additional payment providers remain separate integrations.
- Theatre scheduling, maternity episodes/visits, vaccination documentation and rehabilitation plans/sessions are now implemented. See [SPECIALTY_WORKFLOWS.md](SPECIALTY_WORKFLOWS.md) for exact depth, acceptance checks and remaining specialty requirements.
- Governed medication-interaction/dose decision support, cross-device offline conflict resolution and validated performance targets are not implemented.
- Patient merges must be done during a quiet registration window: audited merge and archived-patient validation are present, but a comprehensive simultaneous-write merge protocol across every legacy entry point remains a hardening task.

## Primary integration references

- [MTN request-to-pay examples](https://momodeveloper.mtn.com/content/html_widgets/v98wn.html)
- [MTN Uganda Open API](https://www.mtn.co.ug/helppersonal/mtn-open-api/)
- [Africa's Talking documentation](https://developers.africastalking.com/)
- [HL7 FHIR R4 validation](https://www.hl7.org/fhir/R4/validation.html)

These references guide adapter behavior; provider certification and operational acceptance are separate from code implementation.
