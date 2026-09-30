# Service selection and clean role workspaces

30 September 2026. Requested extension: standalone pharmacy/clinic/hospital setup, service-specific dashboards, local administration, branding and owner support.

## Available now

- Administrator setup at `/accounts/setup/` with pharmacy, clinic, hospital and custom presets. Presets are editable starting points, not assumptions about which services a facility offers.
- Explicit choices for registration, outpatient care, appointments, pharmacy, inventory, billing, laboratory, imaging, wards, maternity, theatre, vaccination, rehabilitation, clinical programmes, engagement, workforce and management.
- Supporting-service validation: for example, on-site dispensing requires registration, stock and billing. A facility can run consultations and prescribe for outside supply without enabling its own dispensing service.
- Business display name, tagline and contact phone. The workspace shows its configured business name. Invoice/receipt branding uses the actual invoice's facility, including when a system owner assists another site. Logo uploads and full print-theme controls remain future work.
- Menus and home cards are generated from role and service availability. Shared server-rendered link guards also remove unavailable links from existing page templates; hiding does not replace authorization.
- Disabled service routes are rejected on browser and JWT paths. Diagnostic order/result lists and writes enforce lab/imaging selection; disabling a service retains records rather than deleting history. Existing patient-chart tabs filter disabled services.
- Administrator staff recruitment and role/access changes at `/accounts/staff/`. The form cannot grant platform superuser/staff privileges. Writable users remain facility scoped, passwords use configured validators, self-demotion is blocked, and at least one active site administrator must remain. Available roles follow selected services.
- System-owner control dashboard at `/accounts/control/` to review sites, configure them and enter a selected site's workspace. Support selections and staff/configuration changes are audited.
- Default `REQUIRE_SERVICE_SETUP=1`: site administrators must complete first-run configuration; ordinary staff cannot use an unconfigured site. The owner without a selected site starts at the owner control dashboard. Tests explicitly isolate legacy fixtures from this gate and separately test enforcement.

## Administrator flow

1. Complete authenticator enrollment when required.
2. Select the site; the platform owner can create/manage the initial facility and appoint its administrator using protected system administration.
3. Open **Choose services and branding**. Select the closest preset and review each checkbox. Supporting requirements appear as validation errors rather than silently enabling extra modules.
4. Save the configuration. Revision checks reject stale concurrent edits.
5. Recruit staff and assign the roles appropriate for the selected services. Existing duty/credential/onboarding workflows remain available when enabled.
6. Sign in using representative staff accounts and review the actual task flow. Enabling a module does not approve medicine classifications, clinical ranges, provider credentials or governance policies.

A pharmacy-only workspace defaults to registration, dispensing, inventory and billing. It does not display maternity, ward, laboratory, imaging, theatre or clinical-programme workspaces. Management and workforce services can be added if needed. A clinic can add scans and maternity independently. Historical records remain stored when services are disabled; an authorized administrator can re-enable the service for appropriate work.

## Independent tenant boundary — still unfinished

The current deployment has facility-scoped patients/transactions and explicit branch grants, but catalogues, supplier/master configuration and some pricing settings are still shared. Therefore independent tenant onboarding is **not enabled or claimed safe** in this release. The owner dashboard manages sites within the current deployment, not independently isolated SaaS customers.

Required next work before hosting unrelated tenants in one deployment:

1. Introduce organization ownership for facilities, staff memberships and every shared catalogue/configuration record; migrate existing data with a reviewed ownership mapping.
2. Enforce organization boundaries on reads, writes, relation selections, tasks, reports, exports, asynchronous jobs and owner support access. Branch grants must remain within an organization.
3. Add owner-only organization provisioning/suspension, auditable support entry and scoped tenant administrator controls.
4. Run two-organization attack/regression tests, including guessed IDs, conflicting product codes, exports, JWTs, background work and branding isolation.
5. Only then enable independent tenant onboarding and claim multi-tenant isolation.

Fine-grained per-action delegation, atomic reassignment/offboarding and full tenant branding/print templates remain in the tracker. Automated checks follow each visible home link for every defined staff role in a fully enabled hospital workspace, alongside pharmacy-only regressions. Role-filtered navigation is not a claim that every existing action-specific approval control has completed a separate usability audit.
