// State
const state = {
  frameworks: [], audits: [], currentAuditId: null, currentFwId: null,
  controls: [], evidence: [], reminders: [], dashData: null
};

// ---- INIT ----
async function init() {
  await loadFrameworks();
  const savedAudit = localStorage.getItem('currentAuditId');
  if (savedAudit) { state.currentAuditId = savedAudit; }
  await loadAudits();
  if (!state.currentAuditId && state.audits.length > 0) {
    state.currentAuditId = state.audits[0].id;
    state.currentFwId = state.audits[0].framework_id;
  }
  renderSidebar();
  if (state.currentAuditId) await loadDashboard();
}

// ---- API ----
async function api(method, path, data, isFormData) {
  const opts = { method, headers: {} };
  if (data && !isFormData) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(data); }
  else if (data) opts.body = data;
  const res = await fetch('/api' + path, opts);
  return res.json();
}

// ---- FRAMEWORKS ----
async function loadFrameworks() {
  state.frameworks = await api('GET', '/frameworks');
  renderFwBadges();
}

function renderFwBadges() {
  document.getElementById('fw-badges').innerHTML = state.frameworks.map(fw =>
    `<button class="top-framework-badge ${state.currentFwId===fw.id?'active':''}" onclick="selectFramework('${fw.id}')" title="${fw.name}">${fw.name}</button>`
  ).join('');
}

function renderSidebar() {
  document.getElementById('fw-sidebar-list').innerHTML = state.frameworks.map(fw =>
    `<div class="fw-item ${state.currentFwId===fw.id?'active':''}" onclick="selectFramework('${fw.id}')">
      <div class="fw-dot" style="background:${fw.color}"></div>${fw.name}
    </div>`
  ).join('');
}

async function selectFramework(fwId) {
  state.currentFwId = fwId;
  // Find or create audit for this framework
  const audit = state.audits.find(a => a.framework_id === fwId);
  if (audit) {
    state.currentAuditId = audit.id;
    localStorage.setItem('currentAuditId', audit.id);
  } else {
    state.currentAuditId = null;
  }
  renderFwBadges();
  renderSidebar();
  if (state.currentAuditId) await loadDashboard();
  else showToast('No audit found for this framework. Create one with + New Audit.', 'info');
  navigate('dashboard');
}

// ---- AUDITS ----
async function loadAudits() {
  state.audits = await api('GET', '/audits');
}

// ---- DASHBOARD ----
async function loadDashboard() {
  if (!state.currentAuditId) return;
  const data = await api('GET', `/dashboard/${state.currentAuditId}`);
  state.dashData = data;
  state.controls = data.controls;
  state.evidence = data.evidence;
  renderDashboard(data);
  renderBadges(data);
}

function renderDashboard(data) {
  const { audit, controls, evidence, stats } = data;
  // Title
  document.getElementById('dash-title').textContent = audit.name;
  document.getElementById('dash-sub').textContent = `${audit.framework_name} · ${audit.audit_type} · Auditor: ${audit.auditor || 'TBD'}`;

  // Stats
  const daysLeft = Math.ceil(audit.days_remaining || 0);
  document.getElementById('dash-stats').innerHTML = `
    <div class="stat-card c-green">
      <div class="stat-label">Completion</div>
      <div class="stat-value c-green">${stats.completion_pct}%</div>
      <div class="progress-bar"><div class="progress-fill" style="width:${stats.completion_pct}%;background:var(--green)"></div></div>
      <div class="stat-sub">${stats.completed}/${stats.total} controls</div>
    </div>
    <div class="stat-card c-amber">
      <div class="stat-label">Evidence Pending</div>
      <div class="stat-value c-amber">${stats.pending_ev}</div>
      <div class="stat-sub">Controls with no evidence</div>
    </div>
    <div class="stat-card c-red">
      <div class="stat-label">Overdue</div>
      <div class="stat-value c-red">${stats.overdue}</div>
      <div class="stat-sub">Past deadline</div>
    </div>
    <div class="stat-card c-blue">
      <div class="stat-label">Days to Audit</div>
      <div class="stat-value c-blue">${daysLeft > 0 ? daysLeft : 'Past'}</div>
      <div class="stat-sub">${audit.audit_date || 'No date set'}</div>
    </div>`;

  // Controls table
  renderControlsTable(controls, 'controls-tbody', true);

  // Progress ring
  const collected = evidence.filter(e=>e.status==='Uploaded').length;
  const total_ev = evidence.length;
  renderProgressRing(collected, total_ev, controls);

  // Timeline
  renderTimeline(audit);
}

