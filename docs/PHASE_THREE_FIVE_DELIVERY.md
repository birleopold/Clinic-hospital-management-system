# Phases 3–5: engagement, laboratory and governed clinical delivery

30 September 2026. This is an incremental delivery against the complete implementation tracker, **not completion of all three phases**. No remaining requirement has been removed.

## Implemented workflows

### Contact consent and recall outreach (Phase 3)

`/suite/outreach/` lets authorized reception/clinical staff record verified SMS preferences, current international-format phone and consent/recipient-authority evidence. Opt-out cancels pending/failed notices. A changed patient phone invalidates prior verification. Existing job-level consent alone no longer permits dispatch: verify the current contact preference after upgrading.

`queue_due_recalls` defaults to a count-only preview. `--commit --days 3` queues one generic notice per due recall with valid preferences and one owner task when overdue. Repeated runs reuse the notice/task. Closing a recall cancels queued reminders and resolves its open escalation task. Inactive or transferred owners do not receive a new escalation task; staff must reassign ownership. The command does not send messages.

`dispatch_reminders` requires a real configured idempotent provider. It records each attempt, claims jobs under locks, and distinguishes provider acceptance, definitive non-acceptance and uncertain outcomes. Only explicitly confirmed failures under three attempts are retryable. Timeout, malformed response and interrupted processing require provider reconciliation; there is no blind resend or invented delivery receipt. An opt-out cannot recall a request already claimed for external dispatch. Provider errors are not copied into patient-visible text or audit fields.

### Operational insights (Phase 3)

`/suite/insights/` provides admin/manager facility-scoped metrics and paginated source records for a selectable 1–90-day creation cohort:

- Queue mean: entry to service start, with denominator and excluded count.
- Diagnostic mean: order creation to first approved result, with separate laboratory/imaging counts. It is not receipt-to-final-analyte turnaround.
- Payer rejection: rejected / (accepted + rejected), excluding draft/submitted claims from the rate.
- Current overdue tasks and existing cash/receivables reconciliation links.

The display names missing/invalid timestamps and cancelled records as exclusions. Current statuses are not reconstructed historical period-end statuses. Collections and budget obligations are not labeled profit.

### Laboratory traceability and quality (Phase 4)

`/suite/clinical-operations/` includes laboratory-only custody, aliquot, reagent, QC and run-evidence registers:

1. Record specimen location, handoff/receipt/storage/referral/return/disposal, recipient, condition, timestamp and unique evidence reference. Subsequent events continue the last location/time; disposed specimens cannot move or be split. Replaying identical custody evidence returns the original record; conflicting reuse is rejected.
2. Create an aliquot with its own accession, same order, parent link, quantity/unit and reason. The child begins as collected and requires its own receipt workflow. This records the split; it does not invent parent volume balances or reagent stock consumption.
3. Register reagent lots in quarantine, with opening, expiry and optional shorter use-by dates. Another authorized laboratory reviewer releases the lot. Failed QC quarantines the associated lot, and release remains blocked pending a separately designed validated remediation process.
4. Record manual quality observations against actual equipment, reagent, control lot and approved procedure reference. A separate reviewer acknowledges them. No reference limits or clinical pass/fail calculations are supplied by the application.
5. Attach passing reviewed QC evidence to an unreleased laboratory worksheet. Run time must fit the reviewed QC window; reagent release, expiry, quarantine and recorded equipment maintenance/calibration are checked. Report release rechecks attached evidence. Subsequent quarantine prevents release; historical re-release of a lot is treated conservatively.

**Limit:** QC linkage is explicit and optional in this delivery. Existing reports without attached run evidence are not retroactively QC-certified, and no facility-wide mandatory QC policy is enabled. Equipment-specific procedures, failed-run correction, analyzer transport, volume/consumption accounting and external laboratory contracts remain to commission.

### Governed programmes and imaging references (Phase 5)

