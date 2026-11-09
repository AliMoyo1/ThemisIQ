// ── Framework checkbox + control ref logic ──────────────────────────────────
var _controlCache = {};

function getCheckedFwIds() {
  var ids = [];
  document.querySelectorAll('.add-fw-cb:checked').forEach(function(cb) {
    ids.push(cb.getAttribute('data-fw-id'));
  });
  return ids;
}
function getCheckedFwNames() {
  var names = [];
  document.querySelectorAll('.add-fw-cb:checked').forEach(function(cb) {
    names.push(cb.value);
  });
  return names;
}

var _ctrlOptions = [];
var _pickerSelected = { add: [], edit: [] };

async function onAddFwChange() {
  _ctrlOptions = [];
  _pickerSelected.add = [];
  renderPickerTags('add');
  document.getElementById('add-control-search').value = '';
  document.getElementById('add-control-search').placeholder = 'Loading controls...';
  document.getElementById('add-control-ref').value = '';
  var fwIds = getCheckedFwIds();
  if (!fwIds.length) {
    document.getElementById('add-control-search').placeholder = 'Select a framework first';
    return;
  }
  await _loadControlsForFwIds(fwIds);
  document.getElementById('add-control-search').placeholder = 'Search ' + _ctrlOptions.length + ' controls...';
}

async function _loadControlsForFwIds(fwIds) {
  _ctrlOptions = [];
  for (var i = 0; i < fwIds.length; i++) {
    var fid = fwIds[i];
    if (!_controlCache[fid]) {
      try {
        var res = await fetch('/aria/api/controls/' + fid);
        _controlCache[fid] = await res.json();
      } catch(e) { _controlCache[fid] = []; }
    }
    var fwName = '';
    var cb = document.querySelector('.add-fw-cb[data-fw-id="'+fid+'"]');
    if (cb) fwName = cb.value;
    _controlCache[fid].forEach(function(c) {
      var label = c.ref + ' - ' + c.name;
      if (fwIds.length > 1) label += ' (' + fwName + ')';
      _ctrlOptions.push({ ref: c.ref, name: c.name, fw: fwName, label: label });
    });
  }
}

async function _loadControlsForFwNames(fwNames) {
  _ctrlOptions = [];
  var cbs = document.querySelectorAll('.add-fw-cb');
  var fwIds = [];
  fwNames.forEach(function(name) {
    cbs.forEach(function(cb) {
      if (cb.value.trim() === name.trim()) fwIds.push(cb.getAttribute('data-fw-id'));
    });
  });
  await _loadControlsForFwIds(fwIds);
}

function showPickerDD(prefix) { filterPickerDD(prefix); }
function hidePickerDD(prefix) {
  setTimeout(function() { document.getElementById(prefix + '-ctrl-dropdown').style.display = 'none'; }, 180);
}

function filterPickerDD(prefix) {
  var q = document.getElementById(prefix + '-control-search').value.toLowerCase();
  var dd = document.getElementById(prefix + '-ctrl-dropdown');
  dd.innerHTML = '';
  if (!_ctrlOptions.length) {
    dd.innerHTML = '<div data-s="sce44318">No controls loaded</div>';
    dd.style.display = '';
    return;
  }
  var selRefs = _pickerSelected[prefix].map(function(r) { return r.ref; });
  var matches = _ctrlOptions.filter(function(c) {
    if (selRefs.indexOf(c.ref) !== -1) return false;
    return (c.ref + ' ' + c.name + ' ' + c.fw).toLowerCase().indexOf(q) !== -1;
  });
  if (!matches.length) {
    dd.innerHTML = '<div data-s="sce44318">' +
      (selRefs.length ? 'All matching controls selected' : 'No matching controls') + '</div>';
    dd.style.display = '';
    return;
  }
  matches.forEach(function(c) {
    var div = document.createElement('div');
    div.style.cssText = 'padding:7px 10px;font-size:13px;cursor:pointer';
    div.textContent = c.label;
    div.addEventListener('mouseenter', function() { div.style.background = 'var(--hover-bg, rgba(180,130,60,.1))'; });
    div.addEventListener('mouseleave', function() { div.style.background = ''; });
    div.addEventListener('mousedown', function(e) {
      e.preventDefault();
      addPickerTag(prefix, c.ref, c.label);
    });
    dd.appendChild(div);
  });
  dd.style.display = '';
}

