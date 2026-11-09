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
      '<div class="ri-panel">' +
        '<div class="ri-heading">Related Items</div>' +
        '<div id="ri-list-' + eid + '" class="ri-list">Loading...</div>' +
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
    el.innerHTML = '<div class="ri-empty">No related items</div>';
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
        ? ' <span class="ri-rel-chip">' + safe(l.relationship) + '</span>'
        : '';
      var unlinkBtn = '';
      if (opts.canEdit && l.direction === 'outgoing' && Number.isSafeInteger(Number(l.link_id))) {
        unlinkBtn = ' <button type="button" data-ri-unlink="' + index + '" aria-label="Remove link to ' + safe(title) +
          '" class="ri-unlink">x</button>';
      }
      return '<div class="ri-row">' +
        '<div>' +
          '<span class="ri-title">' + titleHtml + '</span>' +
          ' <span class="ri-kind">(' + safe(l.module) + ' ' + safe(l.entity_type) + ')</span>' +
          relChip +
        '</div>' +
        unlinkBtn +
      '</div>';
    }).join('');
    el.innerHTML = html || '<div class="ri-empty-plain">No related items</div>';
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
      '<div class="ri-picker">' +
        '<div class="ri-picker-title">Link related item</div>' +
        '<label for="riSearchInput" class="ri-picker-label">Search records you may open</label>' +
        '<input id="riSearchInput" type="text" placeholder="Search by title..." class="ri-picker-input">' +
        '<div id="riSearchResults" aria-live="polite" class="ri-picker-results"></div>' +
        '<div id="riPickerStatus" role="alert" class="ri-picker-status"></div>' +
        '<button type="button" class="ri-cancel">Cancel</button>' +
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
            res.innerHTML = '<div class="ri-picker-none">No results</div>';
            return;
          }
          res.innerHTML = results.map(function (r, index) {
            var safeTitle = safe(r.title || r.subtitle || '');
            return '<div class="ri-hit">' +
              '<div><strong class="ri-hit-title">' + safeTitle + '</strong><br>' +
              '<span class="ri-hit-kind">' + safe(r.module) + ' ' + safe(r.type || '') + '</span></div>' +
              '<button type="button" data-ri-result="' + index + '" ' +
                'class="ri-hit-link">Link</button>' +
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
