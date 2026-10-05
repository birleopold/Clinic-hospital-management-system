# Tenant administration portal and operator runbook

This is the platform owner's register for separately deployed customer businesses.
It builds on the signed tenant-control boundary in
[TENANT_CONTROL_AND_APPROVAL_RELEASE.md](TENANT_CONTROL_AND_APPROVAL_RELEASE.md).
It is development/pilot software, not production certification or a clinical
acceptance sign-off. Read [AUDIT.md](AUDIT.md) before using real patient data.

## What the offering includes

One independent pharmacy, clinic or hospital business receives its own application
processes, PostgreSQL database, private media, signing/support keys and Redis
queues. Facilities within that deployment are branches of that business, not
separate customers. Never share a database, media volume, secrets or Redis between
independent customers. The owner console has a separate database containing the
deployment register and support administration, not tenant clinical, stock or
financial records.

The portal records customer contacts and deployment context, prepares protected
deployment bundles, tracks operator-attested commissioning, manages the signed
active/suspended policy, and organizes support cases. It does not provision hosts,
configure DNS/TLS, install software on a customer workstation, remotely control a
physical device, poll infrastructure health, collect live uptime, or complete
backups. Those are explicit operator responsibilities.

Recommended starting configurations use the existing service presets:

| Business | Starting preset | Review before commissioning |
| --- | --- | --- |
| Pharmacy | Registration, pharmacy/dispensing, stock/purchasing, billing | Catalogue, stock, permitted supply workflows, prices and cashier controls |
| Clinic | Registration, outpatient consultation, appointments/queues, billing, management | Actual clinic services; add pharmacy, laboratory or imaging only when operated and reviewed |
| Hospital | All currently available service modules | Disable services the facility does not provide; independently accept ward, diagnostic and specialty workflows |
| Custom | Registration, then explicitly selected modules | Include each selected module's dependencies |

These are configuration recommendations, not commercial packages or evidence that
every hospital workflow is production-ready. This release sets no prices,
contract terms, service-level commitments or regulatory assurances.

## Platform owner and tenant administrator

| Responsibility | Platform owner | Tenant administrator |
| --- | --- | --- |
| Independent customer register, protected bundle, policy and retirement | Active superuser on the dedicated owner console | No registry access |
| Contacts, operator checklist, support case ownership and history | Maintains owner-side operational records | Provides verified information through the agreed support process |
| Tenant branding, enabled services, facilities, staff and ordinary workflow setup | Uses an authorized temporary support session when needed | Configures within their tenant's existing permission boundaries |
| Tenant accounts, passwords and MFA | Does not obtain permanent staff authority through a support case | Creates/reviews staff access and manages their own credentials |
| Review and revoke temporary support | Tracks the reason for access | Can revoke a support session from the tenant's setup screens |
| Hosting, updates, backups and restoration | Designated infrastructure operator performs and verifies them | Agrees the operating process and validates business recovery |

The `admin` role by itself does not authorize the owner portal. The deployment
must be the owner control plane, `TENANT_KEY` must be empty, and the user must be an
active superuser. A tenant administrator does not gain this authority by managing
their own facility.

## Reading status correctly

- **Commissioning readiness** is an operator's recorded checklist. It is an
  attestation about work completed outside the portal, not an automated test or a
  condition that itself starts infrastructure.
- **Last authenticated heartbeat** is the most recent valid signed request from
  the registered tenant to the owner policy endpoint. The first heartbeat can
  activate a provisioning tenant. A suspended or retired tenant can still contact
  this endpoint without becoming active.
- **Live uptime** is not measured. A recent heartbeat does not prove that every
  page, worker, database, backup, device or third-party integration is healthy.
  A stale timestamp is an investigation prompt, not proof of an outage.

Search the registry by business name, hostname, contact name/email or deployment
reference and filter by lifecycle state. **Needs attention** excludes retired
records and includes tenants with no authenticated contact in the last ten
minutes, any unverified commissioning step, or unresolved support cases. Summary
counts cover the whole registry even when the visible list is filtered. The
support queue at `/accounts/tenants/support/` defaults to unresolved cases; use
status, priority, **Assigned to me**, business or case-title search and a tenant
filter to focus the work.

The policy gate fails closed when owner policy is invalid or unavailable. It has
a five-second cache and a three-second retrieval socket timeout. Queued tasks
retry; work already executing is not forcibly stopped. Owner-console availability
is therefore a tenant dependency. Arrange separate operational monitoring and
recovery procedures before committing to an availability target.

## Fresh owner-console workspace

1. Choose the reviewed repository revision and a dedicated owner host/workspace.
   Use Python 3.11 or 3.12, a fresh virtual environment and a separate PostgreSQL
   database. Do not point commands at an existing tenant database or reuse a
   customer's working directory. Keep patient data out of the owner instance.
2. Install the reviewed dependencies and a production application server:

   ```sh
   python -m venv .venv
   . .venv/bin/activate
   python -m pip install -r requirements-tenant.txt
   ```

