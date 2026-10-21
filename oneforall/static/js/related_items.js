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
    container.dataset.riMod = mod;
    container.dataset.riEtype = etype;
    container.dataset.riId = String(eid);
    container.dataset.riCanEdit = opts.canEdit ? '1' : '0';
    container.innerHTML =
      '<div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--border)">' +
        '<div style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:8px">Related Items</div>' +
        '<div id="ri-list-' + eid + '" style="font-size:13px;color:var(--muted)">Loading...</div>' +
      '</div>';
    fetchLinks(container, mod, etype, eid, opts);
  }

  function fetchLinks(container, mod, etype, eid, opts) {
    var listEl = container.querySelector('[id="ri-list-' + eid + '"]');
    var xhr = new XMLHttpRequest();
    xhr.open('GET', '/api/links/' + mod + '/' + etype + '/' + eid, true);
    xhr.onload = function () {
      if (container.dataset.riId !== String(eid) || !listEl || !listEl.isConnected) return;
      if (xhr.status !== 200) { renderError(listEl); return; }
      var links;
      try { links = JSON.parse(xhr.responseText); } catch (_) { renderError(listEl); return; }
      if (!links || !links.length) { renderEmpty(container, listEl, mod, etype, eid, opts); return; }
      renderLinks(container, listEl, links, mod, etype, eid, opts);
    };
    xhr.onerror = function () { renderError(listEl); };
    xhr.send();
  }

  function renderEmpty(container, el, mod, etype, eid, opts) {
    if (!el) return;
    el.innerHTML = '<div style="color:var(--muted);padding:4px 0;font-size:12px">No related items</div>';
    addLinkButton(container, mod, etype, eid, opts);
  }

  function renderError(el) {
    if (el) el.textContent = 'Related items are unavailable. Try again later.';
  }

  function addLinkButton(container, mod, etype, eid, opts) {
    var previous = container.querySelector('.ri-add');
    if (previous) previous.remove();
    if (!opts.canEdit) return;
    var addBtn = document.createElement('button');
    addBtn.className = 'btn btn-secondary ri-add';
    addBtn.type = 'button';
    addBtn.textContent = '+ Link item';
    addBtn.style.marginTop = '8px';
    addBtn.style.fontSize = '11px';
    addBtn.onclick = function () { openPicker(mod, etype, eid, opts, container); };
    container.appendChild(addBtn);
  }

  function safe(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function renderLinks(container, el, links, mod, etype, eid, opts) {
    if (!el) return;
    var html = links.map(function (l, index) {
      var title = l.title || '(deleted)';
      var safeTitle = safe(title);
      var localUrl = typeof l.url === 'string' && l.url.charAt(0) === '/' && l.url.charAt(1) !== '/' &&
        l.url.indexOf('\\') === -1 && !/[\u0000-\u001f]/.test(l.url)
        ? l.url : '';
      var titleHtml = localUrl ? '<a href="' + safe(localUrl) + '">' + safeTitle + '</a>' : safeTitle;
      var relChip = l.relationship && l.relationship !== 'related'
        ? ' <span style="font-size:10px;color:var(--accent);background:var(--surface2);padding:1px 6px;border-radius:100px">' + safe(l.relationship) + '</span>'
        : '';
      var unlinkBtn = '';
      if (opts.canEdit && l.direction === 'outgoing' && Number.isSafeInteger(Number(l.link_id))) {
        unlinkBtn = ' <button type="button" data-ri-unlink="' + index + '" aria-label="Remove link to ' + safe(title) +
          '" style="padding:2px 6px;font-size:10px;background:none;border:1px solid var(--border);border-radius:4px;cursor:pointer;color:var(--muted)">x</button>';
      }
      return '<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border)">' +
        '<div>' +
          '<span style="font-size:12px;font-weight:600;color:var(--text)">' + titleHtml + '</span>' +
          ' <span style="font-size:10px;color:var(--muted)">(' + safe(l.module) + ' ' + safe(l.entity_type) + ')</span>' +
          relChip +
        '</div>' +
        unlinkBtn +
      '</div>';
    }).join('');
    el.innerHTML = html || '<div style="color:var(--muted);font-size:12px">No related items</div>';
    el.querySelectorAll('[data-ri-unlink]').forEach(function (button) {
      button.addEventListener('click', function () { unlink(links[Number(button.dataset.riUnlink)].link_id, container); });
    });
    addLinkButton(container, mod, etype, eid, opts);
  }

  function openPicker(mod, etype, eid, opts, container) {
    var existing = document.getElementById('ri-picker-overlay');
    if (existing) existing.remove();
    var previousFocus = document.activeElement;
    var searchXHR = null;
    var generation = 0;
    var timer = null;

    var overlay = document.createElement('div');
    overlay.id = 'ri-picker-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:center;justify-content:center';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Link related item');
    overlay.innerHTML =
      '<div style="background:var(--surface);border-radius:12px;padding:24px;width:420px;max-width:90vw;box-shadow:0 8px 40px rgba(0,0,0,.3)">' +
        '<div style="font-size:16px;font-weight:700;margin-bottom:12px;color:var(--text)">Link related item</div>' +
        '<label for="riSearchInput" style="display:block;font-size:12px;margin-bottom:6px;color:var(--muted)">Search records you may open</label>' +
        '<input id="riSearchInput" type="text" placeholder="Search by title..." style="width:100%;padding:10px;border:1px solid var(--border);border-radius:var(--radius,7px);font-size:14px;box-sizing:border-box;background:var(--surface2);color:var(--text)">' +
        '<div id="riSearchResults" aria-live="polite" style="margin-top:8px;max-height:240px;overflow-y:auto"></div>' +
        '<div id="riPickerStatus" role="alert" style="font-size:12px;color:var(--danger);margin-top:8px"></div>' +
        '<button type="button" class="ri-cancel" style="margin-top:12px;padding:6px 16px;border-radius:6px;border:1px solid var(--border);background:var(--surface);color:var(--muted);cursor:pointer;font-size:12px">Cancel</button>' +
      '</div>';
    document.body.appendChild(overlay);

    var inp = document.getElementById('riSearchInput');
    var res = document.getElementById('riSearchResults');
    var status = document.getElementById('riPickerStatus');
    function close() {
      clearTimeout(timer);
      generation += 1;
      if (searchXHR) searchXHR.abort();
      overlay.remove();
      if (previousFocus && previousFocus.isConnected) previousFocus.focus();
    }
    overlay.querySelector('.ri-cancel').addEventListener('click', close);
    overlay.addEventListener('click', function (event) { if (event.target === overlay) close(); });
    overlay.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') { event.preventDefault(); close(); return; }
      if (event.key !== 'Tab') return;
      var focusable = Array.from(overlay.querySelectorAll('input, button:not([disabled])'));
      if (!focusable.length) return;
      if (event.shiftKey && document.activeElement === focusable[0]) {
        event.preventDefault(); focusable[focusable.length - 1].focus();
      } else if (!event.shiftKey && document.activeElement === focusable[focusable.length - 1]) {
        event.preventDefault(); focusable[0].focus();
      }
    });
    inp.focus();
    inp.oninput = function () {
      clearTimeout(timer);
      generation += 1;
      if (searchXHR) searchXHR.abort();
      status.textContent = '';
      var q = inp.value.trim();
      if (q.length < 2) { res.innerHTML = ''; return; }
      var requested = generation;
      timer = setTimeout(function () {
        var xhr = new XMLHttpRequest();
        searchXHR = xhr;
        xhr.open('GET', '/api/search?q=' + encodeURIComponent(q), true);
        xhr.onload = function () {
          if (requested !== generation || !overlay.isConnected) return;
          if (xhr.status !== 200) { status.textContent = 'Search is unavailable. Try again.'; return; }
          var data;
          try { data = JSON.parse(xhr.responseText); } catch (_) {
            status.textContent = 'Search results could not be read.'; return;
          }
          var results = (data.results || []).filter(function (r) {
            return !(r.module === mod && r.type === etype && String(r.id) === String(eid));
          });
          if (!results.length) {
            res.innerHTML = '<div style="color:var(--muted);padding:8px;font-size:13px">No results</div>';
            return;
          }
          res.innerHTML = results.map(function (r, index) {
            var safeTitle = safe(r.title || r.subtitle || '');
            return '<div style="display:flex;align-items:center;justify-content:space-between;padding:8px;cursor:pointer;border-bottom:1px solid var(--border)">' +
              '<div><strong style="font-size:13px;color:var(--text)">' + safeTitle + '</strong><br>' +
              '<span style="font-size:11px;color:var(--muted)">' + safe(r.module) + ' ' + safe(r.type || '') + '</span></div>' +
              '<button type="button" data-ri-result="' + index + '" ' +
                'style="padding:4px 10px;border-radius:6px;border:none;background:var(--accent);color:#fff;cursor:pointer;font-size:12px;font-weight:600">Link</button>' +
            '</div>';
          }).join('');
          res.querySelectorAll('[data-ri-result]').forEach(function (button) {
            button.addEventListener('click', function () {
              var result = results[Number(button.dataset.riResult)];
              doLink(mod, etype, eid, result.module, result.type, result.id, button, container, close, status);
            });
          });
        };
        xhr.onerror = function () {
          if (requested === generation && overlay.isConnected) status.textContent = 'Search is unavailable. Try again.';
        };
        xhr.send();
      }, 300);
    };
  }

  function doLink(srcMod, srcType, srcId, tgtMod, tgtType, tgtId, btnEl, container, closePicker, statusEl) {
    btnEl.disabled = true;
    btnEl.textContent = '...';
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/links', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    var csrf = (document.cookie.match(/csrf_token=([^;]+)/) || [])[1] || '';
    xhr.setRequestHeader('X-CSRF-Token', decodeURIComponent(csrf));
    xhr.onload = function () {
      if (xhr.status === 200 || xhr.status === 201) {
        if (closePicker) closePicker();
        if (typeof showToast === 'function') showToast('Linked successfully');
        if (container) {
          mount(container, srcMod, srcType, srcId, {canEdit: container.dataset.riCanEdit === '1'});
          container.tabIndex = -1;
          container.focus();
        }
      } else {
        if (typeof showToast === 'function') showToast('Failed to link', 'error');
        if (statusEl) statusEl.textContent = 'This link could not be saved. Check your access and try again.';
        btnEl.disabled = false;
        btnEl.textContent = 'Link';
      }
    };
    xhr.onerror = function () {
      if (typeof showToast === 'function') showToast('Network error', 'error');
      if (statusEl) statusEl.textContent = 'The network request failed. Try again.';
      btnEl.disabled = false;
      btnEl.textContent = 'Link';
    };
    xhr.send(JSON.stringify({
      source_module: srcMod, source_type: srcType, source_id: srcId,
      target_module: tgtMod, target_type: tgtType, target_id: tgtId,
      relationship: 'related'
    }));
  }

  function unlink(linkId, container) {
    if (!confirm('Remove this link?')) return;
    var xhr = new XMLHttpRequest();
    xhr.open('DELETE', '/api/links/' + linkId, true);
    var csrf = (document.cookie.match(/csrf_token=([^;]+)/) || [])[1] || '';
    xhr.setRequestHeader('X-CSRF-Token', decodeURIComponent(csrf));
    xhr.onload = function () {
      if (xhr.status === 200) {
        if (typeof showToast === 'function') showToast('Link removed');
        if (container) {
          var mod = container.dataset.riMod;
          var etype = container.dataset.riEtype;
          if (mod && etype) {
            mount(container, mod, etype, Number(container.dataset.riId),
              {canEdit: container.dataset.riCanEdit === '1'});
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
