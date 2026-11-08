var _vdAll=[], _vdFilter='all';

function esc(s){var d=document.createElement('div');d.textContent=s||'';return d.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function rb(v){var m={critical:'rgba(220,38,38,.12)',high:'rgba(249,115,22,.12)',medium:'rgba(217,119,6,.12)',low:'rgba(22,163,74,.12)'};var t={critical:'#dc2626',high:'#f97316',medium:'#d97706',low:'#16a34a'};var k=String(v||'medium').toLowerCase();return '<span style="background:'+(m[k]||m.medium)+';color:'+(t[k]||t.medium)+';padding:2px 8px;border-radius:5px;font-size:11px;font-weight:700;text-transform:capitalize">'+esc(k)+'</span>';}
function dpaBadge(s){var c=s==='signed'?'present':s==='expired'?'danger':'warn';var ico=s==='signed'?'✓':s==='expired'?'✗':'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-hourglass></use></svg>';return '<span class="vd-badge '+c+'">'+ico+' DPA '+esc(s||'pending')+'</span>';}
function vendorId(value){var id=Number(value);return Number.isSafeInteger(id)&&id>0?id:null;}

var VD_CAN_FLAG_AI = document.getElementById('vdGrid').dataset.canFlagAi === 'true';
var VD_AI_ON = document.getElementById('vdGrid').dataset.aiOn === 'true';
async function vdLoad(){
  document.getElementById('vdGrid').innerHTML='<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--muted)">Loading vendor directory...</div>';
  try{
    var d=await fetch('/api/vendors/directory').then(r=>r.json());
    _vdAll=d.items||[];
    vdRenderStats();
    vdRender();
  }catch(e){
    document.getElementById('vdGrid').innerHTML='<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--muted)">Failed to load vendor directory.</div>';
  }
}

function vdRenderStats(){
  var total=_vdAll.length;
  var covered=_vdAll.filter(v=>v.coverage===3).length;
  var gaps=_vdAll.filter(v=>v.coverage<3).length;
  var flags=_vdAll.filter(v=>v.risk_flag).length;
  document.getElementById('vdStatTotal').textContent=total;
  document.getElementById('vdStatCovered').textContent=covered;
  document.getElementById('vdStatGaps').textContent=gaps;
  document.getElementById('vdStatFlags').textContent=flags;
}

function vdSetFilter(el, f){
  if(!['all','gaps','flags','sentinel','bcm'].includes(f)) return;
  document.querySelectorAll('.vd-chip').forEach(c=>c.classList.remove('active'));
  el.classList.add('active');
  _vdFilter=f;
  vdRender();
}

function vdFilter(){vdRender();}

function vdRender(){
  var q=(document.getElementById('vdSearch').value||'').toLowerCase();
  var items=_vdAll.filter(function(v){
    if(q && !(v.name||'').toLowerCase().includes(q) && !(v.services||'').toLowerCase().includes(q)) return false;
    if(_vdFilter==='gaps') return v.coverage < 3;
    if(_vdFilter==='flags') return !!v.risk_flag;
    if(_vdFilter==='sentinel') return v.sentinel&&v.sentinel.id&&!v.grid?.id&&!v.bcm?.id;
    if(_vdFilter==='bcm') return v.bcm&&v.bcm.id&&!v.sentinel?.id&&!v.grid?.id;
    return true;
  });
  if(!items.length){
    document.getElementById('vdGrid').innerHTML='<div class="vd-empty" style="grid-column:1/-1"><div class="vd-empty-icon"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-building></use></svg></div><div class="vd-empty-title">No vendors found</div><div>Try adjusting your search or filters</div></div>';
    return;
  }
  document.getElementById('vdGrid').innerHTML=items.map(function(v){
    var id=vendorId(v.id);
    if(!id) return '';
    var flag=String(v.risk_flag||'').toLowerCase();
    var flagClass=['critical','high'].includes(flag)?'flag-'+flag:'';
    var coverage=Number(v.coverage);
    var pct=Number.isFinite(coverage)?Math.max(0,Math.min(100,Math.round((coverage/3)*100))):0;
    var senBadge=v.sentinel&&v.sentinel.id
      ? '<span class="vd-badge present"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-lock></use></svg> Privacy</span>'+(v.sentinel.dpa_status==='expired'?'<span class="vd-badge danger">DPA Expired</span>':v.sentinel.dpa_status==='signed'?'':'<span class="vd-badge warn">No DPA</span>')
      : '<span class="vd-badge absent"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-lock></use></svg> Privacy</span>';
    var gridBadge=v.grid&&v.grid.id
      ? '<span class="vd-badge present"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-clipboard-list></use></svg> Audit</span>'
      : '<span class="vd-badge absent"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-clipboard-list></use></svg> Audit</span>';
    var bcmBadge=v.bcm&&v.bcm.id
      ? '<span class="vd-badge present"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-shield></use></svg> Resilience</span>'+(v.bcm.tier?'<span class="vd-badge present">Tier '+esc(v.bcm.tier)+'</span>':'')
      : '<span class="vd-badge absent"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-shield></use></svg> Resilience</span>';
    return '<div class="vd-card '+flagClass+'" role="button" tabindex="0" data-vendor-id="'+id+'">'+
      '<div class="vd-card-name">'+esc(v.name)+'</div>'+
      '<div class="vd-card-services">'+esc(v.services||v.country||'No description')+'</div>'+
      '<div class="vd-coverage-bar"><div class="vd-coverage-fill" style="width:'+pct+'%"></div></div>'+
      '<div class="vd-coverage">'+senBadge+gridBadge+bcmBadge+'</div>'+
      (v.risk_flag?'<div class="vd-flag-row"><span class="vd-flag '+(['critical','high','medium'].includes(flag)?flag:'')+'"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg> Risk flag — click to view</span></div>':'')+
    '</div>';
  }).join('');
}

async function vdOpenDrawer(canonicalId){
  canonicalId=vendorId(canonicalId);
  if(!canonicalId) return;
  var overlay=document.getElementById('vdDrawerOverlay');
  var drawer=document.getElementById('vdDrawer');
  drawer.innerHTML='<button class="vd-drawer-close" aria-label="Close vendor details">×</button><div style="padding:40px;text-align:center;color:var(--muted)">Loading...</div>';
  overlay.classList.add('open');
  try{
    var p=await fetch('/api/vendors/'+canonicalId+'/profile').then(r=>r.json());
    _vdCurrentProfile=p;
    var c=p.canonical||{};
    var sen=p.modules&&p.modules.sentinel||null;
    var grid=p.modules&&p.modules.grid||null;
    var bcm=p.modules&&p.modules.bcm||null;
    var flags=p.flags||[];
    var html='<button class="vd-drawer-close" aria-label="Close vendor details">×</button>'+
      '<div class="vd-drawer-title">'+esc(c.name||'Vendor')+'</div>'+
      '<div class="vd-drawer-sub">'+esc(c.services||c.country||'')+(c.contact_email?' &middot; '+esc(c.contact_email):'')+'</div>';
    // Flags
    if(flags.length){
      html+='<div style="margin-bottom:14px">'+flags.map(function(f){
        return '<div style="display:flex;align-items:center;gap:6px;padding:6px 10px;background:rgba(220,38,38,.07);border:1px solid rgba(220,38,38,.2);border-radius:7px;margin-bottom:5px;font-size:12px;font-weight:600;color:#dc2626"><span><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg></span>'+esc(f.msg)+'</div>';
      }).join('')+'</div>';
    }
    // AI use: does this vendor use AI, or embed it in what it sells us?
    var aiLabels={yes:'Yes',no:'No',unknown:'Not sure'};
    if(VD_AI_ON){
    html+='<div class="vd-module-section">'+
      '<div class="vd-module-head"><div class="vd-module-icon" style="background:rgba(15,118,110,.14)">AI</div><span>AI use</span></div>'+
      '<div class="vd-kv"><span class="vd-kv-k">Uses AI or embedded AI?</span><span class="vd-kv-v">'+esc(aiLabels[c.uses_ai]||'Not asked yet')+'</span></div>'+
      (c.uses_ai_note?'<div class="vd-kv"><span class="vd-kv-k">Note</span><span class="vd-kv-v" style="font-size:11px;max-width:220px;text-align:right">'+esc(c.uses_ai_note)+'</span></div>':'');
    if(VD_CAN_FLAG_AI){
      html+='<div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">'+
        '<select id="vdUsesAi" aria-label="Uses AI or embedded AI?" style="padding:6px 8px;border:1px solid var(--border);border-radius:6px;background:var(--surface2);color:var(--text)">'+
          ['','yes','no','unknown'].map(function(v){return '<option value="'+v+'"'+((c.uses_ai||'')===v?' selected':'')+'>'+(v?aiLabels[v]:'Choose')+'</option>';}).join('')+'</select>'+
        '<input id="vdUsesAiNote" aria-label="What does it do?" placeholder="What does it do? (optional)" value="'+esc(c.uses_ai_note||'')+'" style="flex:1;min-width:120px;padding:6px 8px;border:1px solid var(--border);border-radius:6px;background:var(--surface2);color:var(--text)">'+
        '<button class="vd-add-btn" data-vendor-action="save-ai" data-vendor-id="'+canonicalId+'">Save</button></div>'+
        '<div id="vdUsesAiMsg" role="status" style="font-size:11px;color:var(--muted);margin-top:4px"></div>';
    }
    html+='</div>';
    }
    // Privacy / Sentinel
    html+='<div class="vd-module-section">'+
      '<div class="vd-module-head"><div class="vd-module-icon sentinel"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-lock></use></svg></div><span>Privacy (Sentinel)</span></div>';
    if(sen){
      html+='<div class="vd-kv"><span class="vd-kv-k">DPA Status</span><span class="vd-kv-v">'+dpaBadge(sen.dpa_status)+'</span></div>'+
        '<div class="vd-kv"><span class="vd-kv-k">Type</span><span class="vd-kv-v">'+esc(sen.type||'—')+'</span></div>'+
        '<div class="vd-kv"><span class="vd-kv-k">Risk Level</span><span class="vd-kv-v">'+rb(sen.risk_level)+'</span></div>'+
        '<div class="vd-kv"><span class="vd-kv-k">Regulation</span><span class="vd-kv-v">'+esc(sen.regulation||'—')+'</span></div>'+
        (sen.ai_assessment?'<div class="vd-kv"><span class="vd-kv-k">AI Assessment</span><span class="vd-kv-v" style="font-size:11px;max-width:220px;text-align:right">'+esc((sen.ai_assessment||'').substring(0,80)+(sen.ai_assessment&&sen.ai_assessment.length>80?'…':''))+'</span></div>':'')+
        '<a class="vd-go-btn" href="/sentinel/vendors">→ Open in Privacy</a>';
    } else {
      html+='<div style="color:var(--muted);font-size:12px;margin-bottom:8px">Not registered in Privacy</div>'+
        '<button class="vd-add-btn" data-vendor-action="register" data-module="sentinel" data-vendor-id="'+canonicalId+'">+ Register in Privacy</button>';
    }
    html+='</div>';
    // Audit / GRID
    html+='<div class="vd-module-section">'+
      '<div class="vd-module-head"><div class="vd-module-icon grid"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-clipboard-list></use></svg></div><span>Audit (GRID)</span></div>';
    if(grid){
      var ass=grid.latest_assessment;
      html+='<div class="vd-kv"><span class="vd-kv-k">Risk Level</span><span class="vd-kv-v">'+rb(grid.risk_level)+'</span></div>'+
        '<div class="vd-kv"><span class="vd-kv-k">Status</span><span class="vd-kv-v">'+esc(grid.status||'active')+'</span></div>'+
        '<div class="vd-kv"><span class="vd-kv-k">Frameworks</span><span class="vd-kv-v">'+esc(grid.frameworks||'—')+'</span></div>'+
        (grid.contract_expiry?'<div class="vd-kv"><span class="vd-kv-k">Contract Expiry</span><span class="vd-kv-v">'+esc(grid.contract_expiry)+'</span></div>':'')+
        (ass?'<div class="vd-kv"><span class="vd-kv-k">Last Score</span><span class="vd-kv-v" style="color:'+(Number(ass.score)>=70?'#16a34a':Number(ass.score)>=50?'#d97706':'#dc2626')+'">'+(Number.isFinite(Number(ass.score))?Number(ass.score):0)+'%  ('+esc(ass.assessment_date)+')</span></div>':'<div class="vd-kv"><span class="vd-kv-k">Last Score</span><span class="vd-kv-v" style="color:var(--muted)">Not yet assessed</span></div>')+
        '<a class="vd-go-btn" href="/grid/vendors">→ Open in Audit</a>';
    } else {
      html+='<div style="color:var(--muted);font-size:12px;margin-bottom:8px">Not registered in Audit</div>'+
        '<button class="vd-add-btn" data-vendor-action="register" data-module="grid" data-vendor-id="'+canonicalId+'">+ Register in Audit</button>';
    }
    html+='</div>';
    // Resilience / BCM
    html+='<div class="vd-module-section">'+
      '<div class="vd-module-head"><div class="vd-module-icon bcm"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-shield></use></svg></div><span>Resilience (BCM)</span></div>';
    if(bcm){
      html+='<div class="vd-kv"><span class="vd-kv-k">Criticality</span><span class="vd-kv-v">'+rb(bcm.criticality||'medium')+'</span></div>'+
        '<div class="vd-kv"><span class="vd-kv-k">Tier</span><span class="vd-kv-v">Tier '+esc(String(bcm.tier||3))+'</span></div>'+
        (bcm.sla?'<div class="vd-kv"><span class="vd-kv-k">SLA</span><span class="vd-kv-v">'+esc(bcm.sla)+'</span></div>':'')+
        (bcm.contract_renewal?'<div class="vd-kv"><span class="vd-kv-k">Contract Renewal</span><span class="vd-kv-v">'+esc(bcm.contract_renewal)+'</span></div>':'')+
        (bcm.data_sensitivity?'<div class="vd-kv"><span class="vd-kv-k">Data Sensitivity</span><span class="vd-kv-v">'+esc(bcm.data_sensitivity)+'</span></div>':'')+
        '<a class="vd-go-btn" href="/bcm/vendors">→ Open in Resilience</a>';
    } else {
      html+='<div style="color:var(--muted);font-size:12px;margin-bottom:8px">Not registered in Resilience</div>'+
        '<button class="vd-add-btn" data-vendor-action="register" data-module="bcm" data-vendor-id="'+canonicalId+'">+ Register in Resilience</button>';
    }
    html+='</div>';
    drawer.innerHTML=html;
    if(typeof DialogFocus!=='undefined')DialogFocus.trap(drawer);
  }catch(e){
    drawer.innerHTML='<button class="vd-drawer-close" aria-label="Close vendor details">×</button><div style="padding:40px;text-align:center;color:var(--muted)">Failed to load vendor profile.</div>';
  }
}

async function vdSaveUsesAi(canonicalId){
  canonicalId=vendorId(canonicalId);
  if(!canonicalId) return;
  var answer=document.getElementById('vdUsesAi').value, note=document.getElementById('vdUsesAiNote').value;
  var msg=document.getElementById('vdUsesAiMsg');
  if(!answer){msg.textContent='Choose yes, no or not sure.';return;}
  msg.textContent='Saving...';
  try{
    var r=await fetch('/ai-governance/api/flags/vendor/'+canonicalId,{method:'PUT',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({answer:answer,note:note,source:'Vendor directory'})});
    var d=await r.json().catch(function(){return {};});
    if(r.ok){await vdOpenDrawer(canonicalId);}
    else{msg.textContent=d.error||d.detail||'Could not save.';}
  }catch(e){msg.textContent='Network error.';}
}

function vdCloseDrawer(){
  document.getElementById('vdDrawerOverlay').classList.remove('open');
  if (typeof DialogFocus !== 'undefined') DialogFocus.release();
}
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape' && document.getElementById('vdDrawerOverlay').classList.contains('open')) vdCloseDrawer();
});

