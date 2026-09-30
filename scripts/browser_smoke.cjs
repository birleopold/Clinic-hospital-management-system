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
    for (const width of [1440, 768, 390]) {
      await page.setViewportSize({ width, height: 900 });
      for (const path of ['/suite/', '/suite/workforce/', '/suite/workforce/directory/', '/suite/workforce/timesheets/', '/suite/workforce/inbox/', '/suite/workforce/new/shift/', '/suite/management/', '/suite/management/cases/', '/suite/management/assets/', '/suite/management/checklists/', '/suite/management/budgets/', '/suite/management/expenses/', '/suite/diagnostics/', '/suite/diagnostics/templates/', '/suite/diagnostics/templates/new/', '/suite/visiting-specialists/', '/suite/recalls/', '/suite/appointment-requests/', '/suite/outreach/', '/suite/insights/', ...['custody','aliquots','reagents','quality','runs','programmes','enrollments','reviews','studies'].flatMap(kind=>['/suite/clinical-operations/'+kind+'/', '/suite/clinical-operations/'+kind+'/new/']), '/suite/finance/', '/suite/returns/', '/suite/price-reviews/', '/suite/replenishment/', '/pharmacy/catalog/', '/pharmacy/baskets/', '/suite/results/', '/suite/insurance/prepare/',
        '/suite/stock/', '/suite/medication-round/', '/suite/theatre/',
        '/suite/pregnancies/', '/suite/maternity-visits/', '/suite/vaccinations/',
        '/suite/rehabilitation/', '/suite/rehab-sessions/', '/suite/specialty-follow-up/',
        '/suite/vaccination-corrections/', '/suite/storage-protocols/', '/suite/cold-chain/',
        '/suite/perioperative/', '/suite/instrument-counts/', '/suite/deliveries/',
        '/suite/newborns/', '/suite/labour-observations/', '/suite/rehab-outcomes/',
        '/suite/vaccine-adverse-events/', '/suite/tasks/', '/suite/tasks/new/', '/suite/department-board/', '/suite/department-board/?board=lab', '/suite/department-board/?board=ward', '/suite/department-board/?board=theatre', '/suite/note-templates/', '/suite/find-patient/', ...(process.env.CLINIC_TEST_PATIENT_ID ? ['/suite/patient/'+process.env.CLINIC_TEST_PATIENT_ID+'/', '/suite/patient/'+process.env.CLINIC_TEST_PATIENT_ID+'/task/', '/suite/patient/'+process.env.CLINIC_TEST_PATIENT_ID+'/document/'] : [])]) {
        const response = await page.goto(base + path);
        assert.equal(response.status(), 200, path);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, path);
        await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
        const result = await page.evaluate(() => axe.run(document, {
          runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa'] }
        }));
        assert.deepEqual(result.violations.map(v => ({ id: v.id, impact: v.impact })), [], path);
        if (process.env.CLINIC_TEST_SCREENSHOTS && (['/suite/','/suite/outreach/','/suite/insights/','/suite/clinical-operations/programmes/new/','/suite/diagnostics/','/suite/diagnostics/templates/new/','/suite/workforce/','/suite/workforce/timesheets/','/suite/finance/','/suite/returns/','/suite/replenishment/','/suite/theatre/','/suite/specialty-follow-up/'].includes(path)||path.startsWith('/suite/patient/'))) {
          require('node:fs').mkdirSync(process.env.CLINIC_TEST_SCREENSHOTS,{recursive:true});
          await page.screenshot({path:require('node:path').join(process.env.CLINIC_TEST_SCREENSHOTS, (path.split('/')[2]||'home')+'-'+width+'.png'),fullPage:true});
        }
      }
    }
    if(process.env.CLINIC_TEST_DIAGNOSTIC_SHEET_ID){
      await page.goto(base+'/suite/diagnostics/sheets/'+process.env.CLINIC_TEST_DIAGNOSTIC_SHEET_ID+'/');
      await page.locator('#id_decision').selectOption('release');
      await page.locator('#id_reason').fill('Synthetic browser review completed');
      await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Record decision',exact:true}).click()]);
      await page.getByRole('link',{name:'Patient report / print / download',exact:true}).click();
      assert.equal(await page.getByRole('heading',{name:'Diagnostic report',exact:true}).count(),1);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Patient report overflow');
      await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
      const reportAudit=await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
      assert.deepEqual(reportAudit.violations.map(v=>v.id),[],'Patient report accessibility');
    }
    if(process.env.CLINIC_TEST_SHIFT_ID){
      await page.goto(base+'/suite/workforce/shift/'+process.env.CLINIC_TEST_SHIFT_ID+'/');
      for(const name of ['Clock in','Start break','End break','Clock out']){
        await Promise.all([page.waitForNavigation(),page.getByRole('button',{name,exact:true}).click()]);
      }
      assert.equal(await page.getByRole('button',{name:'Clock in',exact:true}).count(),0);
      await page.goto(base+'/suite/workforce/timesheets/');
      await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
      const attendanceAudit=await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
      assert.deepEqual(attendanceAudit.violations.map(v=>v.id),[],'Attendance accessibility');
    }
    if(process.env.CLINIC_TEST_BASKET_ID){
      const path='/pharmacy/baskets/'+process.env.CLINIC_TEST_BASKET_ID+'/';
      await page.goto(base+path);
      await page.locator('#id_code').fill(process.env.CLINIC_TEST_MEDICINE_CODE);
      await page.locator('#id_packs').fill('2');
      await page.locator('#id_prescription_item').selectOption(process.env.CLINIC_TEST_RX_ITEM_ID);
      await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Add to basket',exact:true}).click()]);
      for(const width of [1440,768,390]){
        await page.setViewportSize({width,height:900});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Basket overflow');
        await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
        const audit=await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
        assert.deepEqual(audit.violations.map(v=>({id:v.id,impact:v.impact})),[],'Basket accessibility');
        if(process.env.CLINIC_TEST_SCREENSHOTS)await page.screenshot({path:require('node:path').join(process.env.CLINIC_TEST_SCREENSHOTS,'basket-'+width+'.png'),fullPage:true});
      }
      await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Hold basket',exact:true}).click()]);
      assert.equal(await page.getByRole('button',{name:'Add to basket',exact:true}).count(),0);
      await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Resume basket',exact:true}).click()]);
      await page.locator('[name=reviewed]').check();
      await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Dispense all and prepare invoice',exact:true}).click()]);
      await page.getByRole('link',{name:'Print medicine labels',exact:true}).click();
      assert.equal(await page.getByRole('heading',{name:'Medicine labels',exact:true}).count(),1);
    }
    await page.setViewportSize({width:390,height:900});
    await page.goto(`${base}/suite/`);
    await page.getByRole('button',{name:'Menu',exact:true}).click();
    assert.equal(await page.locator('#navigation-toggle').getAttribute('aria-expanded'),'true');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#navigation-toggle').getAttribute('aria-expanded'),'false');
    if(process.env.CLINIC_TEST_PATIENT_ID){
      await page.goto(`${base}/suite/patient/${process.env.CLINIC_TEST_PATIENT_ID}/`);
      await page.getByRole('link',{name:'Add clinical note',exact:true}).click();
      assert.equal(await page.locator('#id_patient').inputValue(),process.env.CLINIC_TEST_PATIENT_ID);
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
    const matches=await page.locator('#workspace-links .module-link:visible').allTextContents();
    assert(matches.length>0 && matches.every(text=>text.toLowerCase().includes('vaccination')));
    if (process.env.CLINIC_TEST_PATIENT_ID) {
      await page.goto(`${base}/suite/patient/${process.env.CLINIC_TEST_PATIENT_ID}/task/`);
      await page.locator('#id_audience').selectOption('lab');
      await page.locator('#id_title').fill('Synthetic browser handoff '+Date.now());
      await page.locator('#id_instruction').fill('Synthetic review only');
      await page.locator('#id_due_at').fill('2026-10-01T12:00');
      await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Save',exact:true}).click()]);
      await page.locator('#id_status').selectOption('completed');
      await page.locator('#id_resolution').fill('Synthetic task completed');
      await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Update task',exact:true}).click()]);
      assert.equal(await page.getByRole('button',{name:'Update task',exact:true}).count(),0);
      await page.goto(`${base}/suite/clinical/`);
      await page.locator('#id_patient-search').fill('Synthetic');
      await page.waitForFunction(()=>Array.from(document.querySelectorAll('p.helptext')).some(p=>p.textContent.includes('matches.')));
      assert((await page.locator('#id_patient option').count())>1);
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
      for (const [key,value] of Object.entries({source_reference:'Synthetic external provider',manufacturer:'Synthetic maker',lot_number:'TEST-LOT',dose:'Test dose',route:'Test route',site:'Test site',consent_reference:'Synthetic consent'})) {
        await form.locator(`[name=${key}]`).fill(value);
      }
      await Promise.all([page.waitForNavigation(), form.getByRole('button',{name:'Record given dose'}).click()]);
      assert.equal(await page.locator('tbody tr').filter({hasText:name}).locator('.badge').innerText(),'given');
    }
    assert.deepEqual(errors, []);
    console.log('Desktop/mobile HTTP, overflow, WCAG automated and JavaScript checks passed.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
