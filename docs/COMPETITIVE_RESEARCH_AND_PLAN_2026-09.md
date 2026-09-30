# Competitive research and implementation plan

Research date: 30 September 2026. Code baseline: `67d07192bd9f4eb8d2d94d13bb3ee05fede73a31` on `main`.

## Recommendation

Keep the Django application and its tested transactional services. Prioritize a cohesive outpatient, pharmacy and small-hospital experience: role workspaces, one patient chart, fast dispensing, useful management reports and local integrations. Avoid spreading the next release across every possible specialty.

The suite already covers more operational ground than its interface communicates. Its main weakness is workflow integration and depth, not the absence of basic module names. The goal is to reduce searching, repeated selection and navigation while preserving patient identity, financial integrity, stock controls and explicit review.

This is a research and planning deliverable, not a claim that the proposed functionality has been implemented.

## Evidence and limits

Reviewed all six supplied vendor sites, public product documentation for eight additional systems, and selected open-source repository documentation. Commercial features below are vendor claims, not independently demonstrated behavior. An absent public description is unknown, not proof a competitor lacks a capability. No paid product was installed, no private customer deployment was inspected, and no comparative speed or reliability benchmark was run.

The MedSoftwares comparison is published by a vendor promoting its own products; it is not an independent ranking. Compliance, uptime, customer-count and savings claims are not used as scoring evidence. Vendor phrases such as “offline” require demonstration: LAN operation, cached forms and fully disconnected transactional synchronization are different capabilities.

Our side is based on inspected models, services, templates, existing release documentation and the current synthetic-data desktop screenshot. The previous release passed all four Python/DB CI jobs; that is regression evidence, not clinical acceptance or proof of competitive superiority.

## Systems reviewed and useful lessons

| System | Public evidence / advertised focus | What to apply here |
| --- | --- | --- |
| MedSoftwares PharmaPOS / HospitalOS [1] | Barcode checkout, FEFO, split payments, labels, mobile money, broad hospital modules and offline claims. | Treat retail pharmacy as a distinct fast workflow; demonstrate offline boundaries explicitly. |
| Swift / Magoba [2] | Practitioner availability, linked patient history, document storage, appointments and HR connections. | Patient context should persist through tasks; link schedules and documents instead of reselecting records. |
| Hanmak MedicentreV3 [3] | Advertises HL7, DICOM, SMART/Slade insurance connections and messaging. | Integration depth can matter more than additional forms. Validate Ugandan payer availability separately. |
| Vitaline [4] | Public indexed content presents clinical triage, pharmacy POS and diagnostic lab workstations, barcode/FEFO and mobile-money checkout. | Clear workstation-specific journeys and an understandable queue are good product priorities. Offline and payment claims need a demo. |
| SCORE [5] | Publishes pharmacy POS, barcode sales, batch stock, reordering, patient timelines and operational reporting. | Add a proper pharmacy basket, scanner mapping and management drill-downs. |
| Clinic Plus [6] | Advertises doctor dashboard, pharmacy/lab handoffs, SMS/WhatsApp, insurance, expenditure and reports. | Improve patient engagement and operating-cost visibility; separate message delivery evidence from sending. |
| OpenMRS 3 [7] | Public patient-chart repository contains banner, conditions, allergies, medication, orders, results, vitals, tasks and form components. | Use a stable patient banner and coherent chart sections; borrow information architecture rather than its entire technology stack. |
| Bahmni [8] | Documents registration, clinical forms, prescriptions, diagnostics, inpatient, stock, accounting and PACS integration. | Connect departmental work around the same visit; integrate specialist systems when appropriate. |
| Frappe Health / Marley [9] | Documents configurable workflows, patient history, service-unit mapping, practitioner schedules and ERP connections. | Adopt configurable templates and department/resource mapping. Consider accounting integration instead of recreating a general ledger. |
| OpenEMR [10] | Documents flow boards, recall reminders, template-driven notes, patient portal and interoperability. | Add recall lists, reusable encounter forms and patient self-service. US-specific billing/certification does not transfer to Uganda. |
| HeliumOS [11] | Advertises timeline charting, specialty encounter forms, formulary, outpatient journeys, tasks and telemedicine. | One coherent consultation screen and coordinated tasks should precede speculative AI features. |
| UgandaEMR [12] | Public manual describes Uganda-specific HIV, TB, maternal/child-health workflows and point-of-care/data-exchange processes. | Use local program definitions and reporting workflows as implementation references, with current MoH confirmation. This manual includes older releases. |
| OpenELIS Global [13] | Publishes specimen traceability, quality control, analyzer integration, reagent/equipment management and lab KPIs. | Our result entry is not a full LIS; prioritize chain of custody and QC, then integrate analyzers or an LIS. |
| OpenLMIS [14] | Public logistics product and documentation emphasize supply visibility, accountability and requisitions in low-resource settings. | Extend minimum-stock suggestions with consumption, lead times and approval-based replenishment. It is a logistics reference, not an EHR replacement. |

