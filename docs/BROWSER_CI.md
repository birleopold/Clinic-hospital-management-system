# Disposable browser CI

`.github/workflows/browser.yml` runs `python scripts/browser_ci_review.py` on a
standard Ubuntu 22.04 GitHub-hosted VM with Python 3.12, Node 22 and Playwright
1.63.0. The browser launch explicitly sets `chromiumSandbox: true`. A sandbox
failure is a genuine failed gate: do not disable the sandbox, modify host security,
or add certificate/CSP bypasses to make it pass.

## What this gate covers

- A fresh owner control-plane database and an independent clinic database, each
  with separate process, signing key, cookie name, private media and static root
- Native password login and required TOTP enrollment for the owner, clinic
  administrator, clinician, pharmacy and manager accounts; the browser checks
  the actual same-origin `Origin` and enrollment `Referrer-Policy` headers
- `shell_layout_browser.cjs`: uncached authenticated first visit, a real menu
  link, reload/layout equivalence, Back, mobile menu open/close, and no-JavaScript
  first visit; selected owner and actual role pages at 1440, 768 and 390 pixels
- Owner registry filters and detail navigation, contact/configuration changes,
  operator readiness evidence, support case creation/resolution and queue
- Authenticated protected ZIP download, immediate deletion, and configuration
  locking after download without asserting deployment occurred
- Canceled suspend/retire confirmations send no POST; accepted retirement of a
  synthetic record retains its registry/history, verified again in the database
- Anonymous owner-route denial and clinic-role denial of the owner registry

This is computed loaded-layout verification. It does not measure transient
first-paint timing. It is not a replacement for Django/PostgreSQL tests, a live
TLS test, tenant infrastructure provisioning or activation, cross-tenant runtime
policy/support handoff testing, a manual accessibility audit, or clinical/provider
commissioning.

## Isolation and privacy

The harness always creates a private temporary root; it accepts no existing DB
or target URL option. It imports base settings into temporary settings with
physical SQLite/media separation and never edits production settings. The two
WSGI listeners bind only `127.0.0.1` using independently assigned ephemeral ports.
HTTP is intentional for these disposable local UI fixtures; HTTPS-only production
settings and registry validation are unchanged.

Registry origins are synthetic HTTPS `.example.test` metadata and are never
visited or deployed. Seeded last-contact timestamps/lifecycle states are explicitly
labeled synthetic in operator notes. SMS/payment backends are no-op, email stays
in memory, and no tenant runtime heartbeat or external provider is configured.
The child processes receive an allowlisted environment rather than inherited
production DB URLs, provider credentials or CI tokens.

All browser contexts, including fresh/no-JS contexts made by the shared helper,
block service workers, guard HTTP requests to the two loopback origins, and block
WebSockets. The job fails if any external request is attempted. Standard
Playwright browser installation is the only browser distribution used.

CSRF middleware, ordinary password hashing and MFA remain active. OTP enrollment
uses the actual rendered form and a real in-memory TOTP value; it never inserts a
pre-verified device or bypass session. There is no certificate generation, TLS
warning acceptance, CSP bypass, external login, repository secret or persistent
access setup.

The workflow uploads no artifacts. Passwords, MFA QR/key material, cookies,
storage state, traces, browser profiles, databases and protected bundles are never
published. Downloads are inspected only for ZIP magic, immediately deleted and
also subject to context/temporary-root cleanup. Browser failures print their stage
and a redacted first error line, not Playwright call logs or DOM snapshots.

## Run and verification

On an authorized disposable host with normal Chromium sandbox support:

```sh
python -m pip install -r requirements-core.txt
npm --prefix scripts/browser-ci install --ignore-scripts --no-audit --no-fund
scripts/browser-ci/node_modules/.bin/playwright install --with-deps chromium
python -m unittest discover -s scripts/browser-ci -p 'test_*.py'
python scripts/browser_ci_review.py
```

The Playwright dependency is pinned exactly. An npm lock could not be generated
in the implementation workspace because the offline cache contained no registry
metadata; no network restriction was bypassed. `npm install` on the authorized CI
runner resolves the pinned dependency normally. A future dependency refresh should
commit an npm-generated lockfile and switch this job to `npm ci` when an authorized
registry connection is available.

Static checks can run without Django, Playwright or a browser:

```sh
python -m unittest discover -s scripts/browser-ci -p 'test_*.py'
python -m py_compile scripts/browser_ci_review.py
node --check scripts/browser_ci_review.cjs
node --check scripts/shell_layout_browser.cjs
```

Local syntax/safety checks alone do not prove browser success. The GitHub job must
pass for the exact reviewed commit before this gate is called verified. The
implementation workspace lacks Django/pytest and denies Chromium socket creation;
these restrictions are not worked around by this harness.

## Primary tooling references

- [Playwright CI installation](https://playwright.dev/docs/ci)
- [Playwright supported operating systems and Node versions](https://playwright.dev/docs/intro#system-requirements)
- [Explicit Chromium sandbox option](https://playwright.dev/docs/api/class-browsertype#browser-type-launch-option-chromium-sandbox)
- [Playwright 1.63.0 release](https://github.com/microsoft/playwright/releases/tag/v1.63.0)
- [Official setup-node](https://github.com/actions/setup-node)
- [Official setup-python](https://github.com/actions/setup-python)
- [Official checkout and credential persistence](https://github.com/actions/checkout)
