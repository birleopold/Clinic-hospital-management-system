# Operations and feature roadmap

Research and repository review: **29 September 2026**. This is a prioritized proposal based on the current code, not a claim that all features below are implemented. The review compared first-party documentation and public repository descriptions; it did not run or audit the reference systems.

## Implementation status

An integrated suite foundation is now implemented. See [SUITE_RELEASE.md](SUITE_RELEASE.md) for the exact available workflows, upgrade steps, validation and remaining work. The proposal below retains the original target scope and must not be read as a completion checklist.

## Recommendation

Build a dependable **outpatient clinic product first**, then expand to inpatient hospital workflows. The existing Django/HTMX architecture is suitable for that sequence. Keep one deployable application and extract shared transactional services for billing, dispensing and stock posting before adding more screens. A React rewrite or microservice split would not address the data-integrity gaps found in this review.

The next release should prioritize correct patient identity, safe stock dispensing, verified laboratory results, and daily cash reconciliation. Those are higher-value operational improvements than adding a large number of loosely connected modules.

## Reference projects and transferable patterns

| Source reviewed | Observed pattern | Application to this project |
| --- | --- | --- |
| [OpenMRS patient-management repository](https://github.com/openmrs/openmrs-esm-patient-management) | Distinct registration, search, active-visit, appointment, queue and ward modules | Make the active visit the organizing context; support handoffs between reception, triage, clinician, lab, pharmacy and cashier. |
| [OpenMRS stock-management repository](https://github.com/openmrs/openmrs-esm-stock-management) | Location-aware receipts/issues/transfers, stock counts, disposal, packaging units and approval workflows | Add stock locations and a transaction ledger; separate physical receipt, reservation and actual patient dispensing. |
| [Bahmni core repository](https://github.com/Bahmni/bahmni-core) and [feature overview](https://www.bahmni.org/feature-list/) | Connected clinical, laboratory, stock, billing and inpatient modules | Extend the existing modules around shared patient/visit identities; avoid isolated feature pages. |
| [Bahmni laboratory documentation](https://www.bahmni.org/laboratory/) | Sample labels, panels, result validation and external-lab referrals | Replace a single free-text result step with specimen tracking and approval before release. |
| [Bahmni billing documentation](https://www.bahmni.org/billing-and-accounting/) | Clinical orders connected to draft billing, expiry-oriented stock selection and financial records | Keep clinical orders linked to ledger entries, with explicit credit/refund workflows and safe batch allocation. |
| [OpenEMR repository](https://github.com/openemr/openemr) and [API authorization documentation](https://github.com/openemr/openemr/blob/master/Documentation/api/AUTHORIZATION.md) | Permission scopes distinguish resources, operations and patient/user/system contexts | Define permissions beyond a single role string and introduce narrowly scoped, revocable patient access. |
| [UgandaEMR repository](https://github.com/METS-Programme/openmrs-module-ugandaemr) | Uganda-focused patient transfers, queues, laboratory and pharmacy workflows, with operational reporting | Use it as a local workflow reference when interviewing facility staff; its existence does not establish this project's national reporting compliance. |
| [Marley Health repository](https://github.com/earthians/marley) and [Frappe appointment documentation](https://healthcare.frappe.io/patient-appointment) | Service units/departments and connections between appointments, encounters and billing | Model rooms, appointment duration and service type; carry registration and appointment details into the encounter without re-entry. The appointment documentation is version-specific and is used as a design reference. |
| [Open Hospital repository](https://github.com/informatici/openhospital) and [1.15.1 user guide](https://www.open-hospital.org/wp-content/OH_manuals/user/UserManual.html) | Main-store/ward inventories, stock-count validation and recorded balance adjustments | Build an explicit count-review-post workflow; distinguish a physical count from an approved stock adjustment. |

These are architectural references, not code dependencies or interchangeable Django modules. No source was copied. Any future source reuse needs a separate license/compatibility review.

## Current coverage and prioritized additions

Effort is relative: **S** = contained change, **M** = coordinated model/API/UI work, **L** = substantial workflow/integration work. These are planning sizes, not delivery promises. Acceptance criteria below are proposed engineering checks and need confirmation with clinic staff.

| Priority | Capability | Current gap | Proposed deliverable and acceptance criterion | Effort |
| --- | --- | --- | --- | --- |
| P0 | Pharmacy transaction safety | Dispense validation, stock deduction, prescription counters and billing are split across views/signals | One transactional service for UI/API/admin/commands. Two simultaneous requests for the last unit cannot both succeed; failures leave no partial stock, billing or prescription changes. | M |
| P0 | Expiry, stock receipt and backorders | Expired batches can be selected; posting a receipt can automatically create dispenses without confirming physical handover | Exclude expired/quarantined stock, order valid batches by expiry, require a pharmacy handover confirmation, and make receipt posting idempotent. Receiving goods must not itself document administration/dispensing to a patient. | M |
| P0 | Private records and access | Attachments use file URLs; read permissions remain broad; portal links have no individual revocation | Authenticated file downloads, a reviewed resource/action permission matrix, revocable portal grants, released-results-only access and access-log redaction. Test guessed IDs and revoked links. | M |
| P1 | Patient identity and continuity | Internal numeric PK and phone warnings; no durable medical-record number or safe merge | Facility-aware medical-record number, ID-card/barcode printing, guardian/next-of-kin fields and an audited duplicate-review/merge process. Never merge solely on a shared telephone number. | M |
| P1 | Clinical record completeness | Notes, vitals and diagnoses exist; no structured allergy/problem/medication history | Longitudinal summary with allergies (including unknown/no-known status), chronic problems, prior medications, clinician-signed notes and dated amendments. Clinical staff approve vocabulary and validation rules. | M |
| P1 | Laboratory operations | Free text and attachments; no specimen, analyte, approval or release workflow | Specimen accession/barcode, collected/received/rejected states, numeric/text analytes with units and configured reference ranges, reviewer approval, amended results and critical-result acknowledgment. Unapproved results never appear in the portal. | L |
| P1 | Queue and appointment integrity | Queues and availability exist, but transitions and booking conflicts are not uniformly enforced | Checked status transitions, triage priority, room/provider assignment, wait-time timestamps, atomic booking and no-show/follow-up lists. Repeated start/finish requests cannot corrupt timestamps. | M |
| P1 | Cash controls | Cash-only payment ledger and shifts; no formal refunds/voids/receivables | Unique receipts, immutable payment entries, supervisor-approved refunds/credits, invoice finalization and opening/closing reconciliation. Reports reconcile to ledger totals for each cashier and facility. | L |
| P1 | Stock operations | Global stock pool; direct batch updates can bypass movement history | Facility/store/dispensing locations, bin cards, units/pack conversion, stock-take approval, transfers, supplier returns, disposal reasons and reorder suggestions. Every balance change has a traceable movement. | L |
| P2 | Mobile money and SMS | No-op/sandbox adapters only | MTN/Airtel or aggregator integration after provider selection; unique transaction references, authenticated callbacks, idempotency, retries and reconciliation. Duplicate callbacks must not create duplicate payments. Reminders require consent and should omit clinical details. | L |
| P2 | Insurance and corporate accounts | Insurance provider/ID are free-text fields | Payer contracts, eligibility, coverage/exclusions, co-pay, preauthorization, claim preparation and rejection/resubmission tracking. Separate patient and payer balances. | L |
| P2 | HMIS and interoperability | Starter CSVs and minimal Patient/Encounter NDJSON | Versioned indicator definitions, validation/error reports, reviewed age/sex disaggregation and controlled mapping to the actual facility reporting process. Validate FHIR resources before attempting exchange. | L |
| P2 | Operational resilience | External HTMX CDN, manual backups, little monitoring | Local static assets, backup/restore drills, audit-failure alerts, failed-task queue and downtime procedures. Pilot LAN operation before attempting offline synchronization and conflict resolution. | M/L |
| P3 | Inpatient hospital operations | No admissions, wards, beds or nursing medication-administration record | Admission/transfer/discharge, bed occupancy, nursing observations, medication-administration record and discharge summary; later theatre/maternity/referral modules. A bed cannot have overlapping active occupants. | L |

## Suggested operational flow

1. **Reception:** search and verify patient identity, check consent/contact details, open a visit, record payer and enqueue.
2. **Triage:** capture vitals and priority, assign a room/provider, hand over the same visit.
3. **Clinician:** review longitudinal history, record assessment, sign the note, order investigations and prescribe.
4. **Lab:** collect/label specimens, perform tests, verify results, release them and obtain acknowledgment where needed.
5. **Pharmacy:** validate the prescription, reserve eligible batches, confirm actual handover, then post stock and billing together.
6. **Cashier:** settle the invoice or record approved payer credit, issue a receipt and reconcile the shift.
7. **Follow-up:** record disposition/referral and the next appointment; send consented reminders without exposing clinical content.

Payment policy must be configurable: the software should support a clinic's approved workflow without silently denying care solely because an invoice is unpaid. This is a workflow-design decision for the clinic, not an automated clinical rule.

## Implementation sequence and proposed data models

### Milestone 1 — reliable pilot

Complete P0 work and a restore drill. Extract `record_payment`, `record_dispense`, `post_goods_receipt` and `cancel_order` services with database transactions and consistent locking. Add PostgreSQL concurrent-request tests, not just SQLite tests. Reconcile existing invoice totals, cash-session balances, dispense quantities and batch movements before enabling the pilot.

Introduce identifiers and constraints where the workflow is clear: receipt identifiers, idempotency keys and stock-operation IDs. Prefer explicit correction records to rewriting financial/stock history. Give every action an actor, timestamp, reason and correlation identifier.

### Milestone 2 — complete outpatient operations

Candidate models: `PatientIdentifier`, `PatientMergeReview`, `AllergyRecord`, `Problem`, `ClinicalNoteRevision`, `Specimen`, `LabAnalyteResult`, `ResultApproval`, `ResultAcknowledgment`, `InvoiceAdjustment` and `Refund`. Define draft/final/amended states before building forms. Preserve clinician authorship and the original finalized content.

Candidate inventory models: `StockLocation`, `StockOperation`, `StockOperationLine`, `StockCount` and `StockTransfer`. The current `Batch` can be retained as the lot identity, with balances explicitly tied to a location. Map historical global stock to an approved opening location during migration.

### Milestone 3 — connectivity and management

Add provider-backed mobile money/SMS, payer contracts, reconciliation dashboards and reporting mappings. External calls should use an outbox/retry mechanism so network failure cannot leave a clinical operation half-complete. An integration is not finished until timeout, retry, duplicate callback and reconciliation scenarios are tested.

### Milestone 4 — hospital expansion

Only after outpatient workflows are stable: wards/beds, admissions/transfers/discharges, inpatient medication administration and specialty modules. Separate inpatient orders from actual administration. Interview nursing, lab, pharmacy and finance leads before defining these records.

## Uganda-specific validation

The code already uses `Africa/Kampala` and includes HMIS-oriented exports. The Ministry of Health's [EMRS implementation-guidelines catalog entry](https://library.health.go.ug/health-information-systems/digital-health/guidelines-implementation-electronic-medical-records) identifies national implementation guidance. The catalog/search summary was accessible during this review, but the full document download was not; no clause-level compliance assessment was performed.

Before claiming MoH/HMIS alignment, obtain the current authoritative guidance and the facility's approved reporting forms, review indicator definitions with the records officer, and validate a sample reporting period against the manual register. Add facility identifiers and approved code mappings where required. A CSV export, a consent checkbox, or use of an ICD-10 label does not by itself establish compliance or interoperability.

Use Uganda-relevant phone normalization and currency formatting, but confirm payer/provider contracts and reporting requirements rather than assuming them. Protect identifiers and clinical details in SMS, exports and support logs.

## Operational backlog from the extended comparison

The recommendations below are design proposals for this repository. Reference systems were inspected through their published repositories and documentation, not deployed or benchmarked. They complement the priorities above.

| Staff workflow | Feature to build | Operational rule |
| --- | --- | --- |
| Reception and triage | One active-visit board showing current station, assigned staff, priority and waiting time | Every handoff records sender, destination, time and acceptance; cancelled visits leave active queues. Public queue displays use ticket numbers. |
| Appointment desk | Appointment types, duration, provider/room availability, rescheduling reasons and no-show worklist | Check both provider and room conflicts; appointment completion links to the actual encounter. |
| Clinician | A concise patient summary and follow-up task list | Show allergy status and relevant history before prescribing; distinguish unknown history from an explicitly reviewed absence. |
| Laboratory | Worklists for awaiting collection, processing, review and release | Track specimen rejection and recollection; amendments retain prior results and reviewer identity. |
| Pharmacy | Partial dispensing, backorder worklist and actual handover confirmation | Show prescribed, handed-over and outstanding quantities separately. Receiving supplies must not mark medicine as delivered to a patient. |
| Storekeeper | Printable count sheets, variance review and approved stock posting | Use draft, reviewed and posted states; posting twice has no additional effect. Capture movements during counting or use an explicit count cutoff. |
| Cashier and supervisor | Shift close, tender breakdown, discrepancy reasons and refund approval | Expected cash is calculated from opening float and signed cash movements, including refunds and documented cash drops; it excludes mobile-money receipts. |
| Follow-up team | Referrals with destination, reason, due date and completion status | Record whether the referral was accepted/completed and who follows up; avoid treating a referral printout as confirmed care. |
| Facility manager | Exceptions dashboard with drill-down worklists | Show overdue results, unclosed visits, stockouts, expiring stock, unreconciled payments and failed background jobs. Each item needs an owner and next action. |

### Dashboard definitions to agree before implementation

These are proposed definitions, not national HMIS indicators. Show the reporting period, facility, timezone and missing-data count. Establish a pilot baseline before setting targets.

- **Waiting time:** service-start time minus arrival-at-that-station time; show median and 90th percentile by station. Exclude cancelled steps and flag missing timestamps.
- **Laboratory turnaround:** approved-release time minus specimen-received time, grouped by test; show rejected specimens separately.
- **No-show rate:** appointments explicitly marked no-show divided by due, non-cancelled appointments; exclude future appointments and expose unresolved statuses.
- **Prescription fulfillment:** prescribed lines completely handed over divided by eligible prescribed lines, with partial and unfilled lines shown separately. Define substitutions and cancellations explicitly.
- **Stock availability:** days with zero usable stock for each stocked item/location; usable stock excludes expired and quarantined units. Preserve daily history to calculate this reliably.
- **Cash variance:** counted closing cash minus expected closing cash; report per shift and require explanations and supervisor review for discrepancies.
- **Payment reconciliation:** count and value of external transactions unmatched to ledger entries, grouped by age.
- **Backup recovery:** last successful backup and last successful restore drill; a backup timestamp alone does not prove recoverability.

### Pilot acceptance scenarios

Run these with reception, clinical, laboratory, pharmacy and finance representatives using synthetic patients:

1. A returning patient is found, receives a visit, moves through triage and consultation, and leaves with a documented disposition.
2. A specimen is rejected, recollected, reviewed and released; the patient cannot view the unapproved result.
3. A prescription is partially filled, a receipt replenishes stock, and the remainder is handed over later without duplicate billing or fabricated dispensing.
4. A stock count finds a discrepancy; a supervisor approves one adjustment with a reason and a preserved audit trail.
5. A cashier records payment, corrects it through an approved refund, and closes a shift with matching ledger and cash totals.
6. Two staff attempt the last available appointment slot or stock unit; only one conflicting operation succeeds.
7. Internet access fails while the clinic LAN remains available; core workflows remain usable and queued integrations recover without duplicate messages or payments.
8. A backup restores into a separate environment and reconciles a sample visit, invoice and stock history.

### Features to defer until the first facility needs them

Inpatient beds and nursing administration, theatre scheduling, maternity records, vaccination schedules and rehabilitation can be separate later workstreams. Select them from actual services offered and staff ownership. Automated clinical recommendations require a separately governed clinical-content process. Keep the existing Django/HTMX application while strengthening its shared workflow services.

## Questions to resolve during workflow design

- Is the first installation a single outpatient clinic, several branches, or a hospital with beds?
- Which roles may view clinical details, financial data and cross-branch records?
- When is payment normally collected, and who can approve discounts, credit and refunds?
- Does the laboratory need numeric analytes/specimens or only external result documents initially?
- Are medicines stocked centrally, per branch, or in multiple stores within one facility?
- Which HMIS forms, insurers and payment/SMS providers are actually used?

These questions refine later milestones; they do not block the code-hardening changes in this audit release.
