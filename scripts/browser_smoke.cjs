// npm install --no-save playwright axe-core; npx playwright install chromium
// Run against a disposable seeded instance, with a staff test account.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const base = process.env.CLINIC_TEST_URL || 'http://127.0.0.1:8000';
  assert(process.env.CLINIC_TEST_USERNAME && process.env.CLINIC_TEST_PASSWORD,
    'Set CLINIC_TEST_USERNAME and CLINIC_TEST_PASSWORD for a disposable staff account');
  const browser = await chromium.launch({ executablePath: process.env.CLINIC_CHROMIUM_PATH || undefined });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`${base}/accounts/login/`);
    await page.locator('[name=username]').fill(process.env.CLINIC_TEST_USERNAME);
    await page.locator('[name=password]').fill(process.env.CLINIC_TEST_PASSWORD);
    await Promise.all([page.waitForURL(url => !url.pathname.includes('/login')),
      page.locator('button[type=submit]').click()]);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      for (const path of ['/suite/', '/suite/results/', '/suite/insurance/prepare/',
        '/suite/stock/', '/suite/medication-round/']) {
        const response = await page.goto(base + path);
        assert.equal(response.status(), 200, path);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, path);
        await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
        const result = await page.evaluate(() => axe.run(document, {
          runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] }
        }));
        assert.deepEqual(result.violations.map(v => ({ id: v.id, impact: v.impact })), [], path);
      }
    }
    assert.deepEqual(errors, []);
    console.log('Desktop/mobile HTTP, overflow, WCAG automated and JavaScript checks passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
