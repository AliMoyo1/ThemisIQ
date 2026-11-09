var CAN_MANAGE = document.getElementById('govRoot').dataset.canManage === 'true';
var GOV_AI_ON = document.getElementById('govRoot').dataset.aiOn === 'true';
var govActiveTab = 'bu';
var govBuList = [];
var govDeptList = [];
var govRegList = [];
var govRegFwNames = [];

function esc(s){return (s==null?'':(''+s)).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c])}
function govId(value){
  var id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : '';
}
document.addEventListener('click', function(event){
  var tab = event.target.closest('.gov-tab[data-tab]');
  if(tab){ govSwitchTab(tab.dataset.tab); return; }
  if(event.target.matches('#govModal .modal-overlay, #govModal [data-gov-backdrop]')){
    govCloseModal(); return;
  }
  var control = event.target.closest('[data-gov-action]');
  if(!control) return;
  var action = control.dataset.govAction;
  if(action === 'close-modal'){ govCloseModal(); return; }
  if(!CAN_MANAGE) return;
  if(action === 'open-add'){ govOpenAdd(); return; }
  if(action === 'run-drift'){ govRunDriftCheck(); return; }
  var id = govId(control.dataset.id) || null;
  var actions = {
    'edit-bu':govEditBu, 'delete-bu':govDeleteBu, 'save-bu':govSaveBu,
    'edit-dept':govEditDept, 'delete-dept':govDeleteDept, 'save-dept':govSaveDept,
    'edit-bp':govEditBp, 'delete-bp':govDeleteBp, 'save-bp':govSaveBp,
    'edit-app':govEditApp, 'delete-app':govDeleteApp, 'save-app':govSaveApp,
    'edit-ctrl':govEditCtrl, 'delete-ctrl':govDeleteCtrl, 'save-ctrl':govSaveCtrl,
    'edit-da':govEditDa, 'delete-da':govDeleteDa, 'save-da':govSaveDa,
    'edit-reg':govEditReg, 'delete-reg':govDeleteReg, 'save-reg':govSaveReg,
    'dismiss-reg':govDismissReg, 'review-reg':govReviewRegAi,
  };
  if(action === 'decide-reg'){
    if(id && ['approved','rejected'].includes(control.dataset.decision))
      govDecideRegAi(id, control.dataset.decision);
    return;
  }
  if(!Object.prototype.hasOwnProperty.call(actions,action)) return;
  if(action.startsWith('save-') || id) actions[action](id);
});
document.getElementById('govRoot').addEventListener('change', function(event){
  var id = event.target.id;
  if(id === 'deptBuFilter') govLoadDepts();
  else if(id === 'bpBuFilter' || id === 'bpDeptFilter') govLoadBps();
  else if(id === 'appBuFilter') govLoadApps();
  else if(id === 'ctrlBuFilter') govLoadControls();
  else if(id === 'daBuFilter' || id === 'daClassFilter') govLoadDas();
  else if(id === 'regStatusFilter') govLoadReg();
});
function govSafeSourceUrl(value){try{var url=new URL(value);return url.protocol==='https:'&&url.hostname&& !url.username&&!url.password?url.href:'';}catch(_){return '';}}
function apiFetch(url, opts){return fetch(url, Object.assign({credentials:'same-origin', headers:{'Content-Type':'application/json'}}, opts||{})).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.status===204?null:r.json()})}

function critBadge(c){var m={critical:'crit',high:'high',medium:'med',low:'low'};return '<span class="badge badge-'+(Object.prototype.hasOwnProperty.call(m,c)?m[c]:'med')+'">'+esc(c||'medium')+'</span>'}
function classBadge(c){var m={restricted:'restricted',confidential:'confidential',internal:'internal',public:'public'};return '<span class="badge badge-'+(Object.prototype.hasOwnProperty.call(m,c)?m[c]:'internal')+'">'+esc(c||'internal')+'</span>'}
function sensitivityChips(row){
  var out=[];
  if(row.contains_pii) out.push('<span class="badge badge-pii">PII</span>');
  if(row.contains_phi) out.push('<span class="badge badge-pii">PHI</span>');
  if(row.contains_financial) out.push('<span class="badge badge-pii">FIN</span>');
  if(row.contains_ip) out.push('<span class="badge badge-pii">IP</span>');
  return out.join(' ') || '<span data-s="s6d034cc">–</span>';
}

// ── Tab switching ────────────────────────────────────────────────────
function govSwitchTab(tab){
  if(!document.querySelector('.gov-tab[data-tab="'+tab+'"]')) return;
  govActiveTab = tab;
  document.querySelectorAll('.gov-tab').forEach(b=>b.classList.toggle('active', b.dataset.tab===tab));
  document.querySelectorAll('.tab-view').forEach(v=>v.classList.remove('active'));
  document.getElementById('tab-'+tab).classList.add('active');
  var addBtn = document.querySelector('.gov-header .gov-btn');
  if(addBtn){
    if(tab==='people'){ addBtn.style.display='none'; }
    else{
      addBtn.style.display='';
      addBtn.innerHTML = '<span>+</span> Add ' + {bu:'Business Unit',dept:'Department',bp:'Process',app:'Application',ctrl:'Control',da:'Data Asset',reg:'Regulatory Update'}[tab];
    }
  }
  govLoadTab(tab);
}

function govLoadTab(tab){
  if(tab==='bu') govLoadBus();
  else if(tab==='dept') govLoadDepts();
  else if(tab==='bp') govLoadBps();
  else if(tab==='app') govLoadApps();
  else if(tab==='ctrl') govLoadControls();
  else if(tab==='da') govLoadDas();
  else if(tab==='reg') govLoadReg();
  else if(tab==='people') govLoadPeople();
}

// ── People / BU assignment ──────────────────────────────────────────
function govLoadPeople(){
  var body = document.getElementById('peopleBody');
  apiFetch('/governance/api/users').then(function(users){
    if(!users || !users.length){ body.innerHTML='<tr><td colspan="3" data-s="sa1e3045">No users</td></tr>'; return; }
    var rows = users.map(function(u){
      return '<tr><td><strong>'+esc(u.full_name||u.username)+'</strong><div data-s="s1fd8c81">@'+esc(u.username)+'</div></td>'+
        '<td data-s="s7fc448e">'+esc(u.email||'')+'</td>'+
        '<td><span data-s="s6cb285c">'+esc(u.business_unit_name||'Unassigned')+'</span>'+
        ' <a href="/admin/users" data-s="sea54340">Move SBU</a></td></tr>';
    });
    body.innerHTML = rows.join('');
  }).catch(function(){ body.innerHTML='<tr><td colspan="3" data-s="sabf5cc1">Failed to load</td></tr>'; });
}