function addPickerTag(prefix, ref, label) {
  var state = _pickerSelected[prefix];
  if (state.find(function(r) { return r.ref === ref; })) return;
  state.push({ ref: ref, label: label });
  renderPickerTags(prefix);
  document.getElementById(prefix + '-control-search').value = '';
}

function removePickerTag(prefix, ref) {
  _pickerSelected[prefix] = _pickerSelected[prefix].filter(function(r) { return r.ref !== ref; });
  renderPickerTags(prefix);
}

function renderPickerTags(prefix) {
  var container = document.getElementById(prefix + '-ctrl-tags');
  container.innerHTML = '';
  _pickerSelected[prefix].forEach(function(r) {
    var tag = document.createElement('span');
    tag.style.cssText = 'display:inline-flex;align-items:center;gap:4px;padding:3px 8px 3px 10px;background:var(--accent-bg,#fef6ef);border:1px solid var(--border);border-radius:12px;font-size:11px;font-weight:600;color:var(--text)';
    tag.appendChild(document.createTextNode(r.label));
    var x = document.createElement('span');
    x.textContent = '×';
    x.style.cssText = 'cursor:pointer;color:var(--muted);font-size:14px;line-height:1;margin-left:2px';
    x.addEventListener('click', function() { removePickerTag(prefix, r.ref); });
    tag.appendChild(x);
    container.appendChild(tag);
  });
  document.getElementById(prefix + '-control-ref').value = _pickerSelected[prefix].map(function(r) { return r.ref; }).join(',');
}

// ── Review cycle auto-calc ──────────────────────────────────────────────────
function calcReviewDate() {
  var eff = document.getElementById('add-effective-date').value;
  var cycle = document.getElementById('add-review-cycle').value;
  var hint = document.getElementById('add-review-hint');
  if (!eff || !cycle) { hint.textContent = ''; return; }
  var d = new Date(eff + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + parseInt(cycle, 10));
  var iso = d.toISOString().split('T')[0];
  document.getElementById('add-review-date').value = iso;
  var labels = {'90':'Quarterly','182':'Bi-annually','365':'Annually'};
  hint.textContent = labels[cycle] + ' from effective date';
}

function calcEditReviewDate() {
  var eff = document.getElementById('edit-effective-date').value;
  var cycle = document.getElementById('edit-review-cycle').value;
  var hint = document.getElementById('edit-review-hint');
  if (!eff || !cycle) { hint.textContent = ''; return; }
  var d = new Date(eff + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + parseInt(cycle, 10));
  var iso = d.toISOString().split('T')[0];
  document.getElementById('edit-review-date').value = iso;
  var labels = {'90':'Quarterly','182':'Bi-annually','365':'Annually'};
  hint.textContent = labels[cycle] + ' from effective date';
}

// Init control dropdown on page load
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(onAddFwChange, 300);
});

// ── Drop zone logic ─────────────────────────────────────────────────────────
var _addFile = null;