Retrieval limits: Vitaline and SCORE's supplied pages initially returned no readable body; indexed Vitaline content and SCORE's related official feature pages supplied evidence. Clinic Plus's homepage initially failed; its official features/FAQ pages were available. Bahmni's application repository fetch failed; its official product documentation was used. No missing page was treated as a negative feature finding.

## Where our system is strong

These are demonstrable strengths and potential differentiators, not a verified claim that we outperform every named product.

- **Stock accountability:** FEFO dispensing, batch/location tracking, quarantine, stock counts, transfers, returns/credits and backorder controls already exist. Vaccine stock consumption and cold-chain quarantine are connected to this foundation.
- **Reviewed corrections:** signed clinical amendments, result review/release, critical-result acknowledgment, invoice credits/refunds and different-person reviews are implemented in relevant workflows.
- **Offline clinical documentation:** encrypted browser drafts, selected-patient context, explicit synchronization, stale-context conflicts, idempotent receipts and device revocation have automated coverage. Offline money/stock transactions are not implemented.
- **Operational verification:** SQLite/PostgreSQL CI, concurrent-write tests and isolated backup restoration provide useful engineering evidence. Latest prior release: 151 PostgreSQL tests passed; SQLite: 147 passed and four PostgreSQL-only skips.
- **Breadth already present:** identity/merge review, queues, appointments, encounters, lab panels/specimens, pharmacy, inpatient rounds, insurance preparation/remittance, maternity/newborn, theatre/counts and rehabilitation records.
- **Control of the product:** editable source and adaptable deployment allow tailoring. This does not establish a total-cost advantage; hosting, support, commissioning and maintenance still cost money. A distribution license remains a business decision.

## Evidence-backed gaps

| Area | Current state | Improvement and priority |
| --- | --- | --- |
| Patient chart | `templates/operations/patient.html` shows history, referrals and specialty summaries; encounter vitals/orders/Rx live separately. | **P0:** unified, filterable timeline with visit context, medication history, results and linked actions. |
| Everyday navigation | Role-filtered top navigation plus a large workspace directory; generic record pages dominate. | **P0:** role home pages, grouped sidebar, global patient search, task inbox and contextual navigation. |
| Form efficiency | Shared model forms use many relation dropdowns; broad lists and inline actions compete for space. | **P0:** asynchronous scoped lookup, patient preselection, grouped fields, dedicated create/edit pages or drawers. |
| Pharmacy checkout | Prescription board and single-item quick dispense; item code entry; printed dispense documents. | **P1:** multi-item basket, barcode aliases, package conversion, held baskets, linked payment/dispense and medicine instruction labels. QR identity/specimen labels already exist and are not retail barcode checkout. |
| Medication catalog | Inventory is chiefly code/name/unit; Rx dose/frequency/duration are text. | **P1:** ingredient, strength, dosage form, route, generic/brand links and approved formularies. This is prerequisite data for clinical checking. |
| Replenishment | `reorder_report` compares usable balance with configured minimum. | **P1:** consumption-based coverage, supplier lead time, outstanding POs and transfer suggestions; approval before purchasing. |
| Patient engagement | Expiring/revocable read-only links and consented SMS reminders; no full self-service account workflow found. | **P1/P2:** appointment requests, reminder automation, recall lists, access verification and guardian delegation. WhatsApp requires provider onboarding. |
| Analytics | Revenue/volume/service-mix endpoints and exports; report UI chiefly revenue totals. | **P1:** queue waits, lab turnaround, receivables aging, expiries, stockouts, payer rejections and drill-downs. Expenses needed before credible profitability. |
| Laboratory depth | Panels, analytes, specimens, results, review and critical acknowledgment. | **P2:** specimen event history/aliquots, reagent lots, QC, referral tracking and analyzer/LIS connections. |
| Imaging | Imaging orders and attachments are not a PACS/RIS workflow. | **P2/P3:** study identifiers, scheduling/worklists, secure viewer integration and report review. |
| Local integrations | MTN collection and Africa's Talking adapters exist; live commissioning pending. Claims and HMIS/FHIR exports are partial interfaces. | **P1/P2 gated:** verify MTN live flow; add Airtel, insurer transports, EFRIS and approved DHIS2/HMIS mappings where applicable. |
| Enterprise operations | Facility scoping exists; full multi-tenant SaaS administration is not established. | **P2:** authorized facility switching, consolidated reporting, granular permissions, admin MFA, onboarding and migration tools. |
| Clinical programs | Specialty documentation exists; governed automatic drug/vaccine rules and full program cohorts do not. | **P3 gated:** clinician-approved programs, terminology and decision support with provenance/versioning and validation. |
| Security/reliability | Existing role scope, audit, throttling and restore tests are useful foundations. | **P0/P2:** harden concurrent patient merge, review patient-view/export audit coverage, admin MFA, recovery targets and realistic load testing. |