3. Create a private `.env` in this dedicated checkout from `.env.example`. Supply
   a new strong `DJANGO_SECRET_KEY`, the dedicated owner `DATABASE_URL`, explicit
   `DJANGO_ALLOWED_HOSTS`, and the matching HTTPS
   `DJANGO_CSRF_TRUSTED_ORIGINS`. Set:

   ```text
   DJANGO_SETTINGS_MODULE=config.settings.prod
   DJANGO_DEBUG=0
   OWNER_CONTROL_PLANE=1
   TENANT_KEY=
   TENANT_PUBLIC_ORIGIN=https://owner.example.org
   REQUIRE_ADMIN_MFA=1
   DJANGO_SECURE_SSL_REDIRECT=1
   ```

   Replace the example hostname. Configure dedicated owner Redis URLs if owner
   background work is used. Restrict the workspace and `.env` permissions; never
   commit credentials. The owner's secret encrypts registered tenant secrets, so
   preserve it securely with owner-database recovery material. Key rotation needs
   a reviewed migration, not an arbitrary environment edit.
4. Export `DJANGO_SETTINGS_MODULE=config.settings.prod` in the command shell and
   the web/worker process manager. A value in `.env` alone is not sufficient to
   select settings before Django starts. Run:

   ```sh
   export DJANGO_SETTINGS_MODULE=config.settings.prod
   python manage.py check --deploy
   python manage.py migrate --noinput
   python manage.py collectstatic --noinput
   python manage.py createsuperuser
   ```

5. Serve `config.wsgi:application` behind a trusted HTTPS reverse proxy and process
   supervision. `runserver` is for development. Only enable
   `DJANGO_USE_X_FORWARDED_PROTO=1` when that proxy strips untrusted forwarded
   headers and replaces them correctly. Restrict direct application/database
   access. Verify DNS and valid TLS for the owner hostname.
6. Sign in, enroll the owner in MFA and open `/accounts/tenants/`. Confirm a normal
   tenant/staff account cannot open it. Create separate named owner operators
   only through your approved privileged-account process.

## Register and commission a tenant

1. Verify the business and primary administrative contact. Register a unique
   HTTPS origin, unused private application port, bootstrap administrator
   username, service preset and explicit service selection. The owner hostname
   cannot be a tenant hostname. Record deployment metadata as operational context,
   not credentials, patient details or a promise that the infrastructure exists.
2. Review setup before downloading the first bundle. Setup editing is limited to
   the pre-bundle phase; a generated bundle is a deployment artifact that may
   already be in use. Do not attempt to change a live tenant's identity, hostname,
   port or bootstrap configuration by editing its registry row. Use a separately
   planned infrastructure/application change instead.
3. Build the reviewed image on the intended deployment host or deliver it using
   your approved image-distribution process:

   ```sh
   docker build -f deploy/tenants/Dockerfile -t clinic-hms:tenant-v1 .
   ```

4. Download the protected bundle. It contains database, application, bootstrap
   administrator and support credentials. Transfer it only to an authorized
   operator through an approved private channel. Extract each customer's bundle
   into a new, separate protected directory; on a Unix host use directory mode
   `700` and `.env` mode `600`. Do not attach bundles or secrets to support cases.
   Re-downloading preserves identity and keys; it does not rotate credentials.
   The bundle also includes `SETUP_CHECKLIST.txt`, with this business's origin,
   initial service names and administrator setup/staff links. It is a handoff
   guide, not evidence that those steps ran.
5. From that tenant's directory, review the resolved Compose model privately and
   start the tenant:

   ```sh
   docker compose --env-file .env -f compose.yaml config --quiet
   docker compose up -d
   docker compose ps
   ```

   Each generated project has tenant-specific network and database/media/Redis
   volumes. PostgreSQL and Redis have no published ports; the application binds
   only to the registered loopback port. Do not override those boundaries with
   shared volumes, shared networks or public database/Redis ports. Avoid printing
   the full resolved Compose configuration because it contains credentials.
6. Configure a trusted TLS proxy to route only the registered tenant hostname to
   its loopback port. Check that private media is not publicly served and that
   upstream logs redact bearer URLs. Verify the tenant can reach the owner's HTTPS
   origin. Deployment itself and the first valid signed heartbeat are separate
   steps: registration and bundle download do not start or activate a host.
7. On the tenant's workstation, open only that tenant's HTTPS URL in a separate
   browser profile/workspace. Sign in with its protected bootstrap credentials,
   change the bootstrap password and enroll MFA. Do not reuse the owner's browser
   session or treat workstation setup as remote-control authorization. The
   bootstrap command initializes a fresh tenant once and does not overwrite
   existing users or configuration on a restart.
8. The tenant administrator reviews **Choose services and branding**, facilities,
   staff roles and scope, prices and catalogues, and applicable workflow setup.
   Create ordinary named staff accounts for daily work. Use synthetic records for
   acceptance; do not use a production database as a test fixture.
9. Verify database/media backups and a restore into an isolated recovery workspace
   with matching keys; verify worker and Redis separation. Record the operator
   commissioning checklist only after its supporting work has actually been
   done. A checked box does not replace backup evidence, security testing or
   clinical acceptance.

