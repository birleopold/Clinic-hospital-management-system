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
| STAFF-01 | Staff directory, department, specialty, employment status and credential expiry | Software implemented: facility-scoped directory, audited employment type/status/dates, duty eligibility checks, credential renewal supersession and expiry attention. Migration and runtime acceptance follow the completion-boundary delivery; facility HR policy acceptance remains. |
| DUTY-01 | Doctor/nurse/support-staff duty roster, recurring shifts and on-call coverage | Software implemented: draft/publish/versioned shifts, weekly recurrence, supervisor/backup, overnight dates, overlap/leave/employment checks, configurable department/role minimum coverage and atomic grouped publication. Facility staffing requirements and operational acceptance remain. |
| DUTY-02 | Live doctors-on-duty board and patient assignment | Implemented core: scheduled/checked-in/on-call/break/availability states and reasoned doctor assignment with capacity checks. Legacy consultation routes remain available; roster enforcement is not global. |
| ATTEND-01 | Staff roll call and clock-in/out, breaks, lateness, absence and overtime review | Software implemented: own clock-in/out/breaks, roll call, exact lateness/time-beyond-end, independently reviewed missing-clock-out corrections, approved exports and effective-dated grace/rounding policy snapshots. Original exact totals remain separate from policy-adjusted totals; facility policy acceptance is required and payroll is not inferred. |
| LEAVE-01 | Leave, shift swaps and locum/backup coverage | Implemented core: separate leave reviewer, accepted future cover and atomic reciprocal swaps reuse paired existing cover requests. Both staff accept and an independent supervisor approves both future duties together; role, overlap, leave and stale-duty guards apply. Facility leave/locum policies still require acceptance. |
| HANDOVER-01 | Shift handover and uncompleted work escalation | Partial: outgoing summary, recipient acknowledgment, named owner/due date and overdue board implemented. Automated escalation and source-linked clinical handover bundles remain. |
| MGMT-01 | Manager command centre and exception inbox | Partial: manager exception overview links staffing, cash/receivables, stock, incidents, equipment, checklists and budgets. Unified escalation ownership and service-quality freshness metrics remain. |
| MGMT-02 | Delegated approval matrix and temporary acting supervisors | Partial: eight existing monetary approval workflows now enforce configurable per-facility UGX limits and timed, revocable authority with administrator UI and audit. Independent review, role scope and transactional rollback remain enforced. Nonfinancial acting-supervisor delegation remains. |
| MGMT-03 | Incident/complaint register and corrective actions | Implemented core: restricted incident/complaint register, severity, accountable manager, corrective actions/evidence/due dates, independent closure and audited reopening. |
| MGMT-04 | Asset register, maintenance, calibration and downtime | Implemented core: assets, custodians, vendor/cost/service records, maintenance/calibration dates and downtime/restore/retirement events. Device-specific clinical QC remains LIS-02. |
| MGMT-05 | Budgets, expenses, supplier obligations and accountable cost centres | Partial: independent UGX budget/expense approvals, budget caps and supplier invoice references implemented. Reviewed partial supplier settlements, transaction/evidence references and cash-flow CSV now implemented. Supporting file uploads, general-ledger accounting export, supplier aging and profitability remain. |
| MGMT-06 | Staff onboarding/offboarding, training and policy acknowledgments | Partial: owned checklists, policy/training versions and acknowledgment, independent review and guarded admin offboarding implemented. Automatic reassignment, broader role-change audit and complete lifecycle integration remain. |
| MGMT-07 | Workload, attendance and service-quality reporting | Partial: scoped attendance, workload/capacity and approved attendance CSV implemented. Agreed service-quality KPI definitions and department/period dashboards remain. |

Biometric terminals, location verification and payroll integration are optional adapters after requirements, device/provider access and privacy rules are agreed. The core attendance/roster workflow must work without those dependencies. Full payroll remains deferred; approved attendance exports are in scope.

## R3 — engagement and insights

Started: [diagnostics, visiting access and Phase 3 first delivery](DIAGNOSTICS_AND_PHASE_THREE_START.md). The [patient/staff/operator/owner backlog](PATIENT_STAFF_OWNER_BACKLOG.md) adds case-based visiting specialists and diagnostic worksheet requirements without removing earlier scope.

