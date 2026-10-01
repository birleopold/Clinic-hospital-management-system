# Isolated tenant control and financial approval limits

This delivery adds complete owner/admin workflows to the existing application. It
is not completion of every requirement in the suite plan. The implementation
tracker retains outstanding engineering, provider commissioning and facility
acceptance separately.

## Independent tenant boundary

Independent businesses run **separate application processes, databases, private
media volumes, signing keys and Redis queues**. Facilities inside one deployment
remain branches of one business. Shared medicine catalogues, suppliers and prices
are therefore shared only inside that business. Never connect two independent
tenant application instances to the same database, media volume or signing keys.
This physical deployment boundary replaces the proposed shared-database tenancy
rewrite; existing clinical, stock and financial records are not copied into a
second workflow.

Enable the owner console on its own production instance using
`OWNER_CONTROL_PLANE=1` and `TENANT_PUBLIC_ORIGIN=https://owner.example.org`.
Production requires administrator MFA and an HTTPS origin. Use a dedicated owner
database with no tenant patient, stock or financial records. The owner dashboard
links **Independent tenant deployments**. Register a tenant, choose its services
and private application port, then download its protected deployment bundle.
Repeated registrations for the same origin/port cannot create another tenant;
re-downloading its bundle preserves its identity and keys. Secrets are encrypted
in the owner database and never displayed in the registry.

Build the reviewed image once:

```sh
docker build -f deploy/tenants/Dockerfile -t clinic-hms:tenant-v1 .
```

Extract each bundle into its own protected directory and run `docker compose up
-d`. A trusted HTTPS proxy must route only that tenant hostname to its specified
loopback port and replace forwarded-protocol headers. PostgreSQL and Redis have
no published ports. Compose project names provide distinct networks and volumes.
Private media is not served publicly. Back up each tenant database and media
separately and retain the corresponding keys. Redis uses append-only persistence.
The worker waits until migrations/bootstrap and application startup complete.

Bootstrap initializes only a fresh tenant; retries do not replace users,
configuration or passwords. Django Guardian's framework anonymous account does
not prevent initialization. The administrator logs in with the protected bundle
credentials, changes the bootstrap password, enrolls MFA, then configures branding
and recruits staff through the existing screens.

A signed, audience-bound policy heartbeat activates a deployed tenant. The owner
can suspend/resume with a reason and optimistic revision checks. Unavailable,
invalid or suspended policy blocks ordinary browser/API traffic with a five-second policy cache and a three-second socket timeout for retrieval. Queued Celery tasks retry rather than disappear. Work
already executing is not forcibly interrupted; suspension is an entry-point gate.
Owner policy availability is therefore a dependency for tenant operation. Do not
promise offline clinical/financial operation or any uptime target from this gate.

**Open audited owner support** records a reason and issues a 30-second single-use
POST ticket signed with that tenant's separate trust key. The tenant creates a
30-minute browser support session with an unusable password. Support accounts cannot obtain or use JWT credentials, change permanent credentials, enroll authenticators or open system administration. A valid receipt and its original session marker are required even if a support account password is later changed. This ticket does not grant access to the owner registry. Support remains
available during suspension. Under **Choose services and branding**, tenant
administrators can review and revoke support sessions. Expired or revoked support
sessions are logged out on their next request. The cross-origin support form sends
only the signed ticket; it never sends the owner's CSRF token.

## Financial approval matrix

**Facility setup → Approval limits and timed delegation** provides ordinary admin
forms for workflow policies, grants, expiry, amount limits and revocation history.
Only scoped facility administrators can configure the matrix. They cannot grant
authority to themselves. Recipients must be active administrators/managers assigned
to that facility; authority does not change their role or clinical privileges.
Grant request IDs provide exact-retry deduplication; overlapping grants are
rejected. Limits and intervals are immutable: revoke and issue a reviewed
replacement. All configuration/grant/revocation actions produce security events.

Existing role and independent-review requirements remain mandatory. A disabled
matrix retains existing supervisor behavior for upgrades. An enabled workflow
requires a matching active grant, including for superusers. Revoking the last
grant keeps approvals blocked. Completed decisions remain retry-safe after grant
expiry. Limits cover:

| Workflow | Amount evaluated |
| --- | --- |
| Purchase order | Sum of ordered quantities × unit cost |
| Operating budget | Proposed budget amount |
| Operating expense | Proposed obligation amount |
| Expense reconciliation | Individual disbursement evidence amount |
| Invoice credit | Credit amount |
| Cash refund authorization | Requested refund amount |
| Medicine return | Actual computed credit |
| Basket price change | Absolute unit-price change × entire line quantity, rounded to cents |

Return review also checks the refund limit before automatically authorizing any
cash refund. A denial rolls back the entire stock/credit/refund transaction. These
are per-decision limits, not cumulative daily budgets, procurement contract limits
or authority to split a transaction deliberately.

Refund authorizations now snapshot amount and original payment. A changed refund
cannot be paid against its old authorization. Legacy authorizations have no
snapshot and require a supervisor to revalidate the original approval through the
existing refund screen before payout. Revalidation updates the existing
historied authorization, preserves its original creator and attributes the new
history to the reviewing actor; no duplicate refund or authorization is created.
Non-cash refunds still require their original provider.

Patient-link audit paths are redacted for every portal endpoint, including
feedback, preparation acknowledgment, booking changes and revocation.

## Verification and upgrade

Install `requirements-core.txt` (adds Cryptography for encrypted control-plane
secrets), apply accounts migrations 0010–0011 and operations migration 0038, then
run the normal checks. Tenant deployment additionally installs
`requirements-tenant.txt` for Gunicorn. Existing deployments do not become owner
consoles automatically, and no tenant registration deploys itself to a host.

The disposable HTTPS review runs three independent applications with separate
physical SQLite databases, media directories and keys; it does not touch an
existing database. It exercises real signed suspension/resume policy, owner
registration/bundle/support and tenant revocation, cross-tenant JWT/patient-link
rejection, shared stock-code isolation, administrator MFA and approval-matrix
forms. It checks 1440/768/390 widths, overflow, JavaScript errors and automated
WCAG 2/2.1 AA. Install Node Playwright/axe-core and Chromium, then run:

```sh
python scripts/tenant_control_review.py
```

Optional `CLINIC_CHROMIUM_PATH` and `CLINIC_AXE_PATH` select already-installed test
resources. The runner uses disposable self-signed HTTPS certificates on loopback
addresses 127.0.0.1–3, port 8443; production certificates/proxies are separate host
acceptance. Docker image startup, real host isolation/recovery/load, live providers
and manual clinical/accessibility acceptance are not established by this review.

Additional monetary transaction regressions cover permission boundaries, expiry,
revocation, exact replay, policy revisions, limit boundaries, purchase totals,
whole-line price changes, credit/return atomic rollback and legacy refund
revalidation. The standard CI matrix checks Python 3.11/3.12 with both SQLite and
PostgreSQL and the PostgreSQL restore drill. Exact results are recorded in the
associated pull request after validation.

Release verification on 1 October 2026: local full SQLite suite **298 passed, 17 skipped** before the final Compose/worker checks; financial transaction suite **28 passed**; final targeted tenant suite **8 passed, 1 skipped** (Compose unavailable locally). The three-instance HTTPS/browser review above passed, including all three viewport widths and automated WCAG checks. The pull request records the final four-job CI matrix results.
