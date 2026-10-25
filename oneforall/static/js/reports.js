const reportConfig = document.getElementById('reportConfig');
const typeLabels = JSON.parse(reportConfig.dataset.labels);
const typeTiers = JSON.parse(reportConfig.dataset.tiers);
var currentRun = null;

function tierChip(type) {
  const board = typeTiers[type] === 'board';
  return `<span style="padding:1px 8px;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;background:${board ? 'var(--text)' : 'var(--surface3)'};color:${board ? 'var(--surface)' : 'var(--muted)'};">${board ? 'Board' : 'Operational'}</span>`;
}

function esc(s) { const d=document.createElement('div'); d.textContent=(s===null||s===undefined)?'':String(s); return d.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

function showNotice(text) {
  const el = document.getElementById('reportNotice');
  el.textContent = text;
  el.style.display = text ? 'block' : 'none';
}

function showTab(tab) {
  document.getElementById('tabRuns').style.display = tab === 'runs' ? 'block' : 'none';
  document.getElementById('tabDefinitions').style.display = tab === 'definitions' ? 'block' : 'none';
  if (tab === 'definitions') loadDefinitions();
  else loadRuns();
}

async function readJson(resp) {
  try { return await resp.json(); } catch (e) { return {}; }
}

async function loadDefinitions() {
  const resp = await fetch('/api/reports/definitions');
  if (!resp.ok) { document.getElementById('defsBody').innerHTML = '<tr><td colspan="5" style="padding:40px;text-align:center;color:var(--bad);">The definitions could not be read just now.</td></tr>'; return; }
  const defs = await resp.json();
  const tbody = document.getElementById('defsBody');
  if (!defs.length) { tbody.innerHTML = '<tr><td colspan="5" style="padding:40px;text-align:center;color:var(--muted);">No report definitions</td></tr>'; return; }
  tbody.innerHTML = defs.map(d => `
    <tr style="border-bottom:1px solid var(--border-soft);">
      <td style="padding:10px 14px;"><div style="font-weight:500;font-size:13px;">${esc(d.name)}</div><div style="font-size:11px;color:var(--muted);margin-top:2px;">${esc(d.description||'')}</div></td>
      <td style="padding:10px 14px;font-size:12px;color:var(--muted);">${esc(typeLabels[d.report_type]||d.report_type)} ${tierChip(d.report_type)}</td>
      <td style="padding:10px 14px;font-size:12px;color:var(--muted);">${d.schedule ? 'Not automated yet' : 'Run on request'}</td>
      <td style="padding:10px 14px;text-align:center;"><span style="padding:2px 8px;border-radius:4px;font-size:11px;background:${d.is_active?'var(--good-soft)':'var(--surface3)'};color:${d.is_active?'var(--good)':'var(--muted)'};">${d.is_active?'Active':'Disabled'}</span></td>
      <td style="padding:10px 14px;text-align:center;"><button class="btn btn-primary" style="font-size:11px;padding:3px 10px;" data-report-action="run" data-run-id="${Number(d.id)}">Run Now</button></td>
    </tr>
  `).join('');
}

function when(dt) {
  if (!dt) return '';
  const s = String(dt).replace(' ', 'T');
  return /Z|[+-]\d\d:?\d\d$/.test(s) ? s : s + 'Z';
}

function timeAgo(dt) {
  if (!dt) return 'n/a';
  const diff = (Date.now() - new Date(when(dt)).getTime()) / 1000;
  if (isNaN(diff)) return esc(dt);
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff/60) + 'm ago';
  if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
  return Math.floor(diff/86400) + 'd ago';
}

