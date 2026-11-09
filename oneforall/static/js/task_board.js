(function(){

// ── Constants ─────────────────────────────────────────────────────────────────
const CURRENT_USER_ID = Number(document.querySelector('.kanban-board').dataset.currentUserId);

const PRI_COLOR = {
  critical: 'var(--red)',
  high:     '#f97316',
  medium:   'var(--amber)',
  low:      'var(--green-status)',
};
const MOD_COLOR = {
  aria:     '#7c3aed',
  grid:     '#1a6b3a',
  bcm:      '#d97706',
  sentinel: '#0891b2',
  evidence: '#059669',
  ai_governance: '#334155',
  platform: '#64748b',
};
const MOD_LABEL = {
  aria:'ARIA', grid:'GRID', bcm:'BCM', sentinel:'Sentinel', evidence:'Evidence', platform:'Platform',
  ai_governance:'AI Governance',
};
const MOD_HREF = {
  aria:'/aria/', grid:'/grid/', bcm:'/bcm/', sentinel:'/sentinel/', evidence:'/evidence/', platform:'/',
  ai_governance:'/ai-governance/',
};

// ── State ─────────────────────────────────────────────────────────────────────
let allTasks    = [];
let usersList   = [];
let filterMine  = false;
let filterModule = '';
let filterPri   = '';
let filterSearch = '';
let currentTaskId = null;
let isDragging  = false;

// ── Helpers ───────────────────────────────────────────────────────────────────
function esc(s){ const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

function today(){ return new Date().toISOString().slice(0,10); }

function fmtDate(ds){
  if(!ds) return null;
  const d = new Date(ds.length===10 ? ds+'T00:00:00' : ds);
  if(isNaN(d)) return ds;
  return d.toLocaleDateString('en-GB',{day:'numeric',month:'short'});
}

function isOverdue(due, status){
  return due && due < today() && status !== 'done' && status !== 'cancelled';
}

function initials(name){
  if(!name) return '?';
  return name.trim().split(/\s+/).map(w=>w[0]).slice(0,2).join('').toUpperCase();
}

function avatarColor(name){
  if(!name) return 'var(--accent)';
  const colors = ['#7c3aed','#0891b2','#059669','#d97706','#dc2626','#2563eb'];
  let h = 0;
  for(let i=0;i<name.length;i++) h = (h*31+name.charCodeAt(i)) & 0xffff;
  return colors[h % colors.length];
}

// ── Users ─────────────────────────────────────────────────────────────────────
async function loadUsers(){
  try{
    usersList = await ApiClient.request('/api/platform/users', { actionId: 'task_board.users.load' });
  }catch(e){
    if(typeof showToast==='function')showToast(e.detail || 'Failed to load users','error');
  }
  populateUserDropdowns();
}

function populateUserDropdowns(){
  ['ntAssignTo','ddAssignTo'].forEach(id=>{
    const el = document.getElementById(id);
    if(!el) return;
    const cur = el.value;
    while(el.options.length > 1) el.remove(1);
    usersList.forEach(u=>{
      const o = new Option(u.full_name || u.username, u.id);
      el.add(o);
    });
    el.value = cur;
  });
}

function usersSelectHtml(selectedId){
  const base = `<option value="">Unassigned</option>`;
  return base + usersList.map(u=>{
    const id=Number(u.id);
    return Number.isSafeInteger(id)&&id>0
      ? `<option value="${id}"${id==selectedId?' selected':''}>${esc(u.full_name||u.username)}</option>` : '';
  }).join('');
}

// ── Load & render ─────────────────────────────────────────────────────────────
async function loadTasks(){
  try{
    allTasks = await ApiClient.request('/api/tasks', { actionId: 'task_board.tasks.load' });
  }catch(e){
    if(typeof showToast==='function')showToast(e.detail || 'Failed to load tasks','error');
  }
  renderBoard();
  updateStats();
}

function getFiltered(){
  return allTasks.filter(t=>{
    if(filterMine && t.assigned_to != CURRENT_USER_ID) return false;
    if(filterModule && t.module !== filterModule) return false;
    if(filterPri && t.priority !== filterPri) return false;
    if(filterSearch){
      const hay = ((t.title||'')+' '+(t.description||'')+' '+(t.tags||'')).toLowerCase();
      if(!hay.includes(filterSearch)) return false;
    }
    return true;
  });
}

function renderBoard(){
  const filtered = getFiltered();
  const cols = {todo:[],in_progress:[],review:[],done:[]};
  filtered.forEach(t=>{ (cols[t.status]||cols.todo).push(t); });

  Object.entries(cols).forEach(([status,items])=>{
    const col   = document.getElementById('col-'+status);
    const count = document.getElementById('count-'+status);
    if(!col) return;
    if(count) count.textContent = items.length;
    if(!items.length){
      col.innerHTML = '<div data-s="s8dbb0d6">Drop tasks here</div>';
      return;
    }
    col.innerHTML = items.map(renderCard).join('');
  });
}

function renderCard(t){
  const id=Number(t.id);
  if(!Number.isSafeInteger(id)||id<=0) return '';
  const over    = isOverdue(t.due_date, t.status);
  const mc      = Object.hasOwn(MOD_COLOR,t.module) ? MOD_COLOR[t.module] : '#64748b';
  const ml      = MOD_LABEL[t.module] || t.module || '';
  const priCls  = 'p-'+(['low','medium','high','critical'].includes(t.priority)?t.priority:'medium');
  const init    = initials(t.assigned_name);
  const avColor = avatarColor(t.assigned_name);

  var sel = selectedTasks.has(id) ? ' selected' : '';
  return `<div class="task-card ${priCls}${sel}" data-id="${id}" role="button" tabindex="0" draggable="true">
    <input type="checkbox" class="tc-checkbox" aria-label="Select task" ${selectedTasks.has(id)?'checked':''} data-s="s9daaa60">
    <div class="tc-title">${esc(t.title)}</div>
    <div class="tc-meta">
      ${ml ? `<span class="tc-mod" data-sv="background:${mc}18;color:${mc}">${esc(ml)}</span>` : ''}
      ${t.due_date ? `<span class="tc-due${over?' overdue':''}">${over?'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg> ':''}${esc(fmtDate(t.due_date)||t.due_date)}</span>` : ''}
    </div>
    ${t.assigned_name ? `<div class="tc-assignee">
      <span class="tc-avatar" data-sv="background:${avColor}">${esc(init)}</span>
      ${esc(t.assigned_name)}
    </div>` : ''}
  </div>`;
}

// ── Stats ─────────────────────────────────────────────────────────────────────
async function updateStats(){
  try{
    const r = await fetch('/api/tasks/stats');
    if(!r.ok) return;
    const s = await r.json();
    const total = Object.values(s.by_status||{}).reduce((a,b)=>a+b,0);
    document.getElementById('stTotal').textContent  = total;
    document.getElementById('stPending').textContent = s.my_pending;
    document.getElementById('stOverdue').textContent = s.overdue;
  }catch(e){}
  // Critical + High from local data (no extra round trip)
  const openTasks = allTasks.filter(t=>t.status!=='done'&&t.status!=='cancelled');
  document.getElementById('stCritical').textContent = openTasks.filter(t=>t.priority==='critical').length;
  document.getElementById('stHigh').textContent     = openTasks.filter(t=>t.priority==='high').length;
}

// ── Filters ───────────────────────────────────────────────────────────────────
window.toggleMine = function(){
  filterMine = !filterMine;
  const btn = document.getElementById('mineBtn');
  btn.classList.toggle('active', filterMine);
  btn.setAttribute('aria-pressed', String(filterMine));
  renderBoard();
};

window.setPri = function(pri, chip){
  filterPri = pri;
  document.querySelectorAll('.tb-pri-chip').forEach(c=>c.classList.remove('active'));
  chip.classList.add('active');
  renderBoard();
};

window.applyFilters = function(){
  filterModule = document.getElementById('filterModule').value;
  filterSearch = (document.getElementById('filterSearch').value||'').trim().toLowerCase();
  renderBoard();
};

// ── Bulk Select Mode ─────────────────────────────────────────────────────────
var selectedTasks = new Set();

window.toggleSelectMode = function(){
  document.body.classList.toggle('tb-select-mode');
  var btn = document.getElementById('selectModeBtn');
  var active = document.body.classList.contains('tb-select-mode');
  btn.style.borderColor = active ? 'var(--accent)' : '';
  btn.style.color = active ? 'var(--accent)' : '';
  if(!active){
    selectedTasks.clear();
    updateBulkBar();
    renderBoard();
  }
};

window.toggleTaskSelect = function(id, cb){
  if(cb.checked) selectedTasks.add(id);
  else selectedTasks.delete(id);
  var card = cb.closest('.task-card');
  if(card) card.classList.toggle('selected', cb.checked);
  updateBulkBar();
};

function updateBulkBar(){
  var bar = document.getElementById('bulkBar');
  var count = selectedTasks.size;
  document.getElementById('bbCount').textContent = count + ' selected';
  bar.classList.toggle('visible', count > 0);
}

window.bulkDeselectAll = function(){
  selectedTasks.clear();
  updateBulkBar();
  renderBoard();
};

window.bulkSetField = async function(field, value){
  if(!value || selectedTasks.size === 0) return;
  try{
    var result = await ApiClient.request('/api/tasks/bulk', {
      method: 'PUT',
      body: {ids: Array.from(selectedTasks), updates: {[field]: value}},
      actionId: 'task_board.bulk_set_field',
    });
    if(typeof showToast === 'function') showToast('Updated ' + result.updated + ' tasks');
    selectedTasks.clear();
    updateBulkBar();
    await loadTasks();
  }catch(e){
    if(typeof showToast === 'function') showToast(e.detail || 'Bulk update failed', 'error');
  }
};

// ── AI Prioritize ────────────────────────────────────────────────────────────
window.aiPrioritize = async function(){
  var btn=document.getElementById('aiPriBtn');
  btn.disabled=true;btn.textContent='Analyzing...';
  try{
    var data=await ApiClient.request('/api/tasks/ai-prioritize', {method:'POST', actionId: 'task_board.ai_prioritize'});
    var ranked=data.ranked||[];
    if(!ranked.length){if(typeof showToast==='function')showToast('No prioritization suggestions','info');return;}
    showAiPriPanel(ranked);
  }catch(e){
    if(typeof showToast==='function')showToast(e.detail || 'AI prioritization failed','error');
  }finally{
    btn.disabled=false;btn.innerHTML='<span data-s="s433de30"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-sparkles></use></svg></span> AI Prioritize';
  }
};

function showAiPriPanel(ranked){
  var existing=document.getElementById('aiPriPanel');
  if(existing)existing.remove();
  var panel=document.createElement('div');
  panel.id='aiPriPanel';
  panel.className='card';
  panel.style.cssText='padding:16px 20px;margin-bottom:16px;border-left:3px solid var(--accent)';
  var html='<div data-s="sce63d6d" data-sd="flex">'+
    '<div data-s="s8a79397"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-sparkles></use></svg> AI Priority Suggestions</div>'+
    '<div data-s="s33fcd4c" data-sd="flex">'+
      '<button class="btn btn-primary" data-s="s4ccfc2c" data-ai-action="apply">Apply All</button>'+
      '<button class="btn btn-secondary" data-s="s4ccfc2c" data-ai-action="dismiss">Dismiss</button>'+
    '</div></div>';
  html+='<div data-s="sedd685d">';
  ranked.forEach(function(r,i){
    const taskId=Number(r.task_id);
    if(!Number.isSafeInteger(taskId)||taskId<=0) return;
    var task=allTasks.find(function(t){return t.id===r.task_id;});
    var priColor={'critical':'var(--red)','high':'#f97316','medium':'var(--amber)','low':'var(--green-status)'}[r.suggested_priority]||'var(--muted)';
    html+='<div data-s="s2d97f70" data-sd="flex" data-ai-task="'+taskId+'">'+
      '<span data-s="sbfc7338">#'+(Number.isSafeInteger(Number(r.rank))&&Number(r.rank)>0?Number(r.rank):i+1)+'</span>'+
      '<span data-s="s518f82c">'+esc(task?task.title:'Task #'+taskId)+'</span>'+
      '<span data-sv="padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;background:'+priColor+'18;color:'+priColor+'">'+esc(r.suggested_priority)+'</span>'+
      '<span data-s="s3e80330" title="'+esc(r.rationale||'')+'">'+esc(r.rationale||'')+'</span>'+
    '</div>';
  });
  html+='</div>';
  panel.innerHTML=html;
  window._aiRanked=ranked.filter(r=>Number.isSafeInteger(Number(r.task_id))&&Number(r.task_id)>0&&['low','medium','high','critical'].includes(r.suggested_priority));
  var board=document.querySelector('.kanban-board');
  board.parentNode.insertBefore(panel,board);
}

window.applyAiPriorities = async function(){
  var ranked=window._aiRanked||[];
  if(!ranked.length)return;
  var updates=ranked.filter(r=>Number.isSafeInteger(Number(r.task_id))&&Number(r.task_id)>0&&['low','medium','high','critical'].includes(r.suggested_priority)).map(function(r){return{id:Number(r.task_id),priority:r.suggested_priority};});
  try{
    for(var i=0;i<updates.length;i++){
      await ApiClient.request('/api/tasks/'+updates[i].id, {
        method: 'PUT', body: {priority:updates[i].priority}, actionId: 'task_board.apply_ai_priority',
      });
    }
    if(typeof showToast==='function')showToast('Applied AI priorities to '+updates.length+' tasks');
    document.getElementById('aiPriPanel').remove();
    await loadTasks();
  }catch(e){
    if(typeof showToast==='function')showToast(e.detail || 'Failed to apply priorities','error');
  }
};

// ── Task Detail Drawer ────────────────────────────────────────────────────────
window.onCardClick = function(e, taskId){
  if(isDragging) return;
  if(document.body.classList.contains('tb-select-mode')) return;
  openDrawer(taskId);
};

function openDrawer(taskId){
  const t = allTasks.find(x=>x.id===taskId);
  if(!t) return;
  currentTaskId = taskId;

  document.getElementById('tdHdrTitle').textContent = 'Task #'+t.id;

  const entityHtml = buildEntityLink(t);
  const creatorHtml = t.creator_name
    ? `Created by <strong>${esc(t.creator_name)}</strong>`
    : '';
  const createdAtHtml = t.created_at
    ? ` on ${esc(fmtDate(t.created_at.slice(0,10))||t.created_at.slice(0,10))}`
    : '';

  document.getElementById('tdBody').innerHTML = `
    <div class="td-field">
      <div class="td-label">Title</div>
      <input class="td-input" id="ddTitle" value="${esc(t.title)}">
    </div>
    <div class="td-field">
      <div class="td-label">Description</div>
      <textarea class="td-textarea" id="ddDesc" rows="4">${esc(t.description||'')}</textarea>
    </div>
    <div class="td-two">
      <div class="td-field">
        <div class="td-label">Status</div>
        <select class="td-select" id="ddStatus">
          ${['todo','in_progress','review','done','cancelled'].map(s=>
            `<option value="${s}"${t.status===s?' selected':''}>${s.replace('_',' ').replace(/\b\w/g,c=>c.toUpperCase())}</option>`
          ).join('')}
        </select>
      </div>
      <div class="td-field">
        <div class="td-label">Priority</div>
        <select class="td-select" id="ddPriority">
          ${['low','medium','high','critical'].map(p=>
            `<option value="${p}"${t.priority===p?' selected':''}>${p.charAt(0).toUpperCase()+p.slice(1)}</option>`
          ).join('')}
        </select>
      </div>
    </div>
    <div class="td-two">
      <div class="td-field">
        <div class="td-label">Module</div>
        <select class="td-select" id="ddModule">
          <option value="">None</option>
          ${Object.entries(MOD_LABEL).map(([v,l])=>
            `<option value="${v}"${t.module===v?' selected':''}>${l}</option>`
          ).join('')}
        </select>
      </div>
      <div class="td-field">
        <div class="td-label">Due Date</div>
        <input class="td-input" type="date" id="ddDue" value="${esc(t.due_date||'')}">
      </div>
    </div>
    <div class="td-field">
      <div class="td-label">Assign To</div>
      <select class="td-select" id="ddAssignTo">${usersSelectHtml(t.assigned_to)}</select>
    </div>
    ${t.tags ? `<div class="td-field"><div class="td-label">Tags</div>
      <div data-s="s303c838">${esc(t.tags)}</div></div>` : ''}
    ${entityHtml ? `<div class="td-field"><div class="td-label">Source</div>${entityHtml}</div>` : ''}
    <div class="td-meta-footer">
      ${creatorHtml}${createdAtHtml}
      ${t.updated_at && t.updated_at!==t.created_at ? `<span>Last updated ${esc(fmtDate(t.updated_at.slice(0,10))||t.updated_at.slice(0,10))}</span>` : ''}
    </div>
  `;

  document.getElementById('tdOverlay').classList.add('open');
  document.getElementById('taskDrawer').classList.add('open');
}

function buildEntityLink(t){
  if(!t.module || !t.entity_type || !t.entity_id) return '';
  const base  = MOD_HREF[t.module] || '/';
  const label = (MOD_LABEL[t.module]||t.module) + ' / ' +
                t.entity_type.replace(/_/g,' ') + ' #' + t.entity_id;
  return `<a class="td-source-link" href="${esc(base)}" target="_blank" rel="noopener noreferrer">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12">
      <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
      <polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
    </svg>
    ${esc(label)}
  </a>`;
}

window.closeDrawer = function(){
  document.getElementById('tdOverlay').classList.remove('open');
  document.getElementById('taskDrawer').classList.remove('open');
  currentTaskId = null;
};

window.saveDrawer = async function(){
  if(!currentTaskId) return;
  const body = {
    title:       document.getElementById('ddTitle').value,
    description: document.getElementById('ddDesc').value,
    module:      document.getElementById('ddModule').value,
    priority:    document.getElementById('ddPriority').value,
    status:      document.getElementById('ddStatus').value,
    due_date:    document.getElementById('ddDue').value,
    assigned_to: document.getElementById('ddAssignTo').value || null,
  };
  try{
    await ApiClient.request('/api/tasks/'+currentTaskId, {
      method: 'PUT', body: body, actionId: 'task_board.task.save',
    });
    showToast('Task saved','success');
    closeDrawer();
    await loadTasks();
  }catch(e){ showToast(e.detail || 'Save failed','error'); }
};

window.confirmDeleteTask = async function(){
  if(!currentTaskId) return;
  if(!confirm('Delete this task? This cannot be undone.')) return;
  try{
    await ApiClient.request('/api/tasks/'+currentTaskId, { method: 'DELETE', actionId: 'task_board.task.delete' });
    showToast('Task deleted','success');
    allTasks = allTasks.filter(t=>t.id!==currentTaskId);
    closeDrawer();
    renderBoard();
    updateStats();
  }catch(e){ showToast(e.detail || 'Delete failed','error'); }
};

// ── New Task Modal ────────────────────────────────────────────────────────────
window.openNewTaskModal = function(){
  ModalManager.open('newTaskModal');
};

window.submitNewTask = async function(e){
  e.preventDefault();
  const body = {
    title:       document.getElementById('ntTitle').value,
    description: document.getElementById('ntDesc').value,
    module:      document.getElementById('ntModule').value,
    priority:    document.getElementById('ntPriority').value,
    due_date:    document.getElementById('ntDue').value,
    assigned_to: document.getElementById('ntAssignTo').value || null,
  };
  try{
    await ApiClient.request('/api/tasks', { method: 'POST', body: body, actionId: 'task_board.task.create' });
    ModalManager.close('newTaskModal');
    document.getElementById('taskForm').reset();
    showToast('Task created','success');
    await loadTasks();
  }catch(e){ showToast(e.detail || 'Failed to create task','error'); }
};

// ── Drag and Drop ─────────────────────────────────────────────────────────────
let draggedId = null;

window.onDragStart = function(e, id){
  isDragging = true;
  draggedId  = id;
  e.dataTransfer.setData('text/plain', String(id));
  e.dataTransfer.effectAllowed = 'move';
  requestAnimationFrame(()=>{
    const el = document.querySelector('.task-card[data-id="'+id+'"]');
    if(el) el.classList.add('dragging');
  });
};

window.onDragOver = function(e){
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  e.currentTarget.classList.add('drag-over');
};

window.onDragLeave = function(e){
  if(!e.currentTarget.contains(e.relatedTarget)){
    e.currentTarget.classList.remove('drag-over');
  }
};

window.onDrop = async function(e, status){
  e.preventDefault();
  e.currentTarget.classList.remove('drag-over');
  const id = Number(e.dataTransfer.getData('text/plain')||draggedId);
  draggedId = null;
  if(!Number.isSafeInteger(id)||id<=0||!['todo','in_progress','review','done'].includes(status)) return;

  // Optimistic local update
  const task = allTasks.find(t=>t.id===id);
  if(task) task.status = status;
  renderBoard();
  updateStats();

  try{
    // PLAN-36 T06 (findings.md F08): raw fetch() doesn't reject on a
    // non-2xx status, so a rejected status transition (invalid state,
    // permission denied) previously left the optimistic UI update in place
    // as if it had succeeded, with nothing to catch and revert it.
    // ApiClient.request throws for that case too, not just a network error.
    await ApiClient.request('/api/tasks/'+id, { method: 'PUT', body: {status}, actionId: 'task_board.task.move' });
  }catch(err){
    showToast(err.detail || 'Failed to move task','error');
    await loadTasks(); // revert on error
  }
};

document.addEventListener('dragend',()=>{
  document.querySelectorAll('.task-card.dragging').forEach(el=>el.classList.remove('dragging'));
  document.querySelectorAll('.kanban-cards.drag-over').forEach(el=>el.classList.remove('drag-over'));
  draggedId = null;
  // Reset isDragging after click events have a chance to fire
  setTimeout(()=>{ isDragging = false; }, 50);
});

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async ()=>{
  document.getElementById('aiPriBtn').addEventListener('click', aiPrioritize);
  document.getElementById('selectModeBtn').addEventListener('click', toggleSelectMode);
  document.getElementById('tbNewTask').addEventListener('click', openNewTaskModal);
  document.getElementById('mineBtn').addEventListener('click', toggleMine);
  document.getElementById('filterModule').addEventListener('change', applyFilters);
  document.getElementById('filterSearch').addEventListener('input', applyFilters);
  document.querySelectorAll('.tb-pri-chip').forEach(chip=>{
    chip.addEventListener('click', ()=>setPri(chip.dataset.pri,chip));
  });
  document.getElementById('bbStatus').addEventListener('change', event=>{
    bulkSetField('status',event.currentTarget.value);
    event.currentTarget.selectedIndex=0;
  });
  document.getElementById('bbPriority').addEventListener('change', event=>{
    bulkSetField('priority',event.currentTarget.value);
    event.currentTarget.selectedIndex=0;
  });
  document.getElementById('tbDeselectAll').addEventListener('click', bulkDeselectAll);
  document.getElementById('tbCloseNewTask').addEventListener('click', ()=>ModalManager.close('newTaskModal'));
  document.getElementById('taskForm').addEventListener('submit', submitNewTask);
  document.getElementById('tdOverlay').addEventListener('click', closeDrawer);
  document.getElementById('tbCloseDrawer').addEventListener('click', closeDrawer);
  document.getElementById('tbSaveDrawer').addEventListener('click', saveDrawer);
  document.getElementById('tbDeleteTask').addEventListener('click', confirmDeleteTask);
  document.querySelectorAll('.kanban-cards').forEach(col=>{
    col.addEventListener('dragover', onDragOver);
    col.addEventListener('dragleave', onDragLeave);
    col.addEventListener('drop', event=>onDrop(event,col.dataset.status));
    col.addEventListener('dragstart', event=>{
      const card=event.target.closest('.task-card[data-id]');
      const id=Number(card?.dataset.id);
      if(card && Number.isSafeInteger(id) && id>0) onDragStart(event,id);
    });
    col.addEventListener('click', event=>{
      if(event.target.closest('.tc-checkbox')) return;
      const card=event.target.closest('.task-card[data-id]');
      const id=Number(card?.dataset.id);
      if(card && Number.isSafeInteger(id) && id>0) onCardClick(event,id);
    });
    col.addEventListener('change', event=>{
      if(!event.target.matches('.tc-checkbox')) return;
      const id=Number(event.target.closest('.task-card')?.dataset.id);
      if(Number.isSafeInteger(id) && id>0) toggleTaskSelect(id,event.target);
    });
    col.addEventListener('keydown', event=>{
      if(event.key!=='Enter' && event.key!==' ') return;
      const card=event.target.closest('.task-card[data-id]');
      if(!card || event.target!==card) return;
      const id=Number(card.dataset.id);
      if(!Number.isSafeInteger(id)||id<=0) return;
      event.preventDefault();
      onCardClick(event,id);
    });
  });
  document.querySelector('.kanban-board').parentNode.addEventListener('click', event=>{
    const action=event.target.closest('[data-ai-action]');
    if(!action || !document.getElementById('aiPriPanel')?.contains(action)) return;
    if(action.dataset.aiAction==='apply') applyAiPriorities();
    else if(action.dataset.aiAction==='dismiss') document.getElementById('aiPriPanel').remove();
  });
  await loadUsers();   // populate assignee dropdowns
  await loadTasks();   // load tasks + render board
  const url = new URL(window.location.href);
  const openId = url.searchParams.get('open');
  if(openId === null) return;
  url.searchParams.delete('open');
  window.history.replaceState({}, '', url.pathname + url.search + url.hash);
  if(!/^[1-9]\d*$/.test(openId)) return;
  const taskId = Number(openId);
  if(!Number.isSafeInteger(taskId)) return;
  try{
    let task = allTasks.find(t => t.id === taskId);
    if(!task){
      task = await ApiClient.request('/api/tasks/' + taskId, { actionId: 'task_board.task.open' });
      allTasks.push(task);
    }
    openDrawer(taskId);
  }catch(e){
    if(typeof showToast === 'function') showToast(e.detail || 'Task unavailable', 'error');
  }
});

// Keyboard: Escape closes drawer
document.addEventListener('keydown', e=>{
  if(e.key==='Escape') closeDrawer();
});

})();