// Holds the last-loaded canonical vendor profile so registration can use it
var _vdCurrentProfile = null;

async function vdPromptAddModule(canonicalId, module, btn){
  canonicalId=vendorId(canonicalId);
  if(!canonicalId || !['sentinel','grid','bcm'].includes(module)) return;
  var names={sentinel:'Privacy (Sentinel)',grid:'Audit (GRID)',bcm:'Resilience (BCM)'};
  var apiUrls={sentinel:'/sentinel/api/vendors',grid:'/grid/api/vendors',bcm:'/bcm/api/vendors'};
  var c = (_vdCurrentProfile && _vdCurrentProfile.canonical) || {};

  // Find the button that was clicked and show a spinner
  if(btn){ btn.disabled=true; btn.textContent='Registering…'; }

  try{
    var payload = {
      name: c.name || 'Unnamed Vendor',
      contact_name: c.contact_name || '',
      contact_email: c.contact_email || '',
      services: c.services || '',
      canonical_id: canonicalId,
    };
    var resp = await fetch(apiUrls[module], {
      method:'POST',
      headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},
      body:JSON.stringify(payload)
    });
    if(resp.ok){
      // Refresh the drawer to show the new registration
      await vdOpenDrawer(canonicalId);
      // Also refresh vendor list stats
      vdLoad();
    } else {
      var err = await resp.json().catch(()=>({}));
      alert('Failed to register in '+names[module]+': '+(err.detail||err.error||resp.status));
      if(btn){ btn.disabled=false; btn.textContent='+ Register in '+names[module].split(' ')[0]; }
    }
  } catch(e){
    alert('Network error: '+e.message);
    if(btn){ btn.disabled=false; btn.textContent='+ Register in '+names[module].split(' ')[0]; }
  }
}

