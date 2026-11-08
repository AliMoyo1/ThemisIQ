var MODULES = [
  {key:'aria',     name:'ARIA',     desc:'Compliance and policy management'},
  {key:'bcm',      name:'BCM',      desc:'Business continuity management'},
  {key:'erm',      name:'ERM',      desc:'Enterprise risk management'},
  {key:'grid',     name:'GRID',     desc:'Audits and inspections'},
  {key:'orm',      name:'ORM',      desc:'Operational risk management'},
  {key:'sentinel', name:'Sentinel', desc:'Privacy and data protection'},
];

var PLAN_BADGE = {
  trial:        'badge-amber',
  starter:      'badge-slate',
  professional: 'badge-violet',
  enterprise:   'badge-gold',
};

var _orgs = [];
var _filter = 'all';
window._currentOrg = null;

function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function safeId(value){
  var id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}
document.addEventListener('click',function(event){
  var button=event.target.closest('.js-remove-org-user');
  if(button){
    var orgId = safeId(button.dataset.orgId), userId = safeId(button.dataset.userId);
    if(orgId && userId) deleteOrgUser(orgId,userId,button.dataset.username);
    return;
  }
  var orgButton = event.target.closest('[data-sa-org-id]');
  if(orgButton){
    var selectedOrg = safeId(orgButton.dataset.saOrgId);
    if(selectedOrg) openPanel(selectedOrg);
    return;
  }
  var moduleRow = event.target.closest('[data-sa-module]');
  if(moduleRow){
    toggleModule(moduleRow.dataset.saModule);
    return;
  }
  var filter = event.target.closest('[data-sa-filter]');
  if(filter){ setFilter(filter.dataset.saFilter); return; }
  var demoFilter = event.target.closest('[data-dr-filter]');
  if(demoFilter){ drSetFilter(demoFilter.dataset.drFilter); return; }
  var contact = event.target.closest('[data-sa-demo-contact]');
  if(contact){
    var contactId = safeId(contact.dataset.saDemoContact);
    if(contactId) drMarkContacted(contactId);
    return;
  }
  var remove = event.target.closest('[data-sa-demo-delete]');
  if(remove){
    var removeId = safeId(remove.dataset.saDemoDelete);
    if(removeId) drDelete(removeId);
    return;
  }
  var tab = event.target.closest('.side-panel-tabs [data-tab]');
  if(tab){ switchTab(tab.dataset.tab); return; }
  var action = event.target.closest('[data-sa-action]');
  if(action){
    var handlers = {
      'open-org': openCreateOrgModal,
      'close-org': function(){ document.getElementById('createOrgModal').style.display='none'; },
      'create-org': submitCreateOrg,
      'open-user': function(){ if(window._currentOrg) openCreateUserModal(window._currentOrg.id); },
      'close-user': function(){ document.getElementById('createUserModal').style.display='none'; },
      'create-user': submitCreateUser,
      'close-panel': closePanel,
      'save-subscription': saveSubscription,
      'delete-org': deleteOrg,
    };
    if(Object.prototype.hasOwnProperty.call(handlers, action.dataset.saAction)) handlers[action.dataset.saAction]();
  }
});
document.addEventListener('keydown',function(event){
  if(event.key !== 'Enter' && event.key !== ' ') return;
  var target = event.target.closest('[data-sa-filter], [data-sa-module]');
  if(!target) return;
  event.preventDefault();
  target.click();
});
['createOrgModal','createUserModal'].forEach(function(id){
  document.getElementById(id).addEventListener('click',function(event){
    if(event.target === this) this.style.display='none';
  });
});
document.getElementById('orgSearch').addEventListener('input', renderOrgs);
document.getElementById('drSearch').addEventListener('input', renderDemoRequests);
document.getElementById('newOrgModulesPicker').addEventListener('change', updateNewOrgModules);

async function apiFetch(url, opts){
  // PLAN-36 T06 (findings.md F08): never checked the response status at all
  // -- an error body (e.g. a 403's {"detail": "..."}) was parsed and handed
  // to the caller as if it were successful data. Delegates to the shared
  // ApiClient, which throws on any non-2xx instead.
  opts = opts || {};
  var result = await ApiClient.request(url, { method: opts.method, body: opts.body, headers: opts.headers, actionId: url });
  return result === null ? {} : result;
}