| ID | Requirement | Status / next evidence |
| --- | --- | --- |
| PORTAL-01 | Appointment requests, verified patient access and guardian delegation | Partial: newly issued links require staff-verified recipient/guardian authority and explicit access scopes. Retry-safe requests, reviewed rescheduling/cancellation of the original appointment, patient feedback, approved preparation acknowledgment and patient/staff revocation are exposed in the UI. Legacy grants retain their previous summary access. Self-service identity verification, account recovery and waitlist prioritization remain. |
| ENGAGE-01 | Recall workflow and automated follow-up scheduling | Partial: owned recall worklist, due/overdue tracking, outcomes and idempotent next-recall scheduling implemented. Consented recall queueing and overdue owner-task escalation now implemented; scheduling/provider commissioning remains. |
| ENGAGE-02 | Consent/preferences, delivery inbox, opt-out and controlled retry | Implemented core: verified current-phone preferences, evidence, opt-out cancellation, attempt inbox, provider-acceptance distinction, bounded retries and uncertainty blocking. Live delivery receipts and reconciliation tooling remain partial. |
| ENGAGE-03 | WhatsApp channel | Needs provider onboarding, approved templates and consent model. |
| REPORT-02 | Queue waits, lab turnaround, payer rejection, operational exception dashboards | Implemented scoped queue-entry-to-start, order-to-first-release and adjudicated-claim rejection metrics with denominators, exclusions and paginated source records. Facility KPI acceptance and richer end-to-end service-quality indicators remain. |
| FIN-02 | Expense tracking and meaningful profitability | Partial: approved obligations, retry-safe partial settlement evidence, independent reconciliation and event-dated collection/refund/expense cash-flow drill-down and CSV implemented. Pending evidence reserves the unpaid obligation; approval does not imply payment. Accrual costs, inventory cost allocation and meaningful profitability remain; cash flow is not profit. |

See [Phases 3–5 delivery and exact remaining gates](PHASE_THREE_FIVE_DELIVERY.md). These phases remain partial; outstanding engineering is distinct from external commissioning.

## R4 — integrations and enterprise readiness

| ID | Requirement | Status / dependency |
| --- | --- | --- |
| PAY-01 | MTN live collection/reconciliation commissioning | Adapter exists; live credentials and provider acceptance required. |
| PAY-02 | Airtel and original-provider refunds | Pending adapters and provider specifications; ambiguous outcomes must reconcile safely. |
| PAYER-01 | One actual pilot insurer integration then further transports | Needs selected payer, contracts, sandbox and accepted forms/codes. |
| GOV-01 | EFRIS adapter where applicable | Needs facility tax/invoicing scope and URA integration specifications/access. |
| GOV-02 | Approved HMIS/DHIS2 mapping and submission | Needs current indicators/identifiers, approval and authorized endpoint. |
| LIS-01 | Specimen chain of custody/aliquots/referrals and reagent lots | Implemented core custody sequence, aliquot accessions, referral/return evidence and independently released reagent lots. Volume balances, reagent consumption and external referral commissioning remain partial. |
| LIS-02 | Laboratory QC and equipment service/calibration | Partial: manual SOP-referenced QC, independent review, failed-lot quarantine and attached worksheet run/release checks implemented. Mandatory QC policy, remediation, device-specific limits and lab-owner validation remain. |
| LIS-03 | One analyzer/LIS integration | Needs actual device/protocol, approved mappings and test messages. |
| SEC-01 | Admin MFA, granular permissions and sensitive-view/export audit review | Partial: administrator/opt-in staff TOTP MFA, browser/JWT enforcement, replay/throttle controls, device revocation and audited recovery implemented. Completion review adds support identity/authority containment, role-minimized demographics, released-only nurse results, scoped scheduling and read-only financial admin workflows. Broader granular permission matrix and sensitive-view/export audit review remain. |
| BRANCH-01 | Authorized facility switching and consolidated reports | Implemented core: expiring/revocable administrative branch grants, browser selection, validated JWT facility header and selected/all-facility report scope. Clinical cross-branch credentialing and per-branch comparison exports remain; deployment is a single organization, not SaaS tenancy. |
| SETUP-01 | Guided configuration, enabled modules, forms/prices/approval rules | Partial: pharmacy/clinic/hospital/custom presets, selected services with dependencies, first-run gate, service/role menus, route guards, business naming, staff recruitment/access and readiness dashboard implemented. Facility logo upload, A4/80mm invoice/receipt branding and ordinary scoped department/room configuration now implemented. Financial approval limits and timed authority now have ordinary admin UI; nonfinancial delegation, price/form wizard and extended print themes remain. |
| IMPORT-01 | Validated migrations, preview/errors/reconciliation and staff guides | Partial: reviewed patient demographics CSV preview, row errors, source identity reconciliation, independent atomic commit and migration guide implemented alongside inventory import. Historical clinical/balance imports remain. |
| OPS-02 | Observability, incident handling, update/rollback and recovery targets | Partial: health checks/restore drills exist; deployment load tests and facility recovery rehearsal pending. |
| BIZ-01 | Distribution license, hosting model, support/update ownership and service targets | Needs owner decisions; no assumed licensing or uptime guarantees. |

## R5 — clinically governed expansion

