const CONFIDENCE_COLORS = { equivalent:'var(--green-status)', related:'var(--amber)', partial:'var(--amber)', covers:'var(--accent)', manual:'var(--accent)' };

// ── Enable/disable auto-map button based on selection ───────────────────────
document.getElementById('fwSelector').addEventListener('change', function(){
  const count = Array.from(this.selectedOptions).length;
  const generate = document.getElementById('autoGenBtn');
  if (generate) generate.disabled = count < 2;
});

// ── Helper: parse JSON response safely ───────────────────────────────────────
async function safeJson(res, label) {
  var ct = res.headers.get('content-type') || '';
  if (!ct.includes('application/json')) {
    throw new Error(label + ' returned HTTP ' + res.status + ' (not JSON). Check server logs.');
  }
  return await res.json();
}

// ── Auto-map selected frameworks ─────────────────────────────────────────────
async function runAutoMap() {
  const sel = document.getElementById('fwSelector');
  const fwIds = Array.from(sel.selectedOptions).map(o => parseInt(o.value));
  if (fwIds.length < 2) { if(typeof showToast==='function') showToast('Select at least 2 frameworks', 'error'); return; }

  const useAi = document.getElementById('useAiToggle').checked;

  document.getElementById('progressWrap').style.display = 'block';
  document.getElementById('autoGenBtn').disabled = true;
  document.getElementById('progressMsg').textContent = useAi
    ? 'Running text matching + AI semantic analysis... (this may take a minute)'
    : 'Running text matching...';

  try {
    const genRes = await fetch('/aria/api/control-mappings/auto-generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ framework_ids: fwIds, use_ai: useAi })
    });
    const genData = await safeJson(genRes, 'Auto-generate');
    if (!genData.ok) {
      if(typeof showToast==='function') showToast(genData.error || 'Auto-mapping failed', 'error');
      return;
    }

    document.getElementById('progressMsg').textContent = 'Proposed ' + genData.created + ' control pairs for human review.';

    await loadImsStatus(fwIds);

    if(typeof showToast==='function')
      showToast('Auto-mapping complete: ' + genData.created + ' suggestions awaiting review (' + genData.ai_calls + ' AI calls)');
    await loadMappingProposals();
  } catch(e) {
    if(typeof showToast==='function') showToast('Error: ' + e.message, 'error');
  } finally {
    document.getElementById('progressWrap').style.display = 'none';
    document.getElementById('autoGenBtn').disabled = false;
  }
}

// ── View existing mappings only ───────────────────────────────────────────────
async function viewExisting() {
  const sel = document.getElementById('fwSelector');
  const fwIds = Array.from(sel.selectedOptions).map(o => parseInt(o.value));
  if (fwIds.length < 2) { if(typeof showToast==='function') showToast('Select at least 2 frameworks first', 'error'); return; }
  await loadImsStatus(fwIds);
}

async function loadMappingProposals() {
  const list = document.getElementById('mappingProposalList');
  if (!list) return;
  try {
    const response = await fetch('/aria/api/control-mappings');
    const data = await safeJson(response, 'Mapping proposals');
    if (!response.ok) throw new Error(data.error || 'Could not load proposals');
    const pending = (data.items || []).filter(item => item.mapping_type === 'proposed');
    list.innerHTML = pending.length ? pending.map(item => {
      let proposal = {};
      try { proposal = JSON.parse(item.notes || '{}'); } catch (_) {}
      const own = Number(item.created_by) === Number(list.dataset.currentUserId);
      const mappingId = Number(item.id);
      if (!Number.isSafeInteger(mappingId) || mappingId < 1) return '';
      return `<div style="border-top:1px solid var(--border);padding:12px 0;">
        <div><strong>${esc(item.source_ref)} ${esc(item.source_name)}</strong> to <strong>${esc(item.target_ref)} ${esc(item.target_name)}</strong></div>
        <div style="color:var(--muted);margin:5px 0;">Suggested ${esc(proposal.suggested_type || '')}; ${esc(proposal.method || 'text')} match; confidence ${Number(item.confidence || 0).toFixed(2)}</div>
        ${own ? '<span>Awaiting a different reviewer</span>' : `<label>Review reason <input id="mapping-reason-${mappingId}" maxlength="500" style="width:min(100%,420px);padding:6px;border:1px solid var(--border);border-radius:5px;"></label>
          <button type="button" class="btn btn-secondary js-review-mapping" data-mapping-id="${mappingId}" data-decision="accept">Accept</button>
          <button type="button" class="btn btn-secondary js-review-mapping" data-mapping-id="${mappingId}" data-decision="reject">Reject</button>`}
      </div>`;
    }).join('') : 'No proposals await review.';
  } catch (error) { list.textContent = error.message || 'Could not load proposals'; }
}

