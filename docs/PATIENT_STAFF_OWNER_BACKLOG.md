# Patient, clinical staff, operator and owner checklist

Added 30 September 2026 after the request for visiting specialists, CT/radiography, department worksheets and patient copies. This complements, and does not replace, the implementation tracker. “Implemented core” still requires facility acceptance. “Planned” means code is not complete.

## Patient perspective

| ID | Simple need | Current delivery / next step |
| --- | --- | --- |
| PAT-01 | Know the appointment is requested versus actually booked | Implemented core in Phase 3: verified recipient requests; reception books or declines with a response. Existing read-only links stay read-only. |
| PAT-02 | Take home a clear copy of results | Implemented core: released diagnostic report, browser print/save-as-PDF and downloadable text; clinician/reviewer/date and amendments identified. Physical printers and department layouts need acceptance. |
| PAT-03 | See imaging results as well as lab results | Implemented core: released lab/imaging/procedure narratives appear in the existing patient portal. Scan images/PACS are a separate integration. |
| PAT-04 | Know where to go next and who is responsible | Existing patient/service handoffs retained. Planned: printable visit itinerary, expected wait and clear service-room directions. |
| PAT-05 | Receive preparation instructions before attending | Operator preparation/reference notes exist. Planned: facility-approved patient instructions linked to booked services, accessible language and acknowledgment. |
| PAT-06 | Reschedule, cancel or explain a missed appointment | Existing staff appointment cancellation retained. Planned: patient request/reschedule workflow and visible waitlist priority; no silent automatic slot changes. |
| PAT-07 | Know the estimated bill and remaining balance | Existing invoices/receivables/refunds retained. Planned: versioned estimates and explanation of deposits, covered services and patient portions. |
| PAT-08 | Authorize a guardian and revoke access | Phase 3 records recipient identity/guardian authority before appointment requests; existing link expiry/revocation retained. Planned: self-service verification, fine-grained delegated scopes and recovery process. |
| PAT-09 | Leave feedback or report a problem | Restricted manager complaint register implemented. Planned: patient-facing intake and acknowledgment with confidentiality controls. |
| PAT-10 | Receive a discharge/follow-up sheet in understandable language | Existing recorded care plans and follow-up retained. Planned: approved consolidated discharge sheet, language preferences and interpreter/support-person requirements. |

## Physician / visiting specialist perspective

| ID | Simple need | Current delivery / next step |
| --- | --- | --- |
| VISIT-01 | Come for one case without being a permanent employee | Implemented core: dedicated restricted visiting account, specialty/credential evidence, case/date authorization and expiry/revocation. One account can have separate future engagements. |
| VISIT-02 | See assigned cases and leave a signed operation note | Implemented core: limited theatre case portal, signed notes/amendments, local clinician chart visibility and no general staff API/patient-list access. Planned: facility-approved preoperative packet and structured operative-note fields. |
| VISIT-03 | Agree professional fees and settle a visiting specialist | Planned: per-case fee agreement, independent approval, payable/settlement and accounting links. Do not use employee payroll for one-off visits. |
| CLIN-03 | Know critical results were seen and acted upon | Existing critical-result acknowledgment retained; worksheets can flag a critical result. Planned: accountable escalation timers, acknowledgment reason and closed-loop follow-up. |
| CLIN-04 | Refer externally and know what came back | Existing referrals retained. Planned: receiving-facility acceptance, external result ingestion with provenance and referral completion checklist. |
| CLIN-05 | Know a patient did not return | Implemented core: owned recalls, due/overdue list, completion outcome and idempotent repeat scheduling. Planned: consented outreach attempts and escalation. |
| CLIN-06 | Amend a report without erasing what was issued | Implemented core: worksheet snapshots, independent release, withdrawn drafts, referenced amendments and current-version patient reports. |

## Diagnostic operator / nursing staff perspective

| ID | Simple need | Current delivery / next step |
| --- | --- | --- |
| DIAG-01 | Have an operator worklist for X-ray, CT, ultrasound, MRI and other tests | Implemented core: diagnostic order types, modality labels, assignment, scheduling, start/completion timestamps and review queue. Radiography role is restricted to imaging in the new worklist. |
| DIAG-02 | Fill a defined, customizable department sheet | Implemented core: versioned templates with text/numeric/choice fields, required fields, units/reference context and independent template approval. No guessed clinical rules/ranges. |
| DIAG-03 | Check sample identity before lab results | Existing specimen accession/reception/rejection retained; new laboratory worksheets require a received specimen from the same order. Planned: aliquots, re-collection, referral labs and reagent-lot/QC linkage. |
| DIAG-04 | Reserve equipment/rooms and flag unsafe preparation | Planned: linked equipment/room booking conflicts, protocol-specific contraindication/consent checklists and qualified clearance. Current preparation notes are not clearance. |
| DIAG-05 | Access films/images and machine results | Planned integration: study/accession IDs, DICOM/PACS access, analyzer transport and approved mappings; requires actual systems and protocols. |
| DIAG-06 | Complete handover without losing unfinished work | Implemented core: named incoming colleague, operational notes and acknowledgment. Planned: source-linked department bundles and automatic escalation. |
| DIAG-07 | Record failed/repeated tests and why | Planned: reasoned re-test requests, specimen rejection/re-collection links, charge-policy review and consumables reconciliation. |
| DIAG-08 | Print specimen labels, result copies and patient directions reliably | Result print layouts implemented; existing barcode mechanisms retained. Planned: physical device profiles, paper sizes, printer acceptance and accessible fallback instructions. |

## Facility owner / manager perspective

| ID | Simple need | Current delivery / next step |
| --- | --- | --- |
| OWNER-01 | Know who is expected, present, covering and accepting patients | Implemented core duty/attendance/availability board and reviewed cover. Planned staffing minima, grace rules and atomic reciprocal swaps remain in the tracker. |
| OWNER-02 | Know what needs action today | Implemented core manager exception counts for cases, equipment, checklists, expenses and links to stock/finance/workforce. Planned: one accountable escalation inbox across services. |
| OWNER-03 | Track equipment downtime and maintenance cost | Implemented core asset/service/downtime register. Planned utilization, duration analysis, procurement/warranty and repair-versus-replace reporting. |
| OWNER-04 | Know expenses are approved without pretending they are paid | Implemented core UGX budgets, independent approvals, reference deduplication and caps. Planned supporting uploads, settlements, supplier aging and reconciled profitability. |
| OWNER-05 | Safely onboard and remove staff access | Implemented core owned checklists, policy versions/acknowledgments and guarded admin offboarding. Planned lifecycle automation, permission delegation and comprehensive access-review workflow. |
| OWNER-06 | Know turnaround, cancellations and service demand | Planned Phase 3: agreed KPI definitions and source drill-downs using actual timestamps; no fabricated historical metrics. |
| OWNER-07 | Run safely during network/power problems | Existing clinical offline drafts and restore tooling retained. Planned facility rehearsals, downtime forms and recovery targets. Offline money/stock requires a separate reconciliation design. |

Design references reviewed: [HL7 FHIR R5 DiagnosticReport](https://hl7.org/fhir/R5/diagnosticreport.html) separates report context, individual findings and imaging-study references; [PractitionerRole](https://hl7.org/fhir/R5/practitionerrole.html) distinguishes a practitioner's organizational role/period. These informed the separation of visiting engagements, reports and image integration. The new screens do not claim FHIR/DICOM conformance or automatic clinical validation.