function dzDragOver(e) {
  e.preventDefault();
  document.getElementById('dropZone').classList.add('dz-over');
}
function dzDragLeave(e) {
  document.getElementById('dropZone').classList.remove('dz-over');
}
function dzDrop(e) {
  e.preventDefault();
  document.getElementById('dropZone').classList.remove('dz-over');
  var files = e.dataTransfer.files;
  if (files && files[0]) dzSetFile(files[0]);
}
function dzFileSelected(input) {
  if (input.files && input.files[0]) dzSetFile(input.files[0]);
}
function dzSetFile(file) {
  _addFile = file;
  document.getElementById('dzEmpty').style.display = 'none';
  document.getElementById('dzSelected').style.display = 'flex';
  document.getElementById('dzFileName').textContent = file.name;
  var btn = document.getElementById('analyseBtn');
  var extractable = /\.(docx|pdf)$/i.test(file.name);
  btn.disabled = !extractable;
  btn.style.opacity = extractable ? '1' : '.45';
  document.getElementById('analyseStatus').textContent = extractable
    ? 'Click "Extract Metadata" for source-grounded suggestions; review every field.'
    : 'DOC and ODT are manual entries here. Convert to DOCX for guided extraction and review.';
}
function dzClearFile(e) {
  e.stopPropagation();
  _addFile = null;
  document.getElementById('dzEmpty').style.display = '';
  document.getElementById('dzSelected').style.display = 'none';
  document.getElementById('dzFileName').textContent = '';
  document.getElementById('addFileInput').value = '';
  var btn = document.getElementById('analyseBtn');
  btn.disabled = true;
  btn.style.opacity = '.45';
  document.getElementById('analyseStatus').textContent = 'Select a file to auto-fill details from the document';
}

// ── Metadata extraction ─────────────────────────────────────────────────────
async function analyseFile() {
  if (!_addFile) return;
  var btn = document.getElementById('analyseBtn');
  var statusEl = document.getElementById('analyseStatus');
  btn.disabled = true;
  btn.style.opacity = '.6';
  statusEl.innerHTML = '<span data-s="sa805525">Extracting metadata...</span>';

  var form = new FormData();
  form.append('file', _addFile);

  try {
    var res = await fetch('/aria/documents/parse-upload', { method: 'POST', body: form });
    var data = await res.json();
    if (!data.ok) {
      statusEl.innerHTML = '<span data-s="sf9408e8">Could not extract: ' + esc(data.error || 'unknown error') + '</span>';
      return;
    }

    var filled = [];
    if (data.title) { document.getElementById('add-title').value = data.title; filled.push('title'); }
    if (data.version) { document.getElementById('add-version').value = data.version; filled.push('version'); }
    if (data.review_date) { document.getElementById('add-review-date').value = data.review_date; filled.push('review date'); }
    if (data.effective_date) { document.getElementById('add-effective-date').value = data.effective_date; filled.push('effective date'); }
    if (data.owner) { document.getElementById('add-owner').value = data.owner; filled.push('owner'); }
    if (data.approver) { document.getElementById('add-approver').value = data.approver; filled.push('approver'); }
    if (data.doc_type) {
      var sel = document.getElementById('add-doc-type');
      for (var i = 0; i < sel.options.length; i++) {
        if (sel.options[i].value === data.doc_type) { sel.selectedIndex = i; break; }
      }
    }

    if (filled.length > 0) {
      statusEl.innerHTML = '<span data-s="s15540fe">Filled in: ' + filled.join(', ') + '. Review and adjust below.</span>';
    } else {
      statusEl.innerHTML = '<span data-s="s57f9e31">No structured metadata found. Please fill in the details below.</span>';
    }
  } catch(e) {
    statusEl.innerHTML = '<span data-s="sf9408e8">Extraction failed. Fill in manually below.</span>';
  } finally {
    btn.disabled = false;
    btn.style.opacity = '1';
  }
}

// ── Modal open / close ──────────────────────────────────────────────────────
function openAddModal() {
  ['add-title','add-owner','add-approver',
   'add-effective-date','add-review-date','add-location','add-comments'].forEach(function(id) {
    document.getElementById(id).value = '';
  });
  document.getElementById('add-control-ref').value = '';
  document.getElementById('add-control-search').value = '';
  _pickerSelected.add = [];
  renderPickerTags('add');
  document.getElementById('add-version').value = '1.0';
  document.getElementById('add-status').selectedIndex = 0;
  document.getElementById('add-doc-type').selectedIndex = 0;
  document.getElementById('add-review-cycle').value = '365';
  document.getElementById('add-review-hint').textContent = '';
  var cbs = document.querySelectorAll('.add-fw-cb');
  cbs.forEach(function(cb) { cb.checked = false; });
  onAddFwChange();
  dzClearFile({ stopPropagation: function(){} });
  document.getElementById('analyseStatus').textContent = 'Select a file to auto-fill details from the document';
  document.getElementById('addModal').classList.add('open');
}

