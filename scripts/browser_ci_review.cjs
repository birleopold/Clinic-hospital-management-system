// Called only by browser_ci_review.py with its private, synthetic fixture.
// No storage state, trace, QR image, password, token, or download is published.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const {chromium} = require('./browser-ci/node_modules/playwright');
const {assertShellLayout, verifyShellNavigation} = require('./shell_layout_browser.cjs');

let stage = 'load disposable fixture';
const secrets = [];
const networkViolations = [];
const browserErrors = [];
function check(condition, message) { assert(condition, message); }
function origin(value) {
  const parsed = new URL(value);
  check(parsed.protocol === 'http:' && parsed.hostname === '127.0.0.1' && parsed.port &&
    parsed.pathname === '/' && !parsed.username && !parsed.password && !parsed.search && !parsed.hash,
  'Only explicit HTTP loopback origins are allowed');
  return parsed.origin;
}
function totp(base32) {
  let bits = 0, value = 0;
  const bytes = [];
  for (const character of base32.replace(/=+$/, '').toUpperCase()) {
    const digit = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'.indexOf(character);
    check(digit >= 0, 'Invalid synthetic enrollment encoding');
    value = (value << 5) | digit;
    bits += 5;
    if (bits >= 8) { bits -= 8; bytes.push((value >>> bits) & 255); }
  }
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const digest = crypto.createHmac('sha1', Buffer.from(bytes)).update(counter).digest();
  return String((digest.readUInt32BE(digest[19] & 15) & 0x7fffffff) % 1000000).padStart(6, '0');
}
async function submit(page, button) {
  await Promise.all([page.waitForNavigation({waitUntil: 'load'}), button.click()]);
}
async function loginAndEnroll(page, baseURL, username, password) {
  stage = `${username}: native login and MFA enrollment`;
  assert.equal((await page.goto(baseURL + '/accounts/login/')).status(), 200);
  await page.locator('[name=username]').fill(username);
  await page.locator('[name=password]').fill(password);
  await submit(page, page.locator('button[type=submit]'));
  assert.equal(new URL(page.url()).pathname, '/accounts/mfa/enroll/', 'MFA is required before workspace access');
  const enrollment = await page.reload();
  assert.equal(enrollment.headers()['referrer-policy'], 'same-origin', 'Native MFA form preserves same-origin CSRF');
  await page.locator('#id_password').fill(password);
  const passwordRequest = page.waitForRequest(request => request.method() === 'POST' &&
    request.url() === baseURL + '/accounts/mfa/enroll/');
  await submit(page, page.getByRole('button', {name: 'Verify and continue', exact: true}));
  assert.equal((await (await passwordRequest).allHeaders()).origin, baseURL, 'Real browser password form has same-origin Origin');
  const key = (await page.locator('details p').textContent()).trim();
  secrets.push(key);
  check(/^[A-Z2-7]+=*$/.test(key), 'MFA enrollment displays a valid synthetic key');
  // Keep the enrollment key and derived code solely in memory; never photograph it.
  const remaining = 30000 - Date.now() % 30000;
  if (remaining < 1500) await new Promise(resolve => setTimeout(resolve, remaining + 100));
  const code = totp(key);
  secrets.push(code);
  await page.locator('#id_token').fill(code);
  const tokenRequest = page.waitForRequest(request => request.method() === 'POST' &&
    request.url() === baseURL + '/accounts/mfa/enroll/');
  await submit(page, page.getByRole('button', {name: 'Verify and continue', exact: true}));
  assert.equal((await (await tokenRequest).allHeaders()).origin, baseURL, 'Real browser token form has same-origin Origin');
  check(!new URL(page.url()).pathname.startsWith('/accounts/mfa/'), 'Enrollment must reach the authenticated workspace');
  await assertShellLayout(page, username + ' enrolled workspace');
}
async function pageMatrix(page, baseURL, paths, label) {
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({width, height: 900});
    for (const path of paths) {
      stage = `${label}: ${path} at ${width}px`;
      const response = await page.goto(baseURL + path);
      assert.equal(response.status(), 200, stage + ' HTTP status');
      assert.equal(new URL(page.url()).pathname, path.split('?')[0], stage + ' must not redirect');
      await assertShellLayout(page, stage);
    }
  }
  await page.setViewportSize({width: 1440, height: 900});
}
async function verifyOwnerLanding(page, baseURL) {
  const response = await page.goto(baseURL + '/accounts/control/');
  assert.equal(response.status(), 200, 'Owner control redirect reaches a successful page');
  assert.equal(new URL(page.url()).pathname, '/accounts/tenants/', 'Owner control intentionally redirects to the tenant portal');
}
async function dismissLifecycle(page, name, expectedState) {
  const before = page.url();
  let posted = false;
  const listener = request => { if (request.method() === 'POST') posted = true; };
  page.on('request', listener);
  try {
    await Promise.all([
      page.waitForEvent('dialog').then(async dialog => {
        assert.equal(dialog.type(), 'confirm');
        await dialog.dismiss();
      }),
      page.getByRole('button', {name, exact: true}).click(),
    ]);
    assert.equal(posted, false, 'Cancel must not send a lifecycle POST');
    assert.equal(page.url(), before, 'Cancel preserves the current page');
    assert.equal(await page.locator('.portal-hero .portal-state-' + expectedState).count(), 1);
    assert.equal(await page.locator('#lifecycle_reason').inputValue(), 'Synthetic cancellation proof');
  } finally {
    page.off('request', listener);
  }
}
async function ownerReview(browser, context, page, fixture) {
  const baseURL = fixture.origin;
  const active = `/accounts/tenants/${fixture.tenants.active}/workspace/`;
  const retirement = `/accounts/tenants/${fixture.tenants.retirement}/workspace/`;
  stage = 'owner: fresh first-load, actual click, reload, Back, mobile menu and no JavaScript';
  await verifyShellNavigation(browser, {baseURL, storageState: await context.storageState(),
    firstPath: '/accounts/tenants/', nextPath: '/accounts/tenants/support/'});
  stage = 'owner: intentional control dashboard redirect';
  await verifyOwnerLanding(page, baseURL);
  await assertShellLayout(page, 'owner control redirect');
  await pageMatrix(page, baseURL, ['/accounts/tenants/', active,
    retirement, '/accounts/tenants/support/', '/accounts/approvals/'], 'owner');

  stage = 'owner: tenant search and lifecycle filters';
  await page.goto(baseURL + '/accounts/tenants/');
  await page.locator('#tenant-query').fill('Synthetic CI Active');
  await page.locator('#tenant-state').selectOption('active');
  await submit(page, page.getByRole('button', {name: 'Apply filters', exact: true}));
  assert.equal(await page.locator('.portal-tenant-card').count(), 1);
  await page.getByRole('link', {name: 'Synthetic CI Active', exact: true}).click();
  assert.equal(new URL(page.url()).pathname, active);
  await assertShellLayout(page, 'filtered tenant real detail link');
  check((await page.locator('#overview').innerText()).includes('Contact records show authenticated policy requests'),
    'Contact wording must not claim uptime or production certification');

  stage = 'owner: contact and synthetic operator notes';
  await page.getByText('Edit business metadata', {exact: true}).click();
  await page.locator('#metadata_contact_name').fill('Synthetic operator');
  await page.locator('#metadata_contact_email').fill('synthetic-operator@example.test');
  await page.locator('#metadata_deployment_label').fill('SYNTHETIC CI ONLY');
  await page.locator('#metadata_operator_notes').fill('SYNTHETIC CI: last-contact and lifecycle seeded; no deployed host or TLS verification.');
  await submit(page, page.getByRole('button', {name: 'Save business details', exact: true}));
  assert.equal(await page.locator('#metadata_contact_name').inputValue(), 'Synthetic operator');

  stage = 'owner: readiness evidence';
  const checkDetails = page.locator('details.portal-checkpoint').filter({has: page.locator('#check_services_status')});
  await checkDetails.locator('summary').click();
  await page.locator('#check_services_status').selectOption('verified');
  await page.locator('#check_services_evidence').fill('SYNTHETIC CI ONLY: form persistence checked; no production acceptance asserted.');
  await submit(page, checkDetails.getByRole('button', {name: 'Save readiness check', exact: true}));
  assert.equal(await page.locator('.portal-check-verified').count(), 1);

  stage = 'owner: create and resolve support case';
  await page.getByText('Open a support case', {exact: true}).click();
  await page.locator('#case_title').fill('Synthetic CI support case');
  await page.locator('#case_category').selectOption('configuration');
  await page.locator('#case_priority').selectOption('normal');
  await page.locator('#case_detail').fill('Synthetic browser form exercise with no patient information or credentials.');
  await submit(page, page.getByRole('button', {name: 'Create support case', exact: true}));
  const casePath = new URL(page.url()).pathname;
  check(/^\/accounts\/tenants\/\d+\/cases\/\d+\/$/.test(casePath), 'Case creation reaches its own detail page');
  await page.locator('#case_update_status').selectOption('resolved');
  await page.locator('#case_update_resolution').fill('Synthetic form round-trip verified.');
  await page.locator('#case_update_note').fill('CI case only; no real service issue.');
  await submit(page, page.getByRole('button', {name: 'Save case update', exact: true}));
  assert.equal(await page.locator('#case_update_status').inputValue(), 'resolved');
  await pageMatrix(page, baseURL, [casePath, '/accounts/tenants/support/?status=resolved'], 'owner case');
  await page.goto(baseURL + '/accounts/tenants/support/?status=resolved');
  assert.equal(await page.getByRole('link', {name: 'Synthetic CI support case', exact: true}).count(), 1);

  stage = 'owner: register and configure undeployed synthetic business';
  await page.goto(baseURL + '/accounts/tenants/');
  await page.locator('#register-tenant > summary').click();
  await page.locator('#register_name').fill('Synthetic CI Registered');
  await page.locator('#register_origin').fill('https://synthetic-registered.example.test');
  await page.locator('#register_bind_port').fill('18200');
  await page.locator('#register_admin_username').fill('synthetic-admin');
  await submit(page, page.getByRole('button', {name: 'Register tenant', exact: true}));
  assert.equal(await page.locator('#tenant-title').innerText(), 'Synthetic CI Registered');
  await page.getByText('Edit deployment configuration', {exact: true}).click();
  await page.locator('#configuration_bind_port').fill('18201');
  await submit(page, page.getByRole('button', {name: 'Save deployment configuration', exact: true}));
  assert.equal(await page.locator('#configuration_bind_port').inputValue(), '18201');

  stage = 'owner: protected download remains private and locks initial configuration';
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', {name: 'Download protected deployment bundle', exact: true}).click();
  const download = await downloadEvent;
  assert.equal(await download.failure(), null, 'Protected synthetic bundle download succeeds');
  check(/^tenant-[a-f0-9-]+\.zip$/.test(download.suggestedFilename()), 'Protected download is the expected ZIP');
  // Inspect only the ZIP magic; never extract, print, save-as, or upload contents.
  const downloadedPath = await download.path();
  const fd = fs.openSync(downloadedPath, 'r');
  try {
    const magic = Buffer.alloc(4);
    assert.equal(fs.readSync(fd, magic, 0, 4, 0), 4);
    check(magic.equals(Buffer.from([0x50, 0x4b, 0x03, 0x04])), 'Bundle has ZIP signature');
  } finally { fs.closeSync(fd); await download.delete(); }
  await page.reload();
  assert.equal(await page.getByText('Edit deployment configuration', {exact: true}).count(), 0);
  assert.equal(await page.locator('.portal-hero .portal-state-provisioning').count(), 1);
  check((await page.locator('#overview').innerText()).includes('Not received yet'), 'Downloading never invents contact');

  stage = 'owner: cancel suspension and retirement without a request';
  await page.goto(baseURL + active);
  await page.locator('#lifecycle_reason').fill('Synthetic cancellation proof');
  await dismissLifecycle(page, 'Suspend tenant', 'active');
  await page.goto(baseURL + retirement);
  await page.locator('#lifecycle_reason').fill('Synthetic cancellation proof');
  await dismissLifecycle(page, 'Retire tenant', 'suspended');

  stage = 'owner: synthetic retirement retains registry and history';
  await page.locator('#lifecycle_reason').fill('Synthetic CI retained-record retirement exercise only.');
  const confirmed = page.waitForEvent('dialog').then(async dialog => {
    check(dialog.message().includes('retained'), 'Retirement confirmation explains retained records');
    await dialog.accept();
  });
  await submit(page, page.getByRole('button', {name: 'Retire tenant', exact: true}));
  await confirmed;
  assert.equal(await page.locator('.portal-hero .portal-state-retired').count(), 1);
  assert.equal(await page.getByRole('button', {name: 'Resume tenant', exact: true}).count(), 0);
  assert.equal(await page.getByRole('button', {name: 'Download protected deployment bundle', exact: true}).count(), 0);
  check((await page.locator('#activity').innerText()).includes('Lifecycle policy changed'), 'Retirement history stays visible');
  await page.goto(baseURL + '/accounts/tenants/?state=retired');
  assert.equal(await page.getByRole('link', {name: 'Synthetic CI Retirement', exact: true}).count(), 1);
  console.log('PASS: owner portal filters/detail/contact/configuration/readiness/support case/download and retained-record retirement; lifecycle Cancel sends no POST.');
}