async function loadOrgs(){
  _orgs = await apiFetch('/super-admin/api/orgs');
  var totalUsers = _orgs.reduce(function(s,o){return s+o.user_count},0);
  var activeOrgs = _orgs.filter(function(o){return o.status==='active'}).length;
  var expiring = _orgs.filter(isExpiringSoon).length;
  document.getElementById('statOrgs').textContent = _orgs.length;
  document.getElementById('statUsers').textContent = totalUsers;
  document.getElementById('statActive').textContent = activeOrgs;
  document.getElementById('statExpiring').textContent = expiring;
  renderOrgs();
}

function daysUntil(dateStr){
  if (!dateStr) return null;
  var d = new Date(dateStr);
  if (isNaN(d.getTime())) return null;
  var now = new Date();
  return Math.floor((d - now) / 86400000);
}

function isExpiringSoon(o){
  var d = daysUntil(o.valid_until);
  return d !== null && d <= 30 && d >= 0;
}

function setFilter(f){
  _filter = f;
  document.querySelectorAll('#filterPills .filter-pill').forEach(function(p){
    p.classList.toggle('active', p.dataset.filter === f);
    p.setAttribute('aria-pressed', String(p.dataset.filter === f));
  });
  renderOrgs();
}

function renderOrgs(){
  var q = (document.getElementById('orgSearch').value || '').toLowerCase();
  var list = _orgs.slice();
  if (_filter === 'active')    list = list.filter(function(o){return o.status==='active'});
  if (_filter === 'trial')     list = list.filter(function(o){return o.plan==='trial'});
  if (_filter === 'suspended') list = list.filter(function(o){return o.status==='suspended' || o.status==='cancelled'});
  if (_filter === 'expiring')  list = list.filter(isExpiringSoon);
  if (q) list = list.filter(function(o){return (o.name+o.slug+o.plan).toLowerCase().includes(q)});

  var body = document.getElementById('orgsBody');
  if (!list.length){
    body.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:24px">No organisations match this filter.</td></tr>';
    return;
  }
  body.innerHTML = list.map(function(o){
    var planClass = Object.prototype.hasOwnProperty.call(PLAN_BADGE, o.plan) ? PLAN_BADGE[o.plan] : 'badge-slate';
    var statusBadge =
        o.status === 'active'    ? '<span class="badge badge-green">Active</span>' :
        o.status === 'suspended' ? '<span class="badge badge-amber">Suspended</span>' :
        o.status === 'cancelled' ? '<span class="badge badge-red">Cancelled</span>' :
                                   '<span class="badge badge-gray">'+esc(o.status)+'</span>';

    var modCount = Array.isArray(o.modules) ? o.modules.length : 0;
    var modList  = Array.isArray(o.modules) ? o.modules.join(', ') : '';

    var userCount = Number.isSafeInteger(Number(o.user_count)) ? Number(o.user_count) : 0;
    var seats = Number.isSafeInteger(Number(o.seats)) ? Number(o.seats) : 0;
    var seatPct = seats > 0 ? Math.min(100, Math.round(userCount * 100 / seats)) : 0;
    var seatClass = seatPct >= 95 ? 'full' : seatPct >= 80 ? 'warn' : '';

    var renewalCell;
    if (o.valid_until){
      var d = daysUntil(o.valid_until);
      var dateStr = esc(String(o.valid_until).slice(0,10));
      if (d !== null && d < 0)       renewalCell = '<span class="expiry-danger">Expired '+(-d)+'d ago</span>';
      else if (d !== null && d <= 7) renewalCell = '<span class="expiry-danger">'+dateStr+' &middot; '+d+'d</span>';
      else if (d !== null && d <= 30)renewalCell = '<span class="expiry-warn">'+dateStr+' &middot; '+d+'d</span>';
      else                           renewalCell = dateStr;
    } else {
      renewalCell = '<span style="color:var(--muted)">Perpetual</span>';
    }

    return '<tr>'+
      '<td>'+
        '<div style="font-weight:700;color:var(--text)">'+esc(o.name)+
          (o.slug==='public'?'<span class="badge badge-gray" style="margin-left:6px">default</span>':'')+
        '</div>'+
        '<div style="font-family:monospace;font-size:11px;color:var(--muted);margin-top:2px">'+esc(o.slug)+'</div>'+
      '</td>'+
      '<td><span class="badge '+planClass+'" style="text-transform:capitalize">'+esc(o.plan)+'</span></td>'+
      '<td title="'+esc(modList)+'">'+modCount+' of 6</td>'+ 
      '<td>'+
        '<div style="font-size:12px;font-weight:600">'+userCount+' / '+seats+'</div>'+
        '<div class="seats-bar"><div class="seats-bar-fill '+seatClass+'" style="width:'+seatPct+'%"></div></div>'+
      '</td>'+
      '<td>'+renewalCell+'</td>'+
      '<td>'+statusBadge+'</td>'+
      '<td style="text-align:right"><button class="sa-btn sa-btn-secondary" data-sa-org-id="'+(safeId(o.id)||'')+'">Manage</button></td>'+
    '</tr>';
  }).join('');
}

