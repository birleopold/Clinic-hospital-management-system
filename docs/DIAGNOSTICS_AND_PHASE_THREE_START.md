# Diagnostic/visiting additions and Phase 3 first delivery

Phase 2 remains complete at its recorded software scope. This release extends the workforce/manager work and starts Phase 3. It does not mark the whole roadmap complete.

## New entry points

- `/suite/diagnostics/`: lab/imaging/procedure worklist, operator assignment, appointment time, modality and preparation notes, procedure start, worksheets and review. Radiography/imaging is a new account role; its new worklist scope is imaging only. Existing shared lab/clinical routes retain their prior role policies.
- `/suite/diagnostics/templates/`: create a new immutable version with up to 60 text/numeric/choice fields, required flags, units and approved reference context. Add fields through the form; another qualified reviewer publishes the version. Retired versions cannot start new worksheets. No clinical test ranges or automated interpretation are fabricated.
- Worksheets require an assigned operator who started the service. Laboratory sheets also require a received specimen from that order. Draft snapshots cannot be edited through the legacy result API. Withdraw and replace a draft, or amend a released result with a reference. Duplicate submissions reuse the request key; conflicting replays fail. A different qualified reviewer releases the report; imaging interpretation requires clinician/admin review, not merely the radiography operator role.
- Released report pages support browser print/save as PDF and a downloadable text copy. They identify patient, source order, reporter, reviewer, date and amendments. Superseded result versions remain in history; the patient printout shows current released versions. Stored films, DICOM images, PACS and analyzer connections are not implemented by a report template.
- `/suite/visiting-specialists/`: admins register a dedicated non-admin clinician account, credential evidence and expiry, then authorize an assigned theatre case within a bounded date window. The account becomes restricted to `/suite/visiting/`; both session requests and general JWT API access are denied outside that portal. A previous staff token does not bypass the restriction. Share credentials only after the restriction and grant are configured.
- Visiting specialists see only current assigned cases and may sign append-only notes with amendments. Notes remain in the local clinical chart and administrator case register when access expires or is revoked. No full patient-list permission is granted. The limited case page is not a full preoperative chart; local staff must supply and review the approved clinical packet. Visiting fee/contract/payable workflows remain planned.

## Phase 3 started

Reception can optionally enable appointment requests while creating a patient portal link. This requires a named recipient, recorded identity verification and, for guardians, authority/consent evidence. Existing grants remain read-only. The short-lived bearer link still grants access to the existing patient summary: share securely with the verified recipient. It is not OTP/MFA or identity-provider verification.

Patients submit a preferred date/reason, not a booked slot. Requests have retry keys and a limit of five pending requests per patient. Reception reviews them at `/suite/appointment-requests/`, then books a conflict-checked appointment or declines with a response visible through the same link. Revoked/expired grants cannot submit requests. Appointment scheduling now checks approved staff leave; leave approval also checks existing appointments/theatre cases.

The patient portal includes released imaging/procedure narratives in addition to lab results. `/suite/recalls/` provides clinical-staff-entered due dates, owners, outcomes, overdue visibility and explicit repeat intervals. Completing a repeating recall creates one next recall, safely across retries. No SMS, WhatsApp or other outbound message is sent by this workflow. Preference/opt-out, delivery retries, operational KPIs and live provider commissioning remain Phase 3 work.

## Upgrade and acceptance

Apply accounts migration 0004 and operations migrations through 0027, then collect static files. Canonical-patient guards cover all new patient-linked records. Existing credentials/accounts are not automatically converted to visitors and no clinical template is auto-published. Read `WORKFORCE_MANAGEMENT_RELEASE.md` for the preceding workforce and managerial migrations.

Review facility worksheet wording, units/ranges, reviewer qualifications, visitor identity/credentials/access windows and patient-link authority. Physical scanners/printers and actual equipment protocols still need facility acceptance. Staff-managed verification is not a substitute for a selected future identity-provider integration.

The expanded patient/staff/operator/owner requirements, with implemented and planned items separated, are in `PATIENT_STAFF_OWNER_BACKLOG.md`. No planned scope is removed from `IMPLEMENTATION_TRACKER.md`.