async function openEditModal(doc) {
  document.getElementById('edit-doc-id').value          = doc.doc_id || '';
  document.getElementById('edit-title').value           = doc.title || '';
  document.getElementById('edit-status').value          = doc.status || 'Draft';
  document.getElementById('edit-version').value         = doc.version || '1.0';
  document.getElementById('edit-owner').value           = doc.owner || '';
  document.getElementById('edit-approver').value        = doc.approver || '';
  document.getElementById('edit-effective-date').value  = doc.effective_date || '';
  document.getElementById('edit-review-date').value     = doc.review_date || '';
  document.getElementById('edit-review-cycle').value    = '';
  document.getElementById('edit-review-hint').textContent = '';
  document.getElementById('edit-location').value        = doc.location || '';
  document.getElementById('edit-comments').value        = doc.comments || '';
  document.getElementById('edit-revision-file').value   = '';
  document.getElementById('edit-revision-status').innerHTML = '';
  document.getElementById('edit-template-status').innerHTML = '';

  var dlRow = document.getElementById('edit-download-row');
  var dlLink = document.getElementById('edit-download-link');
  if (doc.file_path || doc.branded_file_path) {
    dlRow.style.display = 'block';
    dlLink.href = '/aria/documents/' + encodeURIComponent(doc.doc_id) + '/download';
  } else {
    dlRow.style.display = 'none';
  }

  // PLAN-35 T10: a managed document's status/version/owner/approver and
  // file/template only change through draft/confirm/submit/approve now --
  // the T08 route guards refuse the legacy paths below outright for one.
  // Swap the whole editing surface rather than let a manager submit a
  // change the server will just 409 back.
  var isManaged = !!doc.policy_workflow_managed;
  document.getElementById('edit-is-managed').value = isManaged ? '1' : '';
  document.getElementById('edit-legacy-lifecycle-fields').style.display = isManaged ? 'none' : 'contents';
  document.getElementById('edit-lifecycle-status').textContent   = doc.status   || '—';
  document.getElementById('edit-lifecycle-version').textContent  = doc.version  || '—';
  document.getElementById('edit-lifecycle-owner').textContent    = doc.owner    || '—';
  document.getElementById('edit-lifecycle-approver').textContent = doc.approver || '—';
  document.getElementById('edit-save-btn').textContent = isManaged ? 'Save metadata' : 'Save changes';
  document.getElementById('edit-legacy-upload-section').style.display = isManaged ? 'none' : '';
  document.getElementById('edit-legacy-template-section').style.display = isManaged ? 'none' : '';
  document.getElementById('edit-managed-panel').style.display = isManaged ? '' : 'none';
  if (isManaged) {
    document.getElementById('edit-workbench-link').href = '/aria/documents/' + encodeURIComponent(doc.doc_id) + '/workbench';
    await AriaPolicyWorkflow.ui.renderPublicationStatus(document.getElementById('edit-publication-status'), doc);
    await AriaPolicyWorkflow.ui.renderVersionHistory(document.getElementById('edit-version-history'), doc);

    var revisionActionEl = document.getElementById('edit-revision-action');
    revisionActionEl.innerHTML =
      '<button type="button" class="btn btn-ghost" data-s="s2cbaf86" id="edit-start-revision-btn">Start a revision</button>';
    document.getElementById('edit-start-revision-btn').onclick = function () {
      AriaPolicyWorkflow.ui.startRevision(doc);
    };

    var submitSection = document.getElementById('edit-submit-approval-section');
    if (doc.current_policy_version_id) {
      var versionRes = await AriaPolicyWorkflow.api.getVersion(doc.current_policy_version_id);
      var version = versionRes.ok ? versionRes.data.version : null;
      // Only a confirmed-but-undecided version (not yet approved) is
      // eligible to submit -- an already-approved current version has
      // nothing pending, and section 11 point 7's form only makes sense
      // for a real candidate.
      if (version && (version.state === 'draft' || version.state === 'withdrawn')) {
        submitSection.style.display = '';
        var submitFormEl = document.getElementById('edit-submit-form');
        await AriaPolicyWorkflow.ui.initSubmitForApprovalForm(
          submitFormEl, document.getElementById('edit-approver-select'),
          document.getElementById('edit-submit-note'), document.getElementById('edit-submit-empty'),
          document.getElementById('edit-submit-btn'), version,
          // PLAN-35 T11 review fix: a real callback (the previous
          // formEl.dataset.onSubmitted check could never actually run --
          // a dataset value is always a string, never typeof 'function').
          // Refreshes both panels with fresh data and hides the
          // now-stale submit section, rather than leaving the page
          // showing pre-submission state after a successful submit.
          function () {
            submitSection.style.display = 'none';
            AriaPolicyWorkflow.ui.renderVersionHistory(document.getElementById('edit-version-history'), doc);
            AriaPolicyWorkflow.ui.renderPublicationStatus(document.getElementById('edit-publication-status'), doc);
          }
        );
      } else {
        submitSection.style.display = 'none';
      }
    } else {
      submitSection.style.display = 'none';
    }
  }

  try {
    var tpls = await fetch('/aria/api/templates').then(function(r){ return r.json(); });
    var sel = document.getElementById('edit-template-id');
    sel.innerHTML = '<option value="">Select a template</option>';
    tpls.forEach(function(t) {
      var opt = document.createElement('option');
      opt.value = t.id;
      opt.textContent = t.name + ' (' + t.doc_type + ')' + (t.is_default ? ' ★' : '');
      sel.appendChild(opt);
    });
    if (doc.template_id) sel.value = doc.template_id;
  } catch(e) {}

  _pickerSelected.edit = [];
  document.getElementById('edit-control-search').value = '';
  document.getElementById('edit-control-ref').value = doc.control_ref || '';
  var fwNames = (doc.framework || '').split(',').map(function(s) { return s.trim(); }).filter(Boolean);
  if (fwNames.length) {
    await _loadControlsForFwNames(fwNames);
    document.getElementById('edit-control-search').placeholder = 'Search ' + _ctrlOptions.length + ' controls...';
  }
  if (doc.control_ref) {
    var refs = doc.control_ref.split(',').map(function(s) { return s.trim(); }).filter(Boolean);
    refs.forEach(function(ref) {
      var match = _ctrlOptions.find(function(c) { return c.ref === ref; });
      _pickerSelected.edit.push({ ref: ref, label: match ? match.label : ref });
    });
  }
  renderPickerTags('edit');

  document.getElementById('editModal').classList.add('open');
}

