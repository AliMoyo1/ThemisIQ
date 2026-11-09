(function(){
'use strict';

var ormPageConfig=document.getElementById('ormPageConfig');
var ORM_CURRENT_USER_ID=Number(ormPageConfig.dataset.userId);

/* Fixed ORM page controls. These handlers are source-controlled functions, never evaluated from HTML. */
var ormStaticActions={
  s0:function(event){ormOpenEventModal()},
  s1:function(event){this.closest('#ormOnboardBanner').style.display='none';localStorage.setItem('hide_orm_onboard','1')},
  s2:function(event){this.parentElement.style.opacity=this.checked?.5:1},
  s3:function(event){event.preventDefault();ormOpenLogModal()},
  s4:function(event){event.preventDefault();ormRouter.navigate('/orm/indicators')},
  s5:function(event){event.preventDefault();ormRouter.navigate('/orm/rcsa')},
  s6:function(event){ormExportCSV()},
  s7:function(event){ormOpenTemplates()},
  s8:function(event){ormChipStatus(this)},
  s9:function(event){ormChipType(this)},
  s10:function(event){evtFilters.search=this.value.trim().toLowerCase();ormRenderEvents()},
  s11:function(event){evtFilters.sev=this.value;ormRenderEvents()},
  s12:function(event){evtFilters.dept=this.value;ormRenderEvents()},
  s13:function(event){ormSelectAll(this.checked)},
  s14:function(event){ormOpenKriLibrary()},
  s15:function(event){ormOpenKriModal()},
  s16:function(event){window.open('/orm/api/board-report/document','_blank')},
  s17:function(event){ormBoardReport(this)},
  s18:function(event){ormOpenRcsaModal()},
  s19:function(event){ormOpenTemplatePickerModal()},
  s20:function(event){ormOpenAiControlModal()},
  s21:function(event){ormChipAicPillar(this)},
  s22:function(event){ormRenderAicRows()},
  s23:function(event){ormOpenAimsModal()},
  s24:function(event){ormSendPromptChip('What are my top financial loss events this month?')},
  s25:function(event){ormSendPromptChip('Suggest corrective actions for recurring process failures')},
  s26:function(event){ormSendPromptChip('Which departments have the most operational risk events?')},
  s27:function(event){ormSendPromptChip('Help me write a board summary of operational risk this month')},
  s28:function(event){if(event.key==='Enter')ormSendChat()},
  s29:function(event){ormSendChat()},
  s30:function(event){ormBulkStatus()},
  s31:function(event){ormBulkDelete()},
  s32:function(event){ormBulkClear()},
  s33:function(event){if(event.target===this)ormCloseDoc()},
  s34:function(event){navigator.clipboard.writeText(_ormDocContent).then(function(){typeof showToast==='function'&&showToast('Copied!')})},
  s35:function(event){ormCloseDoc()},
  s36:function(event){event.preventDefault();ormOpenLogModal()},
  s37:function(event){if(event.target===this)this.remove()},
  s38:function(event){document.getElementById('ormBulkStatusModal').remove()},
  s39:function(event){ormBulkStatusApply()},
  s40:function(event){this.closest('.orm-modal-overlay').remove()},
  s41:function(event){if(event.target===this)ormCloseDrawer()},
  s42:function(event){ormCloseDrawer()},
  s43:function(event){ormOpenEventModal(window._ormDrawerEvt);ormCloseDrawer()},
  s44:function(event){document.getElementById('ormEvtModal').remove()},
  s45:function(event){document.getElementById('oe_resolved_row').style.display=(this.value==='resolved'||this.value==='closed')?'block':'none'},
  s46:function(event){document.getElementById('kriModal').remove()},
  s47:function(event){if(event.target===this)ormCloseTemplates()},
  s48:function(event){event.stopPropagation()},
  s49:function(event){tmplSearch=this.value.toLowerCase();ormRenderTemplates()},
  s50:function(event){ormOpenTemplateModal()},
  s51:function(event){ormCloseTemplates()},
  s52:function(event){document.getElementById('ormTmplEditModal').remove()},
  s53:function(event){document.getElementById('rcsaModal').remove()},
  s54:function(event){ormCloseDrawer();ormRouter.navigate('/orm/assessment')},
  s55:function(event){document.getElementById('rcsaRiskModal').remove()},
  s56:function(event){document.getElementById('rr_ce_val').textContent=this.value},
  s57:function(event){document.getElementById('rcsaControlModal').remove()},
  s58:function(event){document.getElementById('rcsaActionModal').remove()},
  s59:function(event){document.getElementById('aicModal').remove()},
  s60:function(event){document.getElementById('aimsModal').remove()},
  s61:function(event){document.getElementById('aimsRiskModal').remove()},
  s62:function(event){document.getElementById('ar_just_row').style.display=this.value==='0'?'block':'none'},
  s63:function(event){document.getElementById('aimsRcModal').remove()},
  s64:function(event){if(event.key==='Enter')this.blur();if(event.key==='Escape')ormLoadKris();},
  s65:function(event){document.getElementById('kriUpdateModal').remove()},
  s66:function(event){document.getElementById('kumDisplay').textContent=this.value},
};
['click','change','input','keydown'].forEach(function(kind){
  document.addEventListener(kind,function(event){
    var target=event.target instanceof Element ? event.target.closest('[data-orm-static-'+kind+']') : null;
    if(!target)return;
    var handler=ormStaticActions[target.getAttribute('data-orm-static-'+kind)];
    if(!handler)return;
    if(handler.call(target,event)===false)event.preventDefault();
  });
});


/* Generated record actions only accept checked IDs and reviewed function names. */
function ormAttrId(value){var id=Number(value);return Number.isSafeInteger(id)&&id>0?String(id):'';}
function ormReadId(value){var id=Number(value);return value!==''&&Number.isSafeInteger(id)&&id>0?id:null;}
var ormRecordCalls=new Set(['ormAddAimsRisk','ormAddRcsaRisk','ormAiAnalyze','ormAiAnalyzeFromDrawer','ormCustomiseTemplate','ormDeleteAiControl','ormDeleteAims','ormDeleteAimsRiskControl','ormDeleteEvt','ormDeleteKri','ormDeleteRcsa','ormDeleteRcsaAction','ormDeleteRcsaControl','ormDuplicateEvt','ormEditAiControl','ormElevateToErm','ormInlineKriEdit','ormOpenAimsDetail','ormOpenAimsRiskDetail','ormOpenEventDrawer','ormOpenRcsaDetail','ormSaveKriUpdate','ormSaveRcsaRisk','ormToggleWfHistory']);
document.addEventListener('click',function(event){
  var target=event.target instanceof Element?event.target.closest('[data-orm-call]'):null;
  if(!target)return;
  var name=target.dataset.ormCall;
  if(!ormRecordCalls.has(name))return;
  var id=ormReadId(target.dataset.ormId||'');
  if(id===null)return;
  var second=target.dataset.ormId2;
  if(second!==undefined){second=ormReadId(second);if(second===null)return;}
  var action=window[name];
  if(typeof action!=='function')return;
  if(target.dataset.ormThis==='1')action(id,target);
  else if(second!==undefined)action(id,second);
  else action(id);
});


var ormCacheCalls={
  ormOpenEventModal:function(){return evtCache;},
  ormOpenKriUpdateModal:function(){return kriCache;},
  ormOpenKriModal:function(){return kriCache;},
  ormOpenRcsaModal:function(){return rcsaCache;},
  ormOpenAimsModal:function(){return aimsCache;}
};
var ormSaveCalls=new Set(['ormSaveEvent','ormSaveKri','ormSaveTemplate','ormSaveRcsa','ormSaveAiControl','ormSaveAims']);
document.addEventListener('click',function(event){
  var el=event.target instanceof Element?event.target.closest('[data-orm-cache-call],[data-orm-save-call]'):null;
  if(!el)return;
  if(el.dataset.ormCacheCall){
    var name=el.dataset.ormCacheCall;
    if(!Object.hasOwn(ormCacheCalls,name))return;
    var id=ormReadId(el.dataset.ormId||'');if(id===null)return;
    var record=ormCacheCalls[name]().find(function(x){return ormReadId(String(x.id))===id;});
    if(record&&typeof window[name]==='function')window[name](record);
    return;
  }
  var saveName=el.dataset.ormSaveCall;
  if(!ormSaveCalls.has(saveName)||typeof window[saveName]!=='function')return;
  var edit=el.dataset.ormSaveEdit==='1';
  var saveId=edit?ormReadId(el.dataset.ormSaveId||''):null;
  if(edit&&saveId===null)return;
  window[saveName](saveId);
});


document.addEventListener('change',function(event){
  var el=event.target instanceof Element?event.target.closest('[data-orm-select-id]'):null;
  if(!el)return;
  var id=ormReadId(el.dataset.ormSelectId||'');
  if(id!==null)ormToggleSelect(id,el.checked);
});
document.addEventListener('click',function(event){
  var el=event.target instanceof Element?event.target.closest('[data-orm-special]'):null;
  if(!el)return;
  var kind=el.dataset.ormSpecial;
  if(kind==='kri-filter'){ormKriFilter(el.dataset.ormFilter||'');return;}
  if(kind==='tmpl-cat'){ormTmplCat(el,el.dataset.cat||'');return;}
  var id=ormReadId(el.dataset.ormId||'');if(id===null)return;
  if(kind==='open-event-close'){event.preventDefault();ormOpenEventDrawer(id);ormCloseDrawer();}
  else if(kind==='elevate-close'){ormElevateToErm(id);ormCloseDrawer();}
  else if(kind==='kri-update'){
    event.preventDefault();var kri=kriCache.find(function(x){return ormReadId(String(x.id))===id;});
    if(kri)ormOpenKriUpdateModal(kri);
  }
  else if(kind==='advance-workflow'){
    var step=el.dataset.ormStep;
    if(WF_STEPS.some(function(item){return item.key===step;}))ormAdvanceWorkflow(id,step);
  }
  else if(kind==='toggle-recurring'||kind==='toggle-ai-control'){
    var toggle=el.dataset.ormToggle;if(toggle!=='0'&&toggle!=='1')return;
    if(kind==='toggle-recurring')ormToggleRecurring(id,Number(toggle));
    else ormToggleAiControlActive(id,Number(toggle));
  }
});

/* Nested RCSA, AIMS and KRI controls carry IDs as data, never script source. */
document.addEventListener('click',function(event){
  var el=event.target instanceof Element?event.target.closest('[data-orm-complex],[data-orm-adjust]'):null;
  if(!el)return;
  if(el.dataset.ormAdjust){
    var adjustment=el.dataset.ormAdjust;
    if(!['+1','+5','+10','Reset'].includes(adjustment))return;
    var input=document.getElementById('kum_val');
    var display=document.getElementById('kumDisplay');
    if(!input||!display)return;
    input.value=adjustment==='Reset'?'0':String((parseFloat(input.value)||0)+Number(adjustment));
    display.textContent=input.value;
    return;
  }
  var kind=el.dataset.ormComplex;
  var id=ormReadId(el.dataset.ormId||'');
  var id2=ormReadId(el.dataset.ormId2||'');
  var id3=ormReadId(el.dataset.ormId3||'');
  if(id===null)return;
  var edit=el.dataset.ormEdit==='1';
  var rcsa=rcsaCache.find(function(x){return ormReadId(String(x.id))===id;});
  var aims=aimsCache.find(function(x){return ormReadId(String(x.id))===id;});
  if(kind==='rcsa-control-add'&&id2!==null)ormOpenRcsaControlModal(id,null,id2);
  else if(kind==='rcsa-control-edit'&&id2!==null&&id3!==null&&window._rcsaControlsCache&&Object.hasOwn(window._rcsaControlsCache,id2))
    ormOpenRcsaControlModal(id,window._rcsaControlsCache[id2],id3);
  else if(kind==='rcsa-action-add'&&id2!==null)ormOpenRcsaActionModal(id,null,id2);
  else if(kind==='rcsa-action-edit'&&id2!==null&&id3!==null&&window._rcsaActionsCache&&Object.hasOwn(window._rcsaActionsCache,id2))
    ormOpenRcsaActionModal(id,window._rcsaActionsCache[id2],id3);
  else if(kind==='rcsa-edit-close'&&rcsa){ormOpenRcsaModal(rcsa);ormCloseDrawer();}
  else if(kind==='rcsa-control-save'&&id3!==null&&(!edit||id2!==null))ormSaveRcsaControl(id,edit?id2:null,id3);
  else if(kind==='rcsa-action-save'&&id3!==null&&(!edit||id2!==null))ormSaveRcsaAction(id,edit?id2:null,id3);
  else if(kind==='aims-edit-close'&&aims){ormOpenAimsModal(aims);ormCloseDrawer();}
  else if(kind==='aims-risk-save'&&(!edit||id2!==null))ormSaveAimsRisk(id,edit?id2:null);
  else if(kind==='aims-control-edit'&&id2!==null){
    var detail=window._aimsRiskDetailCache&&Object.hasOwn(window._aimsRiskDetailCache,id)?window._aimsRiskDetailCache[id]:null;
    var control=detail&&Array.isArray(detail.controls)?detail.controls.find(function(x){return ormReadId(String(x.id))===id2;}):null;
    if(control)ormOpenAimsRiskControlModal(id,control);
  }
  else if(kind==='aims-control-add')ormOpenAimsRiskControlModal(id,null);
  else if(kind==='aims-risk-edit-close'&&id2!==null){
    var risk=window._aimsRiskDetailCache&&Object.hasOwn(window._aimsRiskDetailCache,id2)?window._aimsRiskDetailCache[id2]:null;
    if(risk){ormEditAimsRisk(id,risk);ormCloseDrawer();}
  }
  else if(kind==='aims-risk-delete-close'&&id2!==null){ormDeleteAimsRisk(id,id2);ormCloseDrawer();}
  else if(kind==='aims-control-save'&&(!edit||id2!==null))ormSaveAimsRiskControl(id,edit?id2:null);
});
document.addEventListener('blur',function(event){
  var el=event.target;
  if(!(el instanceof Element)||!el.hasAttribute('data-orm-inline-id'))return;
  var id=ormReadId(el.dataset.ormInlineId||'');
  if(id!==null)ormInlineKriSave(id,el);
},true);

/* ─────────────────────────── HELPERS ─────────────────────────── */
function esc(s){if(!s)return'';var d=document.createElement('div');d.textContent=String(s);return d.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
document.addEventListener('click',function(event){
  var button=event.target.closest('.js-activate-orm-template');
  if(button)ormActivateTemplate(Number(button.dataset.templateId),button.dataset.templateTitle);
});
function escChartAttr(s){return esc(s).replace(/"/g,'&quot;');}
function fmtDate(ts){if(!ts)return'—';var value=String(ts);var d=new Date(value.length===10?value+'T00:00:00':value.replace(' ','T'));if(isNaN(d.getTime()))return'Invalid date';return d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});}
function timeAgo(ts){if(!ts)return'';var s=Math.floor((Date.now()-new Date(ts.includes('T')?ts:ts+'Z').getTime())/1000);if(s<60)return'just now';if(s<3600)return Math.floor(s/60)+'m ago';if(s<86400)return Math.floor(s/3600)+'h ago';return Math.floor(s/86400)+'d ago';}
function fmtCurrency(v){v=parseFloat(v)||0;if(v>=1000000)return'$'+(v/1000000).toFixed(1)+'M';if(v>=1000)return'$'+(v/1000).toFixed(1)+'K';return'$'+v.toFixed(0);}
function sevBadge(s){var m={critical:'badge-critical',high:'badge-high',medium:'badge-medium',low:'badge-low'};return'<span class="badge '+(m[(s||'').toLowerCase()]||'badge-draft')+'">'+esc((s||'?').toUpperCase())+'</span>';}
function statusBadge(s){var m={open:'badge-high',investigating:'badge-progress',resolved:'badge-complete',closed:'badge-draft',recurring:'badge-critical'};var lbl=(s||'').replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();});return'<span class="badge '+(m[s]||'badge-draft')+'">'+esc(lbl)+'</span>';}
var typeIcons={process_failure:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-settings></use></svg>',fraud:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-siren></use></svg>',system_failure:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-laptop></use></svg>',human_error:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-user></use></svg>',outage:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-plug></use></svg>',vendor_failure:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-package></use></svg>',customer_impact:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-users></use></svg>'};
function typeIcon(t){return typeIcons[t]||'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg>';}
function spinner(cols){return'<tr><td colspan="'+cols+'" data-s="s2e587c2"><div class="spinner" data-s="s266e9b0"></div></td></tr>';}
function emptyRow(cols,msg){return'<tr><td colspan="'+cols+'" data-s="s2e587c2">'+esc(msg||'No records found')+'</td></tr>';}
async function apiFetch(url,opts){
  // PLAN-36 T06 (findings.md F08): delegates to the shared ApiClient --
  // see modules/erm/templates/index.html's identical migration.
  opts=opts||{};
  return ApiClient.request(url, { method: opts.method, body: opts.body, headers: opts.headers, actionId: url });
}
function populateStatCards(elId,cards){
  var el=document.getElementById(elId);if(!el)return;
  el.innerHTML=cards.map(function(c){
    return'<div class="stat-card" data-s="sab42f28">'+
      '<div data-s="s5ba562e">'+esc(c.label)+'</div>'+
      '<div data-sv="font-size:22px;font-weight:800;color:'+(c.color||'var(--text)')+';line-height:1">'+esc(String(c.value))+'</div>'+
      (c.sub?'<div data-s="s8a05498">'+esc(c.sub)+'</div>':'')+
    '</div>';
  }).join('');
  el.querySelectorAll('.stat-card').forEach(function(card){
    card.addEventListener('mousemove',function(e){var r=card.getBoundingClientRect();var x=(e.clientX-r.left)/r.width-0.5;var y=(e.clientY-r.top)/r.height-0.5;card.style.transform='perspective(600px) rotateX('+(-y*8)+'deg) rotateY('+(x*8)+'deg) translateY(-2px)';});
    card.addEventListener('mouseleave',function(){card.style.transform='';});
  });
}

/* Trend arrow — invertColor=true means upward delta is bad (more events = worse) */
function trendArrow(n,invertColor){
  if(n===0||n===null||n===undefined)return'<span data-s="s57f9e31">— 0 vs 30d</span>';
  var isUp=n>0;
  var isBad=invertColor?isUp:!isUp;
  var col=isBad?'var(--red)':'var(--good,#16a34a)';
  var sym=isUp?'▲':'▼';
  return'<span data-sv="color:'+col+';font-weight:700">'+sym+' '+Math.abs(n)+' vs 30d</span>';
}

/* KRI tri-zone gauge */
function ormKriGauge(val,warn,crit){
  var maxVal=crit?crit*1.25:warn?warn*1.5:(val>0?val*1.5:10);
  var warnPct=warn?(warn/maxVal*100).toFixed(1):0;
  var critPct=crit?(crit/maxVal*100).toFixed(1):100;
  var curPct=Math.min(100,(val/maxVal*100)).toFixed(1);
  var fillColor=crit&&val>=crit?'var(--red,#dc2626)':warn&&val>=warn?'var(--amber,#d97706)':'var(--good,#16a34a)';
  return'<div data-s="sab3f02b">'+
    '<div data-sv="position:absolute;inset:0;background:linear-gradient(to right,var(--good,#16a34a) '+warnPct+'%,var(--amber,#d97706) '+warnPct+'% '+critPct+'%,var(--red,#dc2626) '+critPct+'% 100%);opacity:.2"></div>'+
    '<div class="kri-gauge-fill" data-sv="position:absolute;top:0;left:0;height:100%;width:'+curPct+'%;background:'+fillColor+';border-radius:100px;transition:width .6s ease"></div>'+
  '</div>';
}

/* Ring (donut) chart — segments=[{label,count,color}] */
function ormDrawRing(wrapperId,legendId,segments){
  var wrap=document.getElementById(wrapperId);
  var leg=document.getElementById(legendId);
  if(!wrap)return;
  var C=314.16;
  var total=segments.reduce(function(s,x){return s+(x.count||0);},0);
  var offset=0;
  var arcs=segments.map(function(seg){
    var len=total>0?(seg.count/total)*C:0;
    var rotDeg=(offset/C)*360-90;
    offset+=len;
    if(!len)return'';
    return'<circle cx="60" cy="60" r="50" fill="none" stroke="'+seg.color+'" stroke-width="11" '+
      'stroke-dasharray="'+len.toFixed(2)+' '+C+'" '+
      'transform="rotate('+rotDeg.toFixed(1)+' 60 60)"><title>'+esc(seg.label)+': '+esc(String(seg.count))+'</title></circle>';
  }).join('');
  wrap.innerHTML=
    '<div data-s="sf01cea7" data-sd="inline-flex">'+
    '<svg class="orm-ring-chart" viewBox="0 0 120 120" data-s="s4c4fcf9">'+
    '<circle cx="60" cy="60" r="50" fill="none" stroke="var(--chart-track,var(--surface3))" stroke-width="11"/>'+arcs+'</svg>'+
    '<div data-s="s78fecfb"><div data-s="se1004b5">'+total+'</div><div data-s="s1c1097e">Total</div></div>'+
    '</div>';
  if(leg){
    leg.innerHTML=segments.map(function(s){
      var pct=total>0?Math.round((s.count/total)*100):0;
      return'<div data-s="s970774d" data-sd="flex">'+
        '<div data-sv="width:9px;height:9px;border-radius:50%;background:'+s.color+';flex-shrink:0"></div>'+
        '<span data-s="sc6fddc1">'+esc(s.label)+'</span>'+
        '<span data-s="sbed9cea">'+s.count+'</span>'+
        '<span data-s="sf572c93">'+pct+'%</span>'+
      '</div>';
    }).join('');
  }
}

/* ─────────────────────────── DOC VIEWER ─────────────────────────── */
var _ormDocContent='';
window.ormOpenDocViewer=function(title,content){
  _ormDocContent=content||'';
  document.getElementById('ormDocRoot').innerHTML=
    '<div class="orm-doc-overlay" data-orm-static-click="s33">'+
    '<div class="orm-doc-panel">'+
      '<div class="orm-doc-head">'+
        '<div data-s="sf3960c7">'+esc(title)+'</div>'+
        '<div data-s="sf0abc1d" data-sd="flex">'+
          '<button class="btn btn-sm btn-secondary" data-orm-static-click="s34">Copy</button>'+
          '<button class="btn btn-sm btn-secondary" data-orm-static-click="s35">&#10005;</button>'+
        '</div>'+
      '</div>'+
      '<div class="orm-doc-body">'+esc(content)+'</div>'+
    '</div></div>';
};
window.ormCloseDoc=function(){document.getElementById('ormDocRoot').innerHTML='';};

/* ─────────────────────────── SPA ROUTER ─────────────────────────── */
var ormRoutes={'/orm/':'dashboard','/orm':'dashboard','/orm/events':'events','/orm/indicators':'indicators','/orm/reports':'reports','/orm/chat':'chat','/orm/assessment':'assessment','/orm/ai-controls':'ai-controls','/orm/aims':'aims'};
var ormBreadcrumbs={dashboard:'Dashboard',events:'Events',indicators:'KRI Indicators',reports:'Reports',chat:'Ask ORM AI',assessment:'RCSA','ai-controls':'AI Controls',aims:'AI Risk (AIMS)'};
var ormRouter={
  current:null,
  navigate:function(path,replace){if(replace)history.replaceState(null,'',path);else history.pushState(null,'',path);this.resolve();},
  resolve:function(){
    var path=location.pathname.replace(/\/$/,'')||'/orm';
    var view=ormRoutes[path]||'dashboard';
    if(view===this.current)return;
    this.current=view;
    document.querySelectorAll('.spa-view').forEach(function(v){v.classList.remove('active');});
    var el=document.getElementById('view-'+view);if(el)el.classList.add('active');
    var bc=document.getElementById('ormBreadcrumb');if(bc)bc.textContent=ormBreadcrumbs[view]||view;
    document.querySelectorAll('[data-spa]').forEach(function(a){a.classList.remove('active');var t=a.getAttribute('data-spa').replace(/\/$/,'')||'/orm';if(t===path)a.classList.add('active');});
    this.load(view);
  },
  load:function(view){
    switch(view){
      case'dashboard':  ormLoadDashboard();break;
      case'events':     ormLoadEvents();break;
      case'indicators': ormLoadKris();break;
      case'reports':    ormLoadReports();break;
      case'chat':       ormLoadChat();break;
      case'assessment': ormLoadRcsa();break;
      case'ai-controls': ormLoadAiControls();break;
      case'aims':       ormLoadAims();break;
    }
  }
};
document.addEventListener('click',function(e){var a=e.target.closest('[data-spa]');if(a){e.preventDefault();ormRouter.navigate(a.getAttribute('data-spa'));}});
window.addEventListener('popstate',function(){ormRouter.resolve();});

/* ─────────────────────────── USERS CACHE ─────────────────────────── */
var usersCache=null;
async function ormLoadUsers(){
  if(usersCache)return usersCache;
  try{usersCache=await apiFetch('/orm/api/users');}catch(e){usersCache=[];}
  return usersCache||[];
}

/* ─────────────────────────── DASHBOARD ─────────────────────────── */
async function ormLoadDashboard(){
  try{
    var d=await apiFetch('/orm/api/dashboard');
    document.getElementById('ormLastUpdated').textContent='just now';

    // SLA overdue banner
    var slaBanner=document.getElementById('ormSlaBanner');
    var slaCount=document.getElementById('ormSlaCount');
    if(slaBanner){
      var slaOvd=d.sla_overdue||0;
      slaBanner.style.display=slaOvd>0?'flex':'none';
      if(slaCount)slaCount.textContent=slaOvd;
    }

    // Sentinel banner
    var sb=document.getElementById('ormSentinelBanner');
    if(sb)sb.style.display=d.active_sentinel_breach?'flex':'none';

    // BCM banner
    var bb=document.getElementById('ormBcmBanner');
    if(bb)bb.style.display=d.active_bcm_incident?'flex':'none';

    var sourceWarning=document.getElementById('ormSourceWarning');
    if(sourceWarning){
      var missing=[];
      if(d.active_bcm_incident===null)missing.push('Resilience incidents');
      if(d.active_sentinel_breach===null)missing.push('Privacy breaches');
      sourceWarning.style.display=missing.length?'block':'none';
      sourceWarning.textContent=missing.length?missing.join(' and ')+' could not be checked in this view. The absence of an alert does not confirm a clear status.':'';
    }

    // KRI alerts banner
    var kBanner=document.getElementById('ormKriBanner');
    if(kBanner){
      if(d.kri_alerts&&d.kri_alerts.length){
        kBanner.style.display='';
        kBanner.innerHTML='<div data-s="s25d9341" data-sd="flex">'+
          '<span data-s="s1444c6e"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg></span>'+
          '<span><strong>Organization-wide KRI Alerts:</strong> '+d.kri_alerts.map(function(k){return esc(k.name)+' ('+k.value+') is <strong>'+k.level+'</strong>';}).join(', ')+'</span>'+
          '<a href="/orm/indicators" data-spa="/orm/indicators" data-s="sf817d4b">View KRIs →</a>'+
        '</div>';
      }else{kBanner.style.display='none';}
    }

    // KRI status strip
    var kStrip=document.getElementById('ormKriStrip');
    var kDots=document.getElementById('ormKriStripDots');
    if(kStrip&&kDots&&d.kri_alerts&&d.kri_alerts.length){
      kStrip.style.display='flex';
      // Show all KRI alerts as colored dots
      kDots.innerHTML=d.kri_alerts.map(function(k){
        var col=k.level==='critical'?'var(--red)':k.level==='warning'?'var(--amber,#d97706)':'var(--good,#16a34a)';
        return'<span data-s="scd918fa" data-sd="inline-flex">'+
          '<span data-sv="width:7px;height:7px;border-radius:50%;background:'+col+'"></span>'+esc(k.name)+'</span>';
      }).join('');
      // Show badge on sidebar
      var sideAlert=document.getElementById('ormNavKriAlert');
      if(sideAlert){var critCount=d.kri_alerts.filter(function(k){return k.level==='critical';}).length;sideAlert.style.display=critCount?'':'none';sideAlert.textContent=critCount;}
    }else{
      if(kStrip)kStrip.style.display='none';
      var sideAlert=document.getElementById('ormNavKriAlert');
      if(sideAlert)sideAlert.style.display='none';
    }

    // Trend arrows on stat cards (all are "higher = worse" for ORM)
    document.getElementById('dTotalEvts').textContent=d.total_events||0;
    document.getElementById('dEvtDelta').innerHTML=trendArrow(d.total_events_delta||0,true);
    document.getElementById('dFinLoss').textContent=fmtCurrency(d.financial_loss||0);
    document.getElementById('dFinDelta').innerHTML=trendArrow(Math.round(d.financial_loss_delta||0),true);
    document.getElementById('dCustomers').textContent=(d.customers_affected||0).toLocaleString();
    document.getElementById('dCustDelta').innerHTML=trendArrow(d.customers_delta||0,true);
    document.getElementById('dDowntime').textContent=d.downtime_hours||0;
    document.getElementById('dDownDelta').innerHTML=trendArrow(d.downtime_delta||0,true);

    // Nav count
    var navEvts=document.getElementById('ormNavEvents');if(navEvts)navEvts.textContent=d.total_events||0;

    // Smart Insights
    var insights=[];
    var recurring=(d.recent_events||[]).filter(function(e){return e.is_recurring;}).length;
    var byType=d.by_type||[];
    var total=d.total_events||0;
    if(total===0)insights.push('&#10003; No events recorded in the last 30 days');
    if(recurring>0)insights.push('<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-refresh-cw></use></svg> <strong>'+recurring+'</strong> recurring event'+(recurring>1?'s':'')+' this period — consider root cause analysis');
    var fraudRow=byType.find(function(t){return t.event_type==='fraud';});
    if(fraudRow&&fraudRow.cnt>0)insights.push('<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-siren></use></svg> <strong>'+fraudRow.cnt+'</strong> fraud event'+(fraudRow.cnt>1?'s':'')+' — review for data exposure with Sentinel');
    var sysRow=byType.find(function(t){return t.event_type==='system_failure'||t.event_type==='outage';});
    if(sysRow&&sysRow.cnt>0)insights.push('<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-laptop></use></svg> <strong>'+sysRow.cnt+'</strong> system/outage event'+(sysRow.cnt>1?'s':'')+' — check BCM plans');
    if(d.financial_loss_delta>0)insights.push('<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-trending-up></use></svg> Financial loss up <strong>'+fmtCurrency(d.financial_loss_delta)+'</strong> vs previous period');
    else if(d.financial_loss_delta<0)insights.push('&#10003; Financial loss down <strong>'+fmtCurrency(Math.abs(d.financial_loss_delta))+'</strong> vs previous period');
    var resolved=byType.reduce(function(s,t){return s+(t.cnt||0);},0);
    if(d.kri_alerts&&d.kri_alerts.length>0)insights.push('<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg> <strong>'+d.kri_alerts.length+'</strong> KRI'+( d.kri_alerts.length>1?'s':'')+' breaching thresholds');
    var insEl=document.getElementById('ormInsights');
    if(insEl)insEl.innerHTML=insights.length?insights.map(function(i){return'<div data-s="s4673a44">'+i+'</div>';}).join(''):'<div data-s="s57f9e31">No significant insights this period.</div>';

    // Events by type chart
    ormRenderTypeChart('ormTypeChart',d.by_type||[]);

    // Top 5
    var top5El=document.getElementById('ormTop5');
    if(top5El){
      if(!d.top5_by_impact||!d.top5_by_impact.length){top5El.innerHTML='<div data-s="s84c452e">No financial impact recorded</div>';}
      else{top5El.innerHTML=d.top5_by_impact.map(function(e,i){
        return'<div data-s="s151932e" data-sd="flex" data-orm-call="ormOpenEventDrawer" data-orm-id="'+ormAttrId(e.id)+'">'+
          '<div data-s="sdd1819a">'+(i+1)+'.</div>'+
          '<div data-s="s59eddc6">'+
            '<div data-s="sab15306">'+esc(e.title)+'</div>'+
            '<div data-s="s1fd8c81">'+typeIcon(e.event_type)+' '+esc((e.event_type||'').replace(/_/g,' '))+'</div>'+
          '</div>'+
          sevBadge(e.severity)+
          '<div data-s="sb987f87">'+fmtCurrency(e.financial_impact)+'</div>'+
        '</div>';
      }).join('');}
    }

    // Recent events table
    var recent=d.recent_events||[];
    var rBody=document.getElementById('ormRecentBody');
    if(rBody){
      if(!recent.length){rBody.innerHTML=emptyRow(6,'No events yet');}
      else{rBody.innerHTML=recent.map(function(e){
        return'<tr>'+
          '<td data-s="s49b2015" data-orm-call="ormOpenEventDrawer" data-orm-id="'+ormAttrId(e.id)+'">'+esc(e.title||'')+'</td>'+
          '<td>'+typeIcon(e.event_type)+' <span data-s="s1fd8c81">'+esc((e.event_type||'').replace(/_/g,' '))+'</span></td>'+
          '<td>'+sevBadge(e.severity)+'</td>'+
          '<td data-sv="font-weight:700;color:'+(e.financial_impact>0?'var(--red)':'var(--muted)')+'">'+fmtCurrency(e.financial_impact||0)+'</td>'+
          '<td>'+statusBadge(e.status)+'</td>'+
          '<td data-s="s7fc448e">'+timeAgo(e.created_at)+'</td>'+
        '</tr>';
      }).join('');}
    }
    // Onboarding banner
    var ob=document.getElementById('ormOnboardBanner');
    if(ob&&!localStorage.getItem('hide_orm_onboard')){ob.style.display=(d.total_events||0)===0?'':'none';}
    // Quick-add link on zero-count stat card
    var qa=document.getElementById('dTotalEvts');
    if(qa&&(d.total_events||0)===0&&!qa.dataset.qaAdded){qa.dataset.qaAdded='1';qa.insertAdjacentHTML('afterend','<a href="#" data-orm-static-click="s36" data-s="s61d2d1c" data-sd="block">+ Log your first</a>');}
  }catch(e){console.error('ORM dashboard error',e);}
}

function ormRenderTypeChart(elId,byType){
  var el=document.getElementById(elId);if(!el)return;
  if(!byType||!byType.length){el.innerHTML='<div data-s="s686c270">No events recorded</div>';return;}
  var max=Math.max.apply(null,byType.map(function(t){return t.cnt;}));
  var total=byType.reduce(function(s,t){return s+(t.cnt||0);},0);
  var typeColors={process_failure:'#f59e0b',fraud:'#ef4444',system_failure:'#6366f1',human_error:'#ec4899',outage:'#8b5cf6',vendor_failure:'#14b8a6',customer_impact:'#f97316'};
  el.innerHTML=byType.map(function(t){
    var pct=max>0?Math.round((t.cnt/max)*100):0;
    var col=typeColors[t.event_type]||'var(--accent)';
    var sharePct=total>0?Math.round((t.cnt/total)*100):0;
    return'<div data-s="s761d3ad">'+
      '<div data-s="sc76ac38" data-sd="flex">'+
        '<span>'+typeIcon(t.event_type)+' '+esc((t.event_type||'').replace(/_/g,' '))+'</span>'+
        '<span data-s="s57f9e31">'+t.cnt+' ('+sharePct+'%)</span>'+
      '</div>'+
      '<div data-s="s54c335c" title="'+escChartAttr((t.event_type||'').replace(/_/g,' '))+': '+esc(String(t.cnt))+' events"><div class="premium-chart-bar" data-sv="height:100%;width:'+pct+'%;background:'+col+';border-radius:100px;transition:width .6s ease"></div></div>'+
    '</div>';
  }).join('');
}

/* ─────────────────────────── EVENTS ─────────────────────────── */
var evtCache=[];
var evtFilters={status:'',type:'',sev:'',dept:'',search:'',recurring:false};
var evtSelectedIds=new Set();

window.ormChipStatus=function(chip){
  chip.closest('.orm-filter-bar').querySelectorAll('.orm-chip').forEach(function(c){c.classList.remove('active');});
  chip.classList.add('active');
  var v=chip.dataset.val||'';
  evtFilters.recurring=(v==='recurring');
  evtFilters.status=v==='recurring'?'':v;
  ormRenderEvents();
};
window.ormChipType=function(chip){
  chip.closest('.orm-filter-bar').querySelectorAll('.orm-chip').forEach(function(c){c.classList.remove('active');});
  chip.classList.add('active');
  evtFilters.type=chip.dataset.val||'';
  ormRenderEvents();
};

window.ormLoadEvents=async function(){
  var body=document.getElementById('ormEvtBody');
  if(body)body.innerHTML=spinner(10);
  evtSelectedIds.clear();
  var bar=document.getElementById('ormBulkBar');if(bar)bar.style.display='none';
  try{
    var data=await apiFetch('/orm/api/events');
    evtCache=Array.isArray(data)?data:[];
    // Populate dept filter
    var deptSel=document.getElementById('evtDeptFilter');
    if(deptSel){
      var depts=[...new Set(evtCache.map(function(e){return e.department;}).filter(Boolean))].sort();
      deptSel.innerHTML='<option value="">All Departments</option>'+depts.map(function(d){return'<option value="'+esc(d)+'">'+esc(d)+'</option>';}).join('');
    }
    ormRenderEvents();
  }catch(err){if(body)body.innerHTML=emptyRow(9,'Failed to load events');}
};

function ormRenderEvents(){
  var filtered=evtCache.filter(function(e){
    if(evtFilters.recurring&&!e.is_recurring)return false;
    if(!evtFilters.recurring&&evtFilters.status&&e.status!==evtFilters.status)return false;
    if(evtFilters.type&&e.event_type!==evtFilters.type)return false;
    if(evtFilters.sev&&e.severity!==evtFilters.sev)return false;
    if(evtFilters.dept&&e.department!==evtFilters.dept)return false;
    if(evtFilters.search){
      var q=evtFilters.search;
      if(!((e.title||'').toLowerCase().includes(q)||(e.description||'').toLowerCase().includes(q)||(e.department||'').toLowerCase().includes(q)))return false;
    }
    return true;
  });

  var total=filtered.length;
  var open=filtered.filter(function(e){return e.status==='open'||e.status==='investigating';}).length;
  var totalLoss=filtered.reduce(function(s,e){return s+(parseFloat(e.financial_impact)||0);},0);
  var cust=filtered.reduce(function(s,e){return s+(parseInt(e.customers_affected)||0);},0);
  populateStatCards('evtStats',[
    {label:'Total',value:total},
    {label:'Open / Investigating',value:open,color:open>0?'var(--red)':'var(--good,#16a34a)'},
    {label:'Total Financial Loss',value:fmtCurrency(totalLoss),color:totalLoss>0?'var(--red)':'var(--text)'},
    {label:'Customers Affected',value:cust.toLocaleString()}
  ]);

  var body=document.getElementById('ormEvtBody');
  if(!body)return;
  if(!filtered.length){body.innerHTML=emptyRow(10,'No events match the current filters');return;}
  var now=Date.now();
  body.innerHTML=filtered.map(function(e){
    var recurBadge=e.is_recurring?'<span class="badge badge-critical" data-s="s4668d02"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-refresh-cw></use></svg></span>':'';
    var elevateBtn=!e.erm_risk_id&&(e.severity==='critical'||e.severity==='high'||(parseFloat(e.financial_impact)||0)>=10000)?
      '<button class="btn btn-sm btn-secondary" data-orm-call="ormElevateToErm" data-orm-id="'+ormAttrId(e.id)+'" data-s="s53d0ffa">&#8593; ERM</button>':'';
    var aiBtn='<button class="btn-orm-ai" data-orm-call="ormAiAnalyze" data-orm-id="'+ormAttrId(e.id)+'" data-orm-this="1" title="AI root cause"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-brain></use></svg></button>';
    var detDate=e.detected_at||e.created_at;
    // SLA chip
    var slaHtml='<span data-s="s6d034cc">—</span>';
    var isClosed=e.status==='closed'||e.status==='resolved';
    if(!isClosed){
      var respDue=e.response_due_at?new Date(e.response_due_at.includes('T')?e.response_due_at:e.response_due_at+'Z').getTime():null;
      var resDue=e.resolution_due_at?new Date(e.resolution_due_at.includes('T')?e.resolution_due_at:e.resolution_due_at+'Z').getTime():null;
      var overdue=(respDue&&respDue<now)||(resDue&&resDue<now);
      var dueSoon=!overdue&&((respDue&&respDue-now<86400000)||(resDue&&resDue-now<86400000));
      if(overdue)slaHtml='<span class="sla-overdue"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg> OVERDUE</span>';
      else if(dueSoon)slaHtml='<span class="sla-warn"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-alarm-clock></use></svg> Due Soon</span>';
      else if(respDue||resDue){
        var target=respDue&&respDue>now?respDue:(resDue||0);
        if(target>now){var days=Math.ceil((target-now)/86400000);slaHtml='<span class="sla-ok">'+days+'d left</span>';}
      }
    }else{slaHtml='<span class="sla-ok">&#10003;</span>';}
    return'<tr id="evtRow-'+e.id+'">'+
      '<td><input type="checkbox" data-id="'+e.id+'" data-orm-select-id="'+ormAttrId(e.id)+'"></td>'+
      '<td data-s="s3b6a3a6" data-orm-call="ormOpenEventDrawer" data-orm-id="'+ormAttrId(e.id)+'">'+recurBadge+'<span data-s="s64ac89c">'+esc(e.title||'')+'</span></td>'+
      '<td><span data-s="s433de30">'+typeIcon(e.event_type)+'</span> <span data-s="s1fd8c81">'+esc((e.event_type||'').replace(/_/g,' '))+'</span></td>'+
      '<td>'+sevBadge(e.severity)+'</td>'+
      '<td data-s="s4212bf3">'+esc(e.department||'—')+'</td>'+
      '<td data-sv="font-weight:700;color:'+(parseFloat(e.financial_impact)>0?'var(--red)':'var(--muted)')+'">'+fmtCurrency(e.financial_impact||0)+'</td>'+
      '<td>'+statusBadge(e.status)+'</td>'+
      '<td>'+slaHtml+'</td>'+
      '<td data-s="s7fc448e">'+fmtDate(detDate)+'</td>'+
      '<td><div data-s="s577c5fb" data-sd="flex">'+aiBtn+elevateBtn+
        '<button class="btn btn-sm btn-secondary" data-orm-cache-call="ormOpenEventModal" data-orm-id="'+ormAttrId(e.id)+'" data-s="sf261655" title="Edit"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button>'+
        '<button class="btn btn-sm btn-secondary" data-orm-call="ormDuplicateEvt" data-orm-id="'+ormAttrId(e.id)+'" data-s="sf261655" title="Duplicate"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-clipboard-list></use></svg></button>'+
        '<button class="btn btn-sm btn-secondary" data-orm-call="ormDeleteEvt" data-orm-id="'+ormAttrId(e.id)+'" data-s="sc304996" title="Delete">&#10005;</button>'+
      '</div></td>'+
    '</tr>';
  }).join('');
}

/* Bulk actions */
window.ormToggleSelect=function(id,checked){
  if(checked)evtSelectedIds.add(id);else evtSelectedIds.delete(id);
  var bar=document.getElementById('ormBulkBar');
  var cnt=document.getElementById('ormBulkCount');
  if(bar){bar.style.display=evtSelectedIds.size?'flex':'none';}
  if(cnt)cnt.textContent=evtSelectedIds.size+' selected';
};
window.ormSelectAll=function(checked){
  var rows=document.querySelectorAll('#ormEvtBody input[type=checkbox]');
  rows.forEach(function(cb){cb.checked=checked;ormToggleSelect(parseInt(cb.dataset.id),checked);});
};
window.ormBulkClear=function(){
  evtSelectedIds.clear();
  document.querySelectorAll('#ormEvtBody input[type=checkbox]').forEach(function(cb){cb.checked=false;});
  var sel=document.getElementById('evtSelectAll');if(sel)sel.checked=false;
  var bar=document.getElementById('ormBulkBar');if(bar)bar.style.display='none';
};
window.ormBulkStatus=function(){
  if(!evtSelectedIds.size)return;
  var cnt=evtSelectedIds.size;
  var html='<div class="orm-modal-overlay" id="ormBulkStatusModal" data-orm-static-click="s37">'+
    '<div class="modal-box" data-s="sb4a851b">'+
      '<div class="modal-title">Change Status — '+cnt+' Event(s)</div>'+
      '<div class="form-group"><label>New Status</label>'+
        '<select id="bulkStatusSel" data-s="s3c8f9ee">'+
          '<option value="open">Open</option>'+
          '<option value="investigating" selected>Investigating</option>'+
          '<option value="resolved">Resolved</option>'+
          '<option value="closed">Closed</option>'+
        '</select>'+
      '</div>'+
      '<div data-s="sd28ceac" data-sd="flex">'+
        '<button class="btn btn-secondary" data-orm-static-click="s38">Cancel</button>'+
        '<button class="btn btn-primary" data-orm-static-click="s39">Apply</button>'+
      '</div>'+
    '</div></div>';
  document.body.insertAdjacentHTML('beforeend',html);
};
window.ormBulkStatusApply=async function(){
  var s=document.getElementById('bulkStatusSel').value;
  document.getElementById('ormBulkStatusModal').remove();
  var ids=Array.from(evtSelectedIds);
  try{
    await Promise.all(ids.map(function(id){return apiFetch('/orm/api/events/'+id,{method:'PUT',body:{status:s}});}));
    ormBulkClear();ormLoadEvents();
    if(typeof showToast==='function')showToast('Updated '+ids.length+' event(s)');
  }catch(e){if(typeof showToast==='function')showToast('Bulk update failed','error');}
};
window.ormBulkDelete=async function(){
  if(!evtSelectedIds.size)return;
  if(!confirm('Delete '+evtSelectedIds.size+' selected event(s)? This cannot be undone.'))return;
  var ids=Array.from(evtSelectedIds);
  try{
    await Promise.all(ids.map(function(id){return apiFetch('/orm/api/events/'+id,{method:'DELETE'});}));
    ormBulkClear();ormLoadEvents();
    if(typeof showToast==='function')showToast('Deleted '+ids.length+' event(s)');
  }catch(e){if(typeof showToast==='function')showToast('Bulk delete failed','error');}
};

window.ormDeleteEvt=async function(id){
  if(!confirm('Delete this event?'))return;
  try{await apiFetch('/orm/api/events/'+id,{method:'DELETE'});ormLoadEvents();}
  catch(e){if(typeof showToast==='function')showToast('Delete failed','error');}
};
window.ormElevateToErm=async function(id){
  if(!confirm('Elevate this event to an ERM enterprise risk?'))return;
  try{
    var res=await apiFetch('/orm/api/events/'+id+'/elevate',{method:'POST',body:{}});
    if(typeof showToast==='function')showToast('Elevated to ERM — Risk #'+res.erm_risk_id);
    ormLoadEvents();
  }catch(e){if(typeof showToast==='function')showToast('Elevation failed','error');}
};
window.ormAiAnalyze=async function(id,btn){
  var orig=btn.innerHTML;btn.disabled=true;btn.textContent='…';
  try{
    var res=await apiFetch('/orm/api/ai/analyze/'+id,{method:'POST'});
    btn.disabled=false;btn.innerHTML=orig;
    document.body.insertAdjacentHTML('beforeend',
      '<div class="orm-modal-overlay" data-orm-static-click="s37">'+
      '<div class="modal-box" data-s="s765d57b">'+
        '<div class="modal-title"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-brain></use></svg> AI Root Cause Analysis</div>'+
        '<div data-s="s3a10379">'+
          '<div data-s="s5150672">Root Cause Category</div>'+
          '<div data-s="sa6c5f9b">'+esc(res.root_cause_category||'—')+'</div>'+
        '</div>'+
        (res.root_cause_analysis?'<div data-s="sda12f28"><div data-s="s5150672">Analysis</div><div data-s="s6bcb8fe">'+esc(res.root_cause_analysis)+'</div></div>':'')+
        '<div data-s="sda12f28"><div data-s="sf7d7e96">Corrective Action</div><div data-s="s6bcb8fe">'+esc(res.corrective_action||'—')+'</div></div>'+
        '<div data-s="s87c136d"><div data-s="s2bd2920">Preventive Action</div><div data-s="s6bcb8fe">'+esc(res.preventive_action||'—')+'</div></div>'+
        '<div data-s="s455f8cc" data-sd="flex"><button class="btn btn-secondary" data-orm-static-click="s40">Close</button></div>'+
      '</div></div>'
    );
    ormLoadEvents();
  }catch(e){btn.disabled=false;btn.innerHTML=orig;if(typeof showToast==='function')showToast('AI analysis failed','error');}
};

/* ─────────────────────────── EVENT DRAWER ─────────────────────────── */
window.ormOpenEventDrawer=async function(id){
  var drawer=document.getElementById('ormDrawerRoot');
  drawer.innerHTML='<div class="orm-drawer-overlay"><div class="orm-drawer-panel" data-s="sa3fa223"><div class="spinner"></div></div></div>';
  try{
    var e=await apiFetch('/orm/api/events/'+id);
    window._ormDrawerEvt = e;
    var isFraud=e.event_type==='fraud'||e.event_type==='customer_impact';
    var isSystem=e.event_type==='system_failure'||e.event_type==='outage';
    var canElevate=!e.erm_risk_id&&(e.severity==='critical'||e.severity==='high'||(parseFloat(e.financial_impact)||0)>=10000);
    drawer.innerHTML='<div class="orm-drawer-overlay" data-orm-static-click="s41">'+
    '<div class="orm-drawer-panel">'+
      '<div class="orm-drawer-head">'+
        '<div data-s="sb5ca335" data-sd="flex">'+
          '<div>'+
            '<div data-s="s57e146b">'+typeIcon(e.event_type)+' '+esc(e.title||'')+'</div>'+
            '<div data-s="sd14d7bf">'+esc((e.event_type||'').replace(/_/g,' '))+' &bull; '+fmtDate(e.created_at)+'</div>'+
          '</div>'+
          '<button class="btn btn-sm btn-secondary" data-orm-static-click="s42">&#10005;</button>'+
        '</div>'+
        '<div data-s="sfa88970" data-sd="flex">'+
          sevBadge(e.severity)+statusBadge(e.status)+
          (e.is_recurring?'<span class="badge badge-critical" data-s="s0d5be05"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-refresh-cw></use></svg> Recurring</span>':'')+
          (e.erm_risk_id?'<span class="badge badge-complete" title="ERM Risk #'+e.erm_risk_id+'">&#8593; ERM #'+e.erm_risk_id+'</span>':'')+
        '</div>'+
      '</div>'+
      '<div class="orm-drawer-body">'+
        '<!-- Metrics grid -->'+
        '<div data-s="s6f6bd81" data-sd="grid">'+
          '<div data-s="s0ff1122"><div data-s="s0de5e1b">Financial Impact</div><div data-s="sbf41355">'+fmtCurrency(e.financial_impact||0)+'</div></div>'+
          '<div data-s="s0ff1122"><div data-s="s0de5e1b">Customers</div><div data-s="s80b90e3">'+(e.customers_affected||0).toLocaleString()+'</div></div>'+
          '<div data-s="s0ff1122"><div data-s="s0de5e1b">Downtime</div><div data-s="s80b90e3">'+(e.downtime_minutes?Math.round(e.downtime_minutes/60*10)/10+'h':'—')+'</div></div>'+
        '</div>'+
        '<!-- Details section -->'+
        '<div class="orm-drawer-section">'+
          '<div class="orm-drawer-section-title">Details</div>'+
          '<div class="orm-drawer-row"><span class="orm-drawer-label">Department</span><span class="orm-drawer-val">'+esc(e.department||'—')+'</span></div>'+
          '<div class="orm-drawer-row"><span class="orm-drawer-label">Process Affected</span><span class="orm-drawer-val">'+esc(e.process_affected||'—')+'</span></div>'+
          '<div class="orm-drawer-row"><span class="orm-drawer-label">Detected At</span><span class="orm-drawer-val">'+fmtDate(e.detected_at||e.created_at)+'</span></div>'+
          '<div class="orm-drawer-row"><span class="orm-drawer-label">Reported By</span><span class="orm-drawer-val">'+esc(e.reporter_name||'—')+'</span></div>'+
          '<div class="orm-drawer-row"><span class="orm-drawer-label">Owner</span><span class="orm-drawer-val">'+esc(e.owner_name||'Unassigned')+'</span></div>'+
          (e.resolved_at?'<div class="orm-drawer-row"><span class="orm-drawer-label">Resolved At</span><span class="orm-drawer-val">'+fmtDate(e.resolved_at)+'</span></div>':'')+
        '</div>'+
        (e.description?'<div class="orm-drawer-section"><div class="orm-drawer-section-title">Description</div><div data-s="s01643be">'+esc(e.description)+'</div></div>':'')+
        '<!-- Root cause section -->'+
        '<div class="orm-drawer-section">'+
          '<div class="orm-drawer-section-title">Root Cause</div>'+
          '<div class="orm-drawer-row"><span class="orm-drawer-label">Category</span><span class="orm-drawer-val" data-s="s6fedee3">'+esc(e.root_cause_category||'—')+'</span></div>'+
          (e.root_cause?'<div data-s="s1516108">'+esc(e.root_cause)+'</div>':'')+
        '</div>'+
        (e.corrective_action||e.preventive_action?
          '<div class="orm-drawer-section">'+
            '<div class="orm-drawer-section-title">Actions</div>'+
            (e.corrective_action?'<div data-s="sfdf33f2"><div data-s="sb2d4914">Corrective</div><div data-s="s0b422b6">'+esc(e.corrective_action)+'</div></div>':'')+
            (e.preventive_action?'<div><div data-s="s95ad82e">Preventive</div><div data-s="s0b422b6">'+esc(e.preventive_action)+'</div></div>':'')+
          '</div>':'')+
        /* Sentinel cross-module link for fraud/customer impact */
        (isFraud?'<div data-s="sb82a216"><span data-s="s433de30"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-shield></use></svg></span> <strong>Data exposure risk</strong> — If personal data was affected, consider raising a Sentinel incident. <a href="/sentinel/" data-s="s456fefd">Open Sentinel &#8594;</a></div>':'')+
        /* BCM link for system failures with significant downtime */
        (isSystem&&(e.downtime_minutes||0)>=120?'<div data-s="s26e6b37"><span data-s="s433de30"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-zap></use></svg></span> <strong>Significant downtime detected</strong> — Consider creating a BCM incident if business continuity is at risk. <a href="/bcm/" data-s="s456fefd">Open BCM &#8594;</a></div>':'')+
        /* Workflow stepper */
        '<div class="orm-drawer-section" data-s="s1b0f499">'+
          '<div class="orm-drawer-section-title">Investigation Workflow</div>'+
          ormWorkflowStepper(e)+
          '<div id="wfHistory-'+e.id+'" data-s="sd2c171b" data-sd="none"></div>'+
          '<button data-s="sba45a76" data-orm-call="ormToggleWfHistory" data-orm-id="'+ormAttrId(e.id)+'"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-file-clock></use></svg> Show history</button>'+
        '</div>'+
        /* Related events — parent + children from evtCache */
        (function(){
          var parentEvt=e.parent_event_id?evtCache.find(function(x){return x.id===e.parent_event_id;}):null;
          var children=evtCache.filter(function(x){return x.parent_event_id===e.id;});
          if(!parentEvt&&!children.length)return'';
          return'<div class="orm-drawer-section" data-s="s56f4356">'+
            '<div class="orm-drawer-section-title">Related Events</div>'+
            (parentEvt?'<div data-s="s4e420af"><span data-s="s0de5e1b">Parent</span>'+
              '<div data-s="s96ad609"><a href="#" data-orm-special="open-event-close" data-orm-id="'+ormAttrId(parentEvt.id)+'" data-s="s0f569d7">'+typeIcon(parentEvt.event_type)+' '+esc(parentEvt.title)+'</a></div></div>':'')+
            (children.length?'<div><span data-s="s0de5e1b">Children ('+children.length+')</span>'+
              '<div data-s="s5f79c69" data-sd="flex">'+
              children.map(function(c){return'<a href="#" data-orm-special="open-event-close" data-orm-id="'+ormAttrId(c.id)+'" data-s="sc78de4b">'+typeIcon(c.event_type)+' '+esc(c.title)+'</a>';}).join('')+
              '</div></div>':'')+
          '</div>';
        })()+
        '<div class="orm-drawer-section" id="ormRelatedItems"></div>'+
      '</div>'+
      '<div class="orm-drawer-footer">'+
        '<button class="btn-orm-ai" data-orm-call="ormAiAnalyzeFromDrawer" data-orm-id="'+ormAttrId(e.id)+'"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-brain></use></svg> AI Analyze</button>'+
        (canElevate?'<button class="btn btn-secondary" data-orm-special="elevate-close" data-orm-id="'+ormAttrId(e.id)+'">&#8593; Elevate to ERM</button>':'')+
        '<button class="btn btn-sm btn-secondary" data-orm-special="toggle-recurring" data-orm-id="'+ormAttrId(e.id)+'" data-orm-toggle="'+(e.is_recurring?'0':'1')+'">'+(e.is_recurring?'&#10003; Recurring':'Mark <svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-refresh-cw></use></svg> Recurring')+'</button>'+
        '<button class="btn btn-primary" data-orm-static-click="s43" data-s="s6d00061">Edit</button>'+
      '</div>'+
    '</div></div>';
    if(typeof DialogFocus!=='undefined')DialogFocus.trap(drawer.querySelector('.orm-drawer-panel'));
    if(typeof RelatedItems!=='undefined'){
      var related=document.getElementById('ormRelatedItems');
      if(related)RelatedItems.mount(related,'orm','event',e.id,{canEdit:true});
    }
  }catch(ex){drawer.innerHTML='';}
};
window.ormCloseDrawer=function(){if(typeof DialogFocus!=='undefined')DialogFocus.release();document.getElementById('ormDrawerRoot').innerHTML='';};
document.addEventListener('keydown',function(e){
  if(e.key!=='Escape')return;
  if(document.getElementById('ormDrawerRoot').firstElementChild)ormCloseDrawer();
});
window.ormAiAnalyzeFromDrawer=async function(id){
  ormCloseDrawer();
  var fakeBtn={textContent:'…',disabled:false};
  await ormAiAnalyze(id,fakeBtn);
};
window.ormToggleRecurring=async function(id,val){
  try{
    await apiFetch('/orm/api/events/'+id,{method:'PUT',body:{is_recurring:val}});
    ormCloseDrawer();
    if(ormRouter.current==='events')ormLoadEvents();
    if(typeof showToast==='function')showToast(val?'Marked as recurring':'Cleared recurring flag');
  }catch(e){if(typeof showToast==='function')showToast('Update failed','error');}
};

/* ─────────────────────────── EVENT MODAL ─────────────────────────── */
window.ormOpenEventModal=async function(existing){
  var isEdit=!!(existing&&existing.id);
  var users=await ormLoadUsers();
  var types=['process_failure','fraud','system_failure','human_error','outage','vendor_failure','customer_impact'];
  var statusVal=isEdit?(existing.status||'open'):'open';
  var showResolvedAt=statusVal==='resolved'||statusVal==='closed';
  var html='<div class="orm-modal-overlay" id="ormEvtModal" data-orm-static-click="s37">'+
    '<div class="modal-box">'+
      '<button class="modal-close" data-orm-static-click="s44">&#10005;</button>'+
      '<div class="modal-title">'+(isEdit?'Edit':'Log')+' Operational Risk Event</div>'+
      '<div class="form-group"><label>Title *</label><input id="oe_title" value="'+esc(isEdit?(existing.title||''):'')+'"></div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Event Type *</label><select id="oe_type">'+types.map(function(t){return'<option value="'+t+'"'+(isEdit&&existing.event_type===t?' selected':'')+'>'+typeIcon(t)+' '+t.replace(/_/g,' ')+'</option>';}).join('')+'</select></div>'+
        '<div class="form-group"><label>Severity</label><select id="oe_sev">'+['low','medium','high','critical'].map(function(s){return'<option value="'+s+'"'+(isEdit&&existing.severity===s?' selected':'')+'>'+s+'</option>';}).join('')+'</select></div>'+
      '</div>'+
      '<div class="form-group"><label>Description</label><textarea id="oe_desc" rows="3" data-s="sa57b154">'+esc(isEdit?(existing.description||''):'')+'</textarea></div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Financial Impact ($)</label><input type="number" id="oe_fin" min="0" value="'+(isEdit?(existing.financial_impact||0):0)+'"></div>'+
        '<div class="form-group"><label>Customers Affected</label><input type="number" id="oe_cust" min="0" value="'+(isEdit?(existing.customers_affected||0):0)+'"></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Downtime (minutes)</label><input type="number" id="oe_down" min="0" value="'+(isEdit?(existing.downtime_minutes||0):0)+'"></div>'+
        '<div class="form-group"><label>Department</label><input id="oe_dept" value="'+esc(isEdit?(existing.department||''):'')+'"></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Process Affected</label><input id="oe_proc" placeholder="e.g. Payment Processing" value="'+esc(isEdit?(existing.process_affected||''):'')+'"></div>'+
        '<div class="form-group"><label>Owner</label><select id="oe_owner">'+
          '<option value="">— Unassigned —</option>'+
          users.map(function(u){return'<option value="'+u.id+'"'+(isEdit&&existing.owner_id==u.id?' selected':'')+'>'+esc(u.full_name)+'</option>';}).join('')+
        '</select></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Detected At</label><input type="datetime-local" id="oe_detected" value="'+(isEdit&&existing.detected_at?existing.detected_at.replace(' ','T').slice(0,16):'')+'"></div>'+
        '<div class="form-group"><label>Root Cause Category</label><select id="oe_rcc">'+['','people','process','system','external'].map(function(c){return'<option value="'+c+'"'+(isEdit&&existing.root_cause_category===c?' selected':'')+'>'+esc(c||'— Select —')+'</option>';}).join('')+'</select></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Status</label><select id="oe_status" data-orm-static-change="s45">'+['open','investigating','resolved','closed'].map(function(s){return'<option value="'+s+'"'+(isEdit&&existing.status===s?' selected':'')+'>'+s+'</option>';}).join('')+'</select></div>'+
        '<div class="form-group" id="oe_resolved_row" data-sv="display:'+(showResolvedAt?'block':'none')+'"><label>Resolved At</label><input type="datetime-local" id="oe_resolved" value="'+(isEdit&&existing.resolved_at?existing.resolved_at.replace(' ','T').slice(0,16):'')+'"></div>'+
      '</div>'+
      '<div class="form-group"><label>Corrective Action</label><textarea id="oe_corrective" rows="2" data-s="sa57b154">'+esc(isEdit?(existing.corrective_action||''):'')+'</textarea></div>'+
      '<div class="form-group"><label>Preventive Action</label><textarea id="oe_preventive" rows="2" data-s="sa57b154">'+esc(isEdit?(existing.preventive_action||''):'')+'</textarea></div>'+
      '<div class="form-group"><label>Basel III Category <span data-s="s8e93b13">(optional — financial services)</span></label>'+
        '<select id="oe_basel">'+
          '<option value="">— Not specified —</option>'+
          ['internal_fraud','external_fraud','employment_practices','clients_products','physical_assets','business_disruption','execution_delivery'].map(function(c){
            var labels={internal_fraud:'Internal Fraud',external_fraud:'External Fraud',employment_practices:'Employment Practices & Workplace Safety',clients_products:'Clients, Products & Business Practices',physical_assets:'Damage to Physical Assets',business_disruption:'Business Disruption & System Failures',execution_delivery:'Execution, Delivery & Process Management'};
            return'<option value="'+c+'"'+(isEdit&&existing.basel_category===c?' selected':'')+'>'+esc(labels[c]||c)+'</option>';
          }).join('')+
        '</select>'+
      '</div>'+
      '<div data-s="sd28ceac" data-sd="flex">'+
        '<button class="btn btn-secondary" data-orm-static-click="s44">Cancel</button>'+
        '<button class="btn btn-primary" data-orm-save-call="ormSaveEvent" data-orm-save-id="'+(isEdit?ormAttrId(existing.id):'')+'" data-orm-save-edit="'+(isEdit?'1':'0')+'">Save Event</button>'+
      '</div>'+
    '</div></div>';
  document.body.insertAdjacentHTML('beforeend',html);
  setTimeout(function(){var t=document.getElementById('oe_title');if(t)t.focus();},80);
  // Show Sentinel suggestion for fraud type
  document.getElementById('oe_type').addEventListener('change',function(){
    if(this.value==='fraud'&&typeof showToast==='function')
      showToast('Fraud event: if personal data is involved, raise a Sentinel incident after saving');
  });
};
window.ormSaveEvent=async function(id){
  var title=document.getElementById('oe_title').value.trim();
  if(!title){if(typeof showToast==='function')showToast('Title required','error');return;}
  var statusSel=document.getElementById('oe_status').value;
  var detectedVal=document.getElementById('oe_detected').value;
  var resolvedVal=document.getElementById('oe_resolved').value;
  var data={
    title:title,
    event_type:document.getElementById('oe_type').value,
    severity:document.getElementById('oe_sev').value,
    description:document.getElementById('oe_desc').value.trim(),
    financial_impact:parseFloat(document.getElementById('oe_fin').value)||0,
    customers_affected:parseInt(document.getElementById('oe_cust').value)||0,
    downtime_minutes:parseInt(document.getElementById('oe_down').value)||0,
    department:document.getElementById('oe_dept').value.trim(),
    process_affected:document.getElementById('oe_proc').value.trim()||null,
    owner_id:document.getElementById('oe_owner').value||null,
    detected_at:detectedVal?detectedVal.replace('T',' '):null,
    root_cause_category:document.getElementById('oe_rcc').value||null,
    status:statusSel,
    resolved_at:(statusSel==='resolved'||statusSel==='closed')&&resolvedVal?resolvedVal.replace('T',' '):null,
    basel_category:document.getElementById('oe_basel').value||null,
    corrective_action:document.getElementById('oe_corrective').value.trim()||null,
    preventive_action:document.getElementById('oe_preventive').value.trim()||null
  };
  try{
    if(id)await apiFetch('/orm/api/events/'+id,{method:'PUT',body:data});
    else await apiFetch('/orm/api/events',{method:'POST',body:data});
    document.getElementById('ormEvtModal').remove();
    if(ormRouter.current==='events')ormLoadEvents();
    else ormLoadDashboard();
    if(typeof showToast==='function'){
      showToast('Event saved');
      if(data.severity==='critical')
        setTimeout(function(){showToast('Critical event logged — consider elevating to ERM or creating a BCM incident','info');},1000);
      else if(data.event_type==='fraud'&&(data.financial_impact||0)>5000)
        setTimeout(function(){showToast('High-value fraud event — check if a Sentinel privacy incident is needed','info');},1000);
      else if(data.event_type==='system_failure'&&(data.downtime_minutes||0)>120)
        setTimeout(function(){showToast('Significant outage detected — review BCM plans in the Resilience module','info');},1000);
      else if(data.event_type==='fraud')
        setTimeout(function(){showToast('Fraud event: if personal data was affected, raise a Sentinel incident','info');},1200);
    }
  }catch(e){if(typeof showToast==='function')showToast('Save failed','error');}
};

/* ─────────────────────────── EXPORT CSV ─────────────────────────── */
/* One export for every "Export CSV" button: the server file, which holds every event the person may open (not only the page that
   happens to be loaded) and writes any text that starts like a formula as text. */
window.ormExportCSV=function(){
  window.location.href='/orm/api/export/csv';
  if(typeof showToast==='function')showToast('Downloading every event you may open');
};

/* ─────────────────────────── KRI SPARKLINE ─────────────────────────── */
function ormKriSparkline(points){
  /* points = array of numbers, newest last */
  if(!points||points.length<2)return'';
  var w=80,h=28,pad=2;
  var min=Math.min.apply(null,points),max=Math.max.apply(null,points);
  var range=max-min||1;
  var xs=points.map(function(_,i){return pad+(i/(points.length-1))*(w-pad*2);});
  var ys=points.map(function(v){return h-pad-(v-min)/range*(h-pad*2);});
  var d='M'+xs.map(function(x,i){return x.toFixed(1)+','+ys[i].toFixed(1);}).join(' L');
  var last=points[points.length-1];var prev=points[0];
  var col=last>prev?'var(--red,#dc2626)':last<prev?'var(--good,#16a34a)':'var(--muted)';
  return'<svg class="kri-sparkline" width="'+w+'" height="'+h+'" viewBox="0 0 '+w+' '+h+'"><title>From '+esc(String(prev))+' to '+esc(String(last))+'</title>'+
    '<polyline points="'+xs.map(function(x,i){return x.toFixed(1)+','+ys[i].toFixed(1);}).join(' ')+'" fill="none" stroke="'+col+'" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'+
    '<circle cx="'+xs[xs.length-1].toFixed(1)+'" cy="'+ys[ys.length-1].toFixed(1)+'" r="2.5" fill="'+col+'"/>'+
  '</svg>';
}

/* ─────────────────────────── KRI INDICATORS ─────────────────────────── */
var kriCache=[], kriHistoryCache={};
window.ormLoadKris=async function(){
  var grid=document.getElementById('ormKriGrid');
  if(grid)grid.innerHTML='<div data-s="se3e8e97"><div class="spinner" data-s="s266e9b0"></div></div>';
  try{
    var data=await apiFetch('/orm/api/kris');
    kriCache=Array.isArray(data)?data:[];
    // Load history for sparklines (fire and forget — fill in asynchronously)
    kriCache.forEach(function(k){
      apiFetch('/orm/api/kris/'+k.id+'/history?limit=7').then(function(hist){
        kriHistoryCache[k.id]=(hist||[]).map(function(h){return h.value;}).reverse();
        // Re-render just the sparkline in the card if it exists
        var sparkEl=document.getElementById('kriSpark-'+k.id);
        if(sparkEl)sparkEl.innerHTML=ormKriSparkline(kriHistoryCache[k.id]);
      }).catch(function(){});
    });

    // Stats strip
    var crit=kriCache.filter(function(k){var v=k.current_value||0;return k.threshold_crit&&v>=k.threshold_crit;}).length;
    var warn=kriCache.filter(function(k){var v=k.current_value||0;return k.threshold_warn&&v>=k.threshold_warn&&(!k.threshold_crit||v<k.threshold_crit);}).length;
    var ok=kriCache.length-crit-warn;
    populateStatCards('kriStats',[
      {label:'Total KRIs',value:kriCache.length},
      {label:'Breaching (Critical)',value:crit,color:crit>0?'var(--red)':'var(--text)'},
      {label:'Warning',value:warn,color:warn>0?'var(--amber,#d97706)':'var(--text)'},
      {label:'Healthy',value:ok,color:'var(--good,#16a34a)'}
    ]);

    // Breach banner
    var breaching=kriCache.filter(function(k){var v=k.current_value||0;return k.threshold_crit&&v>=k.threshold_crit;});
    var bb=document.getElementById('ormKriBreachBanner');
    if(bb){
      if(breaching.length){
        bb.style.display='';
        bb.innerHTML='<div data-s="sf9990f4" data-sd="flex">'+
          '<span data-s="sb9199e2"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-siren></use></svg></span>'+
          '<div data-s="s97445a8"><strong data-s="s45e7ae4">'+breaching.length+' KRI'+(breaching.length>1?'s':'')+' at Critical Level</strong>: '+
          breaching.map(function(k){
            var sentinelLink=(k.name||'').toLowerCase().includes('breach')||(k.name||'').toLowerCase().includes('data')?
              ' <a href="/sentinel/" data-s="sa715fab">(Review in Sentinel)</a>':'';
            return esc(k.name)+' <strong>'+k.current_value+' '+esc(k.unit||'')+'</strong>'+sentinelLink;
          }).join(', ')+'</div>'+
        '</div>';
      }else{bb.style.display='none';}
    }

    // Stale KRI banner (>30 days without update)
    var stale=kriCache.filter(function(k){
      if(!k.last_updated)return true;
      var ts=k.last_updated.includes('T')?k.last_updated:k.last_updated+'Z';
      return(Date.now()-new Date(ts).getTime())>30*86400*1000;
    });
    var sb=document.getElementById('ormKriStaleBanner');
    if(sb){
      if(stale.length){
        sb.style.display='';
        sb.innerHTML='<div data-s="s6e073d1" data-sd="flex">'+
          '<span data-s="s4ff818f"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-alarm-clock></use></svg></span>'+
          '<div data-s="s7829123"><strong data-s="sd0ca9f2">'+stale.length+' KRI'+(stale.length>1?'s':'')+' haven\'t been updated in over 30 days</strong>: '+
          stale.map(function(k){return'<a href="#" data-s="sa805525" data-orm-special="kri-update" data-orm-id="'+ormAttrId(k.id)+'">'+esc(k.name)+'</a>';}).join(', ')+
          ' — update them to keep your risk picture accurate.</div>'+
        '</div>';
      }else{sb.style.display='none';}
    }

    // Filter chips
    var fb=document.getElementById('kriFilterBar');
    if(fb){
      var chips=[
        {label:'All KRIs',filter:'all'},
        {label:'My KRIs',filter:'mine'},
        {label:'Breaching',filter:'critical'},
        {label:'Warning',filter:'warning'},
        {label:'Healthy',filter:'ok'}
      ];
      fb.innerHTML=chips.map(function(c){
        var active=window._kriFilter===c.filter||(!window._kriFilter&&c.filter==='all');
        return'<button data-orm-special="kri-filter" data-orm-filter="'+esc(c.filter)+'" data-sv="padding:4px 12px;border-radius:100px;border:1px solid var(--border);background:'+(active?'var(--accent)':'var(--surface2)')+';color:'+(active?'white':'var(--text)')+';font-size:12px;font-weight:600;cursor:pointer">'+c.label+'</button>';
      }).join('');
    }

    if(!kriCache.length){
      if(grid)grid.innerHTML='<div data-s="se3e8e97">No KRIs defined. Click "+ Add KRI" to create your first indicator.</div>';
      return;
    }
    var displayKris=ormGetFilteredKris(kriCache);
    if(!displayKris.length){
      if(grid)grid.innerHTML='<div data-s="se3e8e97">No KRIs match the selected filter.</div>';
      return;
    }
    if(grid)grid.innerHTML=displayKris.map(function(k){
      var val=parseFloat(k.current_value)||0;
      var crit=parseFloat(k.threshold_crit)||null;
      var warn=parseFloat(k.threshold_warn)||null;
      var ragColor=crit&&val>=crit?'var(--red)':warn&&val>=warn?'var(--amber,#d97706)':'var(--good,#16a34a)';
      var status=crit&&val>=crit?'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg> CRITICAL':warn&&val>=warn?'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg> WARNING':'&#10003; OK';
      var sentinelHint=(k.name||'').toLowerCase().includes('breach')||(k.name||'').toLowerCase().includes('data');
      var criticalKri=crit&&val>=crit;
      return'<div class="kri-card">'+
        '<div data-s="s3ae5ff5" data-sd="flex">'+
          '<div data-s="s381a5ca">'+esc(k.name)+'</div>'+
          '<span data-sv="font-size:10px;font-weight:700;color:'+ragColor+';flex-shrink:0;margin-left:8px">'+status+'</span>'+
        '</div>'+
        (k.description?'<div data-s="s641c5f4">'+esc(k.description)+'</div>':'')+
        '<div data-sv="font-size:28px;font-weight:900;color:'+ragColor+';line-height:1;cursor:pointer" data-orm-call="ormInlineKriEdit" data-orm-id="'+ormAttrId(k.id)+'" data-orm-this="1" title="Click to update value" id="kriVal-'+k.id+'">'+val+'<span data-s="s1636f8d"> '+esc(k.unit||'')+'</span></div>'+
        ormKriGauge(val,warn,crit)+
        '<div data-s="s1a1f200" data-sd="flex">'+
          (warn?'<span><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg> Warn: '+warn+'</span>':'<span></span>')+
          (crit?'<span><svg class=ic-red aria-hidden=true><use href=/static/icons/sprite.svg#ic-dot></use></svg> Crit: '+crit+'</span>':'<span></span>')+
        '</div>'+
        '<div data-s="s4b67c47" data-sd="flex">'+
          (k.frequency?'<span data-s="sfaae1d0"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-alarm-clock></use></svg> '+esc(k.frequency)+'</span>':'')+
          (k.owner_name?'<span data-s="sfaae1d0"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-user></use></svg> '+esc(k.owner_name)+'</span>':'')+
          (k.last_updated?'<span data-s="sfaae1d0">Updated '+timeAgo(k.last_updated)+'</span>':'')+
          (k.trend==='worsening'?'<span data-s="s55dfec5">&#8593; Worsening</span>':
           k.trend==='improving'?'<span data-s="s3c48ee1">&#8595; Improving</span>':'')+
        '</div>'+
        /* Sparkline */
        '<div data-s="s7357596" data-sd="flex">'+
          '<span data-s="s89bea07">7-day trend</span>'+
          '<span id="kriSpark-'+k.id+'">'+ormKriSparkline(kriHistoryCache[k.id]||[])+'</span>'+
        '</div>'+
        (criticalKri&&sentinelHint?'<div data-s="s621f2cc"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-shield></use></svg> Breach indicator — <a href="/sentinel/" data-s="sa805525">Review in Sentinel</a></div>':'')+
        '<div data-s="s59d05aa" data-sd="flex">'+
          '<button class="btn btn-sm btn-secondary" data-orm-cache-call="ormOpenKriUpdateModal" data-orm-id="'+ormAttrId(k.id)+'">Update Value</button>'+
          '<button class="btn btn-sm btn-secondary" data-orm-cache-call="ormOpenKriModal" data-orm-id="'+ormAttrId(k.id)+'">Edit</button>'+
          '<button class="btn btn-sm btn-secondary" data-orm-call="ormDeleteKri" data-orm-id="'+ormAttrId(k.id)+'" data-s="s45e7ae4">Delete</button>'+
        '</div>'+
      '</div>';
    }).join('');
  }catch(e){if(grid)grid.innerHTML='<div data-s="se3e8e97">Failed to load KRIs</div>';}
};
window.ormUpdateKriValue=function(id,currentVal,unit){
  var newVal=prompt('Update KRI value\nCurrent: '+currentVal+' '+unit+'\n\nEnter new value:');
  if(newVal===null||newVal==='')return;
  var n=parseFloat(newVal);if(isNaN(n)){if(typeof showToast==='function')showToast('Invalid value — enter a number','error');return;}
  apiFetch('/orm/api/kris/'+id,{method:'PUT',body:{current_value:n}}).then(function(){ormLoadKris();}).catch(function(){if(typeof showToast==='function')showToast('Update failed','error');});
};
window.ormDeleteKri=async function(id){
  if(!confirm('Delete this KRI?'))return;
  try{await apiFetch('/orm/api/kris/'+id,{method:'DELETE'});ormLoadKris();}
  catch(e){if(typeof showToast==='function')showToast('Delete failed','error');}
};
window.ormOpenKriModal=async function(existing){
  var isEdit=!!(existing&&existing.id);
  var preset=existing||{};
  var users=await ormLoadUsers();
  var html='<div class="orm-modal-overlay" id="kriModal" data-orm-static-click="s37">'+
    '<div class="modal-box" data-s="s04391f0">'+
      '<button class="modal-close" data-orm-static-click="s46">&#10005;</button>'+
      '<div class="modal-title">'+(isEdit?'Edit':'Add')+' Key Risk Indicator</div>'+
      '<div class="form-group"><label>Name *</label><input id="kr_name" value="'+esc(preset.name||'')+'"></div>'+
      '<div class="form-group"><label>Description</label><input id="kr_desc" value="'+esc(preset.description||'')+'"></div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Metric Type</label><select id="kr_type">'+['count','amount','percentage','duration'].map(function(t){return'<option value="'+t+'"'+(preset.metric_type===t?' selected':'')+'>'+t+'</option>';}).join('')+'</select></div>'+
        '<div class="form-group"><label>Unit</label><input id="kr_unit" placeholder="e.g. events, $, %, hours" value="'+esc(preset.unit||'events')+'"></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Warning Threshold</label><input type="number" id="kr_warn" value="'+esc(preset.threshold_warn??'')+'"></div>'+
        '<div class="form-group"><label>Critical Threshold</label><input type="number" id="kr_crit" value="'+esc(preset.threshold_crit??'')+'"></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Current Value</label><input type="number" id="kr_val" value="'+(isEdit?(existing.current_value||0):0)+'"></div>'+
        '<div class="form-group"><label>Frequency</label><select id="kr_freq">'+['daily','weekly','monthly','quarterly'].map(function(f){return'<option value="'+f+'"'+(preset.frequency===f?' selected':'')+'>'+f+'</option>';}).join('')+'</select></div>'+
      '</div>'+
      '<div class="form-group"><label>Auto-update when event type is logged <span data-s="sb569cab">(optional)</span></label>'+
        '<select id="kr_auto_type">'+
          '<option value="">— Manual updates only —</option>'+
          ['process_failure','fraud','system_failure','human_error','outage','vendor_failure','customer_impact'].map(function(t){
            return'<option value="'+t+'"'+(preset.auto_update_event_type===t?' selected':'')+'>'+typeIcon(t)+' '+t.replace(/_/g,' ')+'</option>';
          }).join('')+
        '</select>'+
      '</div>'+
      '<div class="form-group"><label>Auto-update notes <span data-s="sb569cab">(optional)</span></label><input id="kr_auto_notes" placeholder="e.g. increments by 1 per matching event" value="'+esc(preset.auto_update_notes||'')+'"></div>'+
      '<div class="form-group"><label>Owner</label><select id="kr_owner">'+
        '<option value="">— Unassigned —</option>'+
        users.map(function(u){return'<option value="'+u.id+'"'+(isEdit&&existing.owner_id==u.id?' selected':'')+'>'+esc(u.full_name)+'</option>';}).join('')+
      '</select></div>'+
      '<div data-s="sd28ceac" data-sd="flex">'+
        '<button class="btn btn-secondary" data-orm-static-click="s46">Cancel</button>'+
        '<button class="btn btn-primary" data-orm-save-call="ormSaveKri" data-orm-save-id="'+(isEdit?ormAttrId(existing.id):'')+'" data-orm-save-edit="'+(isEdit?'1':'0')+'">Save KRI</button>'+
      '</div>'+
    '</div></div>';
  document.body.insertAdjacentHTML('beforeend',html);
};
window.ormSaveKri=async function(id){
  var name=document.getElementById('kr_name').value.trim();
  if(!name){if(typeof showToast==='function')showToast('Name required','error');return;}
  var data={name:name,description:document.getElementById('kr_desc').value.trim(),metric_type:document.getElementById('kr_type').value,unit:document.getElementById('kr_unit').value.trim(),threshold_warn:parseFloat(document.getElementById('kr_warn').value)||null,threshold_crit:parseFloat(document.getElementById('kr_crit').value)||null,current_value:parseFloat(document.getElementById('kr_val').value)||0,frequency:document.getElementById('kr_freq').value,owner_id:document.getElementById('kr_owner').value||null,auto_update_event_type:document.getElementById('kr_auto_type').value||null,auto_update_notes:document.getElementById('kr_auto_notes').value.trim()||null};
  try{
    if(id)await apiFetch('/orm/api/kris/'+id,{method:'PUT',body:data});
    else await apiFetch('/orm/api/kris',{method:'POST',body:data});
    document.getElementById('kriModal').remove();ormLoadKris();
    if(typeof showToast==='function')showToast('KRI saved');
  }catch(e){if(typeof showToast==='function')showToast('Save failed','error');}
};

/* ─────────────────────────── REPORTS ─────────────────────────── */
window.ormLoadReports=async function(){
  try{
    var d=await apiFetch('/orm/api/dashboard');
    populateStatCards('rptStatCards',[
      {label:'Total Events',value:d.total_events||0},
      {label:'Total Loss',value:fmtCurrency(d.financial_loss||0),color:d.financial_loss>0?'var(--red)':'var(--text)'},
      {label:'Customers Affected',value:(d.customers_affected||0).toLocaleString()},
      {label:'Downtime Hours',value:d.downtime_hours||0}
    ]);
    ormRenderTypeChart('rptTypeChart',d.by_type||[]);

    // Load all events for ring charts + heat table + trend
    var evts=await apiFetch('/orm/api/events');
    var events=Array.isArray(evts)?evts:[];

    // Severity ring chart
    var sc={critical:0,high:0,medium:0,low:0};
    events.forEach(function(e){var s=(e.severity||'').toLowerCase();if(sc.hasOwnProperty(s))sc[s]++;});
    ormDrawRing('rptSevRing','rptSevLegend',[
      {label:'Critical',count:sc.critical,color:'var(--red)'},
      {label:'High',count:sc.high,color:'var(--amber,#d97706)'},
      {label:'Medium',count:sc.medium,color:'#6366f1'},
      {label:'Low',count:sc.low,color:'var(--good,#16a34a)'}
    ]);

    // Root cause ring chart
    var rcaMap={};
    events.forEach(function(e){var c=e.root_cause_category||'unknown';rcaMap[c]=(rcaMap[c]||0)+1;});
    var rcaColors={people:'#f59e0b',process:'#6366f1',system:'#0ea5e9',external:'#10b981',unknown:'#94a3b8'};
    var rcaSegs=Object.entries(rcaMap).sort(function(a,b){return b[1]-a[1];}).map(function(kv){return{label:kv[0],count:kv[1],color:rcaColors[kv[0]]||'var(--accent)'};});
    ormDrawRing('rptRcaRing','rptRcaLegend',rcaSegs.length?rcaSegs:[{label:'No data',count:0,color:'var(--surface3)'}]);

    // Dept heat table
    ormRenderDeptHeat(events);

    // Loss trend
    ormRenderLossTrend(events);

  }catch(e){console.error('ORM reports error',e);}
};

function ormRenderDeptHeat(events){
  var el=document.getElementById('rptDeptHeat');if(!el)return;
  var sevs=['critical','high','medium','low'];
  var dMap={};
  events.forEach(function(e){
    var d=e.department||'Unknown';var s=(e.severity||'unknown').toLowerCase();
    if(!dMap[d])dMap[d]={};dMap[d][s]=(dMap[d][s]||0)+1;
  });
  var depts=Object.keys(dMap).sort();
  if(!depts.length){el.innerHTML='<div data-s="s686c270">No department data — add departments when logging events</div>';return;}
  var maxCnt=1;
  depts.forEach(function(d){sevs.forEach(function(s){if((dMap[d][s]||0)>maxCnt)maxCnt=dMap[d][s];});});
  var sevRgb={critical:'220,38,38',high:'245,158,11',medium:'99,102,241',low:'22,163,74'};
  el.innerHTML='<table data-s="sa125070">'+
    '<thead><tr><th data-s="s003efe6">Dept</th>'+
    sevs.map(function(s){return'<th data-s="s506b5f8">'+s+'</th>';}).join('')+
    '<th data-s="sa04a661">Total</th></tr></thead>'+
    '<tbody>'+depts.map(function(d){
      var rowTotal=sevs.reduce(function(s,sv){return s+(dMap[d][sv]||0);},0);
      return'<tr><td data-s="s6df6768">'+esc(d)+'</td>'+
        sevs.map(function(s){
          var cnt=dMap[d][s]||0;
          var op=cnt>0?(0.12+(cnt/maxCnt)*0.65).toFixed(2):'0';
          var rgb=sevRgb[s]||'99,102,241';
          return'<td data-s="s42cd250">'+
            (cnt>0?'<span class="orm-heat-cell" title="'+escChartAttr(d)+': '+escChartAttr(s)+' severity, '+cnt+' events" data-sv="display:inline-block;min-width:26px;padding:2px 6px;border-radius:8px;font-size:12px;font-weight:700;background:rgba('+rgb+','+op+');color:rgba('+rgb+',.95)">'+cnt+'</span>':'<span data-s="sae9318f">—</span>')+
          '</td>';
        }).join('')+
        '<td data-s="s56edc85">'+rowTotal+'</td></tr>';
    }).join('')+'</tbody></table>';
}

function ormRenderLossTrend(events){
  var el=document.getElementById('rptLossTrend');if(!el)return;
  var now=new Date();
  var months=[];
  for(var i=5;i>=0;i--){
    var dt=new Date(now.getFullYear(),now.getMonth()-i,1);
    months.push({key:dt.getFullYear()+'-'+(dt.getMonth()+1).toString().padStart(2,'0'),label:dt.toLocaleDateString('en-GB',{month:'short',year:'2-digit'}),loss:0});
  }
  events.forEach(function(e){
    if(!(parseFloat(e.financial_impact)>0))return;
    var d=new Date(e.created_at&&e.created_at.includes('T')?e.created_at:e.created_at+'Z');
    var key=d.getFullYear()+'-'+(d.getMonth()+1).toString().padStart(2,'0');
    var mo=months.find(function(m){return m.key===key;});
    if(mo)mo.loss+=parseFloat(e.financial_impact);
  });
  var maxL=Math.max.apply(null,months.map(function(m){return m.loss;}).concat([1]));
  el.innerHTML=months.map(function(m){
    var pct=(m.loss/maxL*100).toFixed(1);
    return'<div data-s="s761d3ad">'+
      '<div data-s="sc76ac38" data-sd="flex">'+
        '<span data-s="sf045bbe">'+esc(m.label)+'</span>'+
        '<span data-sv="color:'+(m.loss>0?'var(--red)':'var(--muted)')+'">'+fmtCurrency(m.loss)+'</span>'+
      '</div>'+
      '<div data-s="sac3dcd9">'+
        '<div class="premium-chart-bar" data-sv="height:100%;width:'+pct+'%;background:var(--red,#dc2626);border-radius:100px;transition:width .6s ease" title="'+escChartAttr(m.label)+': '+escChartAttr(fmtCurrency(m.loss))+'"></div>'+
      '</div>'+
    '</div>';
  }).join('');
}

window.ormBoardReport=async function(btn){
  var orig=btn.textContent;btn.disabled=true;btn.textContent='Generating…';
  try{
    var res=await apiFetch('/orm/api/ai/board-report',{method:'POST',body:{days:30}});
    btn.disabled=false;btn.textContent=orig;
    ormOpenDocViewer('ORM Board Report: '+new Date().toLocaleDateString('en-GB'),(res.narrative||'No narrative generated.')+(res.narrative_check?'\n\n'+res.narrative_check:''));
  }catch(e){btn.disabled=false;btn.textContent=orig;if(typeof showToast==='function')showToast('Board report failed','error');}
};

/* ─────────────────────────── CHAT ─────────────────────────── */
var chatLoaded=false;
window.ormLoadChat=async function(){
  if(chatLoaded)return;chatLoaded=true;
  try{
    var data=await apiFetch('/orm/api/chat');
    var msgs=Array.isArray(data)?data:[];
    if(msgs.length){
      // Hide prompt chips if history exists
      var chips=document.getElementById('ormPromptChips');
      if(chips)chips.style.display='none';
      var container=document.getElementById('ormChatMsgs');
      msgs.forEach(function(m){
        var div=document.createElement('div');
        var isUser=m.role==='user';
        div.style.cssText=isUser?'align-self:flex-end;background:var(--accent);color:white;padding:12px 16px;border-radius:var(--radius-lg);font-size:14px;max-width:80%;line-height:1.5':'align-self:flex-start;background:var(--surface2);padding:12px 16px;border-radius:var(--radius-lg);font-size:14px;max-width:80%;line-height:1.5';
        div.innerHTML=esc(m.content||'').replace(/\n/g,'<br>');
        container.appendChild(div);
      });
      container.scrollTop=container.scrollHeight;
    }
  }catch(e){}
};
window.ormSendChat=async function(){
  var input=document.getElementById('ormChatInput');
  var msg=input.value.trim();if(!msg)return;
  // Hide prompt chips on first message
  var chips=document.getElementById('ormPromptChips');if(chips)chips.style.display='none';
  input.value='';
  var container=document.getElementById('ormChatMsgs');
  var ud=document.createElement('div');
  ud.style.cssText='align-self:flex-end;background:var(--accent);color:white;padding:12px 16px;border-radius:var(--radius-lg);font-size:14px;max-width:80%;line-height:1.5';
  ud.textContent=msg;container.appendChild(ud);container.scrollTop=container.scrollHeight;
  var tid='t-'+Date.now();
  var ad=document.createElement('div');ad.id=tid;
  ad.style.cssText='align-self:flex-start;background:var(--surface2);padding:12px 16px;border-radius:var(--radius-lg);font-size:14px;max-width:80%;line-height:1.5';
  ad.innerHTML='<div class="spinner" data-s="se29191c"></div>';
  container.appendChild(ad);container.scrollTop=container.scrollHeight;
  try{
    var d=await apiFetch('/orm/api/chat',{method:'POST',body:{message:msg}});
    var el=document.getElementById(tid);
    if(el)el.innerHTML=esc(d.reply||'No reply.').replace(/\n/g,'<br>');
  }catch(e){var el2=document.getElementById(tid);if(el2)el2.textContent='Error — please try again.';}
  container.scrollTop=container.scrollHeight;
};
window.ormSendPromptChip=function(msg){
  var chips=document.getElementById('ormPromptChips');if(chips)chips.style.display='none';
  document.getElementById('ormChatInput').value=msg;
  ormSendChat();
};

/* ─────────────────────────── EVENT TEMPLATES ─────────────────────────── */
var TMPL_CATEGORIES=[
  {key:'',label:'All Templates',icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-clipboard-list></use></svg>',color:'var(--accent)'},
  {key:'Cybersecurity',label:'Cybersecurity',icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-shield></use></svg>',color:'#dc2626'},
  {key:'Data & Privacy',label:'Data & Privacy',icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-lock></use></svg>',color:'#7c3aed'},
  {key:'Process & Operations',label:'Process & Ops',icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-settings></use></svg>',color:'#ea580c'},
  {key:'Technology & Systems',label:'Technology',icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-laptop></use></svg>',color:'#0ea5e9'},
  {key:'People & HR',label:'People & HR',icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-user></use></svg>',color:'#16a34a'},
  {key:'Financial & Fraud',label:'Financial & Fraud',icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-dollar-sign></use></svg>',color:'#b45309'},
  {key:'Vendor & Third Party',label:'Vendor & 3rd Party',icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-package></use></svg>',color:'#0891b2'},
  {key:'Compliance & Regulatory',label:'Compliance',icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-scale></use></svg>',color:'#be123c'}
];
var tmplCache=[],tmplCatFilter='',tmplSearch='';

var TMPL_CAT_COLORS={
  'Cybersecurity':'rgba(220,38,38,.12)',
  'Data & Privacy':'rgba(124,58,237,.12)',
  'Process & Operations':'rgba(234,88,12,.12)',
  'Technology & Systems':'rgba(14,165,233,.12)',
  'People & HR':'rgba(22,163,74,.12)',
  'Financial & Fraud':'rgba(180,83,9,.12)',
  'Vendor & Third Party':'rgba(8,145,178,.12)',
  'Compliance & Regulatory':'rgba(190,18,60,.12)'
};
var TMPL_CAT_TEXT_COLORS={
  'Cybersecurity':'#dc2626','Data & Privacy':'#7c3aed',
  'Process & Operations':'#ea580c','Technology & Systems':'#0ea5e9',
  'People & HR':'#16a34a','Financial & Fraud':'#b45309',
  'Vendor & Third Party':'#0891b2','Compliance & Regulatory':'#be123c'
};

window.ormOpenTemplates=async function(){
  document.body.insertAdjacentHTML('beforeend',
    '<div class="orm-tmpl-overlay" id="ormTmplOverlay" data-orm-static-click="s47">'+
      '<div class="orm-tmpl-panel" data-orm-static-click="s48">'+
        '<div class="orm-tmpl-head">'+
          '<div data-s="sb9199e2"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-clipboard-list></use></svg></div>'+
          '<div data-s="s97445a8">'+
            '<div data-s="s57e146b">Event Templates</div>'+
            '<div data-s="s7fc448e">Select a template to activate instantly or customise before logging</div>'+
          '</div>'+
          '<input id="tmplSearch" class="orm-search" placeholder="Search templates…" data-s="sa5d7a03" data-orm-static-input="s49">'+
          '<button class="btn btn-sm btn-secondary" data-orm-static-click="s50" title="Create custom template">+ Custom</button>'+
          '<button data-s="sd92e39d" data-orm-static-click="s51">&#10005;</button>'+
        '</div>'+
        '<div class="orm-tmpl-body">'+
          '<div class="orm-tmpl-filter-bar" id="tmplCatBar">'+
            TMPL_CATEGORIES.map(function(c){
              return'<button class="orm-tmpl-chip'+(c.key===''?' active':'')+'" data-cat="'+esc(c.key)+'" data-orm-special="tmpl-cat">'+c.icon+' '+esc(c.label)+'</button>';
            }).join('')+
          '</div>'+
          '<div id="tmplGrid" data-s="s10d6b93" data-sd="grid"></div>'+
        '</div>'+
      '</div>'+
    '</div>'
  );
  var grid=document.getElementById('tmplGrid');
  if(grid)grid.innerHTML='<div data-s="s6ffcb09"><div class="spinner" data-s="s266e9b0"></div></div>';
  try{
    var data=await apiFetch('/orm/api/event-templates');
    tmplCache=Array.isArray(data)?data:[];
    tmplCatFilter='';tmplSearch='';
    ormRenderTemplates();
  }catch(e){var g=document.getElementById('tmplGrid');if(g)g.innerHTML='<div data-s="s1eb2c51">Failed to load templates</div>';}
};

window.ormCloseTemplates=function(){
  var el=document.getElementById('ormTmplOverlay');
  if(el)el.remove();
};

window.ormTmplCat=function(btn,cat){
  document.querySelectorAll('#tmplCatBar .orm-tmpl-chip').forEach(function(b){b.classList.remove('active');});
  btn.classList.add('active');
  tmplCatFilter=cat;
  ormRenderTemplates();
};

function ormRenderTemplates(){
  var grid=document.getElementById('tmplGrid');if(!grid)return;
  var filtered=tmplCache.filter(function(t){
    if(tmplCatFilter&&t.category!==tmplCatFilter)return false;
    if(tmplSearch){
      var q=tmplSearch;
      if(!((t.title||'').toLowerCase().includes(q)||(t.description||'').toLowerCase().includes(q)||(t.tags||'').toLowerCase().includes(q)))return false;
    }
    return t.is_active!==0;
  });
  if(!filtered.length){
    grid.innerHTML='<div data-s="s5da5b59">'+
      '<div data-s="s30de678"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-clipboard-list></use></svg></div>'+
      '<div data-s="sfe496b8">No templates match your search</div>'+
      '<button class="btn btn-secondary" data-s="s56f4356" data-orm-static-click="s50">+ Create Custom Template</button>'+
    '</div>';
    return;
  }
  grid.innerHTML=filtered.map(function(t){
    var catColor=TMPL_CAT_TEXT_COLORS[t.category]||'var(--accent)';
    var catBg=TMPL_CAT_COLORS[t.category]||'rgba(99,102,241,.1)';
    var catObj=TMPL_CATEGORIES.find(function(c){return c.key===t.category;})||{icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-clipboard-list></use></svg>'};
    var tags=(t.tags||'').split(',').filter(Boolean).slice(0,3);
    var usageHint=t.usage_count>0?'<span data-s="s54aee87">Used '+t.usage_count+'&#215;</span>':'';
    return'<div class="orm-tmpl-card">'+
      '<div class="orm-tmpl-card-top">'+
        '<div>'+
          '<span class="orm-cat-chip" data-sv="background:'+catBg+';color:'+catColor+';margin-bottom:6px;display:inline-block">'+catObj.icon+' '+esc(t.category)+'</span>'+
          '<div class="orm-tmpl-card-title">'+esc(t.title)+'</div>'+
        '</div>'+
        sevBadge(t.severity)+
      '</div>'+
      '<div class="orm-tmpl-card-desc">'+esc(t.description||'')+'</div>'+
      '<div class="orm-tmpl-card-footer">'+
        '<span data-s="s11a5081"><span data-s="s5e0faad">'+typeIcon(t.event_type)+'</span> '+esc((t.event_type||'').replace(/_/g,' '))+'</span>'+
        (tags.length?tags.map(function(tag){return'<span data-s="sc16e5c0">'+esc(tag.trim())+'</span>';}).join(''):'')+
        usageHint+
      '</div>'+
      '<div data-s="s23e32a9" data-sd="flex">'+
        '<button class="btn btn-primary js-activate-orm-template" data-template-id="'+Number(t.id)+'" data-template-title="'+esc(t.title)+'" data-s="s5a95af4" title="Create event immediately with template defaults">&#9658; Activate</button>'+
        '<button class="btn btn-secondary" data-s="s5a95af4" data-orm-call="ormCustomiseTemplate" data-orm-id="'+ormAttrId(t.id)+'" title="Pre-fill Log Event form for review before saving"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg> Customise</button>'+
      '</div>'+
    '</div>';
  }).join('');
}

window.ormActivateTemplate=async function(id,title){
  if(!confirm('Activate template "'+title+'"?\n\nThis will create an open event immediately. You can edit details afterwards.'))return;
  try{
    var res=await apiFetch('/orm/api/event-templates/'+id+'/activate',{method:'POST',body:{}});
    ormCloseTemplates();
    if(ormRouter.current==='events')ormLoadEvents();else ormLoadDashboard();
    if(typeof showToast==='function')showToast('Event created from template — Event #'+res.id);
  }catch(e){if(typeof showToast==='function')showToast('Activation failed','error');}
};

window.ormCustomiseTemplate=async function(id){
  var tmpl=tmplCache.find(function(t){return t.id===id;});
  if(!tmpl)return;
  ormCloseTemplates();
  // Pre-fill the event modal with template values — user can review & edit before saving
  await ormOpenEventModal({
    title:tmpl.title,description:tmpl.description,
    event_type:tmpl.event_type,severity:tmpl.severity,
    department:tmpl.department||'',process_affected:tmpl.process_affected||'',
    root_cause_category:tmpl.root_cause_category||'',
    corrective_action:tmpl.corrective_action||'',
    preventive_action:tmpl.preventive_action||'',
    basel_category:tmpl.basel_category||'',
    status:'open',_from_template:id
  });
  // Increment usage count in background
  apiFetch('/orm/api/event-templates/'+id+'/activate',{method:'POST',body:{_preview_only:true}}).catch(function(){});
};

/* ── Custom Template Creation Modal ── */
window.ormOpenTemplateModal=async function(existing){
  ormCloseTemplates();
  var isEdit=!!(existing&&existing.id);
  var html='<div class="orm-modal-overlay" id="ormTmplEditModal" data-orm-static-click="s37">'+
    '<div class="modal-box" data-s="se2b01b0">'+
      '<button class="modal-close" data-orm-static-click="s52">&#10005;</button>'+
      '<div class="modal-title">'+(isEdit?'Edit':'Create Custom')+' Event Template</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Template Title *</label><input id="tm_title" value="'+esc(isEdit?(existing.title||''):'')+'"></div>'+
        '<div class="form-group"><label>Category *</label><select id="tm_cat">'+
          TMPL_CATEGORIES.slice(1).map(function(c){return'<option value="'+c.key+'"'+(isEdit&&existing.category===c.key?' selected':'')+'>'+esc(c.label)+'</option>';}).join('')+
        '</select></div>'+
      '</div>'+
      '<div class="form-group"><label>Description</label><textarea id="tm_desc" rows="2" data-s="sa57b154">'+esc(isEdit?(existing.description||''):'')+'</textarea></div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Event Type</label><select id="tm_type">'+['process_failure','fraud','system_failure','human_error','outage','vendor_failure','customer_impact'].map(function(t){return'<option value="'+t+'"'+(isEdit&&existing.event_type===t?' selected':'')+'>'+typeIcon(t)+' '+t.replace(/_/g,' ')+'</option>';}).join('')+'</select></div>'+
        '<div class="form-group"><label>Severity</label><select id="tm_sev">'+['low','medium','high','critical'].map(function(s){return'<option value="'+s+'"'+(isEdit&&existing.severity===s?' selected':'')+'>'+s+'</option>';}).join('')+'</select></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Default Department</label><input id="tm_dept" value="'+esc(isEdit?(existing.department||''):'')+'"></div>'+
        '<div class="form-group"><label>Process Affected</label><input id="tm_proc" value="'+esc(isEdit?(existing.process_affected||''):'')+'"></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Root Cause Category</label><select id="tm_rcc">'+['','people','process','system','external'].map(function(c){return'<option value="'+c+'"'+(isEdit&&existing.root_cause_category===c?' selected':'')+'>'+esc(c||'— Select —')+'</option>';}).join('')+'</select></div>'+
        '<div class="form-group"><label>Tags (comma-separated)</label><input id="tm_tags" placeholder="e.g. fraud,cyber,payment" value="'+esc(isEdit?(existing.tags||''):'')+'"></div>'+
      '</div>'+
      '<div class="form-group"><label>Basel III Category <span data-s="s8e93b13">(optional — financial services)</span></label>'+
        '<select id="tm_basel">'+
          '<option value="">— Not specified —</option>'+
          ['internal_fraud','external_fraud','employment_practices','clients_products','physical_assets','business_disruption','execution_delivery'].map(function(c){
            var labels={internal_fraud:'Internal Fraud',external_fraud:'External Fraud',employment_practices:'Employment Practices & Workplace Safety',clients_products:'Clients, Products & Business Practices',physical_assets:'Damage to Physical Assets',business_disruption:'Business Disruption & System Failures',execution_delivery:'Execution, Delivery & Process Management'};
            return'<option value="'+c+'"'+(isEdit&&existing.basel_category===c?' selected':'')+'>'+esc(labels[c]||c)+'</option>';
          }).join('')+
        '</select>'+
      '</div>'+
      '<div class="form-group"><label>Corrective Action Template</label><textarea id="tm_corr" rows="3" data-s="sa57b154">'+esc(isEdit?(existing.corrective_action||''):'')+'</textarea></div>'+
      '<div class="form-group"><label>Preventive Action Template</label><textarea id="tm_prev" rows="3" data-s="sa57b154">'+esc(isEdit?(existing.preventive_action||''):'')+'</textarea></div>'+
      '<div data-s="sd28ceac" data-sd="flex">'+
        '<button class="btn btn-secondary" data-orm-static-click="s52">Cancel</button>'+
        '<button class="btn btn-primary" data-orm-save-call="ormSaveTemplate" data-orm-save-id="'+(isEdit?ormAttrId(existing.id):'')+'" data-orm-save-edit="'+(isEdit?'1':'0')+'">Save Template</button>'+
      '</div>'+
    '</div></div>';
  document.body.insertAdjacentHTML('beforeend',html);
  setTimeout(function(){var t=document.getElementById('tm_title');if(t)t.focus();},80);
};
window.ormSaveTemplate=async function(id){
  var title=document.getElementById('tm_title').value.trim();
  if(!title){if(typeof showToast==='function')showToast('Title required','error');return;}
  var data={title:title,description:document.getElementById('tm_desc').value.trim(),category:document.getElementById('tm_cat').value,event_type:document.getElementById('tm_type').value,severity:document.getElementById('tm_sev').value,department:document.getElementById('tm_dept').value.trim()||null,process_affected:document.getElementById('tm_proc').value.trim()||null,root_cause_category:document.getElementById('tm_rcc').value||null,basel_category:document.getElementById('tm_basel').value||null,tags:document.getElementById('tm_tags').value.trim()||null,corrective_action:document.getElementById('tm_corr').value.trim()||null,preventive_action:document.getElementById('tm_prev').value.trim()||null,is_active:1};
  try{
    if(id)await apiFetch('/orm/api/event-templates/'+id,{method:'PUT',body:data});
    else await apiFetch('/orm/api/event-templates',{method:'POST',body:data});
    document.getElementById('ormTmplEditModal').remove();
    if(typeof showToast==='function')showToast('Template saved');
  }catch(e){if(typeof showToast==='function')showToast('Save failed','error');}
};

/* ─────────────────────────── WORKFLOW STEPPER ─────────────────────────── */
var WF_STEPS=[
  {key:'identified',label:'Identified'},
  {key:'under_investigation',label:'Investigating'},
  {key:'root_cause_confirmed',label:'Root Cause'},
  {key:'remediation',label:'Remediation'},
  {key:'closed',label:'Closed'}
];
function ormWorkflowStepper(e){
  var cur=e.workflow_step||'identified';
  var curIdx=WF_STEPS.findIndex(function(s){return s.key===cur;});
  if(curIdx<0)curIdx=0;
  return'<div class="orm-stepper">'+WF_STEPS.map(function(s,i){
    var cls=i<curIdx?'done':i===curIdx?'active':'';
    var canAdvance=i===curIdx+1;
    return'<div class="orm-step '+(i<=curIdx?'done':'')+'">'+
      '<div class="orm-step-dot '+cls+'" '+
        (canAdvance?'data-orm-special="advance-workflow" data-orm-id="'+ormAttrId(e.id)+'" data-orm-step="'+esc(s.key)+'" title="Advance to '+s.label+'" data-s="s3b6a3a6"':'title="'+s.label+'"')+
        '>'+
        (i<curIdx?'&#10003;':(i===curIdx?'&#8226;':(i+1).toString()))+
      '</div>'+
      '<div class="orm-step-label">'+esc(s.label)+'</div>'+
    '</div>';
  }).join('')+'</div>';
}
window.ormAdvanceWorkflow=async function(eventId,toStep){
  try{
    await apiFetch('/orm/api/events/'+eventId+'/workflow',{method:'POST',body:{step:toStep}});
    if(typeof showToast==='function')showToast('Workflow advanced');
    ormCloseDrawer();
    if(ormRouter.current==='events')ormLoadEvents();
    else ormLoadDashboard();
  }catch(e){if(typeof showToast==='function')showToast('Workflow update failed','error');}
};
window.ormToggleWfHistory=async function(eventId){
  var el=document.getElementById('wfHistory-'+eventId);if(!el)return;
  if(el.style.display==='block'){el.style.display='none';return;}
  el.style.display='block';
  el.innerHTML='<div class="spinner" data-s="s4bb51cc"></div>';
  try{
    var hist=await apiFetch('/orm/api/events/'+eventId+'/workflow');
    if(!hist||!hist.length){el.innerHTML='<div data-s="s303c838">No history yet</div>';return;}
    el.innerHTML='<div data-s="seb9e601">'+
      hist.map(function(h){
        return'<div data-s="sf30f404">'+
          '<div data-s="s929d193"></div>'+
          '<span data-s="seed0f8f">'+esc((h.to_step||'').replace(/_/g,' '))+'</span>'+
          '<span data-s="s9c02f94">'+fmtDate(h.changed_at)+'</span>'+
          (h.changed_by_name?'<span data-s="s9c02f94">by '+esc(h.changed_by_name)+'</span>':'')+
          (h.notes?'<div data-s="s6d034cc">'+esc(h.notes)+'</div>':'')+
        '</div>';
      }).join('')+
    '</div>';
  }catch(ex){el.innerHTML='<div data-s="sadbd53f">Failed to load history</div>';}
};

/* ─────────────────────────── RCSA ─────────────────────────── */
var rcsaCache=[];
window.ormLoadRcsa=async function(){
  var body=document.getElementById('rcsaBody');
  if(body)body.innerHTML='<tr><td colspan="9" data-s="s453f6c2"><div class="spinner" data-s="s266e9b0"></div></td></tr>';
  try{
    var data=await apiFetch('/orm/api/rcsa');
    rcsaCache=Array.isArray(data)?data:[];
    var total=rcsaCache.length;
    var active=rcsaCache.filter(function(a){return a.status==='active';}).length;
    var completed=rcsaCache.filter(function(a){return a.status==='completed';}).length;
    var openActs=rcsaCache.reduce(function(s,a){return s+(a.open_actions||0);},0);
    populateStatCards('rcsaStats',[
      {label:'Total Assessments',value:total},
      {label:'Active',value:active,color:active>0?'var(--accent)':'var(--text)'},
      {label:'Completed',value:completed,color:'var(--good,#16a34a)'},
      {label:'Open Actions',value:openActs,color:openActs>0?'var(--amber,#d97706)':'var(--text)'}
    ]);
    var navBadge=document.getElementById('ormNavRcsa');
    if(navBadge)navBadge.textContent=total||'';
    if(!rcsaCache.length){
      if(body)body.innerHTML='<tr><td colspan="9" data-s="s810afb2">No RCSA campaigns yet. Click "+ New Assessment" to start.</td></tr>';
      return;
    }
    if(body)body.innerHTML=rcsaCache.map(function(a){
      var statusColors={draft:'badge-draft',active:'badge-progress',under_review:'badge-high',completed:'badge-complete'};
      var sc=statusColors[a.status]||'badge-draft';
      var periodStr=(a.period_start?fmtDate(a.period_start):'—')+(a.period_end?' – '+fmtDate(a.period_end):'');
      return'<tr>'+
        '<td data-s="s49b2015" data-orm-call="ormOpenRcsaDetail" data-orm-id="'+ormAttrId(a.id)+'">'+esc(a.title)+'</td>'+
        '<td data-s="s7fc448e">'+esc(a.scope||'—')+'</td>'+
        '<td data-s="s7fc448e">'+esc(periodStr)+'</td>'+
        '<td><span class="badge '+sc+'">'+esc((a.status||'draft').replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();}))+'</span></td>'+
        '<td data-s="s6cb285c">'+esc(a.owner_name||'—')+'</td>'+
        '<td data-s="s7fc448e">'+fmtDate(a.due_date)+'</td>'+
        '<td data-s="s91a8701"><span class="badge badge-draft">'+esc(a.risk_count||0)+'</span></td>'+
        '<td data-s="s91a8701"><span class="badge '+(a.open_actions>0?'badge-high':'badge-draft')+'">'+esc(a.open_actions||0)+'</span></td>'+
        '<td><div data-s="sd767683" data-sd="flex">'+
          '<button class="btn btn-sm btn-secondary" data-orm-call="ormOpenRcsaDetail" data-orm-id="'+ormAttrId(a.id)+'" title="Open"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-search></use></svg></button>'+
          '<button class="btn btn-sm btn-secondary" data-orm-cache-call="ormOpenRcsaModal" data-orm-id="'+ormAttrId(a.id)+'"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button>'+
          '<button class="btn btn-sm btn-secondary" data-orm-call="ormDeleteRcsa" data-orm-id="'+ormAttrId(a.id)+'" data-s="s45e7ae4">&#10005;</button>'+
        '</div></td>'+
      '</tr>';
    }).join('');
  }catch(e){if(body)body.innerHTML='<tr><td colspan="9" data-s="saab7d13">Failed to load</td></tr>';}
};

window.ormOpenRcsaModal=async function(existing){
  var isEdit=!!(existing&&existing.id);
  var users=await ormLoadUsers();
  var html='<div class="orm-modal-overlay" id="rcsaModal" data-orm-static-click="s37">'+
    '<div class="modal-box" data-s="sf98945b">'+
      '<button class="modal-close" data-orm-static-click="s53">&#10005;</button>'+
      '<div class="modal-title">'+(isEdit?'Edit':'New')+' RCSA Campaign</div>'+
      '<div class="form-group"><label>Title *</label><input id="rc_title" value="'+esc(isEdit?(existing.title||''):'')+'"></div>'+
      '<div class="form-group"><label>Scope / Business Unit</label><input id="rc_scope" placeholder="e.g. Operations, IT, Finance" value="'+esc(isEdit?(existing.scope||''):'')+'"></div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Period Start</label><input type="date" id="rc_ps" value="'+(isEdit&&existing.period_start?existing.period_start.slice(0,10):'')+'"></div>'+
        '<div class="form-group"><label>Period End</label><input type="date" id="rc_pe" value="'+(isEdit&&existing.period_end?existing.period_end.slice(0,10):'')+'"></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Status</label><select id="rc_status">'+['draft','active','under_review','completed'].map(function(s){return'<option value="'+s+'"'+(isEdit&&existing.status===s?' selected':'')+'>'+s.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();})+'</option>';}).join('')+'</select></div>'+
        '<div class="form-group"><label>Due Date</label><input type="date" id="rc_due" value="'+(isEdit&&existing.due_date?existing.due_date.slice(0,10):'')+'"></div>'+
      '</div>'+
      '<div class="form-group"><label>Owner</label><select id="rc_owner">'+
        '<option value="">— Unassigned —</option>'+users.map(function(u){return'<option value="'+u.id+'"'+(isEdit&&existing.owner_id==u.id?' selected':'')+'>'+esc(u.full_name)+'</option>';}).join('')+
      '</select></div>'+
      '<div class="form-group"><label>Notes</label><textarea id="rc_notes" rows="2" data-s="sa57b154">'+esc(isEdit?(existing.notes||''):'')+'</textarea></div>'+
      '<div data-s="sd28ceac" data-sd="flex">'+
        '<button class="btn btn-secondary" data-orm-static-click="s53">Cancel</button>'+
        '<button class="btn btn-primary" data-orm-save-call="ormSaveRcsa" data-orm-save-id="'+(isEdit?ormAttrId(existing.id):'')+'" data-orm-save-edit="'+(isEdit?'1':'0')+'">Save</button>'+
      '</div>'+
    '</div></div>';
  document.body.insertAdjacentHTML('beforeend',html);
  setTimeout(function(){var t=document.getElementById('rc_title');if(t)t.focus();},80);
};
window.ormSaveRcsa=async function(id){
  var title=document.getElementById('rc_title').value.trim();
  if(!title){if(typeof showToast==='function')showToast('Title required','error');return;}
  var data={title:title,scope:document.getElementById('rc_scope').value.trim(),period_start:document.getElementById('rc_ps').value||null,period_end:document.getElementById('rc_pe').value||null,status:document.getElementById('rc_status').value,due_date:document.getElementById('rc_due').value||null,owner_id:document.getElementById('rc_owner').value||null,notes:document.getElementById('rc_notes').value.trim()};
  try{
    var res;
    if(id){await apiFetch('/orm/api/rcsa/'+id,{method:'PUT',body:data});res={id:id};}
    else{res=await apiFetch('/orm/api/rcsa',{method:'POST',body:data});}
    var newId=res&&(res.id||res.assessment_id);
    document.getElementById('rcsaModal').remove();
    // Apply template risks if one was selected
    var tmpl=window._selectedRcsaTemplate;
    if(tmpl&&tmpl.risks&&newId&&!id){
      for(var i=0;i<tmpl.risks.length;i++){
        var tr=tmpl.risks[i];
        await apiFetch('/orm/api/rcsa/'+newId+'/risks',{method:'POST',body:{title:tr.title,inherent_likelihood:tr.inherent_likelihood||3,inherent_impact:tr.inherent_impact||3,control_effectiveness:tr.control_effectiveness||3,notes:(tr.controls||[]).join('; ')}});
      }
      window._selectedRcsaTemplate=null;
      if(typeof showToast==='function'){showToast('Assessment saved');setTimeout(function(){showToast(tmpl.risks.length+' risks pre-populated from template');},800);}
    }else{
      if(typeof showToast==='function')showToast('Assessment saved');
    }
    ormLoadRcsa();
  }catch(e){if(typeof showToast==='function')showToast('Save failed','error');}
};
window.ormDeleteRcsa=async function(id){
  if(!confirm('Delete this assessment and all its risks, controls, and actions?'))return;
  try{await apiFetch('/orm/api/rcsa/'+id,{method:'DELETE'});ormLoadRcsa();}
  catch(e){if(typeof showToast==='function')showToast('Delete failed','error');}
};

/* ── RCSA Detail Drawer ── */
window.ormOpenRcsaDetail=async function(assessId){
  var drawer=document.getElementById('ormDrawerRoot');
  drawer.innerHTML='<div class="orm-drawer-overlay"><div class="orm-drawer-panel" data-s="sa3fa223"><div class="spinner"></div></div></div>';
  try{
    var a=await apiFetch('/orm/api/rcsa/'+assessId);
    var risks=await apiFetch('/orm/api/rcsa/'+assessId+'/risks');
    var actions=await apiFetch('/orm/api/rcsa/'+assessId+'/actions');
    await Promise.all(risks.map(async function(r){r.controls=await apiFetch('/orm/api/rcsa/risks/'+r.id+'/controls');}));
    window._rcsaControlsCache={};window._rcsaActionsCache={};
    risks.forEach(function(r){(r.controls||[]).forEach(function(c){window._rcsaControlsCache[c.id]=c;});});
    actions.forEach(function(ac){window._rcsaActionsCache[ac.id]=ac;});
    drawer.innerHTML='<div class="orm-drawer-overlay" data-orm-static-click="s41">'+
    '<div class="orm-drawer-panel" data-s="s0f5efc8">'+
      '<div class="orm-drawer-head">'+
        '<div data-s="sf0bc6e2" data-sd="flex">'+
          '<div>'+
            '<div data-s="s266e2f3">'+esc(a.title)+'</div>'+
            '<div data-s="sfc85ba5">'+(a.scope?esc(a.scope)+' &bull; ':'')+fmtDate(a.period_start)+' – '+fmtDate(a.period_end)+'</div>'+
          '</div>'+
          '<button class="btn btn-sm btn-secondary" data-orm-static-click="s42">&#10005;</button>'+
        '</div>'+
      '</div>'+
      '<div class="orm-drawer-body">'+
        /* Stats row */
        (function(){
          var avgResidual=risks.length?risks.reduce(function(s,r){return s+(r.residual_score||0);},0)/risks.length:0;
          var healthScore=risks.length?Math.max(0,Math.round((1-avgResidual/25)*100)):null;
          var hColor=healthScore===null?'var(--muted)':healthScore>=70?'var(--good,#16a34a)':healthScore>=40?'var(--amber,#d97706)':'var(--red)';
          return'<div data-s="s1036f8a" data-sd="grid">'+
            '<div data-s="s0ff1122"><div data-s="s0de5e1b">Risks</div><div data-s="s238e820">'+risks.length+'</div></div>'+
            '<div data-s="s0ff1122"><div data-s="s0de5e1b">Open Actions</div><div data-s="s1e77d68">'+(actions.filter(function(x){return x.status==='open';}).length)+'</div></div>'+
            '<div data-s="s0ff1122"><div data-s="s0de5e1b">Avg Residual</div><div data-s="s238e820">'+(risks.length?Math.round(avgResidual*10)/10:'—')+'</div></div>'+
            '<div data-s="s0ff1122"><div data-s="s0de5e1b">Health Score</div>'+
              (healthScore!==null?
                '<div data-sv="font-size:22px;font-weight:800;color:'+hColor+'">'+healthScore+'%</div>'+
                '<div data-s="sf59187f"><div data-sv="height:100%;width:'+healthScore+'%;background:'+hColor+';border-radius:100px;transition:width .8s ease"></div></div>'
                :'<div data-s="s4b4fbcd">—</div>')+
            '</div>'+
          '</div>';
        })()+
        /* Risks */
        '<div class="orm-drawer-section">'+
          '<div data-s="s91ebbdc" data-sd="flex">'+
            '<div class="orm-drawer-section-title" data-s="sef0b7a1">Assessed Risks</div>'+
            '<button class="btn btn-sm btn-primary" data-orm-call="ormAddRcsaRisk" data-orm-id="'+ormAttrId(assessId)+'">+ Add Risk</button>'+
          '</div>'+
          (risks.length?risks.map(function(r){
            var inherent=r.inherent_likelihood*r.inherent_impact;
            var effPct=((r.control_effectiveness||3)/5*100).toFixed(0);
            var effColor=r.control_effectiveness>=4?'var(--good,#16a34a)':r.control_effectiveness>=3?'var(--amber,#d97706)':'var(--red,#dc2626)';
            return'<div class="rcsa-risk-row">'+
              '<div data-s="s3ae5ff5" data-sd="flex">'+
                '<span data-s="s160b067">'+esc(r.title)+'</span>'+
                '<div data-s="saebb47c" data-sd="flex">'+
                  '<span data-s="s1fd8c81">Inherent: <strong>'+inherent+'</strong></span>'+
                  '<span data-s="sc086e5f">Residual: <strong>'+((r.residual_score||0).toFixed(1))+'</strong></span>'+
                '</div>'+
              '</div>'+
              '<div data-s="s24a3220" data-sd="flex">'+
                '<span>Control Effectiveness:</span>'+
                '<div data-s="s7a91738">'+
                  '<div data-sv="height:100%;width:'+effPct+'%;background:'+effColor+';border-radius:100px"></div>'+
                '</div>'+
                '<span data-sv="color:'+effColor+';font-weight:700">'+effPct+'%</span>'+
              '</div>'+
              (r.notes&&r.notes.includes(';')?
                '<div data-s="sbd3348d">'+
                  '<div data-s="sec6d1fe">&#10003; Suggested Controls</div>'+
                  r.notes.split(';').map(function(ctrl){
                    return ctrl.trim()?'<div data-s="scf50eba">&#8226; '+esc(ctrl.trim())+'</div>':'';
                  }).join('')+
                '</div>':'')+
              '<div data-s="sd2c171b">'+
                '<div data-s="s0e487c0" data-sd="flex">'+
                  '<span data-s="s0de5e1b">Controls ('+((r.controls||[]).length)+')</span>'+
                  '<button class="btn btn-sm btn-secondary" data-s="sba6396e" data-orm-complex="rcsa-control-add" data-orm-id="'+ormAttrId(r.id)+'" data-orm-id2="'+ormAttrId(assessId)+'">+ Control</button>'+
                '</div>'+
                ((r.controls&&r.controls.length)?r.controls.map(function(c){
                  var cActs=actions.filter(function(ac){return ac.control_id===c.id;});
                  var deColor=c.design_effectiveness==='adequate'?'var(--good,#16a34a)':c.design_effectiveness==='inadequate'?'var(--red,#dc2626)':'var(--muted)';
                  var oeColor=c.operating_effectiveness==='effective'?'var(--good,#16a34a)':c.operating_effectiveness==='ineffective'?'var(--red,#dc2626)':'var(--muted)';
                  return'<div data-s="s003eab3">'+
                    '<div data-s="s2d7d272" data-sd="flex">'+
                      '<span data-s="seb5cb58">'+esc(c.name)+'</span>'+
                      '<div data-s="sd767683" data-sd="flex">'+
                        '<button class="btn btn-sm btn-secondary" data-s="sf2d6bd2" data-orm-complex="rcsa-control-edit" data-orm-id="'+ormAttrId(r.id)+'" data-orm-id2="'+ormAttrId(c.id)+'" data-orm-id3="'+ormAttrId(assessId)+'" title="Edit"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button>'+
                        '<button class="btn btn-sm btn-secondary" data-s="s940537e" data-orm-call="ormDeleteRcsaControl" data-orm-id="'+ormAttrId(c.id)+'" data-orm-id2="'+ormAttrId(assessId)+'" title="Delete">&#10005;</button>'+
                      '</div>'+
                    '</div>'+
                    '<div data-s="s54c41d6">Design: <span data-sv="color:'+deColor+';font-weight:600">'+(c.design_effectiveness||'—').replace(/_/g,' ')+'</span>&nbsp;&bull;&nbsp;Operating: <span data-sv="color:'+oeColor+';font-weight:600">'+(c.operating_effectiveness||'—').replace(/_/g,' ')+'</span></div>'+
                    (c.gap_description?'<div data-s="s57a8188">Gap: '+esc(c.gap_description)+'</div>':'')+
                    '<div data-s="s249a6af" data-sd="flex">'+
                      '<span data-s="sb569cab">'+cActs.length+' action(s)'+(cActs.length?': '+cActs.map(function(ac){return esc(ac.title);}).join(', '):'')+'</span>'+
                      '<button class="btn btn-sm btn-secondary" data-s="s688d260" data-orm-complex="rcsa-action-add" data-orm-id="'+ormAttrId(c.id)+'" data-orm-id2="'+ormAttrId(assessId)+'">+ Action</button>'+
                    '</div>'+
                  '</div>';
                }).join(''):'<div data-s="s8fa4d6c">No controls recorded</div>')+
              '</div>'+
            '</div>';
          }).join(''):'<div data-s="sa316e87">No risks assessed yet</div>')+
        '</div>'+
        /* Actions */
        (actions.length?
          '<div class="orm-drawer-section">'+
            '<div class="orm-drawer-section-title">Remediation Actions</div>'+
            actions.map(function(ac){
              var s={open:'badge-high',in_progress:'badge-progress',completed:'badge-complete',overdue:'badge-critical'}[ac.status]||'badge-draft';
              return'<div data-s="s1485576" data-sd="flex">'+
                '<div>'+
                  '<div data-s="seb673ec">'+esc(ac.title)+'</div>'+
                  '<div data-s="s1fd8c81">'+esc(ac.control_name||'')+(ac.due_date?' &bull; Due '+fmtDate(ac.due_date):'')+'</div>'+
                '</div>'+
                '<div data-s="saebb47c" data-sd="flex">'+
                  '<span class="badge '+s+'">'+esc((ac.status||'open').replace(/_/g,' '))+'</span>'+
                  '<button class="btn btn-sm btn-secondary" data-s="sf2d6bd2" data-orm-complex="rcsa-action-edit" data-orm-id="'+ormAttrId(ac.control_id)+'" data-orm-id2="'+ormAttrId(ac.id)+'" data-orm-id3="'+ormAttrId(assessId)+'" title="Edit"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button>'+
                  '<button class="btn btn-sm btn-secondary" data-s="s940537e" data-orm-call="ormDeleteRcsaAction" data-orm-id="'+ormAttrId(ac.id)+'" data-orm-id2="'+ormAttrId(assessId)+'" title="Delete">&#10005;</button>'+
                '</div>'+
              '</div>';
            }).join('')+
          '</div>':'')+'</div>'+
      '<div class="orm-drawer-footer">'+
        '<button class="btn btn-secondary" data-orm-complex="rcsa-edit-close" data-orm-id="'+ormAttrId(assessId)+'"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg> Edit</button>'+
        '<button class="btn btn-primary" data-orm-static-click="s54">View All Assessments</button>'+
      '</div>'+
    '</div></div>';
    if(typeof DialogFocus!=='undefined')DialogFocus.trap(drawer.querySelector('.orm-drawer-panel'));
  }catch(ex){drawer.innerHTML='';}
};

window.ormAddRcsaRisk=async function(assessId){
  var users=await ormLoadUsers();
  var html='<div class="orm-modal-overlay" id="rcsaRiskModal" data-orm-static-click="s37">'+
    '<div class="modal-box" data-s="s765d57b">'+
      '<button class="modal-close" data-orm-static-click="s55">&#10005;</button>'+
      '<div class="modal-title">Add Assessed Risk</div>'+
      '<div class="form-group"><label>Risk Title *</label><input id="rr_title" placeholder="e.g. Unauthorised access to customer data"></div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Inherent Likelihood (1-5)</label><input type="number" id="rr_il" min="1" max="5" value="3"></div>'+
        '<div class="form-group"><label>Inherent Impact (1-5)</label><input type="number" id="rr_ii" min="1" max="5" value="3"></div>'+
      '</div>'+
      '<div class="form-group"><label>Control Effectiveness (1=Low, 5=High)</label>'+
        '<input type="range" id="rr_ce" min="1" max="5" value="3" data-s="s0466783" data-orm-static-input="s56">'+
        '<div data-s="s360d374" data-sd="flex"><span>1 Ineffective</span><span id="rr_ce_val" data-s="s4af5888">3</span><span>5 Effective</span></div>'+
      '</div>'+
      '<div class="form-group"><label>Owner</label><select id="rr_owner"><option value="">— Unassigned —</option>'+users.map(function(u){return'<option value="'+u.id+'">'+esc(u.full_name)+'</option>';}).join('')+'</select></div>'+
      '<div class="form-group"><label>Notes</label><textarea id="rr_notes" rows="2" data-s="sa57b154"></textarea></div>'+
      '<div data-s="sd28ceac" data-sd="flex">'+
        '<button class="btn btn-secondary" data-orm-static-click="s55">Cancel</button>'+
        '<button class="btn btn-primary" data-orm-call="ormSaveRcsaRisk" data-orm-id="'+ormAttrId(assessId)+'">Add Risk</button>'+
      '</div>'+
    '</div></div>';
  document.body.insertAdjacentHTML('beforeend',html);
  setTimeout(function(){var t=document.getElementById('rr_title');if(t)t.focus();},80);
};
window.ormSaveRcsaRisk=async function(assessId){
  var title=document.getElementById('rr_title').value.trim();
  if(!title){if(typeof showToast==='function')showToast('Title required','error');return;}
  var data={title:title,inherent_likelihood:parseInt(document.getElementById('rr_il').value)||3,inherent_impact:parseInt(document.getElementById('rr_ii').value)||3,control_effectiveness:parseInt(document.getElementById('rr_ce').value)||3,owner_id:document.getElementById('rr_owner').value||null,notes:document.getElementById('rr_notes').value.trim()};
  try{
    await apiFetch('/orm/api/rcsa/'+assessId+'/risks',{method:'POST',body:data});
    document.getElementById('rcsaRiskModal').remove();
    ormCloseDrawer();ormOpenRcsaDetail(assessId);
    if(typeof showToast==='function')showToast('Risk added');
  }catch(e){if(typeof showToast==='function')showToast('Save failed','error');}
};

/* ── RCSA Control Add/Edit Modal ── */
window.ormOpenRcsaControlModal=async function(riskId,existing,assessId){
  var isEdit=!!(existing&&existing.id);
  var users=await ormLoadUsers();
  var html='<div class="orm-modal-overlay" id="rcsaControlModal" data-orm-static-click="s37">'+
    '<div class="modal-box" data-s="s765d57b">'+
      '<button class="modal-close" data-orm-static-click="s57">&#10005;</button>'+
      '<div class="modal-title">'+(isEdit?'Edit':'Add')+' Control</div>'+
      '<div class="form-group"><label>Control Name *</label><input id="rc_name" placeholder="e.g. Dual approval for payments over $10k" value="'+esc(isEdit?(existing.name||''):'')+'"></div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Design Effectiveness</label><select id="rc_design">'+['adequate','not_assessed','inadequate'].map(function(v){return'<option value="'+v+'"'+(isEdit&&existing.design_effectiveness===v?' selected':'')+'>'+v.replace(/_/g,' ')+'</option>';}).join('')+'</select></div>'+
        '<div class="form-group"><label>Operating Effectiveness</label><select id="rc_operating">'+['effective','partially_effective','ineffective','not_tested'].map(function(v){return'<option value="'+v+'"'+(isEdit&&existing.operating_effectiveness===v?' selected':'')+'>'+v.replace(/_/g,' ')+'</option>';}).join('')+'</select></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Test Date</label><input type="date" id="rc_test_date" value="'+(isEdit&&existing.test_date?existing.test_date.slice(0,10):'')+'"></div>'+
        '<div class="form-group"><label>Tested By</label><select id="rc_tested_by"><option value="">— Unassigned —</option>'+users.map(function(u){return'<option value="'+u.id+'"'+(isEdit&&existing.tested_by==u.id?' selected':'')+'>'+esc(u.full_name)+'</option>';}).join('')+'</select></div>'+
      '</div>'+
      '<div class="form-group"><label>Evidence Notes</label><textarea id="rc_evidence" rows="2" data-s="sa57b154">'+esc(isEdit?(existing.evidence_notes||''):'')+'</textarea></div>'+
      '<div class="form-group"><label>Gap Description <span data-s="sb569cab">(if any)</span></label><textarea id="rc_gap" rows="2" data-s="sa57b154">'+esc(isEdit?(existing.gap_description||''):'')+'</textarea></div>'+
      '<div data-s="sd28ceac" data-sd="flex">'+
        '<button class="btn btn-secondary" data-orm-static-click="s57">Cancel</button>'+
        '<button class="btn btn-primary" data-orm-complex="rcsa-control-save" data-orm-id="'+ormAttrId(riskId)+'" data-orm-id2="'+(isEdit?ormAttrId(existing.id):'')+'" data-orm-id3="'+ormAttrId(assessId)+'" data-orm-edit="'+(isEdit?'1':'0')+'">Save Control</button>'+
      '</div>'+
    '</div></div>';
  document.body.insertAdjacentHTML('beforeend',html);
  setTimeout(function(){var t=document.getElementById('rc_name');if(t)t.focus();},80);
};
window.ormSaveRcsaControl=async function(riskId,id,assessId){
  var name=document.getElementById('rc_name').value.trim();
  if(!name){if(typeof showToast==='function')showToast('Control name required','error');return;}
  var data={name:name,design_effectiveness:document.getElementById('rc_design').value,operating_effectiveness:document.getElementById('rc_operating').value,test_date:document.getElementById('rc_test_date').value||null,tested_by:document.getElementById('rc_tested_by').value||null,evidence_notes:document.getElementById('rc_evidence').value.trim()||null,gap_description:document.getElementById('rc_gap').value.trim()||null};
  try{
    if(id)await apiFetch('/orm/api/rcsa/controls/'+id,{method:'PUT',body:data});
    else await apiFetch('/orm/api/rcsa/risks/'+riskId+'/controls',{method:'POST',body:data});
    document.getElementById('rcsaControlModal').remove();
    ormOpenRcsaDetail(assessId);
    if(typeof showToast==='function')showToast('Control saved');
  }catch(e){if(typeof showToast==='function')showToast('Save failed','error');}
};
window.ormDeleteRcsaControl=async function(controlId,assessId){
  if(!confirm('Delete this control? Any linked actions will remain but lose their control reference.'))return;
  try{
    await apiFetch('/orm/api/rcsa/controls/'+controlId,{method:'DELETE'});
    ormOpenRcsaDetail(assessId);
    if(typeof showToast==='function')showToast('Control deleted');
  }catch(e){if(typeof showToast==='function')showToast('Delete failed','error');}
};

/* ── RCSA Action Add/Edit Modal ── */
window.ormOpenRcsaActionModal=async function(controlId,existing,assessId){
  var isEdit=!!(existing&&existing.id);
  var users=await ormLoadUsers();
  var html='<div class="orm-modal-overlay" id="rcsaActionModal" data-orm-static-click="s37">'+
    '<div class="modal-box" data-s="s04391f0">'+
      '<button class="modal-close" data-orm-static-click="s58">&#10005;</button>'+
      '<div class="modal-title">'+(isEdit?'Edit':'Add')+' Remediation Action</div>'+
      '<div class="form-group"><label>Title *</label><input id="ra_title" placeholder="e.g. Implement quarterly access review" value="'+esc(isEdit?(existing.title||''):'')+'"></div>'+
      '<div class="form-group"><label>Description</label><textarea id="ra_desc" rows="2" data-s="sa57b154">'+esc(isEdit?(existing.description||''):'')+'</textarea></div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Owner</label><select id="ra_owner"><option value="">— Unassigned —</option>'+users.map(function(u){return'<option value="'+u.id+'"'+(isEdit&&existing.owner_id==u.id?' selected':'')+'>'+esc(u.full_name)+'</option>';}).join('')+'</select></div>'+
        '<div class="form-group"><label>Due Date</label><input type="date" id="ra_due" value="'+(isEdit&&existing.due_date?existing.due_date.slice(0,10):'')+'"></div>'+
      '</div>'+
      '<div class="form-group"><label>Status</label><select id="ra_status">'+['open','in_progress','completed','overdue'].map(function(s){return'<option value="'+s+'"'+(isEdit&&existing.status===s?' selected':'')+'>'+s.replace(/_/g,' ')+'</option>';}).join('')+'</select></div>'+
      '<div class="form-group"><label>Notes</label><textarea id="ra_notes" rows="2" data-s="sa57b154">'+esc(isEdit?(existing.notes||''):'')+'</textarea></div>'+
      '<div data-s="sd28ceac" data-sd="flex">'+
        '<button class="btn btn-secondary" data-orm-static-click="s58">Cancel</button>'+
        '<button class="btn btn-primary" data-orm-complex="rcsa-action-save" data-orm-id="'+ormAttrId(controlId)+'" data-orm-id2="'+(isEdit?ormAttrId(existing.id):'')+'" data-orm-id3="'+ormAttrId(assessId)+'" data-orm-edit="'+(isEdit?'1':'0')+'">Save Action</button>'+
      '</div>'+
    '</div></div>';
  document.body.insertAdjacentHTML('beforeend',html);
  setTimeout(function(){var t=document.getElementById('ra_title');if(t)t.focus();},80);
};
window.ormSaveRcsaAction=async function(controlId,id,assessId){
  var title=document.getElementById('ra_title').value.trim();
  if(!title){if(typeof showToast==='function')showToast('Title required','error');return;}
  var data={title:title,description:document.getElementById('ra_desc').value.trim()||null,owner_id:document.getElementById('ra_owner').value||null,due_date:document.getElementById('ra_due').value||null,status:document.getElementById('ra_status').value,notes:document.getElementById('ra_notes').value.trim()||null};
  try{
    if(id)await apiFetch('/orm/api/rcsa/actions/'+id,{method:'PUT',body:data});
    else await apiFetch('/orm/api/rcsa/controls/'+controlId+'/actions',{method:'POST',body:data});
    document.getElementById('rcsaActionModal').remove();
    ormOpenRcsaDetail(assessId);
    if(typeof showToast==='function')showToast('Action saved');
  }catch(e){if(typeof showToast==='function')showToast('Save failed','error');}
};
window.ormDeleteRcsaAction=async function(actionId,assessId){
  if(!confirm('Delete this remediation action?'))return;
  try{
    await apiFetch('/orm/api/rcsa/actions/'+actionId,{method:'DELETE'});
    ormOpenRcsaDetail(assessId);
    if(typeof showToast==='function')showToast('Action deleted');
  }catch(e){if(typeof showToast==='function')showToast('Delete failed','error');}
};

/* ─────────────────────────── AI CONTROLS CATALOGUE (PLAN-21) ─────────────────────────── */
var ormCanManageAiControls=ormPageConfig.dataset.canManageAiControls==='1';
var aicCache=null;
var _aicPillarFilter='';
async function ormEnsureAicCache(force){
  if(aicCache&&!force)return aicCache;
  aicCache=await apiFetch('/orm/api/ai-controls?include_inactive=true');
  return aicCache;
}
window.ormLoadAiControls=async function(){
  var body=document.getElementById('aicBody');
  if(body)body.innerHTML=spinner(7);
  try{
    await ormEnsureAicCache(true);
    ormRenderAicRows();
  }catch(e){if(body)body.innerHTML='<tr><td colspan="7" data-s="saab7d13">Failed to load</td></tr>';}
};
window.ormChipAicPillar=function(el){
  document.querySelectorAll('#aicPillarBar .orm-chip').forEach(function(c){c.classList.remove('active');});
  el.classList.add('active');
  _aicPillarFilter=el.getAttribute('data-val')||'';
  ormRenderAicRows();
};
window.ormRenderAicRows=function(){
  var body=document.getElementById('aicBody');
  if(!body||!aicCache)return;
  var showInactiveEl=document.getElementById('aicShowInactive');
  var includeInactive=showInactiveEl&&showInactiveEl.checked;
  var rows=aicCache.filter(function(c){
    if(_aicPillarFilter&&c.pillar!==_aicPillarFilter)return false;
    if(!includeInactive&&!c.is_active)return false;
    return true;
  });
  if(!rows.length){body.innerHTML=emptyRow(7,'No controls match this filter');return;}
  body.innerHTML=rows.map(function(c){
    var srcBadge=c.source==='built_in'?'<span class="badge badge-draft">Built-in</span>':'<span class="badge badge-progress">Custom</span>';
    var statBadge=c.is_active?'<span class="badge badge-complete">Active</span>':'<span class="badge badge-critical">Inactive</span>';
    var canDelete=c.source!=='built_in'&&!(c.link_count>0);
    return'<tr>'+
      '<td data-s="se81a2ba">'+esc(c.ref)+'</td>'+
      '<td data-s="sb86dc23"><div data-s="s160b067">'+esc(c.title)+'</div>'+(c.description&&c.description!==c.title?'<div data-s="s3f436e2">'+esc(c.description)+'</div>':'')+'</td>'+
      '<td><span class="orm-cat-chip" data-s="sd81fde2">'+esc(c.pillar)+'</span></td>'+
      '<td>'+srcBadge+'</td>'+
      '<td data-s="s91a8701">'+(c.link_count>0?'<span class="badge badge-draft">'+c.link_count+'</span>':'<span data-s="sbf8965d">—</span>')+'</td>'+
      '<td>'+statBadge+'</td>'+
      '<td><div data-s="sd767683" data-sd="flex">'+
        (ormCanManageAiControls?'<button class="btn btn-sm btn-secondary" data-orm-call="ormEditAiControl" data-orm-id="'+ormAttrId(c.id)+'" title="Edit" aria-label="Edit '+escChartAttr(c.ref)+'"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button>'+
        '<button class="btn btn-sm btn-secondary" data-orm-special="toggle-ai-control" data-orm-id="'+ormAttrId(c.id)+'" data-orm-toggle="'+(c.is_active?'0':'1')+'" title="'+(c.is_active?'Deactivate':'Activate')+'">'+(c.is_active?'&#8863;':'&#10003;')+'</button>'+
        (canDelete?'<button class="btn btn-sm btn-secondary" data-orm-call="ormDeleteAiControl" data-orm-id="'+ormAttrId(c.id)+'" data-s="s45e7ae4" title="Delete">&#10005;</button>':''):'')+
      '</div></td>'+
    '</tr>';
  }).join('');
};
window.ormEditAiControl=function(id){
  var control=(aicCache||[]).find(function(x){return x.id===id;});
  if(control)ormOpenAiControlModal(control);
};
window.ormOpenAiControlModal=function(existing){
  var isEdit=!!(existing&&existing.id);
  var pillars=['People','Process','Systems','Technology','Tools'];
  var html='<div class="orm-modal-overlay" id="aicModal" data-orm-static-click="s37">'+
    '<div class="modal-box" data-s="s765d57b">'+
      '<button class="modal-close" data-orm-static-click="s59">&#10005;</button>'+
      '<div class="modal-title">'+(isEdit?'Edit Control':'Add Control')+'</div>'+
      (isEdit&&existing.source==='built_in'?'<div data-s="s5313683">This is a built-in control. It can be reworded but not deleted &mdash; deactivate instead.</div>':'')+
      '<div class="form-row">'+
        '<div class="form-group"><label>Ref</label><input id="aic_ref" '+(isEdit?'readonly data-s="s6109bb5"':'')+' value="'+escChartAttr(isEdit?(existing.ref||''):'')+'" placeholder="Auto-generated if blank"></div>'+
        '<div class="form-group"><label>Pillar *</label><select id="aic_pillar">'+pillars.map(function(p){return'<option value="'+p+'"'+(isEdit&&existing.pillar===p?' selected':'')+'>'+p+'</option>';}).join('')+'</select></div>'+
      '</div>'+
      '<div class="form-group"><label>Title *</label><input id="aic_title" value="'+escChartAttr(isEdit?(existing.title||''):'')+'"></div>'+
      '<div class="form-group"><label>Description</label><textarea id="aic_desc" rows="3" data-s="sa57b154">'+esc(isEdit?(existing.description||''):'')+'</textarea></div>'+
      '<div data-s="sd28ceac" data-sd="flex">'+
        '<button class="btn btn-secondary" data-orm-static-click="s59">Cancel</button>'+
        '<button class="btn btn-primary" data-orm-save-call="ormSaveAiControl" data-orm-save-id="'+(isEdit?ormAttrId(existing.id):'')+'" data-orm-save-edit="'+(isEdit?'1':'0')+'">Save</button>'+
      '</div>'+
    '</div></div>';
  document.body.insertAdjacentHTML('beforeend',html);
  setTimeout(function(){var t=document.getElementById('aic_title');if(t)t.focus();},80);
};
window.ormSaveAiControl=async function(id){
  var title=document.getElementById('aic_title').value.trim();
  if(!title){if(typeof showToast==='function')showToast('Title required','error');return;}
  var data={title:title,description:document.getElementById('aic_desc').value.trim(),pillar:document.getElementById('aic_pillar').value};
  if(!id){
    var ref=document.getElementById('aic_ref').value.trim();
    if(ref)data.ref=ref;
  }
  try{
    if(id)await apiFetch('/orm/api/ai-controls/'+id,{method:'PUT',body:data});
    else await apiFetch('/orm/api/ai-controls',{method:'POST',body:data});
    document.getElementById('aicModal').remove();
    if(typeof showToast==='function')showToast('Control saved');
    ormLoadAiControls();
  }catch(e){if(typeof showToast==='function')showToast(e.message||'Save failed','error');}
};
window.ormToggleAiControlActive=async function(id,newVal){
  try{
    await apiFetch('/orm/api/ai-controls/'+id,{method:'PUT',body:{is_active:newVal}});
    ormLoadAiControls();
  }catch(e){if(typeof showToast==='function')showToast(e.message||'Update failed','error');}
};
window.ormDeleteAiControl=async function(id){
  if(!confirm('Delete this control? This cannot be undone.'))return;
  try{
    await apiFetch('/orm/api/ai-controls/'+id,{method:'DELETE'});
    if(typeof showToast==='function')showToast('Control deleted');
    ormLoadAiControls();
  }catch(e){if(typeof showToast==='function')showToast(e.message||'Delete failed','error');}
};

/* ─────────────────────────── AIMS / ORAAT RISK ENGINE (PLAN-21) ─────────────────────────── */
var aimsCache=[];
window._aimsCurrentAssessment=null;
window._aimsRiskDetailCache={};

/* Colored residual chip vs target/appetite/tolerance thresholds. Falls back to a plain value when no thresholds are set. */
function ormResidualChip(val,risk){
  if(val==null)return'<span data-s="s6d034cc">—</span>';
  var target=risk.rr_target,appetite=risk.rr_appetite,tolerance=risk.rr_tolerance;
  var color='var(--text)',label='Residual';
  if(target!=null&&val<=target){color='var(--good,#16a34a)';label='Within Target';}
  else if(appetite!=null&&val<=appetite){color='var(--good,#16a34a)';label='Within Appetite';}
  else if(tolerance!=null&&val<=tolerance){color='var(--amber,#d97706)';label='Within Tolerance';}
  else if(tolerance!=null){color='var(--red,#dc2626)';label='Breach';}
  return'<span data-sv="font-size:11px;color:'+color+';font-weight:700" title="'+label+'">R: '+val+'</span>';
}

window.ormLoadAims=async function(){
  var body=document.getElementById('aimsBody');
  if(body)body.innerHTML=spinner(7);
  try{
    var data=await apiFetch('/orm/api/aims');
    aimsCache=Array.isArray(data)?data:[];
    var total=aimsCache.length;
    var aimsMode=aimsCache.filter(function(a){return a.mode==='aims';}).length;
    var oraatMode=aimsCache.filter(function(a){return a.mode==='oraat';}).length;
    var totalRisks=aimsCache.reduce(function(s,a){return s+(a.risk_count||0);},0);
    populateStatCards('aimsStats',[
      {label:'Total Assessments',value:total},
      {label:'AIMS Mode',value:aimsMode},
      {label:'ORAAT Mode',value:oraatMode},
      {label:'Total Risks',value:totalRisks}
    ]);
    var navBadge=document.getElementById('ormNavAims');
    if(navBadge)navBadge.textContent=total||'';
    if(!aimsCache.length){
      if(body)body.innerHTML=emptyRow(7,'No AIMS assessments yet. Click "+ New Assessment" to start.');
      return;
    }
    body.innerHTML=aimsCache.map(function(a){
      var statusColors={draft:'badge-draft',active:'badge-progress',under_review:'badge-high',completed:'badge-complete'};
      var sc=statusColors[a.status]||'badge-draft';
      var modeBadge=a.mode==='oraat'?'<span class="badge badge-progress">ORAAT</span>':'<span class="badge badge-draft">AIMS</span>';
      return'<tr>'+
        '<td data-s="se81a2ba">'+esc(a.ref||'')+'</td>'+
        '<td data-s="s49b2015" data-orm-call="ormOpenAimsDetail" data-orm-id="'+ormAttrId(a.id)+'">'+esc(a.title)+'</td>'+
        '<td>'+modeBadge+'</td>'+
        '<td><span class="badge '+sc+'">'+esc((a.status||'draft').replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();}))+'</span></td>'+
        '<td data-s="s6cb285c">'+esc(a.owner_name||'—')+'</td>'+
        '<td data-s="s91a8701"><span class="badge badge-draft">'+(a.risk_count||0)+'</span></td>'+
        '<td><div data-s="sd767683" data-sd="flex">'+
          '<button class="btn btn-sm btn-secondary" data-orm-call="ormOpenAimsDetail" data-orm-id="'+ormAttrId(a.id)+'" title="Open"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-search></use></svg></button>'+
          '<button class="btn btn-sm btn-secondary" data-orm-cache-call="ormOpenAimsModal" data-orm-id="'+ormAttrId(a.id)+'" title="Edit"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button>'+
          '<button class="btn btn-sm btn-secondary" data-orm-call="ormDeleteAims" data-orm-id="'+ormAttrId(a.id)+'" data-s="s45e7ae4" title="Delete">&#10005;</button>'+
        '</div></td>'+
      '</tr>';
    }).join('');
  }catch(e){if(body)body.innerHTML='<tr><td colspan="7" data-s="saab7d13">Failed to load</td></tr>';}
};
window.ormOpenAimsModal=function(existing){
  var isEdit=!!(existing&&existing.id);
  var html='<div class="orm-modal-overlay" id="aimsModal" data-orm-static-click="s37">'+
    '<div class="modal-box" data-s="s04391f0">'+
      '<button class="modal-close" data-orm-static-click="s60">&#10005;</button>'+
      '<div class="modal-title">'+(isEdit?'Edit':'New')+' AI Risk Assessment</div>'+
      '<div class="form-group"><label>Title *</label><input id="am_title" value="'+esc(isEdit?(existing.title||''):'')+'"></div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Mode</label><select id="am_mode">'+
          '<option value="aims"'+(isEdit&&existing.mode==='aims'?' selected':'')+'>AIMS (multi-control)</option>'+
          '<option value="oraat"'+(isEdit&&existing.mode==='oraat'?' selected':'')+'>ORAAT (one-risk-at-a-time)</option>'+
        '</select></div>'+
        '<div class="form-group"><label>Status</label><select id="am_status">'+['draft','active','under_review','completed'].map(function(s){return'<option value="'+s+'"'+(isEdit&&existing.status===s?' selected':'')+'>'+s.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();})+'</option>';}).join('')+'</select></div>'+
      '</div>'+
      '<div class="form-group"><label>Evaluation Date</label><input type="date" id="am_date" value="'+(isEdit&&existing.eval_date?existing.eval_date.slice(0,10):'')+'"></div>'+
      '<div data-s="sd28ceac" data-sd="flex">'+
        '<button class="btn btn-secondary" data-orm-static-click="s60">Cancel</button>'+
        '<button class="btn btn-primary" data-orm-save-call="ormSaveAims" data-orm-save-id="'+(isEdit?ormAttrId(existing.id):'')+'" data-orm-save-edit="'+(isEdit?'1':'0')+'">Save</button>'+
      '</div>'+
    '</div></div>';
  document.body.insertAdjacentHTML('beforeend',html);
  setTimeout(function(){var t=document.getElementById('am_title');if(t)t.focus();},80);
};
window.ormSaveAims=async function(id){
  var title=document.getElementById('am_title').value.trim();
  if(!title){if(typeof showToast==='function')showToast('Title required','error');return;}
  var data={title:title,mode:document.getElementById('am_mode').value,status:document.getElementById('am_status').value,eval_date:document.getElementById('am_date').value||null};
  try{
    if(id)await apiFetch('/orm/api/aims/'+id,{method:'PUT',body:data});
    else await apiFetch('/orm/api/aims',{method:'POST',body:data});
    document.getElementById('aimsModal').remove();
    if(typeof showToast==='function')showToast('Assessment saved');
    ormLoadAims();
  }catch(e){if(typeof showToast==='function')showToast(e.message||'Save failed','error');}
};
window.ormDeleteAims=async function(id){
  if(!confirm('Delete this assessment and all its risks and controls?'))return;
  try{
    await apiFetch('/orm/api/aims/'+id,{method:'DELETE'});
    ormLoadAims();
  }catch(e){if(typeof showToast==='function')showToast(e.message||'Delete failed','error');}
};

/* ── AIMS Assessment Detail Drawer (Risk Register) ── */
function ormAimsRiskRowHtml(r,assessId){
  var computed=r.computed||{};
  var irr=computed.irr!=null?computed.irr:(r.likelihood*r.impact);
  var chip=ormResidualChip(computed.residual_rating,r);
  return'<div class="rcsa-risk-row" data-orm-call="ormOpenAimsRiskDetail" data-orm-id="'+ormAttrId(r.id)+'" data-orm-id2="'+ormAttrId(assessId)+'">'+
    '<div data-s="s3ae5ff5" data-sd="flex">'+
      '<span data-s="s5b1ab39">'+esc((r.ref?r.ref+' — ':'')+(r.risk_description||'').slice(0,90))+'</span>'+
      '<div data-s="sc58a824" data-sd="flex">'+
        '<span data-s="s1fd8c81">IRR: <strong>'+irr+'</strong></span>'+
        chip+
      '</div>'+
    '</div>'+
    '<div data-s="s4bef715" data-sd="flex">'+
      (r.impacted_pillar?'<span class="orm-cat-chip" data-s="sd81fde2">'+esc(r.impacted_pillar)+'</span>':'')+
      '<span>'+(r.control_count||0)+' control(s) linked</span>'+
      '<span data-s="s6d00061">'+esc((r.status||'open').replace(/_/g,' '))+'</span>'+
    '</div>'+
  '</div>';
}
window.ormOpenAimsDetail=async function(assessId){
  window._aimsCurrentAssessment=assessId;
  var drawer=document.getElementById('ormDrawerRoot');
  drawer.innerHTML='<div class="orm-drawer-overlay"><div class="orm-drawer-panel" data-s="sa3fa223"><div class="spinner"></div></div></div>';
  try{
    var a=await apiFetch('/orm/api/aims/'+assessId);
    var risks=await apiFetch('/orm/api/aims/'+assessId+'/risks');
    drawer.innerHTML='<div class="orm-drawer-overlay" data-orm-static-click="s41">'+
    '<div class="orm-drawer-panel" data-s="s7d83361">'+
      '<div class="orm-drawer-head">'+
        '<div data-s="sf0bc6e2" data-sd="flex">'+
          '<div>'+
            '<div data-s="s266e2f3">'+esc(a.title)+'</div>'+
            '<div data-s="sfc85ba5">'+esc(a.ref||'')+' &bull; '+(a.mode==='oraat'?'ORAAT':'AIMS')+' &bull; '+esc((a.status||'draft').replace(/_/g,' '))+'</div>'+
          '</div>'+
          '<button class="btn btn-sm btn-secondary" data-orm-static-click="s42">&#10005;</button>'+
        '</div>'+
      '</div>'+
      '<div class="orm-drawer-body">'+
        '<div data-s="s91ebbdc" data-sd="flex">'+
          '<div class="orm-drawer-section-title" data-s="s9167253">Risk Register ('+risks.length+')</div>'+
          '<div data-s="sf0abc1d" data-sd="flex">'+
            '<a href="/orm/api/aims/'+assessId+'/aggregation/csv" class="btn btn-sm btn-secondary" download>&#8595; CSV</a>'+
            '<button class="btn btn-sm btn-primary" data-orm-call="ormAddAimsRisk" data-orm-id="'+ormAttrId(assessId)+'">+ Add Risk</button>'+
          '</div>'+
        '</div>'+
        (risks.length?risks.map(function(r){return ormAimsRiskRowHtml(r,assessId);}).join(''):'<div data-s="sa316e87">No risks yet. Click "+ Add Risk" to start.</div>')+
      '</div>'+
      '<div class="orm-drawer-footer">'+
        '<button class="btn btn-secondary" data-orm-complex="aims-edit-close" data-orm-id="'+ormAttrId(assessId)+'"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg> Edit Assessment</button>'+
      '</div>'+
    '</div></div>';
    if(typeof DialogFocus!=='undefined')DialogFocus.trap(drawer.querySelector('.orm-drawer-panel'));
  }catch(ex){drawer.innerHTML='';}
};

/* ── AIMS Risk Add/Edit Modal ── */
window.ormAddAimsRisk=function(assessId){ormOpenAimsRiskModal(assessId,null);};
window.ormEditAimsRisk=function(assessId,existing){ormOpenAimsRiskModal(assessId,existing);};
window.ormOpenAimsRiskModal=function(assessId,existing){
  var isEdit=!!(existing&&existing.id);
  var pillars=['People','Process','Systems','Technology','Tools'];
  var html='<div class="orm-modal-overlay" id="aimsRiskModal" data-orm-static-click="s37">'+
    '<div class="modal-box" data-s="se2b01b0">'+
      '<button class="modal-close" data-orm-static-click="s61">&#10005;</button>'+
      '<div class="modal-title">'+(isEdit?'Edit':'Add')+' AI Risk</div>'+
      '<div class="form-group"><label>Risk Description *</label><textarea id="ar_desc" rows="2" data-s="sa57b154">'+esc(isEdit?(existing.risk_description||''):'')+'</textarea></div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Strategic Objective</label><input id="ar_strat" value="'+esc(isEdit?(existing.strategic_objective||''):'')+'"></div>'+
        '<div class="form-group"><label>AI Objective</label><input id="ar_aiobj" value="'+esc(isEdit?(existing.ai_objective||''):'')+'"></div>'+
      '</div>'+
      '<div class="form-group"><label>Contributing Factors</label><input id="ar_cf" value="'+esc(isEdit?(existing.contributing_factors||''):'')+'"></div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Impacted Pillar</label><select id="ar_pillar"><option value="">— None —</option>'+pillars.map(function(p){return'<option value="'+p+'"'+(isEdit&&existing.impacted_pillar===p?' selected':'')+'>'+p+'</option>';}).join('')+'</select></div>'+
        '<div class="form-group"><label>Risk Owner</label><input id="ar_owner" value="'+esc(isEdit?(existing.risk_owner||''):'')+'"></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Likelihood (1-5)</label><input type="number" id="ar_l" min="1" max="5" value="'+(isEdit?(existing.likelihood||5):5)+'"></div>'+
        '<div class="form-group"><label>Impact (1-5)</label><input type="number" id="ar_i" min="1" max="5" value="'+(isEdit?(existing.impact||5):5)+'"></div>'+
      '</div>'+
      '<div class="form-group"><label>EMV Inherent ($)</label><input type="number" id="ar_emv" value="'+(isEdit&&existing.emv_inherent!=null?existing.emv_inherent:'')+'"></div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>RR Target</label><input type="number" step="0.01" id="ar_target" value="'+(isEdit&&existing.rr_target!=null?existing.rr_target:'')+'"></div>'+
        '<div class="form-group"><label>RR Appetite</label><input type="number" step="0.01" id="ar_appetite" value="'+(isEdit&&existing.rr_appetite!=null?existing.rr_appetite:'')+'"></div>'+
        '<div class="form-group"><label>RR Tolerance</label><input type="number" step="0.01" id="ar_tolerance" value="'+(isEdit&&existing.rr_tolerance!=null?existing.rr_tolerance:'')+'"></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>In Scope</label><select id="ar_scope" data-orm-static-change="s62"><option value="1"'+((!isEdit||existing.in_scope)?' selected':'')+'>Yes</option><option value="0"'+(isEdit&&!existing.in_scope?' selected':'')+'>No</option></select></div>'+
        '<div class="form-group"><label>Implemented</label><select id="ar_impl"><option value="0"'+(!isEdit||!existing.implemented?' selected':'')+'>No</option><option value="1"'+(isEdit&&existing.implemented?' selected':'')+'>Yes</option></select></div>'+
      '</div>'+
      '<div class="form-group" id="ar_just_row" data-sv="display:'+(isEdit&&!existing.in_scope?'block':'none')+'"><label>Scope Justification <span data-s="sb569cab">(why is this out of scope?)</span></label><input id="ar_just" value="'+esc(isEdit?(existing.scope_justification||''):'')+'"></div>'+
      '<div class="form-group"><label>Status</label><select id="ar_status">'+['open','mitigating','closed'].map(function(s){return'<option value="'+s+'"'+(isEdit&&existing.status===s?' selected':'')+'>'+s.replace(/\b\w/g,function(c){return c.toUpperCase();})+'</option>';}).join('')+'</select></div>'+
      '<div data-s="sd28ceac" data-sd="flex">'+
        '<button class="btn btn-secondary" data-orm-static-click="s61">Cancel</button>'+
        '<button class="btn btn-primary" data-orm-complex="aims-risk-save" data-orm-id="'+ormAttrId(assessId)+'" data-orm-id2="'+(isEdit?ormAttrId(existing.id):'')+'" data-orm-edit="'+(isEdit?'1':'0')+'">Save</button>'+
      '</div>'+
    '</div></div>';
  document.body.insertAdjacentHTML('beforeend',html);
  setTimeout(function(){var t=document.getElementById('ar_desc');if(t)t.focus();},80);
};
window.ormSaveAimsRisk=async function(assessId,id){
  var desc=document.getElementById('ar_desc').value.trim();
  if(!desc){if(typeof showToast==='function')showToast('Risk description required','error');return;}
  var data={
    risk_description:desc,
    strategic_objective:document.getElementById('ar_strat').value.trim(),
    ai_objective:document.getElementById('ar_aiobj').value.trim(),
    contributing_factors:document.getElementById('ar_cf').value.trim(),
    impacted_pillar:document.getElementById('ar_pillar').value||null,
    risk_owner:document.getElementById('ar_owner').value.trim(),
    likelihood:parseInt(document.getElementById('ar_l').value)||5,
    impact:parseInt(document.getElementById('ar_i').value)||5,
    emv_inherent:document.getElementById('ar_emv').value!==''?parseFloat(document.getElementById('ar_emv').value):null,
    rr_target:document.getElementById('ar_target').value!==''?parseFloat(document.getElementById('ar_target').value):null,
    rr_appetite:document.getElementById('ar_appetite').value!==''?parseFloat(document.getElementById('ar_appetite').value):null,
    rr_tolerance:document.getElementById('ar_tolerance').value!==''?parseFloat(document.getElementById('ar_tolerance').value):null,
    in_scope:document.getElementById('ar_scope').value==='1',
    implemented:document.getElementById('ar_impl').value==='1',
    scope_justification:document.getElementById('ar_just').value.trim()||null,
    status:document.getElementById('ar_status').value
  };
  try{
    if(id)await apiFetch('/orm/api/aims/risks/'+id,{method:'PUT',body:data});
    else await apiFetch('/orm/api/aims/'+assessId+'/risks',{method:'POST',body:data});
    document.getElementById('aimsRiskModal').remove();
    if(typeof showToast==='function')showToast('Risk saved');
    ormOpenAimsDetail(assessId);
  }catch(e){if(typeof showToast==='function')showToast(e.message||'Save failed','error');}
};
window.ormDeleteAimsRisk=async function(riskId,assessId){
  if(!confirm('Delete this risk and all its linked controls?'))return;
  try{
    await apiFetch('/orm/api/aims/risks/'+riskId,{method:'DELETE'});
    if(typeof showToast==='function')showToast('Risk deleted');
    ormOpenAimsDetail(assessId);
  }catch(e){if(typeof showToast==='function')showToast(e.message||'Delete failed','error');}
};

/* ── AIMS Risk Detail Drawer (computed panel + linked controls) ── */
function ormAimsComputedPanelHtml(r,computed){
  var chip=ormResidualChip(computed.residual_rating,r);
  var meanPct=computed.mean_factor!=null?Math.round(computed.mean_factor*100):null;
  return'<div data-s="s7bd035a" data-sd="grid">'+
    '<div data-s="s0ff1122"><div data-s="s0de5e1b">IRR (L&times;I)</div><div data-s="s028ee8c">'+(computed.irr!=null?computed.irr:'—')+'</div></div>'+
    '<div data-s="s0ff1122"><div data-s="s0de5e1b">Mean Factor</div><div data-s="s028ee8c">'+(meanPct!=null?meanPct+'%':'—')+'</div></div>'+
    '<div data-s="s0ff1122"><div data-s="s0de5e1b">Residual Rating</div><div data-s="s028ee8c">'+(computed.residual_rating!=null?computed.residual_rating:'—')+'</div>'+chip+'</div>'+
    '<div data-s="s0ff1122"><div data-s="s0de5e1b">Residual EMV</div><div data-s="s80b90e3">'+(computed.residual_emv!=null?fmtCurrency(computed.residual_emv):'—')+'</div></div>'+
  '</div>';
}
function ormAimsPillarBarsHtml(perPillar){
  if(!perPillar)return'';
  var pillars=['People','Process','Systems','Technology','Tools'];
  var any=pillars.some(function(p){return perPillar[p]&&perPillar[p].count>0;});
  if(!any)return'';
  return'<div class="orm-drawer-section">'+
    '<div class="orm-drawer-section-title">Mitigation by Pillar</div>'+
    pillars.map(function(p){
      var d=perPillar[p]||{count:0,mean_factor:null};
      var pct=d.mean_factor!=null?Math.round((1-d.mean_factor)*100):0;
      var barColor=pct>=70?'var(--good,#16a34a)':pct>=40?'var(--amber,#d97706)':'var(--red,#dc2626)';
      return'<div data-s="s5948d98" data-sd="flex">'+
        '<span data-s="sd0193f5">'+p+'</span>'+
        '<div data-s="s7a91738">'+
          (d.count>0?'<div data-sv="height:100%;width:'+pct+'%;background:'+barColor+';border-radius:100px"></div>':'')+
        '</div>'+
        '<span data-s="s94e48c1">'+(d.count>0?d.count+' ctrl, '+pct+'%':'none')+'</span>'+
      '</div>';
    }).join('')+
  '</div>';
}
function ormAimsControlRowHtml(c,riskId){
  var iceColor=c.ice_score>=70?'var(--good,#16a34a)':c.ice_score>=40?'var(--amber,#d97706)':'var(--red,#dc2626)';
  var title=c.catalogue_ref?(c.catalogue_ref+' — '+c.catalogue_title):(c.control_detail||'Custom control');
  var statBadge={open:'badge-high',in_progress:'badge-progress',completed:'badge-complete'}[c.status]||'badge-draft';
  return'<div data-s="seeda921" data-sd="flex">'+
    '<div data-s="s59eddc6">'+
      '<div data-s="sab15306">'+esc(title)+'</div>'+
      '<div data-s="s3823a5b">'+esc((c.treatment||'mitigate').replace(/\b\w/g,function(x){return x.toUpperCase();}))+(c.control_owner?' &bull; '+esc(c.control_owner):'')+(c.catalogue_pillar?' &bull; '+esc(c.catalogue_pillar):'')+' &bull; <span class="badge '+statBadge+'" data-s="sfb2957a">'+esc((c.status||'open').replace(/_/g,' '))+'</span></div>'+
    '</div>'+
    '<div data-s="s6f085fb" data-sd="flex">'+
      '<span data-sv="font-size:11px;color:'+iceColor+';font-weight:700" title="ICE score (higher = stronger)">ICE '+(c.ice_score||0)+'%</span>'+
      '<button class="btn btn-sm btn-secondary" data-orm-complex="aims-control-edit" data-orm-id="'+ormAttrId(riskId)+'" data-orm-id2="'+ormAttrId(c.id)+'" title="Edit"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg></button>'+
      '<button class="btn btn-sm btn-secondary" data-orm-call="ormDeleteAimsRiskControl" data-orm-id="'+ormAttrId(c.id)+'" data-orm-id2="'+ormAttrId(riskId)+'" data-s="s45e7ae4" title="Remove">&#10005;</button>'+
    '</div>'+
  '</div>';
}
window.ormOpenAimsRiskDetail=async function(riskId,assessId){
  if(assessId)window._aimsCurrentAssessment=assessId;
  var drawer=document.getElementById('ormDrawerRoot');
  drawer.innerHTML='<div class="orm-drawer-overlay"><div class="orm-drawer-panel" data-s="sa3fa223"><div class="spinner"></div></div></div>';
  try{
    var r=await apiFetch('/orm/api/aims/risks/'+riskId);
    window._aimsRiskDetailCache[riskId]=r;
    await ormEnsureAicCache();
    var computed=r.computed||{};
    var controls=r.controls||[];
    var backAssessId=window._aimsCurrentAssessment;
    drawer.innerHTML='<div class="orm-drawer-overlay" data-orm-static-click="s41">'+
    '<div class="orm-drawer-panel" data-s="s0f5efc8">'+
      '<div class="orm-drawer-head">'+
        '<div data-s="sf0bc6e2" data-sd="flex">'+
          '<div>'+
            '<button class="btn btn-sm btn-secondary" data-orm-call="ormOpenAimsDetail" data-orm-id="'+ormAttrId(backAssessId)+'" data-s="sfdf33f2">&#8592; Back to Risk Register</button>'+
            '<div data-s="s13ce2a4">'+esc(r.ref||'')+' — '+esc((r.risk_description||'').slice(0,80))+'</div>'+
          '</div>'+
          '<button class="btn btn-sm btn-secondary" data-orm-static-click="s42">&#10005;</button>'+
        '</div>'+
      '</div>'+
      '<div class="orm-drawer-body">'+
        ormAimsComputedPanelHtml(r,computed)+
        ormAimsPillarBarsHtml(computed.per_pillar)+
        '<div class="orm-drawer-section">'+
          '<div data-s="s91ebbdc" data-sd="flex">'+
            '<div class="orm-drawer-section-title" data-s="sef0b7a1">Linked Controls ('+controls.length+')</div>'+
            '<button class="btn btn-sm btn-primary" data-orm-complex="aims-control-add" data-orm-id="'+ormAttrId(riskId)+'">+ Link Control</button>'+
          '</div>'+
          (controls.length?controls.map(function(c){return ormAimsControlRowHtml(c,riskId);}).join(''):'<div data-s="sa316e87">No controls linked yet.</div>')+
        '</div>'+
      '</div>'+
      '<div class="orm-drawer-footer">'+
        '<button class="btn btn-secondary" data-orm-complex="aims-risk-edit-close" data-orm-id="'+ormAttrId(backAssessId)+'" data-orm-id2="'+ormAttrId(riskId)+'"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-pencil></use></svg> Edit Risk</button>'+
        '<button class="btn btn-secondary" data-orm-complex="aims-risk-delete-close" data-orm-id="'+ormAttrId(riskId)+'" data-orm-id2="'+ormAttrId(backAssessId)+'" data-s="s45e7ae4">Delete Risk</button>'+
      '</div>'+
    '</div></div>';
    if(typeof DialogFocus!=='undefined')DialogFocus.trap(drawer.querySelector('.orm-drawer-panel'));
  }catch(ex){drawer.innerHTML='';}
};

/* ── AIMS Risk <-> Control Link Modal ── */
window.ormOpenAimsRiskControlModal=function(riskId,existing){
  var isEdit=!!(existing&&existing.id);
  var catalogue=(aicCache||[]).filter(function(c){return c.is_active;});
  var byPillar={};
  catalogue.forEach(function(c){(byPillar[c.pillar]=byPillar[c.pillar]||[]).push(c);});
  var options='<option value="">— Custom (no catalogue link) —</option>'+
    Object.keys(byPillar).sort().map(function(p){
      return'<optgroup label="'+p+'">'+byPillar[p].map(function(c){
        return'<option value="'+c.id+'"'+(isEdit&&existing.catalogue_control_id===c.id?' selected':'')+'>'+esc(c.ref+' — '+c.title)+'</option>';
      }).join('')+'</optgroup>';
    }).join('');
  var treatments=['accept','mitigate','share','avoid','exploit'];
  var html='<div class="orm-modal-overlay" id="aimsRcModal" data-orm-static-click="s37">'+
    '<div class="modal-box" data-s="s765d57b">'+
      '<button class="modal-close" data-orm-static-click="s63">&#10005;</button>'+
      '<div class="modal-title">'+(isEdit?'Edit':'Link')+' Control</div>'+
      '<div class="form-group"><label>Catalogue Control</label><select id="arc_cat">'+options+'</select></div>'+
      '<div class="form-group"><label>Control Detail (if custom / additional notes)</label><textarea id="arc_detail" rows="2" data-s="sa57b154">'+esc(isEdit?(existing.control_detail||''):'')+'</textarea></div>'+
      '<div class="form-group"><label>Action Steps</label><textarea id="arc_steps" rows="2" data-s="sa57b154">'+esc(isEdit?(existing.action_steps||''):'')+'</textarea></div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Responsible</label><input id="arc_responsible" value="'+esc(isEdit?(existing.responsible||''):'')+'"></div>'+
        '<div class="form-group"><label>Interdependency</label><input id="arc_interdep" placeholder="e.g. depends on Control X" value="'+esc(isEdit?(existing.interdependency||''):'')+'"></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>ICE Score % (0-90, higher = stronger)</label><select id="arc_ice">'+[0,10,20,30,40,50,60,70,80,90].map(function(v){return'<option value="'+v+'"'+(isEdit&&existing.ice_score===v?' selected':'')+'>'+v+'%</option>';}).join('')+'</select></div>'+
        '<div class="form-group"><label>or Legacy ORAAT (1-10, lower = stronger)</label><input type="number" id="arc_ice10" min="1" max="10" placeholder="optional"></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Treatment</label><select id="arc_treatment">'+treatments.map(function(t){return'<option value="'+t+'"'+(isEdit&&existing.treatment===t?' selected':'')+'>'+t.charAt(0).toUpperCase()+t.slice(1)+'</option>';}).join('')+'</select></div>'+
        '<div class="form-group"><label>Control Owner</label><input id="arc_owner" value="'+esc(isEdit?(existing.control_owner||''):'')+'"></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Treatment Cost ($)</label><input type="number" id="arc_cost" value="'+(isEdit&&existing.treatment_cost!=null?existing.treatment_cost:0)+'"></div>'+
        '<div class="form-group"><label>Due Date</label><input type="date" id="arc_due" value="'+(isEdit&&existing.due_date?existing.due_date.slice(0,10):'')+'"></div>'+
      '</div>'+
      '<div class="form-row">'+
        '<div class="form-group"><label>Evidence</label><input id="arc_evidence" value="'+esc(isEdit?(existing.evidence||''):'')+'"></div>'+
        '<div class="form-group"><label>Status</label><select id="arc_status">'+['open','in_progress','completed'].map(function(s){return'<option value="'+s+'"'+(isEdit&&existing.status===s?' selected':'')+'>'+s.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();})+'</option>';}).join('')+'</select></div>'+
      '</div>'+
      '<div data-s="sd28ceac" data-sd="flex">'+
        '<button class="btn btn-secondary" data-orm-static-click="s63">Cancel</button>'+
        '<button class="btn btn-primary" data-orm-complex="aims-control-save" data-orm-id="'+ormAttrId(riskId)+'" data-orm-id2="'+(isEdit?ormAttrId(existing.id):'')+'" data-orm-edit="'+(isEdit?'1':'0')+'">Save</button>'+
      '</div>'+
    '</div></div>';
  document.body.insertAdjacentHTML('beforeend',html);
};
window.ormSaveAimsRiskControl=async function(riskId,id){
  var ice10=document.getElementById('arc_ice10').value;
  var catId=document.getElementById('arc_cat').value;
  var data={
    catalogue_control_id:catId?parseInt(catId):null,
    control_detail:document.getElementById('arc_detail').value.trim(),
    action_steps:document.getElementById('arc_steps').value.trim()||null,
    responsible:document.getElementById('arc_responsible').value.trim()||null,
    interdependency:document.getElementById('arc_interdep').value.trim()||null,
    treatment:document.getElementById('arc_treatment').value,
    control_owner:document.getElementById('arc_owner').value.trim(),
    treatment_cost:parseFloat(document.getElementById('arc_cost').value)||0,
    due_date:document.getElementById('arc_due').value||null,
    evidence:document.getElementById('arc_evidence').value.trim(),
    status:document.getElementById('arc_status').value
  };
  if(ice10){data.ice_score_10=parseFloat(ice10);}
  else{data.ice_score=parseInt(document.getElementById('arc_ice').value)||0;}
  try{
    if(id)await apiFetch('/orm/api/aims/controls/'+id,{method:'PUT',body:data});
    else await apiFetch('/orm/api/aims/risks/'+riskId+'/controls',{method:'POST',body:data});
    document.getElementById('aimsRcModal').remove();
    if(typeof showToast==='function')showToast('Control linked');
    ormOpenAimsRiskDetail(riskId);
  }catch(e){if(typeof showToast==='function')showToast(e.message||'Save failed','error');}
};
window.ormDeleteAimsRiskControl=async function(linkId,riskId){
  if(!confirm('Remove this control link?'))return;
  try{
    await apiFetch('/orm/api/aims/controls/'+linkId,{method:'DELETE'});
    ormOpenAimsRiskDetail(riskId);
  }catch(e){if(typeof showToast==='function')showToast(e.message||'Delete failed','error');}
};

/* ─────────────────────────── KRI FILTER ─────────────────────────── */
window._kriFilter='all';
window.ormGetFilteredKris=function(kris){
  var f=window._kriFilter||'all';
  return kris.filter(function(k){
    var v=parseFloat(k.current_value)||0;
    var crit=parseFloat(k.threshold_crit)||null;
    var warn=parseFloat(k.threshold_warn)||null;
    if(f==='all')return true;
    if(f==='mine')return k.owner_id==ORM_CURRENT_USER_ID;
    if(f==='critical')return crit&&v>=crit;
    if(f==='warning')return warn&&v>=warn&&(!crit||v<crit);
    if(f==='ok')return!(crit&&v>=crit)&&!(warn&&v>=warn);
    return true;
  });
};
window.ormKriFilter=function(f){
  window._kriFilter=f;
  ormLoadKris();
};

/* ─────────────────────────── EVENT DUPLICATE ─────────────────────────── */
window.ormDuplicateEvt=function(id){
  var src=evtCache.find(function(x){return x.id===id;});
  if(!src)return;
  var clone=Object.assign({},src);
  clone.id=null;clone.status='open';clone.detected_at=null;clone.resolved_at=null;clone.created_at=null;clone.erm_risk_id=null;
  clone.title='Copy of '+clone.title;
  ormOpenEventModal(clone);
};

/* ─────────────────────────── KRI INLINE EDIT ─────────────────────────── */
window.ormInlineKriEdit=function(id,el){
  var cur=parseFloat(el.textContent)||0;
  el.innerHTML='<input type="number" value="'+cur+'" data-s="sfbd79f6" data-orm-inline-id="'+ormAttrId(id)+'" data-orm-static-keydown="s64">';
  var inp=el.querySelector('input');
  if(inp){inp.focus();inp.select();}
};
window.ormInlineKriSave=async function(id,inp){
  var n=parseFloat(inp.value);
  if(isNaN(n))return ormLoadKris();
  try{
    await apiFetch('/orm/api/kris/'+id,{method:'PUT',body:{current_value:n}});
    ormLoadKris();
    if(typeof showToast==='function')showToast('KRI updated');
  }catch(e){if(typeof showToast==='function')showToast('Update failed','error');ormLoadKris();}
};

/* ─────────────────────────── KRI UPDATE MODAL ─────────────────────────── */
window.ormOpenKriUpdateModal=function(kri){
  if(!kri)return;
  var cur=parseFloat(kri.current_value)||0;
  var hist=kriHistoryCache[kri.id]||[];
  var html='<div class="orm-modal-overlay" id="kriUpdateModal" data-orm-static-click="s37">'+
    '<div class="modal-box" data-s="s0fd8744">'+
      '<button class="modal-close" data-orm-static-click="s65">&#10005;</button>'+
      '<div class="modal-title">Update: '+esc(kri.name)+'</div>'+
      '<div data-s="sfb93d3a">'+
        '<div data-s="s3b60326" id="kumDisplay">'+cur+'</div>'+
        '<div data-s="s17d902b">'+esc(kri.unit||'')+'</div>'+
        (hist.length>1?'<div data-s="s8a77e5a">'+ormKriSparkline(hist)+'</div>':'')+
      '</div>'+
      '<div data-s="s2813e62" data-sd="flex">'+
        ['+1','+5','+10','Reset'].map(function(c){
          return'<button class="btn btn-sm btn-secondary" data-orm-adjust="'+esc(c)+'">'+c+'</button>';
        }).join('')+
      '</div>'+
      '<div class="form-group"><label>New Value</label>'+
        '<input type="number" id="kum_val" value="'+cur+'" data-orm-static-input="s66" data-s="s8624e1b">'+
      '</div>'+
      '<div class="form-group"><label>Notes <span data-s="sb569cab">(optional)</span></label>'+
        '<textarea id="kum_notes" rows="2" data-s="sa57b154"></textarea>'+
      '</div>'+
      '<div data-s="sd28ceac" data-sd="flex">'+
        '<button class="btn btn-secondary" data-orm-static-click="s65">Cancel</button>'+
        '<button class="btn btn-primary" data-orm-call="ormSaveKriUpdate" data-orm-id="'+ormAttrId(kri.id)+'">Save</button>'+
      '</div>'+
    '</div></div>';
  document.body.insertAdjacentHTML('beforeend',html);
  setTimeout(function(){var v=document.getElementById('kum_val');if(v){v.focus();v.select();}},80);
};
window.ormSaveKriUpdate=async function(id){
  var n=parseFloat(document.getElementById('kum_val').value);
  if(isNaN(n)){if(typeof showToast==='function')showToast('Invalid value','error');return;}
  try{
    await apiFetch('/orm/api/kris/'+id,{method:'PUT',body:{current_value:n}});
    document.getElementById('kriUpdateModal').remove();
    ormLoadKris();
    if(typeof showToast==='function')showToast('KRI updated');
  }catch(e){if(typeof showToast==='function')showToast('Update failed','error');}
};

/* ─────────────────────────── INIT ─────────────────────────── */
ormRouter.resolve();
setInterval(function(){if(ormRouter.current==='dashboard')ormLoadDashboard();},300000);

})();