function renderControlsTable(controls, tbodyId, mini) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  if (controls.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:32px;color:var(--muted);">No controls found. Add controls or import a checklist.</td></tr>`;
    return;
  }
  tbody.innerHTML = controls.map(c => {
    const isOverdue = c.due_date && c.status !== 'Complete' && new Date(c.due_date) < new Date();
    const dueColor = isOverdue ? 'var(--red)' : c.due_date && (new Date(c.due_date) - new Date()) < 7*86400000 ? 'var(--amber)' : 'var(--muted)';
    const statusBadge = { 'Complete':'badge-complete', 'In Progress':'badge-progress', 'Not Started':'badge-not-started' }[c.status] || 'badge-not-started';
    const initials = (c.assigned_to||'?').split(' ').map(w=>w[0]).join('').substring(0,2).toUpperCase();
    return `<tr class="clickable" onclick="openControlDetail('${c.id}')">
      <td><div class="req-check ${c.status==='Complete'?'done':''}" onclick="event.stopPropagation();quickToggle('${c.id}','${c.status}')">${c.status==='Complete'?'✓':''}</div></td>
      <td><div style="color:var(--accent);font-family:var(--mono);font-size:10px;">${c.control_id||'—'}</div><div style="font-size:12px;">${c.name}</div></td>
      <td><span class="badge badge-${(c.risk_level||'medium').toLowerCase()}">${c.risk_level||'—'}</span></td>
      ${mini ? '' : `<td><span class="badge ${statusBadge}">${c.status||'Not Started'}</span></td>`}
      <td>${c.assigned_to ? `<div style="display:flex;align-items:center;gap:6px;"><div class="av" style="background:rgba(79,142,247,.2);color:var(--accent)">${initials}</div><span style="font-size:11px;">${c.assigned_to}</span></div>` : '<span style="color:var(--muted);font-size:11px;">—</span>'}</td>
      <td style="font-size:11px;color:${dueColor};font-family:var(--mono);">${isOverdue?'⚠ Overdue':(c.due_date||'—')}</td>
      <td style="font-size:11px;font-family:var(--mono);color:${c.ev_count>0?(c.ev_count>=c.ev_req&&c.ev_req>0?'var(--green)':'var(--amber)'):'var(--red)'};">${c.ev_count||0}/${c.ev_req||0}</td>
      ${!mini ? `<td><button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();openControlDetail('${c.id}')">Edit</button><button class="btn btn-danger btn-sm" onclick="event.stopPropagation();deleteControl('${c.id}')">✕</button></td>` : '<td></td>'}
    </tr>`;
  }).join('');
}

async function quickToggle(controlId, currentStatus) {
  const newStatus = currentStatus === 'Complete' ? 'Not Started' : 'Complete';
  await api('PATCH', `/controls/${controlId}`, { status: newStatus });
  await loadDashboard();
}

function renderProgressRing(collected, total, controls) {
  const pct = total > 0 ? Math.round(collected/total*100) : 0;
  const r = 38, cx = 50, cy = 50, circ = 2*Math.PI*r;
  const offset = circ - (pct/100)*circ;
  document.getElementById('progress-ring').innerHTML = `
    <svg width="100" height="100" viewBox="0 0 100 100">
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--surface2)" stroke-width="10"/>
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--green)" stroke-width="10"
        stroke-dasharray="${circ}" stroke-dashoffset="${offset}" stroke-linecap="round" transform="rotate(-90 ${cx} ${cy})"/>
      <text x="${cx}" y="${cy+5}" text-anchor="middle" fill="var(--text)" font-size="16" font-weight="700" font-family="Syne,sans-serif">${pct}%</text>
    </svg>`;
  const missing = total - collected;
  document.getElementById('ev-legend').innerHTML = `
    <div style="display:flex;flex-direction:column;gap:6px;font-size:11px;">
      <div style="display:flex;justify-content:space-between;"><span style="color:var(--muted);">Uploaded</span><span style="color:var(--green);font-family:var(--mono);">${collected}</span></div>
      <div style="display:flex;justify-content:space-between;"><span style="color:var(--muted);">Missing</span><span style="color:var(--red);font-family:var(--mono);">${missing}</span></div>
      <div style="display:flex;justify-content:space-between;"><span style="color:var(--muted);">Total controls</span><span style="font-family:var(--mono);">${controls.length}</span></div>
    </div>`;
}

function renderTimeline(audit) {
  const items = [
    { label: 'Audit created', date: audit.created_at?.substring(0,10), done: true },
    { label: 'Evidence collection starts', date: audit.start_date, done: audit.start_date && new Date(audit.start_date) <= new Date() },
    { label: 'Submission deadline', date: audit.audit_date ? new Date(new Date(audit.audit_date).getTime()-7*86400000).toISOString().substring(0,10) : null, done: false },
    { label: 'Audit date', date: audit.audit_date, done: false },
  ].filter(i => i.date);
  document.getElementById('timeline').innerHTML = items.map((item, i) => {
    const overdue = !item.done && item.date && new Date(item.date) < new Date();
    const dateColor = item.done ? 'var(--green)' : overdue ? 'var(--red)' : 'var(--muted)';
    const dotColor = item.done ? 'var(--green)' : overdue ? 'var(--red)' : 'var(--border2)';
    return `<div class="tl-item">
      <div class="tl-line"><div class="tl-dot" style="background:${dotColor}"></div>${i<items.length-1?'<div class="tl-connector"></div>':''}</div>
      <div class="tl-content">
        <div class="tl-title">${item.label}</div>
        <div class="tl-date" style="color:${dateColor}">${item.done?'✓ ':''}${item.date}${overdue?' — Overdue':''}</div>
      </div>
    </div>`;
  }).join('');
}

function renderBadges(data) {
  document.getElementById('badge-controls').textContent = data.stats.total;
  document.getElementById('badge-evidence').textContent = data.evidence.length;
}

// ---- NAVIGATE ----
function navigate(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-'+page)?.classList.add('active');
  document.querySelector(`[data-page="${page}"]`)?.classList.add('active');
  if (page === 'controls') renderAllControls();
  if (page === 'evidence') renderEvidencePage();
  if (page === 'reminders') loadReminders();
  if (page === 'reports') renderReports();
}

// ---- CONTROLS PAGE ----
function renderAllControls() {
  if (!state.currentAuditId) return;
  document.getElementById('ctrl-sub').textContent = `${state.controls.length} controls · Current audit`;
  renderControlsTable(state.controls, 'all-controls-tbody', false);
}

function filterControls(type, btn) {
  document.querySelectorAll('#page-dashboard .filter-pill').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  let filtered = state.controls;
  if (type === 'overdue') filtered = state.controls.filter(c=>c.due_date&&c.status!=='Complete'&&new Date(c.due_date)<new Date());
  else if (type !== 'all') filtered = state.controls.filter(c=>c.status===type);
  renderControlsTable(filtered, 'controls-tbody', true);
}

function filterAllControls(type, btn) {
  document.querySelectorAll('#page-controls .filter-pill').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  let filtered = state.controls;
  if (type === 'Critical') filtered = state.controls.filter(c=>c.risk_level==='Critical');
  else if (type !== 'all') filtered = state.controls.filter(c=>c.status===type);
  renderControlsTable(filtered, 'all-controls-tbody', false);
}

async function deleteControl(id) {
  if (!confirm('Delete this control and all its evidence?')) return;
  await api('DELETE', `/controls/${id}`);
  showToast('Control deleted', 'success');
  await loadDashboard();
  renderAllControls();
}

// ---- EVIDENCE PAGE ----
function renderEvidencePage() {
  document.getElementById('ev-sub').textContent = `${state.evidence.length} items across current audit`;
  renderEvidenceList(state.evidence);
}

function renderEvidenceList(items) {
  const container = document.getElementById('evidence-list');
  if (!items.length) {
    container.innerHTML = `<div class="empty-state"><div class="icon">📎</div><p>No evidence uploaded yet.<br>Upload files for your controls.</p></div>`;
    return;
  }
  const fileIcon = (type) => {
    if (!type) return '📄';
    if (type.includes('pdf')) return '📕';
    if (type.includes('sheet') || type.includes('excel')) return '📗';
    if (type.includes('image')) return '🖼';
    if (type.includes('word')) return '📘';
    return '📄';
  };
  container.innerHTML = items.map(ev => `
    <div class="ev-item">
      <div class="ev-icon">${fileIcon(ev.file_type)}</div>
      <div class="ev-info">
        <div class="ev-name">${ev.original_name||ev.name}</div>
        <div class="ev-meta">${ev.control_name||'—'} · ${(ev.uploaded_at||'').substring(0,10)} · ${formatBytes(ev.file_size)}</div>
      </div>
      <span class="badge badge-${(ev.status||'pending').toLowerCase()}">${ev.status||'Pending'}</span>
      <div class="ev-actions">
        <button class="btn btn-ghost btn-sm" onclick="downloadEvidence('${ev.id}','${ev.original_name}')">↓</button>
        <button class="btn btn-danger btn-sm" onclick="deleteEvidence('${ev.id}')">✕</button>
      </div>
    </div>`).join('');
}

function filterEvidence(type, btn) {
  document.querySelectorAll('#page-evidence .filter-pill').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  const filtered = type === 'all' ? state.evidence : state.evidence.filter(e=>e.status===type);
  renderEvidenceList(filtered);
}

async function downloadEvidence(id, name) {
  window.open(`/api/evidence/${id}/download`, '_blank');
}

async function deleteEvidence(id) {
  if (!confirm('Delete this evidence file?')) return;
  await api('DELETE', `/evidence/${id}`);
  showToast('Evidence deleted', 'success');
  await loadDashboard();
  renderEvidencePage();
}

function formatBytes(b) {
  if (!b) return '—';
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b/1024).toFixed(1) + ' KB';
  return (b/1048576).toFixed(1) + ' MB';
}

// ---- REMINDERS ----
async function loadReminders() {
  if (!state.currentAuditId) return;
  state.reminders = await api('GET', `/reminders?audit_id=${state.currentAuditId}`);
  const tbody = document.getElementById('reminders-tbody');
  if (!state.reminders.length) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:32px;color:var(--muted);">No reminders set. Add reminders to notify team members.</td></tr>`;
    return;
  }
  tbody.innerHTML = state.reminders.map(r => `
    <tr>
      <td><div style="font-family:var(--mono);font-size:10px;color:var(--accent);">${r.ctrl_ref||'—'}</div><div style="font-size:12px;">${r.control_name||'—'}</div></td>
      <td style="font-size:12px;">${r.email}</td>
      <td><span class="badge badge-medium">${r.frequency}</span></td>
      <td style="font-size:11px;color:var(--muted);font-family:var(--mono);">${r.last_sent?r.last_sent.substring(0,10):'Never'}</td>
      <td><button class="btn btn-primary btn-sm" onclick="sendNow('${r.id}')">Send now</button></td>
    </tr>`).join('');
}

