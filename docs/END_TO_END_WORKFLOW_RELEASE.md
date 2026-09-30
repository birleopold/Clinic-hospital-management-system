# UI-connected workflow delivery

This delivery closes specific workflow gaps in R3 and the workforce, diagnostics,
patient-copy and configuration extensions. It does **not** declare R0–R5 or the
expanded backlog complete. [The implementation tracker](IMPLEMENTATION_TRACKER.md)
and [perspective checklist](PATIENT_STAFF_OWNER_BACKLOG.md) retain unfinished
engineering separately from provider commissioning and facility acceptance.

## Delivered workflows and entry points

| Workflow | UI entry point | Recorded outcome |
| --- | --- | --- |
| Expense disbursement evidence | Management → Expenses → Settlement evidence and reconciliation | Partial bank/mobile-money/separate petty-cash evidence against an approved obligation; another supervisor confirms or rejects it. |
| Expense cash flow | Management → Expense cash flow | Actual event-dated collections, disbursed refunds and confirmed expense settlements; source rows and CSV. This is cash flow, not profit. |
| Scoped patient links | Patient → Create patient link | Verified recipient/guardian evidence, explicit section/action scopes, issued grants and revocation. |
| Patient booking changes | Patient link → Upcoming bookings → Request a change; staff → Appointment requests → Review request | Requested reschedule/cancellation; independent reception decision updates the original appointment. |
| Patient feedback | Patient link → Send feedback; staff → Management → Cases | Retry-safe intake in the existing restricted complaint register; receipt/status without internal investigation details. |
| Reciprocal duty swaps | Workforce → Request reciprocal swap → Inbox | Two linked existing cover requests; both staff accept; an independent supervisor approves or rejects the pair atomically. |
| Missing clock-out | Workforce → Timesheets → Request correction → Inbox | After shift end, independently reviewed actual times close operational attendance and retain original events/history. |
| Diagnostic resources | Diagnostics → Order → Assignment | Operational equipment/room/operator reservations with duration and conflicts against diagnostic, appointment and theatre bookings in both directions. |
| Approved preparation | Diagnostics → Templates → Publish; order → Assignment; scoped patient link → Preparation instructions | Independently published source/language/version snapshot attached to the scheduled service; patient receipt acknowledgment visible to staff. Receipt does not establish clinical clearance. |
| Visit directions | Patient banner → Print visit directions | Existing queues, upcoming appointments, room directions, assigned diagnostics and approved instructions. No fabricated waiting-time estimate. |
| Discharge/follow-up copy | Admissions → Print discharge and follow-up | Actual clinician-recorded summary for a discharged admission and existing follow-up recalls. |
| Facility print branding | Setup → Facility configuration | Validated PNG/JPEG logo, A4/80mm defaults and footer in actual patient-facility invoice/receipt prints. |
| Departments and rooms | Setup → Departments / Service rooms | Scoped create/edit of existing department and room records, including room directions; duplicate names are rejected. |

Navigation and direct routes apply existing role, facility, MFA and enabled-service
controls. Selected-site owner/support scope now also applies to setup, staff,
branding and structure screens. Private logos use scoped delivery; printed copies
embed the actual patient's facility logo rather than another selected site.
An expenses-only installation excludes disabled billing sources and clearly marks
collections/refunds as excluded rather than reporting them as an empty ledger.

## Integrity and duplication

No replacement appointment, complaint, stock or patient/payment ledger is created.
Booking changes retain the appointment ID; feedback uses `ManagementCase`; swaps
use paired `ShiftCover` records; instructions and resource reservations extend the
existing `DiagnosticWorkItem`. A new `ExpenseSettlement` records the disbursement
evidence of an existing expense obligation, without claiming to execute a gateway
payment or withdraw money from an existing cashier session.

Settlement request keys are retry-safe and conflicting replays fail. Facility
locks serialize cross-expense account/transaction-reference checks and pending
plus confirmed evidence cannot exceed the approved expense. Rejected evidence
does not reserve an amount; its transaction reference remains preserved. Expense
invoice references are also checked across budgets at the facility.

