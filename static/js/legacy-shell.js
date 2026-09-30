(function() {
      function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
          const cookies = document.cookie.split(';');
          for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
              cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
              break;
            }
          }
        }
        return cookieValue;
      }
      document.addEventListener('htmx:configRequest', function(evt) {
        evt.detail.headers['X-CSRFToken'] = getCookie('csrftoken');
      });
    })();

(function(){
      const containerId = 'toast-container';
      function ensureContainer(){
        let c = document.getElementById(containerId);
        if(!c){
          c = document.createElement('div');
          c.id = containerId;
          document.body.appendChild(c);
        }
        return c;
      }
      window.showToast = function(message, type){
        const c = ensureContainer();
        const el = document.createElement('div');
        el.className = 'toast' + (type === 'error' ? ' error' : '');
        el.textContent = message || 'Done';
        c.appendChild(el);
        if(type === 'error'){const close=document.createElement('button');close.type='button';close.textContent='Dismiss';close.onclick=()=>el.remove();el.append(close);return;}
        setTimeout(()=>{
          el.style.opacity = '0';
          el.style.transition = 'opacity 200ms';
          setTimeout(()=> el.remove(), 220);
        }, 1600);
      }

      // Global HTMX handler
      document.addEventListener('htmx:afterRequest', function(event){
        try{
          const xhr = event.detail && event.detail.xhr;
          const elt = event.detail && event.detail.elt;
          const ok = xhr && xhr.status >= 200 && xhr.status < 300;
          if(ok && event.detail.requestConfig?.verb?.toLowerCase() === 'get')return;
          if(ok){
            const msg = (elt && elt.dataset && elt.dataset.successMessage) || 'Success';
            window.showToast(msg);
            if(elt && elt.dataset && elt.dataset.reloadAfter === 'true'){
              setTimeout(()=> location.reload(), 600);
            }
          } else if(xhr) {
            let msg = 'Request failed';
            try{
              const ct = xhr.getResponseHeader && xhr.getResponseHeader('Content-Type');
              if(ct && ct.indexOf('application/json') !== -1){
                const data = JSON.parse(xhr.responseText || '{}');
                msg = (data.detail || data.error || JSON.stringify(data)).slice(0, 180);
              } else if(xhr.responseText){
                msg = xhr.responseText.slice(0, 180);
              }
            }catch(e){}
            window.showToast(msg, 'error');
          }
        }catch(e){}
      });

      // Patient autocomplete
      function attachPatientAutocomplete(input){
        const wrap = input.closest('.autocomplete') || input.parentElement;
        let list = wrap.querySelector('.autocomplete-list');
        if(!list){
          list = document.createElement('div');
          list.className = 'autocomplete-list';
          wrap.appendChild(list);
        }
        const targetId = input.dataset.targetInputId;
        const target = targetId ? document.getElementById(targetId) : null;
        const selectedHint = document.getElementById(input.dataset.selectedHintId || 'patient-selected');
        let lastTerm = '';
        let timer = null;
        let ctrl = null;
        function clear(){ list.innerHTML = ''; list.style.display = 'none'; }
        function pick(p){
          if(target) target.value = p.id;
          const name = `${p.first_name || ''} ${p.last_name || ''}`.trim();
          input.value = name || `#${p.id}`;
          if(selectedHint){ selectedHint.textContent = `Selected: ${name} ${p.phone ? '('+p.phone+')' : ''} #${p.id}`.trim(); }
          clear();
        }
        async function query(term){
          try{
            if(ctrl) ctrl.abort();
            ctrl = new AbortController();
            const resp = await fetch(`/api/patients/?q=${encodeURIComponent(term)}`, { signal: ctrl.signal, headers: { 'Accept': 'application/json' } });
            if(!resp.ok){ clear(); return; }
            const data = await resp.json();
            const items = Array.isArray(data) ? data : (data.results || []);
            list.innerHTML = '';
            items.slice(0, 8).forEach(p => {
              const row = document.createElement('div');
              row.className = 'autocomplete-item';
              const name = `${p.first_name || ''} ${p.last_name || ''}`.trim() || 'Unnamed';
              const phone = p.phone ? ` (${p.phone})` : '';
              row.textContent = `${name}${phone} — #${p.id}`;
              row.addEventListener('click', ()=> pick(p));
              list.appendChild(row);
            });
            list.style.display = items.length ? 'block' : 'none';
          }catch(e){ clear(); }
        }
        input.addEventListener('input', function(){
          const term = input.value.trim();
          if(target) target.value = '';
          if(term === lastTerm) return;
          lastTerm = term;
          if(timer) clearTimeout(timer);
          if(term.length < 2){ clear(); return; }
          timer = setTimeout(()=> query(term), 250);
        });
        input.addEventListener('keydown', function(e){ if(e.key === 'Escape') clear(); });
        document.addEventListener('click', function(e){ if(!wrap.contains(e.target)) clear(); });
      }
      document.addEventListener('DOMContentLoaded', function(){
        document.querySelectorAll('[data-autocomplete="patient"]').forEach(attachPatientAutocomplete);
        // Dropdown click toggles
        function closeAllDropdowns(except){
          document.querySelectorAll('.dropdown.open').forEach(function(d){ if(d!==except) d.classList.remove('open'); });
        }
        document.querySelectorAll('.dropdown > .dropbtn').forEach(function(btn){
          btn.addEventListener('click', function(e){
            e.preventDefault();
            const dd = btn.parentElement;
            const willOpen = !dd.classList.contains('open');
            closeAllDropdowns(dd);
            if(willOpen) dd.classList.add('open'); else dd.classList.remove('open');
          });
        });
        document.addEventListener('click', function(e){
          const any = e.target.closest && e.target.closest('.dropdown');
          if(!any) closeAllDropdowns(null);
        });
      });
    })();
