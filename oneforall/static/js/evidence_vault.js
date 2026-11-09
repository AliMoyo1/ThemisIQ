var currentView='all', currentModule='', currentCategory='', currentStatus='', searchTimeout=null, entitySearchTimeout=null;
var evFolder='',evFolderGroup='',evFolderPage=1,evFolderSearchTimer=null;
var evCompanyScope='',evCompanyViews=null,evGroupSource=null,evGroupCursor=null,evGroupBack=[];
var evEntityScope='',evEntityViews=null;
var evPage=1, evPages=1;
var evSavedViews=[], evUserId=Number(document.getElementById('evidencePageData').dataset.userId);
var evViewMode = localStorage.getItem('ev-view-mode') || 'table';
var evCanReviewLinks = false, evOwnerOnly = false, evDetailItem = null, currentState = '', currentWords = '';
var evFindFilters = null, evFindVocab = null;
var evStateKind={needs_filing:'warn',awaiting_review:'warn',returned:'bad',expired:'bad',replaced:'muted',archived:'muted',draft:'muted',accepted:'good'};
var evCanBulkArchive = document.getElementById('evidencePageData').dataset.bulkArchive==='true';
var evSelectionMode = false, evSelectedIds = new Set(), evVisibleIds = [];
var evLoadSeq = 0;
var iconMap={policy:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-clipboard-list></use></svg>',certificate:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-medal></use></svg>',screenshot:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-image></use></svg>',report:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-chart-column></use></svg>',
  generated_record:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-scroll-text></use></svg>',procedure:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-file-pen></use></svg>',training:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-graduation-cap></use></svg>',general:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-file-text></use></svg>',policy_approval:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-clipboard-list></use></svg>',
  control_assessment:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-chart-column></use></svg>',audit_finding:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg>',audit_completion:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-circle-check></use></svg>',
  non_conformance:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-circle-x></use></svg>',risk_assessment:'<svg class=ic-red aria-hidden=true><use href=/static/icons/sprite.svg#ic-dot></use></svg>',incident_record:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-siren></use></svg>',breach_record:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-lock-open></use></svg>',
  dpia_record:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-shield></use></svg>',dsr_overdue:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-alarm-clock></use></svg>',plan_approval:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-circle-check></use></svg>'};
var modColors={aria:'#7e8062',grid:'#1a6b3a',bcm:'#8a8a5b',sentinel:'#00a5c8',erm:'#dc3c50',governance:'#0f766e',platform:'#6b7280'};
var entityTypes={
  aria:['control','document','risk','framework'],
  grid:['audit','control','non_conformance'],
  bcm:['plan','incident','risk','bia','compliance_control'],
  sentinel:['ropa','dpia','breach','dsr','vendor'],
  erm:['risk','scenario'],
  governance:['application']
};

// Template controls carry inert action names. Only these known actions can run;
// the attribute value is never evaluated as JavaScript.
document.addEventListener('click',function(event){
  var button=event.target.closest('[data-ev-click]');
  if(!button)return;
  if(button.matches('a[href="#"]'))event.preventDefault();
  var call=button.dataset.evClick;
  var view=/^switchView\('(all|archived|expiring|for_review|generated_history|needs_filing|recent|review_due)',/.exec(call);
  if(view){switchView(view[1],button.classList.contains('nav-item')?button:document.getElementById('nav-'+(view[1]==='needs_filing'?'unlinked':view[1])));return;}
  var module=/^filterModule\('(aria|bcm|grid|sentinel|)',this\)$/.exec(call);
  if(module){filterModule(module[1],button);return;}
  var category=/^filterCategory\('(certificate|general|policy|screenshot|)'\)$/.exec(call);
  if(category){filterCategory(category[1]);return;}
  var mode=/^setViewMode\('(cards|table)'\)$/.exec(call);
  if(mode){setViewMode(mode[1]);return;}
  var modal=/^ModalManager\.(open|close)\('(uploadModal|findModal|reviewModal|linkToModal)'\)$/.exec(call);
  if(modal){ModalManager[modal[1]](modal[2]);return;}
  switch(call){
    case "evChooseFolder('reports',true);return false":evChooseFolder('reports',true);break;
    case 'clearUploadTarget()':clearUploadTarget();break;
    case 'closeDetail()':closeDetail();break;
    case "document.getElementById('evLegacyPanel').hidden=true":document.getElementById('evLegacyPanel').hidden=true;break;
    case 'evBulkArchive()':evBulkArchive();break;
    case 'evCloseRecordFolders()':evCloseRecordFolders();break;
    case 'evDeleteSavedView()':evDeleteSavedView();break;
    case 'evFindApply()':evFindApply();break;
    case 'evFindOpen()':evFindOpen();break;
    case 'evGoToPage(evPage+1)':evGoToPage(evPage+1);break;
    case 'evGoToPage(evPage-1)':evGoToPage(evPage-1);break;
    case 'evOpenLegacy()':evOpenLegacy();break;
    case 'evSaveCurrentView()':evSaveCurrentView();break;
    case 'evToggleSelection()':evToggleSelection();break;
  }
});
document.addEventListener('change',function(event){
  var call=event.target.dataset.evChange;
  if(call==='evApplySavedView(this.value)')evApplySavedView(event.target.value);
  else if(call==='loadEntityTypes()')loadEntityTypes();
  else if(call==='searchEntities()')searchEntities();
  else if(call==='uploadTargetModuleChanged()')uploadTargetModuleChanged();
  else if(call==='uploadTargetTypeChanged()')uploadTargetTypeChanged();
});
document.addEventListener('input',function(event){
  var call=event.target.dataset.evInput||event.target.dataset.evKeyup;
  if(call==='debounceEntitySearch()')debounceEntitySearch();
  else if(call==='debounceSearch()')debounceSearch();
  else if(call==='debounceUploadTargetSearch()')debounceUploadTargetSearch();
  else if(call==='evSearchRecordFolders()')evSearchRecordFolders();
});
document.addEventListener('submit',function(event){
  var call=event.target.dataset.evSubmit;
  if(!call)return;
  event.preventDefault();
  if(call==='evFindRun(event,false)')evFindRun(event,false);
  else if(call==='evFindRun(event,true)')evFindRun(event,true);
  else if(call==='evSubmitReview(event)')evSubmitReview(event);
  else if(call==='handleUpload(event)')handleUpload(event);
});

// Generated controls use the same inert attribute contract. Parse only known
// calls with checked IDs and fields; never execute attribute text as code.
function evRunGenerated(call,element){
  var m, id, field;
  if(call==='event.stopPropagation()')return;
  if(call==='closeDetail()'){closeDetail();return;}
  if(call==="evShowTab('history')"){evShowTab('history');return;}
  if(call==="evShowTab('details')"){evShowTab('details');return;}
  if(call==="evShowTab('activity')"){evShowTab('activity');return;}
  if(call==="document.getElementById('ev-tags-editor').style.display='none';document.getElementById('ev-tags-display').style.display='block'"){
    document.getElementById('ev-tags-editor').style.display='none';document.getElementById('ev-tags-display').style.display='block';return;
  }
  if(call==="document.getElementById('ev-desc-editor').style.display='none';document.getElementById('ev-desc-display').style.display='block'"){
    document.getElementById('ev-desc-editor').style.display='none';document.getElementById('ev-desc-display').style.display='block';return;
  }
  // Insights cards: the number counts the whole library, so the list it opens drops every other filter first
  m=/^switchView\('(all|expiring|needs_filing)',/.exec(call);
  if(m){evClearFilters();switchView(m[1],document.getElementById('nav-'+(m[1]==='needs_filing'?'unlinked':m[1])));return;}
  m=/^filterModule\('(aria|grid|bcm|sentinel|erm|orm|governance|platform)',null\)$/.exec(call);
  if(m){evClearFilters();currentModule=m[1];switchView('all',document.getElementById('nav-all'));return;}
  m=/^ModalManager\.close\('(findModal|uploadModal)'\);(openDetail|openLinkToModal)\(([1-9]\d*)\)$/.exec(call);
  if(m){ModalManager.close(m[1]);(m[2]==='openDetail'?openDetail:openLinkToModal)(Number(m[3]));return;}
  m=/^(openDetail|evInlineOwner|evAddVersion|evEditTags|evEditDesc|aiSuggestLinks|doRemoveVerification|verifyIntegrity|openLinkToModal|restoreEvidence|permanentDeleteEvidence|archiveEvidence)\(([1-9]\d*)\)$/.exec(call);
  if(m){({openDetail,evInlineOwner,evAddVersion,evEditTags,evEditDesc,aiSuggestLinks,doRemoveVerification,verifyIntegrity,openLinkToModal,restoreEvidence,permanentDeleteEvidence,archiveEvidence})[m[1]](Number(m[2]));return;}
  m=/^evDownload\(([1-9]\d*),(true|false)\)$/.exec(call);
  if(m){evDownload(Number(m[1]),m[2]==='true');return;}
  m=/^unlinkEvidence\(([1-9]\d*),([1-9]\d*)\)$/.exec(call);
  if(m){unlinkEvidence(Number(m[1]),Number(m[2]));return;}
  m=/^doSetVerification\(([1-9]\d*),'(self_asserted|peer_reviewed|auditor_signed|digitally_signed)'\)$/.exec(call);
  if(m){doSetVerification(Number(m[1]),m[2]);return;}
  m=/^evInlineEdit\('(title|expiry_date|review_due_date|period_start|period_end)',([1-9]\d*),(this|null)\)$/.exec(call);
  if(m){evInlineEdit(m[1],Number(m[2]),m[3]==='this'?element:null);return;}
  m=/^evSaveField\('(title|tags|description|expiry_date|review_due_date|period_start|period_end|category|status|owner_user_id)',([1-9]\d*),(?:document\.getElementById\('ev-input-[a-z_]+'\)\.value|this\.value)\)$/.exec(call);
  if(m){field=m[1];id=Number(m[2]);var input=call.endsWith('this.value)')?element:document.getElementById('ev-input-'+field);if(input)evSaveField(field,id,input.value);return;}
}
document.addEventListener('click',function(event){
  if(event.target.closest('[data-ev-action]'))return;
  var element=event.target.closest('[data-ev-dynamic]');
  if(!element)return;
  if(element.dataset.evDynamic==='event.stopPropagation()'){event.stopPropagation();return;}
  evRunGenerated(element.dataset.evDynamic,element);
});
document.addEventListener('change',function(event){
  var call=event.target.dataset.evDynamicChange;
  if(call)evRunGenerated(call,event.target);
});

function escHtml(s){var d=document.createElement('div');d.textContent=s||'';return d.innerHTML.replace(/\"/g,'&quot;').replace(/'/g,'&#39;');}

async function evOpenLegacy(){
  document.getElementById('evLegacyPanel').hidden=false;
  await evLoadLegacy();
}
async function evLoadLegacy(){
  var rows=document.getElementById('evLegacyRows'),status=document.getElementById('evLegacyStatus');
  status.textContent='Loading historical file inventory...';
  try{
    var data=await ApiClient.request('/evidence/api/legacy-files');
    var groups=[
      {title:'GRID current files',kind:'grid',items:data.grid_files||[],allowed:data.grid_access},
      {title:'GRID historical versions',kind:'grid-versions',items:data.grid_versions||[],allowed:data.grid_access},
      {title:'BCM file references',kind:'bcm',items:data.bcm_files||[],allowed:data.bcm_access}
    ];
    rows.innerHTML=groups.map(function(group){
      if(!group.allowed)return '<h3>'+group.title+'</h3><p>Module access is required for this inventory.</p>';
      var pending=group.items.filter(function(item){return item.state!=='vault'&&!item.vault_evidence_id;});
      var visible=pending.slice(0,100);
      var table=visible.length?'<table class="ev-table"><thead><tr><th>Source</th><th>State</th><th>Action</th></tr></thead><tbody>'+
        visible.map(function(item){
          var source='#'+Number(item.id)+' '+escHtml(item.name||item.title||'Untitled');
          var action=(group.kind==='bcm'&&!data.bcm_reconcile)?'<span>BCM manage access required</span>':
            (group.kind==='bcm')?
            '<label>Matching Vault ID <input type="number" min="1" id="evLegacyVault-'+Number(item.id)+'" data-s="s6074682"></label> '+
            '<button type="button" class="btn btn-secondary" data-legacy-kind="bcm" data-legacy-id="'+Number(item.id)+'">Reconcile</button>':
            !data.grid_migrate?'<span>GRID upload access required</span>':
            item.state==='safe_local_file'?
              '<button type="button" class="btn btn-secondary" data-legacy-kind="'+group.kind+'" data-legacy-id="'+Number(item.id)+'">Copy to Vault</button>':
              '<span>Manual source review required</span>';
          return '<tr><td>'+source+'</td><td>'+escHtml(item.state)+'</td><td>'+action+'</td></tr>';
        }).join('')+'</tbody></table>':'<p>No unresolved files in this group.</p>';
      return '<h3 data-s="sd9d8b03">'+group.title+' ('+pending.length+' unresolved)</h3>'+
        (pending.length>visible.length?'<p>Showing the first 100. Resolve them and refresh for the next group.</p>':'')+table;
    }).join('');
    status.textContent='Review each source and its Vault match before changing references.';
  }catch(e){status.textContent=e.detail||'The historical file inventory could not be loaded.';}
}
document.addEventListener('click',async function(event){
  var button=event.target.closest('[data-legacy-kind]');
  if(!button)return;
  var kind=button.dataset.legacyKind,id=Number(button.dataset.legacyId);
  if(!Number.isSafeInteger(id)||id<1)return;
  var vaultId=kind==='bcm'?Number(document.getElementById('evLegacyVault-'+id)?.value):null;
  if(kind==='bcm'&&(!Number.isSafeInteger(vaultId)||vaultId<1)){
    document.getElementById('evLegacyStatus').textContent='Select the matching Vault artifact first.';return;
  }
  if(!confirm('Review the source and confirm this one historical reference should be reconciled. Continue?'))return;
  var url=kind==='grid'?'/evidence/api/legacy-files/grid/'+id+'/migrate':
    kind==='grid-versions'?'/evidence/api/legacy-files/grid-versions/'+id+'/migrate':
    '/evidence/api/legacy-files/bcm/'+id+'/reconcile';
  button.disabled=true;
  try{
    await ApiClient.request(url,{method:'POST',body:kind==='bcm'?{vault_evidence_id:vaultId}:{},
      actionId:'evidence.legacy.reconcile'});
    await evLoadLegacy();
    loadEvidence();loadStats();
  }catch(e){
    document.getElementById('evLegacyStatus').textContent=e.detail||'The reference was not changed.';
    button.disabled=false;
  }
});

function fmtSize(b){if(!b)return '0 B';var k=1024,s=['B','KB','MB','GB'],i=Math.floor(Math.log(b)/Math.log(k));return parseFloat((b/Math.pow(k,i)).toFixed(1))+' '+s[i];}
function fmtDate(ts){
  if(!ts)return '—';
  var value=String(ts);
  if(!/^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2})?/.test(value))return 'Invalid date';
  var d=new Date(value.length===10?value+'T00:00:00':value.replace(' ','T'));
  return Number.isNaN(d.getTime())?'Invalid date':d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
}
function evKnown(map,key,fallback){return Object.hasOwn(map,key)?map[key]:fallback;}
function evCount(value){var number=Number(value);return Number.isSafeInteger(number)&&number>=0?number:0;}

async function loadStats(){
  var r=await fetch('/evidence/api/stats');var s=await r.json();
  var bm=s.by_module||{};
  var exp7=s.expiring_7_days||0;
  evCanReviewLinks=!!s.can_review_links;
  document.getElementById('statsBar').innerHTML=
    '<button type="button" class="card" data-s="sc356914" data-sd="block" data-ev-dynamic="switchView(\'all\',document.getElementById(\'nav-all\'))">'+
      '<div data-s="s6c71a18">Total</div>'+
      '<div data-s="se665b0f">'+evCount(s.total)+'</div></button>'+
    '<div class="card" data-s="s186530a">'+
      '<div data-s="s6c71a18">Links</div>'+
      '<div data-s="scb7839d">'+evCount(s.total_links)+'</div></div>'+
    '<button type="button" class="card" data-s="sc356914" data-sd="block" data-ev-dynamic="switchView(\'expiring\',document.getElementById(\'nav-expiring\'))">'+
      '<div data-s="s6c71a18">Expiring 30d</div>'+
      '<div data-s="s56f123b">'+evCount(s.expiring_soon)+'</div>'+
      (exp7?'<div data-s="s51f3121"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg> '+evCount(exp7)+' within 7 days</div>':'')+
    '</button>'+
    '<button type="button" class="card" data-s="sc356914" data-sd="block" data-ev-dynamic="switchView(\'needs_filing\',document.getElementById(\'nav-unlinked\'))">'+
      '<div data-s="s6c71a18">Needs filing</div>'+
      '<div data-s="sd2e2c66">'+evCount(s.needs_filing)+'</div></button>'+
    Object.keys(bm).filter(function(m){return /^(aria|grid|bcm|sentinel|erm|orm|governance|platform)$/.test(m);}).map(function(m){
      var c=evKnown(modColors,m,'#6b7280');
      return '<button type="button" class="card" data-s="sc356914" data-sd="block" data-ev-dynamic="filterModule(\''+m+'\',null)">'+
        '<div data-s="s6c71a18">'+m.toUpperCase()+'</div>'+
        '<div data-sv="font-size:24px;font-weight:700;color:'+c+';margin-top:4px">'+evCount(bm[m])+'</div></button>';
    }).join('');
  // Work views: every count is the length of the list it opens
  function put(id,n){var node=document.getElementById(id);if(node)node.textContent=(n===null||n===undefined)?'':String(n);}
  put('wc-all',s.total);put('wc-needs_filing',s.needs_filing);put('wc-for_review',s.for_review);
  put('wc-review_due',s.review_due);put('wc-requests',s.open_requests);put('wc-recent',s.recently_updated);
  var reviewTab=document.getElementById('wt-for_review');
  if(reviewTab)reviewTab.hidden=!s.can_review_links;
  // Sidebar badges
  var be=document.getElementById('badge-all');if(be)be.textContent=s.total||'';
  var bx=document.getElementById('badge-expiring');if(bx)bx.textContent=s.expiring_soon||'';
  var bu=document.getElementById('badge-unlinked');if(bu)bu.textContent=s.needs_filing||'';
  Object.keys(bm).forEach(function(m){var b=document.getElementById('badge-'+m);if(b)b.textContent=bm[m]||'';});
  var ba=document.getElementById('badge-archived');if(ba)ba.textContent=s.archived||'';
  var na=document.getElementById('nav-archived');
  if(na){na.style.display=s.can_delete?'':'none';}
  // Recently added strip
  var recent=s.recently_added||[];
  var rs=document.getElementById('recentSection');
  var ri=document.getElementById('recentItems');
  if(recent.length){
    rs.style.display='block';
    ri.innerHTML=recent.map(function(r){
      var icon=evKnown(iconMap,r.category,null)||'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-file-text></use></svg>';
      var ago=timeAgo(r.created_at);
      return '<button type="button" class="ev-recent-card" data-s="sf35f2dc" data-ev-dynamic="openDetail('+Number(r.id)+')">'+
        '<div data-s="s4e4fe8b">'+icon+'</div>'+
        '<div data-s="s593a04d">'+escHtml(r.title)+'</div>'+
        '<div data-s="s58410bd">'+escHtml(r.category)+' · '+ago+'</div>'+
      '</button>';
    }).join('');
  } else {
    rs.style.display='none';
  }
  evLoadFolderCards();
}

function timeAgo(ts){
  if(!ts)return '';
  var d=new Date(ts.includes('T')?ts:ts+'Z');
  var diff=Math.round((Date.now()-d)/1000);
  if(diff<60)return 'just now';
  if(diff<3600)return Math.round(diff/60)+'m ago';
  if(diff<86400)return Math.round(diff/3600)+'h ago';
  return Math.round(diff/86400)+'d ago';
}

async function loadCoverage(){
  try{
    var r=await fetch('/evidence/api/coverage');var cov=await r.json();
    var dr=await fetch('/evidence/api/coverage/definitions');var defs=await dr.json();
    var m=defs.measures||{};
    var html='<div class="card" data-s="s01b9273"><div data-s="s1a24f37">Evidence coverage by module</div>'+
      '<div data-s="s7ba1841">Three different facts, counted separately. '+escHtml(defs.denominator||'')+'</div>'+
      '<div data-s="s0388286" data-sd="grid">';
    ['aria','grid','bcm','sentinel','erm'].forEach(function(mod){
      var d=cov[mod];if(!d)return;
      var c=evKnown(modColors,mod,null)||'#6b7280';
      html+='<div><div data-s="s74bdeff"><span class="ev-mod-dot" data-sv="background:'+c+';margin-right:6px" aria-hidden="true"></span>'+mod.toUpperCase()+' · '+d.total+' records</div>';
      [['linked','Has a live link'],['current','Has current proof'],['accepted','Accepted by a reviewer']].forEach(function(row){
        var n=d[row[0]]||0,pct=d['pct_'+row[0]],measured=pct!==null&&pct!==undefined;
        html+='<div data-s="s77e2b72" data-sd="flex"><span>'+escHtml(row[1])+'</span><span data-s="s57f9e31">'+(measured?n+'/'+d.total+' ('+pct+'%)':'Not measured')+'</span></div>'+
          (measured?'<div class="coverage-bar"><div class="coverage-fill" data-sv="width:'+pct+'%;background:'+c+'"></div></div>':'');
      });
      html+='</div>';
    });
    html+='</div><details class="ev-defs" data-s="s56f4356"><summary>What these mean</summary><dl data-s="s11365be">'+
      Object.keys(m).map(function(k){return '<dt data-s="s0244cca">'+escHtml(m[k].label)+'</dt><dd data-s="se1b96ba">'+escHtml(m[k].means)+'</dd>';}).join('')+
      '</dl><p data-s="s7fc448e">'+escHtml(defs.exclusions||'')+' '+escHtml(defs.empty_denominator||'')+' As of '+escHtml(defs.as_of||'')+'.</p></details></div>';
    document.getElementById('coverageBar').innerHTML=html;
  }catch(e){document.getElementById('coverageBar').innerHTML='';}
}

function expiryBadgeHtml(expiry_date){
  if(!expiry_date)return '';
  var days=Math.ceil((new Date(expiry_date)-new Date())/86400000);
  if(days<=0)return '<span data-s="sfa460a6">expired</span>';
  if(days<=7)return '<span data-s="s07421b5">'+days+'d left</span>';
  if(days<=30)return '<span data-s="s082d2bd">'+days+'d left</span>';
  return '';
}

function confBadgeHtml(score){
  if(score===null||score===undefined||!Number.isFinite(Number(score)))return '';
  score=Math.max(0,Math.min(100,Number(score)));
  var color=score>=80?'#16a34a':score>=50?'#d97706':'#dc2626';
  var bg=score>=80?'rgba(22,163,74,.1)':score>=50?'rgba(217,119,6,.1)':'rgba(220,38,38,.1)';
  return '<span data-sv="padding:2px 7px;border-radius:4px;font-size:10px;font-weight:700;background:'+bg+';color:'+color+'" title="Metadata health: how complete the file\'s own details are. It does not say the file proves anything.">'+score+'%</span>';
}

var _VERIFY_LABELS={
  'self_asserted':'Self-asserted',
  'peer_reviewed':'Peer reviewed',
  'auditor_signed':'Auditor signed',
  'digitally_signed':'Digitally signed'
};

async function doSetVerification(eid, method){
  var r=await fetch('/evidence/api/items/'+eid+'/confidence-verify',{
    method:'POST',
    headers:{'Content-Type':'application/json','X-CSRF-Token':getCsrf()},
    body:JSON.stringify({verification_method:method})
  });
  if(r.ok){openDetail(eid);}else{alert('Failed to set verification');}
}

async function doRemoveVerification(eid){
  if(!confirm('Remove verification from this evidence item?'))return;
  var r=await fetch('/evidence/api/items/'+eid+'/confidence-verify',{
    method:'DELETE',
    headers:{'X-CSRF-Token':getCsrf()}
  });
  if(r.ok){openDetail(eid);}else{alert('Failed to remove verification');}
}

function getCsrf(){
  var m=document.cookie.match(/csrf_token=([^;]+)/);
  return m?decodeURIComponent(m[1]):'';
}

function evRenderPager(data){
  var nav=document.getElementById('evPager');
  evPage=data.page;evPages=data.pages;
  if(!data.total){nav.style.display='none';return;}
  var from=(data.page-1)*data.page_size+1;
  var to=Math.min(data.page*data.page_size,data.total);
  document.getElementById('evPagerStatus').textContent='Showing '+from+' to '+to+' of '+data.total;
  document.getElementById('evPagerButtons').style.display=data.pages>1?'flex':'none';
  [['evPrevPage',data.page<=1],['evNextPage',data.page>=data.pages]].forEach(function(spec){
    var button=document.getElementById(spec[0]);
    button.setAttribute('aria-disabled',spec[1]?'true':'false');
    button.style.opacity=spec[1]?'.5':'';
    button.style.cursor=spec[1]?'not-allowed':'';
  });
  nav.style.display='flex';
}
async function evGoToPage(n){
  if(n<1||n>evPages||n===evPage)return;
  evPage=n;
  await loadEvidence();
  var list=document.getElementById(evViewMode==='table'?'evidenceTable':'evidenceGrid');
  if(list)list.scrollIntoView({block:'start'});
}
function evStateChip(state){
  if(!state)return '';
  return '<span class="ev-chip ev-chip-'+(evKnown(evStateKind,state.key,null)||'muted')+'">'+escHtml(state.label)+'</span>';
}
function evSafeInternalUrl(value){
  if(typeof value!=='string'||!value)return '';
  try{
    var url=new URL(value,window.location.origin);
    if(url.origin!==window.location.origin||url.username||url.password)return '';
    if(!['http:','https:'].includes(url.protocol))return '';
    return url.pathname+url.search+url.hash;
  }catch(_){return '';}
}
function evClaimsHtml(item){
  var parts=(item.claims||[]).map(function(c){
    var url=evSafeInternalUrl(c.url);
    return url?'<a href="'+escHtml(url)+'">'+escHtml(c.title)+'</a>':escHtml(c.title);
  });
  var rest=(item.claims_more||0);
  var hidden=(item.claims_hidden||0);
  if(!parts.length&&!hidden)return '<span data-s="s57f9e31">None yet</span>';
  var out=parts.join(', ');
  if(rest)out+=(out?' and ':'')+rest+' more';
  if(hidden)out+=(out?', ':'')+hidden+' you cannot open';
  return '<span class="ev-claims">'+out+'</span>';
}
function evActiveChips(){
  var chips=[];
  var labels={needs_filing:'Needs filing',unlinked:'Needs filing',for_review:'Waiting for review',review_due:'Review due',recent:'Recently updated',expiring:'Expiring soon',archived:'Archived',superseded:'Replaced versions',generated_history:'Previous generated copies'};
  if(currentView&&currentView!=='all')chips.push([labels[currentView]||currentView,function(){switchView('all',document.getElementById('nav-all'));}]);
  if(currentModule)chips.push(['Module: '+currentModule.toUpperCase(),function(){currentModule='';evPage=1;loadEvidence();}]);
  if(evFolder)chips.push(['Folder: '+evFolder.replace(/:/g,' / '),function(){evChooseFolder('');}]);
  if(currentCategory)chips.push(['Type: '+currentCategory,function(){currentCategory='';evPage=1;loadEvidence();}]);
  if(evOwnerOnly)chips.push(['Mine',function(){evOwnerOnly=false;evPage=1;loadEvidence();}]);
  if(currentState)chips.push(['State: '+currentState.replace(/_/g,' '),function(){currentState='';evPage=1;loadEvidence();}]);
  if(currentWords)chips.push(['Words: '+currentWords,function(){currentWords='';evPage=1;loadEvidence();}]);
  if(evCompanyScope)chips.push(['Filing scope: '+evCompanyLabel(evCompanyScope),function(){evChooseCompany('');}]);
  if(evEntityScope)chips.push(['Company: '+evEntityLabel(evEntityScope),function(){evEntityScope='';evPage=1;evRenderEntityViews();loadEvidence();}]);
  if(currentStatus)chips.push(['Status: '+currentStatus,function(){currentStatus='';evPage=1;loadEvidence();}]);
  var q=document.getElementById('searchInput').value;
  if(q)chips.push(['Search: '+q,function(){document.getElementById('searchInput').value='';evPage=1;loadEvidence();}]);
  // The work view counts are for the whole library: hide them while a filter narrows the list, the pager gives its total
  var narrowed=chips.length>((currentView&&currentView!=='all')?1:0);
  document.getElementById('evWork').classList.toggle('ev-narrowed',narrowed);
  var box=document.getElementById('evChips');
  box.innerHTML='';
  chips.forEach(function(c){
    var b=document.createElement('button');
    b.type='button';b.className='ev-chip';b.style.cursor='pointer';b.style.background='var(--surface2)';
    b.textContent=c[0]+' ×';
    b.setAttribute('aria-label','Remove filter: '+c[0]);
    b.addEventListener('click',c[1]);
    box.appendChild(b);
  });
  if(chips.length>1){
    var all=document.createElement('button');
    all.type='button';all.className='btn btn-secondary';all.style.fontSize='12px';all.textContent='Clear filters';
    all.addEventListener('click',function(){evClearFilters();switchView('all',document.getElementById('nav-all'));});
    box.appendChild(all);
  }
}
// Every filter except the work view, so that a count of the whole library and the list it opens agree
function evClearFilters(){
  currentModule='';currentCategory='';currentStatus='';evOwnerOnly=false;currentState='';currentWords='';
  evFolder='';evCompanyScope='';evEntityScope='';
  if(evCompanyViews)evRenderCompanyViews();
  if(evEntityViews)evRenderEntityViews();
  evCloseRecordFolders();
  document.getElementById('searchInput').value='';
}
function evEntityLabel(id){
  if(id==='unconfirmed')return 'Ownership unconfirmed';
  var found=evEntityViews&&(evEntityViews.companies||[]).find(function(item){return String(item.id)===id;});
  return found?found.name:'Selected company';
}
function evTextMatchHtml(item){
  if(!item.text_match)return '';
  return '<div data-s="sb90743c">'+
    '<strong>'+escHtml(item.text_match.label)+'</strong> · '+escHtml(item.text_match.text)+'</div>';
}
async function loadEvidence(){
  var loadSeq=++evLoadSeq;
  var params=new URLSearchParams();
  if(currentCategory)params.set('category',currentCategory);
  if(currentStatus)params.set('status',currentStatus);
  if(currentModule)params.set('module',currentModule);
  if(evFolder)params.set('folder',evFolder);
  if(evCompanyScope)params.set('filing_scope',evCompanyScope);
  if(evEntityScope)params.set('company',evEntityScope);
  if(currentView&&currentView!=='all')params.set('view',currentView);
  if(evOwnerOnly)params.set('owner','me');
  if(currentState)params.set('state',currentState);
  if(currentWords)params.set('words',currentWords);
  var q=document.getElementById('searchInput').value;
  if(q)params.set('q',q);
  params.set('page',evPage);
  evActiveChips();
  var r=await fetch('/evidence/api/items?'+params.toString());
  var data=await r.json();
  if(loadSeq!==evLoadSeq)return;
  if(!data||!Array.isArray(data.items)){
    if(typeof showToast==='function')showToast('Could not load evidence.','error');
    return;
  }
  var items=data.items;
  evRenderPager(data);
  evSelectedIds.clear();
  evVisibleIds=items.filter(function(item){return item.status!=='archived';}).map(function(item){return Number(item.id);});
  evUpdateSelection();
  var grid=document.getElementById('evidenceGrid');
  var tbl=document.getElementById('evidenceTable');
  var body=document.getElementById('evidenceTableBody');
  var empty=document.getElementById('emptyState');
  if(!items.length){
    grid.innerHTML='';body.innerHTML='';tbl.style.display='none';empty.style.display='block';
    var et=document.getElementById('emptyTitle'),es=document.getElementById('emptySub');
    if(currentView==='expiring'){et.textContent='No expiring evidence';es.textContent='No items expire within the next 30 days.';}
    else if(currentView==='unlinked'||currentView==='needs_filing'){et.textContent='Nothing needs filing';es.textContent='Every current item supports at least one record.';}
    else if(currentView==='for_review'){et.textContent='Nothing is waiting for your review';es.textContent='Links that you did not attach, and that nobody has reviewed, appear here.';}
    else if(currentView==='review_due'){et.textContent='No review is due';es.textContent='No item has a review date in the next 30 days.';}
    else if(currentView==='recent'){et.textContent='Nothing changed recently';es.textContent='Items updated in the last 14 days appear here.';}
    else if(currentView==='archived'){et.textContent='Archive is empty';es.textContent='No archived evidence items.';}
    else if(currentView==='generated_history'){et.textContent='No previous generated copies';es.textContent='When a generated record changes, its previous two versions appear here.';}
    else if(q||currentModule||currentCategory||evOwnerOnly||currentState||currentWords){et.textContent='No evidence matches these filters';es.textContent='Clear a filter above to widen the list.';}
    else{et.textContent='No evidence items found';es.textContent='Upload files or drag & drop here to start';}
    return;
  }
  empty.style.display='none';
  if(evViewMode==='table'){
    grid.style.display='none';tbl.style.display='block';
    body.innerHTML=items.map(function(item){
      var icon=evKnown(iconMap,item.category,null)||'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-file-text></use></svg>';
      var source=item.file_name?escHtml(item.file_name):'<span data-s="s57f9e31">System record, no file</span>';
      var owner=item.owner_name?escHtml(item.owner_name):'<span data-s="s57f9e31">No owner</span>';
      var due=item.review_due_date?fmtDate(item.review_due_date)+(item.review_due?' <span class="ev-chip ev-chip-warn">due</span>':''):'<span data-s="s57f9e31">Not set</span>';
      var expiry=expiryBadgeHtml(item.expiry_date);
      return '<tr data-ev-dynamic="openDetail('+Number(item.id)+')" data-s="s3b6a3a6">'+
        (evSelectionMode&&evCanBulkArchive?'<td data-ev-dynamic="event.stopPropagation()">'+
          (item.status==='archived'?'': '<input type="checkbox" class="ev-row-select" value="'+Number(item.id)+'" aria-label="Select '+escHtml(item.title)+'">')+'</td>':'')+
        '<td><div data-s="s250fc4e" data-sd="flex"><span aria-hidden="true">'+icon+'</span>'+
          '<div data-s="s3922d32"><div data-s="s53be917" title="'+escHtml(item.title)+'">'+escHtml(item.title)+'</div>'+
          '<div data-s="sb569cab">'+source+' · v'+escHtml(String(item.version||1))+'</div>'+evTextMatchHtml(item)+'</div></div></td>'+
        '<td data-ev-dynamic="event.stopPropagation()">'+evClaimsHtml(item)+'</td>'+
        '<td>'+owner+'</td>'+
        '<td>'+due+'</td>'+
        '<td>'+evStateChip(item.state)+(expiry?' '+expiry:'')+'</td>'+
        '<td data-s="s86abdab">'+fmtDate(item.updated_at)+'</td>'+
        '<td data-ev-dynamic="event.stopPropagation()">'+
          (item.file_path&&item.file_size?'<button data-ev-dynamic="evDownload('+Number(item.id)+',false)" data-s="sf0b24a9" title="Download" aria-label="Download '+escHtml(item.title)+'">&#11015;</button>':'')+
        '</td>'+
      '</tr>';
    }).join('');
  } else {
    tbl.style.display='none';grid.style.display='grid';
    grid.innerHTML=items.map(function(item){
      var icon=evKnown(iconMap,item.category,null)||'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-file-text></use></svg>';
      return '<button type="button" class="card" data-s="sc2babfc" data-sd="block" data-ev-dynamic="openDetail('+Number(item.id)+')">'+
        '<div data-s="s4fb60c8" data-sd="flex">'+
          '<span data-s="sa2600b0">'+icon+'</span>'+
          '<div data-s="s59eddc6">'+
            '<div data-s="s7f569b2">'+escHtml(item.title)+'</div>'+
            '<div data-s="s8a05498">'+escHtml(item.file_name||'No file')+' · '+fmtSize(item.file_size)+'</div>'+evTextMatchHtml(item)+
            '<div data-s="s04c34c1" data-sd="flex">'+
              '<span data-s="sfefb16a">'+escHtml(item.category)+'</span>'+
              evStateChip(item.state)+expiryBadgeHtml(item.expiry_date)+
            '</div>'+
          '</div>'+
        '</div></button>';
    }).join('');
  }
}

function evUpdateSelection(){
  if(!evCanBulkArchive)return;
  var count=document.getElementById('evSelectedCount');
  var bar=document.getElementById('evBulkBar');
  var button=document.getElementById('evSelectModeBtn');
  var heading=document.getElementById('evSelectHeading');
  var archive=document.getElementById('evBulkArchiveBtn');
  count.textContent=evSelectedIds.size+' selected';
  bar.style.display=evSelectionMode?'flex':'none';
  button.style.display=evSelectionMode?'none':'';
  heading.style.display=evSelectionMode?'':'none';
  archive.disabled=evSelectedIds.size===0;
  var all=document.getElementById('evSelectAll');
  all.checked=evVisibleIds.length>0&&evVisibleIds.every(function(id){return evSelectedIds.has(id);});
  all.indeterminate=evSelectedIds.size>0&&!all.checked;
}
function evToggleSelection(){
  if(!evCanBulkArchive)return;
  evSelectionMode=!evSelectionMode;
  evSelectedIds.clear();
  if(evSelectionMode){setViewMode('table');}
  else{evUpdateSelection();loadEvidence();}
}
document.addEventListener('change',function(event){
  if(!evSelectionMode)return;
  if(event.target.id==='evSelectAll'){
    evVisibleIds.forEach(function(id){
      if(event.target.checked)evSelectedIds.add(id);
      else evSelectedIds.delete(id);
    });
    document.querySelectorAll('.ev-row-select').forEach(function(input){
      input.checked=event.target.checked;
    });
  }else if(event.target.matches('.ev-row-select')){
    var id=Number(event.target.value);
    if(event.target.checked)evSelectedIds.add(id);
    else evSelectedIds.delete(id);
  }else{return;}
  evUpdateSelection();
});
async function evBulkArchive(){
  if(!evCanBulkArchive||!evSelectedIds.size)return;
  var ids=Array.from(evSelectedIds);
  if(!confirm('Archive '+ids.length+' selected evidence item'+(ids.length===1?'':'s')+
    '? Linked evidence will be archived with each item.'))return;
  var button=document.getElementById('evBulkArchiveBtn');
  var resultEl=document.getElementById('evBulkResult');
  button.disabled=true;
  try{
    var key=(window.crypto&&crypto.randomUUID)?crypto.randomUUID():
      String(Date.now())+'-'+Math.random();
    var result=await ApiClient.request('/evidence/api/items/bulk-archive',{
      method:'PUT',body:{ids:ids},idempotencyKey:key,actionId:'evidence.bulk_archive'
    });
    var skipped=result.skipped||[];
    resultEl.textContent=(result.applied||[]).length+' archived. '+
      (skipped.length?skipped.length+' skipped: '+
        skipped.map(function(row){return '#'+row.id+' '+row.reason;}).join('; '):'');
    evSelectedIds.clear();
    await loadEvidence();
    if(typeof loadStats==='function')loadStats();
  }catch(error){
    resultEl.textContent=error.detail||'Bulk archive failed. Please retry.';
    evUpdateSelection();
  }
}
async function evLoadSavedViews(){
  var select=document.getElementById('evSavedViews');
  var current=select.value;
  try{
    var data=await ApiClient.request('/api/saved-views?module=evidence&view_key=items_list');
    evSavedViews=data.views||[];
    select.innerHTML='<option value="">Choose a saved view</option>'+
      evSavedViews.map(function(view){
        return '<option value="'+Number(view.id)+'">'+escHtml(view.name)+
          (view.shared?' (shared)':'')+'</option>';
      }).join('');
    if(evSavedViews.some(function(view){return String(view.id)===current;}))select.value=current;
    evUpdateViewDelete();
  }catch(error){
    document.getElementById('evSavedViewStatus').textContent=
      error.detail||'Saved views could not be loaded.';
  }
}
function evUpdateViewDelete(){
  var chosen=Number(document.getElementById('evSavedViews').value);
  var view=evSavedViews.find(function(v){return Number(v.id)===chosen;});
  document.getElementById('evDeleteViewBtn').disabled=!view||Number(view.owner_user_id)!==Number(evUserId);
}
function evApplySavedView(rawId){
  evUpdateViewDelete();
  var view=evSavedViews.find(function(v){return Number(v.id)===Number(rawId);});
  if(!view)return;
  var filters=view.filter_params||{};
  currentCategory=filters.category||'';
  currentModule=filters.module||'';
  currentStatus=filters.status||'';
  evFolder=filters.folder||'';
  var requestedScope=filters.filing_scope||'';
  evCompanyScope=requestedScope;
  evEntityScope=filters.company||'';
  evRenderCompanyViews();
  evRenderEntityViews();
  evCloseRecordFolders();
  evMarkFolder();
  currentView=filters.view||'all';
  evPage=1;
  document.getElementById('searchInput').value=filters.q||'';
  document.querySelectorAll('.nav-item').forEach(function(node){node.classList.remove('active');});
  var nav=document.getElementById('nav-'+currentView);
  if(nav)nav.classList.add('active');
  document.querySelectorAll('#evWork [data-view]').forEach(function(tab){
    var on=tab.getAttribute('data-view')===(currentView==='unlinked'?'needs_filing':currentView);
    tab.classList.toggle('is-current',on);
    tab.setAttribute('aria-pressed',on?'true':'false');
  });
  loadEvidence();
}
async function evSaveCurrentView(){
  var name=window.prompt('Name this saved view');
  if(!name||!name.trim())return;
  var filters={};
  if(currentCategory)filters.category=currentCategory;
  if(currentModule)filters.module=currentModule;
  if(evFolder)filters.folder=evFolder;
  if(evCompanyScope)filters.filing_scope=evCompanyScope;
  if(evEntityScope)filters.company=evEntityScope;
  if(currentStatus)filters.status=currentStatus;
  if(currentView!=='all')filters.view=currentView;
  var query=document.getElementById('searchInput').value;
  if(query)filters.q=query;
  try{
    var result=await ApiClient.request('/api/saved-views',{
      method:'POST',actionId:'evidence.saved_view.create',
      body:{module:'evidence',view_key:'items_list',name:name.trim(),filter_params:filters}
    });
    await evLoadSavedViews();
    document.getElementById('evSavedViews').value=String(result.view.id);
    evUpdateViewDelete();
    document.getElementById('evSavedViewStatus').textContent='View saved.';
  }catch(error){
    document.getElementById('evSavedViewStatus').textContent=error.detail||'Could not save view.';
  }
}
async function evDeleteSavedView(){
  var id=Number(document.getElementById('evSavedViews').value);
  var view=evSavedViews.find(function(v){return Number(v.id)===id;});
  if(!view||Number(view.owner_user_id)!==Number(evUserId))return;
  if(!confirm('Delete saved view "'+view.name+'"?'))return;
  try{
    await ApiClient.request('/api/saved-views/'+id,{method:'DELETE',actionId:'evidence.saved_view.delete'});
    document.getElementById('evSavedViews').value='';
    await evLoadSavedViews();
    document.getElementById('evSavedViewStatus').textContent='View deleted.';
  }catch(error){
    document.getElementById('evSavedViewStatus').textContent=error.detail||'Could not delete view.';
  }
}
function setViewMode(mode){
  if(mode==='cards' && evSelectionMode){
    evSelectionMode=false;evSelectedIds.clear();evUpdateSelection();
  }
  evViewMode=mode;
  localStorage.setItem('ev-view-mode',mode);
  var bc=document.getElementById('btnCards'),bt=document.getElementById('btnTable');
  if(mode==='cards'){bc.style.background='var(--accent)';bc.style.color='#fff';bt.style.background='var(--surface2)';bt.style.color='var(--muted)';}
  else{bt.style.background='var(--accent)';bt.style.color='#fff';bc.style.background='var(--surface2)';bc.style.color='var(--muted)';}
  loadEvidence();
}

/* ── Detail Panel ── */
var _detailEid=null;
function isDocxMime(m){return(m||'').indexOf('wordprocessingml')!==-1||(m||'')==='application/msword';}
function isOfficeMime(m){return isDocxMime(m)||(m||'').indexOf('spreadsheetml')!==-1||(m||'').indexOf('presentationml')!==-1||(m||'').indexOf('ms-excel')!==-1||(m||'').indexOf('ms-powerpoint')!==-1;}
function isImageMime(m){return(m||'').startsWith('image/');}
function isPdfMime(m){return(m||'')==='application/pdf';}

async function evDownload(eid,asPdf){
  var url='/evidence/api/items/'+eid+'/'+(asPdf?'download-pdf':'download');
  try{
    var res=await fetch(url);
    if(!res.ok){
      var errData;
      try{errData=await res.json();}catch(e){errData=null;}
      var msg=errData&&errData.detail?errData.detail:'Download failed ('+res.status+')';
      if(typeof showToast==='function')showToast(msg,'error');
      return;
    }
    var cd=res.headers.get('Content-Disposition')||'';
    var match=cd.match(/filename="?([^"]+)"?/);
    var filename=match?match[1]:(asPdf?'evidence.pdf':'evidence');
    var blob=await res.blob();
    var a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download=filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function(){URL.revokeObjectURL(a.href);},5000);
    if(typeof showToast==='function')showToast('Downloaded '+ filename);
  }catch(e){
    if(typeof showToast==='function')showToast('Download error: '+e.message,'error');
  }
}

function _resolvedLinksHtml(links,resolved,eid,item){
  if(!links.length) return '<div data-s="s9b0e5b9">No linked entities. Use "Link to..." or "AI Suggest" to connect this evidence.</div>';
  var canReview=!!(item&&item.can_review_links&&item.status==='current');
  var dark=document.documentElement.getAttribute('data-theme')==='dark';
  var tone=dark?{pending:'#fbbf24',accepted:'#4ade80',returned:'#f87171',rejected:'#f87171',out_of_scope:'var(--muted)'}
               :{pending:'#92400e',accepted:'#15803d',returned:'#b91c1c',rejected:'#b91c1c',out_of_scope:'var(--muted)'};
  return links.map(function(l,i){
    var res=resolved[i]||{};
    var mc=evKnown(modColors,l.module,null)||'#6b7280';
    var status=l.review_status||'pending';
    var who=l.reviewed_by_name?('by '+l.reviewed_by_name+(l.reviewed_at?' on '+fmtDate(l.reviewed_at):'')):'';
    var hint=[l.review_note,who].filter(Boolean).join(' · ');
    var safeUrl=evSafeInternalUrl(res.url);
    var seen=!!(safeUrl||res.name);
    var mine=Number(l.linked_by)===Number(evUserId)||(item&&Number(item.uploaded_by)===Number(evUserId));
    var name=res.name||('#'+l.entity_id);
    return '<div class="ev-link-row" data-s="s62da067">'+
      '<span class="ev-mod-dot" data-sv="background:'+mc+'"></span>'+
      '<span data-s="sbac6e51">'+escHtml(l.module)+'</span>'+
      '<span data-s="sb569cab">'+escHtml(l.entity_type)+'</span>'+
      (safeUrl?'<a href="'+escHtml(safeUrl)+'" data-s="s09ab059">'+escHtml(name)+'</a>':
               '<span data-s="se228898">'+escHtml(name)+'</span>')+
      '<span class="ev-review-chip" data-sv="color:'+(tone[status]||'var(--muted)')+';border-color:'+(tone[status]||'var(--border)')+'" title="'+escHtml(hint)+'">'+escHtml(l.review_label||'Waiting for a reviewer')+'</span>'+
      (l.carried_from_link_id?'<span class="ev-review-chip" data-s="s3daaefb" title="Proposed from the version this one replaced. It needs its own review.">Carried forward</span>':'')+
      (canReview&&seen&&!mine?'<button type="button" class="btn btn-secondary" data-s="se2b3d6e" data-ev-action="review-link" data-link-id="'+Number(l.id)+'" data-evidence-id="'+Number(eid)+'" data-status="'+escHtml(status)+'" data-name="'+escHtml(name)+'" aria-label="Review the link to '+escHtml(name)+'">Review</button>':'')+
      (canReview&&seen&&mine?'<span class="ev-review-chip" data-s="s3daaefb" title="The person who attached the file or made the link cannot review it.">Needs another reviewer</span>':'')+
      '<span data-s="sbff04ca">'+fmtDate(l.created_at)+'</span>'+
      '<button data-ev-dynamic="unlinkEvidence('+Number(l.id)+','+Number(eid)+')" data-s="scc32ab4" title="Unlink" aria-label="Unlink '+escHtml(name)+'">✕</button>'+
      (hint?'<div data-s="s28314ea">'+escHtml(hint)+'</div>':'')+
    '</div>';
  }).join('');
}

async function openDetail(eid){
  _detailEid=eid;
  var r=await fetch('/evidence/api/items/'+eid);var item=await r.json();
  if(!item||item.error){return;}
  if(window.ThemisSelectRecord)window.ThemisSelectRecord('/evidence/?open=item:'+eid);
  evDetailItem=item;
  var icon=evKnown(iconMap,item.category,null)||'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-file-text></use></svg>';
  var tags=(item.tags||'').split(',').filter(function(t){return t.trim();});
  var links=item.links||[];
  var mime=(item.mime_type||'').toLowerCase();
  var canPdf=isOfficeMime(mime);
  var textState=item.text_index&&item.text_index.status;
  var textStateLabel={indexed:'Searchable text ready',empty:'No readable text found',
    pending:'Searchable text is being prepared',disabled:'File text indexing is not enabled',
    unsupported:'File text is not indexed',
    not_applicable:'No attached file to index',
    failed:'Text indexing could not finish; metadata search still works'};

  var html='<div class="ev-section" data-s="s13c1049" data-sd="flex">'+
    '<div><div data-s="sf764568">'+icon+' '+escHtml(item.title)+'</div>'+
    '<div data-s="sd14d7bf">'+escHtml(item.file_name||'')+' · '+fmtSize(item.file_size)+' · v'+escHtml(String(item.version||1))+'</div>'+
    '<div data-s="s8a77e5a">'+evStateChip(item.state)+'</div>'+
    '<div data-s="s5c3809d">'+escHtml(textStateLabel[textState]||'Text search unavailable')+'</div></div>'+
    '<button data-ev-dynamic="closeDetail()" data-s="s34a8942">✕</button></div>';

  /* Actions */
  var hasFile=!!(item.file_path&&item.file_size&&item.file_size>0);
  var isAriaLinked=links.some(function(l){return l.module==='aria'&&l.entity_type==='document';});
  var canDownload=hasFile||isAriaLinked;
  html+='<div class="ev-section" data-s="s4725bb7" data-sd="flex">';
  if(canDownload){
    html+='<button class="btn btn-primary" data-s="s2cbaf86" data-ev-dynamic="evDownload('+eid+',false)">Download original</button>';
    if(canPdf||isAriaLinked)html+='<button class="btn btn-secondary" data-s="s2cbaf86" data-ev-dynamic="evDownload('+eid+',true)">Download PDF</button>';
    if(hasFile){
      html+='<button class="btn btn-secondary" data-s="s2cbaf86" data-ev-dynamic="verifyIntegrity('+eid+')">Verify Integrity</button>';
    }
  } else {
    html+='<span data-s="s2442599">Auto-generated record, no file attached</span>';
  }
  if(item.status!=='archived'){
    html+='<button class="btn btn-secondary" data-s="s459ca32" data-ev-dynamic="openLinkToModal('+eid+')">Link to...</button>';
  }
  if(item.status==='current'&&hasFile){
    html+='<button class="btn btn-secondary" data-s="s2cbaf86" data-ev-dynamic="evAddVersion('+eid+')">Add a new version</button>';
  }
  if(item.can_delete){
    if(item.status==='archived'){
      html+='<button class="btn btn-secondary" data-s="s9c673eb" data-ev-dynamic="restoreEvidence('+eid+')">Restore</button>';
      html+='<button class="btn btn-secondary" data-s="s598a82b" data-ev-dynamic="permanentDeleteEvidence('+eid+')">Delete Permanently</button>';
    } else {
      html+='<button class="btn btn-secondary" data-s="sc68578f" data-ev-dynamic="archiveEvidence('+eid+')">Archive</button>';
    }
  }
  html+='</div>';
  html+='<div id="integrityResult"></div>';

  /* Preview for images */
  if(isImageMime(mime)){
    html+='<div class="ev-section" data-s="sbc32449">'+
      '<img src="/evidence/api/items/'+eid+'/download" data-s="s53637c0" alt="Preview">'+
    '</div>';
  }

  /* Tabs: Details / History / Activity */
  html+='<div class="ev-tabs" role="tablist">'+
    '<button type="button" class="ev-tab active" role="tab" aria-selected="true" aria-controls="tabpane-details" id="tab-details" data-ev-dynamic="evShowTab(\'details\')">Details</button>'+
    '<button type="button" class="ev-tab" role="tab" aria-selected="false" aria-controls="tabpane-history" id="tab-history" data-ev-dynamic="evShowTab(\'history\')">Versions</button>'+
    '<button type="button" class="ev-tab" role="tab" aria-selected="false" aria-controls="tabpane-activity" id="tab-activity" data-ev-dynamic="evShowTab(\'activity\')">Activity</button>'+
  '</div>';

  /* Details tab */
  html+='<div id="tabpane-details" role="tabpanel" aria-labelledby="tab-details">';
  html+='<div id="evChecksItem"></div>';
  html+='<div id="evSourceRetention"></div>';

  /* Inline-editable metadata */
  var statusOpts=['current','superseded','archived','expired','draft'].map(function(s){
    return '<option value="'+s+'"'+(s===item.status?' selected':'')+'>'+s+'</option>';
  }).join('');
  var catOpts=['general','policy','certificate','screenshot','report','procedure','training'].map(function(c){
    return '<option value="'+c+'"'+(c===item.category?' selected':'')+'>'+c+'</option>';
  }).join('');

  html+='<div class="ev-section"><div class="ev-section-title">Details</div>'+
    '<div data-s="sbdd971f" data-sd="grid">'+
      '<span data-s="s57f9e31">Title</span>'+
      '<div class="ev-editable" id="ev-field-title">'+
        '<span class="ev-field-val" data-s="sf045bbe">'+escHtml(item.title)+'</span>'+
        '<button class="ev-edit-btn" aria-label="Edit title" data-ev-dynamic="evInlineEdit(\'title\','+eid+',this)"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button>'+
      '</div>'+
      '<span data-s="s57f9e31">Category</span>'+
      '<div class="ev-editable" id="ev-field-category">'+
        '<span class="ev-field-val" data-s="sf045bbe">'+escHtml(item.category)+'</span>'+
        '<button class="ev-edit-btn" aria-label="Edit category" data-ev-action="inline-select" data-field="category" data-evidence-id="'+Number(eid)+'"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button>'+
      '</div>'+
      '<span data-s="s57f9e31">Status</span>'+
      '<div class="ev-editable" id="ev-field-status">'+
        '<span class="ev-field-val" data-s="sf045bbe">'+escHtml(item.status)+'</span>'+
        '<button class="ev-edit-btn" aria-label="Edit status" data-ev-action="inline-select" data-field="status" data-evidence-id="'+Number(eid)+'"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button>'+
      '</div>'+
      '<span data-s="s57f9e31">Owner</span>'+
      '<div class="ev-editable" id="ev-field-owner_user_id"><span class="ev-field-val" data-s="sf045bbe">'+escHtml(item.owner_name||'No owner')+'</span>'+
        '<button class="ev-edit-btn" data-s="sc6e7979" aria-label="Change the owner" data-ev-dynamic="evInlineOwner('+eid+')"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button></div>'+
      '<span data-s="s57f9e31">Uploaded by</span><span data-s="sf045bbe">'+escHtml(item.uploaded_by_name||'Unknown')+'</span>'+
      '<span data-s="s57f9e31">Created</span><span data-s="sf045bbe">'+fmtDate(item.created_at)+'</span>'+
      '<span data-s="s57f9e31">Expiry</span>'+
      '<div class="ev-editable" id="ev-field-expiry_date">'+
        '<span class="ev-field-val" data-sv="color:'+(item.expiry_date?'var(--warn,#d97706)':'var(--muted)')+'">'+
          (item.expiry_date?fmtDate(item.expiry_date)+' '+expiryBadgeHtml(item.expiry_date):'Not set')+
        '</span>'+
        '<button class="ev-edit-btn" aria-label="Edit expiry date" data-ev-dynamic="evInlineEdit(\'expiry_date\','+eid+',this)" data-s="sc6e7979"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button>'+
      '</div>'+
      '<span data-s="s57f9e31">Review due</span>'+
      '<div class="ev-editable" id="ev-field-review_due_date"><span class="ev-field-val" data-s="sf045bbe">'+(item.review_due_date?fmtDate(item.review_due_date):'Not set')+'</span>'+
        '<button class="ev-edit-btn" data-s="sc6e7979" aria-label="Change the review date" data-ev-dynamic="evInlineEdit(\'review_due_date\','+eid+',this)"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button></div>'+
      '<span data-s="s57f9e31">Period from</span>'+
      '<div class="ev-editable" id="ev-field-period_start"><span class="ev-field-val" data-s="sf045bbe">'+(item.period_start?fmtDate(item.period_start):'Not set')+'</span>'+
        '<button class="ev-edit-btn" data-s="sc6e7979" aria-label="Change the start of the period" data-ev-dynamic="evInlineEdit(\'period_start\','+eid+',this)"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button></div>'+
      '<span data-s="s57f9e31">Period to</span>'+
      '<div class="ev-editable" id="ev-field-period_end"><span class="ev-field-val" data-s="sf045bbe">'+(item.period_end?fmtDate(item.period_end):'Not set')+'</span>'+
        '<button class="ev-edit-btn" data-s="sc6e7979" aria-label="Change the end of the period" data-ev-dynamic="evInlineEdit(\'period_end\','+eid+',this)"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button></div>'+
      (item.file_hash?'<span data-s="s57f9e31">SHA-256</span><span data-s="s0194446">'+escHtml(item.file_hash)+'</span>':'')+
    '</div></div>';

  /* Confidence Score + Verification */
  var confScore=item.confidence_score!=null&&Number.isFinite(Number(item.confidence_score))?
    Math.max(0,Math.min(100,Number(item.confidence_score))):null;
  var confColor=confScore!=null?(confScore>=80?'#16a34a':confScore>=50?'#d97706':'#dc2626'):'#94a3b8';
  var verifyLabel=item.verification_method?(_VERIFY_LABELS[item.verification_method]||item.verification_method):'Not verified';
  html+='<div class="ev-section"><div class="ev-section-title" data-s="sc5879fc" data-sd="flex">Metadata health'+
    (confScore!=null?'<span data-sv="font-size:20px;font-weight:800;color:'+confColor+'">'+confScore+'%</span>':'<span data-s="s7fc448e">Not scored</span>')+
  '</div>'+
  '<div data-s="sbdd971f" data-sd="grid">'+
    '<span data-s="s57f9e31">Verification</span>'+
    '<span data-s="sf045bbe">'+escHtml(verifyLabel)+(item.verified_at?' · <span data-s="s57f9e31">'+fmtDate(item.verified_at)+'</span>':'')+'</span>'+
  '</div>'+
  '<p data-s="sf965e87">How complete the file\'s own details are: a method, an expiry, links and a hash. It does not say the file proves anything; only a reviewer\'s verdict on a link does.</p>'+
  '<div data-s="s902fc60" data-sd="flex">'+
    Object.keys(_VERIFY_LABELS).map(function(m){
      var active=item.verification_method===m;
      return '<button data-ev-dynamic="doSetVerification('+eid+',\''+m+'\')" data-sv="padding:4px 10px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;border:1px solid '+(active?'var(--accent)':'var(--border)')+';background:'+(active?'var(--accent)':'var(--surface)')+';color:'+(active?'#fff':'var(--text)')+'">'+escHtml(_VERIFY_LABELS[m])+'</button>';
    }).join('')+
    (item.verification_method?'<button data-ev-dynamic="doRemoveVerification('+eid+')" data-s="sa77fe97">Remove</button>':'')+
  '</div></div>';

  /* Tags -- editable */
  html+='<div class="ev-section"><div class="ev-section-title" data-s="sa562f4f" data-sd="flex">Tags '+
    '<button class="ev-edit-btn" data-s="s54a5520" data-ev-dynamic="evEditTags('+eid+')"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg> edit</button></div>'+
    '<div id="ev-tags-display">'+(tags.length?tags.map(function(t){return '<span class="ev-tag">'+escHtml(t.trim())+'</span>';}).join(''):'<span data-s="s7fc448e">No tags</span>')+'</div>'+
    '<div id="ev-tags-editor" data-sd="none">'+
      '<input class="ev-inline-input" type="text" id="ev-input-tags" value="'+escHtml(item.tags||'')+'" placeholder="tag1, tag2, tag3">'+
      '<div data-s="s507a1e3" data-sd="flex">'+
        '<button data-ev-dynamic="evSaveField(\'tags\','+eid+',document.getElementById(\'ev-input-tags\').value)" data-s="s7aded7e">Save</button>'+
        '<button data-ev-dynamic="document.getElementById(\'ev-tags-editor\').style.display=\'none\';document.getElementById(\'ev-tags-display\').style.display=\'block\'" data-s="s8b822a8">✕</button>'+
      '</div>'+
    '</div>'+
  '</div>';

  /* Description -- editable */
  html+='<div class="ev-section"><div class="ev-section-title" data-s="sa562f4f" data-sd="flex">Description '+
    '<button class="ev-edit-btn" data-s="s54a5520" data-ev-dynamic="evEditDesc('+eid+')"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg> edit</button></div>'+
    '<div id="ev-desc-display">'+(item.description?'<div data-s="se2aab8d">'+escHtml(item.description)+'</div>':'<span data-s="s7fc448e">No description</span>')+'</div>'+
    '<div id="ev-desc-editor" data-sd="none">'+
      '<textarea class="ev-inline-input" id="ev-input-description" rows="4" data-s="s9d0af0f">'+escHtml(item.description||'')+'</textarea>'+
      '<div data-s="s507a1e3" data-sd="flex">'+
        '<button data-ev-dynamic="evSaveField(\'description\','+eid+',document.getElementById(\'ev-input-description\').value)" data-s="s7aded7e">Save</button>'+
        '<button data-ev-dynamic="document.getElementById(\'ev-desc-editor\').style.display=\'none\';document.getElementById(\'ev-desc-display\').style.display=\'block\'" data-s="s8b822a8">✕</button>'+
      '</div>'+
    '</div>'+
  '</div>';

  /* Linked Entities */
  html+='<div class="ev-section"><div class="ev-section-title" data-s="s2d7d272" data-sd="flex">Linked Entities ('+links.length+') <button data-ev-dynamic="aiSuggestLinks('+eid+')" class="btn btn-secondary" data-s="s27dd323" data-sd="inline-flex"><span data-s="s5e0faad"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-sparkles></use></svg></span> AI Suggest</button></div>';
  html+='<div id="aiSuggestBox" data-s="sfdf33f2" data-sd="none"></div>';
  if(links.length){
    var specs2=links.map(function(l){return {module:l.module,entity_type:l.entity_type,entity_id:l.entity_id};});
    var resolved2=[];
    try{var rr2=await fetch('/evidence/api/resolve-links?evidence_id='+encodeURIComponent(eid)+'&links='+encodeURIComponent(JSON.stringify(specs2)));resolved2=await rr2.json();}catch(e){}
    html+=_resolvedLinksHtml(links,resolved2,eid,item);
  }else{
    html+='<div data-s="s9b0e5b9">No linked entities. Use "Link to..." or "AI Suggest" to connect this evidence.</div>';
  }
  html+='</div></div>';/* end tabpane-details */

  /* History tab */
  html+='<div id="tabpane-history" role="tabpanel" aria-labelledby="tab-history" data-sd="none">'+
    '<div class="ev-section"><div id="evVersions"><div data-s="s6629491"><div class="spinner" data-s="s5051308"></div></div></div></div>'+
    '<div class="ev-section"><div class="ev-section-title">What this version did to the earlier one\'s claims</div><div id="evImpact" data-s="s7fc448e">Loading...</div></div>'+
  '</div>';

  /* Activity tab */
  html+='<div id="tabpane-activity" role="tabpanel" aria-labelledby="tab-activity" data-sd="none">'+
    '<div class="ev-section"><div id="evActivity"><div data-s="s6629491"><div class="spinner" data-s="s5051308"></div></div></div></div>'+
  '</div>';

  document.getElementById('evDetailContent').innerHTML=html;
  document.getElementById('evDetailOverlay').classList.add('open');
  document.getElementById('evDetailPanel').classList.add('open');
  document.body.style.overflow='hidden';
  evRenderSourceRetention(item,eid);

  // Load versions async
  try{
    var vr=await fetch('/evidence/api/items/'+eid+'/versions');var vd=await vr.json();
    var vers=vd.versions||[];
    document.getElementById('evVersions').innerHTML=vers.length?vers.map(function(v){
      var versionId=Number(v.id);
      if(!Number.isSafeInteger(versionId)||versionId<=0)return '';
      var state=v.status==='current'?'Current version':v.status==='superseded'?'Replaced version':v.status;
      return '<div data-s="saac4fc2" data-sd="flex">'+
        '<span data-s="s514fa59">v'+escHtml(String(v.version||''))+'</span>'+
        '<button type="button" data-s="s47b64d9" data-ev-dynamic="openDetail('+versionId+')">'+escHtml(v.title)+'</button>'+
        '<span data-s="s57f9e31">'+fmtDate(v.created_at)+'</span>'+
        '<span class="ev-tag">'+escHtml(state)+'</span></div>';
    }).join(''):'<div data-s="s9b0e5b9">Single version, no history</div>';
  }catch(e){document.getElementById('evVersions').innerHTML='<div data-s="s7fc448e">Could not load versions</div>';}

  loadItemChecks(eid);

  // What this version did to the claims the previous one supported
  try{
    var ir=await fetch('/evidence/api/items/'+eid+'/impact');var imp=await ir.json();
    var box=document.getElementById('evImpact');
    if(!imp||imp.error){box.textContent='Could not load.';}
    else if(!imp.previous){box.textContent='This is the first version, so there is nothing it replaced.';}
    else{
      var sm=imp.summary||{};
      var line='Version '+imp.previous.version+' supported '+sm.claims+' claim'+(sm.claims===1?'':'s')+'. '+
        sm.proposed+' '+(sm.proposed===1?'was':'were')+' proposed again on this version; '+
        sm.awaiting_review+' wait'+(sm.awaiting_review===1?'s':'')+' for a reviewer'+
        (sm.accepted_again?' and '+sm.accepted_again+' already accepted':'')+
        (sm.not_carried?'. '+sm.not_carried+' stayed with the earlier version (the record could not be opened or was removed)':'')+'.';
      box.innerHTML='<p data-s="sf1a216b">'+escHtml(line)+'</p>'+
        (imp.claims.length?'<ul data-s="s592d196">'+imp.claims.map(function(c){
          var url=evSafeInternalUrl(c.url);
          return '<li>'+(url?'<a href="'+escHtml(url)+'">'+escHtml(c.title)+'</a>':escHtml(c.title))+
            ': '+escHtml(c.was_label)+' then, '+escHtml(c.now_label||'not proposed again')+' now</li>';
        }).join('')+'</ul>':'')+
        (imp.hidden?'<p data-s="sc94d43e">'+imp.hidden+' more claim'+(imp.hidden===1?'':'s')+' you cannot open.</p>':'');
    }
  }catch(e){var b2=document.getElementById('evImpact');if(b2)b2.textContent='Could not load.';}

  // Load activity async
  try{
    var ar=await fetch('/evidence/api/items/'+eid+'/audit');var arows=await ar.json();
    document.getElementById('evActivity').innerHTML=arows.length?arows.map(function(a){
      var isDeleted=!!a.deleted_at;
      var mc=evKnown(modColors,a.module,null)||'#6b7280';
      return '<div class="ev-activity-row">'+
        '<span class="ev-act-dot" data-sv="background:'+(isDeleted?'#dc2626':mc)+'"></span>'+
        '<div data-s="s97445a8">'+
          '<span data-s="seed0f8f">'+(isDeleted?'Unlinked':'Linked')+'</span>'+
          ' <span data-s="s57f9e31">'+escHtml(a.module)+'/'+escHtml(a.entity_type)+' #'+escHtml(String(a.entity_id))+'</span>'+
          '<div data-s="s54c41d6">'+
            'by '+escHtml(isDeleted?a.deleted_by_name:a.linked_by_name||'system')+' · '+fmtDate(isDeleted?a.deleted_at:a.created_at)+
          '</div>'+
        '</div>'+
      '</div>';
    }).join(''):'<div data-s="s9b0e5b9">No link activity recorded</div>';
  }catch(e){document.getElementById('evActivity').innerHTML='<div data-s="s7fc448e">Could not load activity</div>';}
}

function evShowTab(tab){
  ['details','history','activity'].forEach(function(t){
    document.getElementById('tabpane-'+t).style.display=t===tab?'block':'none';
    var btn=document.getElementById('tab-'+t);
    btn.className='ev-tab'+(t===tab?' active':'');
    btn.setAttribute('aria-selected',t===tab?'true':'false');
  });
}

function evInlineEdit(field,eid,btn){
  var container=document.getElementById('ev-field-'+field);
  if(!container)return;
  var currentVal=container.querySelector('.ev-field-val');
  var curText=currentVal?currentVal.textContent.trim():'';
  var dateFields=['expiry_date','review_due_date','period_start','period_end'];
  var isDate=dateFields.indexOf(field)>=0;
  var inputType=isDate?'date':'text';
  var inputVal=isDate?'':curText;
  if(isDate&&evDetailItem&&evDetailItem[field])inputVal=String(evDetailItem[field]).slice(0,10);
  container.innerHTML=
    '<input class="ev-inline-input" type="'+inputType+'" id="ev-input-'+field+'" value="'+escHtml(inputVal)+'" data-s="s97445a8">'+
    '<button data-ev-dynamic="evSaveField(\''+field+'\','+eid+',document.getElementById(\'ev-input-'+field+'\').value)" data-s="s4c0a3b3">Save</button>'+
    '<button data-ev-dynamic="openDetail('+eid+')" data-s="s264268d">✕</button>';
  document.getElementById('ev-input-'+field).focus();
}

function evInlineSelect(field,eid,optsHtml){
  var container=document.getElementById('ev-field-'+field);
  if(!container)return;
  container.innerHTML=
    '<select class="ev-inline-input" id="ev-input-'+field+'" data-s="s97445a8" data-ev-dynamic-change="evSaveField(\''+field+'\','+eid+',this.value)">'+optsHtml+'</select>'+
    '<button data-ev-dynamic="openDetail('+eid+')" data-s="s264268d">✕</button>';
}

async function evInlineOwner(eid){
  var container=document.getElementById('ev-field-owner_user_id');
  if(!container)return;
  var current=evDetailItem?evDetailItem.owner_user_id:null;
  container.innerHTML=
    '<div data-s="s2f2d292" data-sd="flex">'+
      '<input type="search" id="ev-owner-find" class="ev-inline-input" aria-label="Find a person by name" placeholder="Find a person" autocomplete="off" data-s="sbde8de7">'+
      '<select class="ev-inline-input" id="ev-input-owner_user_id" aria-label="Owner" data-s="s0613838" data-ev-dynamic-change="evSaveField(\'owner_user_id\','+eid+',this.value)"></select>'+
    '</div>'+
    '<button data-ev-dynamic="openDetail('+eid+')" data-s="s264268d" aria-label="Cancel">&#10005;</button>';
  var select=document.getElementById('ev-input-owner_user_id'), find=document.getElementById('ev-owner-find'), timer=null;
  // The list is the first thirty names, or the thirty that match what was typed: an organization is larger than a list.
  async function load(q){
    var people=[];
    try{var r=await fetch('/evidence/api/people'+(q?'?q='+encodeURIComponent(q):''));people=(await r.json()).items||[];}catch(e){}
    select.innerHTML='<option value="">No owner</option>'+
      people.map(function(p){return '<option value="'+Number(p.id)+'"'+(p.id===current?' selected':'')+'>'+escHtml(p.name)+'</option>';}).join('');
  }
  find.addEventListener('input',function(){clearTimeout(timer);timer=setTimeout(function(){load(find.value.trim());},250);});
  await load('');
  select.focus();
}

function evEditTags(eid){
  document.getElementById('ev-tags-display').style.display='none';
  document.getElementById('ev-tags-editor').style.display='block';
  document.getElementById('ev-input-tags').focus();
}

function evEditDesc(eid){
  document.getElementById('ev-desc-display').style.display='none';
  document.getElementById('ev-desc-editor').style.display='block';
  document.getElementById('ev-input-description').focus();
}

async function evSaveField(field,eid,val){
  var body={};body[field]=val;
  try {
    await ApiClient.request('/evidence/api/items/'+eid, { method: 'PUT', body: body, actionId: 'evidence.field.save' });
    if(typeof showToast==='function')showToast('Updated '+field);
  } catch (e) {
    if(typeof showToast==='function')showToast(e.detail || 'Update failed','error');
  }
  openDetail(eid);loadStats();loadEvidence();
}

function closeDetail(){
  document.getElementById('evDetailOverlay').classList.remove('open');
  document.getElementById('evDetailPanel').classList.remove('open');
  document.body.style.overflow='';
}

document.addEventListener('keydown',function(e){
  if(e.key==='Escape'&&document.getElementById('evDetailPanel').classList.contains('open')){
    closeDetail();
  }
});

async function verifyIntegrity(eid){
  var el=document.getElementById('integrityResult');
  el.innerHTML='<div class="ev-section" data-s="s34116c7"><span data-s="s1917f57">Verifying...</span></div>';
  var r=await fetch('/evidence/api/items/'+eid+'/verify');var d=await r.json();
  var col=d.verified?'var(--good,#16a34a)':'var(--bad,#dc2626)';
  var icon=d.verified?'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-circle-check></use></svg>':'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-circle-x></use></svg>';
  el.innerHTML='<div class="ev-section" data-sv="padding:8px 20px;background:'+(d.verified?'#dcfce722':'#fee2e222')+'"><span data-sv="color:'+col+';font-size:12px;font-weight:600">'+icon+' '+escHtml(d.message)+'</span></div>';
}

async function unlinkEvidence(linkId,eid){
  if(!confirm('Remove this link?'))return;
  try {
    await ApiClient.request('/evidence/api/links/'+linkId, { method: 'DELETE', actionId: 'evidence.link.remove' });
  } catch (e) {
    if(typeof showToast==='function')showToast(e.detail || 'Remove failed','error');
    return;
  }
  openDetail(eid);loadStats();
}

async function archiveEvidence(eid){
  if(!confirm('Archive this evidence item? It will be removed from the repository, unlinked from all modules, and moved to the archive.'))return;
  try {
    await ApiClient.request('/evidence/api/items/'+eid, { method: 'DELETE', actionId: 'evidence.archive' });
    closeDetail();loadEvidence();loadStats();
    if(typeof showToast==='function')showToast('Evidence archived and unlinked from all modules');
  } catch (e) {
    if(typeof showToast==='function')showToast(e.detail || 'Archive failed','error');
  }
}

async function restoreEvidence(eid){
  if(!confirm('Restore this evidence item back to the repository?'))return;
  try {
    await ApiClient.request('/evidence/api/items/'+eid+'/restore', { method: 'POST', actionId: 'evidence.restore' });
    closeDetail();loadEvidence();loadStats();
    if(typeof showToast==='function')showToast('Evidence restored to repository');
  } catch (e) {
    if(typeof showToast==='function')showToast(e.detail || 'Restore failed','error');
  }
}

async function permanentDeleteEvidence(eid){
  if(!confirm('PERMANENTLY delete this evidence? This cannot be undone. The file and all records will be removed.'))return;
  try {
    await ApiClient.request('/evidence/api/items/'+eid+'/permanent', { method: 'DELETE', actionId: 'evidence.permanent_delete' });
    closeDetail();loadEvidence();loadStats();
    if(typeof showToast==='function')showToast('Evidence permanently deleted');
  } catch (e) {
    if(typeof showToast==='function')showToast(e.detail || 'Delete failed','error');
  }
}

/* ── Quality checks ── */
var evCheckKind={error:'bad',warning:'warn',info:'muted',suggestion:'muted'};
async function loadChecks(){
  var box=document.getElementById('evChecks');
  if(!box)return;
  try{
    var r=await fetch('/evidence/api/inspector?limit=25');var d=await r.json();
    if(!d||d.error){box.innerHTML='';return;}
    var rules=d.rules||{};
    var html='<div class="card" data-s="s01b9273"><div data-s="s617c71f">Quality checks</div>'+
      '<div data-s="s7ba1841">'+escHtml(d.note||'')+' Looked at '+d.scanned+' file'+(d.scanned===1?'':'s')+(d.limit_hit?' (the most recent)':'')+'.</div>';
    if(!d.total){html+='<div data-s="s6cb285c">No known defect among the files you can open.</div>';}
    else{
      html+='<div data-s="s8bb0cda" data-sd="flex">'+Object.keys(d.counts).map(function(k){
        return '<button type="button" class="ev-chip ev-chip-'+(evKnown(evCheckKind,(rules[k]||{}).severity,null)||'muted')+'" data-s="sb518c2b" data-ev-action="check-filter" data-rule="'+escHtml(k)+'">'+escHtml((rules[k]||{}).label||k)+': '+Number(d.counts[k])+'</button>';
      }).join('')+'</div><ul data-s="s99409a7">'+d.findings.map(function(f){
        return '<li data-s="sd1baa8d">'+
          '<span class="ev-chip ev-chip-'+(evKnown(evCheckKind,f.severity,null)||'muted')+'">'+escHtml(f.title)+'</span> '+
          '<button type="button" data-ev-dynamic="openDetail('+Number(f.evidence_id)+')" data-s="sa984f15">'+escHtml(f.evidence_title)+'</button>'+
          '<div data-s="s56c0093">'+escHtml(f.why)+(f.claims&&f.claims.length?' Claims: '+escHtml(f.claims.join(', '))+'.':'')+'</div></li>';
      }).join('')+'</ul>';
    }
    box.innerHTML=html+'</div>';
  }catch(e){box.innerHTML='';}
}
async function evChecksOnly(rule){
  try{
    var r=await fetch('/evidence/api/inspector?limit=25&rule='+encodeURIComponent(rule));var d=await r.json();
    var box=document.getElementById('evChecks');
    var first=(d.findings||[])[0];
    if(first)openDetail(first.evidence_id);
  }catch(e){}
}
async function loadItemChecks(eid){
  var box=document.getElementById('evChecksItem');
  if(!box)return;
  try{
    var r=await fetch('/evidence/api/items/'+eid+'/checks');var d=await r.json();
    if(!d||d.error||!d.findings){box.innerHTML='';return;}
    if(!d.findings.length){box.innerHTML='<div class="ev-section"><div class="ev-section-title">Checks</div><div data-s="s7fc448e">No known defect. That is not a statement that this file is sufficient.</div></div>';return;}
    box.innerHTML='<div class="ev-section"><div class="ev-section-title">Checks</div><ul data-s="s99409a7">'+d.findings.map(function(f){
      var fix=f.fix||{};
      var actions={owner:'evInlineOwner('+eid+')',version:'evAddVersion('+eid+')',review_due_date:'evInlineEdit(\'review_due_date\','+eid+',null)',versions:'evShowTab(\'history\')',open:''};
      var act=evKnown(actions,fix.action,'');
      return '<li data-s="scc70c58"><span class="ev-chip ev-chip-'+(evKnown(evCheckKind,f.severity,null)||'muted')+'">'+escHtml(f.title)+'</span> '+escHtml(f.why)+
        (f.claims&&f.claims.length?' Claims: '+escHtml(f.claims.join(', '))+'.':'')+
        (act?' <button type="button" class="btn btn-secondary" data-s="se2b3d6e" data-ev-dynamic="'+act+'">'+escHtml(fix.label||'Fix')+'</button>':'')+'</li>';
    }).join('')+'</ul></div>';
  }catch(e){box.innerHTML='';}
}

/* ── Find evidence ── */
function evFindOpen(){
  document.getElementById('findQuestion').value='';
  document.getElementById('findStatus').textContent='';
  document.getElementById('findResults').innerHTML='';
  document.getElementById('findFilters').style.display='none';
  document.getElementById('findMore').style.display='none';
  ModalManager.open('findModal');
  document.getElementById('findQuestion').focus();
}
function evFindFill(vocab){
  function options(sel,list,blank){
    sel.innerHTML='<option value="">'+blank+'</option>'+list.map(function(o){return '<option value="'+escHtml(o.id)+'">'+escHtml(o.label)+'</option>';}).join('');
  }
  options(document.getElementById('findState'),vocab.states,'Any state');
  options(document.getElementById('findModule'),vocab.modules,'Any module');
}
async function evFindRun(e,edited){
  if(e)e.preventDefault();
  var status=document.getElementById('findStatus');
  var body;
  if(edited){
    var words=document.getElementById('findWords').value.split(/\s+/).filter(Boolean);
    body={filters:{words:words,state:document.getElementById('findState').value||undefined,module:document.getElementById('findModule').value||undefined,
      owner:document.getElementById('findMine').checked?'me':undefined}};
  }else{
    var q=document.getElementById('findQuestion').value.trim();
    if(!q){status.textContent='Write a question first.';return;}
    body={question:q};
  }
  status.textContent='Looking...';
  var d;
  try{d=await ApiClient.request('/evidence/api/find',{method:'POST',body:body,actionId:'evidence.find'});}
  catch(err){status.textContent=err.detail||'Could not search.';return;}
  evFindFilters=d.filters||{};
  if(!evFindVocab){evFindVocab=d.vocabulary;evFindFill(evFindVocab);}
  var f=evFindFilters;
  document.getElementById('findWords').value=(f.words||[]).join(' ');
  document.getElementById('findState').value=f.state||'';
  document.getElementById('findModule').value=f.module||'';
  document.getElementById('findMine').checked=f.owner==='me';
  document.getElementById('findFilters').style.display='block';
  status.textContent=(d.note?d.note+' ':'')+(d.results.length?('Showing '+d.results.length+' of '+d.total+'.'):(d.message||'No accessible match.'));
  document.getElementById('findMore').style.display=d.total>d.results.length?'block':'none';
  document.getElementById('findResults').innerHTML=d.results.map(function(r){
    var st=r.state?'<span class="ev-chip ev-chip-'+(evKnown(evStateKind,r.state.key,null)||'muted')+'">'+escHtml(r.state.label)+'</span>':'';
    var claims=(r.claims||[]).map(function(c){return escHtml(c.title);}).join(', ');
    return '<li data-s="s47bc0d4">'+
      '<button type="button" data-ev-dynamic="ModalManager.close(\'findModal\');openDetail('+Number(r.id)+')" data-s="se44357b">'+escHtml(r.title)+'</button> '+st+
      ' <span data-s="s6d034cc">version '+escHtml(String(r.version||1))+'</span>'+
      '<div data-s="s8a05498">'+escHtml((r.why||[]).join(' · '))+
        (r.expiry_date?' · expires '+escHtml(fmtDate(r.expiry_date)):'')+(r.review_due_date?' · review by '+escHtml(fmtDate(r.review_due_date)):'')+
        (r.owner_name?' · owner '+escHtml(r.owner_name):'')+'</div>'+
      evTextMatchHtml(r)+
      (claims||r.claims_hidden?'<div data-s="s21f4b17">Supports: '+(claims||'')+(r.claims_hidden?(claims?', ':'')+r.claims_hidden+' you cannot open':'')+'</div>':'')+
    '</li>';
  }).join('');
}
function evFindApply(){
  var f=evFindFilters||{};
  currentState=f.state||'';currentModule=f.module||'';currentCategory=f.category||'';
  evOwnerOnly=f.owner==='me';currentWords=(f.words||[]).join(' ');
  document.getElementById('searchInput').value='';
  ModalManager.close('findModal');
  switchView('all',document.getElementById('nav-all'));
}

/* ── Review one link ── */
function evReviewLink(linkId,eid,status,name){
  document.getElementById('rvLinkId').value=linkId;
  document.getElementById('rvEvidenceId').value=eid;
  document.getElementById('rvExpected').value=status;
  document.getElementById('rvTarget').textContent=name||'this record';
  document.getElementById('rvNote').value='';
  document.getElementById('rvStatus').textContent='';
  document.querySelectorAll('#reviewForm input[name=rvOutcome]').forEach(function(r){r.checked=false;});
  ModalManager.open('reviewModal');
}
async function evSubmitReview(e){
  e.preventDefault();
  var picked=document.querySelector('#reviewForm input[name=rvOutcome]:checked');
  var status=document.getElementById('rvStatus');
  if(!picked){status.textContent='Choose what you conclude.';return;}
  var linkId=document.getElementById('rvLinkId').value;
  var eid=Number(document.getElementById('rvEvidenceId').value);
  try{
    await ApiClient.request('/evidence/api/links/'+encodeURIComponent(linkId)+'/review',{
      method:'POST',actionId:'evidence.link.review',
      body:{outcome:picked.value,note:document.getElementById('rvNote').value,expected_status:document.getElementById('rvExpected').value}
    });
  }catch(err){
    status.textContent=err.detail||'The review could not be saved.';
    return;
  }
  ModalManager.close('reviewModal');
  if(typeof showToast==='function')showToast('Review saved','success');
  openDetail(eid);loadStats();loadEvidence();loadCoverage();loadChecks();
}

/* ── Add a new version of a file ── */
function evAddVersion(eid){
  var input=document.getElementById('evVersionFile');
  input.dataset.eid=String(eid);
  input.value='';
  input.click();
}
document.addEventListener('DOMContentLoaded',function(){
  var input=document.getElementById('evVersionFile');
  if(!input)return;
  input.addEventListener('change',async function(){
    var file=input.files&&input.files[0];
    var eid=Number(input.dataset.eid);
    if(!file||!eid||!evDetailItem)return;
    var form=new FormData();
    form.append('file',file);
    form.append('replace_id',String(eid));
    form.append('title',evDetailItem.title||'');
    form.append('category',evDetailItem.category||'general');
    form.append('tags',evDetailItem.tags||'');
    form.append('description',evDetailItem.description||'');
    try{
      var made=await ApiClient.request('/evidence/api/items',{method:'POST',body:form,actionId:'evidence.version.add'});
      var imp=made.impact||{};
      var msg='New version saved.';
      if(imp.carried)msg+=' '+imp.carried+' link'+(imp.carried===1?' was':'s were')+' proposed for review.';
      if(imp.not_carried)msg+=' '+imp.not_carried+' stayed with the earlier version.';
      if(typeof showToast==='function')showToast(msg,'success');
      evPage=1;
      openDetail(made.id);loadStats();loadEvidence();loadCoverage();
    }catch(err){
      var text=err.detail||'The new version could not be saved.';
      if(err.status===409&&err.body&&err.body.duplicate)text=err.body.message||'This file is already in the Vault.';
      if(typeof showToast==='function')showToast(text,'error');
    }
  });
});

/* ── AI Suggest Links ── */
async function aiSuggestLinks(eid){
  var box=document.getElementById('aiSuggestBox');
  if(!box)return;
  box.style.display='block';
  box.innerHTML='<div data-s="s38e4562"><div class="spinner" data-s="s57b27e0"></div>Analyzing evidence for link suggestions...</div>';
  try{
    var r=await fetch('/evidence/api/items/'+eid+'/suggest-links',{method:'POST'});
    if(!r.ok){box.innerHTML='<div data-s="sb1c8c3c">AI not available</div>';return;}
    var data=await r.json();
    var suggestions=data.suggestions||[];
    if(!suggestions.length){
      box.innerHTML='<div data-s="s1e2616c">No additional link suggestions found.</div>';
      return;
    }
    box.innerHTML='<div data-s="sf157ded">AI Suggestions</div>'+
      suggestions.map(function(s){
        var mc=evKnown(modColors,s.module,null)||'#6b7280';
        return '<div data-s="s96dad42" data-sd="flex">'+
          '<span data-sv="width:8px;height:8px;border-radius:50%;background:'+mc+';flex-shrink:0"></span>'+
          '<span data-s="s8fbdd52">'+escHtml(s.entity_name||'')+'</span>'+
          '<span data-s="s6d034cc">'+escHtml(s.module)+' / '+escHtml(s.entity_type)+'</span>'+
          '<span data-s="s7971bf0" title="'+escHtml(s.reason||'')+'">'+escHtml((s.reason||'').substring(0,60))+'</span>'+
          '<button type="button" data-ev-action="ai-link" data-evidence-id="'+Number(eid)+'" data-module="'+escHtml(s.module)+'" data-entity-type="'+escHtml(s.entity_type)+'" data-entity-id="'+Number(s.entity_id)+'" class="btn btn-primary" data-s="saa47ff0">Link</button>'+
        '</div>';
      }).join('');
  }catch(e){
    box.innerHTML='<div data-s="sb1c8c3c">Failed to get suggestions</div>';
  }
}

async function applyAiLink(eid,module,entityType,entityId,btn){
  btn.disabled=true;btn.textContent='...';
  try{
    await ApiClient.request('/evidence/api/items/'+eid+'/links', {
      method: 'POST',
      body: {module:module,entity_type:entityType,entity_id:entityId},
      actionId: 'evidence.link.ai_apply',
    });
    btn.textContent='Linked';btn.style.background='var(--green-status)';
    openDetail(eid);loadStats();
  }catch(e){
    btn.textContent='Error';btn.disabled=false;
    if (typeof showToast === 'function' && e.detail) showToast(e.detail, 'error');
  }
}

/* ── Link-to Modal ── */
function openLinkToModal(eid){
  document.getElementById('linkEvidenceId').value=eid;
  document.getElementById('linkModule').value='';
  document.getElementById('linkEntityType').innerHTML='<option value="">Select type</option>';
  document.getElementById('linkSearch').value='';
  document.getElementById('linkEntityList').innerHTML='<div data-s="sbbd9f32">Select a module and entity type</div>';
  ModalManager.open('linkToModal');
}
function loadEntityTypes(){
  var mod=document.getElementById('linkModule').value;
  var sel=document.getElementById('linkEntityType');
  sel.innerHTML='<option value="">Select type</option>';
  if(mod&&entityTypes[mod]){
    var labels={nc:'Nonconformance',non_conformance:'Nonconformance',bia:'Business impact assessment',
      compliance_control:'Compliance control',ropa:'Processing activity',dpia:'Privacy impact assessment',
      dsr:'Data subject request',application:'AI system or application',scenario:'Risk scenario'};
    entityTypes[mod].forEach(function(t){var o=document.createElement('option');o.value=t;
      o.textContent=labels[t]||t.replace(/_/g,' ').replace(/^./,function(c){return c.toUpperCase();});sel.appendChild(o);});
  }
}
function debounceEntitySearch(){clearTimeout(entitySearchTimeout);entitySearchTimeout=setTimeout(searchEntities,300);}
async function searchEntities(){
  var mod=document.getElementById('linkModule').value;
  var etype=document.getElementById('linkEntityType').value;
  var q=document.getElementById('linkSearch').value;
  var el=document.getElementById('linkEntityList');
  if(!mod||!etype){el.innerHTML='<div data-s="sbbd9f32">Select a module and entity type</div>';return;}
  var params='module='+mod+'&entity_type='+etype;if(q)params+='&q='+encodeURIComponent(q);
  var items;
  try {
    var r=await fetch('/evidence/api/search-entities?'+params);
    if(!r.ok)throw new Error('Search unavailable');
    items=await r.json();
  } catch(e) {
    el.innerHTML='<div data-s="sbbd9f32">Entity search is unavailable. Try again shortly.</div>';
    return;
  }
  if(!items.length){el.innerHTML='<div data-s="sbbd9f32">No entities found</div>';return;}
  var eid=document.getElementById('linkEvidenceId').value;
  el.innerHTML=items.map(function(e){
    var safeId=parseInt(e.id,10)||0;
    return '<button type="button" class="ev-link-result" data-s="s4b75f16" data-sd="block" data-ev-action="create-link" data-evidence-id="'+parseInt(eid,10)+'" data-module="'+escHtml(mod)+'" data-entity-type="'+escHtml(etype)+'" data-entity-id="'+safeId+'">'+
      '<span data-s="s8fbdd52">'+escHtml(e.name)+'</span>'+
      '<span data-s="sec0c92b">#'+safeId+'</span></button>';
  }).join('');
}
async function createLink(eid,mod,etype,entityId){
  try {
    await ApiClient.request('/evidence/api/items/'+eid+'/links', {
      method: 'POST',
      body: {module:mod,entity_type:etype,entity_id:entityId},
      actionId: 'evidence.link.create',
    });
  } catch (e) {
    if(typeof showToast==='function')showToast(e.detail || 'Link failed','error');
    return;
  }
  ModalManager.close('linkToModal');
  if(typeof showToast==='function')showToast('Evidence linked to '+mod+' '+etype);
  openDetail(eid);loadStats();
}

// Values from link and suggestion responses stay in data attributes, never executable handlers.
document.addEventListener('click',function(event){
  var button=event.target.closest('[data-ev-action]');
  if(!button)return;
  var action=button.dataset.evAction;
  if(action==='check-filter'){
    evChecksOnly(button.dataset.rule||'');
    return;
  }
  var eid=Number(button.dataset.evidenceId);
  if(!Number.isSafeInteger(eid)||eid<1)return;
  if(action==='inline-select'){
    var field=button.dataset.field;
    if(field!=='category'&&field!=='status')return;
    var choices=field==='category'?['general','policy','certificate','screenshot','report','procedure','training']:
      ['current','superseded','archived','expired','draft'];
    var current=evDetailItem&&evDetailItem[field];
    var options=choices.map(function(value){return '<option value="'+value+'"'+(value===current?' selected':'')+'>'+value+'</option>';}).join('');
    evInlineSelect(field,eid,options);
  }else if(action==='review-link'){
    var linkId=Number(button.dataset.linkId);
    if(Number.isSafeInteger(linkId)&&linkId>0){
      evReviewLink(linkId,eid,button.dataset.status||'',button.dataset.name||'');
    }
  }else if(action==='ai-link'||action==='create-link'){
    var entityId=Number(button.dataset.entityId);
    if(!Number.isSafeInteger(entityId)||entityId<1)return;
    if(action==='ai-link'){
      applyAiLink(eid,button.dataset.module||'',button.dataset.entityType||'',entityId,button);
    }else{
      createLink(eid,button.dataset.module||'',button.dataset.entityType||'',entityId);
    }
  }
});

/* ── View/Filter Switching ── */
function evMarkFolder(){
  document.querySelectorAll('#evFolderGrid [data-folder]').forEach(function(card){
    card.setAttribute('aria-pressed',evFolder===card.dataset.folder?'true':'false');
  });
}
function evCloseRecordFolders(){document.getElementById('evRecordFolders').hidden=true;evFolderGroup='';}
function evCompanyOption(scope){
  if(!evCompanyViews)return null;
  if(scope==='organization')return evCompanyViews.organization;
  if(scope.startsWith('unit:'))return (evCompanyViews.units||[]).find(function(u){return scope==='unit:'+u.id;});
  return null;
}
function evCompanyLabel(scope){var item=evCompanyOption(scope);return item?item.name:'Accessible documents';}
function evChooseCompany(scope){evCompanyScope=scope;evPage=1;evRenderCompanyViews();loadEvidence();}
function evRenderCompanyViews(){
  var host=document.getElementById('evCompanyViews');host.replaceChildren();
  if(!evCompanyViews||!evCompanyViews.organization){host.textContent='No organization is selected.';return;}
  var org=evCompanyViews.organization;
  var choices=[{scope:'',name:'All accessible documents',count:org.count},
    {scope:'organization',name:org.name+' · organization-wide',count:org.organization_wide}];
  (evCompanyViews.units||[]).forEach(function(unit){choices.push({scope:'unit:'+unit.id,name:unit.name,count:unit.count});});
  choices.forEach(function(item){
    var button=document.createElement('button');button.type='button';button.className='ev-company-card';
    button.setAttribute('aria-pressed',evCompanyScope===item.scope?'true':'false');
    var title=document.createElement('strong');title.textContent=item.name;
    var count=document.createElement('small');count.textContent=item.count+' current documents';
    button.append(title,count);button.addEventListener('click',function(){evChooseCompany(item.scope);});host.appendChild(button);
  });
}
async function evLoadCompanyViews(){
  try{
    var response=await fetch('/evidence/api/company-views');if(!response.ok)throw new Error();
    evCompanyViews=await response.json();
    if(evCompanyScope&&!evCompanyOption(evCompanyScope)){evCompanyScope='';evPage=1;loadEvidence();}
    evRenderCompanyViews();
    var select=document.getElementById('uploadFilingScope');select.replaceChildren();
    var blank=document.createElement('option');blank.value='';blank.textContent='Choose an authorized filing scope';select.appendChild(blank);
    function add(scope,label){var option=document.createElement('option');option.value=scope;option.textContent=label;select.appendChild(option);}
    (evCompanyViews.units||[]).forEach(function(unit){add('unit:'+unit.id,unit.name);});
    if(evCompanyViews.can_file_org_wide)add('organization',evCompanyViews.organization.name+' · organization-wide');
  }catch(_){document.getElementById('evCompanyViews').textContent='Filing scopes are unavailable. Reload before uploading.';}
}
function evRenderEntityViews(){
  var host=document.getElementById('evEntityViews');if(!host)return;
  host.replaceChildren();
  if(!evEntityViews){host.textContent='Company views are unavailable.';return;}
  var choices=[{id:'',name:'All accessible documents',count:null}];
  (evEntityViews.companies||[]).forEach(function(item){choices.push({id:String(item.id),name:item.name,count:item.count});});
  if(evEntityViews.unconfirmed)choices.push({id:'unconfirmed',name:'Ownership unconfirmed',count:evEntityViews.unconfirmed});
  choices.forEach(function(item){
    var button=document.createElement('button');button.type='button';button.className='ev-company-card';
    button.setAttribute('aria-pressed',evEntityScope===item.id?'true':'false');
    var title=document.createElement('strong');title.textContent=item.name;button.appendChild(title);
    if(item.count!==null){var count=document.createElement('small');count.textContent=item.count+' accessible documents';button.appendChild(count);}
    button.addEventListener('click',function(){evEntityScope=item.id;evPage=1;evRenderEntityViews();loadEvidence();});
    host.appendChild(button);
  });
}
async function evLoadEntityViews(){
  // A platform super administrator without a selected tenant has no company catalogue to read.
  if(!document.getElementById('evidencePageData').dataset.hasOrg==='true'){
    evEntityViews={companies:[],unconfirmed:0};evRenderEntityViews();return;
  }
  try{
    var response=await fetch('/evidence/api/companies');if(!response.ok)throw new Error();
    evEntityViews=await response.json();
    if(evEntityScope&&evEntityScope!=='unconfirmed'&&!evEntityViews.companies.some(function(item){return String(item.id)===evEntityScope;})){
      evEntityScope='';evPage=1;loadEvidence();
    }
    evRenderEntityViews();
  }catch(_){evEntityViews=null;evRenderEntityViews();}
}
async function evOpenGroupPublication(item){
  var host=document.getElementById('evGroupDetail');host.hidden=false;host.replaceChildren();
  host.textContent='Loading approved version…';
  try{
    var response=await fetch('/evidence/api/group/publications/'+encodeURIComponent(item.id));
    if(!response.ok)throw new Error();
    var detail=await response.json();host.replaceChildren();
    var heading=document.createElement('h3');heading.textContent=detail.title;host.appendChild(heading);
    var info=document.createElement('p');info.textContent=detail.source_name+' · version '+detail.version+' · '+detail.category+' · '+detail.classification;
    host.appendChild(info);
    var expiry=document.createElement('p');expiry.textContent='Access expires '+detail.expires_at;host.appendChild(expiry);
    if(item.can_download){
      var download=document.createElement('a');download.className='btn btn-secondary';
      download.href='/evidence/api/group/publications/'+encodeURIComponent(item.id)+'/download';
      download.textContent='Download approved version';host.appendChild(download);
    }
    var close=document.createElement('button');close.type='button';close.className='btn btn-secondary';
    close.textContent='Close';close.addEventListener('click',function(){host.hidden=true;host.replaceChildren();});host.appendChild(close);
    host.scrollIntoView({block:'nearest',behavior:'smooth'});
  }catch(_){host.textContent='This version is no longer available to you.';evLoadGroupPublications();}
}
async function evLoadGroupPublications(){
  var section=document.getElementById('evGroupSection'),host=document.getElementById('evGroupViews');
  try{
    var response=await fetch('/evidence/api/group/companies');
    if(!response.ok)throw new Error();
    var data=await response.json(),companies=data.companies||[];
    section.hidden=!companies.length;host.replaceChildren();
    if(evGroupSource&&!companies.some(function(c){return c.id===evGroupSource.id;})){
      evGroupSource=null;document.getElementById('evGroupBrowse').hidden=true;
      document.getElementById('evGroupDetail').hidden=true;
    }
    companies.forEach(function(item){
      var button=document.createElement('button');button.type='button';button.className='ev-company-card';
      button.setAttribute('aria-pressed',evGroupSource&&evGroupSource.id===item.id?'true':'false');
      var title=document.createElement('strong');title.textContent=item.name;
      var label=document.createElement('small');label.textContent='Browse approved releases';
      button.append(title,label);button.addEventListener('click',function(){
        evGroupSource=item;evGroupCursor=null;evGroupBack=[];
        document.getElementById('evGroupBrowse').hidden=false;
        document.getElementById('evGroupBrowseName').textContent=item.name+' · approved releases';
        document.getElementById('evGroupDetail').hidden=true;
        evLoadGroupPublications();
      });host.appendChild(button);
    });
    if(evGroupSource)evLoadGroupCompanyItems();
  }catch(_){section.hidden=true;host.replaceChildren();}
}
async function evLoadGroupCompanyItems(){
  if(!evGroupSource)return;
  var sourceId=evGroupSource.id,cursor=evGroupCursor;
  var host=document.getElementById('evGroupItems'),pager=document.getElementById('evGroupPager');
  host.textContent='Loading approved releases…';pager.replaceChildren();
  try{
    var url='/evidence/api/group/companies/'+encodeURIComponent(sourceId)+'/publications';
    if(cursor)url+='?before='+encodeURIComponent(cursor);
    var response=await fetch(url);if(!response.ok)throw new Error();
    var data=await response.json();if(!evGroupSource||evGroupSource.id!==sourceId||evGroupCursor!==cursor)return;
    host.replaceChildren();
    if(!data.items.length)host.textContent='No current approved releases for this company.';
    (data.items||[]).forEach(function(item){
      var button=document.createElement('button');button.type='button';button.className='ev-company-card';
      var title=document.createElement('strong');title.textContent=item.title;
      var label=document.createElement('small');label.textContent='Version '+item.version+' · '+item.category;
      button.append(title,label);button.addEventListener('click',function(){evOpenGroupPublication(item);});host.appendChild(button);
    });
    if(evGroupBack.length){var prev=document.createElement('button');prev.type='button';prev.className='btn btn-secondary';
      prev.textContent='Previous';prev.addEventListener('click',function(){evGroupCursor=evGroupBack.pop();evLoadGroupCompanyItems();});pager.appendChild(prev);}
    if(data.next_cursor){var next=document.createElement('button');next.type='button';next.className='btn btn-secondary';
      next.textContent='Next';next.addEventListener('click',function(){evGroupBack.push(evGroupCursor);evGroupCursor=data.next_cursor;evLoadGroupCompanyItems();});pager.appendChild(next);}
  }catch(_){host.textContent='Approved releases are unavailable. Try again.';}
}
document.getElementById('evGroupRefresh').addEventListener('click',evLoadGroupPublications);
document.getElementById('evGroupAsk').addEventListener('submit',async function(event){
  event.preventDefault();
  var host=document.getElementById('evGroupAnswer');host.textContent='Searching released documents…';
  try{
    var data=await ApiClient.request('/evidence/api/group/ask',{method:'POST',actionId:'evidence.group_ask',
      body:{question:document.getElementById('evGroupQuestion').value}});
    host.replaceChildren();
    if(data.answer){var answer=document.createElement('p');answer.textContent=data.answer;host.appendChild(answer);}
    if(data.note){var note=document.createElement('small');note.textContent=data.note;host.appendChild(note);}
    (data.results||[]).forEach(function(item){
      var card=document.createElement('div');card.className='ev-company-card';
      var title=document.createElement('strong');
      title.textContent='['+item.n+'] '+item.title+' v'+item.version+' · '+item.source_name+' · '+item.section;
      var text=document.createElement('small');text.textContent=item.text;
      card.append(title,text);host.appendChild(card);
    });
  }catch(error){host.textContent=error.detail||'The question could not be answered. Try again.';}
});
function evChooseFolder(key,openRecords){
  evFolder=key;evPage=1;currentModule='';currentCategory='';currentView='all';
  currentStatus='';currentState='';currentWords='';evOwnerOnly=false;
  document.getElementById('searchInput').value='';
  document.querySelectorAll('#evWork [data-view]').forEach(function(tab){
    var selected=tab.dataset.view==='all';
    tab.classList.toggle('is-current',selected);
    tab.setAttribute('aria-pressed',selected?'true':'false');
  });
  evMarkFolder();
  if(openRecords){
    evFolderGroup=key;evFolderPage=1;
    document.getElementById('evRecordFolderSearch').value='';
    document.getElementById('evRecordFolderTitle').textContent='Browse '+key;
    document.getElementById('evRecordFolders').hidden=false;
    evLoadRecordFolders();
  }else if(!key){evCloseRecordFolders();}
  loadEvidence();
}
async function evLoadFolderCards(){
  var host=document.getElementById('evFolderGrid');
  try{
    var response=await fetch('/evidence/api/folders');
    if(!response.ok)throw new Error('Folder list unavailable');
    var data=await response.json();
    host.replaceChildren();
    (data.folders||[]).forEach(function(folder){
      var button=document.createElement('button');
      button.type='button';button.className='ev-folder-card';button.dataset.folder=folder.key;
      button.setAttribute('aria-label',folder.title+', '+folder.count+' documents');
      button.setAttribute('aria-pressed',evFolder===folder.key?'true':'false');
      ['back','paper','front'].forEach(function(layer){
        var piece=document.createElement('span');piece.className='ev-folder-'+layer;piece.setAttribute('aria-hidden','true');button.appendChild(piece);
      });
      var label=document.createElement('span');label.className='ev-folder-label';
      var name=document.createElement('span');name.className='ev-folder-name';name.textContent=folder.title;
      var count=document.createElement('span');count.className='ev-folder-count';count.textContent=folder.count+' files';
      label.append(name,count);button.appendChild(label);
      button.addEventListener('click',function(){evChooseFolder(folder.key,folder.has_records);});
      host.appendChild(button);
    });
  }catch(_){host.textContent='Folders are unavailable. The evidence list remains available below.';}
}
function evSearchRecordFolders(){
  clearTimeout(evFolderSearchTimer);evFolderSearchTimer=setTimeout(function(){evFolderPage=1;evLoadRecordFolders();},250);
}
async function evLoadRecordFolders(){
  var group=evFolderGroup;if(!group)return;
  var list=document.getElementById('evRecordFolderList'),pager=document.getElementById('evRecordFolderPager');
  var params=new URLSearchParams({page:String(evFolderPage),q:document.getElementById('evRecordFolderSearch').value});
  try{
    var response=await fetch('/evidence/api/folders/'+encodeURIComponent(group)+'/records?'+params);
    if(!response.ok)throw new Error('Record folders unavailable');
    var data=await response.json();if(group!==evFolderGroup)return;
    list.replaceChildren();pager.replaceChildren();
    if(!data.items.length)list.textContent='No records with visible documents match this search.';
    data.items.forEach(function(item){
      var button=document.createElement('button');button.type='button';button.className='ev-record-folder';
      var icon=document.createElement('span');icon.textContent='▣';icon.setAttribute('aria-hidden','true');
      var title=document.createElement('span');title.textContent=item.title;
      var count=document.createElement('small');count.textContent=item.count+' files';
      button.append(icon,title,count);button.addEventListener('click',function(){evChooseFolder(item.key,false);});list.appendChild(button);
    });
    var label=document.createElement('span');label.textContent='Page '+data.page+' of '+data.pages+' · '+data.total+' records';pager.appendChild(label);
    [['Previous',data.page-1,data.page<=1],['Next',data.page+1,data.page>=data.pages]].forEach(function(spec){
      var button=document.createElement('button');button.type='button';button.className='btn btn-secondary';button.textContent=spec[0];button.disabled=spec[2];
      button.addEventListener('click',function(){evFolderPage=spec[1];evLoadRecordFolders();});pager.appendChild(button);
    });
  }catch(_){list.textContent='Record folders could not be loaded.';pager.replaceChildren();}
}
function switchView(v,el){
  currentView=v;evPage=1;
  evFolder='';evCloseRecordFolders();evMarkFolder();
  document.querySelectorAll('.nav-item').forEach(function(n){n.classList.remove('active');});
  if(el)el.classList.add('active');
  var key=(v==='unlinked')?'needs_filing':v;
  document.querySelectorAll('#evWork [data-view]').forEach(function(tab){
    var on=tab.getAttribute('data-view')===key;
    tab.classList.toggle('is-current',on);
    tab.setAttribute('aria-pressed',on?'true':'false');
  });
  loadEvidence();
}
function filterModule(m,el){currentModule=m;evFolder='';evCloseRecordFolders();evMarkFolder();evPage=1;loadEvidence();}
function filterCategory(c){currentCategory=c;evFolder='';evCloseRecordFolders();evMarkFolder();evPage=1;loadEvidence();}
function debounceSearch(){clearTimeout(searchTimeout);searchTimeout=setTimeout(function(){evPage=1;loadEvidence();},300);}

/* ── Upload ── */
var uploadTarget=null, uploadTargetTimer=null, uploadTargetSeq=0;
function clearUploadTarget(){
  uploadTarget=null;
  var selected=document.getElementById('uploadLinkSelected');
  selected.style.display='none';
  selected.querySelector('span').textContent='';
}
function uploadTargetModuleChanged(){
  clearUploadTarget();
  var mod=document.getElementById('uploadLinkModule').value;
  var type=document.getElementById('uploadLinkType');
  type.replaceChildren();
  var blank=document.createElement('option');blank.value='';blank.textContent='Choose type';type.appendChild(blank);
  var labels={nc:'Nonconformance',non_conformance:'Nonconformance',bia:'Business impact assessment',
    compliance_control:'Compliance control',ropa:'Processing activity',dpia:'Privacy impact assessment',
    dsr:'Data subject request',application:'AI system or application'};
  (entityTypes[mod]||[]).forEach(function(kind){
    var option=document.createElement('option');option.value=kind;
    option.textContent=labels[kind]||kind.replace(/_/g,' ').replace(/^./,function(c){return c.toUpperCase();});
    type.appendChild(option);
  });
  uploadTargetTypeChanged();
}
function uploadTargetTypeChanged(){
  clearUploadTarget();
  document.getElementById('uploadLinkSearch').value='';
  searchUploadTargets();
}
function debounceUploadTargetSearch(){
  clearTimeout(uploadTargetTimer);
  uploadTargetTimer=setTimeout(searchUploadTargets,250);
}
async function searchUploadTargets(){
  var mod=document.getElementById('uploadLinkModule').value;
  var type=document.getElementById('uploadLinkType').value;
  var box=document.getElementById('uploadLinkResults');
  var seq=++uploadTargetSeq;
  box.replaceChildren();
  if(!mod||!type)return;
  box.textContent='Finding records...';
  var query=new URLSearchParams({module:mod,entity_type:type,q:document.getElementById('uploadLinkSearch').value});
  try{
    var response=await fetch('/evidence/api/search-entities?'+query);
    if(!response.ok)throw new Error('Search unavailable');
    var items=await response.json();
    if(seq!==uploadTargetSeq)return;
    box.replaceChildren();
    if(!items.length){box.textContent='No accessible records found';return;}
    items.forEach(function(item){
      var id=Number(item.id);
      if(!Number.isSafeInteger(id)||id<=0)return;
      var button=document.createElement('button');button.type='button';
      button.className='btn btn-secondary';
      button.style.cssText='display:block;width:100%;text-align:left;margin:3px 0;white-space:normal';
      button.textContent=item.name+' (#'+id+')';
      button.addEventListener('click',function(){
        uploadTarget={module:mod,entity_type:type,entity_id:id};
        var selected=document.getElementById('uploadLinkSelected');
        selected.querySelector('span').textContent='Selected: '+item.name+' (#'+id+')';
        selected.style.display='flex';
        box.replaceChildren();
      });
      box.appendChild(button);
    });
  }catch(error){
    if(seq===uploadTargetSeq)box.textContent='Record search is unavailable. You can upload without a link.';
  }
}
async function handleUpload(e){
  e.preventDefault();
  document.getElementById('uploadDupeWarning').style.display='none';
  var form=new FormData();
  var fileEl=document.getElementById('uploadFile');
  if(!fileEl.files[0]){return;}
  form.append('file',fileEl.files[0]);
  form.append('filing_scope',document.getElementById('uploadFilingScope').value);
  form.append('title',document.getElementById('uploadTitle').value);
  form.append('category',document.getElementById('uploadCategory').value);
  form.append('tags',document.getElementById('uploadTags').value);
  form.append('description',document.getElementById('uploadDesc').value);
  if(uploadTarget){
    form.append('link_module',uploadTarget.module);
    form.append('link_entity_type',uploadTarget.entity_type);
    form.append('link_entity_id',String(uploadTarget.entity_id));
  }else if(document.getElementById('uploadLinkModule').value){
    document.getElementById('uploadLinkResults').textContent='Select a record, or choose no module to upload without a link.';
    return;
  }
  var expiry=document.getElementById('uploadExpiry').value;
  if(expiry)form.append('expiry_date',expiry);
  [['uploadReviewDue','review_due_date'],['uploadPeriodStart','period_start'],['uploadPeriodEnd','period_end']].forEach(function(f){
    var v=document.getElementById(f[0]).value;
    if(v)form.append(f[1],v);
  });
  var submit=document.getElementById('uploadSubmit');submit.disabled=true;
  try {
    await ApiClient.request('/evidence/api/items', { method: 'POST', body: form, actionId: 'evidence.upload' });
  } catch (e) {
    if (e.status === 409 && e.body) {
      var d=e.body;
      var warn=document.getElementById('uploadDupeWarning');
      if(d.hidden){
        warn.textContent=d.message||'This file is already in the Vault, in a place you cannot open.';
        warn.style.display='block';
        return;
      }
      warn.innerHTML='<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg> <strong>This file already exists:</strong> '+escHtml(d.existing_title||'#'+d.existing_id)+
        '<div data-s="s62ee93e" data-sd="flex">'+
          '<button class="btn btn-secondary" data-s="s301a157" data-ev-dynamic="ModalManager.close(\'uploadModal\');openDetail('+Number(d.existing_id)+')">View Existing</button>'+
          '<button class="btn btn-primary" data-s="s301a157" data-ev-dynamic="ModalManager.close(\'uploadModal\');openLinkToModal('+Number(d.existing_id)+')">Link Existing</button>'+
        '</div>';
      warn.style.display='block';
    } else if (typeof showToast==='function') {
      showToast(e.detail || 'Upload failed','error');
    }
    return;
  } finally {
    submit.disabled=false;
  }
  ModalManager.close('uploadModal');
  document.getElementById('uploadForm').reset();
  clearUploadTarget();
  document.getElementById('uploadLinkType').innerHTML='<option value="">Choose type</option>';
  document.getElementById('uploadLinkResults').replaceChildren();
  document.getElementById('uploadExpiry').value='';
  evPage=1;
  loadEvidence();loadStats();loadCoverage();evLoadCompanyViews();evLoadEntityViews();evLoadGroupPublications();
  if(typeof showToast==='function')showToast('Evidence uploaded'+(form.has('link_module')?' and filed for link review':''),'success');
}

/* ── Drag-drop ── */
(function(){
  var dragCounter=0;
  var dropZone=document.getElementById('pageDropZone');

  function showDropZone(){
    if(dropZone){dropZone.style.display='flex';}
  }
  function hideDropZone(){
    if(dropZone){dropZone.style.display='none';}
  }

  // dragenter fires when dragging enters the window or any child element;
  // use a counter so dragleave from a child doesn't hide the overlay prematurely.
  document.addEventListener('dragenter',function(e){
    if(!e.dataTransfer||!e.dataTransfer.types||
       !Array.prototype.includes.call(e.dataTransfer.types,'Files')) return;
    dragCounter++;
    showDropZone();
  });

  document.addEventListener('dragleave',function(e){
    dragCounter--;
    if(dragCounter<=0){dragCounter=0;hideDropZone();}
  });

  document.addEventListener('dragover',function(e){e.preventDefault();});

  document.addEventListener('drop',function(e){
    e.preventDefault();
    dragCounter=0;
    hideDropZone();
    var files=e.dataTransfer&&e.dataTransfer.files;
    if(!files||!files.length)return;
    document.getElementById('uploadFile').files=files;
    ModalManager.open('uploadModal');
  });
})();

document.addEventListener('DOMContentLoaded',function(){
  setViewMode(evViewMode);  // Apply saved view mode to toggle buttons
  loadStats();loadEvidence();loadCoverage();loadChecks();evLoadSavedViews();evLoadCompanyViews();evLoadEntityViews();
  evLoadGroupPublications();
});


/* A record in another module can open the upload form with itself already chosen: ?attach=module:type:id */
(function(){
  var raw = new URLSearchParams(window.location.search).get('attach');
  if(!raw) return;
  var parts = raw.split(':');
  var mod = parts[0], type = parts[1], id = parseInt(parts[2], 10);
  if(parts.length !== 3 || !(entityTypes[mod] || []).includes(type) || !Number.isSafeInteger(id) || id <= 0) return;
  window.history.replaceState({}, '', window.location.pathname);
  fetch('/evidence/api/search-entities?module=' + encodeURIComponent(mod) + '&entity_type=' + encodeURIComponent(type) + '&entity_id=' + id)
    .then(function(r){ return r.ok ? r.json() : []; })
    .then(function(found){
      var hit = found && found[0];
      if(!hit || !hit.name || hit.id !== id) return;
      ModalManager.open('uploadModal');
      var m = document.getElementById('uploadLinkModule'); m.value = mod; uploadTargetModuleChanged();
      document.getElementById('uploadLinkType').value = type;
      uploadTarget = {module: mod, entity_type: type, entity_id: id};
      var selected = document.getElementById('uploadLinkSelected');
      selected.querySelector('span').textContent = 'Selected: ' + hit.name + ' (#' + id + ')';
      selected.style.display = 'flex';
    }).catch(function(){});
})();

/* ── PLAN-06 deep-link boot handler ── */
(function(){
  var openParam = new URLSearchParams(window.location.search).get('open');
  if(!openParam) return;
  var sep = openParam.indexOf(':');
  if(sep < 1) return;
  var etype = openParam.slice(0, sep);
  var eid = parseInt(openParam.slice(sep + 1), 10);
  if(!eid) return;
  window.history.replaceState({}, '', window.location.pathname);
  var tries = 0;
  function attempt(){
    tries++;
    try { _plan06_fn(eid); } catch(e){ if(tries < 20) setTimeout(attempt, 250); }
  }
  var _plan06_openers = {
    'item': function(id){ openDetail(id); }
  };
  var _plan06_fn = _plan06_openers[etype];
  if(!_plan06_fn) return;
  attempt();
})();

/* Retention of a confirmed document register source workbook: its own deletion date and legal hold. */
function evRenderSourceRetention(item,eid){
  var host=document.getElementById('evSourceRetention');
  var info=item&&item.source_retention;
  if(!host||!info)return;
  host.replaceChildren();
  var box=document.createElement('div');box.className='ev-section';
  var title=document.createElement('div');title.className='ev-section-title';title.textContent='Source workbook retention';
  var state=document.createElement('p');state.style.cssText='font-size:12px;margin:0 0 8px';
  if(info.purged_at){
    state.textContent='The file was removed under retention on '+String(info.purged_at).slice(0,10)+
      '. Its record and SHA-256 hash '+String(info.purged_hash||'').slice(0,16)+'... stay, so register entries still show their source.';
  }else{
    state.textContent=(info.hold_reason?'On legal hold: '+info.hold_reason+'. Nothing is removed while the hold stands. ':'')+
      (info.delete_after?'File removal date: '+info.delete_after+'.':'No removal date: the file is kept.');
  }
  box.append(title,state);
  if(item.can_manage_source_retention&&!info.purged_at){
    var form=document.createElement('form');form.style.cssText='display:grid;gap:6px;font-size:12px';
    function field(labelText,input){var l=document.createElement('label');l.style.cssText='display:grid;gap:2px';var s=document.createElement('span');s.textContent=labelText;l.append(s,input);return l;}
    var dateInput=document.createElement('input');dateInput.type='date';dateInput.value=info.delete_after||'';
    var holdInput=document.createElement('input');holdInput.type='text';holdInput.maxLength=500;holdInput.value=info.hold_reason||'';
    holdInput.placeholder='Leave empty for no hold';
    var reasonInput=document.createElement('input');reasonInput.type='text';reasonInput.required=true;reasonInput.minLength=10;reasonInput.maxLength=500;
    var save=document.createElement('button');save.type='submit';save.className='btn btn-secondary';save.style.cssText='font-size:12px;padding:6px 14px;justify-self:start';save.textContent='Save retention';
    var status=document.createElement('p');status.setAttribute('role','status');status.style.cssText='font-size:12px;margin:0';
    form.append(field('Remove the file after (leave empty to keep it)',dateInput),field('Legal hold reason',holdInput),
      field('Why this is changing',reasonInput),save,status);
    form.addEventListener('submit',async function(event){
      event.preventDefault();save.disabled=true;status.textContent='Saving...';
      try{
        var result=await ApiClient.request('/evidence/api/items/'+Number(eid)+'/source-retention',{method:'POST',
          actionId:'evidence.source_retention.save',
          body:{delete_after:dateInput.value||null,hold_reason:holdInput.value||null,reason:reasonInput.value}});
        item.source_retention=result.source_retention;evRenderSourceRetention(item,eid);
        var done=document.querySelector('#evSourceRetention [role=status]');if(done)done.textContent='Retention saved.';
      }catch(error){save.disabled=false;status.textContent=(error&&error.detail)||'Retention could not be saved.';}
    });
    box.appendChild(form);
  }
  host.appendChild(box);
}