// ── Summary ──────────────────────────────────────────────────────────
function govLoadSummary(){
  apiFetch('/governance/api/summary').then(d=>{
    document.getElementById('sBu').textContent = d.business_units || 0;
    document.getElementById('sDept').textContent = d.departments || 0;
    document.getElementById('sBp').textContent = d.business_processes || 0;
    document.getElementById('sApp').textContent = d.applications || 0;
    document.getElementById('sCtrl').textContent = d.canonical_controls || 0;
    document.getElementById('sDa').textContent = d.data_assets || 0;
    document.getElementById('sReg').textContent = d.open_regulatory_updates || 0;
  }).catch(()=>{});
}

// ── Business Units (tree) ───────────────────────────────────────────
function govLoadBus(){
  Promise.all([
    apiFetch('/governance/api/business-units/tree'),
    apiFetch('/governance/api/business-units')
  ]).then(([tree, flat])=>{
    govBuList = flat;
    updateBuDropdowns();
    var wrap = document.getElementById('buTree');
    var empty = document.getElementById('buEmpty');
    if(!tree.length){wrap.innerHTML=''; empty.style.display='block'; return}
    empty.style.display='none';
    wrap.innerHTML = tree.map(renderBuNode).join('');
  }).catch(err=>console.error('Load BUs failed', err));
}

function renderBuNode(n){
  var kids = (n.children||[]).map(renderBuNode).join('');
  var code = n.code ? '<span class="tree-node-code">'+esc(n.code)+'</span>' : '';
  var head = n.head_name ? '<span data-s="sbf8965d"> — head: '+esc(n.head_name)+'</span>' : '';
  var actions = CAN_MANAGE ? (
    '<button class="gov-btn ghost small" data-gov-action="edit-bu" data-id="'+govId(n.id)+'">Edit</button>' +
    '<button class="gov-btn ghost small" data-gov-action="delete-bu" data-id="'+govId(n.id)+'">Delete</button>'
  ) : '';
  return '<li>'
    + '<div class="tree-node">'
      + '<div class="tree-node-info">'
        + '<div><span class="tree-node-name">'+esc(n.name)+'</span>'+code+head+'</div>'
        + (n.description ? '<div class="tree-node-desc">'+esc(n.description)+'</div>' : '')
      + '</div>'
      + '<div class="tree-node-actions">'+actions+'</div>'
    + '</div>'
    + (kids ? '<ul>'+kids+'</ul>' : '')
  + '</li>';
}

function updateBuDropdowns(){
  var opts = '<option value="">All Business Units</option>' + govBuList.map(b=>'<option value="'+govId(b.id)+'">'+esc(b.name)+'</option>').join('');
  ['deptBuFilter','bpBuFilter','appBuFilter','ctrlBuFilter','daBuFilter'].forEach(id=>{
    var sel = document.getElementById(id);
    if(!sel) return;
    var cur = sel.value;
    sel.innerHTML = opts;
    sel.value = cur;
  });
}

function govEditBu(id){
  var bu = govBuList.find(b=>b.id===id);
  if(!bu) return;
  govOpenBuModal(bu);
}

function govDeleteBu(id){
  if(!confirm('Delete this business unit? Fails if it has children or is referenced by other entities.')) return;
  apiFetch('/governance/api/business-units/'+id, {method:'DELETE'})
    .then(()=>{ govLoadBus(); govLoadSummary(); })
    .catch(err=>alert('Delete failed: '+err.message));
}

// ── Departments ─────────────────────────────────────────────────────
function govLoadDepts(){
  var bu = document.getElementById('deptBuFilter').value;
  var url = '/governance/api/departments' + (bu ? '?bu_id='+bu : '');
  apiFetch(url).then(rows=>{
    govDeptList = rows;
    var tbody = document.getElementById('deptTBody');
    if(!rows.length){tbody.innerHTML='<tr><td colspan="6" data-s="sa1e3045">No departments yet.</td></tr>'; return}
    tbody.innerHTML = rows.map(r=>{
      var actions = CAN_MANAGE ? (
        '<button class="gov-btn ghost small" data-gov-action="edit-dept" data-id="'+govId(r.id)+'">Edit</button> '+
        '<button class="gov-btn ghost small" data-gov-action="delete-dept" data-id="'+govId(r.id)+'">Delete</button>'
      ) : '';
      return '<tr>'
        + '<td><strong>'+esc(r.name)+'</strong>'+(r.description ? '<br><small data-s="s57f9e31">'+esc(r.description)+'</small>' : '')+'</td>'
        + '<td>'+(r.code ? '<code data-s="s5f0ff92">'+esc(r.code)+'</code>' : '–')+'</td>'
        + '<td>'+esc(r.bu_name || '–')+'</td>'
        + '<td>'+esc(r.head_name || '–')+'</td>'
        + '<td>'+(r.is_active ? '<span class="badge" data-s="s6f12565">Active</span>' : '<span class="badge badge-inactive">Inactive</span>')+'</td>'
        + '<td class="actions">'+actions+'</td>'
      + '</tr>';
    }).join('');
  });
}

function govEditDept(id){
  var d = govDeptList.find(x=>x.id===id);
  if(d) govOpenDeptModal(d);
}

function govDeleteDept(id){
  if(!confirm('Delete this department?')) return;
  apiFetch('/governance/api/departments/'+id, {method:'DELETE'})
    .then(()=>{ govLoadDepts(); govLoadSummary(); })
    .catch(err=>alert('Delete failed: '+err.message));
}

// ── Business Processes ──────────────────────────────────────────────
var govBpList = [];
var govBpUsesAiBefore = '|';
function govLoadBps(){
  var bu = document.getElementById('bpBuFilter').value;
  var dept = document.getElementById('bpDeptFilter').value;
  var qs = [];
  if(bu) qs.push('bu_id='+bu);
  if(dept) qs.push('dept_id='+dept);
  apiFetch('/governance/api/business-processes' + (qs.length ? '?'+qs.join('&') : '')).then(rows=>{
    govBpList = rows;
    var tbody = document.getElementById('bpTBody');
    if(!rows.length){tbody.innerHTML='<tr><td colspan="7" data-s="sa1e3045">No processes yet.</td></tr>'; return}
    tbody.innerHTML = rows.map(r=>{
      var actions = '<a class="gov-btn ghost small" href="/governance/connected/governance/process/'+govId(r.id)+'">Connected</a> ' + (CAN_MANAGE ? (
        '<button class="gov-btn ghost small" data-gov-action="edit-bp" data-id="'+govId(r.id)+'">Edit</button> '+
        '<button class="gov-btn ghost small" data-gov-action="delete-bp" data-id="'+govId(r.id)+'">Delete</button>'
      ) : '');
      var rto = r.rto_hours!=null ? r.rto_hours+'h' : '–';
      var rpo = r.rpo_hours!=null ? r.rpo_hours+'h' : '–';
      return '<tr>'
        + '<td><strong>'+esc(r.name)+'</strong>'+(r.description ? '<br><small data-s="s57f9e31">'+esc(r.description)+'</small>' : '')+'</td>'
        + '<td>'+esc(r.bu_name || '–')+'</td>'
        + '<td>'+esc(r.dept_name || '–')+'</td>'
        + '<td>'+esc(r.owner_name || '–')+'</td>'
        + '<td>'+critBadge(r.criticality)+'</td>'
        + '<td>'+rto+' / '+rpo+'</td>'
        + '<td class="actions">'+actions+'</td>'
      + '</tr>';
    }).join('');
  });
  // Populate dept filter with current BU's departments
  if(bu){
    apiFetch('/governance/api/departments?bu_id='+bu).then(depts=>{
      var sel = document.getElementById('bpDeptFilter');
      var cur = sel.value;
      sel.innerHTML = '<option value="">All Departments</option>' + depts.map(d=>'<option value="'+govId(d.id)+'">'+esc(d.name)+'</option>').join('');
      sel.value = cur;
    });
  }
}

