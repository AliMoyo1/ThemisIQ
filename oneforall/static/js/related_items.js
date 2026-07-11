/* ── Related Items Panel ────────────────────────────────────────────────
   Reusable cross-module linking panel for entity drawers.
   Usage: RelatedItems.mount(containerElement, module, entityType, entityId, {canEdit:true, baseUrl:''})
   Depends on: apiFetch, esc (both globally available in ThemisIQ SPAs)
   PLAN-07: Related Items panel + manual cross-module linking
   ──────────────────────────────────────────────────────────────────── */
window.RelatedItems = (function(){
  'use strict';

  function mount(container, mod, etype, eid, opts){
    opts = opts || {};
    container.setAttribute('data-ri-mounted', '1');
    container.innerHTML = '<div class="erm-drawer-section"><div class="erm-drawer-section-title">🔗 Related Items</div><div id="ri-list" style="font-size:13px;color:var(--muted)">Loading...</div></div>';

    fetchLinks(mod, etype, eid, opts);
  }

  function fetchLinks(mod, etype, eid, opts){
    var xhr = new XMLHttpRequest();
    xhr.open('GET', '/api/links/' + mod + '/' + etype + '/' + eid, true);
    xhr.onload = function(){
      if(xhr.status !== 200){ renderEmpty(); return; }
      var links = JSON.parse(xhr.responseText);
      if(!links || !links.length){ renderEmpty(); return; }
      renderLinks(links, opts);
    };
    xhr.onerror = function(){ renderEmpty(); };
    xhr.send();
  }

  function renderEmpty(){
    var el = document.getElementById('ri-list');
    if(el) el.innerHTML = '<div style="color:var(--muted);padding:4px 0">No related items</div>';
  }

  function renderLinks(links, opts){
    var el = document.getElementById('ri-list');
    if(!el) return;
    var html = links.map(function(l){
      var href = l.title ? '/' + l.module + '/?open=' + l.entity_type + ':' + l.entity_id : '#';
      var title = (window.esc ? window.esc(l.title || '(deleted)') : (l.title || '(deleted)'));
      var relChip = l.relationship !== 'related' ? ' <span style="font-size:10px;color:var(--accent);background:var(--surface2);padding:1px 6px;border-radius:100px">' + (window.esc ? window.esc(l.relationship) : l.relationship) + '</span>' : '';
      var unlinkBtn = '';
      if(opts.canEdit && l.direction === 'outgoing'){
        unlinkBtn = ' <button class="btn btn-sm btn-danger" onclick="RelatedItems.unlink(' + l.link_id + ',\'' + l.module + '\',\'' + l.entity_type + '\',' + l.entity_id + ')" style="padding:2px 6px;font-size:10px">✕</button>';
      }
      return '<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border)">' +
        '<div>' +
        (l.title ? '<a href="' + href + '" target="_blank" style="color:var(--accent);text-decoration:none;font-weight:600">' + title + '</a>' : '<span style="color:var(--muted)">' + title + '</span>') +
        ' <span style="font-size:11px;color:var(--muted)">(' + l.module + ' ' + l.entity_type + ')</span>' +
        relChip + '</div>' + unlinkBtn + '</div>';
    }).join('');
    el.innerHTML = html;

    if(opts.canEdit){
      var addBtn = document.createElement('button');
      addBtn.className = 'btn btn-sm btn-secondary';
      addBtn.textContent = '+ Link';
      addBtn.style.marginTop = '8px';
      addBtn.onclick = function(){ openPicker(mod, etype, eid, opts); };
      el.parentElement.appendChild(addBtn);
    }
  }

  function openPicker(mod, etype, eid, opts){
    var overlay = document.createElement('div');
    overlay.className = 'erm-drawer-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:center;justify-content:center';
    overlay.innerHTML = '<div style="background:var(--surface);border-radius:12px;padding:24px;width:420px;max-width:90vw">' +
      '<div style="font-size:16px;font-weight:700;margin-bottom:12px">Link related item</div>' +
      '<input id="riSearch" type="text" placeholder="Search..." style="width:100%;padding:10px;border:1px solid var(--border);border-radius:var(--radius);font-size:14px;box-sizing:border-box">' +
      '<div id="riSearchResults" style="margin-top:8px;max-height:240px;overflow-y:auto"></div>' +
      '<button class="btn btn-secondary" onclick="this.parentElement.parentElement.remove()" style="margin-top:12px">Cancel</button></div>';
    document.body.appendChild(overlay);

    var inp = document.getElementById('riSearch');
    var res = document.getElementById('riSearchResults');
    var timer = null;
    inp.oninput = function(){
      clearTimeout(timer);
      var q = inp.value.trim();
      if(q.length < 2){ res.innerHTML = ''; return; }
      timer = setTimeout(function(){
        var x = new XMLHttpRequest();
        x.open('GET', '/api/search?q=' + encodeURIComponent(q), true);
        x.onload = function(){
          if(x.status !== 200) return;
          var data = JSON.parse(x.responseText);
          var results = (data.results || []).filter(function(r){ return !(r.module===mod && r.type===etype && r.id===eid); });
          if(!results.length){ res.innerHTML = '<div style="color:var(--muted);padding:8px;font-size:13px">No results</div>'; return; }
          res.innerHTML = results.map(function(r){
            return '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px;cursor:pointer;border-bottom:1px solid var(--border)" onclick="RelatedItems.doLink(\'' + mod + '\',\'' + etype + '\',' + eid + ',\'' + r.module + '\',\'' + r.type + '\',' + r.id + ',this)">' +
              '<div><strong>' + (window.esc ? window.esc(r.title||r.subtitle||'') : (r.title||'')) + '</strong><br><span style="font-size:11px;color:var(--muted)">' + r.module + ' ' + (r.type||'') + '</span></div>' +
              '<button class="btn btn-sm btn-primary" style="padding:4px 10px">Link</button></div>';
          }).join('');
        };
        x.send();
      }, 300);
    };
  }

  window.RelatedItems.doLink = function(srcMod, srcType, srcId, tgtMod, tgtType, tgtId, btnEl){
    btnEl.disabled = true;
    btnEl.textContent = '...';
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/links', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = function(){
      if(xhr.status === 200){
        if(typeof showToast === 'function') showToast('Linked!');
        // Close the picker overlay and re-fetch
        var ov = btnEl.closest('.erm-drawer-overlay');
        if(ov) ov.remove();
        // Re-mount the panel
        window.location.reload();
      } else {
        if(typeof showToast === 'function') showToast('Failed to link', 'error');
        btnEl.disabled = false;
        btnEl.textContent = 'Link';
      }
    };
    xhr.onerror = function(){
      if(typeof showToast === 'function') showToast('Network error', 'error');
      btnEl.disabled = false;
      btnEl.textContent = 'Link';
    };
    xhr.send(JSON.stringify({
      source_module: srcMod, source_type: srcType, source_id: srcId,
      target_module: tgtMod, target_type: tgtType, target_id: tgtId,
      relationship: 'related'
    }));
  };

  window.RelatedItems.unlink = function(linkId, mod, etype, eid){
    if(!confirm('Remove this link?')) return;
    var xhr = new XMLHttpRequest();
    xhr.open('DELETE', '/api/links/' + linkId, true);
    xhr.onload = function(){
      if(xhr.status === 200){
        window.location.reload();
      } else {
        if(typeof showToast === 'function') showToast('Failed to unlink', 'error');
      }
    };
    xhr.send();
  };

  return { mount: mount, doLink: doLink, unlink: unlink };
})();