async function reviewMapping(id, decision) {
  if (!Number.isSafeInteger(id) || id < 1 || !['accept', 'reject'].includes(decision)) return;
  const reason = document.getElementById('mapping-reason-' + id)?.value.trim() || '';
  if (reason.length < 10) { if (typeof showToast === 'function') showToast('Record a reason of at least 10 characters', 'error'); return; }
  const response = await fetch(`/aria/api/control-mappings/${id}/review`, {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({decision, reason})
  });
  const data = await safeJson(response, 'Mapping review');
  if (!response.ok) { if (typeof showToast === 'function') showToast(data.error || 'Review failed', 'error'); return; }
  await loadMappingProposals();
  const selected = Array.from(document.getElementById('fwSelector').selectedOptions).map(option => Number(option.value));
  if (selected.length >= 2) await loadImsStatus(selected);
}

loadMappingProposals();

// ── Load and render IMS status ────────────────────────────────────────────────
async function loadImsStatus(fwIds) {
  const res  = await fetch('/aria/api/control-mappings/ims-status?fw_ids=' + fwIds.join(','));
  const data = await safeJson(res, 'IMS status');
  if (data.error) throw new Error(data.error);

  const st = data.stats || {};
  document.getElementById('statsStrip').style.display = 'block';
  document.getElementById('sTotal').textContent  = st.total || 0;
  document.getElementById('sInt').textContent    = st.integrated || 0;
  document.getElementById('sPart').textContent   = st.partial || 0;
  document.getElementById('sUniq').textContent   = st.unique || 0;
  document.getElementById('sEffort').textContent = (st.effort_saved_pct || 0) + '%';

  // Integrated
  document.getElementById('intCount').textContent = (data.integrated||[]).length;
  document.getElementById('intList').innerHTML = renderCtrlList(data.integrated || [], 'integrated');
  document.getElementById('intSection').style.display = 'block';

  // Partial
  document.getElementById('partCount').textContent = (data.partial||[]).length;
  document.getElementById('partList').innerHTML = renderCtrlList(data.partial || [], 'partial');
  document.getElementById('partSection').style.display = (data.partial||[]).length ? 'block' : 'none';

  // Unique
  document.getElementById('uniqCount').textContent = (data.unique||[]).length;
  document.getElementById('uniqList').innerHTML = renderCtrlList(data.unique || [], 'unique');
  document.getElementById('uniqSection').style.display = (data.unique||[]).length ? 'block' : 'none';
}

var _activeCardEl = null;
document.addEventListener('click', function(event) {
  var card = event.target.closest('.ctrl-map-card');
  if (!card || event.target.closest('.ctrl-actions')) return;
  toggleCardActions(card, Number(card.dataset.controlId), card.dataset.frameworkName,
    card.dataset.controlRef, card.dataset.controlName,
    Number(card.dataset.frameworkId), card.dataset.hasDoc === 'true');
});

function renderCtrlList(items, status) {
  if (!items.length) return '<div style="padding:16px;color:var(--muted);font-size:13px;font-style:italic;">None</div>';
  return items.map(c => {
    var docBadge = c.has_doc
      ? '<span class="ctrl-doc-badge" title="Document exists"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-file-text></use></svg> Doc</span>'
      : '';
    return `
    <div class="ctrl-map-card" data-control-id="${Number(c.id)}" data-framework-name="${esc(c.fw_name||'')}" data-control-ref="${esc(c.ref||'')}" data-control-name="${esc(c.name||'')}" data-framework-id="${Number(c.framework_id)||0}" data-has-doc="${c.has_doc?'true':'false'}">
      <div style="flex:1;min-width:0;">
        <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-bottom:5px;">
          <span class="fw-chip" title="${esc(c.fw_name||'')}">${esc((c.fw_name||'').slice(0,14))||'?'}</span>
          <span class="fw-chip" style="color:var(--accent)">[${esc(c.ref||'')}]</span>
          <span class="ims-${status}" style="font-size:9px;">${status.toUpperCase()}</span>
          ${docBadge}
        </div>
        <div style="font-size:13px;font-weight:600;color:var(--text);margin-bottom:3px;">${esc(c.name||'')}</div>
        ${c.mapped_fw_names && c.mapped_fw_names.length
          ? '<div style="font-size:11px;color:var(--muted);">&#8596; '+c.mapped_fw_names.map(n=>'<span class="fw-chip" style="font-size:10px;">'+esc(n)+'</span>').join(' ')+'</div>'
          : ''}
        <div class="ctrl-actions" id="actions-${Number(c.id)||0}" style="display:none;"></div>
      </div>
    </div>`;
  }).join('');
}

