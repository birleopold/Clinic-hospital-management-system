document.addEventListener('DOMContentLoaded',()=>{
 const button=document.getElementById('navigation-toggle'), sidebar=document.getElementById('workspace-navigation');
 if(!button||!sidebar)return;
 const media=matchMedia('(max-width: 1100px)');
 const reset=()=>{document.body.classList.remove('navigation-open','navigation-collapsed');button.setAttribute('aria-expanded',String(!media.matches));};
 reset();media.addEventListener('change',reset);
 button.addEventListener('click',()=>{
  const expanded=button.getAttribute('aria-expanded')==='true';
  button.setAttribute('aria-expanded',String(!expanded));
  document.body.classList.toggle(media.matches?'navigation-open':'navigation-collapsed',media.matches?!expanded:expanded);
 });
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&media.matches){document.body.classList.remove('navigation-open');button.setAttribute('aria-expanded','false');button.focus();}});
 document.querySelectorAll('#workspace-navigation a').forEach(link=>{if(link.pathname===location.pathname)link.setAttribute('aria-current','page');});
});
