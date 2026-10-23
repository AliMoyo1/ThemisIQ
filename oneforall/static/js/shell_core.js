// ── Shell Utilities ──

document.getElementById('mobileNavToggle').addEventListener('click', toggleMobileNav);
document.getElementById('moduleSidebarToggle').addEventListener('click', toggleSidebar);
document.getElementById('notifBtn').addEventListener('click', toggleNotif);
document.getElementById('markAllReadBtn').addEventListener('click', markAllRead);
document.getElementById('reminderOpenBtn').addEventListener('click', function(){ openReminderModal(); });
document.getElementById('themeToggle').addEventListener('click', toggleTheme);

function toggleSidebar(){
  const sb = document.getElementById('moduleSidebar');
  sb.classList.toggle('collapsed');
  localStorage.setItem('sidebarCollapsed', sb.classList.contains('collapsed'));
}

function toggleMobileNav(){
  const icon = document.querySelector('.icon-sidebar');
  const mod  = document.getElementById('moduleSidebar');
  const open = !(icon && icon.classList.contains('open'));
  if (icon) icon.classList.toggle('open', open);
  if (mod)  mod.classList.toggle('open',  open);
  document.body.classList.toggle('drawer-open', open);
}

document.addEventListener('click', function(e){
  // Close mobile drawer when tapping the backdrop or a nav link inside it
  if (!document.body.classList.contains('drawer-open')) return;
  const hitToggle = e.target.closest('.mobile-nav-toggle');
  if (hitToggle) return;
  const hitDrawer = e.target.closest('.icon-sidebar, .module-sidebar');
  const hitLink = e.target.closest('a');
  if (!hitDrawer || hitLink) toggleMobileNav();
});

// Restore sidebar state
(function(){
  if(localStorage.getItem('sidebarCollapsed')==='true'){
    document.getElementById('moduleSidebar').classList.add('collapsed');
  }
})();

// ── Theme Toggle (Dark/Light Mode) ──
function toggleTheme(){
  const html = document.documentElement;
  const isDark = html.getAttribute('data-theme') === 'dark';
  const newTheme = isDark ? 'light' : 'dark';
  html.setAttribute('data-theme', newTheme);
  localStorage.setItem('ofa-theme', newTheme);
  updateThemeIcons(newTheme);
}
function updateThemeIcons(theme){
  const sun = document.getElementById('themeSun');
  const moon = document.getElementById('themeMoon');
  if(theme === 'dark'){ sun.style.display='block'; moon.style.display='none'; }
  else { sun.style.display='none'; moon.style.display='block'; }
}
// Restore theme on load
(function(){
  const saved = localStorage.getItem('ofa-theme') || 'light';
  if(saved === 'dark') document.documentElement.setAttribute('data-theme','dark');
  updateThemeIcons(saved);
})();

// ── Module Context Switching ──
// Dynamically sets data-module on <body> to switch accent colors.
// Called when clicking module icons in the icon sidebar.
// In the real app, navigation is via <a> links (full page loads),
// so this is primarily used to ensure accent colors update correctly
// on module pages that load dynamically or via fetch.
function switchModuleContext(mod){
  const validModules = ['platform','aria','grid','bcm','sentinel'];
  if(!validModules.includes(mod)) return;
  document.body.setAttribute('data-module', mod);
  // Update icon sidebar active state
  document.querySelectorAll('.icon-nav-item').forEach(function(el){
    const href = el.getAttribute('href') || '';
    const isTarget = (mod === 'platform' && href === '/') ||
                     (mod !== 'platform' && href.indexOf('/' + mod) === 0);
    if(isTarget){ el.classList.add('active'); }
    else { el.classList.remove('active'); }
  });
  // Persist module context for sub-pages that might not set it server-side
  try{ sessionStorage.setItem('ofa-module', mod); }catch(e){}
}