function toggleCardActions(el, ctrlId, fwName, ref, name, fwId, hasDoc) {
  if (_activeCardEl && _activeCardEl !== el) {
    _activeCardEl.classList.remove('active-card');
    var prev = _activeCardEl.querySelector('.ctrl-actions');
    if (prev) prev.style.display = 'none';
  }
  var actions = el.querySelector('.ctrl-actions');
  var isOpen = el.classList.contains('active-card');
  if (isOpen) {
    el.classList.remove('active-card');
    actions.style.display = 'none';
    _activeCardEl = null;
    return;
  }
  el.classList.add('active-card');
  _activeCardEl = el;

  var genUrl = '/aria/ai-generator?fw_id=' + fwId + '&control_ref=' + encodeURIComponent(ref);
  var viewUrl = '/aria/documents?search=' + encodeURIComponent(ref);
  var fwUrl = '/aria/framework/' + fwId + '?search=' + encodeURIComponent(ref);

  var html = '<a class="ctrl-action-btn" href="' + genUrl + '" title="Generate a policy for this control">' +
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>' +
    'Generate Policy</a>';

  if (hasDoc) {
    html += '<a class="ctrl-action-btn" href="' + viewUrl + '" title="View existing document">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>' +
      'View Document</a>';
  }

  html += '<a class="ctrl-action-btn" href="' + fwUrl + '" title="View in framework detail">' +
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>' +
    'View in Framework</a>';

  actions.innerHTML = html;
  actions.style.display = 'flex';
}

// ── Manual linking helpers ────────────────────────────────────────────────────
async function loadControls(side) {
  const fwSel   = document.getElementById('fw'+side);
  const ctrlSel = document.getElementById('ctrl'+side);
  const fwId    = fwSel.value;
  ctrlSel.innerHTML = '<option value="">Loading...</option>';
  ctrlSel.disabled  = true;
  if (!fwId) { ctrlSel.innerHTML = '<option value="">Select control...</option>'; return; }
  const res  = await fetch('/aria/api/control-mappings/frameworks/'+fwId+'/controls');
  const data = await res.json();
  ctrlSel.innerHTML = '<option value="">Select control...</option>' +
    data.items.filter(c => Number.isSafeInteger(Number(c.id)) && Number(c.id) > 0)
      .map(c=>`<option value="${Number(c.id)}">[${esc(c.ref)}] ${esc(c.name)}</option>`).join('');
  ctrlSel.disabled = false;
}

async function createMapping() {
  const srcId = document.getElementById('ctrlA').value;
  const tgtId = document.getElementById('ctrlB').value;
  const type  = document.getElementById('mappingType').value;
  const notes = document.getElementById('mappingNotes').value;
  if (!srcId || !tgtId) { if(typeof showToast==='function') showToast('Select a control from both frameworks', 'error'); return; }
  const res  = await fetch('/aria/api/control-mappings', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({source_control_id:srcId,target_control_id:tgtId,mapping_type:type,notes})
  });
  const data = await res.json();
  if(data.ok){ if(typeof showToast==='function') showToast('Controls linked'); document.getElementById('mappingNotes').value=''; }
  else { if(typeof showToast==='function') showToast(data.error||'Error','error'); }
}

function clearResults() {
  document.getElementById('statsStrip').style.display = 'none';
  document.getElementById('intSection').style.display = 'none';
  document.getElementById('partSection').style.display = 'none';
  document.getElementById('uniqSection').style.display = 'none';
  document.getElementById('intList').innerHTML = '';
  document.getElementById('partList').innerHTML = '';
  document.getElementById('uniqList').innerHTML = '';
  _activeCardEl = null;
}

function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

document.getElementById('autoGenBtn')?.addEventListener('click', runAutoMap);
document.getElementById('viewExistingMappings')?.addEventListener('click', viewExisting);
document.getElementById('refreshMappingProposals')?.addEventListener('click', loadMappingProposals);
document.getElementById('clearMappingResults')?.addEventListener('click', clearResults);
document.getElementById('fwA')?.addEventListener('change', () => loadControls('A'));
document.getElementById('fwB')?.addEventListener('change', () => loadControls('B'));
document.getElementById('createManualMapping')?.addEventListener('click', createMapping);
document.getElementById('mappingProposalList')?.addEventListener('click', event => {
  const button = event.target.closest('.js-review-mapping');
  if (!button || !event.currentTarget.contains(button)) return;
  reviewMapping(Number(button.dataset.mappingId), button.dataset.decision);
});
