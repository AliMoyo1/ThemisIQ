var _people = [], _editId = null, _importFile = null;

async function loadPeople() {
  const res = await fetch('/api/people');
  const data = await res.json();
  _people = data.items || [];
  renderStats(data);
  renderDeptFilter(data.departments || []);
  renderGrid(_people);
}

function renderStats(data) {
  var total = data.total || 0;
  var active = (_people).filter(p => p.is_active).length;
  var depts = (data.departments || []).length;
  document.getElementById('pdStats').innerHTML =
    stat(total, 'Total') + stat(active, 'Active') + stat(depts, 'Departments');
}
function stat(v, l) {
  var count = Number(v);
  return '<div class="pd-stat"><div class="pd-stat-val">' + (Number.isSafeInteger(count) && count >= 0 ? count : 0) + '</div><div class="pd-stat-lbl">' + l + '</div></div>';
}

function renderDeptFilter(depts) {
  var sel = document.getElementById('pdDeptFilter');
  var cur = sel.value;
  sel.innerHTML = '<option value="">All Departments</option>';
  var ds = document.getElementById('deptSuggestions');
  ds.innerHTML = '';
  depts.forEach(function(d) {
    sel.innerHTML += '<option value="' + esc(d) + '">' + esc(d) + '</option>';
    ds.innerHTML += '<option value="' + esc(d) + '">';
  });
  if (cur) sel.value = cur;
}

function filterPeople() {
  var q = document.getElementById('pdSearch').value.toLowerCase();
  var dept = document.getElementById('pdDeptFilter').value;
  var status = document.getElementById('pdStatusFilter').value;
  var filtered = _people.filter(function(p) {
    var matchQ = !q || (p.full_name||'').toLowerCase().includes(q) || (p.email||'').toLowerCase().includes(q) || (p.job_title||'').toLowerCase().includes(q) || (p.department||'').toLowerCase().includes(q);
    var matchDept = !dept || p.department === dept;
    var matchStatus = !status || (status === 'active' ? p.is_active : !p.is_active);
    return matchQ && matchDept && matchStatus;
  });
  renderGrid(filtered);
}

function renderGrid(people) {
  var el = document.getElementById('pdGrid');
  if (!people.length) {
    el.innerHTML = '<div class="pd-empty" style="grid-column:1/-1"><div class="pd-empty-icon"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-users></use></svg></div><div style="font-size:15px;font-weight:600">No people found</div><div style="font-size:13px;margin-top:4px">Add staff manually or import from Excel.</div></div>';
    return;
  }
  el.innerHTML = people.map(function(p) {
    var id = Number(p.id);
    if (!Number.isSafeInteger(id) || id <= 0) return '';
    var initials = (p.full_name||'?').split(' ').map(function(w){return w[0]||'';}).slice(0,2).join('').toUpperCase();
    return '<div class="pd-card' + (p.is_active ? '' : ' inactive') + '" role="button" tabindex="0" data-person-id="' + id + '">' +
      '<div class="pd-card-top">' +
        '<div class="pd-avatar" style="background:' + avatarColor(p.full_name) + '">' + esc(initials) + '</div>' +
        '<div class="pd-card-info">' +
          '<div class="pd-card-name">' + esc(p.full_name||'') + '</div>' +
          '<div class="pd-card-title">' + esc(p.job_title||'No title') + '</div>' +
        '</div>' +
        '<div class="pd-status-dot ' + (p.is_active ? 'active' : 'inactive') + '" title="' + (p.is_active ? 'Active' : 'Inactive') + '"></div>' +
      '</div>' +
      (p.department ? '<div class="pd-dept-badge">' + esc(p.department) + '</div>' : '') +
      '<div class="pd-card-contact">' +
        (p.email ? '<div class="pd-contact-row"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg><a href="mailto:' + esc(p.email) + '">' + esc(p.email) + '</a></div>' : '') +
        (p.phone ? '<div class="pd-contact-row"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2A19.79 19.79 0 0 1 11.6 19.27 19.73 19.73 0 0 1 5.2 12.73 19.79 19.79 0 0 1 2.1 4.2 2 2 0 0 1 4.11 2H7.09a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91A16 16 0 0 0 14.09 15.91l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>' + esc(p.phone) + '</div>' : '') +
      '</div>' +
    '</div>';
  }).join('');
}

function avatarColor(name) {
  var colors = ['#2563eb','#7c3aed','#0891b2','#059669','#d97706','#dc2626','#db2777','#4f46e5'];
  var h = 0; for (var i=0;i<(name||'').length;i++) h += (name.charCodeAt(i)*31);
  return colors[Math.abs(h) % colors.length];
}

