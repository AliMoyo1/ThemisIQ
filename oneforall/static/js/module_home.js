/* Source-backed specialist home summary. Existing module dashboards stay intact. */
(function () {
  'use strict';
  var module = document.body && document.body.getAttribute('data-module');
  if (!/^(aria|grid|bcm|sentinel|erm|orm)$/.test(module || '')) return;
  var dashboard = document.getElementById('view-dashboard');
  var ariaHeader = module === 'aria' && /^\/aria\/?$/.test(window.location.pathname) ?
    document.querySelector('.premium-dashboard-header') : null;
  if (!dashboard && !ariaHeader) return;
  var root = document.createElement('section');
  root.className = 'connected-module-home';
  root.setAttribute('aria-label', 'Connected module overview');
  root.innerHTML = '<div class="connected-module-head"><strong>Connected overview</strong>' +
    '<span>Live records in your scope</span></div><div class="connected-module-grid" aria-live="polite">Loading...</div>';
  if (dashboard) dashboard.insertBefore(root, dashboard.firstChild);
  else ariaHeader.parentNode.insertBefore(root, ariaHeader.nextSibling);
  var style = document.createElement('style');
  style.textContent = '.connected-module-home{margin:0 0 18px;padding:16px;border:1px solid var(--border);' +
    'background:var(--surface);border-radius:18px}.connected-module-head{display:flex;justify-content:space-between;' +
    'gap:12px;align-items:center;margin-bottom:12px}.connected-module-head span{font-size:12px;color:var(--muted)}' +
    '.connected-module-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}' +
    '.connected-module-card{padding:12px;border:1px solid var(--border);border-radius:12px;' +
    'background:var(--bg);min-width:0}.connected-module-card strong{display:block;font-size:12px}' +
    '.connected-module-card .value{display:block;font-size:25px;font-weight:700;margin:5px 0}' +
    '.connected-module-card small{color:var(--muted);line-height:1.4}' +
    '@media(max-width:900px){.connected-module-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}' +
    '@media(max-width:550px){.connected-module-grid{grid-template-columns:1fr}}';
  document.head.appendChild(style);
  function safe(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }
  window.ApiClient.request('/api/module-home/' + module).then(function (result) {
    var cards = result.cards || {};
    var order = ['act_now', 'portfolio', 'trends', 'quality'];
    root.querySelector('.connected-module-grid').innerHTML = order.map(function (key) {
      var card = cards[key] || {label:key,state:'unavailable'};
      var measured = card.state === 'measured' || card.state === 'partial';
      var number = measured ? safe(card.value) :
        (card.state === 'not_measured' ? 'Not measured' : 'Unavailable');
      var denominator = measured && card.denominator != null ? ' / ' + safe(card.denominator) : '';
      var link = key === 'act_now' ? '/my-work?source=' + encodeURIComponent(module) : '/' + module + '/';
      return '<article class="connected-module-card"><strong>' + safe(card.label) + '</strong>' +
        '<span class="value">' + number + denominator + '</span><small>' + safe(card.note || '') +
        (card.state === 'partial' ? ' Partial source coverage.' : '') + '</small>' +
        '<div><a href="' + safe(link) + '">Open source</a></div></article>';
    }).join('');
  }).catch(function () {
    root.querySelector('.connected-module-grid').textContent =
      'Connected overview is unavailable. Open the module records below.';
  });
})();