function vdOpenAddModal(){
  document.getElementById('vdModalRoot').innerHTML=
    '<div id="vdModalOverlay" style="position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:300;display:flex;align-items:center;justify-content:center" role="dialog" aria-modal="true" aria-labelledby="vdModalTitle">'+
    '<div style="background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:24px;width:440px;max-width:95vw">'+
    '<div id="vdModalTitle" style="font-size:17px;font-weight:700;margin-bottom:14px">Add to Vendor Directory</div>'+
    '<form id="vdAddForm">'+
    '<div style="margin-bottom:10px"><label style="font-size:12px;color:var(--muted);display:block;margin-bottom:4px">Vendor Name *</label><input name="name" required placeholder="Company name" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--surface2);color:var(--text);font-size:13px;box-sizing:border-box"></div>'+
    '<div style="margin-bottom:10px"><label style="font-size:12px;color:var(--muted);display:block;margin-bottom:4px">Services</label><input name="services" placeholder="What do they provide?" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--surface2);color:var(--text);font-size:13px;box-sizing:border-box"></div>'+
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">'+
    '<div><label style="font-size:12px;color:var(--muted);display:block;margin-bottom:4px">Contact Name</label><input name="contact_name" placeholder="Contact" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--surface2);color:var(--text);font-size:13px;box-sizing:border-box"></div>'+
    '<div><label style="font-size:12px;color:var(--muted);display:block;margin-bottom:4px">Contact Email</label><input name="contact_email" type="email" placeholder="email@co.com" style="width:100%;padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:var(--surface2);color:var(--text);font-size:13px;box-sizing:border-box"></div>'+
    '</div>'+
    '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px">'+
    '<button type="button" class="btn btn-secondary" id="vdCancelAdd">Cancel</button>'+
    '<button type="submit" class="btn btn-primary">Add Vendor</button></div>'+
    '</form></div></div>';
}

