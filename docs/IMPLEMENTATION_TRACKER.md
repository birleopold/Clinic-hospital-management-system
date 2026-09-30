# Suite implementation tracker

Source of truth: [competitive research and implementation plan](COMPETITIVE_RESEARCH_AND_PLAN_2026-09.md). Started 30 September 2026. No planned scope has been removed. An item is **partial** when only some acceptance criteria have been met. Dependencies do not mean cancellation.

## Phase 1: daily workflow implementation

The Phase 1 software scope is implemented. See [release evidence and deployment notes](PHASE_ONE_RELEASE.md). Facility staff acceptance, manual assistive-technology review and production load acceptance remain open gates; this is not a claim of clinical deployment sign-off. All R2–R5 scope below remains tracked.

## R0 — baseline and design

| ID | Requirement | Status / next evidence |
| --- | --- | --- |
| R0-01 | Synthetic dataset and repeatable role journeys | Implemented: six-role registration-through-payment regression, browser fixtures and repeatable large-history benchmark. |
| R0-02 | Registration, consultation, dispensing and reconciliation baseline timings/clicks/errors | Pending staff measurement; no claimed speed or click-reduction result. |
| R0-03 | Patient chart and pharmacy prototypes | Chart implemented; pharmacy basket prototype remains an R2 prerequisite. |
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

| ID | Requirement | Status / next evidence |
| --- | --- | --- |
| PHARM-01 | Structured ingredient/strength/form/route/generic/brand catalog and barcode aliases | Pending; preserve legacy codes and historical records in migration. |
| PHARM-02 | Multi-item scanner basket and atomic/idempotent checkout | Pending; reuse existing dispense/payment services and test final-unit contention. |
| PHARM-03 | Held baskets, package conversions and medicine instruction labels | Pending; existing package unit foundation retained. |
| PHARM-04 | Prescription versus permitted retail-sale rules | Needs facility pharmacy policy; implementation pending. |
| STOCK-01 | Consumption/lead-time/open-PO replenishment and transfer suggestions | Pending; current minimum-stock suggestions retained. |
| STOCK-02 | Approval-based purchasing and price/credit overrides | Pending additional workflow; preserve existing audit/control services. |
| REPORT-01 | Receivables aging, expiry/stockout drill-down and ledger reconciliation | Pending; current reports remain available. |
| FIN-01 | Checkout and return/refund outcomes reconcile stock, cash and ledger | Pending end-to-end basket work; existing tested refund/credit flows retained. |

## R3 — engagement and insights

| ID | Requirement | Status / next evidence |
| --- | --- | --- |
| PORTAL-01 | Appointment requests, verified patient access and guardian delegation | Pending; existing revocable read-only links retained. |
| ENGAGE-01 | Recall workflow and automated follow-up scheduling | Pending; existing entered due-date follow-up retained. |
| ENGAGE-02 | Consent/preferences, delivery inbox, opt-out and controlled retry | Pending extensions; existing consented SMS/reminder controls retained. |
| ENGAGE-03 | WhatsApp channel | Needs provider onboarding, approved templates and consent model. |
| REPORT-02 | Queue waits, lab turnaround, payer rejection, operational exception dashboards | Pending event/KPI definitions and reconciled drill-downs. |
| FIN-02 | Expense tracking and meaningful profitability | Pending; collections must not be mislabeled as profit. |

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
| IMAGE-01 | Imaging worklists, study IDs, PACS viewer and report review | Pending selected PACS/devices and secure integration design. |
| TELE-01 | Teleconsultation when pilot demand justifies it | Pending requirements and selected provider. |

## Explicitly deferred in the source plan, not silently removed

Full disconnected stock/payment operations require a separate allocation/conflict/reconciliation design. The current disconnected capability remains clinical drafts only. AI diagnosis, universal ungoverned clinical rules, payroll, ambulance/fleet, mortuary and blood bank require a justified customer workflow and acceptance owner before becoming committed releases. Mature accounting/PACS/LIS integration should be evaluated before rebuilding those systems.

## Completion rules

- No whole release is complete until all its required acceptance criteria are met.
- Technical test success does not substitute for live-provider commissioning or clinical acceptance.
- The two-second search target has local synthetic evidence only; production search latency, one-minute returning check-in and 30% click reduction require pilot measurement.
- Every subsequent delivery updates this tracker, records evidence and keeps unfinished scope visible.