async function sendNow(reminderId) {
  showToast('Sending email...', 'info');
  const result = await api('POST', `/reminders/${reminderId}/send-now`);
  if (result.success) showToast(`Email sent! ${result.preview?'Preview: '+result.preview:''}`, 'success');
  else showToast('Send failed: ' + result.error, 'error');
  loadReminders();
}

// ---- REPORTS ----
function renderReports() {
  const audits = state.audits;
  document.getElementById('reports-list').innerHTML = audits.map(a => {
    const pct = a.total_controls > 0 ? Math.round(a.completed_controls/a.total_controls*100) : 0;
    return `<div class="card" style="margin-bottom:14px;">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:18px 20px;">
        <div style="display:flex;align-items:center;gap:14px;">
          <div style="width:44px;height:44px;border-radius:10px;background:rgba(79,142,247,.12);display:flex;align-items:center;justify-content:center;font-size:20px;">📋</div>
          <div>
            <div style="font-size:14px;font-weight:700;margin-bottom:4px;">${a.name}</div>
            <div style="font-size:11px;color:var(--muted);font-family:var(--mono);">${a.framework_name} · ${pct}% complete · ${a.total_controls} controls · Audit: ${a.audit_date||'TBD'}</div>
            <div style="margin-top:6px;height:3px;width:200px;background:var(--surface2);border-radius:2px;overflow:hidden;"><div style="height:100%;width:${pct}%;background:${pct>70?'var(--green)':pct>40?'var(--amber)':'var(--red)'};border-radius:2px;"></div></div>
          </div>
        </div>
        <div style="display:flex;gap:8px;">
          <button class="btn btn-secondary" onclick="exportReportFor('pdf','${a.id}')">↓ PDF</button>
          <button class="btn btn-ghost" onclick="exportReportFor('excel','${a.id}')">↓ Excel</button>
        </div>
      </div>
    </div>`;
  }).join('') || '<div class="empty-state"><div class="icon">📊</div><p>No audits found. Create an audit to generate reports.</p></div>';
}