// ── Side panel ──────────────────────────────────────────────────────────────
function openPanel(orgId){
  var org = _orgs.find(function(o){return o.id===orgId});
  if (!org) return;
  window._currentOrg = org;
  document.getElementById('panelTitle').textContent = org.name;
  document.getElementById('panelSlug').textContent = org.slug;
  document.getElementById('editPlan').value = org.plan || 'starter';
  document.getElementById('editStatus').value = org.status || 'active';
  document.getElementById('editSeats').value = org.seats || 10;
  document.getElementById('editValidUntil').value = org.valid_until ? String(org.valid_until).slice(0,10) : '';
  document.getElementById('seatHint').textContent = org.user_count + ' currently used';
  renderModuleToggles(org);
  document.getElementById('deleteOrgBtn').style.display = (org.slug === 'public') ? 'none' : '';
  switchTab('subscription');
  document.getElementById('orgPanel').classList.add('open');
  loadUsersForPanel(orgId);
}

function closePanel(){
  document.getElementById('orgPanel').classList.remove('open');
  window._currentOrg = null;
}

function switchTab(name){
  document.querySelectorAll('.tab-btn').forEach(function(b){b.classList.toggle('active', b.dataset.tab===name)});
  document.querySelectorAll('.tab-pane').forEach(function(p){p.classList.toggle('active', p.id==='tab-'+name)});
}

function renderModuleToggles(org){
  var enabled = new Set(org.modules || []);
  var html = MODULES.map(function(m){
    var on = enabled.has(m.key);
    return '<div class="module-row '+(on?'on':'')+'" role="switch" tabindex="0" aria-checked="'+on+'" data-sa-module="'+m.key+'">'+
      '<div class="icon">'+m.name.slice(0,1)+'</div>'+
      '<div class="meta"><div class="name">'+m.name+'</div><div class="desc">'+m.desc+'</div></div>'+
      '<div class="toggle-switch"></div>'+
    '</div>';
  }).join('');
  document.getElementById('moduleList').innerHTML = html;
}

async function toggleModule(key){
  var org = window._currentOrg;
  if (!org || !MODULES.some(function(m){return m.key===key})) return;
  var set = new Set(org.modules || []);
  if (set.has(key)) set.delete(key); else set.add(key);
  var newMods = Array.from(set);
  var res = await apiFetch('/super-admin/api/orgs/'+org.id, {
    method:'PUT', body:JSON.stringify({modules:newMods.join(',')})
  });
  if (res && res.error){ alert(res.error); return; }
  org.modules = newMods;
  renderModuleToggles(org);
  await loadOrgs();
  window._currentOrg = _orgs.find(function(o){return o.id===org.id});
}