function govEditBp(id){var r = govBpList.find(x=>x.id===id); if(r) govOpenBpModal(r);}
function govDeleteBp(id){if(!confirm('Delete this business process?')) return; apiFetch('/governance/api/business-processes/'+id, {method:'DELETE'}).then(()=>{ govLoadBps(); govLoadSummary(); }).catch(err=>alert(err.message));}

// ── Applications ────────────────────────────────────────────────────
var govAppList = [];
function govLoadApps(){
  var bu = document.getElementById('appBuFilter').value;
  apiFetch('/governance/api/applications' + (bu ? '?bu_id='+bu : '')).then(rows=>{
    govAppList = rows;
    var tbody = document.getElementById('appTBody');
    if(!rows.length){tbody.innerHTML='<tr><td colspan="8" data-s="sa1e3045">No applications yet.</td></tr>'; return}
    tbody.innerHTML = rows.map(r=>{
      var actions = '<a class="gov-btn ghost small" href="/governance/connected/governance/application/'+govId(r.id)+'">Connected</a> ' + (GOV_AI_ON && r.has_ai_profile ? '<a class="gov-btn ghost small" href="/ai-governance/systems/'+govId(r.id)+'">AI workspace</a> ' : '') + (CAN_MANAGE ? (
        '<button class="gov-btn ghost small" data-gov-action="edit-app" data-id="'+govId(r.id)+'">Edit</button> '+
        '<button class="gov-btn ghost small" data-gov-action="delete-app" data-id="'+govId(r.id)+'">Delete</button>'
      ) : '');
      return '<tr>'
        + '<td><strong>'+esc(r.name)+'</strong>'+(r.description ? '<br><small data-s="s57f9e31">'+esc(r.description)+'</small>' : '')+'</td>'
        + '<td>'+esc(r.application_type || '–')+'</td>'
        + '<td>'+esc(r.hosting || '–')+'</td>'
        + '<td>'+esc(r.vendor_name || '–')+'</td>'
        + '<td>'+esc(r.bu_name || '–')+'</td>'
        + '<td>'+esc(r.owner_name || '–')+'</td>'
        + '<td>'+critBadge(r.criticality)+'</td>'
        + '<td class="actions">'+actions+'</td>'
      + '</tr>';
    }).join('');
  });
}

function govEditApp(id){var r = govAppList.find(x=>x.id===id); if(r) govOpenAppModal(r);}
function govDeleteApp(id){if(!confirm('Delete this application?')) return; apiFetch('/governance/api/applications/'+id, {method:'DELETE'}).then(()=>{ govLoadApps(); govLoadSummary(); }).catch(err=>alert(err.message));}

// ── Canonical Controls ───────────────────────────────────────────────
function govScoreColor(s){
  if(s==null) return '';
  if(s>=100) return 'background:rgba(59,130,246,.15);color:#3b82f6';
  if(s>=60)  return 'background:rgba(22,163,74,.15);color:#16a34a';
  if(s>=30)  return 'background:rgba(234,179,8,.15);color:#ca8a04';
  return 'background:rgba(220,38,38,.15);color:#dc2626';
}
var govCtrlList = [];
function govLoadControls(){
  var bu = document.getElementById('ctrlBuFilter').value;
  apiFetch('/governance/api/controls' + (bu ? '?bu_id='+bu : '')).then(rows=>{
    govCtrlList = rows;
    var tbody = document.getElementById('ctrlTBody');
    if(!rows.length){tbody.innerHTML='<tr><td colspan="8" data-s="sa1e3045">No controls yet.</td></tr>'; return}
    tbody.innerHTML = rows.map(r=>{
      var actions = CAN_MANAGE ? (
        '<button class="gov-btn ghost small" data-gov-action="edit-ctrl" data-id="'+govId(r.id)+'">Edit</button> '+
        '<button class="gov-btn ghost small" data-gov-action="delete-ctrl" data-id="'+govId(r.id)+'">Delete</button>'
      ) : '';
      var lastTested = r.last_tested_at ? esc(String(r.last_tested_at).substring(0,10)) : '–';
      var score = Number(r.score);
      var scoreBadge = r.score!=null && Number.isFinite(score) && score>=0 && score<=100
        ? '<span class="badge" title="Scored: '+esc(String(r.scored_at||'').substring(0,10))+'" data-sv="'+govScoreColor(score)+'">'+score+'</span>'
        : '<span data-s="s0096636">–</span>';
      return '<tr>'
        + '<td><code data-s="s5f0ff92">'+esc(r.ref || '–')+'</code></td>'
        + '<td><strong>'+esc(r.title)+'</strong>'+(r.description ? '<br><small data-s="s57f9e31">'+esc(r.description)+'</small>' : '')+'</td>'
        + '<td>'+esc(r.owner_name || '–')+'</td>'
        + '<td>'+esc(r.automation || '–')+'</td>'
        + '<td>'+lastTested+'</td>'
        + '<td>'+scoreBadge+'</td>'
        + '<td>'+(r.is_active ? '<span class="badge" data-s="s6f12565">Active</span>' : '<span class="badge badge-inactive">Inactive</span>')+'</td>'
        + '<td class="actions">'+actions+'</td>'
      + '</tr>';
    }).join('');
  });
}

function govEditCtrl(id){var r = govCtrlList.find(x=>x.id===id); if(r) govOpenCtrlModal(r);}
function govDeleteCtrl(id){
  if(!confirm('Delete this control?')) return;
  apiFetch('/governance/api/controls/'+id, {method:'DELETE'})
    .then(()=>{ govLoadControls(); govLoadSummary(); })
    .catch(err=>alert('Delete failed: '+err.message));
}