async function uploadRevision() {
  var fileInput = document.getElementById('edit-revision-file');
  var file = fileInput.files[0];
  if (!file) { showToast('Select a file to upload', 'error'); return; }
  var docId = document.getElementById('edit-doc-id').value;
  var statusEl = document.getElementById('edit-revision-status');
  statusEl.innerHTML = '<span data-s="sa805525">Uploading...</span>';
  var form = new FormData();
  form.append('file', file);
  form.append('notes', 'Manual revision upload');
  try {
    var res = await fetch('/aria/documents/' + encodeURIComponent(docId) + '/upload-revision', { method: 'POST', body: form });
    var data = await res.json();
    if (data.success) {
      var ver = esc(String(data.version||''));
      statusEl.innerHTML = '<span data-s="s15540fe">Uploaded - v' + ver + '. Status set to Under Review.</span>';
      document.getElementById('edit-version').value = data.version;
      document.getElementById('edit-status').value = 'Under Review';
      showToast('Revision uploaded - v' + ver);
    } else {
      statusEl.innerHTML = '<span data-s="sf9408e8">' + esc(data.error || 'Failed') + '</span>';
    }
  } catch(e) {
    statusEl.innerHTML = '<span data-s="sf9408e8">Upload failed</span>';
  }
}

async function applyTemplate() {
  var tplId = document.getElementById('edit-template-id').value;
  if (!tplId) { showToast('Select a template first', 'error'); return; }
  var docId = document.getElementById('edit-doc-id').value;
  var statusEl = document.getElementById('edit-template-status');
  statusEl.innerHTML = '<span data-s="sa805525">Applying template...</span>';
  var form = new FormData();
  form.append('template_id', tplId);
  try {
    var res = await fetch('/aria/documents/' + encodeURIComponent(docId) + '/apply-template', { method: 'POST', body: form });
    var data = await res.json();
    if (data.ok) {
      statusEl.innerHTML = '<span data-s="s15540fe">Template applied. Download the branded version below.</span>';
      document.getElementById('edit-download-row').style.display = 'block';
      document.getElementById('edit-download-link').href = '/aria/documents/' + encodeURIComponent(docId) + '/download';
      showToast('Branding template applied');
    } else {
      statusEl.innerHTML = '<span data-s="sf9408e8">' + esc(data.error || 'Failed') + '</span>';
    }
  } catch(e) {
    statusEl.innerHTML = '<span data-s="sf9408e8">Template application failed</span>';
  }
}

