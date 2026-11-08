(function(){
  'use strict';
  const canAuthorWorkflow = document.getElementById('wfConfig').dataset.canAuthor === 'true';

  /* ════════════════════════════════════════════════════════════════════════
     HELPERS
     ════════════════════════════════════════════════════════════════════════ */
  function esc(s){if(!s)return '';var d=document.createElement('div');d.textContent=String(s);return d.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
  function wfSafeId(value){
    var id=Number(value);
    return Number.isSafeInteger(id)&&id>0?id:'';
  }
  document.addEventListener('click',function(event){
    var button=event.target.closest('.js-workflow-decision');
    if(button){
      var actionId=wfSafeId(button.dataset.actionId), instanceId=wfSafeId(button.dataset.instanceId);
      if(actionId&&instanceId) wfOpenDecision(actionId,instanceId,button.dataset.workflowName,button.dataset.stepName);
      return;
    }
    button=event.target.closest('.js-workflow-filter');
    if(button){wfFilterTpl(button.dataset.category,button);return;}
    button=event.target.closest('.js-workflow-install');
    if(button){wfInstallTpl(button.dataset.templateId);return;}
    button=event.target.closest('.js-workflow-start');
    if(button){
      var definitionId=wfSafeId(button.dataset.definitionId);
      if(definitionId) wfStartInstanceModal(definitionId,button.dataset.definitionName);
      return;
    }
    button=event.target.closest('[data-wf-tab]');
    if(button){wfShowTab(button.dataset.wfTab,button);return;}
    button=event.target.closest('[data-wf-filter]');
    if(button){wfFilterInst(button.dataset.wfFilter,button);return;}
    button=event.target.closest('[data-sla-tab]');
    if(button){slaSubTab(button.dataset.slaTab,button);return;}
    button=event.target.closest('[data-sla-filter]');
    if(button){slaFilterInst(button.dataset.slaFilter,button);return;}
    if(event.target.matches('#wfModalRoot [data-wf-backdrop]')){wfCloseModal();return;}
    button=event.target.closest('[data-wf-action]');
    if(!button) return;
    var action=button.dataset.wfAction;
    if(action==='close-modal'){wfCloseModal();return;}
    if(action==='close-drawer'){wfCloseDrawer();return;}
    if(action==='add-step'){wfAddStep();return;}
    if(action==='remove-step'){button.parentElement.remove();wfReindexSteps();return;}
    if(action==='new-def'){wfOpenNewDef();return;}
    if(action==='new-sla'){wfOpenNewSla();return;}
    if(action==='start-sla'){slaOpenStart();return;}
    if(action==='breach-check'){slaRunBreachCheck();return;}
    if(action==='new-comm'){wfOpenNewComm();return;}
    if(action==='submit-decision'){
      if(['approve','return','reject'].includes(button.dataset.decision)) wfSubmitDecision(button.dataset.decision);
      return;
    }
    var id=wfSafeId(button.dataset.id);
    if(action==='open-decision'){
      var aid=wfSafeId(button.dataset.actionId), iid=wfSafeId(button.dataset.instanceId);
      if(aid&&iid) wfOpenDecision(aid,iid,button.dataset.workflowName,button.dataset.stepName);
      return;
    }
    if(!id) return;
    var actions={
      'edit-def':wfOpenEditDef,
      'open-instance':wfOpenInstance,
      'sla-respond':slaRespond,
      'sla-resolve':slaResolve,
      'sla-escalate':slaEscalate,
      'preview-comm':wfPreviewComm,
      'edit-comm':wfEditComm,
    };
    if(action==='toggle-def'){wfToggleDef(id,button.dataset.currentActive==='true');return;}
    if(action==='toggle-sla'){slaToggleDef(id,button.dataset.currentActive==='true');return;}
    if(Object.prototype.hasOwnProperty.call(actions,action)) actions[action](id);
  });
  document.addEventListener('keydown',function(event){
    if(!['Enter',' '].includes(event.key)) return;
    var row=event.target.closest('tr[data-wf-action="open-instance"]');
    if(row && event.target===row){event.preventDefault();row.click();}
  });
  document.addEventListener('change',function(event){
    if(event.target.id==='wfTargetOrg') wfLoadTargetDefinitions();
  });
  document.addEventListener('input',function(event){
    if(event.target.id==='instSearch') renderInstances();
  });
  document.addEventListener('submit',function(event){
    var form=event.target.closest('#wfModalRoot form[data-wf-submit]');
    if(!form) return;
    event.preventDefault();
    var kind=form.dataset.wfSubmit, id=wfSafeId(form.dataset.id);
    if(kind==='start-instance' && id) wfSubmitStartInst(event,id);
    else if(kind==='edit-def' && id) wfSubmitEditDef(event,id);
    else if(kind==='definition') wfSubmitDef(event);
    else if(kind==='start-sla') slaSubmitStart(event);
    else if(kind==='sla-policy') wfSubmitSla(event);
    else if(kind==='comm') wfSubmitComm(event,id||null);
  });
  var wfIsSuperAdmin = document.getElementById('wfConfig').dataset.superAdmin === 'true';
  async function wfTargetOrgField(){
    if(!wfIsSuperAdmin) return '';
    var orgs=(await apiFetch('/super-admin/api/orgs')).filter(function(o){return o.status==='active';});
    if(!orgs.length) throw new Error('No active organization is available');
    return '<div class="form-group"><label for="wfTargetOrg">Organization</label>'+
      '<select id="wfTargetOrg" required ><option value="">Select an organization</option>'+
      orgs.map(function(o){return '<option value="'+wfSafeId(o.id)+'">'+esc(o.name)+'</option>';}).join('')+
      '</select></div>';
  }
  function wfSelectedOrg(body){
    var select=document.getElementById('wfTargetOrg');
    if(select) body.org_id=Number(select.value);
    return body;
  }
  window.wfLoadTargetDefinitions=async function(){
    var target=document.getElementById('wfTargetOrg');
    var select=document.getElementById('wfStartDef')||document.getElementById('slaStartDef');
    if(!target||!select) return;
    select.innerHTML='<option value="">Select an organization first</option>';
    if(!target.value) return;
    var isSla=select.id==='slaStartDef';
    var url=(isSla?'/api/sla/definitions':'/api/workflows/definitions')+
      '?org_id='+encodeURIComponent(target.value);
    try{
      var defs=(await apiFetch(url)).filter(function(d){return d.is_active;});
      select.innerHTML='<option value="">Select '+(isSla?'an SLA policy':'a workflow')+'</option>'+
        defs.map(function(d){return '<option value="'+wfSafeId(d.id)+'">'+esc(d.name)+'</option>';}).join('');
      if(!defs.length&&typeof showToast==='function')
        showToast('No active '+(isSla?'SLA policies':'workflows')+' for this organization','error');
    }catch(e){
      if(typeof showToast==='function') showToast('Failed to load definitions','error');
    }
  };

  function timeAgo(ts){
    if(!ts) return '--';
    var s=Math.floor((Date.now()-new Date(ts.includes('T')?ts:ts+'Z').getTime())/1000);
    if(s<60) return 'just now';
    if(s<3600) return Math.floor(s/60)+'m ago';
    if(s<86400) return Math.floor(s/3600)+'h ago';
    return Math.floor(s/86400)+'d ago';
  }

  function statusBadge(s){
    var m={active:'badge-progress',completed:'badge-complete',rejected:'badge-critical',returned:'badge-medium',pending:'badge-draft',approved:'badge-complete',disabled:'badge-draft'};
    var label=(s||'unknown').replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();});
    var key=(s||'').toLowerCase();
    return '<span class="badge '+(Object.prototype.hasOwnProperty.call(m,key)?m[key]:'badge-draft')+'">'+esc(label)+'</span>';
  }

  function catColor(cat){
    var m={Governance:'#6366f1',Risk:'#ef4444',Audit:'#3b82f6',BCM:'#f59e0b',Privacy:'#8b5cf6','Third Party':'#14b8a6',Operations:'#64748b'};
    return Object.prototype.hasOwnProperty.call(m,cat)?m[cat]:'var(--accent)';
  }

  // Build a deep-link for a given entity (module/type/id)
  var MODULE_HREF={aria:'/aria/',grid:'/grid/',bcm:'/bcm/',sentinel:'/sentinel/',evidence:'/evidence/',erm:'/erm/',orm:'/orm/'};
  function entityLink(module, entityType, entityId){
    if(!module && !entityType) return '';
    var label=(module||'')+(entityType?' / '+entityType.replace(/_/g,' '):'')+(entityId?' #'+entityId:'');
    if(!module) return '<span style="font-size:11px;color:var(--muted)">'+esc(label)+'</span>';
    var href=(Object.prototype.hasOwnProperty.call(MODULE_HREF,module)?MODULE_HREF[module]:'/') + '?open=' + entityType + ':' + entityId;
    return '<a class="pending-entity-link" href="'+esc(href)+'" title="Open in '+esc(module)+'" target="_blank" rel="noopener noreferrer">'+
      '↗ '+esc(label)+'</a>';
  }

  async function apiFetch(url,opts){
    // PLAN-36 T06 (findings.md F08): delegates to the shared ApiClient --
    // see modules/erm/templates/index.html's identical migration.
    opts=opts||{};
    return ApiClient.request(url, { method: opts.method, body: opts.body, headers: opts.headers, actionId: url });
  }

  /* ════════════════════════════════════════════════════════════════════════
     TAB SWITCHING
     ════════════════════════════════════════════════════════════════════════ */
  window.wfShowTab=function(tab,btn){
    document.querySelectorAll('.wf-tab').forEach(function(t){t.classList.remove('active');});
    document.querySelectorAll('.wf-panel').forEach(function(p){p.classList.remove('active');});
    if(btn) btn.classList.add('active');
    var panel=document.getElementById('panel-'+tab);
    if(panel) panel.classList.add('active');
    var names={templates:'Templates',definitions:'Definitions',instances:'Active Flows',sla:'SLA Policies',comms:'Notification Templates'};
    document.getElementById('wfBreadcrumb').textContent=names[tab]||'Workflows';
    if(tab==='templates') loadTemplates();
    else if(tab==='definitions') loadDefinitions();
    else if(tab==='instances') loadInstances();
    else if(tab==='sla'){loadSlaStats();loadSlaDefs();}
    else if(tab==='comms') loadComms();
  };

  /* ════════════════════════════════════════════════════════════════════════
     STATS
     ════════════════════════════════════════════════════════════════════════ */
  var installedDefNames=[];
  async function loadStats(){
    try{
      var defs=await apiFetch('/api/workflows/definitions');
      installedDefNames=defs.map(function(d){return(d.name||'').toLowerCase();});
      var active=await apiFetch('/api/workflows/instances?status=active');
      var all=await apiFetch('/api/workflows/instances');
      var actions=await apiFetch('/api/workflows/my-actions');

      document.getElementById('statDefs').textContent=defs.length;
      document.getElementById('statActive').textContent=active.length;
      document.getElementById('statPending').textContent=actions.length;
      var completed=all.filter(function(i){return i.status==='completed';}).length;
      document.getElementById('statCompleted').textContent=completed;

      renderPending(actions);
    }catch(e){}

    // SLA breach count (non-blocking — doesn't break page if SLA tables not created)
    try{
      var sla=await apiFetch('/api/sla/stats');
      var breached=sla.active_breached||0;
      document.getElementById('statSlaBreached').textContent=breached;
      // Add badge on SLA tab if there are active breaches
      var slaTab=document.getElementById('slaTabBtn');
      var existingBadge=slaTab&&slaTab.querySelector('.wf-tab-badge');
      if(slaTab){
        if(breached>0 && !existingBadge){
          var badge=document.createElement('span');
          badge.className='wf-tab-badge';
          badge.textContent=breached;
          slaTab.appendChild(badge);
        } else if(breached===0 && existingBadge){
          existingBadge.remove();
        } else if(existingBadge){
          existingBadge.textContent=breached;
        }
      }
    }catch(e){
      document.getElementById('statSlaBreached').textContent='0';
    }
  }

  // Cache my-actions for use in instance table
  var myActionCache=[];

  function renderPending(actions){
    myActionCache=actions||[];
    var banner=document.getElementById('pendingBanner');
    if(!actions.length){banner.style.display='none';return;}
    banner.style.display='block';
    document.getElementById('pendingList').innerHTML=actions.map(function(a){
      var entityHtml=entityLink(a.entity_module,a.entity_type,a.entity_id);
      var stepName=a.step_name||('Step '+(a.step_index+1));
      // Escape strings for inline onclick - use data attribute pattern
      return '<div class="pending-action-row" data-aid="'+wfSafeId(a.id)+'" data-iid="'+wfSafeId(a.instance_id)+'">'+
        '<div>'+
          '<span style="font-weight:700;font-size:13px;color:var(--text)">'+esc(a.workflow_name)+'</span>'+
          '<div class="pending-meta">'+
            '<span style="font-size:11px;font-weight:700;color:var(--muted);background:var(--surface2);padding:2px 7px;border-radius:10px">'+esc(stepName)+'</span>'+
            (entityHtml ? entityHtml : '')+
            '<span style="font-size:11px;color:var(--muted)">· '+timeAgo(a.created_at)+'</span>'+
          '</div>'+
        '</div>'+
        '<button class="btn btn-sm btn-primary js-workflow-decision" data-action-id="'+wfSafeId(a.id)+'" data-instance-id="'+wfSafeId(a.instance_id)+'" data-workflow-name="'+esc(a.workflow_name)+'" data-step-name="'+esc(stepName)+'">'+
          'Decide &#9658;'+
        '</button>'+
      '</div>';
    }).join('');
  }

  /* ════════════════════════════════════════════════════════════════════════
     TEMPLATE GALLERY
     ════════════════════════════════════════════════════════════════════════ */
  var tplCache=[];
  var tplFilter='All';

  async function loadTemplates(){
    try{
      tplCache=await apiFetch('/api/workflows/templates');
      var cats=['All'];
      tplCache.forEach(function(t){if(cats.indexOf(t.category)===-1)cats.push(t.category);});
      document.getElementById('tplFilters').innerHTML=cats.map(function(c){
        return '<button class="chip js-workflow-filter'+(c===tplFilter?' active':'')+'" data-category="'+esc(c)+'">'+esc(c)+'</button>';
      }).join('');
      renderTemplates();
    }catch(e){
      document.getElementById('tplGrid').innerHTML='<div style="text-align:center;padding:48px;color:var(--muted);grid-column:1/-1">Failed to load templates</div>';
    }
  }

  window.wfFilterTpl=function(cat,btn){
    tplFilter=cat;
    btn.parentElement.querySelectorAll('.chip').forEach(function(c){c.classList.remove('active');});
    btn.classList.add('active');
    renderTemplates();
  };

  function renderTemplates(){
    var items=tplFilter==='All'?tplCache:tplCache.filter(function(t){return t.category===tplFilter;});
    if(!items.length){
      document.getElementById('tplGrid').innerHTML='<div style="text-align:center;padding:48px;color:var(--muted);grid-column:1/-1">No templates in this category</div>';
      return;
    }
    document.getElementById('tplGrid').innerHTML=items.map(function(t){
      var color=catColor(t.category);
      var stepsHtml=t.steps.map(function(s,i){
        var icon=s.type==='approval'?'<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M9 11l3 3L22 4"/></svg>':
                  s.type==='task'?'<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 12l2 2 4-4"/></svg>':
                  '<svg viewBox="0 0 24 24" fill="none" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/></svg>';
        return (i>0?'<span class="tpl-arrow"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-arrow-right></use></svg></span>':'')+
          '<span class="tpl-step">'+icon+esc(s.name)+'</span>';
      }).join('');
      return '<div class="tpl-card">'+
        '<div class="tpl-badge" style="background:color-mix(in srgb,'+color+' 12%,transparent);color:'+color+'">'+esc(t.category)+'</div>'+
        '<div class="tpl-name">'+esc(t.name)+'</div>'+
        '<div class="tpl-desc">'+esc(t.description)+'</div>'+
        '<div class="tpl-steps">'+stepsHtml+'</div>'+
        '<div class="tpl-meta">'+
          '<span><svg viewBox="0 0 24 24" fill="none" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg> '+esc(t.trigger_module)+'</span>'+
          '<span style="color:var(--border)">&middot;</span>'+
          '<span>'+t.steps.length+' steps</span>'+
        '</div>'+
        '<div style="margin-top:14px">'+(installedDefNames.indexOf((t.name||'').toLowerCase())>-1?'<span style="display:inline-flex;align-items:center;gap:4px;padding:5px 12px;border-radius:var(--radius);font-size:12px;font-weight:700;background:rgba(34,197,94,.1);color:var(--green-status)"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg> Installed</span>':canAuthorWorkflow?'<button class="btn btn-sm btn-primary js-workflow-install" data-template-id="'+esc(t.id)+'">Install Workflow</button>':'<span style="font-size:12px;color:var(--muted)">View only</span>')+'</div>'+
      '</div>';
    }).join('');
  }

  window.wfInstallTpl=async function(id){
    try{
      var res=await apiFetch('/api/workflows/templates/'+id+'/install',{method:'POST'});
      if(res.already_exists){
        if(typeof showToast==='function') showToast('This template is already installed','info');
      } else {
        if(typeof showToast==='function') showToast('Workflow installed — view it in Definitions');
        await loadStats();
        renderTemplates();
      }
    }catch(e){
      if(typeof showToast==='function') showToast('Failed to install template','error');
    }
  };

  /* ════════════════════════════════════════════════════════════════════════
     DEFINITIONS
     ════════════════════════════════════════════════════════════════════════ */
  var defCache=[];
  var instCountMap={};  // definition_id → count of active instances

  async function loadDefinitions(){
    var body=document.getElementById('defBody');
    body.innerHTML='<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--muted)"><div class="spinner" style="margin:0 auto"></div></td></tr>';
    try{
      var [defs, insts]=await Promise.all([
        apiFetch('/api/workflows/definitions'),
        apiFetch('/api/workflows/instances')
      ]);
      defCache=defs;
      // Build instances count map
      instCountMap={};
      insts.forEach(function(i){
        if(i.status==='active'){
          instCountMap[i.definition_id]=(instCountMap[i.definition_id]||0)+1;
        }
      });
      if(!defCache.length){
        body.innerHTML='<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--muted)">No workflow definitions yet. Install from Templates or create a custom one.</td></tr>';
        return;
      }
      body.innerHTML=defCache.map(function(d){
        var steps=[];try{steps=JSON.parse(d.steps_json||'[]');}catch(e){}
        var activeInst=instCountMap[d.id]||0;
        var instCell=activeInst>0
          ? '<span style="color:var(--accent);font-weight:700">'+activeInst+' active</span>'
          : '<span style="color:var(--muted)">—</span>';
        return '<tr>'+
          '<td><div style="font-weight:600;font-size:13px">'+esc(d.name)+'</div>'+
            '<div style="font-size:11px;color:var(--muted);margin-top:2px">'+esc(d.description||'')+'</div></td>'+
          '<td style="font-size:12px;color:var(--muted)">'+esc(d.trigger_module||'manual')+' / '+esc(d.trigger_action||'manual')+'</td>'+
          '<td style="text-align:center;font-weight:700">'+steps.length+'</td>'+
          '<td style="text-align:center">'+instCell+'</td>'+
          '<td style="font-size:12px">'+esc(d.creator_name||'System')+'</td>'+
          '<td style="text-align:center">'+statusBadge(d.is_active?'active':'disabled')+'</td>'+
          '<td style="text-align:center">'+
            '<div style="display:flex;gap:4px;justify-content:center">'+
              '<button class="btn btn-sm btn-primary js-workflow-start" data-definition-id="'+wfSafeId(d.id)+'" data-definition-name="'+esc(d.name)+'">Start</button>'+
              (canAuthorWorkflow?'<button class="btn btn-sm btn-secondary" data-wf-action="edit-def" data-id="'+wfSafeId(d.id)+'" title="Edit definition">Edit</button>':'')+
              (canAuthorWorkflow?'<button class="btn btn-sm btn-secondary" data-wf-action="toggle-def" data-id="'+wfSafeId(d.id)+'" data-current-active="'+Boolean(d.is_active)+'" title="'+(d.is_active?'Disable':'Enable')+'" style="'+(d.is_active?'color:var(--muted)':'')+'">'+(d.is_active?'Disable':'Enable')+'</button>':'')+
            '</div>'+
          '</td></tr>';
      }).join('');
    }catch(e){
      body.innerHTML='<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--muted)">Failed to load definitions</td></tr>';
    }
  }

  // Start instance with entity context modal
  window.wfStartInstanceModal=async function(defId, defName){
    var orgField;
    try{orgField=await wfTargetOrgField();}
    catch(e){if(typeof showToast==='function') showToast(e.message||'Failed to load organizations','error');return;}
    var html='<div class="modal-overlay" data-wf-backdrop="true">'+
      '<div class="modal-box" style="max-width:440px">'+
      '<button class="modal-close" data-wf-action="close-modal">&times;</button>'+
      '<div class="modal-title">Start Workflow</div>'+
      (wfIsSuperAdmin?'':'<div class="ctx-block"><div class="ctx-label">Workflow</div><div class="ctx-val">'+esc(defName)+'</div></div>')+
      '<form data-wf-submit="start-instance" data-id="'+wfSafeId(defId)+'">'+
        orgField+
        (wfIsSuperAdmin?'<div class="form-group"><label for="wfStartDef">Workflow</label>'+
          '<select id="wfStartDef" required><option value="">Select an organization first</option></select></div>':'')+
        '<div class="form-row">'+
          '<div class="form-group"><label>Entity Module (optional)</label>'+
            '<select id="siModule"><option value="">None</option><option value="aria">ARIA</option><option value="sentinel">Sentinel</option><option value="grid">GRID</option><option value="bcm">BCM</option></select></div>'+
          '<div class="form-group"><label>Entity Type (optional)</label>'+
            '<input type="text" id="siType" placeholder="e.g. policy, finding"></div>'+
        '</div>'+
        '<div class="form-group"><label>Entity ID (optional)</label>'+
          '<input type="number" id="siId" placeholder="Record ID to attach to this flow"></div>'+
        '<div style="margin-top:16px;display:flex;gap:8px">'+
          '<button type="submit" class="btn btn-primary" style="flex:1">Start Flow</button>'+
          '<button type="button" class="btn btn-secondary" data-wf-action="close-modal">Cancel</button>'+
        '</div>'+
      '</form></div></div>';
    document.getElementById('wfModalRoot').innerHTML=html;
  };

  window.wfSubmitStartInst=function(e,defId){
    e.preventDefault();
    var body={
      definition_id:wfIsSuperAdmin?Number(document.getElementById('wfStartDef').value):defId,
      entity_module:document.getElementById('siModule').value,
      entity_type:document.getElementById('siType').value,
      entity_id:parseInt(document.getElementById('siId').value)||null
    };
    apiFetch('/api/workflows/instances',{method:'POST',body:wfSelectedOrg(body)}).then(function(){
      wfCloseModal();
      if(typeof showToast==='function') showToast('Workflow started');
      loadStats();
      wfShowTab('instances',document.querySelectorAll('.wf-tab')[2]);
    }).catch(function(err){
      if(typeof showToast==='function') showToast('Failed to start workflow: '+err.message,'error');
    });
    return false;
  };

  window.wfToggleDef=async function(id,currentActive){
    try{
      await apiFetch('/api/workflows/definitions/'+id,{method:'PUT',body:{is_active:!currentActive}});
      loadDefinitions();loadStats();
    }catch(e){
      if(typeof showToast==='function') showToast('Failed to update workflow','error');
    }
  };

  // Edit definition — opens the same create modal pre-populated
  window.wfOpenEditDef=function(id){
    var d=defCache.find(function(x){return x.id===id;});
    if(!d){if(typeof showToast==='function') showToast('Definition not found','error');return;}
    var steps=[];try{steps=JSON.parse(d.steps_json||'[]');}catch(e){}

    stepCounter=0;
    var html='<div class="modal-overlay" data-wf-backdrop="true">'+
      '<div class="modal-box">'+
      '<button class="modal-close" data-wf-action="close-modal">&times;</button>'+
      '<div class="modal-title">Edit Workflow</div>'+
      '<form id="wfDefForm" data-wf-submit="edit-def" data-id="'+wfSafeId(id)+'">'+
        '<div class="form-group"><label>Workflow Name</label><input type="text" id="wfName" required value="'+esc(d.name)+'"></div>'+
        '<div class="form-group"><label>Description</label><textarea id="wfDesc" rows="2">'+esc(d.description||'')+'</textarea></div>'+
        '<div class="form-row">'+
          '<div class="form-group"><label>Trigger Module</label>'+
            '<select id="wfModule">'+
              '<option value=""'+((!d.trigger_module)?' selected':'')+'>Any / Manual</option>'+
              ['aria','sentinel','grid','bcm'].map(function(m){return '<option value="'+m+'"'+(d.trigger_module===m?' selected':'')+'>'+m.toUpperCase()+'</option>';}).join('')+
            '</select></div>'+
          '<div class="form-group"><label>Trigger Action</label><input type="text" id="wfAction" value="'+esc(d.trigger_action||'')+'" placeholder="e.g. policy.created"></div>'+
        '</div>'+
        '<div class="form-group"><label>Approval Steps</label><div id="stepBuilder"></div>'+
          '<button type="button" class="btn btn-sm btn-secondary" data-wf-action="add-step" style="margin-top:8px">+ Add Step</button></div>'+
        '<div style="margin-top:20px;display:flex;gap:8px">'+
          '<button type="submit" class="btn btn-primary" style="flex:1">Save Changes</button>'+
          '<button type="button" class="btn btn-secondary" data-wf-action="close-modal">Cancel</button>'+
        '</div>'+
      '</form></div></div>';
    document.getElementById('wfModalRoot').innerHTML=html;
    // Pre-populate steps
    if(steps.length){
      steps.forEach(function(s){wfAddStepPrefilled(s.name||s.label||'',s.type||s.action_type||'approve');});
    } else {
      wfAddStep();
    }
  };

  window.wfSubmitEditDef=function(e,id){
    e.preventDefault();
    var steps=[];
    document.querySelectorAll('#stepBuilder .step-item').forEach(function(el){
      var label=el.querySelector('[data-field="label"]').value;
      var type=el.querySelector('[data-field="action_type"]').value;
      if(label) steps.push({label:label,action_type:type,name:label,type:type});
    });
    if(!steps.length){if(typeof showToast==='function') showToast('Add at least one step','error');return false;}
    var body={
      name:document.getElementById('wfName').value,
      description:document.getElementById('wfDesc').value,
      trigger_module:document.getElementById('wfModule').value,
      trigger_action:document.getElementById('wfAction').value,
      steps:steps
    };
    apiFetch('/api/workflows/definitions/'+id,{method:'PUT',body:body}).then(function(){
      wfCloseModal();
      if(typeof showToast==='function') showToast('Workflow updated');
      loadDefinitions();
    }).catch(function(err){
      if(typeof showToast==='function') showToast('Failed to update workflow','error');
    });
    return false;
  };

  /* ════════════════════════════════════════════════════════════════════════
     INSTANCES
     ════════════════════════════════════════════════════════════════════════ */
  var instCache=[];
  var instFilter='all';

  window.wfFilterInst=function(status,btn){
    instFilter=status;
    btn.parentElement.querySelectorAll('.chip').forEach(function(c){c.classList.remove('active');});
    btn.classList.add('active');
    renderInstances();
  };

  async function loadInstances(){
    var body=document.getElementById('instBody');
    body.innerHTML='<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--muted)"><div class="spinner" style="margin:0 auto"></div></td></tr>';
    try{
      instCache=await apiFetch('/api/workflows/instances');
      renderInstances();
    }catch(e){
      body.innerHTML='<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--muted)">Failed to load instances</td></tr>';
    }
  }

  function renderInstances(){
    var search=(document.getElementById('instSearch')||{}).value||'';
    search=search.trim().toLowerCase();

    var items=instFilter==='all'?instCache:instCache.filter(function(i){return i.status===instFilter;});
    if(search){
      items=items.filter(function(i){
        return (i.workflow_name||'').toLowerCase().includes(search)||
               (i.entity_module||'').toLowerCase().includes(search)||
               (i.entity_type||'').toLowerCase().includes(search)||
               (i.started_by_name||'').toLowerCase().includes(search);
      });
    }

    var body=document.getElementById('instBody');
    if(!items.length){
      body.innerHTML='<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--muted)">No workflow instances found</td></tr>';
      return;
    }

    body.innerHTML=items.map(function(i){
      // Parse current step name
      var steps=[];try{steps=JSON.parse(i.steps_json||'[]');}catch(e){}
      var stepCount=steps.length||Math.max(i.current_step+1,1);
      var currentStepName='—';
      if(i.status==='active' && steps[i.current_step]){
        currentStepName=steps[i.current_step].name||steps[i.current_step].label||('Step '+(i.current_step+1));
      } else if(i.status==='completed'){
        currentStepName='<span style="color:var(--green-status);font-weight:600">✓ Complete</span>';
      } else if(i.status==='rejected'){
        currentStepName='<span style="color:var(--red);font-weight:600">✗ Rejected</span>';
      } else if(i.status==='returned'){
        currentStepName='<span style="color:var(--amber);font-weight:600">↩ Returned</span>';
      }

      var progressPct=stepCount>0?Math.round(((i.current_step+(i.status==='completed'?1:0))/stepCount)*100):0;
      var barColor=i.status==='completed'?'var(--green-status)':i.status==='rejected'?'var(--red)':'var(--accent)';

      // Check if current user has a pending action for this instance
      var myAction=myActionCache.find(function(a){return a.instance_id===i.id;});
      var entityHtml=entityLink(i.entity_module,i.entity_type,i.entity_id)||'<span style="color:var(--muted);font-size:12px">—</span>';

      return '<tr style="cursor:pointer" role="button" tabindex="0" data-wf-action="open-instance" data-id="'+wfSafeId(i.id)+'">'+
        '<td>'+
          '<div style="font-weight:600;font-size:13px">'+esc(i.workflow_name||'--')+'</div>'+
          (myAction?'<div style="font-size:10px;font-weight:700;color:var(--amber);margin-top:2px"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-hourglass></use></svg> Your action needed</div>':'')+
        '</td>'+
        '<td style="font-size:12px">'+entityHtml+'</td>'+
        '<td style="font-size:12px">'+currentStepName+'</td>'+
        '<td style="text-align:center">'+
          '<div style="display:flex;align-items:center;gap:8px;justify-content:center">'+
            '<div style="flex:1;max-width:70px;height:5px;background:var(--surface2);border-radius:3px;overflow:hidden">'+
              '<div style="height:100%;width:'+progressPct+'%;background:'+barColor+';border-radius:3px"></div>'+
            '</div>'+
            '<span style="font-size:11px;font-weight:600;color:var(--muted);width:30px">'+progressPct+'%</span>'+
          '</div>'+
        '</td>'+
        '<td style="font-size:12px">'+esc(i.started_by_name||'--')+'</td>'+
        '<td style="font-size:12px;color:var(--muted)">'+timeAgo(i.started_at)+'</td>'+
        '<td style="text-align:center">'+statusBadge(i.status)+'</td></tr>';
    }).join('');
  }

  /* ════════════════════════════════════════════════════════════════════════
     INSTANCE DETAIL DRAWER
     ════════════════════════════════════════════════════════════════════════ */
  window.wfOpenInstance=async function(iid){
    var root=document.getElementById('wfDrawerRoot');
    root.innerHTML='<div class="drawer-overlay" data-wf-action="close-drawer"></div>'+
      '<div class="drawer">'+
        '<div class="drawer-header">'+
          '<span style="font-weight:700;font-size:16px">Loading…</span>'+
          '<button class="drawer-close" data-wf-action="close-drawer">&times;</button>'+
        '</div>'+
        '<div class="drawer-body"><div class="spinner" style="margin:24px auto"></div></div>'+
      '</div>';
    try{
      var inst=await apiFetch('/api/workflows/instances/'+iid);
      var steps=inst.steps||[];
      var actions=inst.actions||[];

      // Pipeline visualization
      var pipeHtml='<div class="pipe">';
      steps.forEach(function(s,idx){
        var action=actions.find(function(a){return a.step_index===idx;});
        var cls='';
        if(action&&(action.status==='approved'||action.status==='completed')) cls='done';
        else if(action&&action.status==='rejected') cls='rejected';
        else if(idx===inst.current_step&&inst.status==='active') cls='current';
        var iconSvg=cls==='done'?'<svg class="pipe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>':
          cls==='rejected'?'<svg class="pipe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>':
          cls==='current'?'<svg class="pipe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3" fill="currentColor"/></svg>':
          '<svg class="pipe-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="8"/></svg>';
        if(idx>0) pipeHtml+='<div class="pipe-connector'+(cls==='done'?' done':'')+'"></div>';
        pipeHtml+='<div class="pipe-step '+cls+'">'+iconSvg+'<span>'+esc(s.name||s.label||'Step '+(idx+1))+'</span></div>';
      });
      pipeHtml+='</div>';

      // Action history with comments
      var histHtml='<div style="margin-top:24px"><div style="font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:12px">Decision History</div>';
      if(actions.length){
        histHtml+=actions.map(function(a){
          var step=steps[a.step_index]||{};
          return '<div style="display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)">'+
            '<div style="width:32px;height:32px;border-radius:50%;background:var(--surface2);display:flex;align-items:center;justify-content:center;flex-shrink:0">'+
              '<span style="font-size:12px;font-weight:700;color:var(--muted)">'+(a.step_index+1)+'</span></div>'+
            '<div style="flex:1">'+
              '<div style="font-size:13px;font-weight:600;color:var(--text)">'+esc(step.name||step.label||'Step '+(a.step_index+1))+'</div>'+
              '<div style="font-size:11px;color:var(--muted);margin-top:2px">'+
                statusBadge(a.status)+
                (a.assigned_name?' &middot; '+esc(a.assigned_name):'')+
                (a.acted_at?' &middot; '+timeAgo(a.acted_at):' &middot; pending')+
              '</div>'+
              (a.comment?'<div style="font-size:12px;margin-top:8px;padding:8px 10px;background:var(--surface2);border-radius:var(--radius);color:var(--text);font-style:italic">&ldquo;'+esc(a.comment)+'&rdquo;</div>':'')+
            '</div></div>';
        }).join('');
      } else {
        histHtml+='<div style="font-size:12px;color:var(--muted)">No actions yet</div>';
      }
      histHtml+='</div>';

      // Check if current user can decide
      var myAction=myActionCache.find(function(a){return a.instance_id===iid;});
      var decideFooter='';
      if(myAction&&inst.status==='active'){
        decideFooter='<button class="btn btn-primary" data-wf-action="open-decision" data-action-id="'+wfSafeId(myAction.id)+'" data-instance-id="'+wfSafeId(iid)+'" data-workflow-name="'+esc(inst.workflow_name||'')+'" data-step-name="Current step">Decide on This Flow</button>';
      }

      root.querySelector('.drawer-header span').textContent=inst.workflow_name||'Instance #'+iid;
      root.querySelector('.drawer-body').innerHTML=
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px">'+
          '<div><div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase">Status</div><div style="margin-top:4px">'+statusBadge(inst.status)+'</div></div>'+
          '<div><div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase">Started</div><div style="font-size:13px;color:var(--text);margin-top:4px">'+timeAgo(inst.started_at)+' by '+esc(inst.started_by_name||'--')+'</div></div>'+
          '<div><div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase">Entity</div><div style="font-size:13px;margin-top:4px">'+entityLink(inst.entity_module,inst.entity_type,inst.entity_id)+'</div></div>'+
          (inst.completed_at?'<div><div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase">Completed</div><div style="font-size:13px;color:var(--text);margin-top:4px">'+timeAgo(inst.completed_at)+'</div></div>':'')+
        '</div>'+
        '<div style="font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:8px">Approval Pipeline</div>'+
        pipeHtml+histHtml;

      // Add footer if current user can decide
      if(decideFooter){
        var footer=root.querySelector('.drawer').querySelector('.drawer-footer');
        if(!footer){
          footer=document.createElement('div');
          footer.className='drawer-footer';
          root.querySelector('.drawer').appendChild(footer);
        }
        footer.innerHTML=decideFooter;
      }
    }catch(e){
      root.querySelector('.drawer-body').innerHTML='<div style="color:var(--muted);text-align:center;padding:32px">Failed to load instance details</div>';
    }
  };

  window.wfCloseDrawer=function(){document.getElementById('wfDrawerRoot').innerHTML='';};

  /* ════════════════════════════════════════════════════════════════════════
     DECISION MODAL — WITH CONTEXT
     ════════════════════════════════════════════════════════════════════════ */
  var currentActionId=null;

  window.wfOpenDecision=async function(aid, instanceId, workflowName, stepName){
    currentActionId=aid;

    // Show loading modal immediately
    var html='<div class="modal-overlay" data-wf-backdrop="true">'+
      '<div class="modal-box" style="max-width:500px">'+
      '<button class="modal-close" data-wf-action="close-modal">&times;</button>'+
      '<div class="modal-title">Decision Required</div>'+
      '<div id="decisionContext"><div class="spinner" style="margin:20px auto"></div></div>'+
      '</div></div>';
    document.getElementById('wfModalRoot').innerHTML=html;

    // Load instance context
    try{
      var inst=await apiFetch('/api/workflows/instances/'+instanceId);
      var steps=inst.steps||[];
      var actions=inst.actions||[];

      // Previous decisions (from steps before current)
      var prevDecisions=actions.filter(function(a){return a.acted_at&&a.step_index<inst.current_step;});
      var prevHtml='';
      if(prevDecisions.length){
        prevHtml='<div style="margin-bottom:14px"><div style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:6px">Previous Decisions</div>'+
          prevDecisions.map(function(a){
            var step=steps[a.step_index]||{};
            return '<div style="display:flex;gap:10px;align-items:start;padding:8px 0;border-bottom:1px solid var(--border)">'+
              '<span style="font-size:11px;font-weight:700;padding:2px 7px;border-radius:10px;background:var(--surface2);color:var(--muted);white-space:nowrap">Step '+(a.step_index+1)+'</span>'+
              '<div>'+
                '<div style="font-size:12px;font-weight:600">'+esc(step.name||step.label||'')+'</div>'+
                '<div style="font-size:11px;color:var(--muted)">'+statusBadge(a.status)+(a.assigned_name?' · '+esc(a.assigned_name):'')+'</div>'+
                (a.comment?'<div class="ctx-comment">&ldquo;'+esc(a.comment)+'&rdquo;</div>':'')+
              '</div>'+
            '</div>';
          }).join('')+
        '</div>';
      }

      var decisionContextHtml=
        '<div class="ctx-block">'+
          '<div class="ctx-label">Workflow</div><div class="ctx-val">'+esc(inst.workflow_name||workflowName||'')+'</div>'+
        '</div>'+
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px">'+
          '<div><div style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:4px">Current Step</div>'+
            '<div style="font-size:13px;font-weight:600;color:var(--text)">Step '+(inst.current_step+1)+
            (steps[inst.current_step]?' — '+esc(steps[inst.current_step].name||steps[inst.current_step].label||''):'')+
            '</div></div>'+
          '<div><div style="font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:4px">Entity</div>'+
            '<div style="font-size:13px">'+entityLink(inst.entity_module,inst.entity_type,inst.entity_id)+'</div></div>'+
        '</div>'+
        prevHtml+
        '<div class="form-group"><label>Comment (optional)</label>'+
          '<textarea id="decComment" rows="3" placeholder="Add a note for audit trail…"></textarea></div>'+
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:16px">'+
          '<button class="btn btn-primary" style="background:var(--green-status);border-color:var(--green-status)" data-wf-action="submit-decision" data-decision="approve">'+
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M20 6L9 17l-5-5"/></svg> Approve</button>'+
          '<button class="btn btn-secondary" data-wf-action="submit-decision" data-decision="return">↩ Return</button>'+
          '<button class="btn btn-primary" style="background:var(--red);border-color:var(--red)" data-wf-action="submit-decision" data-decision="reject">'+
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg> Reject</button>'+
        '</div>';

      document.getElementById('decisionContext').innerHTML=decisionContextHtml;
    }catch(e){
      // Fallback if instance detail fails — still show the basic form
      document.getElementById('decisionContext').innerHTML=
        '<div class="ctx-block"><div class="ctx-label">Workflow</div><div class="ctx-val">'+esc(workflowName||'')+'</div></div>'+
        '<div style="font-size:12px;color:var(--muted);margin-bottom:12px">'+esc(stepName||'')+'</div>'+
        '<div class="form-group"><label>Comment (optional)</label><textarea id="decComment" rows="3" placeholder="Add a note…"></textarea></div>'+
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:16px">'+
          '<button class="btn btn-primary" style="background:var(--green-status);border-color:var(--green-status)" data-wf-action="submit-decision" data-decision="approve">Approve</button>'+
          '<button class="btn btn-secondary" data-wf-action="submit-decision" data-decision="return">Return</button>'+
          '<button class="btn btn-primary" style="background:var(--red);border-color:var(--red)" data-wf-action="submit-decision" data-decision="reject">Reject</button>'+
        '</div>';
    }
  };

  window.wfSubmitDecision=async function(decision){
    if(!currentActionId) return;
    var comment=(document.getElementById('decComment')||{}).value||'';
    try{
      await apiFetch('/api/workflows/actions/'+currentActionId+'/decide',{method:'POST',body:{decision:decision,comment:comment}});
      wfCloseModal();
      loadStats();
      if(document.getElementById('panel-instances').classList.contains('active')) loadInstances();
      if(typeof showToast==='function'){
        var labels={approve:'Approved ✓',reject:'Rejected — workflow ended',return:'Returned for revision'};
        showToast(labels[decision]||'Decision recorded');
      }
    }catch(e){
      if(typeof showToast==='function') showToast('Failed to submit decision','error');
    }
  };

  window.wfCloseModal=function(){document.getElementById('wfModalRoot').innerHTML='';};

  /* ════════════════════════════════════════════════════════════════════════
     NEW WORKFLOW DEFINITION MODAL
     ════════════════════════════════════════════════════════════════════════ */
  var stepCounter=0;

  window.wfOpenNewDef=function(){
    stepCounter=0;
    var html='<div class="modal-overlay" data-wf-backdrop="true">'+
      '<div class="modal-box">'+
      '<button class="modal-close" data-wf-action="close-modal">&times;</button>'+
      '<div class="modal-title">Create Workflow</div>'+
      '<form id="wfDefForm" data-wf-submit="definition">'+
        '<div class="form-group"><label>Workflow Name</label><input type="text" id="wfName" required placeholder="e.g. Document Approval"></div>'+
        '<div class="form-group"><label>Description</label><textarea id="wfDesc" rows="2" placeholder="What does this workflow do?"></textarea></div>'+
        '<div class="form-row">'+
          '<div class="form-group"><label>Trigger Module</label>'+
            '<select id="wfModule">'+
              '<option value="">Any / Manual</option>'+
              '<option value="aria">ARIA</option><option value="sentinel">Sentinel</option>'+
              '<option value="grid">GRID</option><option value="bcm">BCM</option>'+
            '</select></div>'+
          '<div class="form-group"><label>Trigger Action <span style="font-weight:400;text-transform:none;letter-spacing:0">(e.g. policy.created)</span></label>'+
            '<input type="text" id="wfAction" placeholder="leave blank for manual start" list="triggerSuggestions">'+
            '<datalist id="triggerSuggestions">'+
              '<option value="policy.created"><option value="policy.updated"><option value="risk.escalated">'+
              '<option value="audit.findings_resolved"><option value="incident.declared">'+
              '<option value="breach.confirmed"><option value="vendor.created"><option value="change.requested">'+
            '</datalist>'+
          '</div>'+
        '</div>'+
        '<div class="form-group"><label>Approval Steps</label><div id="stepBuilder"></div>'+
          '<button type="button" class="btn btn-sm btn-secondary" data-wf-action="add-step" style="margin-top:8px">+ Add Step</button>'+
        '</div>'+
        '<div style="margin-top:20px"><button type="submit" class="btn btn-primary" style="width:100%">Create Workflow</button></div>'+
      '</form></div></div>';
    document.getElementById('wfModalRoot').innerHTML=html;
    wfAddStep();wfAddStep();
  };

  window.wfAddStep=function(){wfAddStepPrefilled('','approve');};

  window.wfAddStepPrefilled=function(label, type){
    var c=document.getElementById('stepBuilder');
    var idx=++stepCounter;
    var div=document.createElement('div');
    div.className='step-item';
    div.innerHTML=
      '<div class="step-num">'+idx+'</div>'+
      '<input type="text" placeholder="Step name (e.g. Manager Review)" data-step="'+idx+'" data-field="label" value="'+esc(label)+'" style="padding:8px 10px;border:1px solid var(--border);border-radius:var(--radius);background:var(--surface);color:var(--text);font-size:13px">'+
      '<select data-step="'+idx+'" data-field="action_type" style="padding:8px 10px;border:1px solid var(--border);border-radius:var(--radius);background:var(--surface);color:var(--text);font-size:13px">'+
        '<option value="approve"'+(type==='approve'?' selected':'')+'>Approval</option>'+
        '<option value="review"'+(type==='review'?' selected':'')+'>Review</option>'+
        '<option value="sign_off"'+(type==='sign_off'?' selected':'')+'>Sign Off</option>'+
        '<option value="task"'+(type==='task'?' selected':'')+'>Task</option>'+
        '<option value="notification"'+(type==='notification'?' selected':'')+'>Notify</option>'+
      '</select>'+
      '<button type="button" class="step-remove" data-wf-action="remove-step" title="Remove">'+
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>';
    c.appendChild(div);
  };

  window.wfReindexSteps=function(){
    document.querySelectorAll('#stepBuilder .step-item').forEach(function(el,i){
      el.querySelector('.step-num').textContent=i+1;
    });
  };

  window.wfSubmitDef=function(e){
    e.preventDefault();
    var steps=[];
    document.querySelectorAll('#stepBuilder .step-item').forEach(function(el){
      var label=el.querySelector('[data-field="label"]').value;
      var type=el.querySelector('[data-field="action_type"]').value;
      if(label) steps.push({label:label,action_type:type,name:label,type:type});
    });
    if(!steps.length){if(typeof showToast==='function') showToast('Add at least one step','error');return false;}
    var body={
      name:document.getElementById('wfName').value,
      description:document.getElementById('wfDesc').value,
      trigger_module:document.getElementById('wfModule').value,
      trigger_action:document.getElementById('wfAction').value,
      steps:steps
    };
    apiFetch('/api/workflows/definitions',{method:'POST',body:body}).then(function(){
      wfCloseModal();
      if(typeof showToast==='function') showToast('Workflow created');
      loadStats();loadDefinitions();
      wfShowTab('definitions',document.querySelectorAll('.wf-tab')[1]);
    }).catch(function(){
      if(typeof showToast==='function') showToast('Failed to create workflow','error');
    });
    return false;
  };

  /* ════════════════════════════════════════════════════════════════════════
     SLA ENGINE
     ════════════════════════════════════════════════════════════════════════ */

  window.slaSubTab=function(tab,btn){
    btn.parentElement.querySelectorAll('.wf-tab').forEach(function(t){t.classList.remove('active');});
    btn.classList.add('active');
    document.querySelectorAll('.sla-sub').forEach(function(p){p.classList.remove('active');p.style.display='none';});
    var panel=document.getElementById('slaSub-'+tab);
    if(panel){panel.classList.add('active');panel.style.display='block';}
    if(tab==='defs') loadSlaDefs();
    else if(tab==='inst') loadSlaInstances();
    else if(tab==='breach'){loadBreachedList();slaRunBreachCheck();}  // auto-scan on open
  };

  async function loadSlaStats(){
    try{
      var s=await apiFetch('/api/sla/stats');
      document.getElementById('slStatDefs').textContent=s.definitions||0;
      document.getElementById('slStatActive').textContent=s.active||0;
      document.getElementById('slStatBreached').textContent=s.breached||0;
      document.getElementById('slStatRisk').textContent=s.at_risk||0;
      document.getElementById('slStatCompliance').textContent=(s.compliance_pct||100)+'%';
      document.getElementById('slStatResolved').textContent=s.resolved||0;
    }catch(e){}
  }

  function slaCountdown(dueStr,doneStr){
    if(doneStr) return '<span class="sla-countdown done">Done</span>';
    if(!dueStr) return '<span class="sla-countdown done">N/A</span>';
    var ms=new Date(dueStr.includes('T')?dueStr:dueStr+'Z').getTime()-Date.now();
    if(ms<=0) return '<span class="sla-countdown breach">BREACHED</span>';
    var h=Math.floor(ms/3600000);var m=Math.floor((ms%3600000)/60000);
    var cls=h<2?'warn':'ok';
    return '<span class="sla-countdown '+cls+'">'+h+'h '+m+'m</span>';
  }

  function priBadge(p){
    var cls={low:'pri-low',normal:'pri-normal',high:'pri-high',critical:'pri-critical'};
    return '<span class="pri-badge '+(Object.prototype.hasOwnProperty.call(cls,p)?cls[p]:'pri-normal')+'">'+esc((p||'normal').toUpperCase())+'</span>';
  }

  async function loadSlaDefs(){
    var grid=document.getElementById('slaGrid');
    grid.innerHTML='<div style="text-align:center;padding:48px;color:var(--muted);grid-column:1/-1"><div class="spinner" style="margin:0 auto"></div></div>';
    try{
      var items=await apiFetch('/api/sla/definitions');
      if(!items.length){
        grid.innerHTML='<div style="text-align:center;padding:48px;color:var(--muted);grid-column:1/-1">No SLA policies defined yet — create one to start tracking</div>';
        return;
      }
      grid.innerHTML=items.map(function(s){
        return '<div class="sla-card">'+
          '<div style="display:flex;justify-content:space-between;align-items:start">'+
            '<div><div class="sla-name">'+esc(s.name)+'</div>'+
              '<div class="sla-meta">'+esc(s.module||'All modules')+' &middot; '+esc(s.entity_type||'Any entity')+' &middot; '+priBadge(s.priority)+'</div></div>'+
            '<div style="display:flex;gap:6px;align-items:center">'+
              '<span class="badge '+(s.is_active?'badge-complete':'badge-draft')+'">'+(s.is_active?'Active':'Disabled')+'</span>'+
              '<button class="btn btn-sm btn-secondary" data-wf-action="toggle-sla" data-id="'+wfSafeId(s.id)+'" data-current-active="'+Boolean(s.is_active)+'">'+(s.is_active?'Disable':'Enable')+'</button>'+
            '</div>'+
          '</div>'+
          '<div class="sla-times">'+
            '<div class="sla-time"><div class="val">'+(s.response_hours||'—')+'</div><div class="lbl">Response (h)</div></div>'+
            '<div class="sla-time"><div class="val">'+(s.resolution_hours||'—')+'</div><div class="lbl">Resolution (h)</div></div>'+
            '<div class="sla-time"><div class="val">'+(s.escalation_hours||'—')+'</div><div class="lbl">Escalation (h)</div></div>'+
          '</div></div>';
      }).join('');
    }catch(e){
      grid.innerHTML='<div style="text-align:center;padding:48px;color:var(--muted);grid-column:1/-1">Failed to load SLA policies</div>';
    }
  }

  window.slaToggleDef=async function(id,currentActive){
    try{
      await apiFetch('/api/sla/definitions/'+id,{method:'PUT',body:{is_active:!currentActive}});
      loadSlaDefs();loadSlaStats();
      if(typeof showToast==='function') showToast(currentActive?'Policy disabled':'Policy enabled');
    }catch(e){if(typeof showToast==='function') showToast('Failed to update policy','error');}
  };

  var slaInstCache=[];
  var slaInstFilter='all';

  window.slaFilterInst=function(f,btn){
    slaInstFilter=f;
    btn.parentElement.querySelectorAll('.chip').forEach(function(c){c.classList.remove('active');});
    btn.classList.add('active');
    renderSlaInstances();
  };

  async function loadSlaInstances(){
    var body=document.getElementById('slaInstBody');
    body.innerHTML='<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--muted)"><div class="spinner" style="margin:0 auto"></div></td></tr>';
    try{
      slaInstCache=await apiFetch('/api/sla/instances');
      renderSlaInstances();
    }catch(e){
      body.innerHTML='<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--muted)">Failed to load SLA instances</td></tr>';
    }
  }

  function renderSlaInstances(){
    var items=slaInstCache;
    if(slaInstFilter==='active') items=items.filter(function(i){return i.status==='active'&&!i.breached;});
    else if(slaInstFilter==='breached') items=items.filter(function(i){return i.breached;});
    else if(slaInstFilter==='resolved') items=items.filter(function(i){return i.status==='resolved';});
    var body=document.getElementById('slaInstBody');
    if(!items.length){
      body.innerHTML='<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--muted)">No SLA instances found</td></tr>';
      return;
    }
    body.innerHTML=items.map(function(i){
      var respCell=slaCountdown(i.response_due,i.responded_at);
      var resCell=slaCountdown(i.resolution_due,i.resolved_at);
      var statusHtml=i.breached?'<span class="badge badge-critical">Breached</span>':statusBadge(i.status);
      var actHtml='';
      if(i.status==='active'){
        if(!i.responded_at) actHtml+='<button class="btn btn-sm btn-secondary" data-wf-action="sla-respond" data-id="'+wfSafeId(i.id)+'" title="Mark responded">Respond</button> ';
        actHtml+='<button class="btn btn-sm btn-primary" data-wf-action="sla-resolve" data-id="'+wfSafeId(i.id)+'" title="Mark resolved">Resolve</button> ';
        if(!i.escalated_at) actHtml+='<button class="btn btn-sm btn-secondary" data-wf-action="sla-escalate" data-id="'+wfSafeId(i.id)+'" style="color:var(--amber)">Escalate</button>';
      }
      return '<tr'+(i.breached&&i.status==='active'?' style="background:rgba(239,68,68,.04)"':'')+'>'+
        '<td style="font-weight:600;font-size:13px">'+esc(i.sla_name||'--')+'</td>'+
        '<td style="font-size:12px">'+entityLink(i.entity_module,i.entity_type,i.entity_id)+'</td>'+
        '<td>'+priBadge(i.priority)+'</td>'+
        '<td style="text-align:center">'+respCell+'</td>'+
        '<td style="text-align:center">'+resCell+'</td>'+
        '<td style="text-align:center">'+statusHtml+'</td>'+
        '<td style="text-align:center"><div style="display:flex;gap:4px;justify-content:center">'+actHtml+'</div></td></tr>';
    }).join('');
  }

  window.slaRespond=async function(iid){
    try{
      var r=await apiFetch('/api/sla/instances/'+iid+'/respond',{method:'POST'});
      if(typeof showToast==='function') showToast(r.breached?'Responded — SLA already BREACHED':'Response recorded');
      loadSlaInstances();loadSlaStats();
    }catch(e){if(typeof showToast==='function') showToast('Failed to record response','error');}
  };
  window.slaResolve=async function(iid){
    try{
      var r=await apiFetch('/api/sla/instances/'+iid+'/resolve',{method:'POST'});
      if(typeof showToast==='function') showToast(r.breached?'Resolved — SLA was BREACHED':'SLA resolved');
      loadSlaInstances();loadSlaStats();
    }catch(e){if(typeof showToast==='function') showToast('Failed to resolve','error');}
  };
  window.slaEscalate=async function(iid){
    try{
      await apiFetch('/api/sla/instances/'+iid+'/escalate',{method:'POST'});
      if(typeof showToast==='function') showToast('SLA escalated');
      loadSlaInstances();
    }catch(e){if(typeof showToast==='function') showToast('Failed to escalate','error');}
  };

  window.slaOpenStart=async function(){
    var defs=[];
    try{defs=await apiFetch('/api/sla/definitions');}catch(e){}
    var activeDefs=defs.filter(function(d){return d.is_active;});
    if(!activeDefs.length&&!wfIsSuperAdmin){
      if(typeof showToast==='function') showToast('No active SLA policies — create one first','error');
      return;
    }
    var orgField;
    try{orgField=await wfTargetOrgField();}
    catch(e){if(typeof showToast==='function') showToast(e.message||'Failed to load organizations','error');return;}
    var optsHtml=(wfIsSuperAdmin?[]:activeDefs).map(function(d){
      return '<option value="'+wfSafeId(d.id)+'">'+esc(d.name)+' ('+esc(d.module)+' / '+esc(d.entity_type)+')</option>';
    }).join('');
    var html='<div class="modal-overlay" data-wf-backdrop="true">'+
      '<div class="modal-box" style="max-width:480px">'+
      '<button class="modal-close" data-wf-action="close-modal">&times;</button>'+
      '<div class="modal-title">Start SLA Tracking</div>'+
      '<form data-wf-submit="start-sla">'+
        orgField+
        '<div class="form-group"><label>SLA Policy</label><select id="slaStartDef" required>'+
          (wfIsSuperAdmin?'<option value="">Select an organization first</option>':'')+optsHtml+'</select></div>'+
        '<div class="form-row">'+
          '<div class="form-group"><label>Entity Module</label>'+
            '<select id="slaStartMod"><option value="aria">ARIA</option><option value="sentinel">Sentinel</option><option value="grid">GRID</option><option value="bcm">BCM</option></select></div>'+
          '<div class="form-group"><label>Entity Type</label><input type="text" id="slaStartType" placeholder="e.g. incident, finding"></div>'+
        '</div>'+
        '<div class="form-group"><label>Entity ID (optional)</label><input type="number" id="slaStartId" placeholder="Record ID"></div>'+
        '<div style="margin-top:16px"><button type="submit" class="btn btn-primary" style="width:100%">Start Tracking</button></div>'+
      '</form></div></div>';
    document.getElementById('wfModalRoot').innerHTML=html;
  };

  window.slaSubmitStart=function(e){
    e.preventDefault();
    var body={
      definition_id:parseInt(document.getElementById('slaStartDef').value),
      entity_module:document.getElementById('slaStartMod').value,
      entity_type:document.getElementById('slaStartType').value,
      entity_id:parseInt(document.getElementById('slaStartId').value)||null
    };
    apiFetch('/api/sla/instances',{method:'POST',body:wfSelectedOrg(body)}).then(function(){
      wfCloseModal();loadSlaInstances();loadSlaStats();
      if(typeof showToast==='function') showToast('SLA tracking started');
    }).catch(function(){
      if(typeof showToast==='function') showToast('Failed to start SLA tracking','error');
    });
    return false;
  };

  window.wfOpenNewSla=function(){
    var html='<div class="modal-overlay" data-wf-backdrop="true">'+
      '<div class="modal-box" style="max-width:500px">'+
      '<button class="modal-close" data-wf-action="close-modal">&times;</button>'+
      '<div class="modal-title">New SLA Policy</div>'+
      '<form data-wf-submit="sla-policy">'+
        '<div class="form-group"><label>Policy Name</label><input type="text" id="slaName" required placeholder="e.g. High Priority Incident"></div>'+
        '<div class="form-row">'+
          '<div class="form-group"><label>Module</label>'+
            '<select id="slaModule"><option value="aria">ARIA</option><option value="sentinel">Sentinel</option><option value="grid">GRID</option><option value="bcm">BCM</option></select></div>'+
          '<div class="form-group"><label>Entity Type</label><input type="text" id="slaEntity" required placeholder="e.g. incident, finding"></div>'+
        '</div>'+
        '<div class="form-row">'+
          '<div class="form-group"><label>Response Time (h)</label><input type="number" id="slaResp" min="1" max="8760" placeholder="4"></div>'+
          '<div class="form-group"><label>Resolution Time (h)</label><input type="number" id="slaRes" min="1" max="8760" placeholder="24"></div>'+
        '</div>'+
        '<div class="form-row">'+
          '<div class="form-group"><label>Escalation Time (h)</label><input type="number" id="slaEsc" min="1" max="8760" placeholder="8"></div>'+
          '<div class="form-group"><label>Priority</label>'+
            '<select id="slaPri"><option value="low">Low</option><option value="normal" selected>Normal</option><option value="high">High</option><option value="critical">Critical</option></select></div>'+
        '</div>'+
        '<div style="margin-top:16px"><button type="submit" class="btn btn-primary" style="width:100%">Create SLA Policy</button></div>'+
      '</form></div></div>';
    document.getElementById('wfModalRoot').innerHTML=html;
  };

  window.wfSubmitSla=function(e){
    e.preventDefault();
    var resp=document.getElementById('slaResp').value;
    var res=document.getElementById('slaRes').value;
    var esc_h=document.getElementById('slaEsc').value;
    if(!resp&&!res){if(typeof showToast==='function') showToast('Set at least response or resolution time','error');return false;}
    var body={
      name:document.getElementById('slaName').value,
      module:document.getElementById('slaModule').value,
      entity_type:document.getElementById('slaEntity').value,
      response_hours:resp?parseInt(resp):null,
      resolution_hours:res?parseInt(res):null,
      escalation_hours:esc_h?parseInt(esc_h):null,
      priority:document.getElementById('slaPri').value
    };
    apiFetch('/api/sla/definitions',{method:'POST',body:body}).then(function(){
      wfCloseModal();loadSlaDefs();loadSlaStats();
      if(typeof showToast==='function') showToast('SLA policy created');
    }).catch(function(){
      if(typeof showToast==='function') showToast('Failed to create SLA policy','error');
    });
    return false;
  };

  // Breach Monitor
  window.slaRunBreachCheck=async function(){
    var el=document.getElementById('breachResults');
    el.innerHTML='<div style="text-align:center;padding:20px;color:var(--muted)"><div class="spinner" style="margin:0 auto"></div><div style="margin-top:8px;font-size:12px">Scanning all active SLAs…</div></div>';
    try{
      var r=await apiFetch('/api/sla/check-breaches',{method:'POST'});
      var total=r.response_breaches+r.resolution_breaches;
      if(total>0){
        el.innerHTML='<div class="breach-banner alert">'+
          '<svg viewBox="0 0 24 24" fill="none" stroke="var(--red)" stroke-width="2" width="24" height="24"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'+
          '<div><div style="font-weight:700;color:var(--red);font-size:14px">'+total+' New Breach'+(total>1?'es':'')+' Detected</div>'+
            '<div style="font-size:12px;color:var(--muted);margin-top:2px">Response: '+r.response_breaches+' &middot; Resolution: '+r.resolution_breaches+' &middot; Escalation due: '+r.escalation_due+'</div>'+
          '</div></div>';
      } else {
        el.innerHTML='<div class="breach-banner ok">'+
          '<svg viewBox="0 0 24 24" fill="none" stroke="var(--green-status)" stroke-width="2" width="24" height="24"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'+
          '<div><div style="font-weight:700;color:var(--green-status);font-size:14px">All Clear</div>'+
            '<div style="font-size:12px;color:var(--muted);margin-top:2px">No new breaches. Checked '+esc(r.checked_at||'just now')+'</div>'+
          '</div></div>';
      }
      loadBreachedList();loadSlaStats();loadStats();
    }catch(e){
      el.innerHTML='<div class="breach-banner alert"><div style="color:var(--red)">Failed to run breach scan</div></div>';
    }
  };

  async function loadBreachedList(){
    var body=document.getElementById('breachBody');
    body.innerHTML='<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--muted)"><div class="spinner" style="margin:0 auto"></div></td></tr>';
    try{
      var items=await apiFetch('/api/sla/instances?breached=1');
      if(!items.length){body.innerHTML='<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--muted)">No breached SLAs ✓</td></tr>';return;}
      body.innerHTML=items.map(function(i){
        var btHtml=i.breach_type?'<span class="badge badge-critical">'+esc(i.breach_type.toUpperCase())+'</span>':'<span class="badge badge-critical">BREACH</span>';
        var actHtml=i.status==='active'
          ?'<button class="btn btn-sm btn-primary" data-wf-action="sla-resolve" data-id="'+wfSafeId(i.id)+'">Resolve</button>'
          :'<span class="badge badge-draft">Closed</span>';
        return '<tr style="background:rgba(239,68,68,.04)">'+
          '<td style="font-weight:600;font-size:13px">'+esc(i.sla_name||'--')+'</td>'+
          '<td style="font-size:12px">'+entityLink(i.entity_module,i.entity_type,i.entity_id)+'</td>'+
          '<td style="text-align:center">'+btHtml+'</td>'+
          '<td style="font-size:12px;color:var(--muted)">'+timeAgo(i.started_at)+'</td>'+
          '<td style="text-align:center">'+statusBadge(i.status)+'</td>'+
          '<td style="text-align:center">'+actHtml+'</td></tr>';
      }).join('');
    }catch(e){
      body.innerHTML='<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--muted)">Failed to load breached SLAs</td></tr>';
    }
  }

  /* ════════════════════════════════════════════════════════════════════════
     NOTIFICATION TEMPLATES
     ════════════════════════════════════════════════════════════════════════ */
  async function loadComms(){
    var body=document.getElementById('commBody');
    body.innerHTML='<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--muted)"><div class="spinner" style="margin:0 auto"></div></td></tr>';
    try{
      var items=await apiFetch('/api/comm-templates');
      if(!items.length){
        body.innerHTML='<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--muted)">No notification templates yet — create one to start</td></tr>';
        return;
      }
      body.innerHTML=items.map(function(t){
        var bodyPreview=(t.body_template||'').slice(0,80).replace(/\n/g,' ')+(t.body_template&&t.body_template.length>80?'…':'');
        return '<tr>'+
          '<td style="font-weight:600;font-size:13px">'+esc(t.name)+'</td>'+
          '<td>'+statusBadge(t.category||'general')+'</td>'+
          '<td style="font-size:12px;color:var(--muted)">'+esc(t.module||'All')+'</td>'+
          '<td style="font-size:12px;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc(t.subject_template||'--')+'</td>'+
          '<td class="body-preview">'+esc(bodyPreview||'—')+'</td>'+
          '<td style="text-align:center;font-weight:600;font-size:12px">v'+esc(t.version||1)+'</td>'+
          '<td style="text-align:center">'+
            '<div style="display:flex;gap:4px;justify-content:center">'+
              '<button class="btn btn-sm btn-secondary" data-wf-action="preview-comm" data-id="'+wfSafeId(t.id)+'" title="Preview">Preview</button>'+
              (canAuthorWorkflow?'<button class="btn btn-sm btn-secondary" data-wf-action="edit-comm" data-id="'+wfSafeId(t.id)+'" title="Edit">Edit</button>':'')+
            '</div>'+
          '</td></tr>';
      }).join('');
    }catch(e){
      body.innerHTML='<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--muted)">Failed to load templates</td></tr>';
    }
  }

  window.wfOpenNewComm=function(){showCommModal(null);};
  window.wfEditComm=async function(tid){
    try{
      var items=await apiFetch('/api/comm-templates');
      var t=items.find(function(x){return x.id===tid;});
      if(t) showCommModal(t);
    }catch(e){if(typeof showToast==='function') showToast('Failed to load template','error');}
  };

  function showCommModal(existing){
    var isEdit=!!existing;
    var html='<div class="modal-overlay" data-wf-backdrop="true">'+
      '<div class="modal-box">'+
      '<button class="modal-close" data-wf-action="close-modal">&times;</button>'+
      '<div class="modal-title">'+(isEdit?'Edit':'New')+' Notification Template</div>'+
      '<form data-wf-submit="comm" data-id="'+wfSafeId(isEdit?existing.id:null)+'">'+
        '<div class="form-group"><label>Template Name</label>'+
          '<input type="text" id="commName" required value="'+esc(existing?existing.name:'')+'" placeholder="e.g. Breach Notification"></div>'+
        '<div class="form-row">'+
          '<div class="form-group"><label>Category</label>'+
            '<select id="commCat">'+
              ['notification','escalation','reminder','report','general'].map(function(c){
                return '<option value="'+c+'"'+(existing&&existing.category===c?' selected':'')+'>'+esc(c.charAt(0).toUpperCase()+c.slice(1))+'</option>';
              }).join('')+
            '</select></div>'+
          '<div class="form-group"><label>Module</label>'+
            '<select id="commMod">'+
              '<option value=""'+(existing&&!existing.module?' selected':'')+'>All Modules</option>'+
              ['aria','sentinel','grid','bcm'].map(function(m){
                return '<option value="'+m+'"'+(existing&&existing.module===m?' selected':'')+'>'+m.toUpperCase()+'</option>';
              }).join('')+
            '</select></div>'+
        '</div>'+
        '<div class="form-group"><label>Subject Template</label>'+
          '<input type="text" id="commSubj" value="'+esc(existing?existing.subject_template:'')+'" placeholder="e.g. Action Required: {{item_name}}"></div>'+
        '<div class="form-group"><label>Body Template</label>'+
          '<textarea id="commBodyTpl" rows="6" placeholder="Use {{variable_name}} for placeholders…">'+esc(existing?existing.body_template:'')+'</textarea></div>'+
        '<div style="font-size:11px;color:var(--muted);margin-bottom:16px">Variables: <code>{{user_name}}</code> <code>{{item_name}}</code> <code>{{module}}</code> <code>{{due_date}}</code> <code>{{link}}</code></div>'+
        '<div style="display:flex;gap:8px">'+
          '<button type="submit" class="btn btn-primary" style="flex:1">'+(isEdit?'Save Changes':'Create Template')+'</button>'+
          (isEdit?'<button type="button" class="btn btn-secondary" data-wf-action="preview-comm" data-id="'+wfSafeId(existing.id)+'">Preview</button>':'')+
        '</div>'+
      '</form></div></div>';
    document.getElementById('wfModalRoot').innerHTML=html;
  }

  window.wfSubmitComm=function(e, tid){
    e.preventDefault();
    var body={
      name:document.getElementById('commName').value,
      category:document.getElementById('commCat').value,
      module:document.getElementById('commMod').value,
      subject_template:document.getElementById('commSubj').value,
      body_template:document.getElementById('commBodyTpl').value,
      variables:['user_name','item_name','module','due_date','link']
    };
    var url=tid?'/api/comm-templates/'+tid:'/api/comm-templates';
    var method=tid?'PUT':'POST';
    apiFetch(url,{method:method,body:body}).then(function(){
      wfCloseModal();loadComms();
      if(typeof showToast==='function') showToast(tid?'Template updated':'Template created');
    }).catch(function(){
      if(typeof showToast==='function') showToast('Failed to save template','error');
    });
    return false;
  };

  window.wfPreviewComm=async function(tid){
    try{
      var data=await apiFetch('/api/comm-templates/'+tid+'/render',{method:'POST',body:{variables:{
        user_name:'Jane Smith',item_name:'Sample Record',module:'ARIA',due_date:'2026-06-01',link:'/workflows'
      }}});
      var html='<div class="modal-overlay" data-wf-backdrop="true">'+
        '<div class="modal-box" style="max-width:520px">'+
        '<button class="modal-close" data-wf-action="close-modal">&times;</button>'+
        '<div class="modal-title">Template Preview</div>'+
        '<div style="margin-bottom:12px"><div style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:4px">Subject</div>'+
          '<div style="font-size:14px;font-weight:600;color:var(--text);padding:10px 14px;background:var(--surface2);border-radius:var(--radius)">'+esc(data.subject||'(no subject)')+'</div></div>'+
        '<div><div style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:4px">Body</div>'+
          '<div style="font-size:13px;color:var(--text);padding:14px;background:var(--surface2);border-radius:var(--radius);line-height:1.7;white-space:pre-wrap;max-height:300px;overflow-y:auto">'+esc(data.body||'(no body)')+'</div></div>'+
        '<div style="margin-top:12px;font-size:11px;color:var(--muted);text-align:center">Rendered with sample data · actual values will vary</div>'+
      '</div></div>';
      document.getElementById('wfModalRoot').innerHTML=html;
    }catch(e){
      if(typeof showToast==='function') showToast('Failed to preview template','error');
    }
  };

  /* ════════════════════════════════════════════════════════════════════════
     INIT
     ════════════════════════════════════════════════════════════════════════ */
  loadStats().then(function(){
    var url=new URL(window.location.href);
    var instance=url.searchParams.get('instance');
    if(instance!==null){
      url.searchParams.delete('instance');
      history.replaceState(null,'',url.pathname+url.search+url.hash);
      if(/^[1-9][0-9]*$/.test(instance)) wfOpenInstance(Number(instance));
    }
  });
  loadTemplates();

  // Close modal/drawer with Escape
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'){
      wfCloseModal();
      wfCloseDrawer();
    }
  });

})();
