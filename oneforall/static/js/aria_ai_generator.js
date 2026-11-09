/* ── Init data from server ─────────────────────────────────────────────── */
var allControls     = [];
var selectedControl = null;
var lastGenerated   = '';
var currentFwName   = '';
var generatorData = document.getElementById('generatorPageData');
var docCtrlRefs     = new Set(JSON.parse(generatorData.dataset.docCtrlRefs || '[]'));
var controlsByFw    = JSON.parse(generatorData.dataset.controlsByFw || '{}');

/* ── Org name persistence ──────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function () {
  var stored = localStorage.getItem('aria_org_name');
  if (stored) document.getElementById('orgName').value = stored;
  document.getElementById('orgName').addEventListener('input', function () {
    localStorage.setItem('aria_org_name', this.value);
  });

  // Pre-fill from query params (e.g. from Control Mapping page)
  var params = new URLSearchParams(window.location.search);
  var prefillFwId = params.get('fw_id');
  var prefillRef  = params.get('control_ref');
  if (prefillFwId) {
    var fwSel = document.getElementById('fwSelect');
    fwSel.value = prefillFwId;
    if (fwSel.value === prefillFwId) {
      loadControls().then(function() {
        if (prefillRef) {
          var match = allControls.find(function(c) { return c.ref === prefillRef; });
          if (match) {
            selectControl(match.id, match.ref, match.name, match.description || '');
          }
        }
      });
    }
  }

  // PLAN-35 T10: "resumed editor" -- /aria/ai-generator?draft=<id> (the
  // resume_url a generation/revision-start response returns, and every
  // My Drafts "Resume" link) loads straight into the editor instead of
  // the pick-a-control flow.
  var resumeDraftId = params.get('draft');
  if (resumeDraftId) {
    switchTab('policy');
    AriaPolicyWorkflow.ui.loadDraftById(resumeDraftId);
  }
  AriaPolicyWorkflow.ui.refreshMyDrafts();
});

/* ── Tab switching ─────────────────────────────────────────────────────── */
function switchTab(tab) {
  document.querySelectorAll('.tab-content').forEach(function (el) {
    el.classList.remove('active');
  });
  document.getElementById('tab-' + tab).classList.add('active');
  document.querySelectorAll('.gen-tab').forEach(function (btn) {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
}

/* ── Recent documents toggle ───────────────────────────────────────────── */
function toggleRecent() {
  var list    = document.getElementById('recentList');
  var chevron = document.querySelector('.recent-chevron');
  var hidden  = list.style.display === 'none';
  list.style.display = hidden ? 'flex' : 'none';
  if (chevron) chevron.classList.toggle('open', hidden);
}

/* ── Controls loading ──────────────────────────────────────────────────── */
function esc(s) {
  if (!s && s !== 0) return '';
  var d = document.createElement('div');
  d.textContent = String(s);
  return d.innerHTML;
}

async function loadControls() {
  var sel   = document.getElementById('fwSelect');
  var fwId  = sel.value;
  currentFwName = sel.options[sel.selectedIndex]
    ? (sel.options[sel.selectedIndex].dataset.name || '') : '';

  var search = document.getElementById('ctrlSearch');
  search.disabled = !fwId;
  search.value = '';
  document.getElementById('selectedCtrl').style.display = 'none';
  document.getElementById('ctrlId').value = '';
  document.getElementById('generateBtn').disabled = true;
  document.getElementById('ctrlResults').style.display = 'none';
  selectedControl = null;
  if (!fwId) { allControls = []; return; }

  /* Use pre-loaded controls from page context first */
  allControls = controlsByFw[fwId] || [];

  if (allControls.length === 0) {
    search.placeholder = 'Seeding controls...';
    try {
      var seedResp = await fetch('/aria/api/force-seed-controls/' + fwId, { method: 'POST' });
      var seedData = await seedResp.json();
      if ((seedData.seeded || 0) + (seedData.existing || 0) > 0) {
        var r2 = await fetch('/aria/api/controls/' + fwId);
        allControls = await r2.json();
      }
    } catch (e) { console.error(e); }
  }

  search.placeholder = allControls.length > 0
    ? 'Search ' + allControls.length + ' controls...'
    : 'No controls available';

  // Enrich with IMS status if multiple active frameworks are loaded
  // (non-blocking, runs in background)
  _enrichImsStatus(fwId);
}

var _imsStatusCache = {};  // fwId → {ctrl_id: {status, mapped_fw_names}}

async function _enrichImsStatus(currentFwId) {
  try {
    // Collect all currently active framework IDs from the page context
    var allFwIds = Object.keys(controlsByFw || {}).filter(id => (controlsByFw[id]||[]).length > 0);
    if (allFwIds.length < 2) return;
    var cacheKey = allFwIds.sort().join(',');
    if (_imsStatusCache[cacheKey]) {
      _applyImsStatus(_imsStatusCache[cacheKey]);
      return;
    }
    var res = await fetch('/aria/api/control-mappings/ims-status?fw_ids=' + allFwIds.join(','));
    if (!res.ok) return;
    var data = await res.json();
    var map = {};
    ['integrated','partial','unique'].forEach(function(st){
      (data[st]||[]).forEach(function(c){ map[c.id] = {status: st, mapped_fw_names: c.mapped_fw_names||[]}; });
    });
    _imsStatusCache[cacheKey] = map;
    _applyImsStatus(map);
  } catch(e) { /* non-critical */ }
}

function _applyImsStatus(map) {
  if (!allControls || !allControls.length) return;
  allControls.forEach(function(c) {
    var s = map[c.id];
    if (s) { c.ims_status = s.status; c.mapped_fw_names = s.mapped_fw_names; }
  });
}

/* ── Control search / filter ───────────────────────────────────────────── */
function statusClass(status) {
  var s = (status || '').toLowerCase();
  if (s === 'not started')  return 'warn';
  if (s === 'in progress')  return 'info';
  if (s === 'implemented')  return 'good';
  return 'neutral';
}

/* ── IMS toggle ──────────────────────────────────────────────────────────── */
function toggleIms() {
  var on = document.getElementById('imsToggle').checked;
  document.getElementById('imsPanel').style.display = on ? 'block' : 'none';
  // Update generate button label
  var btnText = document.getElementById('genBtnText');
  if (btnText) btnText.textContent = on ? 'Generate Integrated IMS Policy' : 'Generate Policy Document';
}

function filterControls() {
  var q       = document.getElementById('ctrlSearch').value.toLowerCase();
  var results = document.getElementById('ctrlResults');
  if (!allControls.length) { results.style.display = 'none'; return; }

  var filtered = q
    ? allControls.filter(function (c) {
        return c.ref.toLowerCase().includes(q) ||
               c.name.toLowerCase().includes(q) ||
               (c.description || '').toLowerCase().includes(q);
      }).slice(0, 20)
    : allControls.slice(0, 20);

  if (!filtered.length) {
    results.innerHTML = '<div data-s="s2dd5897">No matching controls</div>';
    results.style.display = 'block';
    return;
  }

  results.innerHTML = filtered.map(function (c, idx) {
    var sClass  = statusClass(c.status);
    var hasDoc  = docCtrlRefs.has(currentFwName + '|' + c.ref);
    var docBadge = hasDoc ? '<span class="ctrl-has-doc" title="Document exists in library"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-file-text></use></svg></span>' : '';
    var statusLabel = c.status ? ('<span class="ctrl-status ctrl-status-' + sClass + '">' + esc(c.status) + '</span>') : '';
    // IMS badge
    var imsBadgeHtml = '';
    if (c.ims_status === 'integrated') {
      imsBadgeHtml = '<span data-s="s44c4256">INT</span>';
    } else if (c.ims_status === 'partial') {
      imsBadgeHtml = '<span data-s="s896a448">PARTIAL</span>';
    } else if (c.ims_status === 'unique') {
      imsBadgeHtml = '<span data-s="sbb90e7d">UNIQUE</span>';
    }
    return '<div class="ctrl-result" data-idx="' + idx + '">' +
      '<div class="ctrl-result-top">' +
        '<span class="ctrl-ref">' + esc(c.ref) + '</span>' +
        statusLabel + docBadge + (imsBadgeHtml ? ' ' + imsBadgeHtml : '') +
      '</div>' +
      '<div class="ctrl-result-name">' + esc(c.name) + '</div>' +
    '</div>';
  }).join('');

  results._filtered = filtered;
  results.querySelectorAll('.ctrl-result').forEach(function (el) {
    el.addEventListener('click', function () {
      var ctrl = results._filtered[parseInt(el.dataset.idx, 10)];
      selectControl(ctrl.id, ctrl.ref, ctrl.name, ctrl.description || '');
    });
  });
  results.style.display = 'block';
}

document.addEventListener('DOMContentLoaded', function () {
  var el = document.getElementById('ctrlSearch');
  if (el) {
    el.addEventListener('focus', filterControls);
    el.addEventListener('click', filterControls);
  }
});
document.addEventListener('click', function (e) {
  if (!e.target.closest('#ctrlSearch') && !e.target.closest('#ctrlResults')) {
    document.getElementById('ctrlResults').style.display = 'none';
  }
});

function selectControl(id, ref, name, desc) {
  document.getElementById('ctrlId').value = id;
  document.getElementById('ctrlSearch').value = ref + ': ' + name;
  document.getElementById('ctrlResults').style.display = 'none';
  document.getElementById('selectedCtrl').style.display = 'block';
  document.getElementById('selRef').textContent  = ref;
  document.getElementById('selName').textContent = name;
  document.getElementById('selDesc').textContent = desc;
  document.getElementById('generateBtn').disabled = false;
  selectedControl = { id: id, ref: ref, name: name };

  // IMS status indicator
  var ctrl = (allControls||[]).find(function(c){ return c.id == id; });
  var imsEl = document.getElementById('selImsStatus');
  if (imsEl && ctrl && ctrl.ims_status) {
    var badges = {
      integrated: { bg:'#16a34a', label:'✓ Integrated Control', msg:'Can generate one document covering all mapped frameworks' },
      partial:    { bg:'#d97706', label:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg> Partial Match', msg:'Mapped to some but not all selected frameworks' },
      unique:     { bg:'#dc2626', label:'✕ Framework-Specific', msg:'Unique to this framework, document will not be integrated' },
    };
    var b = badges[ctrl.ims_status];
    if (b) {
      imsEl.innerHTML = '<div data-sv="display:flex;align-items:center;gap:8px;padding:8px 10px;background:' + b.bg + '22;border:1px solid ' + b.bg + '44;border-radius:6px;margin-top:8px;">' +
        '<span data-sv="background:'+b.bg+';color:#fff;border-radius:4px;padding:2px 8px;font-size:10px;font-weight:800;letter-spacing:.5px;">'+b.label+'</span>' +
        '<span data-s="s112ff04">'+b.msg+'</span>' +
        (ctrl.mapped_fw_names && ctrl.mapped_fw_names.length ? ' <span data-s="sb569cab">↔ ' + ctrl.mapped_fw_names.join(', ') + '</span>' : '') +
        '</div>';
      imsEl.style.display = 'block';
      // Show/hide IMS toggle based on status
      var imsToggleWrap = document.getElementById('imsToggle') ? document.getElementById('imsToggle').closest('.form-group') : null;
      if (imsToggleWrap) {
        imsToggleWrap.style.display = ctrl.ims_status !== 'unique' ? 'block' : 'none';
      }
    } else {
      imsEl.style.display = 'none';
    }
  }
}

/* ── Policy generation ─────────────────────────────────────────────────── */
var policyTrace = null;
function setPolicyLoading(on, msg) {
  document.getElementById('emptyState').style.display   = on ? 'none'  : 'none';
  document.getElementById('outputBody').style.display   = on ? 'none'  : 'none';
  document.getElementById('metaBar').style.display      = on ? 'none'  : 'none';
  document.getElementById('outputActions').style.display = on ? 'none' : 'none';
  document.getElementById('loadingState').classList.toggle('active', on);
  if (policyTrace) { policyTrace.destroy(); policyTrace = null; }
  if (on) {
    policyTrace = window.ThinkingTrace.open(document.getElementById('loadingTraceMount'), {
      variant: 'steps',
      activeLabel: msg || 'Generating your policy document',
      rows: [
        { primary: 'Reading the control requirements' },
        { primary: 'Drafting the document' },
        { primary: 'Applying your formatting and tone' }
      ]
    });
  }
}

/* ── Guide the AI (optional custom instructions) ───────────────────────── */
var ariaCustomInstructions = '';

async function openAriaGuidance() {
  var guidance = await window.openAiGuidanceDialog({
    title: 'Guide the AI Policy Generator',
    placeholder: 'e.g. Emphasise remote work scenarios, keep it under 2 pages, reference our existing incident response policy...'
  });
  if (guidance === null) return; // skipped/cancelled - leave prior guidance (if any) untouched
  ariaCustomInstructions = guidance;
  var btnText = document.getElementById('guideAiBtnText');
  if (btnText) {
    btnText.innerHTML = guidance ? '<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-target></use></svg> Guidance added ✓ (edit)' : '<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-target></use></svg> Guide the AI (optional)';
  }
}

async function generatePolicy() {
  var ctrlId  = document.getElementById('ctrlId').value;
  var orgName = document.getElementById('orgName').value || 'Your Organisation';
  var docType = document.getElementById('docTypeOverride').value;
  if (!ctrlId) { if (typeof showToast === 'function') showToast('Select a control first.', 'warn'); return; }

  switchTab('policy');
  setPolicyLoading(true, 'Generating your ' + (selectedControl ? selectedControl.ref : '') + ' policy document...');
  document.getElementById('generateBtn').disabled = true;
  document.getElementById('genBtnText').textContent = 'Generating...';

  var form = new FormData();
  form.append('control_id', ctrlId);
  form.append('org_name', orgName);
  if (docType) form.append('doc_type_override', docType);
  if (ariaCustomInstructions) form.append('custom_instructions', ariaCustomInstructions);

  // IMS: pass additional framework if integrated mode is enabled
  var imsEnabled = document.getElementById('imsToggle') && document.getElementById('imsToggle').checked;
  var imsFwId    = imsEnabled && document.getElementById('imsFramework') ? document.getElementById('imsFramework').value : '';
  if (imsFwId) form.append('integrated_framework_id', imsFwId);

  if (imsEnabled && imsFwId) {
    var imsName = document.getElementById('imsFramework').options[document.getElementById('imsFramework').selectedIndex].text;
    setPolicyLoading(true, 'Generating integrated IMS policy covering ' + (selectedControl ? selectedControl.ref : '') + ' across multiple frameworks…');
  }

  var start = Date.now();
  try {
    var resp = await fetch('/aria/api/generate-policy', { method: 'POST', body: form });
    var data = await resp.json();
    var elapsed = ((Date.now() - start) / 1000).toFixed(1);

    setPolicyLoading(false);

    if (data.success) {
      document.getElementById('rawContent').textContent = data.content;
      document.getElementById('metaBar').style.display      = 'flex';
      document.getElementById('outputTitle').textContent    =
        (selectedControl ? selectedControl.ref + ': ' + selectedControl.name : 'Generated Document');
      document.getElementById('metaModel').textContent = data.model || '—';
      document.getElementById('metaIn').textContent    = data.input_tokens || '—';
      document.getElementById('metaOut').textContent   = data.output_tokens || '—';
      document.getElementById('metaTime').textContent  = 'Generated in ' + elapsed + 's';
      // Section 11: "do not show 'Saved to library' until confirmation
      // succeeds" -- this is an editable draft, not a library document yet.
      document.getElementById('metaSaved').textContent = '✓ Draft saved';
      if (data.draft_id) {
        await AriaPolicyWorkflow.ui.loadDraftById(data.draft_id);
        AriaPolicyWorkflow.ui.refreshMyDrafts();
      }
      if (typeof showToast === 'function') showToast('Draft generated and saved. Review and edit below.');
    } else {
      document.getElementById('emptyState').style.display = 'flex';
      if (typeof showToast === 'function') showToast(data.error || 'Generation failed', 'error');
    }
  } catch (e) {
    setPolicyLoading(false);
    document.getElementById('emptyState').style.display = 'flex';
    if (typeof showToast === 'function') showToast('Network error. Is the server running?', 'error');
  }
  document.getElementById('generateBtn').disabled = false;
  document.getElementById('genBtnText').textContent = 'Generate Policy Document';
}

/* ── Gap analysis ──────────────────────────────────────────────────────── */
var gapTrace = null;
function setGapLoading(on) {
  document.getElementById('gapLoading').style.display = on ? 'block' : 'none';
  if (gapTrace) { gapTrace.destroy(); gapTrace = null; }
  if (on) {
    gapTrace = window.ThinkingTrace.open(document.getElementById('gapTraceMount'), {
      variant: 'steps',
      activeLabel: 'Analysing compliance gaps',
      rows: [
        { primary: 'Comparing controls against the framework' },
        { primary: 'Identifying gaps and partial coverage' },
        { primary: 'Writing recommendations' }
      ]
    });
  }
}

async function generateGapAnalysis() {
  var fwId = document.getElementById('gapFwSelect').value;
  if (!fwId) { if (typeof showToast === 'function') showToast('Select a framework first.', 'warn'); return; }

  document.getElementById('gapEmpty').style.display   = 'none';
  document.getElementById('gapContent').style.display = 'none';
  setGapLoading(true);
  document.getElementById('gapBtnText').textContent   = 'Analysing...';

  var form = new FormData();
  form.append('framework_id', fwId);

  try {
    var resp = await fetch('/aria/api/generate-gap-analysis', { method: 'POST', body: form });
    var data = await resp.json();
    setGapLoading(false);
    document.getElementById('gapBtnText').textContent   = 'Run Gap Analysis';

    if (data.success) {
      AriaMarkdown.renderInto(document.getElementById('gapContent'), data.content);
      document.getElementById('gapContent').style.display = 'block';
      if (typeof showToast === 'function') showToast('Gap analysis complete!');
    } else {
      document.getElementById('gapEmpty').style.display = 'block';
      document.getElementById('gapEmpty').textContent   = data.error || 'Analysis failed.';
      if (typeof showToast === 'function') showToast(data.error || 'Error', 'error');
    }
  } catch (e) {
    setGapLoading(false);
    document.getElementById('gapBtnText').textContent   = 'Run Gap Analysis';
    document.getElementById('gapEmpty').style.display   = 'block';
    if (typeof showToast === 'function') showToast('Network error', 'error');
  }
}

/* ── Export functions ──────────────────────────────────────────────────── */
function copyToClipboard() {
  navigator.clipboard.writeText(lastGenerated)
    .then(function () { if (typeof showToast === 'function') showToast('Copied to clipboard!'); });
}

async function downloadWord() {
  var ctrlId  = document.getElementById('ctrlId').value;
  var orgName = document.getElementById('orgName').value || 'Your Organisation';
  if (!lastGenerated) { if (typeof showToast === 'function') showToast('Generate a policy first.', 'warn'); return; }
  if (typeof showToast === 'function') showToast('Building Word document...');

  try {
    var form = new FormData();
    form.append('control_id', ctrlId || '1');
    form.append('content', lastGenerated);
    form.append('org_name', orgName);

    var res = await fetch('/aria/api/export-word', { method: 'POST', body: form });
    if (!res.ok) throw new Error('Server returned ' + res.status);

    var cd = res.headers.get('Content-Disposition') || '';
    var match = cd.match(/filename="?([^"]+)"?/);
    var filename = match ? match[1] : 'ARIA_Policy.docx';

    var blob = await res.blob();
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function() { URL.revokeObjectURL(url); }, 5000);

    if (typeof showToast === 'function') showToast('Word document downloaded!');
  } catch(e) {
    if (typeof showToast === 'function') showToast('Download failed: ' + e.message, 'error');
  }
}

function downloadMd() {
  var blob = new Blob([lastGenerated], { type: 'text/markdown' });
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'ARIA_' + ((selectedControl ? selectedControl.ref : 'policy').replace(/\./g, '_')) + '_Policy.md';
  a.click();
}

function printPolicy() {
  var content = document.getElementById('outputBody').innerHTML;
  var w = window.open('', '_blank');
  // The blank window inherits this page's security policy, so its <style> needs this page's nonce.
  var nonced = document.querySelector('style[nonce]');
  var nonce = nonced ? String(nonced.nonce).replace(/[^A-Za-z0-9_-]/g, '') : '';
  w.document.write('<html><head><title>Policy Document</title>' +
    '<style nonce="' + nonce + '">body{font-family:Arial,sans-serif;max-width:800px;margin:40px auto;color:#1a1a2e;line-height:1.7}' +
    'h1{font-size:22px}h2{font-size:16px;margin-top:24px;border-bottom:1px solid #ccc;padding-bottom:4px;color:#1E3A5F}' +
    'p{margin-bottom:10px}ul,ol{margin:8px 0 12px 20px}li{margin-bottom:4px}' +
    'code{background:#f4f4f4;padding:2px 6px;border-radius:3px;font-size:12px}' +
    '@media print{body{margin:20px}}</style></head>' +
    '<body>' + content + '</body></html>');
  w.document.close();
  w.print();
}

document.getElementById('fwSelect').addEventListener('change', loadControls);
document.getElementById('imsToggle').addEventListener('change', toggleIms);
document.getElementById('ctrlSearch').addEventListener('input', filterControls);
document.getElementById('draftEditor').addEventListener('input', function () {
  AriaPolicyWorkflow.ui.onEditorInput();
});
document.addEventListener('click', function (event) {
  var tab = event.target.closest('.gen-tab[data-tab]');
  if (tab) {
    if (tab.dataset.tab === 'policy' || tab.dataset.tab === 'gap') switchTab(tab.dataset.tab);
    return;
  }
  var editorView = event.target.closest('[data-editor-view]');
  if (editorView) {
    if (editorView.dataset.editorView === 'edit' || editorView.dataset.editorView === 'preview') {
      AriaPolicyWorkflow.ui.switchEditorView(editorView.dataset.editorView);
    }
    return;
  }
  var button = event.target.closest('[data-generator-action]');
  if (!button) return;
  switch (button.dataset.generatorAction) {
    case 'guidance': openAriaGuidance(); break;
    case 'generate': generatePolicy(); break;
    case 'drafts': AriaPolicyWorkflow.ui.toggleMyDrafts(); break;
    case 'recent': toggleRecent(); break;
    case 'copy': copyToClipboard(); break;
    case 'download-md': downloadMd(); break;
    case 'download-word': downloadWord(); break;
    case 'print': printPolicy(); break;
    case 'save-draft': AriaPolicyWorkflow.ui.saveDraft(); break;
    case 'build-draft': AriaPolicyWorkflow.ui.buildDraft(); break;
    case 'back-edit': AriaPolicyWorkflow.ui.backToEditing(); break;
    case 'confirm-draft': AriaPolicyWorkflow.ui.confirmDraft(); break;
    case 'gap-analysis': generateGapAnalysis(); break;
  }
});
document.addEventListener('keydown', function (event) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  var heading = event.target.closest('.recent-header[data-generator-action]');
  if (!heading) return;
  event.preventDefault();
  heading.click();
});