function closeModal(id) { document.getElementById(id).classList.remove('open'); }

// ── PLAN-35 T10: pending approvals + decision modal ─────────────────────────
var _pendingApprovalsOpen = false;
function togglePendingApprovals() {
  var list = document.getElementById('pendingApprovalsList');
  var chevron = document.getElementById('pendingApprovalsChevron');
  _pendingApprovalsOpen = !_pendingApprovalsOpen;
  list.style.display = _pendingApprovalsOpen ? '' : 'none';
  if (chevron) chevron.style.transform = _pendingApprovalsOpen ? 'rotate(180deg)' : '';
}

function openApprovalDecision(approval) {
  document.getElementById('approvalDecisionModal').classList.add('open');
  AriaPolicyWorkflow.ui.renderApprovalDecision(
    document.getElementById('approvalDecisionBody'), approval,
    function () {
      closeModal('approvalDecisionModal');
      refreshPendingApprovals();
    }
  );
}

async function refreshPendingApprovals() {
  var card = document.getElementById('pendingApprovalsCard');
  var res = await AriaPolicyWorkflow.api.listMyApprovals();
  if (!res.ok) return;
  var approvals = res.data.approvals || [];
  if (!approvals.length) {
    card.style.display = 'none';
    return;
  }
  card.style.display = '';
  document.getElementById('pendingApprovalsCount').textContent = String(approvals.length);
  await AriaPolicyWorkflow.ui.renderPendingApprovals(document.getElementById('pendingApprovalsList'), openApprovalDecision);
}

document.addEventListener('DOMContentLoaded', function () {
  if (window.AriaPolicyWorkflow) refreshPendingApprovals();
});

