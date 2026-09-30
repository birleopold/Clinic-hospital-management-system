# Suite implementation tracker

Source of truth: [competitive research and implementation plan](COMPETITIVE_RESEARCH_AND_PLAN_2026-09.md). Started 30 September 2026. No planned scope has been removed. An item is **partial** when only some acceptance criteria have been met. Dependencies do not mean cancellation.

## Phase 1: daily workflow implementation

The Phase 1 software scope is implemented. See [release evidence and deployment notes](PHASE_ONE_RELEASE.md). Facility staff acceptance, manual assistive-technology review and production load acceptance remain open gates; this is not a claim of clinical deployment sign-off. All R2–R5 scope below remains tracked.

## R0 — baseline and design

| ID | Requirement | Status / next evidence |
| --- | --- | --- |
| R0-01 | Synthetic dataset and repeatable role journeys | Implemented: six-role registration-through-payment regression, browser fixtures and repeatable large-history benchmark. |
| R0-02 | Registration, consultation, dispensing and reconciliation baseline timings/clicks/errors | Pending staff measurement; no claimed speed or click-reduction result. |
| R0-03 | Patient chart and pharmacy prototypes | Chart implemented; working pharmacy basket now delivered for pilot review in R2. |
| R0-04 | Pilot clinic, staff reviewers and accepted workflow designs | Needs facility participants; release includes a concrete review checklist. |
| SAFE-01 | Concurrent patient merge audit and transaction protocol across write paths | Implemented for current schema: database guards cover direct and indirect patient relations, including bulk writes; PostgreSQL contention regression verifies blocking/rejection of late writes. Future schema changes require guard review. |

## R1 — daily workflow UI

| ID | Requirement | Status / next evidence |
| --- | --- | --- |
| UX-01 | Shared navigation, grouped sidebar, breadcrumbs and design components | Implemented: grouped responsive navigation, breadcrumbs, shared fields/pagination/status/error patterns, persistent errors, confirmations and extracted shell assets. |
| UX-02 | Role homes and relevant primary actions | Implemented: role shortcuts, assigned visits/tasks and scoped reception, triage, consultation, lab, pharmacy and cashier boards. |
| CHART-01 | Unified original-record chart, pagination, permission-aware sections | Implemented: existing clinical feed plus versioned consultation notes, private documents, care plans, specialty events, finance-scoped billing and overview counts. Reception sees appointments; finance roles do not gain clinical notes. |
| CHART-02 | Persistent identity and encounter-scoped actions | Implemented: contextual patient banners, visit acceptance, resume/write-note links and service handoffs. No handoff silently completes a clinical or financial action. |
| FORMS-01 | Scoped asynchronous selectors and preselection | Implemented: server-scoped search, bounded choices, preserved selection and patient/order/admission context. Full queryset validates submitted relations. |
| FORMS-02 | Versioned consultation templates and attributed note reuse | Implemented: immutable published versions, template snapshots, same-patient copy/amend references, explicit review and closed-visit checks. |
| OPS-01 | Task inbox with owner, status, next action, resolution audit | Implemented: facility/audience scope, ownership, due dates, patient/general tasks, source links, optimistic revision checks and audited terminal resolution. |
| FLOW-01 | Registration → triage → consultation → lab → pharmacy → cashier preserves patient/visit | Implemented and covered by a synthetic six-role regression using actual endpoints, including queue completion, release, dispense and payment. Staff review remains pending. |
| LAB-UI | Collection/processing/review status tabs and specimen scanning | Implemented: status tabs, critical-result attention and accession UUID lookup accepting scanner input. Physical scanner validation remains a pilot check. |
| WARD-UI | Occupancy/theatre boards and focused readiness/count/cancellation panels | Implemented: occupancy, active admissions and theatre schedule with focused detail/action panels reusing existing transactional services. |
| A11Y-01 | Keyboard, screen-reader, tablet/mobile and staff acceptance | Automated checks cover 390/768/1440 widths, overflow, accessibility, JavaScript errors and keyboard menu dismissal. Manual assistive-technology and staff acceptance remain pending. |
| PERF-01 | Query/index review and agreed realistic load targets | Bounded hydration/selection, task index and synthetic benchmark implemented: 5,000 patients/500 chart notes, 20 requests per endpoint. Production concurrency, hardware and accepted load targets remain pending. |

