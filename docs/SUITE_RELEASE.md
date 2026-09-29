# Integrated clinic suite release

29 September 2026. This release implements a connected operational foundation at **`/suite/`**, retaining the existing Django/HTMX application. It is not completion of every item in the research roadmap and is not a production certification. The full original roadmap remains in [OPERATIONS_ROADMAP.md](OPERATIONS_ROADMAP.md).

## Implemented workflows

| Area | Available in this release |
| --- | --- |
| Shared UI | Responsive workspace, shared forms/cards/tables, role-filtered module links, keyboard focus styling, skip navigation, empty states and locally hosted HTMX. Existing module screens inherit the shared styling. |
| Operations overview | Active visits, pending laboratory orders, admissions, referrals and exception counts for unreviewed results, overdue referrals, failed reminders and expiring stock. |
| Patient records | Stable UUID medical-record identifiers, guardian contacts, structured allergy/problem/medication history, append-only clinical notes with amendment ancestry and a patient summary. |
| Identity review | Same-person/different-person duplicate review with reviewer and history. This does **not** merge records or rewrite clinical/financial history. |
| Appointments | Appointment type, room, duration and facility-scoped booking form; provider and room conflict validation inside transactions; confirmation, cancellation and no-show actions. Existing scheduling/rescheduling screens remain. |
| Patient flow | Existing queues with checked transitions and preserved start/finish timestamps. Active-visit links connect the workspace to the existing encounter UI. |
| Laboratory | Specimen accession identifiers, collection/receiving/rejection, result analyte/value/units/reference-range fields, draft results, separate reviewer release, critical-result acknowledgment and amendment references. Superusers retain an explicit reviewer override. |
| Pharmacy | Transactional dispensing across stock, prescription counters and invoice lines; expiry/quarantine checks; facility-specific stock; immutable dispense records; outstanding prescription checks; explicit backorder handover. |
| Inventory | Facility stock locations, opening balances, transfers, quarantine/release, disposal/supplier-return movements, physical counts with separate approval and stale-count rejection. Repeated receipt posting has no additional effect and never creates a patient dispense. |
| Finance | Refund requests and supervisor approval against original payments, separate invoice credits, net cash aggregates, discrepancy explanations at shift closing and refund-adjusted revenue totals. |
| Payers | Facility payer directory and manual claim preparation, external-submission status, acceptance/rejection and resubmission tracking. Claim acceptance does not create a payment. |
| Referrals | Destination, reason, due date, acceptance and completion history. |
| Inpatient basics | Ward/bed directory, admission, occupancy protection, bed transfer, discharge summary, nursing observations and scheduled medication-administration outcomes. |
| Patient access | Individually revocable, expiring grants; released-results-only portal; authenticated staff downloads and grant-authorized patient downloads. Raw Django media serving is removed. |
| Reminders | Consented reminder outbox, cancellation/retry, delivery history and a dispatcher that refuses no-op/sandbox delivery. Real provider configuration remains required. |

New workspaces are server-rendered staff screens; a parallel public REST API for every new model is not included. Existing APIs remain available with tighter clinical read permissions. Batch balance mutations now use the stock workflow rather than direct batch API edits. The legacy inventory import is restricted to superusers and produces stock requiring location review.

## Upgrade and initialization

Back up the current database and media before applying schema changes. In the project's activated Python environment:

```bash
git pull origin main
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check
```

Restart the application service using the deployment's existing process manager, then visit `/suite/`.