function govOpenCtrlModal(row){
  var isEdit = !!row;
  document.getElementById('govModal').innerHTML =
    '<div class="modal-overlay" data-gov-backdrop="true">'
    + '<div class="modal-box">'
      + '<button class="modal-close" data-gov-action="close-modal">×</button>'
      + '<div class="modal-title">'+(isEdit ? 'Edit' : 'New')+' Control</div>'
      + '<div class="form-group"><label>Title *</label><input id="ctrl_title" value="'+esc(row?row.title:'')+'"></div>'
      + '<div class="form-row">'
        + '<div class="form-group"><label>Ref</label><input id="ctrl_ref" value="'+esc(row?(row.ref||''):'')+'"></div>'
        + '<div class="form-group"><label>Automation</label><select id="ctrl_auto"><option value="">—</option><option value="manual">Manual</option><option value="semi-automated">Semi-automated</option><option value="automated">Automated</option></select></div>'
      + '</div>'
      + '<div class="form-row-3">'
        + '<div class="form-group"><label>P2sT2 Category</label><select id="ctrl_p2st2"><option value="">—</option><option value="People">People</option><option value="Process">Process</option><option value="System">System</option><option value="Technology">Technology</option><option value="Tool">Tool</option></select></div>'
        + '<div class="form-group"><label>Business Unit</label><select id="ctrl_bu"><option value="">— None —</option>'+buOptions()+'</select></div>'
      + '<div class="form-group"><label>Test Frequency (days)</label><input type="number" step="1" id="ctrl_freq" value="'+esc(row&&row.test_frequency_days!=null?row.test_frequency_days:'')+'"></div>'
      + '</div>'
      + '<div class="form-group"><label>Last Tested</label><input type="date" id="ctrl_lasttest" value="'+esc(row&&row.last_tested_at?String(row.last_tested_at).substring(0,10):'')+'"></div>'
      + '<div class="form-group"><label>Description</label><textarea id="ctrl_desc" rows="3">'+esc(row?(row.description||''):'')+'</textarea></div>'
      + (isEdit ? '<div class="form-check"><input type="checkbox" id="ctrl_active"'+(row.is_active?' checked':'')+'><label for="ctrl_active">Active</label></div>' : '')
      + '<div class="modal-actions">'
        + '<button class="gov-btn ghost" data-gov-action="close-modal">Cancel</button>'
        + '<button class="gov-btn" data-gov-action="save-ctrl" data-id="'+govId(row?row.id:null)+'">Save</button>'
      + '</div>'
    + '</div></div>';
  if(isEdit){
    document.getElementById('ctrl_auto').value = row.automation || '';
    document.getElementById('ctrl_bu').value = row.business_unit_id || '';
    document.getElementById('ctrl_p2st2').value = row.p2st2_category || '';
  }
}

function govSaveCtrl(id){
  var body = {
    title: document.getElementById('ctrl_title').value.trim(),
    ref: document.getElementById('ctrl_ref').value.trim(),
    automation: document.getElementById('ctrl_auto').value || null,
    p2st2_category: document.getElementById('ctrl_p2st2').value || null,
    business_unit_id: parseInt(document.getElementById('ctrl_bu').value) || null,
    test_frequency_days: parseInt(document.getElementById('ctrl_freq').value) || null,
    last_tested_at: document.getElementById('ctrl_lasttest').value || null,
    description: document.getElementById('ctrl_desc').value.trim(),
  };
  if(id) body.is_active = document.getElementById('ctrl_active').checked ? 1 : 0;
  apiFetch('/governance/api/controls' + (id ? '/'+id : ''), {method: id ? 'PUT' : 'POST', body: JSON.stringify(body)})
    .then(()=>{ govCloseModal(); govLoadControls(); govLoadSummary(); })
    .catch(err=>alert('Save failed: '+err.message));
}

// ── Data Assets ─────────────────────────────────────────────────────
var govDaList = [];
function govLoadDas(){
  var bu = document.getElementById('daBuFilter').value;
  var cls = document.getElementById('daClassFilter').value;
  var qs = [];
  if(bu) qs.push('bu_id='+bu);
  if(cls) qs.push('classification='+cls);
  apiFetch('/governance/api/data-assets' + (qs.length ? '?'+qs.join('&') : '')).then(rows=>{
    govDaList = rows;
    var tbody = document.getElementById('daTBody');
    if(!rows.length){tbody.innerHTML='<tr><td colspan="7" data-s="sa1e3045">No data assets yet.</td></tr>'; return}
    tbody.innerHTML = rows.map(r=>{
      var actions = '<a class="gov-btn ghost small" href="/governance/connected/governance/data_asset/'+govId(r.id)+'">Connected</a> ' + (CAN_MANAGE ? (
        '<button class="gov-btn ghost small" data-gov-action="edit-da" data-id="'+govId(r.id)+'">Edit</button> '+
        '<button class="gov-btn ghost small" data-gov-action="delete-da" data-id="'+govId(r.id)+'">Delete</button>'
      ) : '');
      return '<tr>'
        + '<td><strong>'+esc(r.name)+'</strong>'+(r.description ? '<br><small data-s="s57f9e31">'+esc(r.description)+'</small>' : '')+'</td>'
        + '<td>'+esc(r.category || '–')+'</td>'
        + '<td>'+classBadge(r.classification)+'</td>'
        + '<td>'+esc(r.application_name || '–')+'</td>'
        + '<td>'+esc(r.bu_name || '–')+'</td>'
        + '<td>'+sensitivityChips(r)+'</td>'
        + '<td class="actions">'+actions+'</td>'
      + '</tr>';
    }).join('');
  });
}

function govEditDa(id){var r = govDaList.find(x=>x.id===id); if(r) govOpenDaModal(r);}
function govDeleteDa(id){if(!confirm('Delete this data asset?')) return; apiFetch('/governance/api/data-assets/'+id, {method:'DELETE'}).then(()=>{ govLoadDas(); govLoadSummary(); }).catch(err=>alert(err.message));}

// ── Modals ──────────────────────────────────────────────────────────
function govCloseModal(){document.getElementById('govModal').innerHTML='';}
function govOpenAdd(){
  var openers = {bu:govOpenBuModal, dept:govOpenDeptModal, bp:govOpenBpModal, app:govOpenAppModal, ctrl:govOpenCtrlModal, da:govOpenDaModal, reg:govOpenRegModal};
  (openers[govActiveTab] || govOpenBuModal)(null);
}

function buOptions(exclude){
  return govBuList.filter(b=>!exclude || b.id!==exclude).map(b=>'<option value="'+govId(b.id)+'">'+esc(b.name)+'</option>').join('');
}