async function openDrawer(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) return;
  var res = await fetch('/api/people/' + pid + '/profile');
  var p = await res.json();
  if (p.error) return;
  var initials = (p.full_name||'?').split(' ').map(function(w){return w[0]||'';}).slice(0,2).join('').toUpperCase();
  document.getElementById('ddAvatar').textContent = initials;
  document.getElementById('ddAvatar').style.background = avatarColor(p.full_name);
  document.getElementById('ddName').textContent = p.full_name || '';
  document.getElementById('ddRole').textContent = (p.job_title||'') + (p.department ? ' - ' + p.department : '');
  var html = '<div class="pd-section"><div class="pd-section-title">Contact</div>' +
    kv('Email', p.email ? '<a href="mailto:'+esc(p.email)+'">'+esc(p.email)+'</a>' : '-') +
    kv('Phone', esc(p.phone || '-')) +
    kv('Status', p.is_active ? 'Active' : 'Inactive') +
  '</div>';
  if (p.notes) html += '<div class="pd-section"><div class="pd-section-title">Notes</div><p style="font-size:12px;color:var(--text);margin:0">'+esc(p.notes)+'</p></div>';
  if (p.tasks && p.tasks.length) {
    html += '<div class="pd-section"><div class="pd-section-title">Assigned Tasks (' + p.tasks.length + ')</div>';
    p.tasks.forEach(function(t) {
      html += '<div class="pd-profile-item">' + esc(t.title) + '<span class="pd-profile-item-status ' + statusClass(t.status) + '">' + esc(t.status||'') + '</span></div>';
    });
    html += '</div>';
  }
  if (p.risks && p.risks.length) {
    html += '<div class="pd-section"><div class="pd-section-title">Owned Risks (' + p.risks.length + ')</div>';
    p.risks.forEach(function(r) {
      html += '<div class="pd-profile-item">' + esc(r.title) + '<span class="pd-profile-item-status ' + statusClass(r.status) + '">' + esc(r.status||'') + '</span></div>';
    });
    html += '</div>';
  }
  html += '<div style="display:flex;gap:8px;margin-top:4px">' +
    '<button class="pd-btn pd-btn-secondary" style="flex:1" data-person-action="edit" data-person-id="' + pid + '">Edit</button>' +
    '<button class="pd-btn" style="flex:1;background:rgba(239,68,68,.1);color:#ef4444;border:1px solid rgba(239,68,68,.3)" data-person-action="delete" data-person-id="' + pid + '">Delete</button>' +
  '</div>';
  document.getElementById('ddBody').innerHTML = html;
  document.getElementById('pdDrawer').classList.add('open');
  if (typeof DialogFocus !== 'undefined') DialogFocus.trap(document.getElementById('pdDrawerPanel'));
}
function closeDrawer() {
  document.getElementById('pdDrawer').classList.remove('open');
  if (typeof DialogFocus !== 'undefined') DialogFocus.release();
}
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape' && document.getElementById('pdDrawer').classList.contains('open')) closeDrawer();
});
function kv(k, v) { return '<div class="pd-kv"><span class="pd-kv-k">'+k+'</span><span class="pd-kv-v">'+v+'</span></div>'; }
function statusClass(status) {
  var value = String(status || '').toLowerCase();
  return ['open', 'closed', 'completed'].includes(value) ? value : '';
}

function openAddModal() {
  _editId = null;
  document.getElementById('addModalTitle').textContent = 'Add Person';
  ['fName','fEmail','fPhone','fTitle','fDept','fNotes'].forEach(function(id){ document.getElementById(id).value=''; });
  document.getElementById('pdAddModal').classList.add('open');
}
function openEditModal(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) return;
  var p = _people.find(function(x){return x.id===pid;});
  if (!p) return;
  _editId = pid;
  document.getElementById('addModalTitle').textContent = 'Edit Person';
  document.getElementById('fName').value = p.full_name||'';
  document.getElementById('fEmail').value = p.email||'';
  document.getElementById('fPhone').value = p.phone||'';
  document.getElementById('fTitle').value = p.job_title||'';
  document.getElementById('fDept').value = p.department||'';
  document.getElementById('fNotes').value = p.notes||'';
  document.getElementById('pdAddModal').classList.add('open');
}
function closeAddModal() { document.getElementById('pdAddModal').classList.remove('open'); }

