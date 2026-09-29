# Repository audit — 29 September 2026

Baseline reviewed: `f82f3f0033bdb1b8af7cba7779a97da95aaddeaa` (`main`, initial project upload).

Scope: settings/dependencies, models, API serializers/viewsets, shared authorization, key HTML workflows, billing/stock signals, audit logging, exports, backup commands, migrations and existing tests. This is a source review with regression tests, not a penetration test, clinical validation, legal certification or complete line-by-line audit. No live database or real patient records were accessed.

## Outcome

The repository is a useful outpatient prototype with substantial workflow coverage. The initial two tests passed, but they covered only billable order creation/cancellation. Several access-control and operational gaps existed outside those tests. The changes below improve that foundation; unresolved pharmacy/data-integrity and private-file risks still block a production sign-off.

## Fixed in this change set

| Finding | Risk before change | Fix |
| --- | --- | --- |
| Unsupported framework series | Django 4.2 had reached end of support | Upgrade to Django 5.2 LTS and compatible DRF/filter/guardian/schema packages; deduplicate dependency files; POST logout |
| RolePermission skipped action-specific GET rules | A role could bypass an explicit action restriction; empty rules and unspecified writes were permissive | Resolve action/method/any rules first; empty rules deny, inactive users deny, unspecified writes deny |
| Facility scope applied to reads but not foreign-key writes | Staff could reference another facility's patient/encounter/order/prescription in API writes | Shared serializer scopes writable relations; validate matching patient/encounter and prescription links |
| Unassigned staff implicitly had global access | Missing profile/facility exposed all patient-scoped rows | Deny patient-scoped access until facility assignment; retain explicit superuser access |
| Reports and pharmacy UI had unscoped queries | Cross-facility records/aggregates were accessible in specific paths | Scope report APIs, prescription/backorder/dispense UI lookups and duplicate-patient warnings |
| Patient facility could be cleared/moved in API | A staff user could detach or reassign records outside their scope | Restrict facility relations, reject clearing, fix default facility assignment |
| Payment creation accepted invalid/negative amounts and client sessions | Financial totals could be corrupted or attributed to another cashier; concurrent read-modify-write totals could be lost | Validate decimal input before side effects, reject excess/cancelled payments, lock cashier/invoice/session, derive totals from ledger, select own session |
| Payment/dispense update/delete had no reconciliation | Editing ledger rows did not reverse dependent stock/billing totals | Expose create/list/retrieve only; correction workflows remain a roadmap item |
| Non-positive API order/dispense quantities | Negative stock/billing activity could be submitted | Positive finite decimal validation; prescription dispensed counter becomes read-only |
| Scheduling accepted zero/negative slot increments | Slot-generation loop could run indefinitely | Validate bounded positive intervals; reject malformed API parameters |
| Procurement mutations used GET | Links could alter stock/PO status without CSRF-protected POST | POST-only views and form buttons with CSRF tokens |
| Audit app had no migration | Normal clean migration did not create the audit table; tests could mask this via unmigrated-app synchronization | Add initial migration; make admin audit records read-only |
| Audit paths included searches and portal credentials | Logs could persist patient search text and signed bearer links | Remove query strings and redact portal-token paths; portal responses use no-store/no-referrer |
| Production configuration allowed weak defaults | Debug, wildcard hosts and silent SQLite fallback were possible; base integrations could miss `.env` values | Require strong secret/hosts/database, reject debug, default HTTPS, load `.env` before base |
| Missing report response schemas | OpenAPI generation omitted report response definitions | Add report response serializers and export content-type annotations |
| Report dates and day boundaries | Invalid dates raised errors; final fractional second omitted | Return validation errors and use local day bounds through `time.max` |
| Spreadsheet formula interpretation | User-controlled text could become formulas in web CSV/XLSX exports | Escape dangerous text prefixes while retaining numeric value types |
| SQLite file copying | Live/WAL snapshots could miss committed data | Use SQLite backup API; reject backing up over source; use configured PostgreSQL password for pg_dump |
| Missing README/CI and duplicate `gitignore` | Setup was unclear; roadmap claimed CI that was absent | Add setup/deployment/research documentation and CI; remove redundant filename; ignore backups/exports |

## Outstanding findings — required follow-up

