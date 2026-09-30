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
        '/suite/stock/', '/suite/medication-round/', '/suite/theatre/',
        '/suite/pregnancies/', '/suite/maternity-visits/', '/suite/vaccinations/',
        '/suite/rehabilitation/', '/suite/rehab-sessions/', '/suite/specialty-follow-up/']) {
        const response = await page.goto(base + path);
        assert.equal(response.status(), 200, path);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, path);
        await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
        const result = await page.evaluate(() => axe.run(document, {
          runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] }
        }));
        assert.deepEqual(result.violations.map(v => ({ id: v.id, impact: v.impact })), [], path);
        if (process.env.CLINIC_TEST_SCREENSHOTS && ['/suite/theatre/','/suite/specialty-follow-up/'].includes(path)) {
          require('node:fs').mkdirSync(process.env.CLINIC_TEST_SCREENSHOTS,{recursive:true});
          await page.screenshot({path:require('node:path').join(process.env.CLINIC_TEST_SCREENSHOTS, path.split('/')[2]+'-'+width+'.png'),fullPage:true});
        }
      }
    }
    await page.goto(`${base}/suite/pregnancies/`);
    const detailLink=page.locator('a[href^="/suite/specialties/pregnancies/"]').first();
    if (await detailLink.count()) {
      await detailLink.click();
      assert.equal(await page.getByRole('heading',{name:'Recorded details',exact:true}).count(),1);
      await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
      const detailAudit=await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
      assert.deepEqual(detailAudit.violations.map(v=>v.id),[],'Specialty record detail');
    }
    await page.goto(`${base}/suite/`);
    await page.locator('#workspace-search').fill('vaccination');
    assert.equal(await page.locator('#workspace-links .module-link:visible').count(), 1);
    if (process.env.CLINIC_TEST_PATIENT_ID) {
      // Opt-in write scenario. Use only a synthetic patient on a disposable instance.
      await page.goto(`${base}/suite/vaccinations/`);
      const name = 'Browser test vaccine ' + Date.now();
      await page.locator('#id_patient').selectOption(process.env.CLINIC_TEST_PATIENT_ID);
      await page.locator('#id_vaccine').fill(name);
      await page.locator('#id_dose_label').fill('Synthetic dose');
      await page.locator('#id_due_on').fill(new Date().toISOString().slice(0,10));
      await Promise.all([page.waitForNavigation(), page.getByRole('button',{name:'Save record',exact:true}).click()]);
      const row = page.locator('tbody tr').filter({hasText:name});
      await row.locator('summary').click();
      const form = row.locator('form[action$="/given/"]');
      await form.locator('[name=administered_at]').fill(new Date(Date.now()-3600000).toISOString().slice(0,16));
      await form.locator('[name=expires_on]').fill(new Date(Date.now()+86400000).toISOString().slice(0,10));
      for (const [key,value] of Object.entries({manufacturer:'Synthetic maker',lot_number:'TEST-LOT',dose:'Test dose',route:'Test route',site:'Test site',consent_reference:'Synthetic consent'})) {
        await form.locator(`[name=${key}]`).fill(value);
      }
      await Promise.all([page.waitForNavigation(), form.getByRole('button',{name:'Record given dose'}).click()]);
      assert.equal(await page.locator('tbody tr').filter({hasText:name}).locator('.badge').innerText(),'given');
    }
    assert.deepEqual(errors, []);
    console.log('Desktop/mobile HTTP, overflow, WCAG automated and JavaScript checks passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
