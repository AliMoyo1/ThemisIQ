(function () {
  'use strict';

  function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }

  function cardFor(title, state) {
    state = state || { state: 'not_configured', message: 'No data.' };
    var allowed = ['available', 'degraded', 'not_configured', 'forbidden', 'unavailable_in_tier', 'disabled_by_policy'];
    var badgeClass = 'diag-badge-' + (allowed.includes(state.state) ? state.state : 'not_configured');
    var label = (state.state || 'unknown').replace(/_/g, ' ');
    return '<div class="diag-card">' +
      '<div class="diag-card-title">' + esc(title) + '</div>' +
      '<span class="diag-badge ' + badgeClass + '">' + esc(label) + '</span>' +
      (state.message ? '<div class="diag-message">' + esc(state.message) + '</div>' : '') +
      (state.remediation_route && state.remediation_route.charAt(0) === '/' &&
       state.remediation_route.charAt(1) !== '/' ?
        '<div class="diag-message"><a href="' + esc(state.remediation_route) +
        '">Configuration guidance</a></div>' : '') +
      '</div>';
  }

  async function load() {
    var orgGrid = document.getElementById('diagOrgGrid');
    try {
      var data = await ApiClient.request('/api/admin/diagnostics');
      var cards = '';
      cards += cardFor('Database', data.database);
      cards += cardFor('AI Features', data.ai);
      cards += cardFor('Email', data.email);
      cards += '<div class="diag-card"><div class="diag-card-title">Licensed Modules</div>' +
        '<div class="diag-message">' + esc((data.licensed_modules || []).join(', ') || 'None') + '</div></div>';
      orgGrid.innerHTML = cards;
      if (data.request_id) orgGrid.setAttribute('data-request-id', data.request_id);

      if (data.platform) {
        document.getElementById('diagPlatformSection').style.display = '';
        var pf = data.platform;
        var pcards = '';
        pcards += cardFor('Backup Freshness', pf.backup);
        pcards += cardFor('ARIA Preview Worker', pf.aria_preview_worker);
        var schedulerState = { state: pf.scheduler && pf.scheduler.running ? 'available' : 'degraded',
                                message: pf.scheduler ? (pf.scheduler.jobs || []).length + ' job(s) registered' : '' };
        pcards += cardFor('Scheduler', schedulerState);
        var frequencies = Array.isArray(pf.capability_state_frequency) ? pf.capability_state_frequency : [];
        var totals = {};
        frequencies.forEach(function (row) {
          var key = row.area + ' / ' + row.state;
          totals[key] = (totals[key] || 0) + Number(row.count || 0);
        });
        pcards += '<div class="diag-card"><div class="diag-card-title">Capability states (last 30 days)</div>' +
          '<div class="diag-message">' +
          (Object.keys(totals).length ? Object.keys(totals).sort().map(function (key) {
            return '<div>' + esc(key) + ': ' + totals[key] + '</div>';
          }).join('') : 'No state requests recorded, or metrics unavailable.') +
          '</div></div>';
        document.getElementById('diagPlatformGrid').innerHTML = pcards;
      }
    } catch (err) {
      orgGrid.innerHTML = '<div class="diag-card">Could not load diagnostics' +
        (err && err.detail ? ': ' + esc(err.detail) : '.') + '</div>';
    }
  }

  load();
})();