The seven portal checks are isolated application/storage, HTTPS/private network,
backup/restore rehearsal, administrator/MFA, services/branding, staff/workstations,
and tenant workflow acceptance. For each check, record either **Needs review** or
**Operator verified** with an evidence reference or a reason for further review.
Evidence is required in both states. Record who checked it and when, without
credentials or patient details. Changing a check records its operator and time;
completing all seven does not activate the tenant or probe its host.

## Support, suspension and retirement

Keep support cases in the owner's tenant record with a concise description,
priority, named owner assignee, current state and resolution. Record meaningful
updates in the case activity. Assignment and case state do not grant tenant
permissions or launch a support session. Avoid clinical content, passwords,
signing keys, bearer tickets and protected bundles in free-text fields.

Cases use **Open**, **In progress**, **Waiting on tenant** and **Resolved** states
with normal, high or urgent priority. Starting work requires an active permanent
platform-owner assignee, closing requires a resolution, and every update requires
a short note. Reopen a resolved case before moving it back to in-progress work.
Reload a stale form before changing the record; an exact submission retry does
not duplicate the original change or activity.

An authorized owner may start audited support with a reason for a deployed
tenant. The launch ticket is bound to that tenant, valid for 30 seconds and
single-use. It creates a 30-minute tenant browser session with an unusable
password. This is privileged temporary support within the selected tenant;
case assignment is not a finer-grained clinical-access restriction. Support
accounts cannot obtain or use JWTs, change permanent credentials, enroll MFA,
open system administration or access the owner registry. Tenant administrators
can review and revoke support sessions; expiry/revocation ends access on the next
request. Support is available while suspended for authorized diagnosis.

Before suspension, agree the operational impact and record a reason. Suspension
blocks ordinary browser/API entry and pauses queued work at the policy gate; it
does not shut down containers, erase data or interrupt an already executing
transaction. Resume only after the cause is resolved and the owner has reviewed
the current record revision.

Retirement is terminal and requires suspension first. Record a clear reason and
the agreed external shutdown/retention plan. A retired record remains in the
registry with its activity; the portal does not delete customer records, volumes
or backups. Retirement does not provision a replacement, physically power down a
device or execute data erasure. Preserve legal/operational retention and recovery
decisions outside the portal. Do not promise that suspending or retiring the
record immediately terminates a support session already accepted by a tenant;
revoke that session and verify closure separately.

## Upgrade and verification

Back up owner and tenant databases, media and corresponding keys before upgrading.
Test a restored staging copy first, stop writes for the planned change window,
and deploy the reviewed code/dependencies. Accounts migration `0013` extends the
owner register for this portal; run all migrations rather than faking a migration
or selectively skipping dependencies. Existing deployments are not automatically
converted into owner consoles, and migrations do not provision a customer host.

Migration `0013_tenant_admin_portal` conservatively locks initial configuration on
pre-upgrade tenant rows without a recorded download by setting an explicit
`legacy_configuration_locked` flag. The earlier release did not track downloads,
so a historical bundle might already exist. The flag is a safety lock, **not
proof that a bundle was downloaded**: it leaves the unknown download timestamp
empty and does not create a download activity or establish deployment readiness.
An existing recorded download timestamp is preserved. Registrations made after
the upgrade have no legacy lock and remain editable until their first bundle or
authenticated contact.

In an authorized build/test environment with reviewed dependencies installed:

```sh
python -m pip check
python manage.py check --settings=config.settings.test
python manage.py makemigrations --check --dry-run
python manage.py spectacular --validate --fail-on-warn --file /tmp/schema.yaml
python -m pytest -q tests/test_tenant_control.py tests/test_tenant_portal.py
python -m pytest -q
python manage.py migrate --noinput
python manage.py collectstatic --noinput
```

Use the production settings module for deployment checks/migrations and a
disposable database for tests. CI's Python 3.11/3.12 and SQLite/PostgreSQL matrix
is configured in `.github/workflows/tests.yml`; inspect results for the exact
release commit. A static syntax check is not a test pass. If dependencies cannot
be installed in a restricted workspace, leave execution marked blocked and run
the same checks in the authorized CI environment.

### Manual acceptance still required

- Review owner login/MFA, search/filter/attention results, empty results and
  multi-page navigation at desktop, tablet and narrow mobile sizes
- Exercise form errors, stale revisions, double submits, interrupted downloads,
  Back/Forward and return navigation without leaking secrets
- Confirm pre-bundle edits and post-bundle locking, operator checklist changes,
  support ownership/state/resolution history and tenant-specific case boundaries
- Use separate real instances to verify signed activation, suspension/resume,
  support launch/expiry/revocation, and terminal retirement without record deletion
- Commission actual DNS/TLS, isolated networks/volumes/keys/Redis, image startup,
  backups/restoration, monitoring and recovery using synthetic data first
- Complete keyboard/screen-reader and staff/clinical workflow acceptance;
  automated tests and historical browser reviews do not establish this release's
  manual acceptance or real infrastructure readiness

The current implementation is an owner administration workflow. Host deployment,
physical workstation setup, provider commissioning, real uptime monitoring and
clinical go-live acceptance remain separate, uncompleted operational work until
their responsible operators produce evidence.
