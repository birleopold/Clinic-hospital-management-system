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
  const alpha=fixture.tenants[0],alphaWorkspace='/accounts/tenants/'+alpha.pk+'/workspace/';
  for(const width of [1440,768,390]){
   await page.setViewportSize({width,height:900});
   for(const route of ['/accounts/control/','/accounts/tenants/',alphaWorkspace,'/accounts/tenants/support/','/accounts/approvals/','/accounts/support/sessions/']){
    assert.equal((await page.goto(owner+route)).status(),200);await audit(page,route+' '+width);
   }
  }
  await page.goto(owner+'/accounts/tenants/');
  const registration=page.locator('#register-tenant');
  assert.equal(await registration.getAttribute('open'),null);await registration.locator('summary').click();
  await registration.locator('#register_name').fill('Synthetic Gamma');await registration.locator('#register_origin').fill('https://gamma.example.test');
  await registration.locator('#register_bind_port').fill('18004');await registration.locator('#register_admin_username').fill('gamma-admin');await registration.locator('#register_service_type').selectOption('custom');
  for(const service of await registration.locator('input[name=services]').all())await service.uncheck();
  await registration.locator('input[name=services][value=patients]').check();
  await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Register tenant',exact:true}).click()]);
  assert.equal(await page.getByRole('heading',{name:'Synthetic Gamma',exact:true}).count(),1);
  assert.match(new URL(page.url()).pathname,/^\/accounts\/tenants\/\d+\/workspace\/$/);
  const gammaWorkspace=page.url();
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'Download protected deployment bundle',exact:true}).click();assert((await download).suggestedFilename().endsWith('.zip'));
  // Readiness and support records contain only synthetic, non-clinical evidence.
  await page.goto(gammaWorkspace);
  const check=page.locator('.portal-checkpoint').filter({has:page.locator('input[name=step][value=isolation]')});
  await check.locator('summary').click();await check.locator('select[name=status]').selectOption('verified');
  await check.locator('textarea[name=evidence]').fill('Disposable acceptance fixture: simulated operator verification, not production evidence.');
  await Promise.all([page.waitForNavigation(),check.getByRole('button',{name:'Save readiness check',exact:true}).click()]);
  assert.equal(await page.locator('.portal-checkpoint').filter({has:page.locator('input[name=step][value=isolation]')}).getByText('Operator verified',{exact:true}).first().isVisible(),true);
  await page.getByText('Open a support case',{exact:true}).click();
  await page.locator('#case_title').fill('Synthetic Gamma onboarding review');await page.locator('#case_category').selectOption('onboarding');
  await page.locator('#case_priority').selectOption('normal');await page.locator('#case_detail').fill('Disposable browser verification of the owner support workflow. No patient information.');
  await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Create support case',exact:true}).click()]);
  const gammaCase=page.url();assert.match(new URL(gammaCase).pathname,/^\/accounts\/tenants\/\d+\/cases\/\d+\/$/);
  await page.locator('#case_update_status').selectOption('resolved');await page.locator('#case_update_resolution').fill('Synthetic support workflow verified.');
  await page.locator('#case_update_note').fill('Closing this disposable acceptance case.');
  await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Save case update',exact:true}).click()]);
  assert.equal(await page.locator('.portal-hero').getByText('Resolved',{exact:true}).count(),1);
  for(const width of [1440,768,390]){
   await page.setViewportSize({width,height:900});
   for(const url of [gammaWorkspace,gammaCase,owner+'/accounts/tenants/support/?status=all']){
    assert.equal((await page.goto(url)).status(),200);await audit(page,new URL(url).pathname+' populated '+width);
   }
  }
  await page.goto(owner+'/accounts/approvals/');await page.locator('#id_facility').selectOption(String(fixture.facility));await page.locator('#id_operation').selectOption('expense');await page.locator('#id_approver').selectOption(String(fixture.manager));await page.locator('#id_maximum').fill('800');
  await page.locator('#id_starts_at').fill(new Date(Date.now()-60000).toISOString().slice(0,16));await page.locator('#id_ends_at').fill(new Date(Date.now()+86400000).toISOString().slice(0,16));await page.locator('#id_reason').fill('Synthetic browser delegation');
  await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Grant approval authority',exact:true}).click()]);
  await page.getByRole('heading',{name:'review-manager · Operating expenses',exact:true}).waitFor();
  const policy=page.locator('article').filter({has:page.getByRole('heading',{name:'Synthetic control facility · Operating expenses',exact:true})});await policy.locator('input[name=reason]').fill('Synthetic browser policy');
  await Promise.all([page.waitForNavigation(),policy.getByRole('button',{name:'Require active approval grants',exact:true}).click()]);
  assert.equal(await page.getByText('Active grants required',{exact:true}).count(),1);
  const authority=page.locator('article').filter({has:page.getByRole('heading',{name:'review-manager · Operating expenses',exact:true})});await authority.locator('input[name=reason]').fill('Synthetic browser revocation');
  await Promise.all([page.waitForNavigation(),authority.getByRole('button',{name:'Revoke authority',exact:true}).click()]);assert.equal(await page.getByText(/Revoked .*Synthetic browser revocation/).count(),1);
  await page.goto(owner+alphaWorkspace);
  await page.locator('#lifecycle_reason').fill('Synthetic suspension');
  const beforeCancellation=page.url(),cancelledPosts=[];
  const watchCancelledPost=request=>{if(request.method()==='POST'&&request.url()===owner+alphaWorkspace)cancelledPosts.push(request.url());};
  page.on('request',watchCancelledPost);
  await Promise.all([page.waitForEvent('dialog').then(dialog=>dialog.dismiss()),page.getByRole('button',{name:'Suspend tenant',exact:true}).click()]);
  page.off('request',watchCancelledPost);
  assert.equal(page.url(),beforeCancellation);assert.deepEqual(cancelledPosts,[]);
  assert.equal(await page.locator('.portal-hero .portal-state-active').count(),1);
  assert.equal(await page.locator('#lifecycle_reason').inputValue(),'Synthetic suspension');
  page.on('dialog',d=>d.accept());
  await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Suspend tenant',exact:true}).click()]);
  for(let i=0;i<20;i++){const r=await anon.request.get(alpha.origin+'/accounts/login/');if(r.status()===503)break;assert(i<19);await new Promise(r=>setTimeout(r,500));}
  await page.locator('#launch_reason').fill('Synthetic owner diagnosis');
  await Promise.all([page.waitForNavigation(),page.getByRole('button',{name:'Open audited owner support',exact:true}).click()]);
  assert.equal(await page.locator('form[action$="/accounts/support/accept/"] input[name=csrfmiddlewaretoken]').count(),0);
  await audit(page,'Owner support launch');
  await Promise.all([page.waitForURL(u=>u.hostname==='127.0.0.2'),page.getByRole('button',{name:'Continue to tenant workspace',exact:true}).click()]);
  assert.equal(await page.getByRole('heading',{name:'Owner control dashboard',exact:true}).count(),1);
  assert.equal((await root.request.get(alpha.origin+'/accounts/tenants/')).status(),403);
  // A separate owner browser resumes normal access while support stays open.
  const rootTab=await root.newPage();await rootTab.goto(owner+alphaWorkspace);await rootTab.locator('#lifecycle_reason').fill('Synthetic resumed operation');
  await Promise.all([rootTab.waitForNavigation(),rootTab.getByRole('button',{name:'Resume tenant',exact:true}).click()]);
  for(let i=0;i<20;i++){const r=await anon.request.get(alpha.origin+'/accounts/login/');if(r.status()===200)break;assert(i<19);await new Promise(r=>setTimeout(r,500));}
  const adminContext=await browser.newContext({ignoreHTTPSErrors:true});const admin=await adminContext.newPage();await login(admin,alpha.origin,'tenant-admin',alpha.otp);
  await admin.goto(alpha.origin+'/accounts/support/sessions/');await audit(admin,'Tenant support revocation');
  await Promise.all([admin.waitForNavigation(),admin.getByRole('button',{name:'End this support session',exact:true}).click()]);
  assert.equal((await root.request.get(alpha.origin+'/accounts/control/',{maxRedirects:0})).status(),302);
  assert.deepEqual(errors,[]);
  console.log('PASS: separate databases, catalogues, signing keys and private media; real HTTPS policy suspension/resume; owner portal registry/details/queue/readiness/case resolution/registration/bundle/support/revocation; approval grant/policy/revocation UI; MFA; 3 widths and WCAG 2/2.1 AA.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
