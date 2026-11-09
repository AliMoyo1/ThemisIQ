// ── Drawer state ────────────────────────────────────────────────────────────
var _drawerUid = null;

document.querySelectorAll('form[data-confirm-action]').forEach(function (form) {
  form.addEventListener('submit', function (event) {
    var name = form.dataset.confirmUser;
    var action = form.dataset.confirmAction;
    var messages = {
      'revoke-role': 'Revoke the ' + form.dataset.confirmRole + ' role from ' + name + '?',
      restore: 'Restore ' + name + '?\nThey will reappear in the list (still inactive until you Reactivate them).',
      'hard-delete': 'Permanently delete ' + name + '?\nThis cannot be undone. Only allowed if nothing references this account (audit history, owned risks, tasks, etc) -- otherwise it will be refused.',
      'reset-password': 'Reset password for ' + name + '?\nA new temporary password will be shown once.',
      deactivate: 'Deactivate ' + name + '?\nThey will no longer be able to log in.'
    };
    if (!Object.prototype.hasOwnProperty.call(messages, action) || !confirm(messages[action])) {
      event.preventDefault();
    }
  });
});

function openEditDrawerBtn(btn) {
  if (!/^[1-9]\d*$/.test(btn.dataset.uid || '')) return;
  openEditDrawer(
    btn.dataset.uid,
    btn.dataset.name,
    btn.dataset.email,
    btn.dataset.username,
    btn.dataset.created
  );
}

function openEditDrawer(uid, fullName, email, username, createdAt) {
  _drawerUid = uid;
  document.getElementById('drawerUid').value       = uid;
  document.getElementById('drawerFullName').value  = fullName;
  document.getElementById('drawerEmail').value     = email;
  document.getElementById('drawerUsername').value  = username;
  document.getElementById('drawerSubtitle').textContent = '@' + username;

  var created = createdAt ? createdAt.slice(0, 16).replace('T', ' ') : '—';
  document.getElementById('drawerCreated').value   = created;

  var errEl = document.getElementById('drawerError');
  errEl.style.display = 'none';
  errEl.textContent   = '';

  document.getElementById('editDrawerOverlay').style.display = 'block';
  document.getElementById('editDrawer').classList.add('open');

  // Reset save button state
  var btn = document.getElementById('drawerSaveBtn');
  btn.disabled    = false;
  btn.textContent = 'Save Changes';

  setTimeout(function() {
    document.getElementById('drawerFullName').focus();
  }, 60);
}

function closeEditDrawer() {
  document.getElementById('editDrawer').classList.remove('open');
  document.getElementById('editDrawerOverlay').style.display = 'none';
  _drawerUid = null;
}

// Close on Escape
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape' && _drawerUid !== null) closeEditDrawer();
});

// ── Save via PATCH /api/admin/users/{uid} ───────────────────────────────────
async function saveEditDrawer() {
  var uid      = document.getElementById('drawerUid').value;
  var fullName = document.getElementById('drawerFullName').value.trim();
  var email    = document.getElementById('drawerEmail').value.trim().toLowerCase();
  var errEl    = document.getElementById('drawerError');
  var saveBtn  = document.getElementById('drawerSaveBtn');

  // Client-side quick validation
  if (!fullName) { showDrawerErr('Full name cannot be empty.'); return; }
  if (!email || !email.includes('@')) { showDrawerErr('Enter a valid email address.'); return; }

  var csrfToken = document.getElementById('usersPageData').dataset.csrf;

  var payload = { full_name: fullName, email: email };

  saveBtn.disabled    = true;
  saveBtn.textContent = 'Saving…';
  errEl.style.display = 'none';

  try {
    var resp = await fetch('/api/admin/users/' + uid, {
      method: 'PATCH',
      headers: {
        'Content-Type':  'application/json',
        'X-CSRF-Token': csrfToken,
      },
      body: JSON.stringify(payload),
    });

    var data = await resp.json();

    if (!data.success) {
      showDrawerErr(data.error || 'An error occurred. Please try again.');
      return;
    }

    // ── In-place DOM update (no page reload) ──────────────────────────────
    var nameEl   = document.getElementById('fullname-' + uid);
    var emailEl  = document.getElementById('email-'    + uid);
    var avatarEl = document.getElementById('avatar-'   + uid);
    if (nameEl)   nameEl.textContent   = data.full_name;
    if (emailEl)  emailEl.textContent  = data.email;
    if (avatarEl) avatarEl.textContent = data.avatar_initials;

    // Update data-searchtext so filtering stays accurate
    var rowEl = document.querySelector('tr[data-user-id="' + uid + '"]');
    if (rowEl) {
      var uname = document.getElementById('drawerUsername').value;
      rowEl.dataset.searchtext = (data.full_name + ' ' + uname + ' ' + data.email).toLowerCase();
    }

    closeEditDrawer();
    if (typeof showToast === 'function') showToast('User profile updated.');

  } catch (err) {
    showDrawerErr('Network error — could not save. Please try again.');
  } finally {
    saveBtn.disabled    = false;
    saveBtn.textContent = 'Save Changes';
  }
}