function exportReport(type) {
  if (!state.currentAuditId) { showToast('No audit selected', 'error'); return; }
  exportReportFor(type, state.currentAuditId);
}

function exportReportFor(type, auditId) {
  showToast(`Generating ${type.toUpperCase()} report...`, 'info');
  window.open(`/api/reports/${type}/${auditId}`, '_blank');
}

// ---- GAP ANALYSIS ----
async function runGapAnalysis() {
  if (!state.currentAuditId) { showToast('Select an audit first', 'error'); return; }
  document.getElementById('gap-result').innerHTML = `<div class="empty-state"><div class="icon">✦</div><p>Analyzing your audit with AI...<br><small style="color:var(--muted)">This may take 15-30 seconds</small></p></div>`;
  const result = await api('POST', '/ai/gap-analysis', { audit_id: state.currentAuditId });
  if (result.error) { document.getElementById('gap-result').innerHTML = `<div class="empty-state"><p style="color:var(--red);">${result.error}</p></div>`; return; }
  const pct = parseInt(result.overall_readiness)||0;
  const riskColor = {'High':'var(--red)','Medium':'var(--amber)','Low':'var(--green)'}[result.risk_rating]||'var(--muted)';
  document.getElementById('gap-result').innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:20px;">
      <div class="card card-body">
        <div class="stat-label">Readiness</div>
        <div class="stat-value" style="color:${pct>70?'var(--green)':pct>40?'var(--amber)':'var(--red)'};">${pct}%</div>
        <div class="progress-bar"><div class="progress-fill" style="width:${pct}%;background:${pct>70?'var(--green)':pct>40?'var(--amber)':'var(--red)'}"></div></div>
      </div>
      <div class="card card-body">
        <div class="stat-label">Risk Rating</div>
        <div class="stat-value" style="color:${riskColor};">${result.risk_rating||'—'}</div>
        <div class="stat-sub">${result.timeline_feasibility?.substring(0,60)||''}</div>
      </div>
      <div class="card card-body">
        <div class="stat-label">Critical Gaps</div>
        <div class="stat-value c-red">${(result.critical_gaps||[]).length}</div>
        <div class="stat-sub">Items needing attention</div>
      </div>
    </div>
    ${result.executive_summary?`<div class="gap-card"><h4>Executive Summary</h4><p style="font-size:13px;line-height:1.7;">${result.executive_summary}</p></div>`:''}
    ${result.critical_gaps?.length?`<div class="gap-card"><h4>Critical Gaps</h4><ul class="gap-list">${result.critical_gaps.map(g=>`<li>${g}</li>`).join('')}</ul></div>`:''}
    ${result.recommendations?.length?`<div class="gap-card"><h4>Recommendations</h4><ul class="gap-list">${result.recommendations.map(r=>`<li>${r}</li>`).join('')}</ul></div>`:''}
    ${result.timeline_feasibility?`<div class="gap-card"><h4>Timeline Assessment</h4><p style="font-size:13px;line-height:1.7;">${result.timeline_feasibility}</p></div>`:''}
    <div style="text-align:right;margin-top:8px;"><button class="btn btn-ghost btn-sm" onclick="runGapAnalysis()">↻ Re-run Analysis</button></div>`;
}

// ---- AI CHAT ----
function openAIChat() { document.getElementById('modal-chat').classList.add('open'); }

async function sendChat() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';
  const msgs = document.getElementById('chat-messages');
  msgs.innerHTML += `<div class="chat-msg user">${escHtml(msg)}</div>`;
  msgs.innerHTML += `<div class="chat-msg ai loading" id="chat-loading">Thinking...</div>`;
  msgs.scrollTop = msgs.scrollHeight;
  const result = await api('POST', '/ai/chat', { message: msg, audit_id: state.currentAuditId });
  document.getElementById('chat-loading')?.remove();
  msgs.innerHTML += `<div class="chat-msg ai">${(result.reply||result.error||'Error').replace(/\n/g,'<br>')}</div>`;
  msgs.scrollTop = msgs.scrollHeight;
}

// ---- MODALS ----
function openModal(type) {
  const modal = document.getElementById('modal-main');
  const box = document.getElementById('modal-box');
  box.className = 'modal';
  const defs = modalDefs[type];
  if (!defs) return;
  document.getElementById('modal-title').textContent = defs.title;
  document.getElementById('modal-body').innerHTML = typeof defs.body === 'function' ? defs.body() : defs.body;
  document.getElementById('modal-footer').innerHTML = defs.footer ? (typeof defs.footer === 'function' ? defs.footer() : defs.footer) : `<button class="btn btn-ghost" onclick="closeModal('modal-main')">Cancel</button><button class="btn btn-primary" onclick="${defs.save||'closeModal(\'modal-main\')'}">${defs.saveLabel||'Save'}</button>`;
  if (defs.wide) box.classList.add('modal-lg');
  modal.classList.add('open');
  if (defs.onOpen) defs.onOpen();
}

function closeModal(id) { document.getElementById(id).classList.remove('open'); }
function handleBackdropClick(e) { if (e.target.id==='modal-main') closeModal('modal-main'); }

const modalDefs = {
  newAudit: {
    title: 'Create New Audit',
    body: () => `
      <div class="form-group"><label class="form-label">Audit Name *</label><input class="form-input" id="f-audit-name" placeholder="e.g. ISO 27001 Annual Audit 2025"></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Framework *</label>
          <select class="form-select" id="f-audit-fw">${state.frameworks.map(f=>`<option value="${f.id}">${f.name}</option>`).join('')}</select>
        </div>
        <div class="form-group"><label class="form-label">Audit Type</label>
          <select class="form-select" id="f-audit-type"><option>External</option><option>Internal</option><option>System Audit</option><option>Gap Analysis</option></select>
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Start Date</label><input class="form-input" type="date" id="f-audit-start"></div>
        <div class="form-group"><label class="form-label">Audit Date</label><input class="form-input" type="date" id="f-audit-date"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Auditor / Firm</label><input class="form-input" id="f-audit-auditor" placeholder="e.g. KPMG, Internal"></div>
        <div class="form-group"><label class="form-label">Audit Lead</label><input class="form-input" id="f-audit-lead" placeholder="Name or email"></div>
      </div>`,
    save: 'saveNewAudit()', saveLabel: 'Create Audit'
  },
  addControl: {
    title: 'Add Control',
    body: () => `
      <div class="form-row">
        <div class="form-group"><label class="form-label">Control ID</label><input class="form-input" id="f-ctrl-id" placeholder="e.g. A.5.1"></div>
        <div class="form-group"><label class="form-label">Risk Level</label>
          <select class="form-select" id="f-ctrl-risk"><option>Critical</option><option>High</option><option selected>Medium</option><option>Low</option></select>
        </div>
      </div>
      <div class="form-group"><label class="form-label">Control Name *</label><input class="form-input" id="f-ctrl-name" placeholder="e.g. Information security policies"></div>
      <div class="form-group"><label class="form-label">Description</label><textarea class="form-textarea" id="f-ctrl-desc" placeholder="Describe what this control requires..."></textarea></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Assigned To</label><input class="form-input" id="f-ctrl-owner" placeholder="Full name"></div>
        <div class="form-group"><label class="form-label">Owner Email</label><input class="form-input" type="email" id="f-ctrl-email" placeholder="email@company.com"></div>
      </div>
      <div class="form-group"><label class="form-label">Due Date</label><input class="form-input" type="date" id="f-ctrl-due"></div>
      <div style="margin-top:4px;"><button class="btn btn-ai btn-sm" onclick="aiGenerateReqs()">✦ AI: Auto-generate evidence requirements</button></div>
      <div id="ai-reqs-result" style="margin-top:12px;"></div>`,
    save: 'saveControl()', saveLabel: 'Add Control'
  },
  uploadChecklist: {
    title: 'Import Checklist',
    body: () => `
      <div id="import-drop" class="upload-zone" onclick="document.getElementById('import-file').click()">
        <div class="upload-icon-lg">📊</div>
        <div class="upload-text"><strong>Drop Excel or PDF</strong><br>Auditor checklists auto-mapped with AI</div>
      </div>
      <input type="file" id="import-file" accept=".xlsx,.xls,.pdf,.csv,.txt" style="display:none" onchange="importChecklist(this)">
      <div id="import-status" style="margin-top:12px;"></div>`,
    footer: () => `<button class="btn btn-ghost" onclick="closeModal('modal-main')">Close</button>`
  },
  uploadEvidence: {
    title: 'Upload Evidence',
    body: () => {
      const ctrlOptions = state.controls.map(c=>`<option value="${c.id}">${c.control_id} — ${c.name}</option>`).join('');
      return `
        <div class="form-group"><label class="form-label">Control *</label><select class="form-select" id="f-ev-ctrl">${ctrlOptions}</select></div>
        <div class="form-group"><label class="form-label">Description</label><input class="form-input" id="f-ev-desc" placeholder="What does this evidence demonstrate?"></div>
        <div class="form-row">
          <div class="form-group"><label class="form-label">Uploaded By</label><input class="form-input" id="f-ev-by" placeholder="Your name"></div>
          <div class="form-group"><label class="form-label">Expires</label><input class="form-input" type="date" id="f-ev-expires"></div>
        </div>
        <div class="upload-zone" onclick="document.getElementById('ev-file').click()" id="ev-drop">
          <div class="upload-icon-lg">📎</div>
          <div class="upload-text" id="ev-file-label"><strong>Select file</strong><br>PDF, XLSX, PNG, DOCX, up to 50MB</div>
        </div>
        <input type="file" id="ev-file" style="display:none" onchange="document.getElementById('ev-file-label').innerHTML='<strong>'+this.files[0].name+'</strong>'">
        <div id="ev-ai-result" style="margin-top:12px;"></div>`;
    },
    save: 'uploadEvidence()', saveLabel: 'Upload'
  },
  newFramework: {
    title: 'Add Framework',
    body: () => `
      <div class="form-group"><label class="form-label">Framework Name *</label><input class="form-input" id="f-fw-name" placeholder="e.g. NIST CSF, COBIT, Custom"></div>
      <div class="form-group"><label class="form-label">Description</label><input class="form-input" id="f-fw-desc" placeholder="Short description"></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Color</label><input class="form-input" type="color" id="f-fw-color" value="#4f8ef7"></div>
        <div class="form-group"><label class="form-label">Type</label>
          <select class="form-select" id="f-fw-type"><option>Security</option><option>Privacy</option><option>AI Governance</option><option>Financial</option><option>Healthcare</option><option>Custom</option></select>
        </div>
      </div>`,
    save: 'saveFramework()', saveLabel: 'Add Framework'
  },
  addReminder: {
    title: 'Add Email Reminder',
    body: () => {
      const ctrlOpts = state.controls.map(c=>`<option value="${c.id}">${c.control_id} — ${c.name.substring(0,40)}</option>`).join('');
      return `
        <div class="form-group"><label class="form-label">Control *</label><select class="form-select" id="f-rm-ctrl">${ctrlOpts}</select></div>
        <div class="form-group"><label class="form-label">Recipient Email *</label><input class="form-input" type="email" id="f-rm-email" placeholder="owner@company.com"></div>
        <div class="form-group"><label class="form-label">Frequency</label>
          <select class="form-select" id="f-rm-freq"><option value="daily">Daily</option><option value="weekly" selected>Weekly</option></select>
        </div>`;
    },
    save: 'saveReminder()', saveLabel: 'Set Reminder'
  }
};

// Control detail modal (dynamic content)
async function openControlDetail(controlId) {
  const ctrl = state.controls.find(c=>c.id===controlId);
  if (!ctrl) return;
  const reqs = await api('GET', `/controls/${controlId}/requirements`);
  const evItems = await api('GET', `/evidence?control_id=${controlId}`);

  document.getElementById('modal-title').textContent = `${ctrl.control_id||'Control'} — ${ctrl.name}`;
  document.getElementById('modal-box').className = 'modal modal-lg';
  document.getElementById('modal-body').innerHTML = `
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;">
      <span class="badge badge-${(ctrl.risk_level||'medium').toLowerCase()}">${ctrl.risk_level||'Medium'}</span>
      <span class="badge badge-${ctrl.status==='Complete'?'complete':ctrl.status==='In Progress'?'progress':'not-started'}">${ctrl.status||'Not Started'}</span>
      ${ctrl.due_date?`<span style="font-size:11px;color:var(--muted);font-family:var(--mono);align-self:center;">Due: ${ctrl.due_date}</span>`:''}
    </div>
    <div class="form-row" style="margin-bottom:16px;">
      <div class="form-group"><label class="form-label">Status</label>
        <select class="form-select" id="detail-status" onchange="updateControlField('${controlId}','status',this.value)">
          <option ${ctrl.status==='Not Started'?'selected':''}>Not Started</option>
          <option ${ctrl.status==='In Progress'?'selected':''}>In Progress</option>
          <option ${ctrl.status==='Complete'?'selected':''}>Complete</option>
        </select>
      </div>
      <div class="form-group"><label class="form-label">Assigned To</label>
        <input class="form-input" id="detail-owner" value="${ctrl.assigned_to||''}" onblur="updateControlField('${controlId}','assigned_to',this.value)" placeholder="Name">
      </div>
    </div>
    <div class="form-row" style="margin-bottom:16px;">
      <div class="form-group"><label class="form-label">Owner Email</label>
        <input class="form-input" type="email" id="detail-email" value="${ctrl.assigned_email||''}" onblur="updateControlField('${controlId}','assigned_email',this.value)" placeholder="email">
      </div>
      <div class="form-group"><label class="form-label">Due Date</label>
        <input class="form-input" type="date" id="detail-due" value="${ctrl.due_date||''}" onblur="updateControlField('${controlId}','due_date',this.value)">
      </div>
    </div>
    <div class="form-group" style="margin-bottom:16px;">
      <label class="form-label">Description / Notes</label>
      <textarea class="form-textarea" id="detail-notes" onblur="updateControlField('${controlId}','notes',this.value)">${ctrl.notes||ctrl.description||''}</textarea>
    </div>
    <div style="margin-bottom:16px;">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
        <label class="form-label" style="margin:0;">Evidence Requirements</label>
        <button class="btn btn-ai btn-sm" onclick="aiRequirementsForControl('${controlId}')">✦ AI Generate</button>
      </div>
      <div id="req-list">
        ${reqs.map(r=>`<div class="req-row"><div class="req-check ${r.is_satisfied?'done':''}" onclick="toggleReq('${r.id}',${r.is_satisfied})">${r.is_satisfied?'✓':''}</div><div style="flex:1;font-size:12px;">${r.description}</div></div>`).join('')}
        ${!reqs.length?'<div style="color:var(--muted);font-size:12px;padding:8px 0;">No requirements defined. Add manually or use AI.</div>':''}
      </div>
      <div style="display:flex;gap:8px;margin-top:8px;">
        <input class="form-input" id="new-req-input" placeholder="Add requirement..." style="flex:1;">
        <button class="btn btn-secondary btn-sm" onclick="addRequirement('${controlId}')">Add</button>
      </div>
    </div>
    <div>
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
        <label class="form-label" style="margin:0;">Evidence Files (${evItems.length})</label>
        <button class="btn btn-primary btn-sm" onclick="closeModal('modal-main');openModal('uploadEvidence')">+ Upload</button>
      </div>
      ${evItems.map(ev=>`<div class="ev-item"><div class="ev-icon">📄</div><div class="ev-info"><div class="ev-name">${ev.original_name||ev.name}</div><div class="ev-meta">${(ev.uploaded_at||'').substring(0,10)}</div></div><span class="badge badge-${(ev.status||'pending').toLowerCase()}">${ev.status}</span><button class="btn btn-ghost btn-sm" onclick="downloadEvidence('${ev.id}')">↓</button></div>`).join('')}
      ${!evItems.length?'<div style="color:var(--muted);font-size:12px;padding:8px;">No evidence uploaded for this control.</div>':''}
    </div>`;
  document.getElementById('modal-footer').innerHTML = `
    <button class="btn btn-ghost" onclick="closeModal('modal-main')">Close</button>
    <button class="btn btn-secondary" onclick="openReminderForControl('${controlId}')">🔔 Set Reminder</button>`;
  document.getElementById('modal-main').classList.add('open');
}

async function updateControlField(id, field, value) {
  await api('PATCH', `/controls/${id}`, { [field]: value });
  await loadDashboard();
}

async function toggleReq(reqId, current) {
  await api('PATCH', `/requirements/${reqId}`, { is_satisfied: !current });
  showToast(current ? 'Marked as pending' : 'Marked as satisfied', 'success');
}

async function addRequirement(controlId) {
  const input = document.getElementById('new-req-input');
  if (!input.value.trim()) return;
  await api('POST', `/controls/${controlId}/requirements`, { description: input.value.trim() });
  input.value = '';
  openControlDetail(controlId);
}

async function aiRequirementsForControl(controlId) {
  showToast('Generating with AI...', 'info');
  const result = await api('POST', '/ai/generate-requirements', { control_id: controlId });
  if (result.error) { showToast(result.error, 'error'); return; }
  showToast(`Added ${result.requirements?.length||0} requirements`, 'success');
  openControlDetail(controlId);
}

function openReminderForControl(controlId) {
  closeModal('modal-main');
  openModal('addReminder');
  setTimeout(()=>{ document.getElementById('f-rm-ctrl').value = controlId; }, 100);
}

// ---- SAVE FUNCTIONS ----
async function saveNewAudit() {
  const name = document.getElementById('f-audit-name').value.trim();
  if (!name) { showToast('Audit name required', 'error'); return; }
  const result = await api('POST', '/audits', {
    framework_id: document.getElementById('f-audit-fw').value,
    name, audit_type: document.getElementById('f-audit-type').value,
    start_date: document.getElementById('f-audit-start').value,
    audit_date: document.getElementById('f-audit-date').value,
    auditor: document.getElementById('f-audit-auditor').value,
    audit_lead: document.getElementById('f-audit-lead').value,
  });
  if (result.error) { showToast(result.error, 'error'); return; }
  state.currentAuditId = result.id;
  localStorage.setItem('currentAuditId', result.id);
  closeModal('modal-main');
  showToast('Audit created!', 'success');
  await loadAudits();
  await loadDashboard();
}

async function saveControl() {
  const name = document.getElementById('f-ctrl-name').value.trim();
  if (!name) { showToast('Control name required', 'error'); return; }
  const result = await api('POST', '/controls', {
    audit_id: state.currentAuditId,
    control_id: document.getElementById('f-ctrl-id').value,
    name, description: document.getElementById('f-ctrl-desc').value,
    risk_level: document.getElementById('f-ctrl-risk').value,
    assigned_to: document.getElementById('f-ctrl-owner').value,
    assigned_email: document.getElementById('f-ctrl-email').value,
    due_date: document.getElementById('f-ctrl-due').value,
  });
  if (result.error) { showToast(result.error, 'error'); return; }
  closeModal('modal-main');
  showToast('Control added!', 'success');
  await loadDashboard();
}

async function saveFramework() {
  const name = document.getElementById('f-fw-name').value.trim();
  if (!name) { showToast('Name required', 'error'); return; }
  const result = await api('POST', '/frameworks', {
    name, description: document.getElementById('f-fw-desc').value,
    color: document.getElementById('f-fw-color').value,
    type: document.getElementById('f-fw-type').value,
  });
  closeModal('modal-main');
  showToast('Framework added!', 'success');
  await loadFrameworks();
  renderSidebar();
}

async function saveReminder() {
  const email = document.getElementById('f-rm-email').value.trim();
  if (!email) { showToast('Email required', 'error'); return; }
  await api('POST', '/reminders', {
    control_id: document.getElementById('f-rm-ctrl').value,
    audit_id: state.currentAuditId,
    email, frequency: document.getElementById('f-rm-freq').value,
  });
  closeModal('modal-main');
  showToast('Reminder set!', 'success');
  loadReminders();
}

async function uploadEvidence() {
  const file = document.getElementById('ev-file').files[0];
  if (!file) { showToast('Select a file first', 'error'); return; }
  const fd = new FormData();
  fd.append('file', file);
  fd.append('control_id', document.getElementById('f-ev-ctrl').value);
  fd.append('audit_id', state.currentAuditId);
  fd.append('description', document.getElementById('f-ev-desc').value);
  fd.append('uploaded_by', document.getElementById('f-ev-by').value);
  fd.append('expires_at', document.getElementById('f-ev-expires').value);
  showToast('Uploading...', 'info');
  const result = await fetch('/api/evidence/upload', { method:'POST', body:fd }).then(r=>r.json());
  if (result.error) { showToast(result.error, 'error'); return; }
  closeModal('modal-main');
  showToast('Evidence uploaded!', 'success');
  if (result.aiResult?.summary) {
    setTimeout(()=>showToast(`AI: ${result.aiResult.summary.substring(0,80)}`, 'info'), 1000);
  }
  await loadDashboard();
}

async function importChecklist(input) {
  const file = input.files[0];
  if (!file || !state.currentAuditId) return;
  document.getElementById('import-status').innerHTML = '<div style="color:var(--accent);font-size:12px;">⏳ Parsing with AI... this may take 20-30 seconds</div>';
  const fd = new FormData();
  fd.append('file', file);
  fd.append('audit_id', state.currentAuditId);
  const result = await fetch('/api/import/checklist', { method:'POST', body:fd }).then(r=>r.json());
  if (result.error) {
    document.getElementById('import-status').innerHTML = `<div style="color:var(--red);font-size:12px;">${result.error}</div>`;
    return;
  }
  document.getElementById('import-status').innerHTML = `<div style="color:var(--green);font-size:12px;">✓ Imported ${result.inserted} controls (${result.parseMethod})</div>`;
  showToast(`${result.inserted} controls imported!`, 'success');
  await loadDashboard();
}

async function aiGenerateReqs() {
  const name = document.getElementById('f-ctrl-name').value.trim();
  if (!name) { showToast('Enter control name first', 'error'); return; }
  document.getElementById('ai-reqs-result').innerHTML = '<div style="color:var(--accent);font-size:11px;">✦ Generating...</div>';
  // Temporarily save control to get AI suggestions
  const fw = state.frameworks.find(f=>f.id===state.currentFwId);
  const fakeCtrl = { control_id: document.getElementById('f-ctrl-id').value, name, description: document.getElementById('f-ctrl-desc').value };
  const result = await api('POST', '/ai/chat', { message: `For ${fw?.name||'this framework'} control "${fakeCtrl.control_id} ${fakeCtrl.name}", list 3-5 specific evidence items an auditor would require. Be brief and specific.`, audit_id: state.currentAuditId });
  document.getElementById('ai-reqs-result').innerHTML = `<div style="background:var(--surface2);border-radius:8px;padding:12px;font-size:12px;color:var(--muted2);line-height:1.7;">${(result.reply||'').replace(/\n/g,'<br>')}</div>`;
}

// ---- UTILS ----
function showToast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = `toast ${type} show`;
  clearTimeout(t._timer);
  t._timer = setTimeout(()=>t.classList.remove('show'), 4000);
}

function escHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// Init
init();