// ── Submit: Add / Upload ────────────────────────────────────────────────────
async function submitAdd() {
  var title = document.getElementById('add-title').value.trim();
  if (!title) { showToast('Title is required', 'error'); return; }

  var btn = document.getElementById('addSaveBtn');
  btn.disabled = true;
  btn.textContent = _addFile ? 'Uploading...' : 'Saving...';

  var fwNames = getCheckedFwNames();

  var form = new FormData();
  if (_addFile) form.append('file', _addFile);
  form.append('framework',      fwNames.join(', ') || 'Unmapped');
  form.append('control_ref',    document.getElementById('add-control-ref').value);
  form.append('title',          title);
  form.append('doc_type',       document.getElementById('add-doc-type').value);
  form.append('version',        document.getElementById('add-version').value);
  form.append('status',         document.getElementById('add-status').value);
  form.append('owner',          document.getElementById('add-owner').value);
  form.append('approver',       document.getElementById('add-approver').value);
  form.append('effective_date', document.getElementById('add-effective-date').value);
  form.append('review_date',    document.getElementById('add-review-date').value);
  form.append('location',       document.getElementById('add-location').value);
  form.append('comments',       document.getElementById('add-comments').value);

  var endpoint = _addFile ? '/aria/documents/upload-new' : '/aria/documents/add';

  try {
    var res = await fetch(endpoint, { method: 'POST', body: form });
    var data = await res.json();
    if (data.ok) {
      showToast('Document saved: ' + data.doc_id);
      setTimeout(function(){ location.reload(); }, 900);
    } else {
      showToast(data.error || 'Failed to save', 'error');
      btn.disabled = false;
      btn.textContent = 'Save Document';
    }
  } catch(e) {
    showToast('Save failed', 'error');
    btn.disabled = false;
    btn.textContent = 'Save Document';
  }
}

async function submitEdit() {
  var docId = document.getElementById('edit-doc-id').value;
  var isManaged = document.getElementById('edit-is-managed').value === '1';

  // PLAN-36 T01 (findings.md F01): a managed document's status/version/
  // owner/approver are workflow-owned -- start a revision, then submit and
  // decide, instead. Sending them here used to happen unconditionally and
  // the backend correctly 409s any of them on a managed document; the fix
  // is that this generic Save must never send them for a managed one, not
  // that the backend guard should ever be relaxed to let it.
  var form = new FormData();
  form.append('title',          document.getElementById('edit-title').value);
  form.append('effective_date', document.getElementById('edit-effective-date').value);
  form.append('review_date',    document.getElementById('edit-review-date').value);
  form.append('location',       document.getElementById('edit-location').value);
  form.append('comments',       document.getElementById('edit-comments').value);
  form.append('control_ref',    document.getElementById('edit-control-ref').value);
  if (!isManaged) {
    form.append('status',   document.getElementById('edit-status').value);
    form.append('version',  document.getElementById('edit-version').value);
    form.append('owner',    document.getElementById('edit-owner').value);
    form.append('approver', document.getElementById('edit-approver').value);
  }

  var btn = document.getElementById('edit-save-btn');
  var originalLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Saving...';
  try {
    await ApiClient.request('/aria/documents/update/' + encodeURIComponent(docId), { method: 'POST', body: form, actionId: 'aria.document.update' });
    showToast('Document updated');
    setTimeout(function(){ location.reload(); }, 900);
    return; // page reloads shortly; finally still restores the button in the meantime
  } catch (e) {
    showToast(e.detail || 'Failed to update document.', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = originalLabel;
  }
}

async function deleteDoc(docId) {
  if (!confirm('Delete ' + docId + '? This cannot be undone.')) return;
  try {
    await ApiClient.request('/aria/documents/delete/' + encodeURIComponent(docId), { method: 'POST', actionId: 'aria.document.delete' });
    document.getElementById('row-' + docId)?.remove();
    showToast('Document deleted');
  } catch (e) {
    showToast(e.detail || 'Failed', 'error');
  }
}

// ── Review-date status badges ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
  var today = new Date();
  today.setHours(0,0,0,0);
  var in30 = new Date(today);
  in30.setDate(in30.getDate() + 30);

  document.querySelectorAll('[data-review]').forEach(function(cell) {
    var rv = cell.getAttribute('data-review');
    if (!rv) return;
    var d = new Date(rv);
    if (isNaN(d.getTime())) return;
    d.setHours(0,0,0,0);
    var span = cell.querySelector('.review-date-cell');
    if (!span) return;
    if (d < today) {
      span.classList.add('review-overdue');
      span.insertAdjacentHTML('afterend', '<span class="badge-review-overdue">Overdue</span>');
    } else if (d <= in30) {
      span.classList.add('review-soon');
      span.insertAdjacentHTML('afterend', '<span class="badge-review-soon">Due Soon</span>');
    }
  });
});