function showDrawerErr(msg) {
  var el = document.getElementById('drawerError');
  el.textContent  = msg;
  el.style.display = 'block';
}

// ── Controlled SBU transfer ─────────────────────────────────────────────────
var _transferUid = null;
var _transferCurrentBu = '';

function openTransferModal(btn) {
  if (!/^[1-9]\d*$/.test(btn.dataset.uid || '')) return;
  _transferUid = btn.dataset.uid;
  _transferCurrentBu = btn.dataset.currentBu || '';
  document.getElementById('transferUserName').textContent = btn.dataset.name || 'User';
  document.getElementById('transferCurrentBu').textContent = btn.dataset.currentBuName || 'Unassigned';
  document.getElementById('transferDestination').value = '';
  Array.from(document.getElementById('transferDestination').options).forEach(function(opt) {
    opt.disabled = !!opt.value && opt.value === _transferCurrentBu;
  });
  document.getElementById('transferReason').value = '';
  document.getElementById('transferRolesReviewed').checked = false;
  document.getElementById('transferHandoverConfirmed').checked = false;
  document.getElementById('transferPreview').style.display = 'none';
  document.getElementById('transferPreview').innerHTML = '';
  showTransferError('');
  document.getElementById('transferModal').classList.add('show');
}

function closeTransferModal() {
  var modal = document.getElementById('transferModal');
  if (modal) modal.classList.remove('show');
  _transferUid = null;
}

function showTransferError(message) {
  var el = document.getElementById('transferError');
  if (!el) return;
  el.textContent = message || '';
  el.style.display = message ? 'block' : 'none';
}

async function loadTransferPreview() {
  var destination = document.getElementById('transferDestination').value;
  var previewEl = document.getElementById('transferPreview');
  showTransferError('');
  if (!_transferUid || !destination) {
    previewEl.style.display = 'none';
    previewEl.innerHTML = '';
    return;
  }
  previewEl.style.display = 'block';
  previewEl.textContent = 'Reviewing current roles and responsibilities...';
  try {
    var resp = await fetch(
      '/api/admin/users/' + _transferUid +
      '/business-unit-transfer-preview?to_business_unit_id=' + encodeURIComponent(destination)
    );
    var data = await resp.json();
    if (!resp.ok || !data.success) {
      previewEl.style.display = 'none';
      showTransferError(data.error || 'Could not prepare the transfer preview.');
      return;
    }
    var p = data.preview;
    var roles = p.roles && p.roles.length ? p.roles.join(', ') : 'No assigned roles';
    var impact = p.responsibility_impact || {};
    var impactKeys = Object.keys(impact);
    var impactText = impactKeys.length
      ? impactKeys.map(function(k) { return impact[k] + ' ' + k; }).join(', ')
      : 'No linked responsibilities found';
    previewEl.innerHTML =
      '<div><strong data-s="sf045bbe">' + _esc(p.current_business_unit.name) +
      '</strong> &rarr; <strong data-s="sa805525">' +
      _esc(p.destination_business_unit.name) + '</strong></div>' +
      '<div data-s="s62838f5"><strong>Roles:</strong> ' + _esc(roles) + '</div>' +
      '<div data-s="s96ad609"><strong>Responsibility impact:</strong> ' +
      _esc(impactText) + '</div>';
  } catch (err) {
    previewEl.style.display = 'none';
    showTransferError('Network error. Could not prepare the transfer preview.');
  }
}

