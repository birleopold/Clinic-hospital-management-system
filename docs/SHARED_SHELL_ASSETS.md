# First-load shell styling

The shared clinic shell is defined by one render-blocking stylesheet,
`static/css/workspace.css`, linked once in `templates/base.html` before scripts.
It contains the base components, responsive sidebar, topbar, hidden search label,
patient/chart components, and print rules. The old `legacy-shell.css` and
`suite.css` files have been removed; individual pages may add scoped components,
such as `tenant-portal.css`, through the existing `head` block.

The layout is server-rendered and does not wait for JavaScript. `shell.js` only
enhances the navigation controls and active/group labels. Navigation remains
ordinary document navigation; HTMX is used for selected in-page actions, not
whole-page/head swapping. The offline service worker remains scoped to
`/offline/` and does not intercept clinic shell assets.

## Asset generations

- Local/default/test settings use `ContentVersionedStaticFilesStorage`. Static
  URLs include a deterministic hash of their file bytes. The URL stays stable
  while the content is unchanged and changes immediately when it changes,
  including same-length updates with unchanged timestamps. Browsers can cache
  normally; users do not need to clear caches or force reloads after an update.
- Production retains WhiteNoise's `CompressedManifestStaticFilesStorage` and
  content-hashed filenames. Run `collectstatic` under production settings when
  deploying an existing checkout, and deploy the collected files and application
  from the same release. Do not copy new source files over an older collected
  directory or retain older compressed variants under current asset names.
- The tenant Docker image now explicitly collects with
  `config.settings.static_build`, which uses the same manifest backend without
  requiring production secrets or a running database during image construction.
  This management-command-only setting is not the runtime configuration; the
  application must still use `config.settings.prod` and its security checks.

## Regression checks

Run `python -m pytest tests/test_static_assets.py -q` for first-response template
coverage, deterministic local versioning, and collected manifest/compression
consistency. Existing `scripts/browser_smoke.cjs` and the disposable
`scripts/tenant_control_review.py` exercise `scripts/shell_layout_browser.cjs`.
It checks a fresh authenticated browser context, real link navigation, ordinary
reload, history back, mobile menu behavior, and a separate first visit with
JavaScript disabled. It also asserts the canonical stylesheet and computed shell
layout across the existing route/viewport audit loops.

Use only disposable synthetic accounts/instances for these browser runners.

## Evidence and remaining runtime diagnosis

The reported screenshots show current page controls and colors in both states,
but the broken state lacks the sidebar/topbar/visually-hidden layout rules and
shows navigation horizontally. This is consistent with current HTML paired with
an older stylesheet. Repository inspection found two overlapping shell CSS
files and mutable asset URLs in local/default settings; it found no deferred
style swap, theme restoration, or full-page HTMX navigation.

The exact source that supplied the user's older CSS was not observed. If a
running installation still differs after deploying this release, inspect the
actual stylesheet URL, status, response body, content encoding, and cache headers
on its first request. Compare the returned bytes to that release's source or
manifest entry and check for multiple application/static-server generations.
Do not treat a hard refresh as the fix or disable CSRF/MFA/security middleware.