document.querySelectorAll('.modal-overlay').forEach(function(el) {
  el.addEventListener('click', function(e) { if (e.target === el) el.classList.remove('open'); });
});

// PLAN-35 T10: "?open=<doc_id>" deep link -- api_confirm_policy_draft has
// returned a detail_url in exactly this shape since T06, and My Drafts /
// the confirm flow both navigate to it, but nothing here ever read the
// parameter: arriving from a fresh confirmation landed on the plain list,
// never the document itself. Keep row data in JSON, never in executable
// attributes. Jinja's built-in tojson escapes script boundaries.
var _allDocsById = Object.create(null);
JSON.parse(document.getElementById('documentsPageData').dataset.docs || '[]').forEach(function (d) { _allDocsById[d.doc_id] = d; });
document.addEventListener('click', function (event) {
  var edit = event.target.closest('[data-doc-edit]');
  if (edit) {
    var doc = _allDocsById[edit.dataset.docEdit];
    if (doc) openEditModal(doc);
    return;
  }
  var remove = event.target.closest('[data-doc-delete]');
  if (remove) deleteDoc(remove.dataset.docDelete);
});
document.addEventListener('DOMContentLoaded', function () {
  var openId = new URLSearchParams(window.location.search).get('open');
  if (openId && _allDocsById[openId]) {
    openEditModal(_allDocsById[openId]);
  }
});

document.addEventListener('click', function (event) {
  var close = event.target.closest('[data-doc-close]');
  if (close) {
    var modalId = close.dataset.docClose;
    if (['approvalDecisionModal', 'addModal', 'editModal'].includes(modalId)) closeModal(modalId);
    return;
  }
  var action = event.target.closest('[data-doc-action]');
  if (!action) return;
  switch (action.dataset.docAction) {
    case 'open-add': openAddModal(); break;
    case 'toggle-approvals': togglePendingApprovals(); break;
    case 'analyse': analyseFile(); break;
    case 'save-add': submitAdd(); break;
    case 'revision': uploadRevision(); break;
    case 'apply-template': applyTemplate(); break;
    case 'save-edit': submitEdit(); break;
  }
});
document.addEventListener('keydown', function (event) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  var action = event.target.closest('[data-doc-action="toggle-approvals"], #dropZone, #dzClear');
  if (!action) return;
  event.preventDefault();
  action.click();
});

var dropZone = document.getElementById('dropZone');
dropZone.addEventListener('click', function (event) {
  if (!event.target.closest('#dzClear')) document.getElementById('addFileInput').click();
});
dropZone.addEventListener('dragover', dzDragOver);
dropZone.addEventListener('dragleave', dzDragLeave);
dropZone.addEventListener('drop', dzDrop);
document.getElementById('dzClear').addEventListener('click', dzClearFile);
document.getElementById('addFileInput').addEventListener('change', function () { dzFileSelected(this); });
document.querySelectorAll('.add-fw-cb').forEach(function (cb) {
  cb.addEventListener('change', onAddFwChange);
});
['add-effective-date', 'add-review-cycle'].forEach(function (id) {
  document.getElementById(id).addEventListener('change', calcReviewDate);
});
['edit-effective-date', 'edit-review-cycle'].forEach(function (id) {
  document.getElementById(id).addEventListener('change', calcEditReviewDate);
});
['add', 'edit'].forEach(function (prefix) {
  var search = document.getElementById(prefix + '-control-search');
  search.addEventListener('focus', function () { showPickerDD(prefix); });
  search.addEventListener('input', function () { filterPickerDD(prefix); });
  search.addEventListener('blur', function () { hidePickerDD(prefix); });
});