Primary local evidence: `templates/base.html`, `templates/operations/{home,patient,collection}.html`, `templates/encounters/detail.html`, `templates/pharmacy/board.html`, `templates/reports/dashboard.html`, `apps/operations/{views,advanced_views,offline_views}.py`, `apps/{inventory,pharmacy}/models.py`, `apps/portal/ui_views.py`, `apps/reports/views.py`, `apps/integrations/providers.py` and the existing care/offline release documents. “Not found” means no end-to-end implementation identified in this review, not a claim that every line of the repository was audited.

## UI specification for the next release

Retain the current teal/navy identity, readable system fonts and locally hosted assets. The current screens have clear contrast but many present a large create form beside a wide table. In the inspected theatre screen, ten columns and inline action inputs compete with the left form. Desktop horizontal scrolling may pass an overflow test and still make tasks awkward.

### Shared application shell

- Collapsible grouped sidebar: Today, Patients, Clinical, Diagnostics, Pharmacy, Finance, Reports, Administration. Show only permitted destinations.
- Top bar: patient search, assigned facility, date/session context, task notifications and account menu. A facility switch appears only for users authorized to switch.
- Keep one page title, one primary action and meaningful breadcrumbs. Show current task/visit rather than database terminology such as “Add a record.”
- Create reusable buttons, inputs, alerts, status badges, empty states, skeleton/loading states, tables and confirmation dialogs. Move duplicated inline styling/scripts toward shared assets.
- Use badges with text/icons, not color alone. Errors remain visible with field links; destructive/financial actions show what will change before submission.

### Role home screens

| Role | Default screen and useful actions |
| --- | --- |
| Reception | Today's appointments and walk-ins, patient lookup, check-in, missing details and waiting times. |
| Nurse | Triage queue, observations due, assigned ward tasks and medications due. |
| Clinician | My queue, outstanding results/referrals and open encounters; resume consultation directly. |
| Pharmacy | Ready-to-dispense prescriptions, active basket, stock exceptions and backorders. |
| Lab | Awaiting collection, received, processing, awaiting review and critical communication tasks. |
| Cashier | Open cash session, outstanding invoices, pending collections and reconciliation exceptions. |
| Manager | Collections, unpaid balances, waiting time, stock risks and operational exceptions with drill-downs. |

### Patient and encounter workspace

Persistent identity banner: name, full MRN, birth date/age, allergy status and current encounter. Do not confuse “unknown allergies” with “none.” Chart sections: Overview, Visits, Notes, Medicines, Results, Documents, Care Plans and role-permitted Billing.

Overview displays relevant recent information with dates, units, status and provenance; it must not silently hide amended or unreleased results. A timeline filters by event/visit, and separates device draft time from server synchronization. The consultation workspace groups notes, diagnosis lookup, tests and prescribing around the same patient/encounter. Reusable templates need versioning; copying old notes must be explicit and attributable.

### Task-focused pages