## R2 — pharmacy and financial efficiency

The Phase 2 software scope is implemented; [release evidence and deployment notes](PHASE_TWO_RELEASE.md) describe the completed workflows. Facility acceptance and hardware validation remain open release gates. Original-provider refunds remain an explicit PAY-02 dependency; unsupported refunds are not paid out as cash.

| ID | Requirement | Status / next evidence |
| --- | --- | --- |
| PHARM-01 | Structured ingredient/strength/form/route/generic/brand catalog and barcode aliases | Implemented: catalog profile linked to unchanged stock codes, ingredient/strength/form/route/generic/brand fields, reviewed status, unique barcode aliases and package mapping. Facility catalog review remains required. |
| PHARM-02 | Multi-item scanner basket and atomic/idempotent checkout | Implemented: scanner basket, atomic dispensing/invoice posting and retry-safe completion; cashier handoff uses a required payment idempotency key and rejects conflicting replays. Separate authorized dispensing and collection steps have independent transaction boundaries. |
| PHARM-03 | Held baskets, package conversions and medicine instruction labels | Implemented: hold/resume/cancel, audited removal and stale-revision checks; existing package units converted to base quantities; labels preserve medicine/prescription snapshots. Physical scanner and label-printer review pending. |
| PHARM-04 | Prescription versus permitted retail-sale rules | Implemented software; facility acceptance pending: reviewed Rx-required classification and default-disabled facility retail switch implemented; no-Rx supply requires reviewed catalog and enabled policy across existing/new dispensing. Facility approval of actual classifications remains required; additional controlled-medicine rules not inferred. |
| STOCK-01 | Consumption/lead-time/open-PO replenishment and transfer suggestions | Implemented: 30-day dispensing consumption, configurable lead/review/safety days, usable stock and approved outstanding purchase quantities; explicit destination-based transfer suggestions and expiry drill-downs. |
| STOCK-02 | Approval-based purchasing and price/credit overrides | Implemented: attributed purchase drafts and separate supervisor approval, approved quantity receipt limits, reviewed basket price exceptions and invoice credits. Requesters cannot approve their own changes. |
| REPORT-01 | Receivables aging, expiry/stockout drill-down and ledger reconciliation | Implemented: invoice-age receivables buckets, current stockouts/expiry and stock movement drill-downs, invoice/payment/refund and cash-session reconciliation. Aging is since invoice creation; historical stockout duration and profit are not inferred. |
| FIN-01 | Checkout and return/refund outcomes reconcile stock, cash and ledger | Implemented: reviewed returns link immutable dispense records, inspected/quarantined stock, invoice credits and bounded original-payment refund requests. Cash authorization and actual disbursement are separate; repeated actions are safe. Noncash provider execution remains PAY-02. |

## Workforce and management extension — added 30 September 2026

Requested before starting R2. “Role calling” is tracked as staff **roll call / attendance**, alongside role-based duty assignment. The [workforce/management delivery](WORKFORCE_MANAGEMENT_RELEASE.md) now implements core roster, attendance, review and manager registers. The statuses below retain every remaining acceptance criterion; partial does not mean complete. Actual working-time rules require facility policy; attendance records do not automatically prove clinical coverage or determine payroll.