async function saveSubscription(){
  var org = window._currentOrg;
  if (!org) return;
  var btn = document.getElementById('saveSubBtn');
  var err = document.getElementById('subErr');
  err.style.display = 'none';
  btn.disabled = true; btn.textContent = 'Saving...';
  try {
    var res = await apiFetch('/super-admin/api/orgs/'+org.id, {
      method:'PUT',
      body: JSON.stringify({
        plan: document.getElementById('editPlan').value,
        status: document.getElementById('editStatus').value,
        seats: parseInt(document.getElementById('editSeats').value)||1,
        valid_until: document.getElementById('editValidUntil').value || null,
      })
    });
    if (res && res.error){ err.textContent = res.error; err.style.display='block'; }
    else { await loadOrgs(); window._currentOrg = _orgs.find(function(o){return o.id===org.id}); }
  } catch(e){ err.textContent = 'Save failed.'; err.style.display='block'; }
  btn.disabled = false; btn.textContent = 'Save Changes';
}

async function deleteOrg(){
  var org = window._currentOrg;
  if (!org) return;
  if (!confirm('Delete "'+org.name+'"? This drops the tenant schema and cannot be undone.')) return;
  var res = await fetch('/super-admin/api/orgs/'+org.id, {method:'DELETE'});
  var data = await res.json();
  if (!res.ok){ alert(data.error || 'Delete failed.'); return; }
  closePanel();
  await loadOrgs();
}

async function loadUsersForPanel(orgId){
  var users = await apiFetch('/super-admin/api/orgs/'+orgId+'/users');
  document.getElementById('usersList').innerHTML = users.length
    ? '<table class="sa-table" style="table-layout:fixed;width:100%"><thead><tr><th>Name</th><th>Status</th><th style="width:60px"></th></tr></thead><tbody>'+
        users.map(function(u){
          return '<tr><td style="overflow:hidden"><div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+esc(u.full_name)+
            (u.is_super_admin?'<span class="badge badge-violet" style="margin-left:6px">super</span>':'')+'</div>'+
            '<div style="font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+esc(u.email)+'</div></td>'+
            '<td>'+(u.is_active?'<span class="badge badge-green">Active</span>':'<span class="badge badge-red">Inactive</span>')+'</td>'+
            '<td style="text-align:right"><button class="sa-btn sa-btn-danger js-remove-org-user" type="button" data-org-id="'+(safeId(orgId)||'')+'" data-user-id="'+(safeId(u.id)||'')+'" data-username="'+esc(u.username)+'" style="font-size:11px;padding:4px 10px">Remove</button></td>'+
            '</tr>';
        }).join('')+
        '</tbody></table>'
    : '<div style="text-align:center;color:var(--muted);padding:24px">No users yet.</div>';
}

async function deleteOrgUser(orgId, userId, username){
  if (!confirm('Remove user "'+username+'" and delete their account? This cannot be undone.')) return;
  var res = await fetch('/super-admin/api/orgs/'+orgId+'/users/'+userId, {method:'DELETE'});
  var data = await res.json();
  if (!res.ok){ alert(data.error || 'Delete failed.'); return; }
  loadUsersForPanel(orgId);
  await loadOrgs();
  window._currentOrg = _orgs.find(function(o){return o.id===orgId}) || window._currentOrg;
}

// ── Create org modal ────────────────────────────────────────────────────────
function openCreateOrgModal(){
  document.getElementById('createOrgErr').style.display = 'none';
  document.getElementById('newOrgName').value = '';
  // Build module checkbox picker
  var picker = document.getElementById('newOrgModulesPicker');
  picker.innerHTML = MODULES.map(function(m){
    return '<label style="display:flex;align-items:center;gap:6px;padding:6px 8px;border:1px solid var(--border);border-radius:var(--radius);background:var(--surface2);font-size:12px;cursor:pointer">'+
      '<input type="checkbox" value="'+m.key+'" checked/>'+m.name+
    '</label>';
  }).join('');
  updateNewOrgModules();
  document.getElementById('createOrgModal').style.display = 'flex';
}

function updateNewOrgModules(){
  var keys = Array.from(document.querySelectorAll('#newOrgModulesPicker input:checked')).map(function(i){return i.value});
  document.getElementById('newOrgModules').value = keys.join(',');
}