async function submitBusinessUnitTransfer() {
  var destination = document.getElementById('transferDestination').value;
  var reason = document.getElementById('transferReason').value.trim();
  var rolesReviewed = document.getElementById('transferRolesReviewed').checked;
  var handoverConfirmed = document.getElementById('transferHandoverConfirmed').checked;
  if (!destination) { showTransferError('Choose a destination business unit.'); return; }
  if (reason.length < 10) { showTransferError('Provide a transfer reason of at least 10 characters.'); return; }
  if (!rolesReviewed || !handoverConfirmed) {
    showTransferError('Complete both review confirmations before activating the transfer.');
    return;
  }

  var btn = document.getElementById('transferSubmitBtn');
  btn.disabled = true;
  btn.textContent = 'Activating...';
  showTransferError('');
  try {
    var resp = await fetch('/api/admin/users/' + _transferUid + '/business-unit-transfer', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': document.getElementById('usersPageData').dataset.csrf,
      },
      body: JSON.stringify({
        to_business_unit_id: parseInt(destination, 10),
        reason: reason,
        roles_reviewed: rolesReviewed,
        handover_confirmed: handoverConfirmed,
      }),
    });
    var data = await resp.json();
    if (!resp.ok || !data.success) {
      showTransferError(data.error || 'The transfer could not be activated.');
      return;
    }
    closeTransferModal();
    if (typeof showToast === 'function') showToast('SBU transfer activated. Refreshing users...');
    window.setTimeout(function() { window.location.reload(); }, 500);
  } catch (err) {
    showTransferError('Network error. The transfer was not activated.');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Activate Transfer';
  }
}

// ── Show deleted toggle ──────────────────────────────────────────────────────
function toggleShowDeleted() {
  var url = new URL(window.location.href);
  if (url.searchParams.get('show_deleted') === '1') {
    url.searchParams.delete('show_deleted');
  } else {
    url.searchParams.set('show_deleted', '1');
  }
  window.location.href = url.toString();
}

// ── Delete user (safe delete) with best-effort impact preview ──────────────
async function confirmDeleteUser(btn) {
  var form = btn.closest('form');
  var match = form.action.match(/\/users\/(\d+)\/delete/);
  var uid = match ? match[1] : null;
  var name = btn.dataset.name || 'this user';
  var msg = 'Delete ' + name + '?\n\nThey will be hidden from the list and ' +
            'can no longer log in. This can be undone later via Restore.';
  if (uid) {
    btn.disabled = true;
    try {
      var resp = await fetch('/admin/api/users/' + uid + '/impact');
      if (resp.ok) {
        var data = await resp.json();
        var refs = data.references || {};
        var keys = Object.keys(refs);
        if (keys.length) {
          msg += '\n\nStill referenced by: ' +
                 keys.map(function(k) { return refs[k] + ' ' + k; }).join(', ') + '.';
        }
      }
    } catch (err) {
      // Impact preview is best-effort; fall through to the confirm either way.
    }
    btn.disabled = false;
  }
  if (confirm(msg)) form.submit();
}

