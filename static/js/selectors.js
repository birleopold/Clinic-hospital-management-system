document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('#record-actions form').forEach(form=>{const input=document.createElement('input');input.type='hidden';input.name='return_to_record';input.value='1';form.append(input);});
 document.querySelectorAll('select[data-lookup]').forEach(select=>{
  const label=document.createElement('label'),input=document.createElement('input'),state=document.createElement('p');
  input.type='search';input.id=select.id+'-search';input.placeholder='Type to find options';label.htmlFor=input.id;
  label.textContent='Search '+(document.querySelector('label[for="'+select.id+'"]')?.textContent||'options').replace(/:$/,'');
  state.className='helptext';state.setAttribute('aria-live','polite');let controller,timer;
  select.before(label,input);select.after(state);
  input.addEventListener('input',()=>{clearTimeout(timer);controller?.abort();timer=setTimeout(async()=>{
   controller=new AbortController();state.textContent='Searching…';
   try{const response=await fetch(select.dataset.lookup+'?q='+encodeURIComponent(input.value),{signal:controller.signal});if(!response.ok)throw Error();const data=await response.json();
    const chosen=select.selectedOptions[0]?.cloneNode(true);const value=select.value;select.replaceChildren(new Option('Choose an option',''));
    if(value&&chosen)select.append(chosen);
    for(const row of data.results)if(String(row.id)!==value)select.add(new Option(row.label,row.id));select.value=value;
    state.textContent=data.results.length+' matches. Choose from the list below the search field.';
   }catch(error){if(error.name!=='AbortError')state.textContent='Search unavailable. Try again; your current selection is preserved.';}
  },250);});
 });
});