async function submitCreateOrg(){
  var btn = document.getElementById('createOrgBtn');
  var err = document.getElementById('createOrgErr');
  err.style.display = 'none';
  btn.disabled = true; btn.textContent = 'Creating...';
  try {
    var res = await apiFetch('/super-admin/api/orgs', {
      method:'POST',
      body: JSON.stringify({
        name: document.getElementById('newOrgName').value.trim(),
        plan: document.getElementById('newOrgPlan').value,
        modules: document.getElementById('newOrgModules').value.trim(),
        seats: parseInt(document.getElementById('newOrgSeats').value)||10,
      })
    });
    if (res.error){ err.textContent = res.error; err.style.display = 'block'; }
    else { document.getElementById('createOrgModal').style.display = 'none'; await loadOrgs(); }
  } catch(e){ err.textContent = 'Request failed.'; err.style.display = 'block'; }
  btn.disabled = false; btn.textContent = 'Create';
}

function openCreateUserModal(orgId){
  document.getElementById('newUserOrgId').value = orgId;
  document.getElementById('createUserErr').style.display = 'none';
  ['newUserName','newUserUsername','newUserEmail','newUserPassword'].forEach(function(id){
    document.getElementById(id).value = '';
  });
  document.getElementById('createUserModal').style.display = 'flex';
}

async function submitCreateUser(){
  var btn = document.getElementById('createUserBtn');
  var err = document.getElementById('createUserErr');
  var orgId = parseInt(document.getElementById('newUserOrgId').value);
  err.style.display = 'none';
  btn.disabled = true; btn.textContent = 'Creating...';
  try {
    var res = await apiFetch('/super-admin/api/orgs/'+orgId+'/users', {
      method:'POST',
      body: JSON.stringify({
        full_name: document.getElementById('newUserName').value.trim(),
        username:  document.getElementById('newUserUsername').value.trim(),
        email:     document.getElementById('newUserEmail').value.trim(),
        password:  document.getElementById('newUserPassword').value.trim(),
        role:      document.getElementById('newUserRole').value,
      })
    });
    if (res.error){ err.textContent = res.error; err.style.display = 'block'; }
    else {
      document.getElementById('createUserModal').style.display = 'none';
      loadUsersForPanel(orgId);
    }
  } catch(e){ err.textContent = 'Request failed.'; err.style.display = 'block'; }
  btn.disabled = false; btn.textContent = 'Create User';
}

loadOrgs();

// ── Demo Requests ─────────────────────────────────────────────────────────────
var _demoRequests = [];
var _drFilter = 'all';

async function loadDemoRequests() {
  try {
    _demoRequests = await apiFetch('/super-admin/api/demo-requests');
    updateDemoStats();
    renderDemoChart();
    renderDemoRequests();
  } catch(e) {
    document.getElementById('drBody').innerHTML =
      '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:24px">Failed to load requests.</td></tr>';
  }
}

function updateDemoStats() {
  var total = _demoRequests.length;
  var weekAgo = new Date(); weekAgo.setDate(weekAgo.getDate() - 7);
  var thisWeek = _demoRequests.filter(function(r){ return new Date(r.created_at) >= weekAgo; }).length;
  var pending   = _demoRequests.filter(function(r){ return !r.contacted; }).length;
  var contacted = _demoRequests.filter(function(r){ return r.contacted; }).length;
  document.getElementById('drStatTotal').textContent    = total;
  document.getElementById('drStatWeek').textContent     = thisWeek;
  document.getElementById('drStatPending').textContent  = pending;
  document.getElementById('drStatContacted').textContent = contacted;
}