- **Reception:** search first; show duplicate candidates before new registration; check in directly to a queue.
- **Pharmacy:** search/scan at left, basket at right, persistent patient/Rx header, stock/batch details on demand and a single reviewed checkout flow. Keep Rx restrictions distinct from permitted retail sales.
- **Laboratory:** status tabs, specimen scanning, result entry grouped by panel and separate review. Critical communication includes assigned recipient and acknowledgment history.
- **Theatre/ward:** timeline or occupancy board plus case detail; show only key columns in lists and move readiness/count/cancellation workflows into explicit panels.
- **Mobile/tablet:** navigation drawer, stacked forms, compact worklists and reachable primary actions. Desktop is the primary pharmacy/cashier workstation; tablets suit rounds. Do not compress every desktop table into a phone.

No wholesale React rewrite is required to deliver this design. Extend Django templates/HTMX and shared components first; add a narrowly scoped interactive component only when the workflow warrants it. This is an architectural recommendation for the existing repository, not a general rule about frontend frameworks.

## Implementation sequence and acceptance criteria

| Release | Scope | Dependencies | Evidence required before completion |
| --- | --- | --- | --- |
| **R0: baseline and design** | Synthetic demo dataset, task inventory, agreed role journeys, patient chart and pharmacy prototypes; merge-concurrency audit. | Identify a pilot clinic and staff reviewers; agree what “done” means. | Baseline time/click/error measurements for registration, consultation, dispensing and reconciliation; approved screen designs. |
| **R1: daily workflow UI** | Shared shell, role homes, patient search/banner, unified chart, linked visit actions, scoped lookups and actionable task inbox. | R0; query/index review; reuse existing services. | Reception → triage → consultation → lab → pharmacy → cashier works without reselecting the patient; roles remain scoped; keyboard and 390/768/1440-width review passes. |
| **R2: pharmacy and financial efficiency** | Structured catalog, barcode basket, packages/labels, held baskets, linked checkout, replenishment, receivables/expiry reports. | R1, approved catalog/prices/unit conversions; decide account and prescription policies. | Concurrent final-unit sales cannot oversell; repeated checkout cannot duplicate payment/dispense; labels match approved Rx; ledger/cash/stock reconcile; no unapproved credit or pricing override. |
| **R3: patient engagement and insights** | Booking requests, recall workflow, message consent/preferences/delivery inbox, upgraded portal; operational dashboards and expense tracking. | Patient access/guardian model; approved templates/provider accounts; KPI definitions. | Patient cannot access another record; no unreviewed result is exposed; opt-out/retry behavior tested; every KPI reconciles to underlying events. |
| **R4: integration and enterprise readiness** | Prioritize one payer, one analyzer/LIS and needed local payment/reporting adapters; MFA, branch control, import validation, observability and recovery rehearsal. | Contracts/specifications/sandbox access, chosen pilot equipment and facility policies. | Signed commissioning evidence, duplicate/out-of-order/error-path tests, scoped exports, approved recovery targets and load results. |
| **R5: clinically governed expansion** | Approved HIV/TB/NCD/ANC programs, drug/vaccine rules, advanced specialty workflows; PACS/teleconsultation as demand justifies. | Clinical owners, current licensed/approved sources, terminology and formal acceptance. | Source/version traceability, reviewed clinical test cases, safe override/escalation behavior and facility sign-off. |

R4 discovery can begin during R1 because partner access may be slow. R2 should not wait for every external integration. These are ordered releases, not calendar promises: estimate after R0 and a pilot scope are agreed.

### First implementable backlog

1. `UX-01` — Shared navigation/components; change `templates/base.html` and `static/css/suite.css`; retain route permissions and print layouts.
2. `UX-02` — Role home views; replace workspace-directory-first behavior without removing administrative access to modules.
3. `CHART-01` — Patient chart aggregation, pagination and permission-aware sections; reuse original records rather than duplicating their data.
4. `CHART-02` — Persistent banner and encounter-scoped actions; prevent patient/encounter mismatch on every submission.
5. `FORMS-01` — Scoped asynchronous patient/catalog/related-record selectors and preselected patient context.
6. `OPS-01` — Task inbox for unreleased/critical results, overdue referrals, failed messages and stock issues; define owner, status and resolution audit.
7. `SAFE-01` — Concurrency-safe merge design across writes; protect archived/canonical identity throughout the request transaction.
8. `PHARM-01` — Catalog and barcode schema; migration maps existing item codes without breaking historical dispense records.
9. `PHARM-02` — Basket/checkout orchestration; one reviewed command uses existing money/stock services, with explicit failure/retry semantics.
10. `REPORT-01` — Event definitions and drill-down reporting; distinguish billed revenue, collections, refunds, receivables and actual profit.

