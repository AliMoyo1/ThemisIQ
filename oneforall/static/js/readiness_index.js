// Data readiness (moved from its template for strict script policy).
(function () {
  'use strict';

  function esc(s) {
    if (s == null) return '';
    // Quotes too: some values are written into attributes.
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function qs() {
    var params = [];
    var m = document.getElementById('rdFilterModule').value;
    var s = document.getElementById('rdFilterSeverity').value;
    var st = document.getElementById('rdFilterStatus').value;
    if (m) params.push('module=' + encodeURIComponent(m));
    if (s) params.push('severity=' + encodeURIComponent(s));
    if (st) params.push('status=' + encodeURIComponent(st));
    return params.length ? '?' + params.join('&') : '';
  }

  async function loadFindings() {
    var tbody = document.getElementById('rdTableBody');
    tbody.innerHTML = '<tr><td colspan="6" class="rd-empty">Loading…</td></tr>';
    try {
      var data = await ApiClient.request('/readiness/api/findings' + qs());
      var findings = data.findings || [];
      var skipped = (data.rule_coverage || []).filter(function (rule) {
        return rule.state === 'skipped_unlicensed';
      });
      var modulesSkipped = Array.from(new Set(skipped.map(function (rule) { return rule.module; })));
      document.getElementById('rdCoverageStatus').textContent = modulesSkipped.length ?
        'Not inspected because the module is not licensed: ' + modulesSkipped.join(', ') +
        '. An empty findings list does not mean those modules are healthy.' : '';
      if (!findings.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="rd-empty">No issues found for this filter.</td></tr>';
        return;
      }
      var modules = {};
      findings.forEach(function (f) { modules[f.module] = true; });
      var moduleSel = document.getElementById('rdFilterModule');
      var current = moduleSel.value;
      moduleSel.innerHTML = '<option value="">All modules</option>' +
        Object.keys(modules).sort().map(function (m) {
          return '<option value="' + esc(m) + '"' + (m === current ? ' selected' : '') + '>' + esc(m) + '</option>';
        }).join('');

      tbody.innerHTML = findings.map(function (f) {
        var actions = '';
        if (f.status === 'open') {
          actions = '<button type="button" class="btn btn-ghost" style="font-size:11px;padding:4px 10px" data-ack="' + f.id + '">Acknowledge</button>';
        } else {
          actions = '<button type="button" class="btn btn-ghost" style="font-size:11px;padding:4px 10px" data-reopen="' + f.id + '">Reopen</button>';
        }
        var link = f.remediation_route
          ? '<a href="' + esc(f.remediation_route) + '" style="display:block;margin-top:2px;font-size:11px">Open record &rarr;</a>' : '';
        return '<tr>' +
          '<td><span class="rd-sev rd-sev-' + esc(f.severity) + '">' + esc(f.severity) + '</span></td>' +
          '<td>' + esc(f.module) + '</td>' +
          '<td>' + esc(f.message) + link + '</td>' +
          '<td>' + esc((f.detected_at || '').slice(0, 10)) + '</td>' +
          '<td>' + esc(f.status) + '</td>' +
          '<td>' + actions + '</td>' +
          '</tr>';
      }).join('');

      Array.prototype.forEach.call(tbody.querySelectorAll('[data-ack]'), function (btn) {
        btn.addEventListener('click', function () { acknowledge(parseInt(btn.getAttribute('data-ack'), 10)); });
      });
      Array.prototype.forEach.call(tbody.querySelectorAll('[data-reopen]'), function (btn) {
        btn.addEventListener('click', async function () {
          btn.disabled = true;
          try {
            await ApiClient.request('/readiness/api/findings/' + btn.getAttribute('data-reopen') + '/reopen', { method: 'POST' });
            loadFindings();
          } catch (e) {
            if (window.showToast) showToast((e && e.detail) || 'Reopen failed.', 'error');
            btn.disabled = false;
          }
        });
      });
    } catch (err) {
      tbody.innerHTML = '<tr><td colspan="6" class="rd-empty">Could not load findings' +
        (err && err.detail ? ': ' + esc(err.detail) : '.') + '</td></tr>';
    }
  }

  async function acknowledge(id) {
    var reason = window.prompt('Reason (required):');
    if (!reason || !reason.trim()) return;
    var suppressDays = window.prompt('Suppress for how many days? Leave blank to just acknowledge (no re-surfacing timer).');
    var body = { reason: reason.trim() };
    if (suppressDays && suppressDays.trim()) {
      var days = parseInt(suppressDays.trim(), 10);
      if (!isNaN(days) && days > 0) {
        var until = new Date(Date.now() + days * 86400000);
        body.expires_at = until.toISOString();
      }
    }
    try {
      await ApiClient.request('/readiness/api/findings/' + id + '/acknowledge', {
        method: 'POST', body: body,
      });
      loadFindings();
    } catch (e) {
      if (window.showToast) showToast((e && e.detail) || 'Acknowledge failed.', 'error');
    }
  }

  document.getElementById('rdFilterModule').addEventListener('change', loadFindings);
  document.getElementById('rdFilterSeverity').addEventListener('change', loadFindings);
  document.getElementById('rdFilterStatus').addEventListener('change', loadFindings);

  document.getElementById('rdExportBtn').addEventListener('click', function () {
    window.location.href = '/readiness/api/findings/export' + qs();
  });

  document.getElementById('rdScanBtn').addEventListener('click', async function () {
    var btn = document.getElementById('rdScanBtn');
    btn.disabled = true;
    btn.textContent = 'Scanning…';
    try {
      var scan = await ApiClient.request('/readiness/api/scan', { method: 'POST' });
      var failed = (scan.counts && scan.counts.failed_rules) || [];
      var skipped = (scan.counts && scan.counts.skipped) || 0;
      if (window.showToast) showToast(
        failed.length ? 'Scan completed with ' + failed.length + ' rule error(s): ' + failed.join(', ') :
          skipped ? 'Scan complete. ' + skipped + ' rule(s) skipped because modules are unlicensed.' :
            'Scan complete.',
        failed.length ? 'error' : 'success'
      );
      loadFindings();
    } catch (e) {
      if (window.showToast) showToast((e && e.detail) || 'Scan failed.', 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Scan now';
    }
  });

  loadFindings();
})();