Patient actions recheck signed-link scope, expiry/revocation and canonical identity
inside the write transaction. Existing grants preserve prior summary access;
newly issued links require explicit verified scopes. Enabled diagnostic services
filter patient instructions and result downloads. Released-result rules remain
in force. Instruction acknowledgment checks the current work-item revision and
patient before recording receipt.

Portal HTML uses `Referrer-Policy: same-origin`: native browser form submissions
retain CSRF origin verification while external destinations receive no referrer.
Binary downloads retain `no-referrer`. Responses are non-cacheable and audit paths
continue to redact signed tokens.

## Validation

The SQLite full suite passed **273 tests** with 17 PostgreSQL contention cases skipped
locally. Existing and new PostgreSQL cases run in the repository's Python 3.11/3.12
database CI matrix. New contention cases cover pending expense overcommit,
concurrent settlement replay and equipment reservations for different patients
and operators. Do not treat SQLite as evidence of PostgreSQL row-lock behavior.

`manage.py check`, `makemigrations --check --dry-run`, migration installation and
`git diff --check` pass. SQLite also passed reversal to operations `0031` and
re-upgrade on an empty disposable database. After real records use the new fields,
operational rollback requires restoring the release backup rather than removing
populated fields. The synthetic Chromium review covers the changed screens
at **1440, 768 and 390 pixels**, WCAG 2/2.1 AA axe checks, page overflow and JavaScript
errors. It submits settlement evidence, confirms it as a different supervisor,
submits anonymous patient feedback and a cancellation request, acknowledges
instructions and approves cancellation from reception. All browser checks passed.
This remains synthetic acceptance, not staff/assistive-technology/hardware sign-off.

Reproduce the UI review only against a migrated disposable database:

```sh
python scripts/seed_workflow_review.py --confirm-disposable
```

Then run the ordinary development server with the synthetic fixture's MFA/setup
gates disabled solely in that disposable test environment. Install Playwright and
axe-core for the Node harness and set `CLINIC_UI_FIXTURE` to the seed JSON output,
`CLINIC_TEST_PASSWORD` to the synthetic password in the seed script,
`CLINIC_TEST_URL` to that server and optionally `CLINIC_CHROMIUM_PATH` and
`CLINIC_AXE_PATH` to the local browser and axe files. Run:

```sh
node scripts/workflow_completion_browser.cjs
```

## Upgrade

Back up the database and private media, install `requirements-core.txt` (now
including Pillow image validation), run `python manage.py migrate --noinput` and
collect static files through the existing deployment workflow. This release adds
accounts migration `0009` and operations migrations `0032`–`0037`. The operations
field migrations temporarily remove/reinstall canonical-patient triggers around
SQLite table rebuilds; new guard states include the new indirect patient links.

Private media must remain private. Configure actual logos, room directions and
approved preparation text in the UI. Empty preparation templates do not generate
clinical instructions. Historical grants are not silently restricted or expanded
to the new action scopes.

## Still open

- Independent tenant ownership/isolation, tenant provisioning/suspension and
  cross-organization support boundaries. Shared catalog/suppliers/prices remain
  single-organization resources; independent SaaS tenants must remain disabled.
- Configurable approval/delegation limits, staffing minima/grace policies,
  employment lifecycle, source-linked handover escalation, broader access review,
  historical clinical/balance imports and richer operational dashboards.
- Supporting expense uploads, supplier aging, general-ledger export, accrual
  costing/profitability, specialist fee agreements, patient estimates/deposits,
  waitlist priority, self-service identity/recovery and translated patient copies.
- Specimen volume/reagent-consumption balances, mandatory device-specific QC
  policies/remediation, preparation clearance, retest/charge policies and external
  referral completion.
- Actual MTN commissioning, Airtel/refund adapters, WhatsApp, pilot payer,
  EFRIS/HMIS mappings, analyzer/LIS transport, PACS authorization and any justified
  teleconsultation provider. These require actual specifications/access; existing
  adapters, exports or viewer links are not commissioning evidence.
- Approved clinical program eligibility/indicators, drug/vaccine knowledge,
  specialty scales/partograph rules and multi-team resource validation.
- Pilot time/click/error measurements, clinical/staff acceptance, physical
  scanner/printer checks, production load targets and recovery acceptance.

These are unfinished requirements, not exclusions from the user's requested plan.