function govOpenBuModal(row){
  var isEdit = !!row;
  document.getElementById('govModal').innerHTML =
    '<div class="modal-overlay" data-gov-backdrop="true">'
    + '<div class="modal-box">'
      + '<button class="modal-close" data-gov-action="close-modal">×</button>'
      + '<div class="modal-title">'+(isEdit ? 'Edit' : 'New')+' Business Unit</div>'
      + '<div class="form-group"><label>Name *</label><input id="bu_name" value="'+esc(row?row.name:'')+'"></div>'
      + '<div class="form-row">'
        + '<div class="form-group"><label>Code</label><input id="bu_code" value="'+esc(row?(row.code||''):'')+'"></div>'
        + '<div class="form-group"><label>Parent Unit</label><select id="bu_parent"><option value="">— None (root) —</option>'+buOptions(row?row.id:null)+'</select></div>'
      + '</div>'
      + '<div class="form-group"><label>Description</label><textarea id="bu_desc" rows="3">'+esc(row?(row.description||''):'')+'</textarea></div>'
      + (isEdit ? '<div class="form-check"><input type="checkbox" id="bu_active"'+(row.is_active?' checked':'')+'><label for="bu_active">Active</label></div>' : '')
      + '<div class="modal-actions">'
        + '<button class="gov-btn ghost" data-gov-action="close-modal">Cancel</button>'
        + '<button class="gov-btn" data-gov-action="save-bu" data-id="'+govId(row?row.id:null)+'">Save</button>'
      + '</div>'
    + '</div></div>';
  if(isEdit) document.getElementById('bu_parent').value = row.parent_id || '';
}

function govSaveBu(id){
  var body = {
    name: document.getElementById('bu_name').value.trim(),
    code: document.getElementById('bu_code').value.trim(),
    parent_id: parseInt(document.getElementById('bu_parent').value) || null,
    description: document.getElementById('bu_desc').value.trim(),
  };
  if(id){
    body.is_active = document.getElementById('bu_active').checked ? 1 : 0;
  }
  var url = '/governance/api/business-units' + (id ? '/'+id : '');
  apiFetch(url, {method: id ? 'PUT' : 'POST', body: JSON.stringify(body)})
    .then(()=>{ govCloseModal(); govLoadBus(); govLoadSummary(); })
    .catch(err=>alert('Save failed: '+err.message));
}

function govOpenDeptModal(row){
  var isEdit = !!row;
  document.getElementById('govModal').innerHTML =
    '<div class="modal-overlay" data-gov-backdrop="true">'
    + '<div class="modal-box">'
      + '<button class="modal-close" data-gov-action="close-modal">×</button>'
      + '<div class="modal-title">'+(isEdit ? 'Edit' : 'New')+' Department</div>'
      + '<div class="form-group"><label>Name *</label><input id="dept_name" value="'+esc(row?row.name:'')+'"></div>'
      + '<div class="form-row">'
        + '<div class="form-group"><label>Code</label><input id="dept_code" value="'+esc(row?(row.code||''):'')+'"></div>'
        + '<div class="form-group"><label>Business Unit</label><select id="dept_bu"><option value="">— None —</option>'+buOptions()+'</select></div>'
      + '</div>'
      + '<div class="form-group"><label>Description</label><textarea id="dept_desc" rows="3">'+esc(row?(row.description||''):'')+'</textarea></div>'
      + (isEdit ? '<div class="form-check"><input type="checkbox" id="dept_active"'+(row.is_active?' checked':'')+'><label for="dept_active">Active</label></div>' : '')
      + '<div class="modal-actions">'
        + '<button class="gov-btn ghost" data-gov-action="close-modal">Cancel</button>'
        + '<button class="gov-btn" data-gov-action="save-dept" data-id="'+govId(row?row.id:null)+'">Save</button>'
      + '</div>'
    + '</div></div>';
  if(isEdit) document.getElementById('dept_bu').value = row.business_unit_id || '';
}

function govSaveDept(id){
  var body = {
    name: document.getElementById('dept_name').value.trim(),
    code: document.getElementById('dept_code').value.trim(),
    business_unit_id: parseInt(document.getElementById('dept_bu').value) || null,
    description: document.getElementById('dept_desc').value.trim(),
  };
  if(id) body.is_active = document.getElementById('dept_active').checked ? 1 : 0;
  apiFetch('/governance/api/departments' + (id ? '/'+id : ''), {method: id ? 'PUT' : 'POST', body: JSON.stringify(body)})
    .then(()=>{ govCloseModal(); govLoadDepts(); govLoadSummary(); })
    .catch(err=>alert('Save failed: '+err.message));
}

function govOpenBpModal(row){
  var isEdit = !!row;
  document.getElementById('govModal').innerHTML =
    '<div class="modal-overlay" data-gov-backdrop="true">'
    + '<div class="modal-box">'
      + '<button class="modal-close" data-gov-action="close-modal">×</button>'
      + '<div class="modal-title">'+(isEdit ? 'Edit' : 'New')+' Business Process</div>'
      + '<div class="form-group"><label>Name *</label><input id="bp_name" value="'+esc(row?row.name:'')+'"></div>'
      + '<div class="form-row">'
        + '<div class="form-group"><label>Code</label><input id="bp_code" value="'+esc(row?(row.code||''):'')+'"></div>'
        + '<div class="form-group"><label>Criticality</label><select id="bp_crit"><option value="low">Low</option><option value="medium" selected>Medium</option><option value="high">High</option><option value="critical">Critical</option></select></div>'
      + '</div>'
      + '<div class="form-row">'
        + '<div class="form-group"><label>Business Unit</label><select id="bp_bu"><option value="">— None —</option>'+buOptions()+'</select></div>'
        + '<div class="form-group"><label>Department</label><select id="bp_dept"><option value="">— None —</option></select></div>'
      + '</div>'
      + '<div class="form-row-3">'
        + '<div class="form-group"><label>RTO (hours)</label><input type="number" step="0.5" id="bp_rto" value="'+(row&&row.rto_hours!=null?row.rto_hours:'')+'"></div>'
        + '<div class="form-group"><label>RPO (hours)</label><input type="number" step="0.5" id="bp_rpo" value="'+(row&&row.rpo_hours!=null?row.rpo_hours:'')+'"></div>'
        + '<div class="form-group"><label>Revenue impact / hr</label><input type="number" step="1" id="bp_rev" value="'+(row&&row.revenue_impact_per_hour!=null?row.revenue_impact_per_hour:'')+'"></div>'
      + '</div>'
      + '<div class="form-group"><label>Description</label><textarea id="bp_desc" rows="3">'+esc(row?(row.description||''):'')+'</textarea></div>'
      + (GOV_AI_ON ? '<div class="form-row">'
        + '<div class="form-group"><label>Uses AI or embedded AI?</label><select id="bp_uses_ai"><option value="">Not asked</option><option value="yes">Yes</option><option value="no">No</option><option value="unknown">Not sure</option></select></div>'
        + '<div class="form-group"><label>What does the AI do?</label><input id="bp_uses_ai_note" maxlength="500" value="'+esc(row?(row.uses_ai_note||''):'')+'"></div>'
      + '</div>' : '')
      + (isEdit ? '<div class="form-check"><input type="checkbox" id="bp_active"'+(row.is_active?' checked':'')+'><label for="bp_active">Active</label></div>' : '')
      + '<div class="modal-actions">'
        + '<button class="gov-btn ghost" data-gov-action="close-modal">Cancel</button>'
        + '<button class="gov-btn" data-gov-action="save-bp" data-id="'+govId(row?row.id:null)+'">Save</button>'
      + '</div>'
    + '</div></div>';
  govBpUsesAiBefore = row ? ((row.uses_ai || '') + '|' + (row.uses_ai_note || '')) : '|';
  if(isEdit){
    document.getElementById('bp_bu').value = row.business_unit_id || '';
    document.getElementById('bp_crit').value = row.criticality || 'medium';
    if(document.getElementById('bp_uses_ai')) document.getElementById('bp_uses_ai').value = row.uses_ai || '';
    _refreshBpDeptOptions(row.business_unit_id, row.department_id);
  }
  document.getElementById('bp_bu').addEventListener('change', function(){
    _refreshBpDeptOptions(this.value || null, null);
  });
}
function _refreshBpDeptOptions(buId, selectedDeptId){
  var url = '/governance/api/departments' + (buId ? '?bu_id='+buId : '');
  apiFetch(url).then(depts=>{
    var sel = document.getElementById('bp_dept');
    sel.innerHTML = '<option value="">— None —</option>' + depts.map(d=>'<option value="'+govId(d.id)+'">'+esc(d.name)+'</option>').join('');
    if(selectedDeptId) sel.value = selectedDeptId;
  });
}

