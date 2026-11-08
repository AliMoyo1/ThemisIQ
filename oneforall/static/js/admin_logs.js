let currentPage = 1;
let totalPages = 1;

function getFilters() {
  return {
    module: document.getElementById('filterModule').value,
    action: document.getElementById('filterAction').value,
    user: document.getElementById('filterUser').value,
    from: document.getElementById('filterFrom').value,
    to: document.getElementById('filterTo').value,
  };
}

function fmtDate(ds) {
  if (!ds) return '—';
  const d = new Date(ds.length === 10 ? ds + 'T00:00:00' : ds);
  if (isNaN(d)) return ds;
  return d.toLocaleDateString('en-GB', {day:'numeric', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit'});
}

function buildQueryString(filters, page) {
  const params = new URLSearchParams();
  if (filters.module) params.set('module', filters.module);
  if (filters.action) params.set('action', filters.action);
  if (filters.user) params.set('user', filters.user);
  if (filters.from) params.set('from', filters.from);
  if (filters.to) params.set('to', filters.to);
  params.set('page', page);
  params.set('per_page', '50');
  return params.toString();
}

async function loadLogs(page) {
  currentPage = page || 1;
  const filters = getFilters();
  const qs = buildQueryString(filters, currentPage);

  try {
    const resp = await fetch('/admin/api/logs?' + qs);
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();

    totalPages = data.pages || 1;

    // Populate module dropdown if first load
    const sel = document.getElementById('filterModule');
    if (sel.options.length <= 1 && data.modules) {
      data.modules.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m.charAt(0).toUpperCase() + m.slice(1);
        sel.appendChild(opt);
      });
    }

    renderLogs(data.logs);
    updatePagination(data);
  } catch (err) {
    const tbody = document.getElementById('logBody');
    tbody.replaceChildren();
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 6;
    cell.style.cssText = 'padding:30px; text-align:center; color:var(--bad);';
    cell.textContent = 'Failed to load logs: ' + err.message;
    row.appendChild(cell);
    tbody.appendChild(row);
  }
}

function renderLogs(logs) {
  const tbody = document.getElementById('logBody');
  if (!logs || logs.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" style="padding:40px; text-align:center; color:var(--muted);">No audit log entries found</td></tr>';
    return;
  }

  const moduleColors = {
    platform: '#94a3b8',
    aria: '#6c63ff',
    sentinel: '#10b981',
    grid: '#f59e0b',
    bcm: '#ef4444',
  };

  tbody.innerHTML = logs.map(log => {
    const ts = log.created_at ? fmtDate(log.created_at) : '—';
    const user = log.full_name || log.username || 'system';
    const mod = log.module || '—';
    const modColor = Object.hasOwn(moduleColors, mod) ? moduleColors[mod] : 'var(--muted)';
    const action = escHtml(log.action || '');
    const details = escHtml((log.details || '').substring(0, 120));
    const ip = log.ip_address || '';

    return `<tr style="border-bottom:1px solid var(--border-soft);">
      <td style="padding:10px 14px; font-size:12px; color:var(--muted); white-space:nowrap;">${escHtml(ts)}</td>
      <td style="padding:10px 14px; font-size:13px; font-weight:500; color:var(--text);">${escHtml(user)}</td>
      <td style="padding:10px 14px;">
        <span style="display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; background:${modColor}22; color:${modColor}; text-transform:uppercase;">${escHtml(mod)}</span>
      </td>
      <td style="padding:10px 14px; font-size:12.5px; color:var(--text);">${action}</td>
      <td style="padding:10px 14px; font-size:12px; color:var(--muted); max-width:250px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${details}">${details}</td>
      <td style="padding:10px 14px; font-size:11px; color:var(--muted); font-family:monospace;">${escHtml(ip)}</td>
    </tr>`;
  }).join('');
}

function updatePagination(data) {
  document.getElementById('pageInfo').textContent =
    `Showing page ${data.page} of ${data.pages} (${data.total} entries)`;
  document.getElementById('btnPrev').disabled = data.page <= 1;
  document.getElementById('btnNext').disabled = data.page >= data.pages;
}

function prevPage() { if (currentPage > 1) loadLogs(currentPage - 1); }
function nextPage() { if (currentPage < totalPages) loadLogs(currentPage + 1); }

function quickFilter(preset) {
  document.getElementById('filterModule').value = '';
  document.getElementById('filterAction').value = '';
  document.getElementById('filterUser').value = '';
  document.getElementById('filterFrom').value = '';
  document.getElementById('filterTo').value = '';
  if (preset === 'login_failed') {
    document.getElementById('filterAction').value = 'login_failed';
  } else if (preset === 'delete') {
    document.getElementById('filterAction').value = 'delete';
  } else if (preset === 'export') {
    document.getElementById('filterAction').value = 'export';
  } else if (preset === 'create') {
    document.getElementById('filterAction').value = 'create';
  } else if (preset === 'today') {
    document.getElementById('filterFrom').value = new Date().toISOString().slice(0, 10);
    document.getElementById('filterTo').value = new Date().toISOString().slice(0, 10);
  } else if (preset === 'week') {
    var d = new Date(); d.setDate(d.getDate() - 7);
    document.getElementById('filterFrom').value = d.toISOString().slice(0, 10);
    document.getElementById('filterTo').value = new Date().toISOString().slice(0, 10);
  }
  loadLogs(1);
}

function clearFilters() {
  document.getElementById('filterModule').value = '';
  document.getElementById('filterAction').value = '';
  document.getElementById('filterUser').value = '';
  document.getElementById('filterFrom').value = '';
  document.getElementById('filterTo').value = '';
  loadLogs(1);
}

function exportCSV() {
  const filters = getFilters();
  const params = new URLSearchParams();
  if (filters.module) params.set('module', filters.module);
  if (filters.action) params.set('action', filters.action);
  if (filters.user) params.set('user', filters.user);
  if (filters.from) params.set('from', filters.from);
  if (filters.to) params.set('to', filters.to);
  window.location.href = '/admin/api/logs/export?' + params.toString();
}

function escHtml(str) {
  const d = document.createElement('div');
  d.textContent = String(str);
  return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

document.addEventListener('DOMContentLoaded', () => {
  for (const id of ['filterModule', 'filterAction', 'filterUser', 'filterFrom', 'filterTo']) {
    document.getElementById(id).addEventListener('change', () => loadLogs(1));
  }
  document.getElementById('clearLogFilters').addEventListener('click', clearFilters);
  document.getElementById('exportLogs').addEventListener('click', exportCSV);
  document.getElementById('btnPrev').addEventListener('click', prevPage);
  document.getElementById('btnNext').addEventListener('click', nextPage);
  document.querySelectorAll('.log-preset').forEach(button => {
    button.addEventListener('click', () => quickFilter(button.dataset.preset));
  });
  loadLogs(1);
});