async function savePerson() {
  var name = document.getElementById('fName').value.trim();
  if (!name) { toast('Full name is required', 'error'); return; }
  var payload = {
    full_name: name,
    email: document.getElementById('fEmail').value.trim()||null,
    phone: document.getElementById('fPhone').value.trim()||null,
    job_title: document.getElementById('fTitle').value.trim()||null,
    department: document.getElementById('fDept').value.trim()||null,
    notes: document.getElementById('fNotes').value.trim()||null,
  };
  var url = _editId ? '/api/people/' + _editId : '/api/people';
  var method = _editId ? 'PATCH' : 'POST';
  var res = await fetch(url, {method:method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  var data = await res.json();
  if (data.ok) { closeAddModal(); toast(_editId ? 'Updated' : 'Person added', 'success'); loadPeople(); }
  else toast(data.error||'Error', 'error');
}

async function deletePerson(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) return;
  if (!confirm('Delete this person from the directory?')) return;
  var res = await fetch('/api/people/' + pid, {method:'DELETE'});
  var data = await res.json();
  if (data.ok) { closeDrawer(); toast('Deleted', 'success'); loadPeople(); }
  else toast(data.error||'Error', 'error');
}

function openImportModal() { _importFile=null; document.getElementById('importFileName').textContent='XLSX files only, max 5 MB'; document.getElementById('importResult').style.display='none'; document.getElementById('importBtn').disabled=true; document.getElementById('pdImportModal').classList.add('open'); }
function closeImportModal() { document.getElementById('pdImportModal').classList.remove('open'); }
function fileSelected(input) {
  _importFile = input.files[0];
  if (_importFile) { document.getElementById('importFileName').textContent = _importFile.name; document.getElementById('importBtn').disabled = false; }
}
var importDrop = document.getElementById('importDrop');
importDrop.addEventListener('dragover', function(e){e.preventDefault();importDrop.classList.add('dragover');});
importDrop.addEventListener('dragleave', function(){importDrop.classList.remove('dragover');});
importDrop.addEventListener('drop', function(e){e.preventDefault();importDrop.classList.remove('dragover');var f=e.dataTransfer.files[0];if(f){_importFile=f;document.getElementById('importFileName').textContent=f.name;document.getElementById('importBtn').disabled=false;}});

async function doImport() {
  if (!_importFile) return;
  var btn = document.getElementById('importBtn');
  btn.disabled = true; btn.textContent = 'Importing...';
  var formData = new FormData();
  formData.append('file', _importFile);
  try {
    var res = await fetch('/api/people/import', {method:'POST', headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}, body: await _importFile.arrayBuffer()});
    var data = await res.json();
    var resultEl = document.getElementById('importResult');
    resultEl.style.display = 'block';
    if (data.ok) {
      resultEl.style.color = '#16a34a';
      resultEl.textContent = 'Imported ' + data.imported + ' people. ' + data.skipped + ' skipped (already exist or missing name).';
      loadPeople();
    } else {
      resultEl.style.color = '#ef4444';
      resultEl.textContent = data.error || 'Import failed';
    }
  } catch(e) { document.getElementById('importResult').style.display='block'; document.getElementById('importResult').style.color='#ef4444'; document.getElementById('importResult').textContent='Network error'; }
  btn.disabled = false; btn.textContent = 'Import';
}

function toast(msg, type) {
  var el = document.getElementById('pdToast');
  el.textContent = msg; el.className = 'pd-toast show ' + (type||'');
  setTimeout(function(){ el.classList.remove('show'); }, 3000);
}
function esc(s) { return (s||'').toString().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

document.getElementById('pdOpenImport').addEventListener('click', openImportModal);
document.getElementById('pdOpenAdd').addEventListener('click', openAddModal);
document.getElementById('pdSearch').addEventListener('input', filterPeople);
document.getElementById('pdDeptFilter').addEventListener('change', filterPeople);
document.getElementById('pdStatusFilter').addEventListener('change', filterPeople);
document.getElementById('pdCloseDrawer').addEventListener('click', closeDrawer);
document.getElementById('pdCancelAdd').addEventListener('click', closeAddModal);
document.getElementById('pdSavePerson').addEventListener('click', savePerson);
document.getElementById('pdCancelImport').addEventListener('click', closeImportModal);
document.getElementById('importBtn').addEventListener('click', doImport);
document.getElementById('importFile').addEventListener('change', event => fileSelected(event.currentTarget));
importDrop.addEventListener('click', () => document.getElementById('importFile').click());
importDrop.addEventListener('keydown', event => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  document.getElementById('importFile').click();
});
document.getElementById('pdGrid').addEventListener('click', event => {
  if (event.target.closest('a')) return;
  const card = event.target.closest('[data-person-id]');
  if (card) openDrawer(Number(card.dataset.personId));
});
document.getElementById('pdGrid').addEventListener('keydown', event => {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  const card = event.target.closest('.pd-card[data-person-id]');
  if (!card || event.target !== card) return;
  event.preventDefault();
  openDrawer(Number(card.dataset.personId));
});
document.getElementById('ddBody').addEventListener('click', event => {
  const button = event.target.closest('[data-person-action][data-person-id]');
  if (!button) return;
  const id = Number(button.dataset.personId);
  if (button.dataset.personAction === 'edit') openEditModal(id);
  if (button.dataset.personAction === 'delete') deletePerson(id);
});

loadPeople();