function govSaveBp(id){
  var body = {
    name: document.getElementById('bp_name').value.trim(),
    code: document.getElementById('bp_code').value.trim(),
    business_unit_id: parseInt(document.getElementById('bp_bu').value) || null,
    department_id: parseInt(document.getElementById('bp_dept').value) || null,
    criticality: document.getElementById('bp_crit').value,
    rto_hours: parseFloat(document.getElementById('bp_rto').value) || null,
    rpo_hours: parseFloat(document.getElementById('bp_rpo').value) || null,
    revenue_impact_per_hour: parseFloat(document.getElementById('bp_rev').value) || null,
    description: document.getElementById('bp_desc').value.trim(),
  };
  if(id) body.is_active = document.getElementById('bp_active').checked ? 1 : 0;
  var usesAiBox = document.getElementById('bp_uses_ai');
  var usesAi = usesAiBox ? usesAiBox.value : '', usesAiNote = usesAiBox ? document.getElementById('bp_uses_ai_note').value.trim() : '';
  apiFetch('/governance/api/business-processes' + (id ? '/'+id : ''), {method: id ? 'PUT' : 'POST', body: JSON.stringify(body)})
    .then(res=>{
      var pid = id || (res && res.id);
      if(pid && usesAi && (usesAi + '|' + usesAiNote) !== govBpUsesAiBefore){
        return apiFetch('/ai-governance/api/flags/process/'+pid, {method: 'PUT',
          body: JSON.stringify({answer: usesAi, note: usesAiNote, source: 'Governance settings'})});
      }
    })
    .then(()=>{ govCloseModal(); govLoadBps(); govLoadSummary(); })
    .catch(err=>alert('Save failed: '+err.message));
}

function govOpenAppModal(row){
  var isEdit = !!row;
  document.getElementById('govModal').innerHTML =
    '<div class="modal-overlay" data-gov-backdrop="true">'
    + '<div class="modal-box">'
      + '<button class="modal-close" data-gov-action="close-modal">×</button>'
      + '<div class="modal-title">'+(isEdit ? 'Edit' : 'New')+' Application</div>'
      + '<div class="form-group"><label>Name *</label><input id="app_name" value="'+esc(row?row.name:'')+'"></div>'
      + '<div class="form-row">'
        + '<div class="form-group"><label>Type</label><select id="app_type"><option value="">—</option><option value="saas">SaaS</option><option value="on_prem">On-premise</option><option value="custom">Custom-built</option><option value="mobile">Mobile</option><option value="manual">Manual process</option></select></div>'
        + '<div class="form-group"><label>Hosting</label><select id="app_host"><option value="">—</option><option value="cloud">Cloud</option><option value="on_prem">On-premise</option><option value="hybrid">Hybrid</option><option value="n/a">N/A</option></select></div>'
      + '</div>'
      + '<div class="form-row">'
        + '<div class="form-group"><label>Business Unit</label><select id="app_bu"><option value="">— None —</option>'+buOptions()+'</select></div>'
        + '<div class="form-group"><label>Criticality</label><select id="app_crit"><option value="low">Low</option><option value="medium" selected>Medium</option><option value="high">High</option><option value="critical">Critical</option></select></div>'
      + '</div>'
      + '<div class="form-group"><label>Description</label><textarea id="app_desc" rows="3">'+esc(row?(row.description||''):'')+'</textarea></div>'
      + (isEdit ? '<div class="form-check"><input type="checkbox" id="app_active"'+(row.is_active?' checked':'')+'><label for="app_active">Active</label></div>' : '')
      + '<div class="modal-actions">'
        + '<button class="gov-btn ghost" data-gov-action="close-modal">Cancel</button>'
        + '<button class="gov-btn" data-gov-action="save-app" data-id="'+govId(row?row.id:null)+'">Save</button>'
      + '</div>'
    + '</div></div>';
  if(isEdit){
    document.getElementById('app_type').value = row.application_type || '';
    document.getElementById('app_host').value = row.hosting || '';
    document.getElementById('app_bu').value = row.business_unit_id || '';
    document.getElementById('app_crit').value = row.criticality || 'medium';
  }
}

function govSaveApp(id){
  var body = {
    name: document.getElementById('app_name').value.trim(),
    application_type: document.getElementById('app_type').value || null,
    hosting: document.getElementById('app_host').value || null,
    business_unit_id: parseInt(document.getElementById('app_bu').value) || null,
    criticality: document.getElementById('app_crit').value,
    description: document.getElementById('app_desc').value.trim(),
  };
  if(id) body.is_active = document.getElementById('app_active').checked ? 1 : 0;
  apiFetch('/governance/api/applications' + (id ? '/'+id : ''), {method: id ? 'PUT' : 'POST', body: JSON.stringify(body)})
    .then(()=>{ govCloseModal(); govLoadApps(); govLoadSummary(); })
    .catch(err=>alert('Save failed: '+err.message));
}