| ID | Requirement | Acceptance / dependency |
| --- | --- | --- |
| STAFF-01 | Staff directory, department, specialty, employment status and credential expiry | Partial: facility-scoped directory, active-account checks, specialty/credential register and expiry attention implemented. Formal employment lifecycle fields and renewal supersession remain. |
| DUTY-01 | Doctor/nurse/support-staff duty roster, recurring shifts and on-call coverage | Partial: draft/publish/versioned shifts, weekly recurrence, supervisor/backup, overnight dates and overlap/leave checks implemented. Configurable minimum coverage and grouped roster publication remain. |
| DUTY-02 | Live doctors-on-duty board and patient assignment | Implemented core: scheduled/checked-in/on-call/break/availability states and reasoned doctor assignment with capacity checks. Legacy consultation routes remain available; roster enforcement is not global. |
| ATTEND-01 | Staff roll call and clock-in/out, breaks, lateness, absence and overtime review | Partial: own clock-in/out/breaks, roll-call board, exact lateness/time-beyond-end, reviewed corrections and approved exports implemented. Grace/rounding policy and unattended missing-clock-out correction remain. |
| LEAVE-01 | Leave, shift swaps and locum/backup coverage | Partial: separate leave reviewer, accepted future cover, matching roles and overlap guards implemented. Reciprocal swaps use two cover requests; an atomic two-way swap remains. |
| HANDOVER-01 | Shift handover and uncompleted work escalation | Partial: outgoing summary, recipient acknowledgment, named owner/due date and overdue board implemented. Automated escalation and source-linked clinical handover bundles remain. |
| MGMT-01 | Manager command centre and exception inbox | Partial: manager exception overview links staffing, cash/receivables, stock, incidents, equipment, checklists and budgets. Unified escalation ownership and service-quality freshness metrics remain. |
| MGMT-02 | Delegated approval matrix and temporary acting supervisors | Pending: current fixed admin/manager roles and independent approvals are enforced. Configurable amount limits and timed delegation remain unimplemented. |
| MGMT-03 | Incident/complaint register and corrective actions | Implemented core: restricted incident/complaint register, severity, accountable manager, corrective actions/evidence/due dates, independent closure and audited reopening. |
| MGMT-04 | Asset register, maintenance, calibration and downtime | Implemented core: assets, custodians, vendor/cost/service records, maintenance/calibration dates and downtime/restore/retirement events. Device-specific clinical QC remains LIS-02. |
| MGMT-05 | Budgets, expenses, supplier obligations and accountable cost centres | Partial: independent UGX budget/expense approvals, budget caps and supplier invoice references implemented. Attachments, supplier settlement, accounting exports and profitability remain. |
| MGMT-06 | Staff onboarding/offboarding, training and policy acknowledgments | Partial: owned checklists, policy/training versions and acknowledgment, independent review and guarded admin offboarding implemented. Automatic reassignment, broader role-change audit and complete lifecycle integration remain. |
| MGMT-07 | Workload, attendance and service-quality reporting | Partial: scoped attendance, workload/capacity and approved attendance CSV implemented. Agreed service-quality KPI definitions and department/period dashboards remain. |

Biometric terminals, location verification and payroll integration are optional adapters after requirements, device/provider access and privacy rules are agreed. The core attendance/roster workflow must work without those dependencies. Full payroll remains deferred; approved attendance exports are in scope.

## R3 — engagement and insights

Started: [diagnostics, visiting access and Phase 3 first delivery](DIAGNOSTICS_AND_PHASE_THREE_START.md). The [patient/staff/operator/owner backlog](PATIENT_STAFF_OWNER_BACKLOG.md) adds case-based visiting specialists and diagnostic worksheet requirements without removing earlier scope.

| ID | Requirement | Status / next evidence |
| --- | --- | --- |
| PORTAL-01 | Appointment requests, verified patient access and guardian delegation | Partial: existing links remain read-only by default; staff-verified recipient/guardian authority can enable retry-safe patient appointment requests, reception review and conflict-checked booking. Self-service identity verification and finer delegated scopes remain. |
| ENGAGE-01 | Recall workflow and automated follow-up scheduling | Partial: owned recall worklist, due/overdue tracking, outcomes and idempotent next-recall scheduling implemented. Automated consented outreach/escalation remains. |
| ENGAGE-02 | Consent/preferences, delivery inbox, opt-out and controlled retry | Pending extensions; existing consented SMS/reminder controls retained. |
| ENGAGE-03 | WhatsApp channel | Needs provider onboarding, approved templates and consent model. |
| REPORT-02 | Queue waits, lab turnaround, payer rejection, operational exception dashboards | Pending event/KPI definitions and reconciled drill-downs. |
| FIN-02 | Expense tracking and meaningful profitability | Partial: approved budgeted expense obligations implemented in manager registers. Settlement, reconciled costs and meaningful profitability remain; collections are not profit. |

