'use strict';
(()=>{
 const $=id=>document.getElementById(id);
 const encoder=new TextEncoder(),decoder=new TextDecoder();
 const AAD=encoder.encode('clinic-offline-v1');
 let db,key=null,vault=null,meta=null,profile=null,editing=null,timer=null;
 let selected=new Set(),saving=Promise.resolve(),busy=false;
 const notice=text=>{$('notice').textContent=text;};
 const element=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
 function openDB(){return new Promise((resolve,reject)=>{const req=indexedDB.open('clinic-offline-v1',1);req.onupgradeneeded=()=>req.result.createObjectStore('vault');req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});}
 function store(mode,fn){return new Promise((resolve,reject)=>{const tx=db.transaction('vault',mode),req=fn(tx.objectStore('vault'));let value;req.onsuccess=()=>{value=req.result;};tx.oncomplete=()=>resolve(value);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});}
 async function derive(pass,salt){const source=await crypto.subtle.importKey('raw',encoder.encode(pass),'PBKDF2',false,['deriveKey']);return crypto.subtle.deriveKey({name:'PBKDF2',salt,iterations:600000,hash:'SHA-256'},source,{name:'AES-GCM',length:256},false,['encrypt','decrypt']);}
 function persist(){
  if(!vault||!key)throw Error('Unlock the workspace first.');
  const text=JSON.stringify(vault),currentKey=key,currentMeta=meta;
  saving=saving.catch(()=>{}).then(async()=>{const iv=crypto.getRandomValues(new Uint8Array(12));const ciphertext=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:AAD},currentKey,encoder.encode(text));await store('readwrite',s=>s.put({version:1,salt:currentMeta.salt,iv,ciphertext},'data'));});
  return saving;
 }
 async function api(path,data){
  const response=await fetch('/offline/api/'+path,{method:data===undefined?'GET':'POST',credentials:'same-origin',headers:data===undefined?{}:{'Content-Type':'application/json','X-CSRFToken':profile?.csrf||''},body:data===undefined?undefined:JSON.stringify(data)});
  const json=await response.json().catch(()=>({error:response.status===403?'Access denied or session expired. Sign in online.':'Unexpected server response.'}));
  if(!response.ok){const error=Error(json.error||'Request failed.');error.status=response.status;error.details=json;throw error;}
  return json;
 }
 async function onlineSession(){
  const result=await api('session/');
  if(vault&&(result.user_id!==vault.user_id||result.facility_id!==vault.facility_id)){lock();throw Error('Account or facility changed. Unlock only under the original staff account.');}
  profile=result;return result;
 }
 function resetTimer(){clearTimeout(timer);if(key)timer=setTimeout(lock,5*60*1000);}
 function lock(){key=null;vault=null;editing=null;selected.clear();clearTimeout(timer);$('workspace').hidden=true;$('lock').hidden=true;$('unlock').hidden=!meta;$('setup').hidden=!!meta;for(const id of ['drafts','draft-fields','patient-options','devices','account'])$(id).replaceChildren();$('passphrase').value='';$('patient-search').value='';notice('Workspace locked. Patient context and drafts are encrypted on this device.');}
 function connection(){ $('connection').textContent=navigator.onLine?'Connection available':'Offline — drafts stay on this device'; }
 function unlocked(){
  $('setup').hidden=true;$('unlock').hidden=true;$('workspace').hidden=false;$('lock').hidden=false;
  $('account').textContent=`${vault.username} · Device: ${vault.label}`;
  selected=new Set((vault.pack?.patients||[]).map(p=>p.id));
  $('selected-count').textContent=selected.size+' patients selected';
  renderSchemas();renderDrafts();resetTimer();
 }
 function renderSchemas(){
  const dropdown=$('module');dropdown.replaceChildren();
  for(const schema of vault.pack?.schemas||[]){const option=element('option',schema.title);option.value=schema.slug;dropdown.append(option);}
  if(!dropdown.options.length)dropdown.append(element('option','Prepare patient context first'));
  $('prepared').textContent=vault.pack?`Downloaded ${new Date(vault.pack.prepared_at).toLocaleString()}. Context expires in seven days.`:'';
  editing=null;renderForm();
 }
 function renderForm(values={}){
  const schema=vault.pack?.schemas.find(s=>s.slug===$('module').value);
  $('draft-fields').replaceChildren();$('save-draft').disabled=!schema;
  if(!schema)return;
  for(const field of schema.fields){
   const id='offline-'+field.name;
   const label=element('label',field.label);label.htmlFor=id;$('draft-fields').append(label);
   let control;
   if(field.type==='relation'||field.type==='choice'){
    control=element('select');const empty=element('option','Select…');empty.value='';control.append(empty);
    for(const choice of field.choices){const option=element('option',choice.label);option.value=choice.value;control.append(option);}
   }else if(field.type==='textarea')control=element('textarea');
   else{control=element('input');control.type=field.type;if(field.step)control.step=field.step;}
   control.id=id;control.name=field.name;control.required=field.required;
   if(field.max_length)control.maxLength=field.max_length;
   if(field.type==='checkbox')control.checked=!!values[field.name];else control.value=values[field.name]??'';
   $('draft-fields').append(control);
   if(field.help){const help=element('p',field.help);help.className='help';$('draft-fields').append(help);}
   if(field.truncated){const help=element('p','Only the 200 most recent choices are downloaded. Use the connected workspace for older records.');help.className='help';$('draft-fields').append(help);}
  }
 }
 function preview(draft){return draft.schema.fields.filter(f=>draft.values[f.name]!==''&&draft.values[f.name]!==undefined).map(f=>`${f.label}: ${f.choices?.find(c=>c.value===draft.values[f.name])?.label||draft.values[f.name]}`).join('\n\n');}
 function renderDrafts(){
  const panel=$('drafts');panel.replaceChildren();
  if(!vault.drafts.length){panel.append(element('p','No drafts saved on this device.'));return;}
  for(const draft of [...vault.drafts].reverse()){
   const article=element('article');article.className='draft';article.append(element('h3',draft.schema.title));article.append(element('p','Device draft time: '+new Date(draft.created_at).toLocaleString()));
   const state=element('p',draft.status==='synced'?`Synchronized · record #${draft.record_id}`:draft.attempted?'Outcome unconfirmed — retry the same submission':draft.error||'Saved on this device; awaiting your review');state.className='state';article.append(state);
   const details=element('details');details.append(element('summary','Review draft content'),element('pre',preview(draft)));article.append(details);
   if(draft.status!=='synced'){
    const reviewLabel=element('label');const reviewed=element('input');reviewed.type='checkbox';reviewed.setAttribute('aria-label','I reviewed this draft for synchronization');reviewLabel.append(reviewed,document.createTextNode('I reviewed this draft for synchronization.'));article.append(reviewLabel);
    const send=element('button',draft.attempted?'Check/retry submission':'Synchronize reviewed draft');send.type='button';send.disabled=true;reviewed.onchange=()=>{send.disabled=!reviewed.checked;};send.onclick=()=>run(()=>syncDraft(draft.client_id));article.append(send);
    const edit=element('button','Edit with current context');edit.type='button';edit.disabled=!!draft.attempted;edit.onclick=()=>{
     if(!vault.pack?.schemas.some(s=>s.slug===draft.slug)){notice('Download fresh context for this workspace first.');return;}
     editing=draft.client_id;$('module').value=draft.slug;renderForm(draft.values);notice('Review every field. Saving creates a new draft submission using the currently downloaded context.');$('module').scrollIntoView({behavior:'smooth'});
    };article.append(edit);
   }
   const remove=element('button',draft.status==='synced'?'Remove local copy':'Delete local draft');remove.type='button';remove.disabled=!!draft.attempted&&draft.status!=='synced';remove.onclick=()=>run(async()=>{if(!confirm('Remove this local draft? This does not change any server record.'))return;vault.drafts=vault.drafts.filter(d=>d.client_id!==draft.client_id);await persist();renderDrafts();});article.append(remove);
   panel.append(article);
  }
 }
 async function syncDraft(id){
  await onlineSession();const current=vault;const draft=vault.drafts.find(d=>d.client_id===id);if(!draft)return;
  draft.attempted=true;draft.error='';await persist();renderDrafts();
  try{
   const result=await api('sync/',{device_id:vault.device_id,client_id:draft.client_id,client_created_at:draft.created_at,slug:draft.slug,grant:draft.grant,values:draft.values,proofs:draft.proofs});
   if(vault!==current)return;
   if(!Number.isSafeInteger(result.record_id)||result.record_id<=0||typeof result.model!=='string')throw Error('Server receipt was not confirmed.');
   draft.status='synced';draft.record_id=result.record_id;draft.attempted=false;await persist();notice('Draft synchronized. The server applied its current authorization and validation checks.');
  }catch(error){
   if(vault!==current)return;
   // A definitive client/conflict/validation rejection did not create a record.
   if([400,401,403,409,422].includes(error.status))draft.attempted=false;
   draft.error=error.message+(error.details?.fields?' '+Object.entries(error.details.fields).map(([k,v])=>k+': '+v.map(e=>e.message).join(', ')).join('; '):'');
   await persist();notice(draft.attempted?'Response not confirmed. Retry this same submission before editing or deleting it.':draft.error);
  }
  if(vault===current)renderDrafts();
 }
 async function run(fn){if(busy)return;busy=true;try{await fn();}catch(error){notice(error.message||'Unable to complete this operation.');}finally{busy=false;resetTimer();}}
 $('setup-form').onsubmit=event=>{event.preventDefault();run(async()=>{
  if(!crypto?.subtle)throw Error('Use HTTPS (or localhost) with a browser supporting Web Crypto.');
  const pass=$('new-passphrase').value;if(pass.length<12)throw Error('Use a passphrase of at least 12 characters.');
  await onlineSession();const label=$('device-name').value.trim();const enrolled=await api('devices/',{label});
  meta={salt:crypto.getRandomValues(new Uint8Array(16))};key=await derive(pass,meta.salt);
  vault={version:1,user_id:profile.user_id,facility_id:profile.facility_id,username:profile.username,label,device_id:enrolled.device_id,pack:null,drafts:[]};await persist();$('new-passphrase').value='';unlocked();notice('Encrypted workspace created. Select patients while connected.');
 });};
 $('unlock-form').onsubmit=event=>{event.preventDefault();run(async()=>{
  const stored=await store('readonly',s=>s.get('data'));if(!stored)throw Error('No local workspace found.');
  const pass=$('passphrase').value;$('passphrase').value='';
  try{const derived=await derive(pass,stored.salt);const decoded=await crypto.subtle.decrypt({name:'AES-GCM',iv:stored.iv,additionalData:AAD},derived,stored.ciphertext);const opened=JSON.parse(decoder.decode(decoded));if(opened.version!==1)throw Error();key=derived;meta={salt:stored.salt};vault=opened;}catch(error){throw Error('Could not unlock. Check your passphrase; the local data may also have been altered.');}
  unlocked();notice('Unlocked. Drafts remain local until you review and synchronize them.');
 });};
 $('search-form').onsubmit=event=>{event.preventDefault();run(async()=>{
  await onlineSession();const result=await api('patients/?q='+encodeURIComponent($('patient-search').value));$('patient-options').replaceChildren();
  for(const patient of result.patients){const label=element('label');const checkbox=element('input');checkbox.type='checkbox';checkbox.checked=selected.has(patient.id);checkbox.onchange=()=>{if(checkbox.checked)selected.add(patient.id);else selected.delete(patient.id);$('selected-count').textContent=selected.size+' patients selected';};label.append(checkbox,document.createTextNode(patient.label));$('patient-options').append(label);}
  if(!result.patients.length)$('patient-options').append(element('p','No matching patients in your facility.'));
 });};
 $('prepare').onclick=()=>run(async()=>{await onlineSession();if(!selected.size||selected.size>20)throw Error('Select between one and twenty patients.');const pack=await api('prepare/',{device_id:vault.device_id,patient_ids:[...selected]});vault.pack=pack;await persist();renderSchemas();notice('Selected patient context downloaded and encrypted. Existing drafts still retain their original context.');});
 $('module').onchange=()=>{editing=null;renderForm();};
 $('draft-form').onsubmit=event=>{event.preventDefault();run(async()=>{
  const schema=vault.pack?.schemas.find(s=>s.slug===$('module').value);if(!schema)throw Error('Prepare context first.');
  if(vault.drafts.filter(d=>d.status!=='synced').length>=100&&!editing)throw Error('Synchronize some drafts first (maximum 100 pending).');
  const values={},proofs={};for(const field of schema.fields){const control=$('offline-'+field.name);values[field.name]=field.type==='checkbox'?control.checked:control.value;if(String(values[field.name]).length>20000)throw Error('One field exceeds the 20,000-character offline limit.');if(field.type==='relation'&&control.value)proofs[field.name]=field.choices.find(c=>c.value===control.value)?.proof;}
  if(editing)vault.drafts=vault.drafts.filter(d=>d.client_id!==editing);
  vault.drafts.push({client_id:crypto.randomUUID(),slug:schema.slug,schema:structuredClone(schema),grant:vault.pack.grant,values,proofs,status:'pending',attempted:false,created_at:new Date().toISOString()});
  await persist();editing=null;renderForm();renderDrafts();notice('Draft encrypted and saved on this device. It is not yet part of the server clinical record.');
 });};
 $('list-devices').onclick=()=>run(async()=>{await onlineSession();const result=await api('devices/'+(profile.can_manage_devices?'?facility=1':''));$('devices').replaceChildren();for(const device of result.devices){const box=element('div');box.className='device';box.append(element('span',device.label+' · '+device.owner__username+(device.revoked_at?' · Revoked':'')));if(!device.revoked_at){const button=element('button','Revoke');button.type='button';button.onclick=()=>run(async()=>{await onlineSession();await api('devices/',{revoke:device.id});notice('Device revoked. It can no longer synchronize; locally encrypted data is not remotely erased.');button.disabled=true;});box.append(button);}$('devices').append(box);}});
 $('forget').onclick=()=>run(async()=>{if(!confirm('Permanently erase this local encrypted workspace, including unsynchronized drafts? This cannot be undone and does not revoke server access.'))return;await saving.catch(()=>{});await store('readwrite',s=>s.delete('data'));meta=null;lock();notice('Local workspace erased. Revoke any unused registration while online.');});
 $('lock').onclick=()=>lock();
 document.addEventListener('visibilitychange',()=>{if(document.hidden&&key)lock();});
 for(const event of ['keydown','pointerdown'])document.addEventListener(event,resetTimer,{passive:true});
 window.addEventListener('online',connection);window.addEventListener('offline',connection);
 (async()=>{try{db=await openDB();const stored=await store('readonly',s=>s.get('data'));meta=stored?{salt:stored.salt}:null;$('unlock').hidden=!stored;$('setup').hidden=!!stored;connection();if('serviceWorker'in navigator)await navigator.serviceWorker.register('/offline/sw.js',{scope:'/offline/'});}catch(error){notice('Offline storage is unavailable: '+error.message);}})();
})();