1. Assign each staff member a facility and an appropriate role. Unassigned staff cannot use facility-scoped records.
2. Create stock locations, service rooms, wards/beds and payer entries from the suite.
3. As a superuser, use **Stock control → Assign legacy batch** to assign previously global batches to their correct locations. Do not assume all old stock belongs to the first facility. Batch assignment preserves movement history and records a zero-quantity assignment event.
4. Assign legacy purchase orders to the correct facility through the trusted administrative interface. New purchase orders use the staff member's facility. Select the matching receiving location before posting each receipt.
5. Verify every old stock balance and prescription counter against physical records before dispensing. Existing negative stock or historical over-dispensing is not silently repaired.
6. Existing portal links without persisted grants are intentionally invalidated. Issue fresh links from the patient portal-link screen; creation now requires POST.
7. Existing laboratory results default to unreleased. Review and release records explicitly before patient access. Amendment records preserve earlier releases.
8. Configure the web server so it does **not** publicly serve the clinical media directory. Removing Django's development media route does not change an existing Nginx/Apache media alias. Serve public static assets separately.
9. Review each role with clinic staff. Inpatient and clinical forms require clinical workflow acceptance before use with real patients.

## Reminder integration contract

Set `INTEGRATIONS_SMS_BACKEND` to a real provider adapter implementing:

```python
supports_idempotency = True

def send(to_e164, body, *, idempotency_key):
    # Provider implementation must enforce this key across retries.
    return {"ok": True, "ref": "provider-acceptance-reference"}
```

Schedule `python manage.py dispatch_reminders` only after provider setup and operational approval. It processes up to 100 due jobs per run, refuses simulated delivery, and uses a stable job idempotency key. `sent` means accepted by the provider, not a handset delivery receipt. A job left `processing` after a worker crash requires provider reconciliation before recovery. The command was tested against the no-op refusal path; no messages were sent during development.

Mobile-money collection, provider callback verification and reconciliation are **not** implemented by this release. Existing sandbox adapters must not be treated as successful payment collection.

## Validation performed

- **101 automated tests pass locally.** The suite includes prior regressions and new transaction, workflow, facility-isolation and screen-render checks.
- New cases cover expired/quarantined/insufficient stock, prescription over-dispensing, receipt rollback and repeat posting, backorder separation, stale counts, balanced stock transfers, refund/repayment reconciliation, invoice credits, portal revocation and draft-result isolation, reviewer separation, bed occupancy/transfer, discharged-admission rejection, provider/room conflicts and no-op reminder refusal.
- Django checks, migration drift, OpenAPI validation, static collection and dependency consistency are checked before commit.
- Local tests use SQLite. PostgreSQL concurrency and deadlock behavior require the configured PostgreSQL CI/deployment tests; SQLite passing is not evidence that row-lock contention was exercised.
- Actual desktop/mobile screenshot QA could not run: the environment lacked a browser and Chromium downloads repeatedly returned invalid archives. Server-side rendering of all new workspace routes is tested. Visual and interaction acceptance remains open.

## Work still required for the full roadmap

- Full audited patient merge with collision handling, identity-card/barcode printing, and canonical identity across historical records.
- Complete lab panels/reference-range catalogs, specimen-to-analyte linkage, barcode printing, machine interfaces and a governed clinical terminology catalog.
- Medication terminology, governed dose/interaction checks, specialty forms, inpatient order scheduling and more comprehensive nursing records. The administration log does not validate medical appropriateness.
- Packaging/unit conversion, reorder purchasing automation and reconciled supplier credit notes. Stock returns currently record physical movements only.
- Contract/eligibility rules, coverage exclusions, co-pay allocation, claim files and automated payer remittances. Claims currently provide a manual operational register.
- Real mobile-money/SMS adapters, authenticated callbacks, transaction reconciliation and provider delivery receipts.
- HMIS indicator validation against approved facility forms, FHIR conformance validation and exchange agreements. Existing exports are not certified national submissions.
- Automated backup scheduling, demonstrated restore drills, login throttling, operational alerting, richer wait-time/turnaround dashboards, automated accessibility/browser tests and offline synchronization.
- Review remaining trusted Django admin and legacy order-editing paths before production. This release restricts direct stock, payment and released-result admin edits, but does not provide comprehensive facility isolation for all Django admin models.

Use the roadmap's acceptance scenarios with synthetic patients first. New features are deliberately documented at their actual implementation level; completing this release does not mean every advanced hospital workflow is ready.