(async () => {
  const fixture = JSON.parse(fs.readFileSync(process.env.BROWSER_CI_FIXTURE, 'utf8'));
  secrets.push(fixture.password);
  fixture.owner.origin = origin(fixture.owner.origin);
  fixture.clinic.origin = origin(fixture.clinic.origin);
  check(fixture.owner.origin !== fixture.clinic.origin, 'Independent app listeners are required');
  const allowedOrigins = new Set([fixture.owner.origin, fixture.clinic.origin]);
  stage = 'launch Chromium with its sandbox enabled';
  // Never add fallback launch flags or weaken host security if this fails.
  const browser = await chromium.launch({chromiumSandbox: true, headless: true});
  try {
    async function newContext(options = {}) {
      const context = await browser.newContext({...options, serviceWorkers: 'block'});
      context.setDefaultTimeout(15000);
      context.setDefaultNavigationTimeout(20000);
      await context.route('**/*', async route => {
        const url = new URL(route.request().url());
        if (allowedOrigins.has(url.origin) && url.protocol === 'http:') return route.continue();
        networkViolations.push('Non-loopback request blocked');
        return route.abort('blockedbyclient');
      });
      // No app under test needs a WebSocket. Prevent a future fixture/page change
      // from bypassing the HTTP request guard through one.
      await context.routeWebSocket(/.*/, socket => {
        networkViolations.push('Unexpected WebSocket blocked');
        socket.close();
      });
      context.on('page', page => {
        page.on('pageerror', () => browserErrors.push('Uncaught browser error'));
        page.on('response', response => {
          if (response.status() >= 500) browserErrors.push('Application returned HTTP ' + response.status());
        });
      });
      return context;
    }
    // The shared helper creates fresh/no-JS contexts through this same guard.
    const guardedBrowser = {newContext};
    const anonymous = await newContext();
    try {
      stage = 'anonymous owner portal and protected bundle denial';
      const page = await anonymous.newPage();
      for (const path of ['/accounts/tenants/', `/accounts/tenants/${fixture.owner.tenants.active}/`]) {
        await page.goto(fixture.owner.origin + path);
        assert.equal(new URL(page.url()).pathname, '/accounts/login/', 'Protected owner route requires authentication');
      }
    } finally { await anonymous.close(); }

    const ownerContext = await newContext();
    try {
      const page = await ownerContext.newPage();
      await loginAndEnroll(page, fixture.owner.origin, fixture.owner.admin, fixture.password);
      await ownerReview(guardedBrowser, ownerContext, page, fixture.owner);
    } finally { await ownerContext.close(); }

    const roles = [{role: 'admin', username: fixture.clinic.admin}, ...fixture.clinic.accounts];
    const paths = {
      admin: ['/accounts/setup/', '/accounts/staff/', '/suite/management/'],
      clinician: ['/suite/pregnancies/', '/suite/vaccinations/'],
      pharmacy: ['/pharmacy/baskets/', '/suite/stock/'],
      manager: ['/suite/management/', '/suite/finance/'],
    };
    for (const account of roles) {
      const context = await newContext();
      try {
        const page = await context.newPage();
        await loginAndEnroll(page, fixture.clinic.origin, account.username, fixture.password);
        stage = `clinic ${account.role}: fresh first-load/navigation/reload/Back/mobile/no-JS`;
        await verifyShellNavigation(guardedBrowser, {baseURL: fixture.clinic.origin,
          storageState: await context.storageState(), firstPath: '/suite/tasks/', nextPath: '/suite/'});
        await pageMatrix(page, fixture.clinic.origin, ['/suite/', '/suite/tasks/', ...paths[account.role]], 'clinic ' + account.role);
        stage = `clinic ${account.role}: owner registry access stays forbidden`;
        assert.equal((await page.goto(fixture.clinic.origin + '/accounts/tenants/')).status(), 403);
        console.log(`PASS: independent clinic ${account.role} MFA and shell/role pages at 1440/768/390px.`);
      } finally { await context.close(); }
    }
    stage = 'final browser/network assertions';
    assert.deepEqual(networkViolations, [], 'Browser must not attempt external traffic');
    assert.deepEqual(browserErrors, [], 'No JavaScript errors or server failures');
    console.log('PASS: sandboxed Chromium, same-origin native MFA forms, guarded loopback traffic, first navigation/reload/Back/mobile/no-JS. No TLS, live tenant activation, or provider acceptance claim.');
  } finally { await browser.close(); }
})().catch(error => {
  // Avoid Playwright call logs/DOM snapshots: they can contain entered secrets.
  let message = String(error.message || error.name).split('\n')[0];
  for (const secret of secrets.filter(Boolean)) message = message.split(secret).join('[redacted]');
  console.error(`FAIL: ${stage}: ${message}`);
  process.exitCode = 1;
});