async function vdCreateCanonical(e){
  e.preventDefault();
  var f=e.target;
  var field=name=>f.elements.namedItem(name)?.value||'';
  var body={name:field('name'),services:field('services'),contact_name:field('contact_name'),contact_email:field('contact_email')};
  try{
    var r=await fetch('/api/vendors/directory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(r.ok){
      document.getElementById('vdModalRoot').innerHTML='';
      if(typeof showToast==='function') showToast('Vendor added to directory','success');
      vdLoad();
    } else {
      if(typeof showToast==='function') showToast('Failed to add vendor','error');
    }
  }catch(ex){if(typeof showToast==='function') showToast('Error: '+ex.message,'error');}
  return false;
}

document.getElementById('vdOpenAdd')?.addEventListener('click', vdOpenAddModal);
document.getElementById('vdSearch').addEventListener('input', vdFilter);
document.querySelectorAll('.vd-chip').forEach(button => {
  button.addEventListener('click', () => vdSetFilter(button, button.dataset.f));
});
document.getElementById('vdGrid').addEventListener('click', event => {
  const card=event.target.closest('.vd-card[data-vendor-id]');
  if(card) vdOpenDrawer(vendorId(card.dataset.vendorId));
});
document.getElementById('vdGrid').addEventListener('keydown', event => {
  if(event.key!=='Enter' && event.key!==' ') return;
  const card=event.target.closest('.vd-card[data-vendor-id]');
  if(!card || event.target!==card) return;
  event.preventDefault();
  vdOpenDrawer(vendorId(card.dataset.vendorId));
});
document.getElementById('vdDrawerOverlay').addEventListener('click', event => {
  if(event.target===event.currentTarget) vdCloseDrawer();
});
document.getElementById('vdDrawer').addEventListener('click', event => {
  if(event.target.closest('.vd-drawer-close')) {vdCloseDrawer();return;}
  const button=event.target.closest('[data-vendor-action][data-vendor-id]');
  if(!button) return;
  const id=vendorId(button.dataset.vendorId);
  if(!id) return;
  if(button.dataset.vendorAction==='save-ai') vdSaveUsesAi(id);
  else if(button.dataset.vendorAction==='register') vdPromptAddModule(id, button.dataset.module, button);
});
document.getElementById('vdModalRoot').addEventListener('click', event => {
  if(event.target.id==='vdModalOverlay' || event.target.id==='vdCancelAdd') event.currentTarget.innerHTML='';
});
document.getElementById('vdModalRoot').addEventListener('submit', event => {
  if(event.target.id==='vdAddForm') vdCreateCanonical(event);
});

vdLoad();