function govOpenDaModal(row){
  var isEdit = !!row;
  document.getElementById('govModal').innerHTML =
    '<div class="modal-overlay" data-gov-backdrop="true">'
    + '<div class="modal-box">'
      + '<button class="modal-close" data-gov-action="close-modal">×</button>'
      + '<div class="modal-title">'+(isEdit ? 'Edit' : 'New')+' Data Asset</div>'
      + '<div class="form-group"><label>Name *</label><input id="da_name" value="'+esc(row?row.name:'')+'"></div>'
      + '<div class="form-row">'
        + '<div class="form-group"><label>Category</label><input id="da_cat" value="'+esc(row?(row.category||''):'')+'" placeholder="e.g. customer_data, financial"></div>'
        + '<div class="form-group"><label>Classification</label><select id="da_class"><option value="public">Public</option><option value="internal" selected>Internal</option><option value="confidential">Confidential</option><option value="restricted">Restricted</option></select></div>'
      + '</div>'
      + '<div class="form-row">'
        + '<div class="form-group"><label>Business Unit</label><select id="da_bu"><option value="">— None —</option>'+buOptions()+'</select></div>'
        + '<div class="form-group"><label>Storage location</label><input id="da_loc" value="'+esc(row?(row.location||''):'')+'" placeholder="e.g. AWS S3, SharePoint"></div>'
      + '</div>'
      + '<div class="form-group"><label>Description</label><textarea id="da_desc" rows="3">'+esc(row?(row.description||''):'')+'</textarea></div>'
      + '<div data-s="s2cde380" data-sd="flex">'
        + '<div class="form-check"><input type="checkbox" id="da_pii"'+((row&&row.contains_pii)?' checked':'')+'><label for="da_pii">Contains PII</label></div>'
        + '<div class="form-check"><input type="checkbox" id="da_phi"'+((row&&row.contains_phi)?' checked':'')+'><label for="da_phi">Contains PHI</label></div>'
        + '<div class="form-check"><input type="checkbox" id="da_fin"'+((row&&row.contains_financial)?' checked':'')+'><label for="da_fin">Contains Financial</label></div>'
        + '<div class="form-check"><input type="checkbox" id="da_ip"'+((row&&row.contains_ip)?' checked':'')+'><label for="da_ip">Contains IP</label></div>'
      + '</div>'
      + (isEdit ? '<div class="form-check"><input type="checkbox" id="da_active"'+(row.is_active?' checked':'')+'><label for="da_active">Active</label></div>' : '')
      + '<div class="modal-actions">'
        + '<button class="gov-btn ghost" data-gov-action="close-modal">Cancel</button>'
        + '<button class="gov-btn" data-gov-action="save-da" data-id="'+govId(row?row.id:null)+'">Save</button>'
      + '</div>'
    + '</div></div>';
  if(isEdit){
    document.getElementById('da_class').value = row.classification || 'internal';
    document.getElementById('da_bu').value = row.business_unit_id || '';
  }
}

function govSaveDa(id){
  var body = {
    name: document.getElementById('da_name').value.trim(),
    category: document.getElementById('da_cat').value.trim() || null,
    classification: document.getElementById('da_class').value,
    business_unit_id: parseInt(document.getElementById('da_bu').value) || null,
    location: document.getElementById('da_loc').value.trim() || null,
    description: document.getElementById('da_desc').value.trim(),
    contains_pii: document.getElementById('da_pii').checked ? 1 : 0,
    contains_phi: document.getElementById('da_phi').checked ? 1 : 0,
    contains_financial: document.getElementById('da_fin').checked ? 1 : 0,
    contains_ip: document.getElementById('da_ip').checked ? 1 : 0,
  };
  if(id) body.is_active = document.getElementById('da_active').checked ? 1 : 0;
  apiFetch('/governance/api/data-assets' + (id ? '/'+id : ''), {method: id ? 'PUT' : 'POST', body: JSON.stringify(body)})
    .then(()=>{ govCloseModal(); govLoadDas(); govLoadSummary(); })
    .catch(err=>alert('Save failed: '+err.message));
}

// ── Regulatory Inbox ────────────────────────────────────────────────
function sevBadge(s){var m={info:'badge-low',medium:'badge-med',high:'badge-high'};return '<span class="badge '+(Object.prototype.hasOwnProperty.call(m,s)?m[s]:'badge-low')+'">'+esc(s||'info')+'</span>'}
function statusBadge(s){var m={open:'badge-high',processed:'badge-low',dismissed:'badge-inactive'};return '<span class="badge '+(Object.prototype.hasOwnProperty.call(m,s)?m[s]:'badge-low')+'">'+esc(s||'open')+'</span>'}

function govLoadReg(){
  if(window.govLoadSourceCandidates) window.govLoadSourceCandidates();
  var st = document.getElementById('regStatusFilter') ? document.getElementById('regStatusFilter').value : '';
  apiFetch('/governance/api/regulatory-updates'+(st?'?status='+encodeURIComponent(st):'')).then(rows=>{
    govRegList = rows;
    var tbody = document.getElementById('regTBody');
    if(!rows.length){tbody.innerHTML='<tr><td colspan="7" data-s="sa1e3045">No regulatory updates yet.</td></tr>'; return;}
    tbody.innerHTML = rows.map(r=>{
      var actions = CAN_MANAGE ? (
        '<button class="gov-btn ghost small" data-gov-action="edit-reg" data-id="'+govId(r.id)+'">Edit</button> '+
        (r.status==='open' ? '<button class="gov-btn ghost small" data-gov-action="dismiss-reg" data-id="'+govId(r.id)+'">Dismiss</button> ' : '')+
        (r.ai_summary ? '<button class="gov-btn ghost small" data-gov-action="review-reg" data-id="'+govId(r.id)+'">Review AI draft</button> ' : '')+
        '<button class="gov-btn ghost small danger" data-gov-action="delete-reg" data-id="'+govId(r.id)+'">Delete</button>'
      ) : '';
      var aiHint = r.ai_summary && r.ai_review_state==='approved' ? ' title="'+esc(r.ai_summary)+'"' : '';
      var aiState = r.ai_review_state==='approved' ? 'Reviewed AI summary' :
        r.ai_review_state==='rejected' ? 'AI draft rejected' :
        r.ai_review_state==='pending' ? 'AI draft awaiting human review' : '';
      var sourceUrl=govSafeSourceUrl(r.source_url);
      return '<tr>'
        + '<td><strong'+aiHint+'>'+esc(r.title)+'</strong>'+(aiState?'<br><span data-s="s1fd8c81">'+aiState+'</span>':'')+(sourceUrl?'<br><a href="'+esc(sourceUrl)+'" target="_blank" rel="noopener noreferrer" data-s="s53d0ffa">Source</a>':'')+'</td>'
        + '<td>'+esc(r.framework_name)+'</td>'
        + '<td>'+sevBadge(r.severity)+'</td>'
        + '<td>'+(r.effective_date?esc(String(r.effective_date).substring(0,10)):'–')+'</td>'
        + '<td>'+statusBadge(r.status)+'</td>'
        + '<td>'+(r.matched_count!=null?esc(r.matched_count):'–')+'</td>'
        + '<td class="actions">'+actions+'</td>'
      + '</tr>';
    }).join('');
  });
  if(!govRegFwNames.length){
    apiFetch('/governance/api/regulatory-frameworks').then(names=>{govRegFwNames=names;}).catch(()=>{});
  }
}

