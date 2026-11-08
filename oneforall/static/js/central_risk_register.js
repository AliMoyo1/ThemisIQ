const levelColors = { critical: 'var(--bad)', high: '#f97316', medium: 'var(--warn)', low: 'var(--good)' };
const levelBg = { critical: 'var(--bad-soft)', high: 'rgba(249,115,22,0.12)', medium: 'var(--warn-soft)', low: 'var(--good-soft)' };
function safeCount(value) {
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= 0 ? number : 0;
}

async function loadStats() {
  const resp = await fetch('/api/risks/stats');
  const s = await resp.json();
  document.getElementById('riskStats').innerHTML = `
    <div class="card" style="padding:12px 16px;"><div style="font-size:10px;text-transform:uppercase;color:var(--muted);">Total Open</div><div style="font-size:22px;font-weight:700;color:var(--text);margin-top:2px;">${safeCount(s.total)}</div></div>
    <div class="card" style="padding:12px 16px;"><div style="font-size:10px;text-transform:uppercase;color:var(--muted);">Critical</div><div style="font-size:22px;font-weight:700;color:var(--bad);margin-top:2px;">${safeCount(s.by_level?.critical)}</div></div>
    <div class="card" style="padding:12px 16px;"><div style="font-size:10px;text-transform:uppercase;color:var(--muted);">High</div><div style="font-size:22px;font-weight:700;color:#f97316;margin-top:2px;">${safeCount(s.by_level?.high)}</div></div>
    <div class="card" style="padding:12px 16px;"><div style="font-size:10px;text-transform:uppercase;color:var(--muted);">Medium</div><div style="font-size:22px;font-weight:700;color:var(--warn);margin-top:2px;">${safeCount(s.by_level?.medium)}</div></div>
    <div class="card" style="padding:12px 16px;"><div style="font-size:10px;text-transform:uppercase;color:var(--muted);">Low</div><div style="font-size:22px;font-weight:700;color:var(--good);margin-top:2px;">${safeCount(s.by_level?.low)}</div></div>
  `;
  renderHeatMap(s.heat_map);
}

function renderHeatMap(data) {
  const grid = document.getElementById('heatMap');
  let html = '';
  const cells = Array.isArray(data) ? data : [];
  for (let l = 5; l >= 1; l--) {
    for (let i = 1; i <= 5; i++) {
      const cell = cells.find(d => d.likelihood === l && d.impact === i);
      const count = safeCount(cell?.count);
      const score = l * i;
      const bg = score >= 20 ? 'rgba(248,113,113,0.6)' : score >= 12 ? 'rgba(249,115,22,0.5)' : score >= 6 ? 'rgba(251,191,36,0.4)' : 'rgba(74,222,128,0.3)';
      html += '<div style="aspect-ratio:1;display:flex;align-items:center;justify-content:center;border-radius:4px;background:' + bg + ';font-size:11px;font-weight:600;color:var(--text);">' + (count || '') + '</div>';
    }
  }
  grid.innerHTML = html;
}

let _riskPage = 1;

async function loadRisks(page) {
  _riskPage = (page !== undefined) ? page : 1;
  const module = document.getElementById('filterModule').value;
  const status = document.getElementById('filterStatus').value;
  const params = new URLSearchParams();
  if (module) params.set('module', module);
  if (status) params.set('status', status);
  params.set('page', _riskPage);
  params.set('per_page', '50');
  const resp = await fetch('/api/risks?' + params.toString());
  const data = await resp.json();
  const risks = data.items || [];

  const tbody = document.getElementById('riskBody');
  if (!risks.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="padding:40px;text-align:center;color:var(--muted);">No risks found</td></tr>';
    document.getElementById('riskPager').innerHTML = '';
    return;
  }

  tbody.innerHTML = risks.map(r => `
    <tr style="border-bottom:1px solid var(--border-soft);">
      <td style="padding:10px 14px;"><div style="font-weight:500;font-size:13px;color:var(--text);">${esc(r.title)}</div><div style="font-size:11px;color:var(--muted);margin-top:2px;">${esc(r.category)}</div></td>
      <td style="padding:10px 14px;text-align:center;"><span style="display:inline-block;padding:3px 10px;border-radius:10px;font-size:12px;font-weight:700;background:${Object.hasOwn(levelBg, r.risk_level) ? levelBg[r.risk_level] : 'var(--surface3)'};color:${Object.hasOwn(levelColors, r.risk_level) ? levelColors[r.risk_level] : 'var(--muted)'};">${esc(r.risk_score)}</span></td>
      <td style="padding:10px 14px;font-size:12px;text-transform:uppercase;color:var(--muted);">${esc(r.source_module||'—')}</td>
      <td style="padding:10px 14px;font-size:12px;color:var(--text);">${esc(r.treatment)}</td>
      <td style="padding:10px 14px;font-size:12px;color:var(--text);">${esc(r.owner_name||'Unassigned')}</td>
      <td style="padding:10px 14px;"><span style="padding:2px 8px;border-radius:4px;font-size:11px;background:var(--surface3);color:var(--muted);">${esc(r.status)}</span></td>
    </tr>
  `).join('');

  const pager = document.getElementById('riskPager');
  pager.replaceChildren();
  const pages = safeCount(data.pages);
  if (pages <= 1) return;
  const btnStyle = 'padding:4px 10px;border-radius:4px;border:1px solid var(--border);background:var(--surface2);color:var(--text);cursor:pointer;font-size:12px;';
  const previous = document.createElement('button');
  previous.textContent = 'Previous';
  previous.style.cssText = btnStyle;
  previous.disabled = _riskPage <= 1;
  previous.addEventListener('click', () => loadRisks(_riskPage - 1));
  const label = document.createElement('span');
  label.textContent = `Page ${safeCount(data.page)} of ${pages} — ${safeCount(data.total)} risks`;
  const next = document.createElement('button');
  next.textContent = 'Next';
  next.style.cssText = btnStyle;
  next.disabled = _riskPage >= pages;
  next.addEventListener('click', () => loadRisks(_riskPage + 1));
  pager.append(previous, label, next);
}

function openNewRisk() { ModalManager.open('newRiskModal'); }

async function createRisk(e) {
  e.preventDefault();
  const body = {
    title: document.getElementById('rTitle').value,
    description: document.getElementById('rDesc').value,
    likelihood: parseInt(document.getElementById('rLikelihood').value),
    impact: parseInt(document.getElementById('rImpact').value),
    source_module: document.getElementById('rModule').value,
    treatment: document.getElementById('rTreatment').value,
    category: document.getElementById('rCategory').value,
  };
  const resp = await fetch('/api/risks', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
  if (resp.ok) {
    ModalManager.close('newRiskModal');
    document.getElementById('riskForm').reset();
    loadRisks();
    loadStats();
  }
}

function esc(s) { const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('filterModule')?.addEventListener('change', () => loadRisks());
  document.getElementById('filterStatus')?.addEventListener('change', () => loadRisks());
  document.getElementById('openNewRiskBtn')?.addEventListener('click', openNewRisk);
  document.getElementById('closeNewRiskBtn')?.addEventListener('click', () => ModalManager.close('newRiskModal'));
  document.getElementById('riskForm')?.addEventListener('submit', createRisk);
  loadStats();
  loadRisks();
});