Clinical programme definitions contain a clinical owner, source reference, version and locally approved manual workflow. Another qualified reviewer publishes a draft; revised definitions require a new version. Enrollment requires explicit eligibility/consent evidence, clinician and review date, and retains a text snapshot of the published definition. Only one active enrollment per patient/programme name is allowed across versions. Clinical/nursing staff can append review notes, reference amendments and track follow-up. Clinical staff close care as completed/transferred/withdrawn. Reception and management accounts do not gain access to programme records.

No HIV/TB/ANC/NCD eligibility, treatment, dose, interaction, vaccination or scoring rules have been invented. Facility-approved definitions can be entered; disease-specific validated cohort indicators still require their clinical specifications.

The imaging study registry records order-linked study UID, accession, modality, actual acquisition time and source reference. Optional viewer links accept only exact `PACS_VIEWER_ALLOWED_HOSTS` over HTTPS, with no credentials, query tokens, fragments or custom ports. The application does not fetch those links. The external viewer must independently authorize the patient/study. This is a reference registry, not DICOM transport, image storage or a commissioned PACS integration.

## Upgrade and verification

1. Back up the database and private media; retain the previous application revision.
2. Run `python manage.py migrate --noinput` (operations migrations 0028 and 0029).
3. Run system checks and the test suite. Migration 0029 extends canonical-patient guards to the new direct/indirect patient records.
4. Verify role/facility access with synthetic records before entering real records.
5. Review contact preferences before enabling the supervised reminder dispatcher. Preview recall counts first; do not enable external sends without a commissioned provider and facility consent process.
6. Configure exact approved viewer hostnames only after authorization review.
7. Roll back application/database together from the verified backup if necessary. Do not reverse migrations over live records as a routine rollback.

Automated regressions cover consent/opt-out, changed phones, idempotent recall queueing, provider uncertainty, controlled retries, custody sequence/disposal, aliquots, independent reagent/QC review, report-release blocking, programme snapshot/role checks, viewer allowlists, facility selectors and metric denominators. No real patient messages or provider financial transactions are sent in these tests. Browser checks include the new screens at desktop/tablet/phone widths, automated accessibility and JavaScript/overflow checks. Facility clinical acceptance and hardware/provider commissioning remain separate gates.

## Remaining completion gates — not merely testing

| Scope | Concrete next requirement / owner |
| --- | --- |
| R3 portal | Identity-verification method and guardian/delegated scopes; implementation and acceptance still required. |
| R3 WhatsApp | Facility-approved consent/templates, selected provider and sandbox credentials; implement actual transport and receipts. |
| R3 profitability | Supplier settlement, reconciled expense/cost attribution and accounting policy; implement before calling any figure profit. |
| R4 payments/payer/government | Provider/payer selected, sandbox access, signed transport/mapping specifications, EFRIS applicability and approved DHIS2 indicators/endpoint. Actual adapters and commissioning remain. |
| R4 laboratory | Lab owner approves mandatory QC policy, correction/remediation and device mappings; implement actual analyzer/LIS protocol and test with recorded device messages. |
| R4 security/branches/setup/import | Admin MFA, granular authorization review, authorized branch switching, guided configuration and expanded migration preview/reconciliation are still engineering work. They are not blocked solely by credentials. |
| R4 operations/business | Production load/recovery rehearsal, hosting/license/support ownership and agreed recovery/service targets. |
| R5 clinical rules/specialties | Clinical owners supply current approved/licensed knowledge, terminology, cohort indicators, labour-chart/scoring specifications and multi-team theatre acceptance criteria. Implement and validate those concrete rules. |
| R5 imaging/telehealth | Actual PACS/device/viewer contract and authorization tests; selected teleconsultation requirements/provider. Storage/transport and teleconsultation remain unimplemented. |

The separate workforce and patient/staff/operator backlog remains applicable, including managerial delegation, coverage policy, missing-clock-out correction, preparation/transport, specialist fees and other items marked partial/pending. This release does not close them by implication.