function esc(s){
  if(!s&&s!==0)return '';
  var d=document.createElement('div');
  d.textContent=String(s);
  // innerHTML escapes text nodes, but leaves quotes intact. Search and
  // notification links also use this helper inside quoted HTML attributes.
  return d.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function toggleNotif(){
  const p = document.getElementById('notifPanel');
  const isOpen = p.classList.toggle('show');
  document.getElementById('notifBtn').setAttribute('aria-expanded', String(isOpen));
  if(isOpen) loadNotifications();
}

async function loadNotifications(){
  try {
    const resp = await fetch('/api/notifications');
    const data = await resp.json();
    const dot = document.getElementById('notifDot');
    dot.style.display = data.unread_count > 0 ? 'block' : 'none';
    const list = document.getElementById('notifList');
    if(!data.notifications.length){
      list.innerHTML = '<div class="empty-state" style="padding:24px"><p>No notifications</p></div>';
      return;
    }
    list.innerHTML = data.notifications.slice(0,20).map(function(n) {
      var safeLink = safeHref(n.link, '');
      return '<div style="padding:10px 14px;border-bottom:1px solid var(--border-soft);cursor:pointer;background:'+(n.is_read?'transparent':'var(--surface2)')+'" data-nid="'+parseInt(n.id,10)+'" data-link="'+esc(safeLink)+'">' +
        '<div style="font-size:12.5px;font-weight:'+(n.is_read?'400':'600')+';color:var(--text);">'+esc(n.title)+'</div>' +
        '<div style="font-size:11px;color:var(--muted);margin-top:2px;">'+esc(n.message||'')+'</div>' +
        '<div style="font-size:10px;color:var(--muted);margin-top:4px;">'+esc(n.module||'')+' &middot; '+esc(timeAgo(n.created_at))+'</div>' +
      '</div>';
    }).join('');
    list.querySelectorAll('[data-nid]').forEach(function(el){
      el.addEventListener('click', function(){ handleNotifClick(parseInt(el.getAttribute('data-nid'),10), el.getAttribute('data-link')||''); });
    });
  } catch(e){}
}

async function handleNotifClick(nid, link){
  await fetch('/api/notifications/'+(parseInt(nid,10)||0)+'/read', {method:'POST'});
  if(link){
    try {
      var u = new URL(link, window.location.origin);
      if((u.protocol==='http:'||u.protocol==='https:') && u.origin===window.location.origin && u.pathname.startsWith('/')){
        var safePath = encodeURI(u.pathname || '/');
        var params = new URLSearchParams(u.search || '');
        var safeSearch = params.toString();
        safeSearch = safeSearch ? '?' + safeSearch : '';
        var safeHash = u.hash ? '#' + encodeURIComponent((u.hash || '').replace(/^#/, '')) : '';
        var targetUrl = new URL(safePath + safeSearch + safeHash, window.location.origin);
        if(targetUrl.origin===window.location.origin){
          window.location.assign(targetUrl.toString());
          return;
        }
      }
    } catch(e){}
  }
  loadNotifications();
}

async function markAllRead(){
  await fetch('/api/notifications/read-all', {method:'POST'});
  document.getElementById('notifDot').style.display='none';
  loadNotifications();
}

function timeAgo(ts){
  if(!ts) return '';
  const d=new Date(ts+'Z'); const now=new Date(); const s=Math.floor((now-d)/1000);
  if(s<60) return 'just now'; if(s<3600) return Math.floor(s/60)+'m ago';
  if(s<86400) return Math.floor(s/3600)+'h ago'; return Math.floor(s/86400)+'d ago';
}

function toggleUserMenu(){
  const d = document.getElementById('userDropdown');
  d.classList.toggle('show');
}

// Close dropdowns on outside click
document.addEventListener('click', function(e){
  if(!e.target.closest('.icon-sidebar-user')){
    document.getElementById('userDropdown').classList.remove('show');
  }
  if(!e.target.closest('#notifBtn') && !e.target.closest('#notifPanel')){
    document.getElementById('notifPanel').classList.remove('show');
  }
});

// Global search (Ctrl+K)
document.addEventListener('keydown', function(e){
  if((e.ctrlKey || e.metaKey) && e.key === 'k'){
    e.preventDefault();
    document.getElementById('globalSearch').focus();
  }
  if(e.key === 'Escape'){
    document.getElementById('searchResults').style.display='none';
    document.getElementById('globalSearch').blur();
    searchIndex = -1;
  }
  // Arrow-key navigation within search results dropdown
  var resultsEl = document.getElementById('searchResults');
  if(resultsEl.style.display === 'block'){
    var items = resultsEl.querySelectorAll('.search-result');
    if(e.key === 'ArrowDown'){
      e.preventDefault();
      searchIndex = Math.min(searchIndex + 1, items.length - 1);
      updateSearchActive(items, searchIndex);
    } else if(e.key === 'ArrowUp'){
      e.preventDefault();
      searchIndex = Math.max(searchIndex - 1, 0);
      updateSearchActive(items, searchIndex);
    } else if(e.key === 'Enter' && searchIndex >= 0 && searchIndex < items.length){
      e.preventDefault();
      var activeItem = items[searchIndex];
      if(activeItem && activeItem.href){
        window.location.href = activeItem.href;
      }
    }
  }
});

// A link the server gave, kept as it is when it is a path on this site. The earlier filter removed every character that
// was not a letter, digit or one of a few marks, which turned "?open=control:12" into "?open=control12".
function safeHref(link, fallback){
  var value = String(link || '');
  if(value.charAt(0) === '/' && value.charAt(1) !== '/' && value.indexOf('\\') < 0 && !/[\u0000-\u001f\u007f]/.test(value)){
    return value;
  }
  return fallback;
}

function updateSearchActive(items, idx){
  items.forEach(function(it, i){ it.classList.toggle('active', i === idx); });
  if(idx >= 0 && items[idx]){
    items[idx].scrollIntoView({block:'nearest'});
  }
}

let searchDebounce = null;
let searchIndex = -1;
document.getElementById('globalSearch').addEventListener('input', function(){
  clearTimeout(searchDebounce);
  searchIndex = -1;
  const q = this.value.trim();
  if(q.length < 2){ document.getElementById('searchResults').style.display='none'; return; }
  searchDebounce = setTimeout(()=>doGlobalSearch(q), 250);
});

async function doGlobalSearch(q){
  searchIndex = -1;
  const resp = await fetch('/api/search?q=' + encodeURIComponent(q));
  const data = await resp.json();
  const el = document.getElementById('searchResults');
  if(!data.results.length){
    el.innerHTML = '<div style="padding:16px;text-align:center;color:var(--muted);font-size:13px;">No results</div>';
  } else {
    var modColors = {aria:'#6c63ff',sentinel:'#10b981',grid:'#f59e0b',bcm:'#ef4444',platform:'#94a3b8'};
    el.innerHTML = data.results.map(function(r) {
      var safeLink = safeHref(r.link, '#');
      var facts = [r.status, r.date, r.business_unit].filter(Boolean).join(' \u00b7 ');
      var mod = (r.module||'').replace(/[^a-z]/g,'');
      return '<a href="'+esc(safeLink)+'" class="search-result" style="display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--border-soft);text-decoration:none;color:var(--text);">' +
        '<span style="width:8px;height:8px;border-radius:50%;background:'+(modColors[mod]||'var(--muted)')+';flex-shrink:0;"></span>' +
        '<div style="flex:1;min-width:0;">' +
          '<div style="font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'+esc(r.title)+'</div>' +
          '<div style="font-size:11px;color:var(--muted);">'+esc(r.module)+' &middot; '+esc(r.type)+(r.subtitle?' &middot; '+esc(r.subtitle):'')+'</div>' +
          (facts?'<div style="font-size:11px;color:var(--muted);">'+esc(facts)+'</div>':'') +
          (r.snippet?'<div style="font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'+esc(r.snippet)+'</div>':'') +
        '</div>' +
      '</a>';
    }).join('');
  }
  el.style.display = 'block';
}

// Hide search results on click outside
document.addEventListener('click', function(e){
  if(!e.target.closest('.search-wrap')){
    document.getElementById('searchResults').style.display='none';
  }
});

// Toast helper
function showToast(message, type='success', duration=4000){
  const c = document.getElementById('toastContainer');
  const t = document.createElement('div');
  t.className = 'toast toast-' + type;
  t.innerHTML = '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>' + esc(message);
  c.appendChild(t);
  setTimeout(()=>{t.style.opacity='0';setTimeout(()=>t.remove(),300)}, duration);
}

// Confirm dialog helper
function confirmAction(msg, callback){
  if(confirm(msg)) callback();
}

// Load notification badge count on page load
(async function(){
  try{
    const r = await fetch('/api/notifications');
    const d = await r.json();
    document.getElementById('notifDot').style.display = d.unread_count > 0 ? 'block' : 'none';
  }catch(e){}
})();
// Poll every 60s
setInterval(async()=>{
  try{
    const r = await fetch('/api/notifications');
    const d = await r.json();
    document.getElementById('notifDot').style.display = d.unread_count > 0 ? 'block' : 'none';
  }catch(e){}
}, 60000);

// ── Stat card 3D mouse tilt ────────────────────────────────────────
(function(){
  const MAX = 5;
  const attached = new WeakSet();
  function applyTilt(card){
    if(attached.has(card)) return;
    attached.add(card);
    card.style.transformOrigin = 'center center';
    card.addEventListener('mousemove', function(e){
      var r  = card.getBoundingClientRect();
      var dx = (e.clientX - r.left  - r.width  / 2) / (r.width  / 2);
      var dy = (e.clientY - r.top   - r.height / 2) / (r.height / 2);
      card.style.transform  = 'translateY(-3px) perspective(600px) rotateX('+(-dy*MAX)+'deg) rotateY('+(dx*MAX)+'deg)';
      card.style.transition = 'transform 0.05s ease-out, box-shadow 0.2s';
      card.style.boxShadow  = '0 12px 32px rgba(0,0,0,0.13)';
    });
    card.addEventListener('mouseleave', function(){
      card.style.transform  = '';
      card.style.transition = 'transform 0.35s ease-out, box-shadow 0.35s';
      card.style.boxShadow  = '';
    });
  }
  function initTilts(){
    document.querySelectorAll('.stat-card, .panel-card, [data-glass-tilt]').forEach(applyTilt);
  }
  document.addEventListener('DOMContentLoaded', initTilts);
  // Re-run after SPA content injections
  var mc = document.getElementById('mainContent');
  if(mc){ new MutationObserver(initTilts).observe(mc,{childList:true,subtree:false}); }
})();

// ── Keyboard Shortcuts Panel ──────────────────────────────────────
(function(){
  var panel=document.createElement('div');
  panel.id='shortcutsPanel';
  panel.style.cssText='display:none;position:fixed;inset:0;z-index:10001;align-items:center;justify-content:center';
  panel.innerHTML='<div data-shortcuts-close style="position:absolute;inset:0;background:rgba(0,0,0,.45);backdrop-filter:blur(2px)"></div>'+
    '<div style="position:relative;background:var(--surface);border-radius:16px;padding:28px;width:440px;max-width:92vw;box-shadow:var(--shadow-lg)">'+
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">'+
        '<h3 style="font-size:16px;font-weight:800;color:var(--text);margin:0">Keyboard Shortcuts</h3>'+
        '<button type="button" data-shortcuts-close style="background:none;border:none;font-size:20px;color:var(--muted);cursor:pointer">&times;</button>'+
      '</div>'+
      '<div style="display:grid;gap:8px;font-size:13px">'+
        '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border-soft)"><span style="color:var(--text)">Show this panel</span><kbd style="padding:3px 8px;border-radius:4px;background:var(--surface2);border:1px solid var(--border);font-size:12px;font-family:var(--mono);color:var(--muted)">?</kbd></div>'+
        '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border-soft)"><span style="color:var(--text)">Global search</span><kbd style="padding:3px 8px;border-radius:4px;background:var(--surface2);border:1px solid var(--border);font-size:12px;font-family:var(--mono);color:var(--muted)">Ctrl + K</kbd></div>'+
        '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border-soft)"><span style="color:var(--text)">Go to Command Centre</span><kbd style="padding:3px 8px;border-radius:4px;background:var(--surface2);border:1px solid var(--border);font-size:12px;font-family:var(--mono);color:var(--muted)">G then H</kbd></div>'+
        '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border-soft)"><span style="color:var(--text)">Go to Task Board</span><kbd style="padding:3px 8px;border-radius:4px;background:var(--surface2);border:1px solid var(--border);font-size:12px;font-family:var(--mono);color:var(--muted)">G then T</kbd></div>'+
        '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border-soft)"><span style="color:var(--text)">Go to Audit Log</span><kbd style="padding:3px 8px;border-radius:4px;background:var(--surface2);border:1px solid var(--border);font-size:12px;font-family:var(--mono);color:var(--muted)">G then L</kbd></div>'+
        '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border-soft)"><span style="color:var(--text)">New item (primary action)</span><kbd style="padding:3px 8px;border-radius:4px;background:var(--surface2);border:1px solid var(--border);font-size:12px;font-family:var(--mono);color:var(--muted)">N</kbd></div>'+
        '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0"><span style="color:var(--text)">Close modal / panel</span><kbd style="padding:3px 8px;border-radius:4px;background:var(--surface2);border:1px solid var(--border);font-size:12px;font-family:var(--mono);color:var(--muted)">Escape</kbd></div>'+
      '</div>'+
    '</div>';
  document.body.appendChild(panel);
  panel.addEventListener('click',function(event){
    if(event.target.closest('[data-shortcuts-close]'))panel.style.display='none';
  });

  var lastKey='';var lastKeyTime=0;
  document.addEventListener('keydown',function(e){
    var tag=e.target.tagName;
    if(tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT'||e.target.isContentEditable) return;
    var now=Date.now();
    if(e.key==='?'&&!e.ctrlKey&&!e.metaKey){
      e.preventDefault();
      var sp=document.getElementById('shortcutsPanel');
      sp.style.display=sp.style.display==='flex'?'none':'flex';
      return;
    }
    if(e.key==='Escape'){
      document.getElementById('shortcutsPanel').style.display='none';
      return;
    }
    if(e.key==='n'&&!e.ctrlKey&&!e.metaKey){
      var btn=document.querySelector('.header-actions .btn-primary, .topbar-actions .btn-primary');
      if(btn){e.preventDefault();btn.click();}
      return;
    }
    if(lastKey==='g'&&(now-lastKeyTime)<1000){
      if(e.key==='h'){e.preventDefault();window.location.href='/dashboard';}
      else if(e.key==='t'){e.preventDefault();window.location.href='/tasks';}
      else if(e.key==='l'){e.preventDefault();window.location.href='/admin/logs';}
      lastKey='';return;
    }
    if(e.key==='g'&&!e.ctrlKey&&!e.metaKey){lastKey='g';lastKeyTime=now;return;}
    lastKey='';
  });
})();
