# Enterprise access, reviewed imports and labour observation display

30 September 2026. This delivery closes additional engineering gaps in the Phase 3–5 tracker. It does not claim that all planned integrations or clinically governed features are complete.

## Administrator MFA

Administrators and system superusers must enroll and verify a TOTP authenticator by default (`REQUIRE_ADMIN_MFA=1`). Other staff can enroll voluntarily; enrollment sets a persistent MFA requirement, so removing a device does not downgrade that account to password-only access.

- `/accounts/mfa/enroll/` requires the current password before showing a private, ten-minute enrollment QR/secret. Confirmation requires an authenticator code.
- `/accounts/mfa/` verifies subsequent sessions. Codes are single-use, with django-otp throttling and the existing login-attempt limiter.
- Password authentication alone cannot access protected pages or session-authenticated APIs while verification is pending.
- `/api/auth/token/` accepts `otp_token` when MFA is required. Access/refresh tokens bind to the confirmed device; old password-only tokens and revoked device tokens are rejected. Role changes to administrator also invalidate inadequate old tokens.
- Secrets, passwords and submitted codes are excluded from application security events and marked sensitive for Django error reporting. Enrollment responses are private/no-store. Protect the database and backups because the authenticator seed must be available to the verifier.
- Device management is removed from the generic Django admin. Security events are read-only there.

### MFA browser form correction (5 October 2026)

Enrollment HTML uses `Referrer-Policy: same-origin`. The previous `no-referrer`
header made native browser form submissions send `Origin: null`, causing Django's
CSRF protection to reject password confirmation and authenticator enrollment even
in a normal same-origin tab. The correction preserves referrer privacy for external
destinations, private/no-store responses, and all CSRF token/origin checks. It does
not trust null or foreign origins. See [MDN's form-origin behavior](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy#effect_on_the_origin_header)
and [Django's CSRF referrer guidance](https://docs.djangoproject.com/en/5.2/ref/csrf/#removing-the-referer-header).

After updating the application and restarting a running server if needed, reload
`/accounts/mfa/enroll/` before retrying so the browser receives the corrected header.
This fix adds no migration. Do not add `null` to trusted origins or disable CSRF.

Recovery is a privileged server action after the facility's independent identity-verification procedure. It is a preview unless `--commit` is supplied:

```bash
python manage.py reset_staff_mfa USERNAME --operator SYSTEM_SUPERUSER --reason "Verified recovery evidence reference"
python manage.py reset_staff_mfa USERNAME --operator SYSTEM_SUPERUSER --reason "Verified recovery evidence reference" --commit
```

The command revokes devices and records the attributed reason. It does not change the password or send messages. Re-enrollment still requires the current password. Server access itself is privileged; the command's operator argument records accountability, not a separate server authentication mechanism. Keep trusted server recovery available before enforcing this upgrade.

Implementation uses [django-otp's TOTP verification and replay/throttling controls](https://django-otp-official.readthedocs.io/en/stable/overview.html). No custom OTP algorithm was introduced.

## Authorized facility selection

`/accounts/facility/` selects the working facility for this browser session. Home-facility access remains available. Additional branch grants are administered by MFA-verified system superusers and record recipient, facility, expiry, reason and revocation. Grants are checked on every request; expired/revoked selections fail closed with a link to select an authorized facility.

Additional grants are limited to administration, management and reception. They do not change employment records, roles, clinical credentialing, staff scheduling or doctor assignment. The grant system assumes branches belong to one organization; it is not SaaS tenant isolation.

JWT clients can send `X-Clinic-Facility: FACILITY_ID`; authorization is rechecked for each request. Omitting the header uses the existing home-facility behavior (all facilities for a system superuser). Selecting a facility also narrows the shared scope helpers for system superusers. Their Django administration remains explicitly global.

Existing aggregate reports support a system-superuser all-facility view or a selected facility. Per-branch comparison exports and broader clinical cross-branch privileges remain separate scope.

## Setup and patient migration

`/suite/setup/` provides a readiness checklist with scoped facility, department, staff, published diagnostic/programme template counts and links to setup/import/security workflows. Counts do not certify clinical approval. Enabled-module policies, configurable approval matrices and a full price/rules wizard remain tracked separately.

`/suite/imports/` provides a downloadable blank UTF-8 CSV template and preview/history. Exact columns:

```text
external_id,first_name,last_name,gender,date_of_birth,phone,email,address
```

Use a stable source-system name and external ID. Limits are 1 MiB and 500 rows per reviewed batch. Preview validates fields, dates, duplicate source IDs and likely existing identities; it records row-specific errors without creating patients. Another authorized admin/manager must approve an unchanged error-free preview. Commit revalidates against current records and is atomic. Any new conflict rolls back every patient created by that commit.

Matching source identities with identical data are skipped on re-import; conflicting data is rejected for manual reconciliation. The import does not overwrite clinical records, infer consent, mark allergies reviewed or silently merge people. New patients retain unknown allergy status and unrecorded consent. Source-to-patient mappings, batch counts, reviewer, evidence and history remain available. Patient-merge database guards extend to the mappings.

Suspected duplicates must be reconciled using the existing patient identity process before a corrected upload. This is demographics import plus the existing inventory import; historical encounters, opening financial balances and programme migration require dedicated reconciliation workflows and are not silently handled by this CSV.

## Labour observation trends

The maternity episode links to `/suite/pregnancies/ID/trends/`. Authorized clinical staff see the latest 200 current observations, six numeric scatter plots and an accessible exact-value source table. Axes use actual observation times. Superseded records are omitted from the current display but remain in source history. Missing values are not interpolated.

This is a display of recorded dilation, fetal/maternal pulse, blood pressure and temperature. It does not provide clinical alarm thresholds, alert/action lines, labour scoring or a validated partograph. Those still require the reviewed clinical specification and acceptance owner from SPECIALTY-01. The source-table links retain findings, plans and authorship.

## Upgrade

```bash
git pull origin main
python -m pip install -r requirements-core.txt
python manage.py migrate --noinput
python manage.py check
```

Back up database/private media and rehearse restoration before upgrade. New migrations include accounts 0005–0008, operations 0030–0031 and django-otp's TOTP schema. On first administrator login, complete authenticator enrollment and the facility service setup at `/accounts/setup/`. Server recovery procedures must be ready before deployment. Do not use `REQUIRE_ADMIN_MFA=0` in production to evade enrollment; the setting exists for isolated development/test fixtures.

Automated tests cover enrollment, password confirmation, replay rejection, session/API enforcement, token refresh and revocation, branch grants/expiry scope, independent imports, atomic revalidation, unchanged re-import, default consent, clinical chart scope and amendment selection. The full role suite runs with the MFA policy isolated; dedicated security regressions explicitly enable it. Browser regression covers setup, import, branch selection and initial authenticator enrollment screens at 390/768/1440 widths. Hardware scanning, staff acceptance, production recovery and clinical interpretation remain facility checks.

## Still required for whole-phase completion

The tracker retains portal identity/delegation refinements, messaging-provider delivery/reconciliation, WhatsApp, expense settlement/profitability, actual payment/payer/government/analyzer/PACS transports, granular authorization review, full configuration and migration scope, approved clinical knowledge/scales, multi-team theatre resources and teleconsultation. Some are still engineering tasks; others need provider contracts/access or approved clinical/business decisions. None are described as merely pending tests.
