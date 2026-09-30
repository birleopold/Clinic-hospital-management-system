# Care documentation and recovery release

30 September 2026. This release adds operational controls and clinical documentation. It does not claim every possible hospital feature, national approval or production clinical acceptance.

## Added workflows

| Area | Implementation |
| --- | --- |
| Vaccine stock | Select clinic stock or an external/previously issued dose. Clinic administration locks the batch and consumes the entered base-unit quantity atomically, with a stock movement tied to the vaccination. Requires matching lot/expiry, facility, adequate balance and no quarantine. External doses require a provider/previous-issue reference and do not deduct stock again. |
| Vaccine corrections | Submit a field correction with a reason. A different clinician reviews it; stale corrections cannot overwrite a newer review. Original values and full model history remain. A status correction can mark the record `entered_error`. Corrections never assume that stock was physically returned. |
| Suspected adverse events | Document onset, observed event, staff-assessed seriousness, action and follow-up. A clinician reviews and closes follow-up with an assessment. This does not establish causality or automatically notify a regulator. |
| Cold chain | Create a storage protocol with source/version and explicit temperature limits; a different manager approves it. Record batch temperature and device reference. Readings outside the approved limits quarantine the batch. A subsequent normal reading does not release quarantine; a manager must document that decision in stock control. No universal storage temperatures are seeded. |
| Theatre | Authored anesthesia, intraoperative, complication and handoff entries, with append-only amendments. Instrument counts include phase, item group, expected/actual totals and discrepancy notes. All recorded counts need second-person verification before case completion; discrepancies require a resolution. The existing facility checklist remains mandatory for readiness. |
| Maternity | Delivery records tied to the pregnancy; separate newborn identities, birth order, outcome, weight and recorded Apgar totals; time-stamped labour observations with amendment history. Infant identity must be separate, in the same facility, and have a matching birth date. |
| Rehabilitation | Versioned instrument/source references, recorded scores/units and clinician interpretation. No licensed scoring content or automatic interpretation is bundled. |
| Recovery | Hash verification and isolated SQLite/media restoration; rejects overwrites, changed files, archive traversal and links. A separate CI-only PostgreSQL drill creates its own temporary database, restores a real dump and compares row counts. |
| PostgreSQL fix | Backorder fulfillment locks the backorder row explicitly instead of trying to lock the nullable side of a joined prescription record. This fixes a failure found in the previous PostgreSQL CI run. |

These records use the existing role/facility scopes, full detail pages and model history. Newborn access is scoped through the delivery/mother facility; a child's independent patient identity is checked separately. Corrections and clinical records are not automatically transmitted externally.

## Use and upgrade

```sh
git pull origin main
python -m pip install -r requirements-core.txt
python manage.py migrate
python manage.py check
python manage.py collectstatic --noinput
```

Migrations `0009` and `0010` add these records and vaccine stock metadata. Existing vaccine administrations are classified as external/previously issued without retroactive stock deduction. Before using a previously scheduled vaccination, select and verify its stock source; an external/previous-issue reference is required when recording administration.

Vaccination base inventory units are not the dose's clinical volume. Staff must verify the chosen inventory item, lot and unit conversion. There is no automatic dose calculation or automatic invoice creation from this administration record. Do not select “consume clinic stock” for a dose already deducted by a pharmacy dispense.

An erroneous administration can be flagged through a reviewed status correction. A genuine physical return, wastage correction or financial adjustment is a separate reviewed stock/finance operation. This prevents documentary corrections from inventing usable stock.

### Recovery drill

```sh
python manage.py backup_bundle /secure-backups/clinic-YYYY-MM-DD
python manage.py verify_backup_bundle /secure-backups/clinic-YYYY-MM-DD /secure-drills/clinic-YYYY-MM-DD
```

The destination must not exist. The command restores into that directory and never replaces the configured database/media. `restore-report.json` contains hash/integrity results and counts, not patient records. Both backup and restored data still contain confidential information; protect the directories and use encrypted storage. The default media expansion limit is 5 GiB and is configurable with `--max-media-bytes`.

The PostgreSQL CI drill is `scripts/postgres_restore_drill.py`. It refuses a non-local server, requires CI mode and the disposable `hms` database, creates `clinic_restore_drill` itself and never drops a pre-existing target. It is not a production restoration command. Use [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md) for the production runbook and rehearse staff workflows after restoration.

## Verification

Local regression result: **136 passed, 3 PostgreSQL-only tests skipped**. Django checks, migration drift and API schema validation pass. Browser checks cover 22 workspace pages, the full-record page, search and a synthetic vaccine administration at desktop/mobile widths, with automated accessibility and JavaScript checks. A real local SQLite bundle restored successfully into a separate directory; tests also cover media restoration, tampering and malicious archive paths.

The prior GitHub PostgreSQL run identified the backorder join-lock failure described above. The fix and new PostgreSQL restore drill passed all four Python 3.11/3.12 × SQLite/PostgreSQL jobs in [run 36684075334](https://github.com/birleopold/Clinic-hospital-management-system/actions/runs/36684075334). A CI restore drill complements, but does not replace, a facility's production recovery rehearsal.

## Remaining scope and external acceptance

This release closes specific gaps in [SPECIALTY_WORKFLOWS.md](SPECIALTY_WORKFLOWS.md). The following are still distinct workstreams, not completed features:

- Full offline transactional operations. The subsequent [disconnected-device release](OFFLINE_DRAFTS.md) implements encrypted clinical drafts with synchronization and conflict detection; financial, stock and release operations still require the application server.
- Governed drug-interaction/dose decision support and automatic vaccination eligibility. These require an approved clinical knowledge source, licensing where applicable, and clinical validation.
- Full multi-team theatre resource optimization, a validated graphical partograph, and specialty-specific licensed scoring engines. The records above support staff documentation without implementing these engines.
- National HMIS mappings/submission certification and insurer-specific electronic submission. Approved forms, code mappings, contracts and test endpoints are required.
- Live MTN/SMS credentials, provider onboarding and end-to-end commissioning; original-provider payment refunds and other provider adapters.
- Facility permission review, load targets, clinical acceptance, comprehensive simultaneous-write patient-merge hardening, and production backup recovery drills.

### Reference design sources

The immunization correction/status terminology and explicit lot/expiry data were checked against [HL7 FHIR R4 Immunization](https://hl7.org/fhir/R4/immunization.html). Separate infant identity and maternal linkage were checked against the [FHIR R4 newborn/mother example](https://hl7.org/fhir/R4/relatedperson-example-newborn-mom.html). These are design references, not a claim that these Django models or existing exports implement the complete FHIR resources.