function govReviewRegAi(id){
  var row = govRegList.find(r=>r.id===id);
  if(!row || !row.ai_summary || !CAN_MANAGE) return;
  document.getElementById('govModal').innerHTML =
    '<div class="modal-overlay"><div class="modal-box">'+
      '<button class="modal-close" data-gov-action="close-modal">x</button>'+
      '<div class="modal-title">Review AI draft</div>'+
      '<p data-s="s7fc448e">Check the cited source and affected controls. This draft does not decide legal applicability.</p>'+
      '<div data-s="sc112876">'+esc(row.ai_summary)+'</div>'+
      '<div class="form-group" data-s="s56f4356"><label>Review reason</label><textarea id="reg_ai_reason" maxlength="500" rows="3"></textarea></div>'+
      '<div class="modal-actions"><button class="gov-btn ghost" data-gov-action="close-modal">Cancel</button>'+
        '<button class="gov-btn ghost" data-gov-action="decide-reg" data-id="'+govId(id)+'" data-decision="rejected">Reject</button>'+
        '<button class="gov-btn" data-gov-action="decide-reg" data-id="'+govId(id)+'" data-decision="approved">Approve draft</button></div>'+
    '</div></div>';
}

function govDecideRegAi(id,decision){
  var reason = document.getElementById('reg_ai_reason').value.trim();
  if(reason.length<10){alert('Record a review reason of at least 10 characters.');return;}
  apiFetch('/governance/api/regulatory-updates/'+id+'/ai-review',
    {method:'POST',body:JSON.stringify({decision:decision,reason:reason})})
    .then(()=>{govCloseModal();govLoadReg();})
    .catch(err=>alert('Review could not be recorded: '+err.message));
}

function govEditReg(id){var r=govRegList.find(x=>x.id===id); if(r) govOpenRegModal(r);}

function govOpenRegModal(row){
  var isEdit = !!row;
  var fwDl = govRegFwNames.map(n=>'<option value="'+esc(n)+'">').join('');
  document.getElementById('govModal').innerHTML =
    '<div class="modal-overlay" data-gov-backdrop="true">'
    + '<div class="modal-box">'
      + '<button class="modal-close" data-gov-action="close-modal">x</button>'
      + '<div class="modal-title">'+(isEdit?'Edit':'New')+' Regulatory Update</div>'
      + '<datalist id="fwDl">'+fwDl+'</datalist>'
      + '<div class="form-row">'
        + '<div class="form-group"><label>Framework *</label><input id="reg_fw" list="fwDl" value="'+esc(row?row.framework_name:'')+'"></div>'
        + '<div class="form-group"><label>Severity</label><select id="reg_sev"><option value="info"'+((!row||row.severity==='info')?' selected':'')+'>Info</option><option value="medium"'+(row&&row.severity==='medium'?' selected':'')+'>Medium</option><option value="high"'+(row&&row.severity==='high'?' selected':'')+'>High</option></select></div>'
      + '</div>'
      + '<div class="form-group"><label>Title *</label><input id="reg_title" value="'+esc(row?row.title:'')+'"></div>'
      + '<div class="form-group"><label>Summary</label><textarea id="reg_summary" rows="3">'+esc(row?row.summary||'':'')+'</textarea></div>'
      + '<div class="form-row">'
        + '<div class="form-group"><label>Effective Date</label><input type="date" id="reg_date" value="'+esc(row&&row.effective_date?String(row.effective_date).substring(0,10):'')+'"></div>'
        + '<div class="form-group"><label>Source URL</label><input id="reg_url" value="'+esc(row?row.source_url||'':'')+'"></div>'
      + '</div>'
      + '<div class="form-group"><label>Affected Control Refs</label><input id="reg_refs" placeholder="A.5.1, A.8.12" value="'+esc(row?row.affected_refs||'':'')+'"></div>'
      + '<div class="modal-actions">'
        + '<button class="gov-btn ghost" data-gov-action="close-modal">Cancel</button>'
        + '<button class="gov-btn" data-gov-action="save-reg" data-id="'+govId(isEdit?row.id:null)+'">Save</button>'
      + '</div>'
    + '</div></div>';
}

function govSaveReg(id){
  var fw = document.getElementById('reg_fw').value.trim();
  var title = document.getElementById('reg_title').value.trim();
  if(!fw){alert('Framework name is required'); return;}
  if(!title){alert('Title is required'); return;}
  var body = {
    framework_name: fw,
    title: title,
    summary: document.getElementById('reg_summary').value.trim()||null,
    source_url: document.getElementById('reg_url').value.trim()||null,
    effective_date: document.getElementById('reg_date').value||null,
    affected_refs: document.getElementById('reg_refs').value.trim()||null,
    severity: document.getElementById('reg_sev').value,
  };
  apiFetch('/governance/api/regulatory-updates'+(id?'/'+id:''), {method:id?'PUT':'POST', body:JSON.stringify(body)})
    .then(()=>{govCloseModal(); govLoadReg(); govLoadSummary();})
    .catch(err=>alert('Save failed: '+err.message));
}

function govDismissReg(id){
  if(!confirm('Dismiss this regulatory update?')) return;
  apiFetch('/governance/api/regulatory-updates/'+id+'/dismiss', {method:'POST'})
    .then(()=>{govLoadReg(); govLoadSummary();})
    .catch(err=>alert(err.message));
}

function govDeleteReg(id){
  if(!confirm('Delete this regulatory update?')) return;
  apiFetch('/governance/api/regulatory-updates/'+id, {method:'DELETE'})
    .then(()=>{govLoadReg(); govLoadSummary();})
    .catch(err=>alert(err.message));
}

function govRunDriftCheck(){
  apiFetch('/governance/api/regulatory-updates/run-drift', {method:'POST'})
    .then(res=>{
      alert('Drift check complete: '+res.updates+' update(s) processed, '+res.tasks+' task(s) created.');
      govLoadReg(); govLoadSummary();
    })
    .catch(err=>alert('Drift check failed: '+err.message));
}

// ── Init ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function(){
  govLoadSummary();
  govLoadBus();  // Loads BU list once so all dropdowns are populated
  govLoadReg();
});