function renderDemoChart() {
  var chartEl  = document.getElementById('drChart');
  var labelEl  = document.getElementById('drChartLabels');
  var days = 14;
  var buckets = [];
  for (var i = days - 1; i >= 0; i--) {
    var d = new Date(); d.setDate(d.getDate() - i);
    var ds = d.toISOString().slice(0, 10);
    var dayReqs = _demoRequests.filter(function(r){ return (r.created_at || '').slice(0, 10) === ds; });
    buckets.push({ date: ds, label: d.toLocaleDateString('en', {month:'short', day:'numeric'}),
                   count: dayReqs.length,
                   contacted: dayReqs.filter(function(r){ return r.contacted; }).length });
  }
  var maxCount = Math.max(1, Math.max.apply(null, buckets.map(function(b){ return b.count; })));
  var barW = 'calc(' + (100/days) + '% - 6px)';

  chartEl.innerHTML = buckets.map(function(b) {
    var h = b.count === 0 ? 4 : Math.max(8, Math.round((b.count / maxCount) * 72));
    var color = b.contacted === b.count && b.count > 0 ? '#16a34a' : b.count > 0 ? '#f59e0b' : 'var(--border)';
    return '<div style="flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end" title="' + b.label + ': ' + b.count + ' request(s)">' +
           '<div class="premium-chart-column" style="width:100%;height:' + h + 'px;background:' + color + ';border-radius:7px 7px 2px 2px;transition:height .2s"></div>' +
           '</div>';
  }).join('');

  labelEl.innerHTML = buckets.map(function(b, i) {
    var show = (i === 0 || i === 6 || i === 13);
    return '<div style="flex:1;text-align:center;font-size:10px;color:var(--muted);font-family:monospace;white-space:nowrap;overflow:hidden">' +
           (show ? b.label : '') + '</div>';
  }).join('');
}

function drSetFilter(f) {
  _drFilter = f;
  ['all','pending','contacted'].forEach(function(k) {
    var button = document.getElementById('drFilter' + k.charAt(0).toUpperCase() + k.slice(1));
    button.classList.toggle('active', k === f);
    button.setAttribute('aria-pressed', String(k === f));
  });
  renderDemoRequests();
}

function renderDemoRequests() {
  var q = (document.getElementById('drSearch').value || '').toLowerCase();
  var rows = _demoRequests.filter(function(r) {
    if (_drFilter === 'pending'   && r.contacted) return false;
    if (_drFilter === 'contacted' && !r.contacted) return false;
    if (q && ![r.name, r.email, r.company].some(function(s){ return (s||'').toLowerCase().includes(q); })) return false;
    return true;
  });

  if (!rows.length) {
    document.getElementById('drBody').innerHTML =
      '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:32px">No requests found.</td></tr>';
    return;
  }

  document.getElementById('drBody').innerHTML = rows.map(function(r) {
    var date = r.created_at ? esc(String(r.created_at).slice(0, 10)) : '';
    var requestId = safeId(r.id);
    var status = r.contacted
      ? '<span class="badge badge-green">Contacted</span>'
      : '<span class="badge badge-amber">Pending</span>';
    var contactBtn = r.contacted ? '' :
      '<button class="sa-btn sa-btn-primary" data-sa-demo-contact="' + (requestId||'') + '" style="margin-right:6px;font-size:11px;padding:4px 10px">Mark Contacted</button>';
    return '<tr>' +
      '<td style="font-weight:600">' + esc(r.name) + '</td>' +
      '<td><a href="mailto:' + esc(r.email) + '" style="color:var(--accent)">' + esc(r.email) + '</a></td>' +
      '<td>' + esc(r.company || '-') + '</td>' +
      '<td>' + (r.plan ? '<span class="badge badge-violet">' + esc(r.plan) + '</span>' : '<span style="color:var(--muted)">-</span>') + '</td>' +
      '<td style="color:var(--muted);font-size:12px;font-family:monospace">' + date + '</td>' +
      '<td>' + status + '</td>' +
      '<td style="text-align:right">' + contactBtn +
        '<button class="sa-btn sa-btn-danger" data-sa-demo-delete="' + (requestId||'') + '" style="font-size:11px;padding:4px 10px">Delete</button>' +
      '</td>' +
    '</tr>';
  }).join('');
}

async function drMarkContacted(id) {
  await apiFetch('/super-admin/api/demo-requests/' + id + '/contacted', { method: 'POST' });
  await loadDemoRequests();
}

async function drDelete(id) {
  if (!confirm('Delete this demo request? This cannot be undone.')) return;
  await apiFetch('/super-admin/api/demo-requests/' + id, { method: 'DELETE' });
  await loadDemoRequests();
}

loadDemoRequests();