async function loadRuns() {
  const resp = await fetch('/api/reports/runs');
  const tbody = document.getElementById('runsBody');
  if (!resp.ok) { tbody.innerHTML = '<tr><td colspan="5" style="padding:40px;text-align:center;color:var(--bad);">The saved reports could not be read just now. This is not an empty list.</td></tr>'; return; }
  const runs = await resp.json();
  if (!runs.length) { tbody.innerHTML = '<tr><td colspan="5" style="padding:40px;text-align:center;color:var(--muted);">No reports generated yet. Use Quick Generate above.</td></tr>'; return; }
  tbody.innerHTML = runs.map(r => {
    const ok = r.status === 'completed';
    const kind = r.frozen ? 'Saved as generated' : (ok ? 'Legacy: not frozen' : '');
    return `
    <tr style="border-bottom:1px solid var(--border-soft);">
      <td style="padding:10px 14px;font-weight:500;font-size:13px;">${esc(r.report_name||'Ad-hoc')}${r.previous_run_id ? `<div style="font-size:11px;color:var(--muted);font-weight:400;">Run again after #${Number(r.previous_run_id)}</div>` : ''}</td>
      <td style="padding:10px 14px;font-size:12px;color:var(--muted);">${esc(typeLabels[r.report_type]||r.report_type||'n/a')} ${tierChip(r.report_type)}</td>
      <td style="padding:10px 14px;font-size:12px;color:var(--muted);">${timeAgo(r.completed_at||r.started_at)}</td>
      <td style="padding:10px 14px;text-align:center;"><span style="padding:2px 8px;border-radius:4px;font-size:11px;background:${ok?'var(--good-soft)':'var(--warn-soft)'};color:${ok?'var(--good)':'var(--warn)'};">${esc(r.status)}</span>${kind ? `<div style="font-size:10px;color:var(--muted);margin-top:2px;">${kind}</div>` : ''}</td>
      <td style="padding:10px 14px;text-align:center;">${ok ? `<button class="btn btn-secondary" style="font-size:11px;padding:3px 10px;" data-report-action="view" data-run-id="${Number(r.id)}">View</button>` : ''}</td>
    </tr>`;
  }).join('');
}

async function loadStats() {
  const [dResp, rResp] = await Promise.all([fetch('/api/reports/definitions'), fetch('/api/reports/runs')]);
  const el = document.getElementById('reportStats');
  if (!dResp.ok || !rResp.ok) { el.innerHTML = ''; return; }
  const defs = await dResp.json();
  const runs = await rResp.json();
  const boardRuns = runs.filter(r => typeTiers[r.report_type] === 'board').length;
  el.innerHTML = `
    <div class="card" style="padding:12px 16px;"><div style="font-size:10px;text-transform:uppercase;color:var(--muted);">Definitions</div><div style="font-size:22px;font-weight:700;color:var(--text);margin-top:2px;">${defs.length}</div></div>
    <div class="card" style="padding:12px 16px;"><div style="font-size:10px;text-transform:uppercase;color:var(--muted);">Board runs</div><div style="font-size:22px;font-weight:700;color:var(--text);margin-top:2px;">${boardRuns}</div></div>
    <div class="card" style="padding:12px 16px;"><div style="font-size:10px;text-transform:uppercase;color:var(--muted);">Total Runs</div><div style="font-size:22px;font-weight:700;color:var(--text);margin-top:2px;">${runs.length}</div></div>
  `;
}

function openNewReport() { ModalManager.open('newReportModal'); }

async function createReport(e) {
  e.preventDefault();
  const body = {
    name: document.getElementById('rptName').value,
    description: document.getElementById('rptDesc').value,
    report_type: document.getElementById('rptType').value,
    modules: document.getElementById('rptModules').value,
  };
  const resp = await fetch('/api/reports/definitions', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
  if (resp.ok) {
    ModalManager.close('newReportModal');
    document.getElementById('reportForm').reset();
    loadDefinitions(); loadStats();
    showTab('definitions');
  } else {
    showNotice((await readJson(resp)).error || 'The report definition could not be created.');
  }
}

async function runReport(defId) {
  showNotice('');
  const resp = await fetch(`/api/reports/${defId}/run`, { method:'POST', headers:{'Content-Type':'application/json'} });
  const data = await readJson(resp);
  if (!resp.ok) { showNotice(data.error || 'The report could not be generated.'); return; }
  loadRuns(); loadStats();
  viewRun(data.run_id);
}

async function quickRun(type) {
  showNotice('');
  const resp = await fetch('/api/reports/quick-run', {
    method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ report_type: type })
  });
  const data = await readJson(resp);
  if (!resp.ok) { showNotice(data.error || 'The report could not be generated.'); return; }
  loadRuns(); loadStats();
  viewRun(data.run_id);
}

async function viewRun(runId) {
  showNotice('');
  const resp = await fetch(`/api/reports/runs/${runId}`);
  const data = await readJson(resp);
  if (!resp.ok) { showNotice(data.error || 'This report could not be opened.'); return; }
  viewRunData(data);
}

async function rerunCurrent() {
  if (!currentRun) return;
  showNotice('');
  const resp = await fetch(`/api/reports/runs/${currentRun.run_id}/rerun`, { method:'POST', headers:{'Content-Type':'application/json'} });
  const data = await readJson(resp);
  if (!resp.ok) { showNotice(data.error || 'The report could not be generated again.'); return; }
  loadRuns(); loadStats();
  viewRun(data.run_id);
}

function exportCurrent() {
  if (currentRun && currentRun.frozen) window.location.href = `/api/reports/runs/${currentRun.run_id}/export`;
}

/* The document of a frozen run: a PDF or workbook with a cover, charts and a footer, or the print view. */
function documentOf(runId, format) {
  if (runId) window.location.href = `/api/reports/runs/${Number(runId)}/document?format=${format}`;
}
function printRun(runId) {
  if (runId) window.open(`/reports/runs/${Number(runId)}/print`, '_blank', 'noopener');
}
function documentCurrent(format) {
  if (currentRun && currentRun.frozen) documentOf(currentRun.run_id, format);
}
function printCurrent() {
  if (currentRun && currentRun.frozen) printRun(currentRun.run_id);
}

/* ── Rendering a frozen run ──────────────────────────────────────────── */

function humanize(k) { return String(k).replace(/_/g, ' ').replace(/^./, c => c.toUpperCase()); }
const NA = '<span style="color:var(--muted);">Not available</span>';

function isScalar(v) { return v === null || typeof v !== 'object'; }

function renderScalar(v) {
  if (v === null || v === undefined) return NA;
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  return esc(v);
}

function renderTable(rows) {
  const cols = [];
  rows.forEach(r => Object.keys(r).forEach(k => { if (isScalar(r[k]) && cols.indexOf(k) < 0) cols.push(k); }));
  if (!cols.length) return '';
  return `<div style="overflow-x:auto;margin-bottom:12px;"><table style="width:100%;border-collapse:collapse;font-size:12px;">
    <thead><tr>${cols.map(c => `<th scope="col" style="text-align:left;padding:6px 8px;border-bottom:1px solid var(--border);color:var(--muted);font-weight:600;">${esc(humanize(c))}</th>`).join('')}</tr></thead>
    <tbody>${rows.map(r => `<tr>${cols.map(c => `<td style="padding:6px 8px;border-bottom:1px solid var(--border-soft);">${renderScalar(r[c])}</td>`).join('')}</tr>`).join('')}</tbody>
  </table></div>`;
}

function renderValue(v, depth) {
  if (isScalar(v)) return renderScalar(v);
  if (Array.isArray(v)) {
    if (!v.length) return '<div style="font-size:12px;color:var(--muted);margin-bottom:12px;">None.</div>';
    if (v.every(i => i && typeof i === 'object' && !Array.isArray(i))) return renderTable(v);
    return `<div style="font-size:12px;margin-bottom:12px;">${v.map(i => renderScalar(i)).join(', ')}</div>`;
  }
  return renderObject(v, depth);
}

function renderObject(o, depth) {
  const scalars = Object.keys(o).filter(k => isScalar(o[k]));
  const nested = Object.keys(o).filter(k => !isScalar(o[k]));
  let html = '';
  if (scalars.length) {
    html += `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px;">${
      scalars.map(k => `<div style="padding:10px 12px;border-radius:8px;background:var(--surface2);">
        <div style="font-size:10px;color:var(--muted);text-transform:uppercase;">${esc(humanize(k))}</div>
        <div style="font-size:18px;font-weight:700;margin-top:4px;">${renderScalar(o[k])}</div></div>`).join('')}</div>`;
  }
  nested.forEach(k => {
    const level = Math.min(depth + 3, 5);
    html += `<h${level} style="font-size:12px;font-weight:600;color:var(--muted);margin:12px 0 8px;text-transform:uppercase;">${esc(typeLabels[k] || humanize(k))}</h${level}>` + renderValue(o[k], depth + 1);
  });
  return html;
}

function renderFacts(snap) {
  const run = snap.run || {}, scope = snap.scope || {};
  const rows = [
    ['Report', `${run.type_label || ''} (definition version ${run.definition_version || ''})`],
    ['Generated', `${run.generated_at || ''} UTC by ${(run.generated_by || {}).name || 'unknown'}`],
    ['Organization', scope.org_name || ''],
    ['Scope', scope.label || ''],
    ['Period', (snap.period || {}).note || ''],
    ['Complete', snap.complete ? 'Every source was read.' : 'No. A source could not be read; its figures are blank, not zero.'],
    ['Decision status at generation', (snap.decision_status || {}).text || ''],
  ];
  return `<dl style="display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;font-size:12px;margin:0 0 16px;">${
    rows.map(r => `<dt style="color:var(--muted);">${esc(r[0])}</dt><dd style="margin:0;">${esc(r[1])}</dd>`).join('')}</dl>`;
}

function renderChanges(ch) {
  if (!ch) return '';
  const head = `<div style="font-size:12px;margin-bottom:8px;"><strong>Since run #${Number(ch.previous_run_id)}</strong>` +
    (ch.previous_generated_at ? ` (${esc(ch.previous_generated_at)} UTC)` : '') +
    `: ${Number(ch.changed)} figure${ch.changed === 1 ? '' : 's'} changed, ${Number(ch.unchanged)} unchanged.` +
    (ch.scope_changed ? ' The scope is not the same as then.' : '') +
    (ch.definition_changed ? ' The report definition has changed.' : '') +
    ` <button type="button" class="btn btn-secondary" style="font-size:11px;padding:2px 8px;" data-report-action="view" data-run-id="${Number(ch.previous_run_id)}">Open that run</button></div>`;
  const rows = (ch.changes || []).slice(0, 20).map(c => ({ Figure: c.label, Was: c.was, Now: c.now, Change: c.delta }));
  return `<section aria-label="Changes since the previous run" style="margin-bottom:16px;">${head}${rows.length ? renderTable(rows) : ''}</section>`;
}

function renderLimitations(snap) {
  const items = (snap.limitations || []).concat((snap.exclusions || []).map(e => 'Left out: ' + e));
  if (!items.length) return '';
  return `<section aria-label="What this report leaves out" style="margin:16px 0;"><h3 style="font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;margin:0 0 6px;">What this report cannot tell you</h3>
    <ul style="margin:0;padding-left:18px;font-size:12px;line-height:1.6;">${items.map(i => `<li>${esc(i)}</li>`).join('')}</ul></section>`;
}

const SOURCE_STATE = { read: 'Read', not_in_scope: 'Not open to the person who generated it', unavailable: 'Could not be read' };

function renderSources(snap) {
  const src = snap.sources || [];
  if (!src.length) return '';
  const inputs = snap.inputs || {};
  const rows = src.map(s => {
    const got = inputs[s.source];
    const count = got && Array.isArray(got.ids) ? got.ids.length : 0;
    const kept = got ? `${count} identifier${count === 1 ? '' : 's'} kept${got.truncated ? ' (list cut at the limit)' : ''}` : '';
    const revision = got ? (got.revision_state === 'source_recorded' ? 'Source version or change time' : 'No revision recorded') : '';
    return { Source: s.label, 'What happened': SOURCE_STATE[s.state] || s.state, Records: s.records,
             'Identifiers stored': kept, 'Revision detail': revision };
  });
  const details = src.map(s => {
    const got = inputs[s.source];
    if (!got || !Array.isArray(got.ids) || !got.ids.length) return '';
    const versions = new Map((got.revisions || []).map(v => [String(v.id), v]));
    const records = got.ids.slice(0, 50).map(id => {
      const version = versions.get(String(id)) || {};
      return { ID: id, Version: version.version != null ? version.version : 'Not recorded',
               'Last recorded change': version.last_recorded_change != null ? version.last_recorded_change : 'Not recorded' };
    });
    return `<details style="margin:8px 0;"><summary style="cursor:pointer;font-size:12px;">${esc(s.label)}: view first ${records.length} recorded inputs</summary>` +
      `${renderTable(records)}<p class="gc-muted" style="font-size:11px;">Download CSV for the full frozen identifier list. A recorded timestamp may not capture every edit.</p></details>`;
  }).join('');
  return `<section aria-label="Sources read" style="margin-top:16px;"><h3 style="font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;margin:0 0 6px;">Sources read</h3>${renderTable(rows)}${details}</section>`;
}

/* A note or a dispute sits beside the figure it is about. The saved figure is never edited. */
function renderNotes(data) {
  const box = document.getElementById('viewerNotes');
  if (!data.frozen) { box.innerHTML = ''; return; }
  const notes = data.notes || [];
  const figures = data.figures || [];
  const list = notes.length
    ? `<ul style="margin:0 0 10px;padding-left:18px;font-size:12px;line-height:1.6;">${notes.map(n =>
        `<li><strong>${n.kind === 'dispute' ? 'Disputed' : 'Note'}</strong>${n.figure ? ' (' + esc(humanize(n.figure)) + ')' : ''}: ${esc(n.body)}
         <span style="color:var(--muted);">${esc(n.author_name || '')}, ${esc(String(n.created_at || '').slice(0, 16))}</span></li>`).join('')}</ul>`
    : '<p style="font-size:12px;color:var(--muted);margin:0 0 10px;">No notes or disputes yet.</p>';
  box.innerHTML = `<section aria-label="Notes and disputes" style="margin-top:16px;">
    <h3 style="font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;margin:0 0 6px;">Notes and disputes</h3>
    ${list}
    <form id="noteForm" style="display:grid;gap:8px;max-width:560px;">
      <label style="font-size:12px;color:var(--muted);">Kind
        <select id="noteKind" style="display:block;margin-top:2px;padding:6px 8px;border:1px solid var(--border);border-radius:6px;background:var(--surface2);color:var(--text);">
          <option value="note">Note</option><option value="dispute">Dispute a figure</option></select></label>
      <label style="font-size:12px;color:var(--muted);">Figure (optional)
        <select id="noteFigure" style="display:block;margin-top:2px;padding:6px 8px;border:1px solid var(--border);border-radius:6px;background:var(--surface2);color:var(--text);">
          <option value="">This report as a whole</option>${figures.map(f => `<option value="${esc(f)}">${esc(humanize(f))}</option>`).join('')}</select></label>
      <label style="font-size:12px;color:var(--muted);">What you want to record
        <textarea id="noteBody" rows="3" maxlength="1000" required style="display:block;width:100%;margin-top:2px;padding:6px 8px;border:1px solid var(--border);border-radius:6px;background:var(--surface2);color:var(--text);"></textarea></label>
      <div><button type="submit" class="btn btn-secondary">Add to this run</button>
        <span style="font-size:11px;color:var(--muted);margin-left:8px;">The saved figures do not change.</span></div>
    </form></section>`;
  document.getElementById('noteForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    showNotice('');
    const resp = await fetch(`/api/reports/runs/${data.run_id}/notes`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({kind: document.getElementById('noteKind').value,
                            figure: document.getElementById('noteFigure').value,
                            body: document.getElementById('noteBody').value})
    });
    const out = await readJson(resp);
    if (!resp.ok) { showNotice(out.error || 'The note could not be saved.'); return; }
    viewRun(data.run_id);
  });
}

