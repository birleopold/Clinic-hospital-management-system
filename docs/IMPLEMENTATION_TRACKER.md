# Suite implementation tracker

Source of truth: [competitive research and implementation plan](COMPETITIVE_RESEARCH_AND_PLAN_2026-09.md). Started 30 September 2026. No planned scope has been removed. An item is **partial** when only some acceptance criteria have been met. Dependencies do not mean cancellation.

## Delivery 1: workflow foundation

Implemented: responsive collapsible navigation, facility context and role-permitted patient search; eight staff-role shortcut sets and relevant attention counts; clinician home lists assigned open visits; a permission-scoped patient chart with a paginated chronological feed of original visits, notes, observations, prescriptions, results and referrals. Chart sections and visit filters are server-enforced. Clinical users see released results; laboratory/admin users can see explicitly labeled drafts. Pharmacy sees prescriptions and allergy entries without general clinical notes. Specialty summaries remain linked for clinical users. Search and chart responses use no-store. Notes entered from a chart preselect the scoped patient. The encounter screen links back to the chart. Existing specialty and administrative screens remain available.

The chart preserves authored amendments and device draft/synchronization timestamps. Visit filtering explicitly excludes patient-level notes/referrals that lack an encounter relation rather than inventing one. Recent visit selector is bounded to 100; feed pagination covers all eligible source records. This is an initial chart, not completion of all chart sections or all connected workflows.

Validation: dedicated role/facility/direct-URL tests, pagination and visit identity tests, contextual-form tests and role destination checks. Browser coverage includes 390/768/1440 widths, keyboard menu dismissal, chart-to-note patient preselection, automated accessibility, JavaScript errors and existing clinical workflows. Final test/CI results are reported with the commit delivery.

## R0 — baseline and design

| ID | Requirement | Status / next evidence |
| --- | --- | --- |
| R0-01 | Synthetic dataset and repeatable role journeys | Partial: existing synthetic browser dataset plus chart/workspace tests; expand to full reception-through-payment fixture. |
| R0-02 | Registration, consultation, dispensing and reconciliation baseline timings/clicks/errors | Pending measurement; do not claim the proposed speed targets are achieved. |
| R0-03 | Patient chart and pharmacy prototypes | Partial: functional initial chart; pharmacy basket prototype pending. |
| R0-04 | Pilot clinic, staff reviewers and accepted workflow designs | Needs facility participants; technical work continues meanwhile. |
| SAFE-01 | Concurrent patient merge audit and transaction protocol across all write paths | Pending; existing quiet-registration-window limitation remains. |

## R1 — daily workflow UI

| ID | Requirement | Status / next evidence |
| --- | --- | --- |
| UX-01 | Shared navigation, grouped sidebar, breadcrumbs and design components | Partial: responsive sidebar/search/facility context delivered. Grouping, breadcrumbs, shared form/dialog/status components and inline-asset cleanup remain. |
| UX-02 | Role homes and relevant primary actions | Partial: role shortcuts, attention counts and assigned clinician visits delivered. Rich reception/triage/lab/pharmacy/cashier worklists remain. |
| CHART-01 | Unified original-record chart, pagination, permission-aware sections | Partial: timeline/visits/notes/vitals/referrals/prescriptions/results delivered. Care plans, documents outside results, specialty events, billing section and richer overview remain. |
| CHART-02 | Persistent identity and encounter-scoped actions | Partial: chart banner, resume links and encounter-to-chart navigation delivered. Banner across all clinical screens and complete visit handoffs remain. |
| FORMS-01 | Scoped asynchronous selectors and preselection | Partial: server-validated patient preselection for direct-patient collection forms. Asynchronous catalog/related-record selectors remain. |
| FORMS-02 | Versioned consultation templates and attributed note reuse | Pending; copied historical text must remain distinguishable. |
| OPS-01 | Task inbox with owner, status, next action, resolution audit | Partial: actionable attention counts link to existing workspaces. Persisted task ownership, inbox filters and resolution history remain. |
| FLOW-01 | Registration → triage → consultation → lab → pharmacy → cashier preserves patient/visit | Partial: chart/encounter/note links delivered. Complete journey still pending. |
| LAB-UI | Collection/processing/review status tabs and specimen scanning | Pending; existing specimen and result workflows retained. |
| WARD-UI | Occupancy/theatre boards and focused readiness/count/cancellation panels | Pending; existing forms retained. |
| A11Y-01 | Keyboard, screen-reader, tablet/mobile and staff acceptance | Partial: automated browser checks and menu keyboard tests pass; manual assistive technology and staff validation remain. |
| PERF-01 | Query/index review and agreed realistic load targets | Partial: bounded feed hydration and pagination; large-dataset measurements/index tuning pending. |

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
- The proposed two-second search, one-minute returning check-in and 30% click reduction remain unmeasured targets.
- Every subsequent delivery updates this tracker, records evidence and keeps unfinished scope visible.
