# Phase 1: daily workflow release

The software scope of R1 is implemented. [IMPLEMENTATION_TRACKER.md](IMPLEMENTATION_TRACKER.md) retains every later phase and separates shipped functionality from facility acceptance. No live provider or clinical sign-off is implied.

## Daily use

- Start at the role workspace, department board or owned-task inbox. Boards retain facility and role restrictions. Reception/triage/consultation queues, laboratory stages, prescriptions, ready invoices, ward occupancy and theatre cases link to existing actions.
- Registration opens the patient's chart. A service handoff reuses an active ticket and does not finish the previous service. A clinician can accept an open nurse/unassigned visit; another clinician's visit cannot be silently taken over.
- The patient chart combines original records with paginated visit, observation, note, result, prescription, referral, document, care-plan and specialty sections. Billing appears only to authorized finance/admin roles. Reception sees appointments; pharmacy sees prescriptions and allergies; lab sees its result scope. Draft results remain explicitly labeled and restricted.
- Patient context persists through chart, encounter, order, pharmacy, cashier and related collection forms. Scoped searchable selectors return at most 30 results and keep the chosen record. Server validation uses the complete permitted queryset.
- Tasks may concern a patient or general facility work. Each has an audience, optional owner, due date, next-action instruction and resolution history. Stale revisions cannot overwrite newer work. Completed/cancelled tasks cannot be reopened through this UI. Results, referrals and reminders can seed linked follow-up tasks.
- Consultation templates are published as distinct immutable versions. New notes record the template snapshot, author and optional same-patient source/amendment. Reuse requires explicit review; earlier notes remain intact. Closed visits reject new consultation notes.
- Private patient documents accept PDF/JPEG/PNG up to 10 MiB with type-signature validation. Downloads enforce facility/role scope, use attachment disposition and disable caching. This is not malware scanning: add a deployment-approved scanning/quarantine service if required by the facility's document policy.

## Upgrade and operation

1. Back up database and private media using the existing deployment procedure.
2. Install the release and run `python manage.py migrate`, then `python manage.py collectstatic --noinput`.
3. Run `python manage.py check` and verify synthetic records with each assigned staff role before reopening service.

Migrations 0013–0014 create the task, template, consultation-note and document models/history. Tasks created through the UI receive a facility. Imported tasks must also be assigned a facility to appear in normal staff workspaces.

Migration 0015 installs canonical-patient database guards for the current schema on SQLite and PostgreSQL. Direct and indirect patient writes, including bulk writes that bypass model hooks, reject archived identities. PostgreSQL patient-row SHARE locks serialize these checks against the merge service's row locks. History, merge provenance and duplicate reviews intentionally retain source identities. A request rejected because identity changed returns a conflict response so staff can reload the canonical record. Existing merge permissions, review and audit requirements remain.

**Future migrations must review these guards:** adding patient-related tables or relations, or rebuilding SQLite tables, requires a follow-up migration to recreate/update affected guards. The migration derives paths from its historical application state, not models added later. Other database engines are not covered. Keep merges within the existing reviewed service; avoid direct database identity edits.

Serve private media through authenticated application access or equivalent protected storage. Do not expose the media directory as a public document directory. Browser scripts and CSS changed; ensure the deployed static asset cache is refreshed. No new external service or frontend framework is required.

## Verification evidence

- Local regression suite: 178 passed; five PostgreSQL-only contention checks skipped on SQLite. CI runs the full suite on PostgreSQL and SQLite across supported Python versions, including migration checks and the existing backup/restore drill.
- New coverage verifies task revisions/ownership, immutable note provenance, file access and validation, scoped lookups, laboratory tabs/accessions, idempotent handoffs, bounded chart queries, visit ownership and late writes to merged identities.
- A synthetic journey uses six real staff roles: registration, nurse triage/vitals, clinician acceptance/note/order, lab specimen/result, clinician review/release and prescription, pharmacy dispense, cashier payment and each service's queue completion. Assertions retain the same patient/encounter and verify stock/payment outcomes.
- Browser checks exercise 390, 768 and 1440 widths, automated accessibility, overflow, JavaScript errors, menu keyboard dismissal, patient preselection, asynchronous search and task completion. Automated accessibility is not a substitute for manual screen-reader review.

### Repeatable performance sample

On a disposable development database with DEBUG enabled:

```sh
python manage.py benchmark_phase_one --confirm-disposable
```

The command creates synthetic data inside a transaction and rolls it back. The measured SQLite sample used 5,000 patients, 500 notes in one chart and 20 requests per endpoint:

| Endpoint | Median | p95 | Maximum queries |
| --- | ---: | ---: | ---: |
| Patient chart | 17.38 ms | 21.91 ms | 16 |
| Patient search | 6.40 ms | 9.58 ms | 7 |

These are in-process Django client measurements, excluding network/browser latency. They do not establish production capacity or concurrent-user targets. Feed hydration is limited to 25 records per page; lookup results are bounded to 30. More indexing should follow measured production query plans rather than guesses.

## Facility acceptance still required

A named facility reviewer should record pass/fail, observed time, clicks/errors and any correction for each item:

1. Returning/new patient registration, duplicate handling and handoff through all six departments without wrong-patient or lost-visit context.
2. Two clinicians accepting visits, copied-note attribution, amendments and closed-visit behavior.
3. Task assignment, overdue work, source follow-up, stale updates and audited resolution.
4. Lab stages with a physical scanner; ward occupancy, theatre readiness, count verification and cancellation reasons.
5. Keyboard-only and screen-reader operation, visible focus/error handling, and the facility's actual tablet/mobile devices.
6. Production-like data/concurrency on deployment hardware; agreed search/check-in targets and baseline click measurements. No 30% click-reduction result has been measured.
7. Protected document storage/download and backup/restore including private media.

These acceptance gates stay open until reviewers supply evidence. Phase 2 pharmacy/financial work has not been silently included or marked complete; its catalog, scanner basket, checkout and reconciliation requirements remain in the tracker.