## R4 — integrations and enterprise readiness

| ID | Requirement | Status / dependency |
| --- | --- | --- |
| PAY-01 | MTN live collection/reconciliation commissioning | Adapter exists; live credentials and provider acceptance required. |
| PAY-02 | Airtel and original-provider refunds | Pending adapters and provider specifications; ambiguous outcomes must reconcile safely. |
| PAYER-01 | One actual pilot insurer integration then further transports | Needs selected payer, contracts, sandbox and accepted forms/codes. |
| GOV-01 | EFRIS adapter where applicable | Needs facility tax/invoicing scope and URA integration specifications/access. |
| GOV-02 | Approved HMIS/DHIS2 mapping and submission | Needs current indicators/identifiers, approval and authorized endpoint. |
| LIS-01 | Specimen chain of custody/aliquots/referrals and reagent lots | Pending extension of existing specimens/results. |
| LIS-02 | Laboratory QC and equipment service/calibration | Needs lab-owner requirements and approved quality processes. |
| LIS-03 | One analyzer/LIS integration | Needs actual device/protocol, approved mappings and test messages. |
| SEC-01 | Admin MFA, granular permissions and sensitive-view/export audit review | Pending; existing role/audit/throttle controls retained. |
| BRANCH-01 | Authorized facility switching and consolidated reports | Pending; preserve explicit facility scope and distinguish single organization from SaaS tenancy. |
| SETUP-01 | Guided configuration, enabled modules, forms/prices/approval rules | Pending; retain current setup screens. |
| IMPORT-01 | Validated migrations, preview/errors/reconciliation and staff guides | Pending expansion beyond existing inventory import. |
| OPS-02 | Observability, incident handling, update/rollback and recovery targets | Partial: health checks/restore drills exist; deployment load tests and facility recovery rehearsal pending. |
| BIZ-01 | Distribution license, hosting model, support/update ownership and service targets | Needs owner decisions; no assumed licensing or uptime guarantees. |

## R5 — clinically governed expansion

| ID | Requirement | Status / dependency |
| --- | --- | --- |
| CLIN-01 | HIV/TB/NCD/ANC programs and cohort workflows | Needs approved current program definitions and clinical owners. |
| CLIN-02 | Drug-interaction/dose and vaccination eligibility rules | Needs approved/licensed knowledge, terminology, source/version provenance and clinical validation. |
| SPECIALTY-01 | Validated graphical labour chart, specialty scales and multi-team theatre resources | Pending reviewed specification; existing documentation/count controls retained. |
| IMAGE-01 | Imaging worklists, study IDs, PACS viewer and report review | Partial: imaging operator role/worklist, scheduling, versioned worksheets, independent review and released patient reports implemented. Study IDs, image storage/PACS and actual device integration remain. |
| TELE-01 | Teleconsultation when pilot demand justifies it | Pending requirements and selected provider. |

## Additional patient/staff/operator/owner requirements

See [the expanded checklist](PATIENT_STAFF_OWNER_BACKLOG.md) for PAT-01–10, VISIT-01–03, CLIN-03–06, DIAG-01–08 and OWNER-01–07. Implemented cores include temporary case access, immutable diagnostic templates, operator worklists and printable released reports. Preparation clearance, specialist fees, external referral completion, equipment booking, imaging transport, retests, patient itinerary and operational KPIs remain explicitly planned.

## Explicitly deferred in the source plan, not silently removed

Full disconnected stock/payment operations require a separate allocation/conflict/reconciliation design. The current disconnected capability remains clinical drafts only. AI diagnosis, universal ungoverned clinical rules, payroll, ambulance/fleet, mortuary and blood bank require a justified customer workflow and acceptance owner before becoming committed releases. Mature accounting/PACS/LIS integration should be evaluated before rebuilding those systems.

## Completion rules

- No whole release is complete until all its required acceptance criteria are met.
- Technical test success does not substitute for live-provider commissioning or clinical acceptance.
- The two-second search target has local synthetic evidence only; production search latency, one-minute returning check-in and 30% click reduction require pilot measurement.
- Every subsequent delivery updates this tracker, records evidence and keeps unfinished scope visible.
