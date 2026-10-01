const fs=require('fs'),assert=require('node:assert/strict'),crypto=require('crypto');
const {chromium}=require('playwright');
const fixture=JSON.parse(fs.readFileSync(process.env.CLINIC_TENANT_FIXTURE,'utf8'));
function otp(key){const counter=Buffer.alloc(8);counter.writeBigUInt64BE(BigInt(Math.floor(Date.now()/30000)));const h=crypto.createHmac('sha1',Buffer.from(key,'hex')).update(counter).digest();return String((h.readUInt32BE(h[19]&15)&0x7fffffff)%1000000).padStart(6,'0');}
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CLINIC_CHROMIUM_PATH||undefined,args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--no-zygote','--single-process']});
 const errors=[];const owner='https://127.0.0.1:8443';
 try{
  const root=await browser.newContext({ignoreHTTPSErrors:true});const page=await root.newPage();page.on('pageerror',e=>errors.push(e.message));
  async function login(p,url,username,key){
   for(let i=0;i<30;i++){try{await p.goto(url+'/accounts/login/');break;}catch(e){if(i===29)throw e;await new Promise(r=>setTimeout(r,500));}}
   await p.locator('[name=username]').fill(username);await p.locator('[name=password]').fill(fixture.password);
   await Promise.all([p.waitForURL(u=>!u.pathname.includes('/login')),p.locator('button[type=submit]').click()]);
   await p.locator('#id_token').fill(otp(key));await Promise.all([p.waitForURL(u=>!u.pathname.includes('/mfa')),p.getByRole('button',{name:'Verify and continue',exact:true}).click()]);
  }
  async function audit(p,label){
   assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,label+' overflow');
   await p.addScriptTag({path:process.env.CLINIC_AXE_PATH||require.resolve('axe-core/axe.min.js')});
   const result=await p.evaluate(()=>axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}}));
   assert.deepEqual(result.violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)})),[],label+' accessibility');
  }
  const anon=await browser.newContext({ignoreHTTPSErrors:true});
  for(const t of fixture.tenants){
   let ready;for(let i=0;i<30;i++){try{ready=await anon.request.get(t.origin+'/accounts/login/');break;}catch(e){if(i===29)throw e;await new Promise(r=>setTimeout(r,500));}}
   assert.equal(ready.status(),200);
   const r=await anon.request.get(t.origin+'/api/inventory/items/',{headers:{Authorization:'Bearer '+t.jwt}});assert.equal(r.status(),200);
   const rows=(await r.json()).results;assert.equal(rows.length,1);assert.equal(rows[0].name,t.name+' private medicine');
   const other=fixture.tenants.find(x=>x!==t);
   assert.equal((await anon.request.get(t.origin+'/api/inventory/items/',{headers:{Authorization:'Bearer '+other.jwt}})).status(),401);
   assert.equal((await anon.request.get(t.origin+'/portal/'+other.portal)).status(),403);
   assert.equal((await anon.request.get(t.origin+'/media/private.txt')).status(),404);
  }
  assert.equal(fixture.tenants[0].patient,fixture.tenants[1].patient);
  await login(page,owner,'review-owner',fixture.owner_otp);
  for(const width of [1440,768,390]){
   await page.setViewportSize({width,height:900});
   for(const route of ['/accounts/control/','/accounts/tenants/','/accounts/approvals/','/accounts/support/sessions/']){
    assert.equal((await page.goto(owner+route)).status(),200);await audit(page,route+' '+width);
   }
  }
  await page.goto(owner+'/accounts/tenants/');
  await page.locator('#id_name').fill('Synthetic Gamma');await page.locator('#id_origin').fill('https://gamma.example.test');
  await page.locator('#id_bind_port').fill('18004');await page.locator('#id_admin_username').fill('gamma-admin');await page.locator('#id_service_type').selectOption('custom');
  await page.locator('input[name=services][value=patients]').check();
  await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Register tenant',exact:true}).click()]);
  assert.equal(await page.getByRole('heading',{name:'Synthetic Gamma',exact:true}).count(),1);
  const gamma=page.locator('section').filter({has:page.getByRole('heading',{name:'Synthetic Gamma',exact:true})});
  const download=page.waitForEvent('download');await gamma.getByRole('button',{name:'Download protected deployment bundle',exact:true}).click();assert((await download).suggestedFilename().endsWith('.zip'));
  await page.goto(owner+'/accounts/approvals/');await page.locator('#id_facility').selectOption(String(fixture.facility));await page.locator('#id_operation').selectOption('expense');await page.locator('#id_approver').selectOption(String(fixture.manager));await page.locator('#id_maximum').fill('800');
  await page.locator('#id_starts_at').fill(new Date(Date.now()-60000).toISOString().slice(0,16));await page.locator('#id_ends_at').fill(new Date(Date.now()+86400000).toISOString().slice(0,16));await page.locator('#id_reason').fill('Synthetic browser delegation');
  await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Grant approval authority',exact:true}).click()]);
  await page.getByRole('heading',{name:'review-manager · Operating expenses',exact:true}).waitFor();
  const policy=page.locator('article').filter({has:page.getByRole('heading',{name:'Synthetic control facility · Operating expenses',exact:true})});await policy.locator('input[name=reason]').fill('Synthetic browser policy');
  await Promise.all([page.waitForNavigation(),policy.getByRole('button',{name:'Require active approval grants',exact:true}).click()]);
  assert.equal(await page.getByText('Active grants required',{exact:true}).count(),1);
  const authority=page.locator('article').filter({has:page.getByRole('heading',{name:'review-manager · Operating expenses',exact:true})});await authority.locator('input[name=reason]').fill('Synthetic browser revocation');
  await Promise.all([page.waitForNavigation(),authority.getByRole('button',{name:'Revoke authority',exact:true}).click()]);assert.equal(await page.getByText(/Revoked .*Synthetic browser revocation/).count(),1);
  const alpha=fixture.tenants[0];await page.goto(owner+'/accounts/tenants/');
  let card=page.locator('section').filter({has:page.getByRole('heading',{name:'Synthetic Alpha',exact:true})});await card.locator('input[name=reason]').fill('Synthetic suspension');
  page.on('dialog',d=>d.accept());
  await Promise.all([page.waitForNavigation(),card.getByRole('button',{name:'Suspend tenant',exact:true}).click()]);
  for(let i=0;i<20;i++){const r=await anon.request.get(alpha.origin+'/accounts/login/');if(r.status()===503)break;assert(i<19);await new Promise(r=>setTimeout(r,500));}
  card=page.locator('section').filter({has:page.getByRole('heading',{name:'Synthetic Alpha',exact:true})});await card.locator('input[name=reason]').fill('Synthetic owner diagnosis');
  await Promise.all([page.waitForNavigation(),card.getByRole('button',{name:'Open audited owner support',exact:true}).click()]);
  assert.equal(await page.locator('form[action$="/accounts/support/accept/"] input[name=csrfmiddlewaretoken]').count(),0);
  await audit(page,'Owner support launch');
  await Promise.all([page.waitForURL(u=>u.hostname==='127.0.0.2'),page.getByRole('button',{name:'Continue to tenant workspace',exact:true}).click()]);
  assert.equal(await page.getByRole('heading',{name:'Owner control dashboard',exact:true}).count(),1);
  assert.equal((await root.request.get(alpha.origin+'/accounts/tenants/')).status(),403);
  // A separate owner browser resumes normal access while support stays open.
  const rootTab=await root.newPage();await rootTab.goto(owner+'/accounts/tenants/');card=rootTab.locator('section').filter({has:rootTab.getByRole('heading',{name:'Synthetic Alpha',exact:true})});await card.locator('input[name=reason]').fill('Synthetic resumed operation');
  await Promise.all([rootTab.waitForNavigation(),card.getByRole('button',{name:'Resume tenant',exact:true}).click()]);
  for(let i=0;i<20;i++){const r=await anon.request.get(alpha.origin+'/accounts/login/');if(r.status()===200)break;assert(i<19);await new Promise(r=>setTimeout(r,500));}
  const adminContext=await browser.newContext({ignoreHTTPSErrors:true});const admin=await adminContext.newPage();await login(admin,alpha.origin,'tenant-admin',alpha.otp);
  await admin.goto(alpha.origin+'/accounts/support/sessions/');await audit(admin,'Tenant support revocation');
  await Promise.all([admin.waitForNavigation(),admin.getByRole('button',{name:'End this support session',exact:true}).click()]);
  assert.equal((await root.request.get(alpha.origin+'/accounts/control/',{maxRedirects:0})).status(),302);
  assert.deepEqual(errors,[]);
  console.log('PASS: separate databases, catalogues, signing keys and private media; real HTTPS policy suspension/resume; owner registration/bundle/support/revocation; approval grant/policy/revocation UI; MFA; 3 widths and WCAG 2/2.1 AA.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