| ID | Requirement | Status / dependency |
| --- | --- | --- |
| CLIN-01 | HIV/TB/NCD/ANC programs and cohort workflows | Partial: versioned independently published definitions, snapshot enrollments, cohort status, append-only reviews/amendments and closure implemented. Approved disease-specific content, eligibility and cohort indicators still require clinical owners and validation. |
| CLIN-02 | Drug-interaction/dose and vaccination eligibility rules | Needs approved/licensed knowledge, terminology, source/version provenance and clinical validation. |
| SPECIALTY-01 | Validated graphical labour chart, specialty scales and multi-team theatre resources | Partial: source-linked labour observation plots, exact-value table, missing-value handling and amendment selection implemented. Validated partograph rules, specialty scales and multi-team theatre resources still require reviewed specifications. |
| IMAGE-01 | Imaging worklists, study IDs, PACS viewer and report review | Partial: imaging operator role/worklist, scheduling, versioned worksheets, independent review and released patient reports implemented. Study UIDs and allowlisted external viewer references now implemented; image storage/PACS authorization and actual device integration remain. |
| TELE-01 | Teleconsultation when pilot demand justifies it | Pending requirements and selected provider. |

See [enterprise access/import and observation-display release](ENTERPRISE_ACCESS_AND_IMPORT_RELEASE.md) for this delivery, upgrade instructions and explicit limits.

## Modular installations and independent tenant ownership — added 30 September 2026

See [service setup and role workspaces](SERVICE_SETUP_AND_ROLE_WORKSPACES.md) and [isolated tenant control and approval release](TENANT_CONTROL_AND_APPROVAL_RELEASE.md). This requirement expands the earlier single-organization branch design; it does not silently redefine facility scope as tenant isolation.

| ID | Requirement | Status / next evidence |
| --- | --- | --- |
| MOD-01 | Pharmacy/clinic/hospital presets and selectable service modules | Implemented core setup, dependency validation, first-run gates, filtered menus/cards/chart sections and browser/JWT service enforcement. Facility acceptance and exhaustive cross-module action review remain. |
| ROLE-UX-01 | Roles see only permitted work, without dead-end menu links | Implemented shared role/service navigation and template link filtering; dedicated role-link regression. Action-specific ownership/approval controls need continued review. |
| TENANT-01 | Independent tenant data and configuration ownership | Implemented deployment boundary: each independent business has its own application/database/private media/signing keys/Redis, including catalogues, suppliers and prices. Owner UI generates unique deployment bundles; physical-runtime isolation is covered by the disposable HTTPS review. Real host deployment, load and recovery acceptance remain; never share a database across independent businesses. |
| TENANT-02 | Tenant setup, branding and recruitment/role administration | Partial: facility-scoped setup, naming, invoice-header branding, recruitment and guarded role changes implemented. Facility logo upload, validated image delivery, patient-facility invoice/receipt branding and A4/80mm defaults now implemented. Independent-business isolation now uses separate deployment/database/media/key ownership; extended print themes and nonfinancial permission delegation remain. |
| OWNER-ACCESS-01 | Owner overview and audited support access across tenants | Implemented owner/admin workflow: registry, protected isolated deployment bundles, authenticated activation, reasoned suspend/resume and 30-second single-use support tickets opening revocable 30-minute sessions. Tenant instances cannot manage the owner registry. Host deployment/acceptance remains external; provisioning is a bundle workflow, not a claim that hosts are already running. |

## Additional patient/staff/operator/owner requirements

See [the expanded checklist](PATIENT_STAFF_OWNER_BACKLOG.md) for PAT-01–10, VISIT-01–03, CLIN-03–06, DIAG-01–08 and OWNER-01–07. Implemented cores include temporary case access, immutable diagnostic templates, operator worklists and printable released reports. This delivery adds resource-conflict-checked diagnostic room/equipment reservations, source/version/language snapshots of approved preparation instructions with receipt acknowledgment, printable visit directions and clinician-recorded discharge/follow-up copies. Preparation clearance, specialist fees, external referral completion, imaging transport, retests and richer operational KPIs remain explicitly planned. See [workflow release evidence](END_TO_END_WORKFLOW_RELEASE.md).

## Explicitly deferred in the source plan, not silently removed

Full disconnected stock/payment operations require a separate allocation/conflict/reconciliation design. The current disconnected capability remains clinical drafts only. AI diagnosis, universal ungoverned clinical rules, payroll, ambulance/fleet, mortuary and blood bank require a justified customer workflow and acceptance owner before becoming committed releases. Mature accounting/PACS/LIS integration should be evaluated before rebuilding those systems.

## Completion rules

The [completion boundaries and workforce delivery](COMPLETION_BOUNDARIES_AND_WORKFORCE.md)
records the October 2026 direct-action permission fixes, workforce additions,
upgrade steps and exact verification limitations. Unchanged later-stage rows remain open.

- No whole release is complete until all its required acceptance criteria are met.
- Technical test success does not substitute for live-provider commissioning or clinical acceptance.
- The two-second search target has local synthetic evidence only; production search latency, one-minute returning check-in and 30% click reduction require pilot measurement.
- Every subsequent delivery updates this tracker, records evidence and keeps unfinished scope visible.
