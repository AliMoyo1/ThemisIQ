/* Related Items Panel
   Reusable cross-module linking panel for entity detail drawers.

   Usage:
     RelatedItems.mount(containerElement, 'erm', 'risk', 123, {canEdit: true})

   Depends on globals: esc (HTML-escape), showToast (optional toast notification)
*/
window.RelatedItems = (function () {
  'use strict';

  function mount(container, mod, etype, eid, opts) {
    opts = opts || {};
    container.setAttribute('data-ri-mounted', '1');
    container.innerHTML =
      '<div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--border)">' +
        '<div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:8px">Related Items</div>' +
        '<div id="ri-list-' + eid + '" style="font-size:13px;color:var(--muted)">Loading...</div>' +
      '</div>';
    fetchLinks(container, mod, etype, eid, opts);
  }

  function fetchLinks(container, mod, etype, eid, opts) {
    var listEl = document.getElementById('ri-list-' + eid);
    var xhr = new XMLHttpRequest();
    xhr.open('GET', '/api/links/' + mod + '/' + etype + '/' + eid, true);
    xhr.onload = function () {
      if (xhr.status !== 200) { renderEmpty(listEl); return; }
      var links = JSON.parse(xhr.responseText);
      if (!links || !links.length) { renderEmpty(listEl); return; }
      renderLinks(listEl, links, mod, etype, eid, opts);
    };
    xhr.onerror = function () { renderEmpty(listEl); };
    xhr.send();
  }

  function renderEmpty(el) {
    if (!el) return;
    el.innerHTML = '<div style="color:var(--muted);padding:4px 0;font-size:12px">No related items</div>';
  }

  function renderLinks(el, links, mod, etype, eid, opts) {
    if (!el) return;
    var html = links.map(function (l) {
      var title = l.title || '(deleted)';
      var safeTitle = typeof esc === 'function' ? esc(title) : title;
      var relChip = l.relationship && l.relationship !== 'related'
        ? ' <span style="font-size:10px;color:var(--accent);background:var(--surface2);padding:1px 6px;border-radius:100px">' + (typeof esc === 'function' ? esc(l.relationship) : l.relationship) + '</span>'
        : '';
      var unlinkBtn = '';
      if (opts.canEdit && l.direction === 'outgoing') {
        unlinkBtn = ' <button onclick="RelatedItems.unlink(' + l.link_id + ',' + eid + ')" style="padding:2px 6px;font-size:10px;background:none;border:1px solid var(--border);border-radius:4px;cursor:pointer;color:var(--muted)">x</button>';
      }
      return '<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border)">' +
        '<div>' +
          '<span style="font-size:12px;font-weight:600;color:var(--text)">' + safeTitle + '</span>' +
          ' <span style="font-size:10px;color:var(--muted)">(' + l.module + ' ' + l.entity_type + ')</span>' +
          relChip +
        '</div>' +
        unlinkBtn +
      '</div>';
    }).join('');
    el.innerHTML = html || '<div style="color:var(--muted);font-size:12px">No related items</div>';

    if (opts.canEdit) {
      var addBtn = document.createElement('button');
      addBtn.className = 'btn btn-secondary';
      addBtn.textContent = '+ Link item';
      addBtn.style.marginTop = '8px';
      addBtn.style.fontSize = '11px';
      addBtn.onclick = function () { openPicker(mod, etype, eid, opts, el); };
      el.parentElement.appendChild(addBtn);
    }
  }

  function openPicker(mod, etype, eid, opts, listEl) {
    var existing = document.getElementById('ri-picker-overlay');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.id = 'ri-picker-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:center;justify-content:center';
    overlay.innerHTML =
      '<div style="background:var(--surface);border-radius:12px;padding:24px;width:420px;max-width:90vw;box-shadow:0 8px 40px rgba(0,0,0,.3)">' +
        '<div style="font-size:16px;font-weight:700;margin-bottom:12px;color:var(--text)">Link related item</div>' +
        '<input id="riSearchInput" type="text" placeholder="Search by title..." style="width:100%;padding:10px;border:1px solid var(--border);border-radius:var(--radius,7px);font-size:14px;box-sizing:border-box;background:var(--surface2);color:var(--text)">' +
        '<div id="riSearchResults" style="margin-top:8px;max-height:240px;overflow-y:auto"></div>' +
        '<button onclick="document.getElementById(\'ri-picker-overlay\').remove()" style="margin-top:12px;padding:6px 16px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--muted);cursor:pointer;font-size:12px">Cancel</button>' +
      '</div>';
    document.body.appendChild(overlay);

    var inp = document.getElementById('riSearchInput');
    var res = document.getElementById('riSearchResults');
    var timer = null;
    inp.focus();
    inp.oninput = function () {
      clearTimeout(timer);
      var q = inp.value.trim();
      if (q.length < 2) { res.innerHTML = ''; return; }
      timer = setTimeout(function () {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/api/search?q=' + encodeURIComponent(q), true);
        xhr.onload = function () {
          if (xhr.status !== 200) return;
          var data = JSON.parse(xhr.responseText);
          var results = (data.results || []).filter(function (r) {
            return !(r.module === mod && r.type === etype && r.id === eid);
          });
          if (!results.length) {
            res.innerHTML = '<div style="color:var(--muted);padding:8px;font-size:13px">No results</div>';
            return;
          }
          res.innerHTML = results.map(function (r) {
            var safeTitle = typeof esc === 'function' ? esc(r.title || r.subtitle || '') : (r.title || '');
            return '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px;cursor:pointer;border-bottom:1px solid var(--border)">' +
              '<div><strong style="font-size:13px;color:var(--text)">' + safeTitle + '</strong><br>' +
              '<span style="font-size:11px;color:var(--muted)">' + r.module + ' ' + (r.type || '') + '</span></div>' +
              '<button onclick="RelatedItems.doLink(\'' + mod + '\',\'' + etype + '\',' + eid + ',\'' + r.module + '\',\'' + r.type + '\',' + r.id + ',this)" ' +
                'style="padding:4px 10px;border-radius:6px;border:none;background:var(--accent);color:#fff;cursor:pointer;font-size:12px;font-weight:600">Link</button>' +
            '</div>';
          }).join('');
        };
        xhr.send();
      }, 300);
    };
  }

  function doLink(srcMod, srcType, srcId, tgtMod, tgtType, tgtId, btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = '...';
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/links', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    var csrf = (document.cookie.match(/csrf_token=([^;]+)/) || [])[1] || '';
    xhr.setRequestHeader('X-CSRF-Token', decodeURIComponent(csrf));
    xhr.onload = function () {
      var overlay = document.getElementById('ri-picker-overlay');
      if (overlay) overlay.remove();
      if (xhr.status === 200 || xhr.status === 201) {
        if (typeof showToast === 'function') showToast('Linked successfully');
        var container = document.querySelector('[data-ri-mounted="1"]');
        if (container) {
          container.removeAttribute('data-ri-mounted');
          mount(container, srcMod, srcType, srcId, {canEdit: true});
        }
      } else {
        if (typeof showToast === 'function') showToast('Failed to link', 'error');
        btnEl.disabled = false;
        btnEl.textContent = 'Link';
      }
    };
    xhr.onerror = function () {
      if (typeof showToast === 'function') showToast('Network error', 'error');
      btnEl.disabled = false;
      btnEl.textContent = 'Link';
    };
    xhr.send(JSON.stringify({
      source_module: srcMod, source_type: srcType, source_id: srcId,
      target_module: tgtMod, target_type: tgtType, target_id: tgtId,
      relationship: 'related'
    }));
  }

  function unlink(linkId, eid) {
    if (!confirm('Remove this link?')) return;
    var xhr = new XMLHttpRequest();
    xhr.open('DELETE', '/api/links/' + linkId, true);
    var csrf = (document.cookie.match(/csrf_token=([^;]+)/) || [])[1] || '';
    xhr.setRequestHeader('X-CSRF-Token', decodeURIComponent(csrf));
    xhr.onload = function () {
      if (xhr.status === 200) {
        if (typeof showToast === 'function') showToast('Link removed');
        var container = document.querySelector('[data-ri-mounted="1"]');
        if (container) {
          var mod = container.dataset.riMod;
          var etype = container.dataset.riEtype;
          if (mod && etype) {
            container.removeAttribute('data-ri-mounted');
            mount(container, mod, etype, eid, {canEdit: true});
          } else {
            window.location.reload();
          }
        }
      } else {
        if (typeof showToast === 'function') showToast('Failed to remove link', 'error');
      }
    };
    xhr.send();
  }

  return { mount: mount, doLink: doLink, unlink: unlink };
}());
