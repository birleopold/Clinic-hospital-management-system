// Requires the same disposable-instance credentials as browser_smoke.cjs,
// plus CLINIC_TEST_PATIENT_ID and CLINIC_TEST_PATIENT_QUERY for a synthetic patient.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
 const base=process.env.CLINIC_TEST_URL||'http://127.0.0.1:8000';
 const patient=process.env.CLINIC_TEST_PATIENT_ID;
 assert(patient&&process.env.CLINIC_TEST_PATIENT_QUERY,'Set synthetic patient ID and search query');
 const browser=await chromium.launch({executablePath:process.env.CLINIC_CHROMIUM_PATH||undefined});
 try{
  const context=await browser.newContext({viewport:{width:1280,height:1000}});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/accounts/login/');
  await page.locator('[name=username]').fill(process.env.CLINIC_TEST_USERNAME);
  await page.locator('[name=password]').fill(process.env.CLINIC_TEST_PASSWORD);
  await Promise.all([page.waitForURL(url=>!url.pathname.includes('/login')),page.locator('button[type=submit]').click()]);
  await page.goto(base+'/offline/');
  const pass='Synthetic device passphrase '+Date.now(),label='Browser offline '+Date.now(),note='Synthetic disconnected note '+Date.now();
  await page.locator('#device-name').fill(label);await page.locator('#new-passphrase').fill(pass);
  await page.getByRole('button',{name:'Create encrypted workspace'}).click();
  await page.locator('#workspace').waitFor({state:'visible'});
  await page.locator('#patient-search').fill(process.env.CLINIC_TEST_PATIENT_QUERY);
  await page.getByRole('button',{name:'Find patients',exact:true}).click();
  await page.locator('#patient-options input').first().waitFor();
  // Select by exact patient identity via labels from the current scoped search.
  const labelText=await page.evaluate(async q=>{
   const r=await fetch('/offline/api/patients/?q='+encodeURIComponent(q.query));
   return (await r.json()).patients.find(p=>String(p.id)===q.id)?.label;
  },{query:process.env.CLINIC_TEST_PATIENT_QUERY,id:patient});
  assert(labelText,'Synthetic patient missing from search results');
  await page.getByLabel(labelText,{exact:true}).check();
  await page.getByRole('button',{name:'Download selected context'}).click();
  await page.locator('#module option[value=clinical]').waitFor({state:'attached'});
  await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('downloaded and encrypted'));
  await page.evaluate(()=>navigator.serviceWorker.ready);
  await page.waitForFunction(()=>!!navigator.serviceWorker.controller);
  await context.setOffline(true);await page.reload();
  await page.locator('#passphrase').fill('wrong passphrase');await page.getByRole('button',{name:'Unlock offline workspace'}).click();
  await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Could not unlock'));
  await page.locator('#passphrase').fill(pass);await page.getByRole('button',{name:'Unlock offline workspace'}).click();
  await page.locator('#workspace').waitFor({state:'visible'});
  await page.locator('#module').selectOption('clinical');
  await page.locator('#offline-patient').selectOption(patient);
  await page.locator('#offline-kind').selectOption('note');
  await page.locator('#offline-text').fill(note);
  await page.getByRole('button',{name:'Save encrypted draft'}).click();
  await page.locator('.draft').waitFor();
  const storage=await page.evaluate(()=>new Promise((resolve,reject)=>{
   const r=indexedDB.open('clinic-offline-v1');r.onsuccess=()=>{const get=r.result.transaction('vault').objectStore('vault').get('data');get.onsuccess=()=>resolve({keys:Object.keys(get.result).sort(),ciphertext:new TextDecoder().decode(get.result.ciphertext)});get.onerror=()=>reject(get.error);};r.onerror=()=>reject(r.error);
  }));
  assert.deepEqual(storage.keys,['ciphertext','iv','salt','version']);assert(!storage.ciphertext.includes(note));assert(!storage.ciphertext.includes(labelText));
  for(const width of [1280,390]){
   await page.setViewportSize({width,height:900});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   await page.evaluate(fs.readFileSync(require.resolve('axe-core/axe.min.js'),'utf8'));
   const audit=await page.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
   assert.deepEqual(audit.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)})),[]);
   if(process.env.CLINIC_TEST_SCREENSHOTS){fs.mkdirSync(process.env.CLINIC_TEST_SCREENSHOTS,{recursive:true});await page.screenshot({path:process.env.CLINIC_TEST_SCREENSHOTS+'/offline-'+width+'.png',fullPage:true});}
  }
  await context.setOffline(false);
  let sentPayload;
  await page.route('**/offline/api/sync/',async route=>{sentPayload=route.request().postDataJSON();const result=await route.fetch();assert.equal(result.status(),201,await result.text());await route.abort('failed');});
  await page.getByLabel('I reviewed this draft for synchronization').check();
  await page.getByRole('button',{name:'Synchronize reviewed draft'}).click();
  await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Response not confirmed'));
  assert(await page.getByRole('button',{name:'Edit with current context'}).isDisabled());
  await page.unroute('**/offline/api/sync/');
  await page.getByLabel('I reviewed this draft for synchronization').check();
  await page.getByRole('button',{name:'Check/retry submission'}).click();
  await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Draft synchronized'));
  const replay=await page.evaluate(async payload=>{const s=await (await fetch('/offline/api/session/')).json();const r=await fetch('/offline/api/sync/',{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':s.csrf},body:JSON.stringify(payload)});return {status:r.status,data:await r.json()};},sentPayload);
  assert.equal(replay.status,200);assert.equal(replay.data.replayed,true);
  await page.getByRole('button',{name:'Manage registered devices'}).click();
  const device=page.locator('.device').filter({hasText:label});await device.getByRole('button',{name:'Revoke',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Device revoked'));
  await page.getByRole('button',{name:'Lock device',exact:true}).click();
  assert.equal(await page.locator('#drafts').innerText(),'');
  assert.deepEqual(errors,[]);
  console.log('Offline reload, wrong-passphrase rejection, encrypted draft storage, mobile/desktop accessibility, lost-response retry, idempotency and revocation passed.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
