# Specialty workflows

Released 30 September 2026. These modules provide operational scheduling and clinical documentation. They do not generate treatment recommendations, vaccine schedules or doses, replace a facility's approved surgical checklist, or constitute specialty-care certification.

## Workspaces and permissions

All workspaces require login, an assigned facility and a clinician/nurse role (or facility admin/system superuser). Relationships and patient searches are facility-scoped. Assigned surgeons and rehabilitation clinicians must be active clinicians in that facility. Cashier, laboratory, pharmacy and reception roles cannot open these specialty records.

| Workspace | Workflow |
| --- | --- |
| `/suite/theatre/` | Book a patient, surgeon and room with start/end times. Record consent and approved checklist references, then procedure start, recovery handoff and completion. Cancellation requires a reason and is available before start. |
| `/suite/pregnancies/` | Record pregnancy history, clinician-confirmed due date and assessment. One active episode per patient. Close with an explicit outcome and follow-up note. |
| `/suite/maternity-visits/` | Append antenatal, delivery or postnatal documentation, care and follow-up date. Postnatal records remain possible after episode closure. Correct a record by selecting it in “supersedes” and recording the reason; the original is retained. |
| `/suite/vaccinations/` | Schedule, defer, reschedule or cancel a clinician-selected vaccine/dose visit. Record actual administration time, manufacturer, lot, expiry, dose, route, site, consent evidence and administering staff. Future administrations and expired lots are rejected. Given doses cannot be posted twice. |
| `/suite/rehabilitation/` | Record the clinician, baseline, goals, intervention plan and review date. Complete/cancel with an outcome. |
| `/suite/rehab-sessions/` | Append interventions, response, progress and next-visit date. Closed plans reject new sessions; corrections to existing sessions remain possible with a reason. |
| `/suite/specialty-follow-up/` | Facility worklists for due vaccination visits, latest maternity follow-up, active rehabilitation reviews/sessions and overdue/upcoming theatre cases. |

Theatre reservations check overlap with other theatre cases and outpatient appointments for the patient, clinician and room. Booking also checks recorded clinician time off. Resource locks serialize competing requests in PostgreSQL; the CI contention test verifies one successful booking for a contested slot. Starting a second case is blocked while the same patient, surgeon or room is in another active procedure. This is not an operating-room capacity or staffing optimizer.

Due dates come from staff-entered records. The latest unamended maternity visit determines the current follow-up date; a new visit can replace or clear it. The dashboard limits each list to 100 entries and shows the total. A due item does not automatically send an SMS or mark a patient contacted. Use the consent-controlled reminder workflow separately.

## UI

The home workspace now has a local search field. Specialty record lists support patient name, full MRN, record text and status filters, with pagination. Patient summaries show recent specialty episodes to clinical roles. Wide record tables are keyboard-scrollable on desktop and mobile. Each specialty record links to a full detail/history page; long clinical notes are not limited to the truncated table preview. Dates show the clinic timezone, and numeric zero values are retained.

## Upgrade and validation

Install the existing requirements, run `python manage.py migrate`, `python manage.py check`, then `python manage.py collectstatic --noinput`. Migration `operations.0008` adds six specialty models with historical records and constraints; it does not convert existing free-text notes.

Local result: **124 passed, 3 PostgreSQL-only tests skipped**. Django system checks, migration-drift detection and API schema validation passed. The browser run passed on twelve screens at desktop/mobile widths, including a synthetic vaccination creation/administration flow. Remote PostgreSQL results have not been verified.

`tests/test_specialties.py` covers handoffs, conflict rejection in both booking directions, case overruns, episode closure, amendments, lot expiry, future administration, final-state protection, roles/facility isolation, UI submissions, search and current follow-up dates. `tests/test_concurrency.py` includes a PostgreSQL-only theatre contention test.

The browser smoke script checks all six specialty workspaces and the follow-up dashboard at desktop/mobile widths. It also checks workspace search. Set `CLINIC_TEST_PATIENT_ID` only on a disposable instance with a synthetic patient to exercise creation and administration through the browser; this optional test writes a vaccination record. Other required environment variables are documented at the top of `scripts/browser_smoke.cjs`. Automated accessibility checks supplement, but do not replace, staff and assistive-technology acceptance testing.

## Explicit remaining depth

- Theatre: anesthesia charts, intraoperative observations, instrument counts, multi-team resource planning and structured surgical complications are not modeled. Readiness stores references to the facility's approved documents.
- Maternity: partographs, individual newborn records linked to a delivery, structured obstetric outcomes and national maternity registers require a further clinically reviewed specification. The delivery visit currently records findings, care and plan as signed documentation.
- Vaccination: automatic age/series eligibility, stock deduction, cold-chain monitoring, structured adverse-event reporting and corrections to a finalized administration are not implemented. Lot details are entered by staff; this module does not establish stock provenance. Record stock movements through inventory and any clinical correction through a signed clinical entry linked by record number until a dedicated correction workflow is added.
- Rehabilitation: specialty-specific scoring instruments and licensed outcome scales are not included.

Facility leads must approve forms, role assignments and pilot scenarios before production use. Live integrations, national reporting conformance, governed decision support and cross-device offline synchronization remain separate workstreams described in `EXPANDED_SUITE.md`.
