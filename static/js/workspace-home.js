
(function(){
 const input=document.getElementById('workspace-search');
 const links=Array.from(document.querySelectorAll('#workspace-links .module-link'));
 input.addEventListener('input',function(){
  const query=input.value.trim().toLocaleLowerCase();
  links.forEach(link=>{link.hidden=!link.textContent.toLocaleLowerCase().includes(query);});
  document.getElementById('workspace-count').textContent=links.filter(link=>!link.hidden).length+' workspaces shown';
 });
})();
