# Completion boundaries and workforce follow-through

5 October 2026. This delivery closes concrete backend, screen and authorization
gaps found while reviewing PR2. It does not mark every later roadmap phase complete.

## Access and module boundaries

- Temporary owner support cannot recruit/promote permanent users, change approval
  policies/grants, change credentials or approve account offboarding. Endpoint and
  service checks preserve this boundary even outside the normal middleware path.
- Permanent role changes and account deactivation require reassignment or closure
  of open consultations, tasks, cash/attendance sessions, diagnostic work and
  published duties, including supervision and backup assignments.
- Patient directory APIs explicitly enforce their read roles. Worklist roles
  receive identity fields only; registration/clinical roles retain their existing
  full demographics access. Store and radiology do not gain general patient search.
- Nurse result lists, details, nested order results and private downloads expose
  released results only. Authorized lab/clinical review remains available, with
  facility and enabled-service filtering.
- Appointment and clinician availability/time-off reads now share facility and
  role boundaries; rescheduling rejects another facility's clinician.
- Disabled modules are filtered in queue summaries/actions, laboratory worklists,
  specialty follow-up, operational insight sources and mixed diagnostic templates.
  Direct clinical history/upload, barcode and import routes enforce their module.
- Radiology has the shared scoped task inbox and handoff ownership, without
  acquiring full-chart or unrelated clinical privileges.
- Financial workflow records and their line inlines are read-only in Django
  admin, including for superusers. Admin inspection links to guarded application
  workflows rather than bypassing independent review or financial approval limits.

## Workforce screens and services

- The staff directory supports audited employment type, status, start/end dates,
  revision checks and credential renewals that retain the original record.
  Employment eligibility is separate from login access. Existing staff without an
  employment record keep their prior eligibility until the facility configures it.
- Managers can configure minimum simultaneous department/role coverage and publish
  a group of draft duties atomically. Overlap, leave, employment and stale-revision
  checks apply to the entire group. Cancellation cannot silently violate configured
  coverage. These are facility-entered staffing requirements, not a clinical safety
  certification or an assumed staffing ratio.
- Effective-dated attendance policies configure grace and worked-minute rounding.
  Clock-in stores a policy snapshot. Original timestamps and exact totals remain;
  adjusted totals are separately labeled and included in reviewed exports. This
  does not implement payroll or assert legal compliance with local employment rules.

## Upgrade and verification

Apply operations migration `0039_workforce_completion` using the normal upgrade
procedure. Existing records are retained; policy and employment setup is explicit.
The migration refreshes canonical-patient guards around SQLite schema changes.

New regressions cover forbidden direct URLs/POSTs, support identity escape,
per-role API representations, private result downloads, disabled-module queues,
financial admin write attempts, cross-facility scheduling, employment/renewals,
grouped coverage publication and attendance policy snapshots.

Local Python compilation and whitespace checks pass. Local Django tests and
migration/schema checks could not start because required dependencies were absent
and the package download proxy denied the Django wheel request. Full verification
must therefore use the associated commit's four-job SQLite/PostgreSQL,
Python 3.11/3.12 CI matrix before considering the code validated. Exact CI results
belong to the commit, not to earlier PR2 runs.

Remaining tracker work is preserved, including nonfinancial acting-supervisor
delegation, broader granular permissions/audit review, automated escalation,
historical imports, integrations, provider onboarding, clinical specifications,
real-host deployment/recovery/load testing and staff/accessibility acceptance.