function renderGovernance(data) {
  const box = document.getElementById('viewerGovernance');
  if (!data.frozen) { box.textContent = ''; return; }
  const signoffs = data.signoffs || [];
  const shares = data.shares || [];
  const retention = data.retention || {};
  const formStyle = 'display:grid;gap:8px;max-width:560px;margin:10px 0 18px;';
  const inputStyle = 'padding:7px;border:1px solid var(--border);border-radius:6px;background:var(--surface2);color:var(--text);';
  const attrEsc = value => esc(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  box.innerHTML = `<section aria-label="Report review and sharing" style="margin-top:20px;border-top:1px solid var(--border);padding-top:16px;">
    <h3 style="font-size:14px;margin:0 0 8px;">Review, sharing and retention</h3>
    <p style="font-size:12px;color:var(--muted);">The snapshot is frozen. Access is checked again when a recipient opens it. A sign-off records a human decision beside the saved figures.</p>
    <div style="font-size:12px;margin-bottom:10px;"><strong>Review:</strong> ${esc(data.signoff_state || 'not_reviewed')}</div>
    ${signoffs.length ? `<ul style="font-size:12px;padding-left:18px;">${signoffs.map(s =>
      `<li>${esc(s.decision)} by user #${Number(s.signer_id)} on ${esc(s.signed_at || '')}: ${esc(s.reason)}</li>`).join('')}</ul>` : ''}
    ${data.can_signoff ? `<form id="reportSignoffForm" style="${formStyle}">
      <label>Decision <select id="reportSignoffDecision" style="${inputStyle}"><option value="approved">Approve</option><option value="rejected">Reject</option></select></label>
      <label>Reason <textarea id="reportSignoffReason" minlength="10" maxlength="2000" required style="${inputStyle}"></textarea></label>
      ${(data.snapshot || {}).narrative ? '<label><input id="reportNarrativeReviewed" type="checkbox"> I reviewed the draft AI narrative and its source figures</label>' : ''}
      <button type="submit" class="btn btn-primary">Record independent decision</button></form>` : ''}
    ${data.can_share ? `<form id="reportShareForm" style="${formStyle}">
      <label>Share with a colleague in this organization <input id="reportShareEmail" type="email" required style="${inputStyle}" placeholder="colleague@example.com"></label>
      <label>Days until access expires <input id="reportShareDays" type="number" min="1" max="90" value="30" required style="${inputStyle}"></label>
      <button type="submit" class="btn btn-secondary">Grant scoped access</button></form>` : ''}
    ${shares.length ? `<ul style="font-size:12px;padding-left:18px;">${shares.map(s =>
      `<li>${esc(s.full_name || s.email || '')} (${esc(s.email || '')}), expires ${esc(s.expires_at || '')}` +
      (s.revoked_at ? ' (revoked)' : ` <button type="button" class="btn btn-secondary report-revoke" data-user="${Number(s.recipient_user_id)}">Revoke</button>`) + '</li>').join('')}</ul>` : ''}
    <div style="font-size:12px;"><strong>Retention:</strong> ${retention.delete_after ? 'Delete after ' + esc(retention.delete_after) : 'No deletion date approved'}${retention.hold_reason ? '; on hold: ' + esc(retention.hold_reason) : ''}</div>
    ${data.can_manage_retention ? `<form id="reportRetentionForm" style="${formStyle}">
      <label>Deletion date (leave blank to remove the date) <input id="reportDeleteAfter" type="date" value="${attrEsc(retention.delete_after || '')}" style="${inputStyle}"></label>
      <label>Hold reason (optional) <input id="reportHoldReason" maxlength="500" value="${attrEsc(retention.hold_reason || '')}" style="${inputStyle}"></label>
      <label>Reason for this retention decision <textarea id="reportRetentionReason" minlength="10" maxlength="500" required style="${inputStyle}"></textarea></label>
      <button type="submit" class="btn btn-secondary">Save retention decision</button></form>` : ''}
  </section>`;
  const send = async (url, method, body) => {
    const resp = await fetch(url, {method, headers:{'Content-Type':'application/json'}, body: body ? JSON.stringify(body) : undefined});
    const out = await readJson(resp);
    if (!resp.ok) { showNotice(out.error || 'The action could not be saved.'); return; }
    viewRun(data.run_id);
  };
  document.getElementById('reportSignoffForm')?.addEventListener('submit', e => {
    e.preventDefault();
    send(`/api/reports/runs/${data.run_id}/signoff`, 'POST', {
      decision: document.getElementById('reportSignoffDecision').value,
      reason: document.getElementById('reportSignoffReason').value,
      narrative_reviewed: !!document.getElementById('reportNarrativeReviewed')?.checked,
    });
  });
  document.getElementById('reportShareForm')?.addEventListener('submit', e => {
    e.preventDefault();
    send(`/api/reports/runs/${data.run_id}/shares`, 'POST', {
      recipient_email: document.getElementById('reportShareEmail').value,
      expires_days: Number(document.getElementById('reportShareDays').value),
    });
  });
  box.querySelectorAll('.report-revoke').forEach(button => button.addEventListener('click', () => {
    send(`/api/reports/runs/${data.run_id}/shares/${Number(button.dataset.user)}`, 'DELETE');
  }));
  document.getElementById('reportRetentionForm')?.addEventListener('submit', e => {
    e.preventDefault();
    send(`/api/reports/runs/${data.run_id}/retention`, 'POST', {
      delete_after: document.getElementById('reportDeleteAfter').value,
      hold_reason: document.getElementById('reportHoldReason').value,
      reason: document.getElementById('reportRetentionReason').value,
    });
  });
}

function viewRunData(data) {
  currentRun = data;
  const viewer = document.getElementById('reportViewer');
  viewer.style.display = 'block';
  document.getElementById('viewerTitle').textContent = data.report_name || typeLabels[data.report_type] || 'Report';
  const snap = data.snapshot || null;
  const when_ = snap ? (snap.run || {}).generated_at : (data.completed_at || data.started_at || '');
  document.getElementById('viewerMeta').innerHTML = `${esc(typeLabels[data.report_type] || data.report_type || '')} ${tierChip(data.report_type)} &bull; Run #${Number(data.run_id)} &bull; ${data.frozen ? 'Saved as generated' : 'Legacy run'} &bull; ${esc(when_ || '')}`;
  document.getElementById('viewerRerun').style.display = '';
  ['viewerExport', 'viewerPdf', 'viewerXlsx', 'viewerPrint'].forEach(id => { document.getElementById(id).style.display = data.frozen ? '' : 'none'; });

  const banner = document.getElementById('viewerBanner');
  banner.innerHTML = data.legacy
    ? `<div role="note" style="padding:10px 12px;border-radius:8px;background:var(--warn-soft);color:var(--text);font-size:12px;margin-bottom:12px;">${esc(data.legacy_note || '')}</div>`
    : '';
  document.getElementById('viewerFacts').innerHTML = snap ? renderFacts(snap) : '';
  document.getElementById('viewerChanges').innerHTML = snap ? renderChanges(snap.changes) : '';

  const result = data.result;
  document.getElementById('viewerContent').innerHTML = (result && typeof result === 'object')
    ? renderValue(result, 0)
    : '<div style="font-size:13px;color:var(--muted);">There is no saved output for this run.</div>';

  const narrative = snap && snap.narrative;
  document.getElementById('viewerNarrative').innerHTML = narrative && narrative.text
    ? `<section aria-label="Draft narrative" style="margin-top:16px;border-left:3px solid var(--accent);padding-left:12px;">
         <div style="font-size:11px;color:var(--muted);margin-bottom:6px;">Draft narrative, not reviewed${narrative.model ? ' &bull; written by ' + esc(narrative.model) : ''}. ${esc(narrative.basis || '')} ${esc(data.narrative_check || '')}</div>
         ${String(narrative.text).split(/\n\n+/).map(p => `<p style="margin:0 0 10px;font-size:13px;line-height:1.6;">${esc(p)}</p>`).join('')}</section>`
    : '';

  document.getElementById('viewerSources').innerHTML = snap ? renderLimitations(snap) + renderSources(snap) : '';
  renderNotes(data);
  renderGovernance(data);
  document.getElementById('viewerFoot').textContent = data.frozen
    ? `Integrity: SHA-256 ${data.hash}. These figures are the ones stored when the report was generated.` : '';
  viewer.scrollIntoView({ behavior:'smooth' });
}

/* ── The AI executive summary ────────────────────────────────────────── */

async function generateExecSummary() {
  showNotice('');
  const panel = document.getElementById('execSummaryPanel');
  panel.style.display = 'block';
  window.execRunId = null;
  document.getElementById('execPdf').disabled = true;
  document.getElementById('execPrint').disabled = true;
  document.getElementById('execSummaryNarrative').innerHTML = '<div style="text-align:center;padding:20px;color:var(--accent)"><div class="spinner" style="margin:0 auto 8px;width:20px;height:20px"></div>Generating the executive figures and a draft narrative...</div>';
  document.getElementById('execSummaryStats').innerHTML = '';
  document.getElementById('execSummaryMeta').textContent = '';
  try {
    const r = await fetch('/api/reports/executive-summary', {method:'POST'});
    const data = await readJson(r);
    if (!r.ok) {
      document.getElementById('execSummaryNarrative').textContent = data.error || 'The executive summary could not be generated.';
      return;
    }
    const s = data.stats || {};
    const pct = s.compliance_pct;
    const item = (label, value, color) => ({label, value: (value === null || value === undefined) ? 'n/a' : value, color});
    const statItems = [
      item('Compliance', pct === null || pct === undefined ? null : pct + '%', pct >= 80 ? 'var(--green-status)' : pct >= 60 ? 'var(--amber)' : 'var(--red)'),
      item('Open Risks', s.risks_open, s.risks_critical > 0 ? 'var(--red)' : 'var(--text)'),
      item('Critical Risks', s.risks_critical, s.risks_critical > 0 ? 'var(--red)' : 'var(--green-status)'),
      item('Active Audits', s.audits_active, 'var(--accent)'),
      item('Open Breaches', s.breaches_open, s.breaches_open > 0 ? 'var(--red)' : 'var(--green-status)'),
      item('Open DSRs', s.dsrs_open, 'var(--amber)'),
      item('Active Incidents', s.incidents_active, s.incidents_active > 0 ? 'var(--red)' : 'var(--green-status)'),
      item('Tasks Overdue', s.tasks_overdue, s.tasks_overdue > 0 ? 'var(--red)' : 'var(--green-status)'),
    ];
    document.getElementById('execSummaryStats').innerHTML = statItems.map(si =>
      '<div style="text-align:center;padding:12px;background:var(--surface2);border-radius:8px;border:1px solid var(--border)">' +
      '<div style="font-size:22px;font-weight:800;color:' + si.color + '">' + esc(si.value) + '</div>' +
      '<div style="font-size:10px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.5px;margin-top:3px">' + esc(si.label) + '</div></div>').join('');
    const narrative = document.getElementById('execSummaryNarrative');
    if (data.narrative) {
      narrative.innerHTML = String(data.narrative).split('\n\n').filter(p => p.trim()).map(p => '<p style="margin:0 0 12px">' + esc(p) + '</p>').join('');
    } else {
      narrative.textContent = data.narrative_note || 'No narrative was written. The figures above are complete.';
    }
    window.execRunId = data.run_id;
    document.getElementById('execPdf').disabled = false;
    document.getElementById('execPrint').disabled = false;
    document.getElementById('execSummaryMeta').innerHTML = esc('Generated ' + (data.generated_at || '') + ' UTC. ') +
      (data.complete ? '' : esc('Some figures could not be read and are shown as n/a. ')) +
      (data.narrative_check ? esc(data.narrative_check + ' ') : '') +
      '<a href="/reports?run=' + Number(data.run_id) + '">Open the saved run</a>';
    loadRuns(); loadStats();
  } catch (e) {
    document.getElementById('execSummaryNarrative').textContent = 'The executive summary could not be generated just now.';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('reportForm').addEventListener('submit', createReport);
  document.addEventListener('click', event => {
    const control = event.target.closest('[data-report-action]');
    if (!control) return;
    const action = control.dataset.reportAction;
    const rawId = control.dataset.runId;
    const recordId = rawId && /^[1-9]\d*$/.test(rawId) ? Number(rawId) : null;
    if (action === 'runs') showTab('runs');
    else if (action === 'definitions') showTab('definitions');
    else if (action === 'new') openNewReport();
    else if (action === 'executive') generateExecSummary();
    else if (action === 'exec-pdf') documentOf(window.execRunId, 'pdf');
    else if (action === 'exec-print') printRun(window.execRunId);
    else if (action === 'close-exec') document.getElementById('execSummaryPanel').style.display = 'none';
    else if (action === 'rerun') rerunCurrent();
    else if (action === 'pdf') documentCurrent('pdf');
    else if (action === 'xlsx') documentCurrent('xlsx');
    else if (action === 'print') printCurrent();
    else if (action === 'csv') exportCurrent();
    else if (action === 'close-viewer') document.getElementById('reportViewer').style.display = 'none';
    else if (action === 'close-new') ModalManager.close('newReportModal');
    else if (action === 'run' && Number.isSafeInteger(recordId)) runReport(recordId);
    else if (action === 'view' && Number.isSafeInteger(recordId)) viewRun(recordId);
  });
  const policyForm = document.getElementById('reportPolicyForm');
  if (policyForm) {
    const status = document.getElementById('reportPolicyStatus');
    fetch('/api/reports/retention-policy').then(readJson).then(policy => {
      if (Number.isInteger(policy.days)) document.getElementById('reportPolicyDays').value = policy.days;
    }).catch(() => { status.textContent = 'The tenant retention policy could not be loaded.'; });
    policyForm.addEventListener('submit', async event => {
      event.preventDefault();
      try {
        const resp = await fetch('/api/reports/retention-policy', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({days:Number(document.getElementById('reportPolicyDays').value),
            reason:document.getElementById('reportPolicyReason').value})});
        const result = await readJson(resp);
        status.textContent = resp.ok ? `New reports will be retained for ${result.days} days unless a run has its own date or hold.`
          : (result.error || 'The tenant policy could not be saved.');
      } catch (_) { status.textContent = 'The tenant policy could not be saved.'; }
    });
  }
  document.querySelectorAll('.js-quick-report').forEach(button => {
    button.addEventListener('click', () => quickRun(button.dataset.quick));
  });
  loadStats(); loadRuns();
  const open = new URLSearchParams(window.location.search).get('run');
  if (open && /^\d+$/.test(open)) viewRun(open);
});