### Proposed product targets, not current measured performance

Measure on a defined pilot database and network. Aim for routine patient lookup under two seconds at the 95th percentile, a returning-patient check-in within one minute, and at least 30% fewer clicks for a standard consultation/dispense journey against R0. User-test with reception, clinician, nurse, pharmacist, lab, cashier and manager roles. Automated accessibility checks supplement manual keyboard and assistive-technology checks.

## Integration and business decisions

- **Payments:** finish MTN production reconciliation first; add Airtel where needed. An available payment-method label is not a live gateway integration. Define pending, failed, reversed and ambiguous outcomes.
- **Insurance:** select actual pilot insurers and their accepted forms/transports; preserve existing allocations/remittances while adding adapters. A SMART/Slade marketing reference does not establish a usable Ugandan contract.
- **URA EFRIS:** URA documents system-to-system integration [15]. Establish the facility's applicable invoicing/tax configuration and obtain its integration specifications before implementing an adapter; do not infer applicability from vendor claims.
- **HMIS/DHIS2:** confirm current indicators, facility identifiers, aggregation rules and submission authorization. Follow MoH interoperability guidance [16]; an export file alone is not a certified national connection.
- **Devices:** inventory the actual analyzer models, scanner formats and printers. Validate their real interfaces before promising plug-and-play support.
- **Distribution:** decide single-facility installation versus a managed multi-facility service, license, support ownership, update process, migration assistance and service targets.
- **Offline:** retain disconnected drafts. Any future offline stock/money design needs explicit allocation limits, conflict/duplicate handling and reconciliation; do not extend the draft queue to financial transactions casually.

## Defer until justified

Do not prioritize AI diagnosis, universal drug-interaction databases, complete offline financial replication, payroll, ambulance/fleet, mortuary, blood bank or every specialty merely to match a brochure. Some are valuable future products; each needs an identified customer workflow, owner and acceptance criteria. Add clinical decision support only with an approved knowledge source and clinical review. Prefer integration for mature accounting, PACS and LIS capabilities when it reduces operational risk and maintenance.

## Sources

Official product pages/documentation unless noted; accessed 30 September 2026. These links are research evidence, not endorsement.

1. [MedSoftwares comparison — vendor-authored](https://www.medsoftwares.com/news/best-pharmacy-hospital-software-uganda-2026).
2. [Swift / Magoba clinics](https://swift-webdesign.com/best-clinic-management-system-in-uganda/).
3. [Hanmak Uganda / MedicentreV3](https://www.hanmak.co.ke/hmis-uganda/).
4. [Vitaline](https://vitalinesystem.com/) — indexed public text; initial direct text extraction was empty.
5. [SCORE supplied pharmacy page](https://hmscore.cc/solutions/pharmacy), [features](https://hmscore.cc/features), [pharmacy POS](https://hmscore.cc/pharmacy-pos-uganda).
6. [Clinic Plus features](https://clinicplusug.com/features/), [FAQ](https://clinicplusug.com/faqs/).
7. [OpenMRS product](https://openmrs.org/product/), [patient-chart source repository and module documentation](https://github.com/openmrs/openmrs-esm-patient-chart).
8. [Bahmni feature list](https://www.bahmni.org/feature-list), [screenshots](https://www.bahmni.org/screenshots).
9. [Frappe Health](https://frappehealth.com/home), [documentation](https://frappehealth.com/docs), [Marley repository](https://github.com/earthians/marley).
10. [OpenEMR features](https://www.open-emr.org/wiki/index.php/OpenEMR_Features).
11. [HeliumOS](https://heliumhealth.com/helium-os/).
12. [UgandaEMR user manual repository](https://github.com/METS-Programme/ugandaemr-usermanual).
13. [OpenELIS Global capabilities](https://openelis-global.org/features-and-functionality/).
14. [OpenLMIS features](https://openlmis.org/product/features/).
15. [URA EFRIS](https://ura.go.ug/en/efris/), [handbook](https://ura.go.ug/en/efris-handbook/).
16. [Uganda MoH health information exchange and interoperability guidelines](https://library.health.go.ug/health-information-systems/digital-health/uganda-health-information-exchange-and-interoperability).