// ── Bulk user import (PLAN-33 Phase 3) ──────────────────────────────────────
function _esc(t) {
  return String(t == null ? '' : t).replace(/[&<>"']/g, function(c) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}

var _userImportPreviewData = null;

async function importUsersExcel(input) {
  var file = input.files[0];
  if (!file) return;
  var res = document.getElementById('userImportResult');
  res.style.display = 'block';
  res.innerHTML = '<div data-s="s54ff9b6">Parsing Excel file…</div>';
  var fd = new FormData();
  fd.append('file', file);
  try {
    var r = await fetch('/admin/api/users/import-preview', { method: 'POST', body: fd });
    var d = await r.json();
    if (!r.ok || d.error) {
      res.innerHTML = '<div data-s="sd21ec66">' + _esc(d.error || 'Upload failed') + '</div>';
      input.value = '';
      return;
    }
    _userImportPreviewData = d;
    res.style.display = 'none';
    showUserImportPreview(d);
  } catch (err) {
    res.innerHTML = '<div data-s="sd21ec66">Import failed: ' + _esc(err.message) + '</div>';
  }
  input.value = '';
}

function showUserImportPreview(d) {
  var s = d.summary || {};
  var buMap = d.bu_map || {};
  var bus = d.business_units || [];
  var warns = d.warnings || [];

  function confBadge(c) {
    var colors = { exact: 'var(--good)', fuzzy: 'var(--amber)', unmapped: 'var(--bad)', empty: 'var(--muted)' };
    return '<span data-sv="display:inline-block; padding:1px 7px; border-radius:8px; font-size:10px; font-weight:700; color:#fff; background:' + (colors[c] || '#999') + ';">' + _esc(c) + '</span>';
  }

  var buRows = '';
  var buKeys = Object.keys(buMap);
  for (var i = 0; i < buKeys.length; i++) {
    var bk = buKeys[i], bm = buMap[bk];
    var opts = '<option value="">-- Unassigned --</option>';
    for (var j = 0; j < bus.length; j++) {
      var buId = Number(bus[j].id);
      if (!Number.isSafeInteger(buId) || buId <= 0) continue;
      opts += '<option value="' + buId + '"' + (bm.bu_id === bus[j].id ? ' selected' : '') + '>' + _esc(bus[j].name) + '</option>';
    }
    buRows += '<tr><td data-s="s4025540">' + _esc(bk) + '</td>' +
      '<td data-s="s2f0ad35"><select class="import-bu-sel" data-raw="' + _esc(bk) + '" ' +
      'data-s="sbeb841c">' + opts + '</select></td>' +
      '<td data-s="s2f0ad35">' + confBadge(bm.confidence) + '</td></tr>';
  }

  var sampleRows = '';
  var rows = d.rows || [];
  var limit = Math.min(rows.length, 10);
  for (var i = 0; i < limit; i++) {
    var row = rows[i];
    var status = row.error ? '<span data-s="s83ef854">invalid</span>'
      : (row.duplicate_email ? '<span data-s="s08935a7">duplicate</span>' : '<span data-s="s544e76c">ok</span>');
    sampleRows += '<tr><td data-s="s289b2a6">' + _esc(row.full_name) + '</td>' +
      '<td data-s="s289b2a6">' + _esc(row.email) + '</td>' +
      '<td data-s="s289b2a6">' + _esc((row.roles || []).join(', ')) + '</td>' +
      '<td data-s="s289b2a6">' + _esc(row.business_unit_raw || '—') + '</td>' +
      '<td data-s="s289b2a6">' + status + '</td></tr>';
  }

  var warnHtml = '';
  if (warns.length) {
    var showWarns = warns.slice(0, 5);
    warnHtml = '<div data-s="s3b04896">' +
      '<strong data-s="s08935a7">' + warns.length + ' warning(s)</strong><ul data-s="sa1fb5df">';
    for (var i = 0; i < showWarns.length; i++) warnHtml += '<li data-s="s57f9e31">' + _esc(showWarns[i]) + '</li>';
    if (warns.length > 5) warnHtml += '<li data-s="s57f9e31">…and ' + (warns.length - 5) + ' more</li>';
    warnHtml += '</ul></div>';
  }

  var statCard = function(val, label, color) {
    return '<div data-s="s19dcd4b">' +
      '<div data-sv="font-size:20px; font-weight:700; color:' + color + ';">' + _esc(val) + '</div>' +
      '<div data-s="s56bfd0f">' + label + '</div></div>';
  };

  var html = '<div class="modal-overlay show" id="userImportModal">' +
    '<div class="modal" data-s="s5d9a4e9">' +
    '<div class="modal-header"><div class="modal-title">Import Users</div>' +
    '<button type="button" class="modal-close" data-users-action="close-import">' +
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
    '</button></div>' +
    '<div class="modal-body">' +
    '<div data-s="sd489e5b">Sheet: ' + _esc(d.sheet_name || 'Sheet1') + '</div>' +
    '<div data-s="s7bd035a" data-sd="grid">' +
    statCard(s.total, 'Total Rows', 'var(--accent)') +
    statCard(s.valid, 'Will Import', 'var(--good)') +
    statCard(s.duplicates, 'Duplicates', 'var(--amber)') +
    statCard(s.invalid, 'Invalid', 'var(--bad)') +
    '</div>' +
    warnHtml +
    (buKeys.length ? '<div data-s="s87c136d"><div data-s="s617c71f">Business Unit Mapping</div>' +
      '<table data-s="sa55f31d"><thead><tr data-s="s1008415">' +
      '<th data-s="saf13840">In sheet</th>' +
      '<th data-s="saf13840">Map to</th>' +
      '<th data-s="sf1cc8ae">Match</th></tr></thead><tbody>' + buRows + '</tbody></table></div>' : '') +
    '<div data-s="sa3af230">Preview (first ' + limit + ' of ' + rows.length + ')</div>' +
    '<div data-s="s0ddf068"><table data-s="s6b26614"><thead><tr data-s="s1008415">' +
    '<th data-s="sc637739">Name</th><th data-s="sc637739">Email</th>' +
    '<th data-s="sc637739">Roles</th><th data-s="sc637739">Business Unit</th>' +
    '<th data-s="sc637739">Status</th></tr></thead><tbody>' + sampleRows + '</tbody></table></div>' +
    '</div>' +
    '<div class="modal-footer">' +
    '<button type="button" class="btn btn-ghost" data-users-action="close-import">Cancel</button>' +
    '<button type="button" class="btn btn-primary" id="userImportCommitBtn" data-users-action="commit-import">Import ' + _esc(s.valid) + ' Users</button>' +
    '</div></div></div>';
  document.body.insertAdjacentHTML('beforeend', html);
}

async function commitUserImport() {
  if (!_userImportPreviewData || !_userImportPreviewData.rows) return;
  var btn = document.getElementById('userImportCommitBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Importing…'; }

  var buOverrides = {};
  document.querySelectorAll('.import-bu-sel').forEach(function(sel) {
    buOverrides[sel.dataset.raw] = sel.value ? parseInt(sel.value, 10) : null;
  });

  var csrfToken = document.getElementById('usersPageData').dataset.csrf;
  try {
    var resp = await fetch('/admin/api/users/import-commit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ rows: _userImportPreviewData.rows, bu_overrides: buOverrides }),
    });
    var r = await resp.json();
    var modal = document.getElementById('userImportModal');
    if (modal) modal.remove();

    var res = document.getElementById('userImportResult');
    res.style.display = 'block';
    if (!resp.ok || r.error) {
      res.innerHTML = '<div data-s="sd21ec66">' + _esc(r.error || 'Import failed') + '</div>';
      return;
    }

    var credRows = '';
    (r.credentials || []).forEach(function(c) {
      credRows += '<tr><td data-s="s4025540">' + _esc(c.full_name) + '</td>' +
        '<td data-s="s29c827f">' + _esc(c.username) + '</td>' +
        '<td data-s="s2861b56">' + _esc(c.temp_password) + '</td></tr>';
    });
    var errHtml = '';
    if (r.errors && r.errors.length) {
      errHtml = '<div data-s="s5a218b3">' + r.errors.length + ' row(s) failed: ';
      for (var i = 0; i < Math.min(r.errors.length, 3); i++) {
        errHtml += _esc(r.errors[i].full_name || 'Row ' + r.errors[i].row) + ' — ' + _esc(r.errors[i].error) + '; ';
      }
      errHtml += '</div>';
    }
    res.innerHTML = '<div data-s="s66977a2">' +
      '<div data-s="s07c6944">Import Complete</div>' +
      '<div data-s="scd480be">' + _esc(r.created) + ' created, ' + _esc(r.skipped) + ' skipped. ' +
      'Temporary passwords are shown once below — share them securely; each user must change theirs at first login.</div>' +
      (credRows ? '<div data-s="s12ce91d"><table data-s="sa55f31d">' +
        '<thead><tr data-s="s1008415"><th data-s="saf13840">Name</th>' +
        '<th data-s="saf13840">Username</th>' +
        '<th data-s="saf13840">Temp Password</th></tr></thead><tbody>' + credRows + '</tbody></table></div>' : '') +
      errHtml +
      '<button class="btn btn-ghost" data-s="s4931371" data-users-action="refresh">Done — Refresh List</button>' +
      '</div>';
    _userImportPreviewData = null;
    if (typeof showToast === 'function') showToast('Imported ' + r.created + ' users');
  } catch (err) {
    if (btn) { btn.disabled = false; btn.textContent = 'Import'; }
    if (typeof showToast === 'function') showToast('Import failed: ' + err.message, 'error');
  }
}

// ── Client-side filtering ───────────────────────────────────────────────────
var _statusFilter = 'all';

function setStatusFilter(val) {
  _statusFilter = val;
  ['all', 'active', 'inactive'].forEach(function(s) {
    document.getElementById('chip-' + s).classList.toggle('active', s === val);
  });
  filterUsers();
}

function filterUsers() {
  var q      = (document.getElementById('userSearch').value || '').toLowerCase().trim();
  var role   = (document.getElementById('roleFilter').value || '').trim();
  var orgSel = document.getElementById('orgFilter');
  var orgVal = orgSel ? (orgSel.value || '').trim() : '';
  var buSel  = document.getElementById('buFilter');
  var buVal  = buSel ? (buSel.value || '').trim() : '';
  var rows   = document.querySelectorAll('tr[data-user-id]');
  var visible = 0;

  rows.forEach(function(row) {
    var text   = (row.dataset.searchtext || '').toLowerCase();
    var status = row.dataset.status || 'active';
    var roles  = (row.dataset.roles  || '');
    var orgId  = (row.dataset.orgId  || '0');
    var buId   = (row.dataset.buId   || '0');

    var ok = (!q     || text.includes(q))
          && (_statusFilter === 'all' || status === _statusFilter)
          && (!role   || roles.split(' ').indexOf(role) !== -1)
          && (!orgVal || orgId === orgVal)
          && (!buVal  || buId === buVal);

    row.classList.toggle('u-hidden', !ok);
    if (ok) visible++;
  });

  var filtering = !!(q || role || orgVal || buVal || _statusFilter !== 'all');

  // Hide org / business-unit sections whose visible row count is 0; auto-expand
  // sections that still have matches so filtering doesn't hide results behind
  // a collapsed header.
  var sections = document.querySelectorAll('.org-section, .bu-section');
  sections.forEach(function(sec) {
    var anyVisible = sec.querySelectorAll('tr[data-user-id]:not(.u-hidden)').length > 0;
    sec.classList.toggle('s-hidden', !anyVisible);
    if (anyVisible && filtering) {
      sec.classList.remove('collapsed');
    }
  });

  // Empty state (shared by both the grouped and single-org views)
  var groupedEmpty = document.getElementById('filterEmptyHost');
  if (groupedEmpty) {
    groupedEmpty.style.display = (visible === 0 && rows.length > 0) ? '' : 'none';
  }
}

// ── Collapse / expand all org sections ──────────────────────────────────────
function toggleAllOrgs() {
  var sections = document.querySelectorAll('.org-section');
  var anyOpen = false;
  sections.forEach(function(s) { if (!s.classList.contains('collapsed')) anyOpen = true; });
  sections.forEach(function(s) {
    if (anyOpen) s.classList.add('collapsed');
    else         s.classList.remove('collapsed');
  });
  var btn = document.getElementById('collapseToggleBtn');
  if (btn) btn.textContent = anyOpen ? 'Expand All' : 'Collapse All';
}

// ── Copy temporary password ─────────────────────────────────────────────────
function copyTempPassword() {
  var el = document.getElementById('tempPwValue');
  if (!el) return;
  var txt = el.textContent.trim();
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(txt).then(
      function() { if (typeof showToast === 'function') showToast('Temporary password copied.'); },
      function() { _fbCopy(txt); }
    );
  } else {
    _fbCopy(txt);
  }
}
function _fbCopy(txt) {
  var ta = document.createElement('textarea');
  ta.value = txt; document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); if (typeof showToast === 'function') showToast('Copied.'); }
  catch (_) {}
  document.body.removeChild(ta);
}

