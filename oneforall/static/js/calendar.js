(function(){
'use strict';

/* ── Constants ────────────────────────────────────────────────────────────── */

const TYPE_COLOR = {
  audit:    '#1a6b3a',
  review:   '#7c3aed',
  training: '#6366f1',
  exercise: '#f97316',
  deadline: '#dc2626',
  meeting:  '#2563eb',
  other:    '#64748b',
};
const TYPE_LABEL = {
  audit:'Audit', review:'Review', training:'Training',
  exercise:'Exercise', deadline:'Deadline', meeting:'Meeting', other:'Other',
};
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const MOD_COLOR = {aria:'#7c3aed',grid:'#1a6b3a',bcm:'#d97706',sentinel:'#0891b2'};

/* ── State ────────────────────────────────────────────────────────────────── */
let currentYear, currentMonth;
let allEvents      = [];   // events in current month view
let upcomingEvents = [];   // events in next 30 days (sidebar)
let currentView    = 'month';
let currentEventId = null;
let usersList      = [];

/* ── Helpers ──────────────────────────────────────────────────────────────── */
function esc(s){ const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

function today(){ return new Date().toISOString().slice(0,10); }

function fmtDate(ds){
  if(!ds) return '—';
  const d = new Date(ds.length===10?ds+'T00:00:00':ds.replace(' ','T'));
  if(isNaN(d.getTime())) return ds;
  return d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
}

function shortDate(ds){
  if(!ds) return '';
  const d = new Date(ds+'T00:00:00');
  return d.toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short'});
}

function addDays(ds, n){
  const d = new Date(ds+'T00:00:00');
  d.setDate(d.getDate()+n);
  return d.toISOString().slice(0,10);
}

function weekStart(){
  const d = new Date();
  const dow = (d.getDay()+6)%7;
  d.setDate(d.getDate()-dow);
  return d.toISOString().slice(0,10);
}

function weekEnd(){
  return addDays(weekStart(), 6);
}

/* ── Users ────────────────────────────────────────────────────────────────── */
async function loadUsers(){
  try{
    const r = await fetch('/api/platform/users');
    if(r.ok) usersList = await r.json();
    populateUserSelect();
  }catch(e){}
}

function populateUserSelect(){
  const sel = document.getElementById('efAssignTo');
  while(sel.options.length>1) sel.remove(1);
  usersList.forEach(u=>{
    sel.add(new Option(u.full_name||u.username, u.id));
  });
}

/* ── Navigation ───────────────────────────────────────────────────────────── */
window.prevMonth = function(){
  currentMonth--;
  if(currentMonth<0){currentMonth=11;currentYear--;}
  reload();
};
window.nextMonth = function(){
  currentMonth++;
  if(currentMonth>11){currentMonth=0;currentYear++;}
  reload();
};
window.goToday = function(){
  const n=new Date();
  currentYear=n.getFullYear();
  currentMonth=n.getMonth();
  reload();
};

function reload(){ loadMonthEvents(); }

/* ── View toggle ──────────────────────────────────────────────────────────── */
window.setView = function(view, btn){
  currentView = view;
  document.querySelectorAll('.cal-view-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('panelMonth').style.display = view==='month' ? '' : 'none';
  document.getElementById('panelList').style.display  = view==='list'  ? '' : 'none';
  renderCurrentView();
};

function renderCurrentView(){
  if(currentView==='month') renderMonth();
  else renderList();
}

/* ── Filters ──────────────────────────────────────────────────────────────── */
window.applyFilters = function(){
  loadMonthEvents();
};

function getFiltered(events){
  const type   = document.getElementById('filterType').value;
  const module = document.getElementById('filterModule').value;
  return events.filter(e=>{
    if(type   && e.event_type!==type)   return false;
    if(module && e.module!==module)     return false;
    return true;
  });
}

/* ── Load events ──────────────────────────────────────────────────────────── */
async function loadMonthEvents(){
  const start = `${currentYear}-${String(currentMonth+1).padStart(2,'0')}-01`;
  // Fetch slightly wider window to capture multi-day events that start before month end
  const lastDay = new Date(currentYear, currentMonth+1, 0).getDate();
  const end = `${currentYear}-${String(currentMonth+1).padStart(2,'0')}-${String(lastDay).padStart(2,'0')}`;

  document.getElementById('monthLabel').textContent = MONTHS[currentMonth]+' '+currentYear;

  try{
    const r = await fetch(`/api/calendar/events?start=${start}&end=${end}`);
    if(!r.ok) throw new Error('fetch failed');
    allEvents = await r.json();
  }catch(e){
    allEvents = [];
    if(typeof showToast==='function') showToast('Failed to load calendar events','error');
  }

  updateStats();
  renderCurrentView();
}

async function loadUpcomingEvents(){
  const start = today();
  const end   = addDays(start, 30);
  try{
    const r = await fetch(`/api/calendar/events?start=${start}&end=${end}`);
    if(!r.ok) throw new Error();
    upcomingEvents = await r.json();
  }catch(e){
    upcomingEvents = [];
  }
  renderUpcoming();
}

/* ── Stats ────────────────────────────────────────────────────────────────── */
function updateStats(){
  const t = today();
  const ws = weekStart();
  const we = weekEnd();
  const filtered = getFiltered(allEvents);

  document.getElementById('stTotal').textContent     = filtered.length;
  document.getElementById('stDeadlines').textContent = filtered.filter(e=>e.event_type==='deadline').length;
  document.getElementById('stWeek').textContent      = filtered.filter(e=>e.start_date>=ws&&e.start_date<=we).length;
  document.getElementById('stOverdue').textContent   = filtered.filter(e=>{
    const end = e.end_date||e.start_date;
    return end<t && e.status==='scheduled';
  }).length;
}

/* ── Month render ─────────────────────────────────────────────────────────── */
function renderMonth(){
  const t = today();
  const ws = weekStart();
  const we = weekEnd();
  const firstDay = new Date(currentYear, currentMonth, 1);
  const lastDay  = new Date(currentYear, currentMonth+1, 0);
  const startDow = (firstDay.getDay()+6)%7;  // 0=Mon
  const totalDays = lastDay.getDate();
  const filtered = getFiltered(allEvents);

  let cells = '';

  // Padding cells (previous month)
  for(let i=0;i<startDow;i++){
    cells += '<div class="cal-day other-month"></div>';
  }

  // Day cells
  for(let d=1;d<=totalDays;d++){
    const ds = `${currentYear}-${String(currentMonth+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    const dow = (new Date(ds+'T00:00:00').getDay()+6)%7;
    const isWeekend = dow>=5;
    const isToday   = ds===t;
    const isPast    = ds<t;

    // Events spanning this day
    const dayEvents = filtered.filter(e=>{
      const s = e.start_date;
      const en = e.end_date||e.start_date;
      return ds>=s && ds<=en;
    });

    let cls = 'cal-day';
    if(isWeekend) cls+=' weekend';
    if(isToday)   cls+=' today';
    if(isPast)    cls+=' past';

    const pillsHtml = dayEvents.slice(0,3).map(e=>{
      const color  = TYPE_COLOR[e.event_type]||'#64748b';
      const isStart = e.start_date===ds;
      const isEnd   = (e.end_date||e.start_date)===ds;
      const spanCls = (!isStart&&!isEnd)?'span-mid':isStart&&!isEnd?'span-start':!isStart&&isEnd?'span-end':'';
      const id = Number(e.id);
      if (!Number.isSafeInteger(id) || id <= 0) return '';
      return `<div class="cal-pill ${spanCls}" role="button" tabindex="0" data-event-id="${id}"
                   style="background:${color}22;color:${color}"
                   title="${esc(e.title)}">${esc(e.title)}</div>`;
    }).join('');

    const moreHtml = dayEvents.length>3
      ? `<div class="cal-more">+${dayEvents.length-3} more</div>` : '';

    cells += `<div class="${cls}" role="button" tabindex="0" data-date="${ds}">
      <div class="cal-day-num">${d}</div>
      ${pillsHtml}${moreHtml}
    </div>`;
  }

  // Trailing padding
  const totalCells = startDow + totalDays;
  const trailing = (7 - (totalCells%7))%7;
  for(let i=0;i<trailing;i++){
    cells += '<div class="cal-day other-month"></div>';
  }

  document.getElementById('calDays').innerHTML = cells;
}

/* ── List render ──────────────────────────────────────────────────────────── */
function renderList(){
  const filtered = getFiltered(allEvents);
  const el = document.getElementById('evList');
  if(!filtered.length){
    el.innerHTML = '<div style="padding:40px;text-align:center;color:var(--muted)">No events this month</div>';
    return;
  }

  // Group by date
  const grouped = {};
  filtered.forEach(e=>{
    if(!grouped[e.start_date]) grouped[e.start_date]=[];
    grouped[e.start_date].push(e);
  });

  const t = today();
  let html = '';
  Object.keys(grouped).sort().forEach(date=>{
    const isPast = date<t;
    html += `<div class="ev-list-date" style="${isPast?'opacity:.55':''}">${shortDate(date)}</div>`;
    grouped[date].forEach(e=>{
      const color = TYPE_COLOR[e.event_type]||'#64748b';
      const statusColor = e.status==='completed'?'var(--green-status)':e.status==='cancelled'?'var(--muted)':'';
      const id = Number(e.id);
      if (!Number.isSafeInteger(id) || id <= 0) return;
      html += `<div class="ev-list-row" role="button" tabindex="0" data-event-id="${id}" style="${isPast?'opacity:.6':''}">
        <div class="ev-list-dot" style="background:${color}"></div>
        <div style="flex:1;min-width:0">
          <div class="ev-list-title" style="${statusColor?'color:'+statusColor:''}${e.status==='completed'?';text-decoration:line-through':''}">${esc(e.title)}</div>
          <div class="ev-list-meta">${esc(TYPE_LABEL[e.event_type]||e.event_type)}${e.module?' · '+esc(e.module.toUpperCase()):''}${e.assigned_name?' · '+esc(e.assigned_name):''}</div>
        </div>
        ${e.end_date&&e.end_date!==e.start_date?`<div class="ev-list-meta" style="flex-shrink:0">→ ${esc(fmtDate(e.end_date))}</div>`:''}
        <span class="ev-list-badge" style="background:${color}18;color:${color};flex-shrink:0">${esc(TYPE_LABEL[e.event_type]||e.event_type)}</span>
      </div>`;
    });
  });

  el.innerHTML = html;
}

/* ── Upcoming sidebar ─────────────────────────────────────────────────────── */
function renderUpcoming(){
  const el = document.getElementById('upcomingList');
  const filtered = getFiltered(upcomingEvents);
  if(!filtered.length){
    el.innerHTML = '<div class="cal-sidebar-empty">No upcoming events in the next 30 days</div>';
    return;
  }

  // Group by date
  const grouped = {};
  filtered.forEach(e=>{
    if(!grouped[e.start_date]) grouped[e.start_date]=[];
    grouped[e.start_date].push(e);
  });

  const t = today();
  let html = '';
  Object.keys(grouped).sort().forEach(date=>{
    const label = date===t ? 'Today' : date===addDays(t,1) ? 'Tomorrow' : shortDate(date);
    html += `<div class="upcoming-date-hdr">${esc(label)}</div>`;
    grouped[date].forEach(e=>{
      const color = TYPE_COLOR[e.event_type]||'#64748b';
      const id = Number(e.id);
      if (!Number.isSafeInteger(id) || id <= 0) return;
      html += `<div class="upcoming-row" role="button" tabindex="0" data-event-id="${id}">
        <div class="upcoming-bar" style="background:${color}"></div>
        <div>
          <div class="upcoming-title">${esc(e.title)}</div>
          <div class="upcoming-meta">${esc(TYPE_LABEL[e.event_type]||'')}${e.module?' · '+esc(e.module.toUpperCase()):''}${e.assigned_name?' · '+esc(e.assigned_name):''}</div>
        </div>
      </div>`;
    });
  });

  el.innerHTML = html;
}

/* ── Event detail drawer ──────────────────────────────────────────────────── */
function openEventDrawer(id){
  const e = [...allEvents,...upcomingEvents].find(x=>x.id===id);
  if(!e) return;
  currentEventId = id;

  const color  = TYPE_COLOR[e.event_type]||'#64748b';
  const isOverdue = (e.end_date||e.start_date)<today() && e.status==='scheduled';

  document.getElementById('drawerHdrTitle').textContent = e.title;
  document.getElementById('drawerBody').innerHTML = `
    <div style="margin-bottom:16px">
      <span class="ev-type-badge" style="background:${color}18;color:${color}">${esc(TYPE_LABEL[e.event_type]||e.event_type)}</span>
      ${isOverdue?'<span class="ev-type-badge" style="background:rgba(220,38,38,.1);color:var(--red);margin-left:6px">Overdue</span>':''}
    </div>
    <div class="ev-field">
      <div class="ev-field-lbl">Date</div>
      <div class="ev-field-val">${esc(fmtDate(e.start_date))}${e.end_date&&e.end_date!==e.start_date?' → '+esc(fmtDate(e.end_date)):''}</div>
    </div>
    ${e.module?`<div class="ev-field">
      <div class="ev-field-lbl">Module</div>
      <div class="ev-field-val"><span style="color:${MOD_COLOR[e.module]||'var(--accent)'}">● </span>${esc(e.module.toUpperCase())}</div>
    </div>`:''}
    ${e.assigned_name?`<div class="ev-field">
      <div class="ev-field-lbl">Assigned To</div>
      <div class="ev-field-val">${esc(e.assigned_name)}</div>
    </div>`:''}
    <div class="ev-field">
      <div class="ev-field-lbl">Status</div>
      <div class="ev-field-val" style="text-transform:capitalize">${esc((e.status||'scheduled').replace('_',' '))}</div>
    </div>
    ${e.description?`<div class="ev-field">
      <div class="ev-field-lbl">Description</div>
      <div class="ev-field-val" style="white-space:pre-wrap;line-height:1.5">${esc(e.description)}</div>
    </div>`:''}
    ${e.entity_type?`<div class="ev-field">
      <div class="ev-field-lbl">Linked Entity</div>
      <div class="ev-field-val">${esc(e.entity_type.replace(/_/g,' '))}${e.entity_id?' #'+esc(e.entity_id):''}</div>
    </div>`:''}
    <div class="ev-field" style="padding-top:12px;border-top:1px solid var(--border)">
      <div class="ev-field-lbl">Created</div>
      <div class="ev-field-val" style="font-size:11px;color:var(--muted)">${esc(fmtDate((e.created_at||'').slice(0,10)))}</div>
    </div>
  `;

  document.getElementById('evOverlay').classList.add('open');
  document.getElementById('evDrawer').classList.add('open');
}

window.closeDrawer = function(){
  document.getElementById('evOverlay').classList.remove('open');
  document.getElementById('evDrawer').classList.remove('open');
  currentEventId = null;
};

/* ── Edit from drawer ─────────────────────────────────────────────────────── */
window.openEditModal = function(){
  const e = [...allEvents,...upcomingEvents].find(x=>x.id===currentEventId);
  if(!e) return;
  closeDrawer();

  document.getElementById('modalTitle').textContent = 'Edit Event';
  document.getElementById('efSubmitBtn').textContent = 'Save Changes';
  document.getElementById('efId').value     = e.id;
  document.getElementById('efTitle').value  = e.title||'';
  document.getElementById('efType').value   = e.event_type||'other';
  document.getElementById('efModule').value = e.module||'';
  document.getElementById('efStart').value  = e.start_date||'';
  document.getElementById('efEnd').value    = e.end_date||'';
  document.getElementById('efStatus').value = e.status||'scheduled';
  document.getElementById('efDesc').value   = e.description||'';
  // Assignee
  populateUserSelect();
  document.getElementById('efAssignTo').value = e.assigned_to||'';
  ModalManager.open('eventModal');
};

/* ── New event modal ──────────────────────────────────────────────────────── */
window.openNewEventModal = function(dateStr){
  document.getElementById('modalTitle').textContent = 'New Event';
  document.getElementById('efSubmitBtn').textContent = 'Create Event';
  document.getElementById('efId').value     = '';
  document.getElementById('efTitle').value  = '';
  document.getElementById('efType').value   = 'other';
  document.getElementById('efModule').value = '';
  document.getElementById('efStart').value  = dateStr||today();
  document.getElementById('efEnd').value    = '';
  document.getElementById('efStatus').value = 'scheduled';
  document.getElementById('efDesc').value   = '';
  populateUserSelect();
  document.getElementById('efAssignTo').value = '';
  ModalManager.open('eventModal');
};

/* ── Submit (create or edit) ──────────────────────────────────────────────── */
window.submitEventForm = async function(ev){
  ev.preventDefault();
  const id = document.getElementById('efId').value;
  const body = {
    title:       document.getElementById('efTitle').value,
    event_type:  document.getElementById('efType').value,
    module:      document.getElementById('efModule').value,
    start_date:  document.getElementById('efStart').value,
    end_date:    document.getElementById('efEnd').value||null,
    status:      document.getElementById('efStatus').value,
    description: document.getElementById('efDesc').value,
    assigned_to: document.getElementById('efAssignTo').value||null,
  };

  const url    = id ? `/api/calendar/events/${id}` : '/api/calendar/events';
  const method = id ? 'PUT' : 'POST';

  try{
    const r = await fetch(url,{
      method,
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body),
    });
    if(!r.ok) throw new Error();
    ModalManager.close('eventModal');
    document.getElementById('eventForm').reset();
    if(typeof showToast==='function') showToast(id?'Event updated':'Event created','success');
    loadMonthEvents();
    loadUpcomingEvents();
  }catch(e){
    if(typeof showToast==='function') showToast('Failed to save event','error');
  }
};

/* ── Delete event ─────────────────────────────────────────────────────────── */
window.deleteCurrentEvent = async function(){
  if(!currentEventId) return;
  if(!confirm('Delete this event? This cannot be undone.')) return;
  try{
    const r = await fetch(`/api/calendar/events/${currentEventId}`,{method:'DELETE'});
    if(!r.ok) throw new Error();
    if(typeof showToast==='function') showToast('Event deleted','success');
    closeDrawer();
    loadMonthEvents();
    loadUpcomingEvents();
  }catch(e){
    if(typeof showToast==='function') showToast('Failed to delete event','error');
  }
};

/* ── Init ─────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function(){
  const n = new Date();
  currentYear  = n.getFullYear();
  currentMonth = n.getMonth();
  document.getElementById('monthLabel').textContent = MONTHS[currentMonth]+' '+currentYear;

  loadUsers();
  loadMonthEvents();
  loadUpcomingEvents();

  document.getElementById('filterType').addEventListener('change', applyFilters);
  document.getElementById('filterModule').addEventListener('change', applyFilters);
  document.getElementById('calPrevMonth').addEventListener('click', prevMonth);
  document.getElementById('calNextMonth').addEventListener('click', nextMonth);
  document.getElementById('calGoToday').addEventListener('click', goToday);
  document.getElementById('viewMonth').addEventListener('click', e=>setView('month', e.currentTarget));
  document.getElementById('viewList').addEventListener('click', e=>setView('list', e.currentTarget));
  document.getElementById('calAddEvent').addEventListener('click', ()=>openNewEventModal(null));
  document.getElementById('evOverlay').addEventListener('click', closeDrawer);
  document.getElementById('calCloseDrawer').addEventListener('click', closeDrawer);
  document.getElementById('calEditEvent').addEventListener('click', openEditModal);
  document.getElementById('calDeleteEvent').addEventListener('click', deleteCurrentEvent);
  document.getElementById('calCloseEventModal').addEventListener('click', ()=>ModalManager.close('eventModal'));
  document.getElementById('eventForm').addEventListener('submit', submitEventForm);
  const openCalendarItem = (event) => {
    const item = event.target.closest('[data-event-id], [data-date]');
    if (!item || !event.currentTarget.contains(item)) return;
    if (item.dataset.eventId) openEventDrawer(Number(item.dataset.eventId));
    else if (item.dataset.date) openNewEventModal(item.dataset.date);
  };
  for (const id of ['calDays', 'evList', 'upcomingList']) {
    const container = document.getElementById(id);
    container.addEventListener('click', openCalendarItem);
    container.addEventListener('keydown', event => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      const item = event.target.closest('[data-event-id], [data-date]');
      if (!item || !container.contains(item)) return;
      event.preventDefault();
      openCalendarItem(event);
    });
  }
});

// ESC closes drawer/modal
document.addEventListener('keydown', function(e){
  if(e.key==='Escape'){
    closeDrawer();
    ModalManager.close('eventModal');
  }
});

})();
