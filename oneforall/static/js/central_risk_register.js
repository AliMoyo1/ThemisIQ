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
    <div class="card" data-s="sfdf20b9"><div data-s="s94ea384">Total Open</div><div data-s="s745dcfb">${safeCount(s.total)}</div></div>
    <div class="card" data-s="sfdf20b9"><div data-s="s94ea384">Critical</div><div data-s="sb3437ed">${safeCount(s.by_level?.critical)}</div></div>
    <div class="card" data-s="sfdf20b9"><div data-s="s94ea384">High</div><div data-s="s0b9497f">${safeCount(s.by_level?.high)}</div></div>
    <div class="card" data-s="sfdf20b9"><div data-s="s94ea384">Medium</div><div data-s="s12a73a9">${safeCount(s.by_level?.medium)}</div></div>
    <div class="card" data-s="sfdf20b9"><div data-s="s94ea384">Low</div><div data-s="s4513d46">${safeCount(s.by_level?.low)}</div></div>
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
      html += '<div data-sv="aspect-ratio:1;display:flex;align-items:center;justify-content:center;border-radius:4px;background:' + bg + ';font-size:11px;font-weight:600;color:var(--text);">' + (count || '') + '</div>';
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
    tbody.innerHTML = '<tr><td colspan="6" data-s="sc0add8c">No risks found</td></tr>';
    document.getElementById('riskPager').innerHTML = '';
    return;
  }

  tbody.innerHTML = risks.map(r => `
    <tr data-s="sc91b18f">
      <td data-s="s9944357"><div data-s="s1ae31e3">${esc(r.title)}</div><div data-s="s3823a5b">${esc(r.category)}</div></td>
      <td data-s="s9c0b302"><span data-sv="display:inline-block;padding:3px 10px;border-radius:10px;font-size:12px;font-weight:700;background:${Object.hasOwn(levelBg, r.risk_level) ? levelBg[r.risk_level] : 'var(--surface3)'};color:${Object.hasOwn(levelColors, r.risk_level) ? levelColors[r.risk_level] : 'var(--muted)'};">${esc(r.risk_score)}</span></td>
      <td data-s="s6a6318d">${esc(r.source_module||'—')}</td>
      <td data-s="s0a1e521">${esc(r.treatment)}</td>
      <td data-s="s0a1e521">${esc(r.owner_name||'Unassigned')}</td>
      <td data-s="s9944357"><span data-s="s046e0ea">${esc(r.status)}</span></td>
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