// All actions are bound here so the Users page works with script-src-attr 'none'.
document.addEventListener('click', function (event) {
  var filter = event.target.closest('[data-users-filter]');
  if (filter) {
    setStatusFilter(filter.dataset.usersFilter);
    return;
  }
  var button = event.target.closest('[data-users-action]');
  if (button) {
    switch (button.dataset.usersAction) {
      case 'choose-import': document.getElementById('userImportFile').click(); break;
      case 'open-create': document.getElementById('newUserModal').classList.add('show'); break;
      case 'close-create': document.getElementById('newUserModal').classList.remove('show'); break;
      case 'copy-password': copyTempPassword(); break;
      case 'toggle-deleted': toggleShowDeleted(); break;
      case 'toggle-orgs': toggleAllOrgs(); break;
      case 'edit': openEditDrawerBtn(button); break;
      case 'transfer': openTransferModal(button); break;
      case 'delete': confirmDeleteUser(button); break;
      case 'close-edit': closeEditDrawer(); break;
      case 'save-edit': saveEditDrawer(); break;
      case 'close-transfer': closeTransferModal(); break;
      case 'submit-transfer': submitBusinessUnitTransfer(); break;
      case 'close-import': document.getElementById('userImportModal')?.remove(); break;
      case 'commit-import': commitUserImport(); break;
      case 'refresh': window.location.reload(); break;
    }
    return;
  }
  var heading = event.target.closest('.bu-head, .org-head');
  if (heading) {
    var collapsed = heading.parentElement.classList.toggle('collapsed');
    heading.setAttribute('aria-expanded', String(!collapsed));
    return;
  }
  if (event.target.id === 'transferModal') closeTransferModal();
  if (event.target.id === 'newUserModal') event.target.classList.remove('show');
  if (event.target.id === 'userImportModal') event.target.remove();
});

document.addEventListener('keydown', function (event) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  var heading = event.target.closest('.bu-head, .org-head');
  if (!heading) return;
  event.preventDefault();
  heading.click();
});

document.getElementById('userImportFile').addEventListener('change', function () {
  importUsersExcel(this);
});
document.getElementById('userSearch').addEventListener('input', filterUsers);
['roleFilter', 'buFilter', 'orgFilter'].forEach(function (id) {
  var select = document.getElementById(id);
  if (select) select.addEventListener('change', filterUsers);
});
document.querySelectorAll('.role-add-select').forEach(function (select) {
  select.addEventListener('change', function () {
    if (select.value) select.form.requestSubmit();
  });
});
var transferDestination = document.getElementById('transferDestination');
if (transferDestination) transferDestination.addEventListener('change', loadTransferPreview);
