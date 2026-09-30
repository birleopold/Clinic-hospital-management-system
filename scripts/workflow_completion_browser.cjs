// Run only against the disposable synthetic seed described in the release notes.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
(async()=>{
  const base=process.env.CLINIC_TEST_URL || 'http://127.0.0.1:8000';
  const fixture=JSON.parse(fs.readFileSync(process.env.CLINIC_UI_FIXTURE,'utf8'));
  const password=process.env.CLINIC_TEST_PASSWORD;
  assert(password,'Set the synthetic fixture password');
  const axe=process.env.CLINIC_AXE_PATH || require.resolve('axe-core/axe.min.js');
  const browser=await chromium.launch({executablePath:process.env.CLINIC_CHROMIUM_PATH || undefined,args:['--no-sandbox','--disable-dev-shm-usage']});
  const errors=[];
  try{
    const context=await browser.newContext();const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    async function login(username){
      await context.clearCookies();await page.goto(base+'/accounts/login/');
      await page.locator('[name=username]').fill(username);await page.locator('[name=password]').fill(password);
      await Promise.all([page.waitForURL(u=>!u.pathname.includes('/login')),page.locator('button[type=submit]').click()]);
    }
    async function audit(page,label){
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,label+' overflow');
      await page.addScriptTag({path:axe});
      const result=await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
      assert.deepEqual(result.violations.map(v=>({id:v.id,impact:v.impact,targets:v.nodes.map(n=>n.target)})),[],label+' accessibility');
    }
    for(let attempt=0;attempt<30;attempt++){try{await fetch(base+'/accounts/login/');break;}catch(error){if(attempt===29)throw error;await new Promise(r=>setTimeout(r,1000));}}
    await login('ui-admin');
    const routes=['/accounts/setup/','/accounts/structure/departments/','/accounts/structure/rooms/','/suite/management/expenses/',`/suite/management/expenses/${fixture.expense}/`,'/suite/management/expenses/report/','/suite/workforce/new/swap/','/suite/workforce/timesheets/',`/suite/diagnostics/orders/${fixture.order}/`,`/suite/patient/${fixture.patient}/itinerary/`,`/suite/admissions/${fixture.admission}/discharge-copy/`,`/portal/token?patient_id=${fixture.patient}`];
    for(const width of [1440,768,390]){
      await page.setViewportSize({width,height:900});
      for(const route of routes){
        const response=await page.goto(base+route);assert.equal(response.status(),200,route);await audit(page,route+' '+width);
        if(process.env.CLINIC_TEST_SCREENSHOTS && (route.includes('/expenses/')||route.includes('/diagnostics/')||route.includes('/itinerary/'))){
          fs.mkdirSync(process.env.CLINIC_TEST_SCREENSHOTS,{recursive:true});
          await page.screenshot({path:path.join(process.env.CLINIC_TEST_SCREENSHOTS,route.replace(/[^a-z0-9]/gi,'_')+'-'+width+'.png'),fullPage:true});
        }
      }
    }
    await page.goto(base+`/suite/management/expenses/${fixture.expense}/`);
    await page.locator('#id_amount').fill('200');await page.locator('#id_method').selectOption('bank');
    await page.locator('#id_account_reference').fill('Synthetic browser account');await page.locator('#id_transaction_reference').fill('UI-BROWSER-TX-2');
    await page.locator('#id_evidence').fill('Synthetic browser statement evidence');
    await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Record disbursement evidence',exact:true}).click()]);
    assert.equal(await page.getByText('Another supervisor must review your evidence.',{exact:true}).count(),1);
    await login('ui-reviewer');await page.goto(base+`/suite/management/expenses/${fixture.expense}/`);
    const article=page.locator('article').filter({hasText:'UI-BROWSER-TX-2'});await article.locator('textarea[name=reason]').fill('Checked synthetic account statement');
    await Promise.all([page.waitForNavigation(),article.getByRole('button',{name:'Record independent review',exact:true}).click()]);
    assert.equal(await page.locator('article').filter({hasText:'UI-BROWSER-TX-2'}).getByRole('heading',{name:'200.00 UGX · Reconciled'}).count(),1);
    const anonymous=await browser.newContext();const portal=await anonymous.newPage();portal.on('pageerror',e=>errors.push(e.message));
    const portalUrl=base+'/portal/'+fixture.token;
    for(const width of [1440,768,390]){
      await portal.setViewportSize({width,height:900});await portal.goto(portalUrl);await audit(portal,'Patient portal '+width);
      await portal.goto(portalUrl+`/appointments/${fixture.appointment}/change/`);await audit(portal,'Patient booking change '+width);
      await portal.goto(portalUrl+'/feedback/');await audit(portal,'Patient feedback '+width);
    }
    await portal.goto(portalUrl+'/feedback/');await portal.locator('#id_title').fill('Synthetic browser feedback');await portal.locator('#id_details').fill('Test submission from the verified recipient.');
    await Promise.all([portal.waitForNavigation(),portal.getByRole('button',{name:'Submit request',exact:true}).click()]);
    assert.equal(await portal.getByText(/Synthetic browser feedback/).count(),1);
    await portal.goto(portalUrl+`/appointments/${fixture.appointment}/change/`);await portal.locator('#id_kind').selectOption('cancel');await portal.locator('#id_reason').fill('Synthetic patient cannot attend');
    await Promise.all([portal.waitForNavigation(),portal.getByRole('button',{name:'Submit request',exact:true}).click()]);
    assert.equal(await portal.getByText(/Cancel booking/).count(),1);
    await portal.getByRole('button',{name:'I have received these instructions',exact:true}).click();
    await portal.getByText(/Acknowledged/).waitFor();
    await login('ui-reception');await page.goto(base+'/suite/appointment-requests/');
    await page.getByRole('link',{name:'Review request',exact:true}).last().click();await page.locator('#id_decision').selectOption('booked');await page.locator('#id_response_note').fill('Synthetic cancellation confirmed');
    await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Save',exact:true}).click()]);
    await portal.goto(portalUrl);assert.equal(await portal.getByRole('link',{name:'Request reschedule or cancellation',exact:true}).count(),0);
    assert.deepEqual(errors,[],'Browser JavaScript errors');
    console.log('Workflow UI: 3 viewport sizes, accessibility, reviewed settlement, feedback, booking cancellation and instruction acknowledgment passed.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