| Priority | Evidence / location | Recommended next action |
| --- | --- | --- |
| P0 | `apps/pharmacy/signals.py`, `apps/pharmacy/ui_views.py`, `apps/pharmacy/views.py`: stock validation and decrement use separate steps; dispensing can include expired batches | Central transactional dispense service with row locks, eligible-batch checks, prescription consistency and rollback tests on PostgreSQL |
| P0 | `apps/inventory/ui_views.py::grn_post_view`: posting is not transactionally idempotent and auto-fulfills backorders as dispenses; some received totals count unposted GRNs | Locked receipt posting; count only posted receipts; separate replenishment/reservation from verified patient handover; test retries and concurrent posting |
| P0 | `OrderResult.attachment`, debug media URLs and portal attachment links | Private authenticated media delivery and file validation/scanning; do not publish MEDIA_ROOT as a public directory |
| P1 | Most clinical read actions still use broad authenticated fallback in RolePermission; UI/API role policies differ | Define and test a permission matrix per action and data type. Guardian installation alone does not enforce object permissions. Audit admin remains a trusted administrative surface. |
| P1 | Direct batch editing/admin writes and some management paths bypass service-layer invariants | Route all stock/financial mutations through services, add suitable database constraints and an explicit correction process |
| P1 | Orders remain editable after billing, totals rely on signals, and source_ref uniqueness alone does not govern every state transition | Define immutable finalized orders/invoices and credit adjustments; test cancellations after payment, retries and simultaneous billing |
| P1 | Appointment create/update and queue actions do not consistently enforce booking conflicts, time windows or status transitions | Shared scheduling/queue service, clinician/facility checks on custom actions, atomic conflict protection and transition tests |
| P1 | Inventory/price lists are global; facility-scoped related records can become inconsistent after privileged reassignment | Model stock locations and reassignment policy; audit historical patient/encounter relationships before multi-branch use |
| P1 | Portal links expire but cannot be individually revoked; lab results lack reviewed/released states | Store hashed/revocable grants, gate visible results, support amendments and monitor portal access |
| P1 | Session/JWT login lacks an explicit anti-brute-force policy; request audit failures only log exceptions | Configure rate limits, account controls, monitoring and alerting; review JWT history attribution and audit retention |
| P1 | Clinical fields are permissive; structured allergies/history and clinician note sign-off are absent | Clinical-led model/form validation, longitudinal record and signed/amended notes |
| P2 | CLI HMIS/FHIR exports have database-wide scope and may contain identifiable/free-text data | Add explicit facility filters, export permissions/metadata and formula neutralization for management CSVs; validate real reporting mappings |
| P2 | Core requirements use version ranges; optional PDF stack and full dependency CVE inventory not audited | Add a reviewed lock/constraint workflow and recurring vulnerability review; verify PDF behavior on deployment platform |
| P2 | HTMX CDN dependency and no tested offline strategy | Serve assets locally, monitor backups, rehearse downtime and design conflict-safe synchronization only if needed |

## Verification performed

- Baseline: 2 existing billing/order tests passed on Django 4.2.
- Expanded automated suite: **76 tests passed locally** on Python 3.12 / Django 5.2.17. Coverage includes role rules, facility isolation and relation writes, payment rejection/totals, invalid quantities, report scope/date handling, slot validation, pharmacy UI scope, audit redaction, formula-safe web exports, SQLite WAL backup, production settings, CSRF-protected procurement, logout and core-screen rendering.
- Runtime checks: dependency consistency (`pip check`), Django system checks, migration drift check, fresh SQLite migrations, static-file collection and OpenAPI validation with `--fail-on-warn`. Production checks with valid sample settings had only the deliberate HSTS subdomain/preload policy warnings after report schemas were added.
- CI configuration covers Python 3.11/3.12 and SQLite/PostgreSQL. Remote CI execution is separate from the local validation result; consult the repository Actions tab for run status.

Limitations: local tests used Python 3.12 and SQLite; PostgreSQL concurrency/load behavior, live providers, optional PDF rendering, browser end-to-end behavior and backup restoration of a real installation were not validated in this local audit. Tests reduce regression risk but do not prove the unresolved workflows safe.

## Rollout notes

Read [DEPLOYMENT.md](DEPLOYMENT.md) before upgrading. The important operational changes are mandatory staff facility assignment, a new audit migration, stricter production configuration, and append-only payment/dispense APIs. Existing stored data is not automatically reconciled or rewritten by this change set.

Reference: Django's [April 2026 support notice](https://www.djangoproject.com/weblog/2026/apr/07/security-releases/) confirms the end of Django 4.2 support. Operational research and source links are in [OPERATIONS_ROADMAP.md](OPERATIONS_ROADMAP.md).
