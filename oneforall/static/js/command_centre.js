// Command Centre (moved from its template for strict script policy).
(function(){
  // ── Helpers ──
  const modColors = {aria:'#7c3aed',grid:'#1a6b3a',bcm:'#d97706',sentinel:'#0891b2',erm:'#dc3c50',orm:'#e67828'};
  const modNames  = {aria:'Governance',grid:'Audit',bcm:'Resilience',sentinel:'Privacy',erm:'Enterprise Risk',orm:'Operations Risk'};

  // Escaping for text and for attribute values (quotes too) injected via innerHTML.
  function esc(s){
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function timeAgoShort(ts){
    if(!ts) return '';
    const d=new Date(ts.includes('T')?ts:ts+'Z');
    const s=Math.floor((Date.now()-d.getTime())/1000);
    if(s<60) return 'just now';
    if(s<3600) return Math.floor(s/60)+' min ago';
    if(s<86400) return Math.floor(s/3600)+' hour'+(Math.floor(s/3600)>1?'s':'')+' ago';
    if(s<172800) return 'Yesterday';
    return Math.floor(s/86400)+' days ago';
  }

  function fmtDate(ts){
    if(!ts) return '—';
    const d=new Date(ts.includes('T')?ts:ts+'Z');
    return d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
  }

  // ── "Last updated" tracker ──
  function setLastUpdated(isoTs){
    const el = document.getElementById('ccLastUpdated');
    if(!el) return;
    el.textContent = isoTs ? timeAgoShort(isoTs) : 'just now';
  }

  // ── What a number says when it has no value ──
  // A figure is shown only when the server measured it. When it could not be read, or there is nothing to measure, the card
  // shows a dash and says which: it never shows a zero or a sample in its place.
  let readFailed = false;
  function metricOf(d, key){ return (d && d.metrics && d.metrics[key]) || null; }
  function hasValue(m){ return !!m && (m.state === 'measured' || m.state === 'partial' || m.state === 'stale') && m.value !== null && m.value !== undefined; }
  function stateWords(m){
    if(!m) return readFailed ? 'Unavailable just now. This is not a count of zero.' : 'Not available to you.';
    if(m.state === 'unavailable') return 'Unavailable just now. This is not a count of zero.';
    if(m.state === 'not_measured') return 'Not measured. ' + (m.note || '');
    if(m.state === 'partial') return 'Partial: ' + ((m.sources && m.sources.missing) || ['a source']).join(', ') + ' could not be read, so it is not counted.';
    if(m.state === 'stale') return 'Out of date: as of ' + (m.as_of || 'an earlier time') + '.';
    return '';
  }
  function put(id, m, suffix){
    const el = document.getElementById(id);
    if(!el) return;
    el.textContent = hasValue(m) ? String(m.value) + (suffix || '') : '\u2014';
    el.setAttribute('data-state', m ? m.state : (readFailed ? 'unavailable' : 'hidden'));
    const words = ((m && m.definition) ? m.definition + ' ' : '') + stateWords(m);
    if(m && m.state === 'measured') el.setAttribute('title', (m.definition || '').trim()); else el.setAttribute('title', words.trim());
    if(!hasValue(m)) el.style.color = 'var(--muted)';
  }
  function colour(id, cardId, value, c){
    const el = document.getElementById(id);
    if(el) el.style.color = c;
    const card = document.getElementById(cardId);
    if(card) card.style.setProperty('--status-color', c);
  }

  // ── Greeting: daypart + date (client-side -- the server is UTC and
  // would greet half the world with the wrong daypart) ──
  (function(){
    var h = new Date().getHours();
    var word = h < 12 ? 'Good morning' : (h < 17 ? 'Good afternoon' : 'Good evening');
    var g = document.getElementById('ccGreeting');
    if(g) g.textContent = g.textContent.replace('Welcome back', word);
    var t = document.getElementById('ccToday');
    if(t) t.textContent = new Date().toLocaleDateString(undefined,
        {weekday:'short', day:'numeric', month:'short', year:'numeric'});
  })();

  // ── Populate stats ──
  function populateStats(d){
    const compliance = metricOf(d, 'cc.controls_implemented');
    put('ccCompliancePct', compliance, '%');
    document.getElementById('ccCompliancePct').style.color = '';
    const pct = hasValue(compliance) ? Math.max(0, Math.min(100, Number(compliance.value) || 0)) : 0;
    document.getElementById('ccComplianceBar').style.width = pct + '%';
    const complianceCard = document.getElementById('ccComplianceCard');
    if(complianceCard) complianceCard.style.setProperty('--compliance-pct', pct + '%');
    const ring = document.getElementById('ccHeroRingPct');
    if(ring) ring.textContent = hasValue(compliance) ? pct + '%' : 'n/a';
    const trend = document.getElementById('ccComplianceTrend');
    if(trend){
      const x = compliance && compliance.detail;
      trend.querySelector('span').textContent = (hasValue(compliance) && x)
        ? x.implemented + ' of ' + x.total + ' controls implemented' + (x.approved_not_implemented ? ', ' + x.approved_not_implemented + ' approved and not yet implemented' : '')
        : stateWords(compliance);
    }

    const fw = metricOf(d, 'cc.active_frameworks');
    put('ccActiveProjects', fw);
    put('ccActiveFrameworks', fw);
    const names = document.getElementById('ccProjectsList');
    if(names) names.textContent = hasValue(fw) ? (((fw.detail && fw.detail.names) || []).join(' · ') || 'No framework is active') : stateWords(fw);
    const navProj = document.getElementById('sideNavProjects');
    if(navProj) navProj.textContent = hasValue(fw) ? fw.value : '';

    const overdue = metricOf(d, 'cc.overdue_actions');
    put('ccOverdueCount', overdue);
    const overdueTrend = document.getElementById('ccOverdueTrend');
    if(overdueTrend) overdueTrend.querySelector('span').textContent = (overdue && overdue.state === 'measured') ? 'Tasks past due and breached service clocks' : stateWords(overdue);

    const crit = metricOf(d, 'cc.critical_high_risks');
    put('ccErmCritHigh', crit);
    if(hasValue(crit)) colour('ccErmCritHigh', 'ccErmCritCard', crit.value, crit.value > 0 ? 'var(--red)' : 'var(--green-status)');

    const evidence = metricOf(d, 'cc.evidence_files');
    put('ccEvidenceCount', evidence);
    const navEv = document.getElementById('sideNavEvidence');
    if(navEv) navEv.textContent = hasValue(evidence) ? evidence.value : '';

    // Sentinel open breaches
    const breaches = metricOf(d, 'cc.open_breaches');
    put('ccSentinelBreaches', breaches);
    const sentSub = document.getElementById('ccSentinelSub');
    if(hasValue(breaches)){
      const worst = breaches.detail && breaches.detail.worst;
      const c = breaches.value > 0 ? (worst === 'critical' ? 'var(--red)' : 'var(--amber)') : 'var(--green-status)';
      colour('ccSentinelBreaches', 'ccSentinelCard', breaches.value, c);
      if(sentSub) sentSub.textContent = breaches.value === 0 ? 'No high or critical breaches open' : (breaches.value === 1 ? '1 active breach' : breaches.value + ' active breaches');
    } else if(sentSub){
      sentSub.textContent = stateWords(breaches);
    }

    const appetite = metricOf(d, 'cc.appetite_breaches');
    put('ccErmBreaches', appetite);
    if(hasValue(appetite)) colour('ccErmBreaches', 'ccErmCard', appetite.value, appetite.value > 0 ? 'var(--red)' : 'var(--green-status)');

    const orm = metricOf(d, 'cc.orm_open_events');
    put('ccOrmEvents', orm);
    if(hasValue(orm)) colour('ccOrmEvents', 'ccOrmCard', orm.value, orm.value > 5 ? 'var(--amber)' : (orm.value > 0 ? 'var(--muted)' : 'var(--green-status)'));

    const bcm = metricOf(d, 'cc.bcm_active_incidents');
    put('ccBcmIncidents', bcm);
    if(hasValue(bcm)) colour('ccBcmIncidents', 'ccBcmCard', bcm.value, bcm.value > 0 ? 'var(--red)' : 'var(--green-status)');

    const grid = metricOf(d, 'cc.grid_open_audit_controls');
    put('ccGridFindings', grid);
    if(hasValue(grid)) colour('ccGridFindings', 'ccGridFindCard', grid.value, grid.value > 10 ? 'var(--red)' : (grid.value > 0 ? 'var(--amber)' : 'var(--green-status)'));

    const reviews = metricOf(d, 'cc.upcoming_reviews');
    put('ccUpcomingReviews', reviews);
    if(hasValue(reviews)) colour('ccUpcomingReviews', 'ccReviewsCard', reviews.value, reviews.value > 0 ? 'var(--amber)' : 'var(--green-status)');

    // Breach notification countdown alerts
    populateBreachAlerts(d.breach_alerts || []);

    // ── Attention summary: only claims "all clear" when everything it rests on was read ──
    const att = document.getElementById('ccAttention');
    if(att){
      const parts = [crit, overdue];
      const unread = parts.filter(m => !hasValue(m) || (m && m.state === 'partial'));
      const critHigh = hasValue(crit) ? crit.value : 0;
      const late = hasValue(overdue) ? overdue.value : 0;
      const bits = [];
      if(critHigh > 0) bits.push(critHigh + ' critical/high risk' + (critHigh > 1 ? 's' : ''));
      if(late > 0) bits.push(late + ' overdue item' + (late > 1 ? 's' : ''));
      if(bits.length){
        att.textContent = bits.join(' and ') + ' need' + (critHigh + late === 1 ? 's' : '') + ' your attention' + (unread.length ? ', and some figures could not be read' : '');
      } else if(unread.length){
        att.textContent = 'Some figures could not be read just now, so this is not an all clear.';
      } else {
        att.textContent = 'All clear. Nothing urgent today.';
      }
    }
  }

  // ── Breach Notification Countdown ──
  var _breachTimerInterval = null;

  function populateBreachAlerts(alerts){
    var wrap = document.getElementById('ccBreachAlert');
    var list = document.getElementById('ccBreachAlertList');
    var badge = document.getElementById('ccBreachAlertCount');
    if(!wrap || !list) return;

    if(!alerts || !alerts.length){
      wrap.style.display = 'none';
      if(_breachTimerInterval){ clearInterval(_breachTimerInterval); _breachTimerInterval = null; }
      return;
    }

    wrap.style.display = '';
    badge.textContent = alerts.length;

    var html = '';
    for(var i = 0; i < alerts.length; i++){
      var a = alerts[i];
      var sevCls = a.severity === 'critical' ? 'ba-sev-critical' : a.severity === 'high' ? 'ba-sev-high' : 'ba-sev-medium';
      var regLabel = esc(a.regulation) + ' / ' + esc(a.authority);
      var hoursLabel = a.breach_hours ? a.breach_hours + 'h deadline' : 'ASAP';

      html += '<div class="breach-alert-row" data-cc-href="/sentinel/breaches" title="Open in Sentinel">';
      html += '<span class="ba-sev ' + sevCls + '">' + esc(a.severity) + '</span>';
      html += '<div class="ba-info">';
      html += '<div class="ba-info-title">' + esc(a.ref) + ': ' + esc(a.title) + '</div>';
      html += '<div class="ba-info-sub">' + regLabel + ' (' + hoursLabel + ')</div>';
      html += '</div>';

      if(a.authority_notified){
        html += '<div class="ba-countdown" style="display:flex;align-items:center;gap:8px">';
        html += '<span class="ba-notified-badge">Authority notified</span>';
        html += '</div>';
      } else {
        html += '<div class="ba-countdown">';
        html += '<div class="ba-countdown-time" data-breach-deadline="' + esc(a.deadline) + '"></div>';
        html += '<div class="ba-countdown-label">remaining to notify</div>';
        html += '</div>';
      }

      html += '</div>';
    }

    list.innerHTML = html;
    updateBreachCountdowns();

    if(_breachTimerInterval) clearInterval(_breachTimerInterval);
    _breachTimerInterval = setInterval(updateBreachCountdowns, 1000);
  }

  function updateBreachCountdowns(){
    var els = document.querySelectorAll('[data-breach-deadline]');
    var now = Date.now();
    for(var i = 0; i < els.length; i++){
      var el = els[i];
      var dl = el.getAttribute('data-breach-deadline');
      var deadlineMs = new Date(dl.includes('T') ? dl : dl + 'Z').getTime();
      var diffMs = deadlineMs - now;

      if(diffMs <= 0){
        var overMs = Math.abs(diffMs);
        var overH = Math.floor(overMs / 3600000);
        var overM = Math.floor((overMs % 3600000) / 60000);
        el.textContent = 'OVERDUE by ' + overH + 'h ' + overM + 'm';
        el.className = 'ba-countdown-time ba-countdown-expired';
        el.closest('.ba-countdown').querySelector('.ba-countdown-label').textContent = 'deadline passed';
      } else {
        var totalSec = Math.floor(diffMs / 1000);
        var days = Math.floor(totalSec / 86400);
        var hrs  = Math.floor((totalSec % 86400) / 3600);
        var mins = Math.floor((totalSec % 3600) / 60);
        var secs = totalSec % 60;

        var timeStr = '';
        if(days > 0) timeStr = days + 'd ' + hrs + 'h ' + mins + 'm';
        else if(hrs > 0) timeStr = hrs + 'h ' + mins + 'm ' + secs + 's';
        else timeStr = mins + 'm ' + secs + 's';

        el.textContent = timeStr;

        var totalH = diffMs / 3600000;
        if(totalH < 6) el.className = 'ba-countdown-time ba-countdown-urgent';
        else if(totalH < 24) el.className = 'ba-countdown-time ba-countdown-warning';
        else el.className = 'ba-countdown-time ba-countdown-ok';
      }
    }
  }

  // ── Module Health ──
  const MODULE_LINKS = {aria:'/aria/',grid:'/grid/',bcm:'/bcm/',sentinel:'/sentinel/',erm:'/erm/',orm:'/orm/'};
  function populateModuleHealth(items){
    const el = document.getElementById('ccModuleHealth');
    if(!items || !items.length){
      el.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:12px">' + (readFailed ? 'Not read just now' : 'No module data') + '</div>';
      return;
    }
    el.innerHTML = items.map(m => {
      const detail = m.detail || {};
      const key = detail.module;
      const name = detail.name || key || '';
      const safeColor = modColors[key] || 'var(--muted)';
      const link = MODULE_LINKS[key] || '#';
      const measured = hasValue(m);
      const pct = measured ? (parseInt(m.value, 10) || 0) : 0;
      const pctColor = !measured ? 'var(--muted)' : pct >= 80 ? 'var(--green-status)' : pct >= 60 ? 'var(--amber)' : 'var(--red)';
      const words = measured ? esc(name) + ': ' + pct + '% of ' + (detail.of || '') + ' records are in their good state' : esc(name) + ': ' + esc(stateWords(m));
      return `<div class="module-health-item" style="cursor:pointer" title="${words}"
                   data-cc-href="${esc(link)}">
        <div class="mh-dot" style="background:${safeColor}"></div>
        <div class="mh-name">${esc(name)}</div>
        <div class="mh-pct" style="color:${pctColor}">${measured ? pct + '%' : 'n/a'}</div>
        <div class="mh-bar"><div class="mh-bar-fill" style="width:${pct}%;background:${safeColor}"></div></div>
        ${measured ? '' : '<span class="sr-only">' + esc(stateWords(m)) + '</span>'}
      </div>`;
    }).join('');
  }

  // ── Risk Register Widget ──
  function populateRiskWidget(risks, workflows){
    const levels = (risks && risks.detail) || {};
    const known = hasValue(risks);
    const text = (n, word) => (known ? (n || 0) : 'n/a') + ' ' + word;
    const rEl = document.getElementById('ccRiskCrit'); if(rEl) rEl.textContent = text(levels.critical, 'Critical');
    const hEl = document.getElementById('ccRiskHigh'); if(hEl) hEl.textContent = text(levels.high, 'High');
    const mEl = document.getElementById('ccRiskMed');  if(mEl) mEl.textContent = text(levels.medium, 'Medium');
    put('ccWorkflowActive', workflows);
  }

  // ── SLA Donut ──
  function populateSLA(m){
    const detail = (m && m.detail) || {};
    const known = !!m && (m.state === 'measured' || m.state === 'not_measured');
    const met = known ? Math.max(0, Number(detail.met) || 0) : 0;
    const breached = known ? Math.max(0, Number(detail.breached) || 0) : 0;
    const atRisk = known ? Math.max(0, Number(detail.at_risk) || 0) : 0;
    const resolved = met + breached;
    const pct = resolved ? Math.round(met / resolved * 100) : 0;
    const circ = 2 * Math.PI * 56;
    const onTimeArc = document.getElementById('ccSlaArc');
    const breachedArc = document.getElementById('ccSlaBreachArc');
    onTimeArc.querySelector('title').textContent = 'Met SLA: ' + (known ? met : 'not read');
    breachedArc.querySelector('title').textContent = 'Breached SLA: ' + (known ? breached : 'not read');
    const caption = document.getElementById('ccSlaCaption');
    const pctEl = document.getElementById('ccSlaPct');
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    function paint(){
      onTimeArc.style.visibility = met ? 'visible' : 'hidden';
      breachedArc.style.visibility = breached ? 'visible' : 'hidden';
      onTimeArc.setAttribute('stroke-dashoffset', String(circ * (1 - met / (resolved || 1))));
      breachedArc.setAttribute('transform', 'rotate(' + (-90 + 360 * met / (resolved || 1)) + ' 70 70)');
      breachedArc.setAttribute('stroke-dashoffset', String(circ * (1 - breached / (resolved || 1))));
    }
    if(reduceMotion) paint();
    else requestAnimationFrame(() => requestAnimationFrame(paint));
    caption.textContent = !known ? (m ? 'NOT READ' : 'NOT AVAILABLE') : (resolved ? 'RESOLVED ON TIME' : 'NO RESOLVED SLAs');
    if(pctEl._frame) cancelAnimationFrame(pctEl._frame);
    if(!resolved || reduceMotion){
      pctEl.textContent = resolved ? pct + '%' : String.fromCharCode(8212);
    } else {
      const from = Number.parseInt(pctEl.textContent, 10) || 0;
      const began = performance.now();
      function tick(now){
        const t = Math.min(1, (now - began) / 850);
        const eased = 1 - Math.pow(1 - t, 3);
        pctEl.textContent = Math.round(from + (pct - from) * eased) + '%';
        if(t < 1) pctEl._frame = requestAnimationFrame(tick);
      }
      pctEl._frame = requestAnimationFrame(tick);
    }
    document.getElementById('ccSlaMet').textContent = known ? met : 'n/a';
    document.getElementById('ccSlaRisk').textContent = known ? atRisk : 'n/a';
    document.getElementById('ccSlaBreach').textContent = known ? breached : 'n/a';
  }

  // ── Recent Activity Timeline ──
  function populateActivity(items){
    const el = document.getElementById('ccRecentActivity');
    if(!items || !items.length){
      el.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:12px">' + (readFailed ? 'Not read just now' : 'No recent activity') + '</div>';
      return;
    }
    el.innerHTML = items.map((a, i) => {
      const color = modColors[a.module] || 'var(--muted)';
      const isLast = i === items.length - 1;
      return `<div class="tl-item">
        <div class="tl-col">
          <div class="tl-dot" style="box-shadow:0 0 0 2px ${color};border-color:var(--surface)"></div>
          ${isLast ? '' : '<div class="tl-line"></div>'}
        </div>
        <div class="tl-content">
          <div class="tl-name">${esc(a.text)}</div>
          <div class="tl-date">${esc(a.time || timeAgoShort(a.created_at))} · ${esc(modNames[a.module] || a.module)}</div>
        </div>
      </div>`;
    }).join('');
  }

  // ── Overdue Table ──
  let allOverdueItems = [];
  let overdueMetric = null;

  function renderOverdueTable(items){
    const body = document.getElementById('ccOverdueBody');
    if(!items || !items.length){
      const unread = readFailed || (overdueMetric && !hasValue(overdueMetric));
      body.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:32px;color:var(--muted)">' +
        (unread ? 'The overdue items could not be read just now. This is not an empty list.' : 'No overdue items') + '</td></tr>';
      return;
    }
    body.innerHTML = items.map(row => {
      const slaBadge = row.sla === 'breached' ? 'badge-critical' : row.sla === 'at_risk' ? 'badge-high' : 'badge-low';
      const slaLabel = row.sla === 'breached' ? 'BREACHED' : row.sla === 'at_risk' ? 'AT RISK' : 'ON TIME';
      const priBadge = row.priority === 'critical' ? 'badge-critical' : row.priority === 'high' ? 'badge-high' : row.priority === 'medium' ? 'badge-medium' : 'badge-low';
      return `<tr>
        <td><span class="item-id">${esc(row.id)}</span> ${esc(row.item)}</td>
        <td><span style="display:inline-flex;align-items:center;gap:6px"><span style="width:8px;height:8px;border-radius:50%;background:${modColors[row.module]||'var(--muted)'}"></span>${esc(modNames[row.module]||row.module)}</span></td>
        <td>${esc(row.assigned || '—')}</td>
        <td style="font-family:var(--mono);font-size:12px">${fmtDate(row.due)}</td>
        <td><span class="badge ${slaBadge}">${slaLabel}</span></td>
        <td><span class="badge ${priBadge}">${esc((row.priority||'').toUpperCase())}</span></td>
      </tr>`;
    }).join('');
  }

  window.filterOverdue = function(mod, chip){
    document.querySelectorAll('#ccModuleFilters .filter-chip').forEach(c=>c.classList.remove('active'));
    chip.classList.add('active');
    if(mod === 'all'){
      renderOverdueTable(allOverdueItems);
    } else {
      renderOverdueTable(allOverdueItems.filter(r=>r.module===mod));
    }
  };

  // ── Fetch data from the API; when it fails, say so (never a sample) ──
  function showUnavailable(on){
    const banner = document.getElementById('ccUnavailable');
    if(banner) banner.style.display = on ? 'flex' : 'none';
  }
  async function loadDashboard(){
    let data = null;
    readFailed = false;
    try {
      const resp = await fetch('/api/command-centre/stats');
      if(resp.ok) data = await resp.json();
    } catch(e){}
    if(!data || !data.metrics){
      readFailed = true;
      showUnavailable(true);
      overdueMetric = null;
      populateStats({metrics: {}});
      populateModuleHealth([]);
      populateSLA(null);
      populateActivity(null);
      populateRiskWidget(null, null);
      allOverdueItems = [];
      renderOverdueTable([]);
      const att = document.getElementById('ccAttention');
      if(att) att.textContent = 'The figures could not be read just now. This is not an all clear.';
      const updated = document.getElementById('ccLastUpdated');
      if(updated) updated.textContent = 'not read';
      loadBriefing();
      return;
    }
    showUnavailable(false);
    const d = data;
    overdueMetric = metricOf(d, 'cc.overdue_actions');
    populateStats(d);
    populateModuleHealth(d.health);
    populateSLA(metricOf(d, 'cc.sla_on_time'));
    populateActivity(d.activity);
    populateRiskWidget(metricOf(d, 'cc.open_risks'), metricOf(d, 'cc.workflows_active'));
    allOverdueItems = d.overdue_items || [];
    renderOverdueTable(allOverdueItems);
    setLastUpdated(d.fetched_at);
    loadBriefing();
  }
  const retry = document.getElementById('ccRetry');
  if(retry) retry.addEventListener('click', loadDashboard);

  // ── Today's Briefing ──
  async function loadBriefing(){
    try {
      const resp = await fetch('/api/advisories/today');
      if(!resp.ok) return;
      const data = await resp.json();
      const items = data.advisories || [];
      const unacked = items.filter(function(a){ return !a.acknowledged_by; });
      if(unacked.length === 0){ document.getElementById('briefingStrip').style.display = 'none'; return; }
      document.getElementById('briefingStrip').style.display = '';
      var html = unacked.map(function(a){
        var dotColor = a.severity === 'high' ? '#dc2626' : a.severity === 'medium' ? '#d97706' : '#6366f1';
        var link = a.link ? '<a href="'+esc(a.link)+'" style="color:var(--accent);text-decoration:none;margin-left:8px;font-weight:600">Open</a>' : '';
        return '<div style="display:flex;align-items:flex-start;gap:10px;padding:8px 0;border-bottom:1px solid var(--border)">'+
          '<span style="width:8px;height:8px;border-radius:50%;background:'+dotColor+';flex-shrink:0;margin-top:5px"></span>'+
          '<div style="flex:1;font-size:13px">'+
          '<strong>'+esc(a.title)+'</strong>'+
          (a.detail ? '<br><span style="color:var(--muted)">'+esc(a.detail)+'</span>' : '')+
          (a.ai_narrative ? '<br><span style="font-size:12px;color:var(--text-mid);font-style:italic">'+esc(a.ai_narrative)+'</span>' : '')+
          '</div>'+
          '<div style="display:flex;gap:6px;align-items:center;flex-shrink:0">'+link+
          '<button class="btn btn-sm btn-secondary" data-cc-ack="'+Number(a.id)+'" style="padding:3px 10px;font-size:11px">✓</button></div></div>';
      }).join('');
      document.getElementById('briefingItems').innerHTML = html;
    } catch(e){}
  }

  window.ackAdvisory = async function(aid, btn){
    btn.disabled = true;
    btn.textContent = '...';
    try {
      await ApiClient.request('/api/advisories/'+aid+'/ack', { method: 'POST', actionId: 'command_centre.advisory.ack' });
      btn.parentElement.parentElement.style.opacity = '0.3';
      btn.textContent = '✓';
    } catch(e){
      btn.disabled = false;
      btn.textContent = '✓';
      if(typeof showToast==='function')showToast(e.detail || 'Failed to acknowledge','error');
    }
  };

  // ── Init ──
  loadDashboard();
  loadPredictiveRisk();

  // Refresh dashboard every 5 minutes, predictions every 30 minutes
  setInterval(loadDashboard, 300000);
  setInterval(loadPredictiveRisk, 1800000);
})();

// ── Predictive Risk Intelligence ──────────────────────────────────────────────
var _prData = null;

var PR_COLORS = {
  low:      {hex:'#16a34a', css:'var(--good,#16a34a)',  badge:'badge-complete'},
  medium:   {hex:'#d97706', css:'var(--amber,#d97706)', badge:'badge-high'},
  high:     {hex:'#dc2626', css:'var(--red,#dc2626)',   badge:'badge-critical'},
  critical: {hex:'#7c1220', css:'#7c1220',              badge:'badge-critical'},
};

var _prExpanded = false;

function togglePredictiveRisk() {
  _prExpanded = !_prExpanded;
  var body = document.getElementById('prBody');
  var chevron = document.getElementById('prChevron');
  var summary = document.getElementById('prSummary');
  if(body) body.style.display = _prExpanded ? 'block' : 'none';
  if(chevron) chevron.style.transform = _prExpanded ? 'rotate(180deg)' : '';
  // Render body content on first expand
  if(_prExpanded && _prData && body && body.innerHTML.includes('spinner')) {
    var col = PR_COLORS[_prData.risk_level] || PR_COLORS.low;
    body.innerHTML = _renderPredictivePanel(_prData, col);
  }
}

async function loadPredictiveRisk(force) {
  var panel = document.getElementById('prPanel');
  var body  = document.getElementById('prBody');
  var btn   = document.getElementById('prRefreshBtn');
  if(!panel) return;

  if(force && btn) { btn.innerHTML = '…'; btn.disabled = true; }

  try {
    var url = '/api/predictive-risk' + (force ? '?force=1' : '');
    var d = await ApiClient.request(url, { actionId: 'command_centre.predictive_risk.load' });
    _prData = d;

    var col = PR_COLORS[d.risk_level] || PR_COLORS.low;

    // Show panel and expose its status colour
    panel.style.display = 'block';
    panel.style.setProperty('--pr-color', col.hex);

    // Badge in bar
    var badge = document.getElementById('prBadge');
    if(badge){ badge.className='badge '+col.badge; badge.textContent=(d.risk_level||'low').toUpperCase(); badge.style.display='inline-block'; }

    // Inline summary (collapsed view)
    var sumDelta = document.getElementById('prSumDelta');
    if(sumDelta) sumDelta.textContent = '+' + (d.delta_p||0) + '%';
    var sumDomains = document.getElementById('prSumDomains');
    if(sumDomains) sumDomains.textContent =
      'Cyber ' + (d.delta_cyber||0) + '%  ·  Operational ' + (d.delta_operational||0) + '%  ·  Compliance ' + (d.delta_compliance||0) + '%';

    // ERM chip
    var ermBadge = document.getElementById('prErmBadge');
    if(ermBadge) ermBadge.style.display = d.erm_risk_id ? 'inline-block' : 'none';

    // Age
    var age = document.getElementById('prAge');
    if(age) age.textContent = d.cached ? _prTimeAgo(d.computed_at) : 'just now';

    // Acknowledge button
    var ackBtn = document.getElementById('prAckBtn');
    if(ackBtn) ackBtn.style.display = (d.risk_level==='high'||d.risk_level==='critical')&&!d.acknowledged_at ? 'inline-flex' : 'none';

    // If already expanded (e.g. forced refresh), re-render body
    if(_prExpanded && body) body.innerHTML = _renderPredictivePanel(d, col);

    // Auto-expand if high or critical
    if(!_prExpanded && (d.risk_level==='high'||d.risk_level==='critical')) togglePredictiveRisk();

  } catch(e) {
    if(panel) panel.style.display = 'block';
    console.error('Predictive risk error', e);
  } finally {
    if(btn){ btn.innerHTML = '&#8635;'; btn.disabled = false; }
  }
}

function _renderPredictivePanel(d, col) {
  var dp = Number(d.delta_p);
  if(!Number.isFinite(dp)) dp = 0;
  var hist = d.history || [];
  var contribs = d.signal_contributions || {};
  var tel = d.telemetry || {};

  var sigLabels = {
    breaches:          'Sentinel Breaches',
    non_conformances:  'GRID NCs',
    bcm_staleness:     'BCM Staleness',
    orm_recurring:     'ORM Recurring Events',
    compliance_gap:    'ARIA Compliance Gap',
    appetite_breaches: 'ERM Appetite Breaches',
  };

  // ── Gauge arc (SVG) ──
  var circ = 251.2; // 2π×40
  var arc  = (Math.max(0, Math.min(100, Number(dp) || 0)) / 100) * circ;
  var gaugeColor = col.hex;
  var gaugeSvg =
    '<svg viewBox="0 0 100 60" role="img" aria-label="Predicted risk increase: '+dp+' percent" style="width:130px;height:78px;display:block;margin:0 auto;overflow:visible">' +
    '<circle cx="50" cy="50" r="40" fill="none" stroke="var(--surface3)" stroke-width="10" ' +
    'stroke-dasharray="' + (circ*0.5).toFixed(1) + ' ' + circ + '" transform="rotate(180 50 50)"/>' +
    '<circle class="premium-gauge-arc" cx="50" cy="50" r="40" fill="none" stroke="' + gaugeColor + '" stroke-width="10" ' +
    'stroke-linecap="round" ' +
    'stroke-dasharray="' + (arc*0.5).toFixed(1) + ' ' + circ + '" transform="rotate(180 50 50)" ' +
    'style="filter:drop-shadow(0 3px 6px rgba(var(--accent-rgb),.2))"><title>Predicted risk increase: '+dp+'%</title></circle>' +
    '<text x="50" y="46" text-anchor="middle" fill="' + gaugeColor + '" font-size="16" font-weight="800" font-family="Manrope,sans-serif">+' + dp + '%</text>' +
    '<text x="50" y="56" text-anchor="middle" fill="var(--muted)" font-size="7" font-family="Manrope,sans-serif">ΔP RISK</text>' +
    '</svg>';

  // ── Domain bars ──
  var domains = [
    {label:'Cyber',       val:d.delta_cyber||0,       color:'var(--red,#dc2626)'},
    {label:'Operational', val:d.delta_operational||0,  color:'var(--amber,#d97706)'},
    {label:'Compliance',  val:d.delta_compliance||0,   color:'var(--accent-ink)'},
  ];
  var domainHtml = domains.map(function(dm){
    return '<div style="margin-bottom:8px">' +
      '<div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:3px">' +
        '<span style="color:var(--muted)">' + dm.label + '</span>' +
        '<span style="font-weight:700;color:' + dm.color + '">' + dm.val + '%</span>' +
      '</div>' +
      '<div style="height:5px;background:var(--surface3);border-radius:100px">' +
        '<div class="cc-predictive-fill" style="height:100%;width:' + dm.val + '%;background:' + dm.color + ';border-radius:100px;transition:width 1s ease"></div>' +
      '</div></div>';
  }).join('');

  // ── Signal contributions ──
  var sigEntries = Object.entries(contribs).sort(function(a,b){return b[1]-a[1];});
  var sigHtml = sigEntries.map(function(kv){
    var lbl = sigLabels[kv[0]] || kv[0];
    var pct = kv[1];
    return '<div style="display:flex;align-items:center;gap:8px;font-size:11px;margin-bottom:5px">' +
      '<span style="flex:1;color:var(--muted)">' + lbl + '</span>' +
      '<div style="width:80px;height:4px;background:var(--surface3);border-radius:100px">' +
        '<div class="cc-predictive-fill" style="height:100%;width:' + pct + '%;background:' + col.hex + ';border-radius:100px;opacity:.7;transition:width 1s ease"></div>' +
      '</div>' +
      '<span style="width:30px;text-align:right;font-weight:700;color:var(--text)">' + pct + '%</span>' +
    '</div>';
  }).join('');

  // ── 7-day sparkline ──
  var sparkHtml = '';
  if(hist.length > 1){
    var maxV = Math.max.apply(null, hist.map(function(h){return h.delta_p||0;}).concat([1]));
    var W=200, H=32, pts = hist.map(function(h,i){
      var x = i * (W/(hist.length-1));
      var y = H - ((h.delta_p||0)/maxV)*H;
      return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');
    sparkHtml =
      '<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border)">' +
      '<div style="font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px">7-Day Trend</div>' +
      '<svg class="cc-trend-sparkline" viewBox="0 0 200 32" style="width:100%;height:32px;display:block"><title>7-day risk trend, latest '+Number(hist[hist.length-1].delta_p||0).toFixed(1)+'</title>' +
        '<polyline points="' + pts + '" fill="none" stroke="' + col.hex + '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity=".8"/>' +
        '<polyline points="0,' + H + ' ' + pts + ' ' + W + ',' + H + '" fill="' + col.hex + '" opacity=".08"/>' +
      '</svg></div>';
  }

  // ── Telemetry snapshot chips ──
  // A figure the engine did not supply is a dash. It is not 0 (no breaches) and not 100 per cent.
  var telVal = function(v, fmt){ return (v === null || v === undefined || isNaN(Number(v))) ? 'n/a' : (fmt ? fmt(Number(v)) : String(v)); };
  var telChips = [
    {icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-shield></use></svg>', label:'Breaches',    val:telVal(tel.breach_raw_count), link:'/sentinel/'},
    {icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-settings></use></svg>',   label:'Open NCs',    val:telVal(tel.nc_count),         link:'/grid/'},
    {icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-alarm-clock></use></svg>',   label:'BCM (days)',  val:telVal(tel.days_since_exercise, function(n){return String(Math.round(n));}), link:'/bcm/'},
    {icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-triangle-alert></use></svg>',   label:'Recurring Ops',val:telVal(tel.orm_recurring),   link:'/orm/'},
    {icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-chart-column></use></svg>', label:'ARIA %',      val:telVal(tel.compliance_pct, function(n){return n.toFixed(0)+'%';}), link:'/aria/'},
    {icon:'<svg class=ic-red aria-hidden=true><use href=/static/icons/sprite.svg#ic-dot></use></svg>', label:'Appetite',    val:telVal(tel.appetite_breaches), link:'/erm/'},
  ];
  var chipHtml = telChips.map(function(c){
    return '<a href="' + esc(/^\/(?!\/)/.test(c.link || '') ? c.link : '#') + '" style="display:inline-flex;align-items:center;gap:4px;padding:4px 9px;border-radius:100px;background:var(--surface2);border:1px solid var(--border);font-size:11px;font-weight:600;color:var(--text);text-decoration:none;transition:all .15s" class="cc-hover-chip">' +
      c.icon + ' ' + c.label + ': <span style="margin-left:2px;color:var(--accent)">' + c.val + '</span></a>';
  }).join('');

  // ── Advisory block ──
  var advHtml = '';
  if(d.advisory_text){
    // Convert simple markdown to HTML
    var adv = d.advisory_text
      .replace(/### (.*)/g, '<div style="font-size:13px;font-weight:800;color:var(--text);margin-bottom:8px">$1</div>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/^(\d+\.) (.+)$/gm, '<div style="display:flex;gap:8px;margin-bottom:4px"><span style="color:' + col.hex + ';font-weight:700;flex-shrink:0">$1</span><span>$2</span></div>')
      .replace(/\n\n/g, '<br>')
      .replace(/\n/g, '<br>');
    advHtml =
      '<div style="background:rgba(' + _hexToRgb(col.hex) + ',.06);border:1px solid rgba(' + _hexToRgb(col.hex) + ',.2);border-radius:var(--radius);padding:14px 16px;margin-top:16px">' +
      '<div style="font-size:10px;font-weight:700;color:' + col.hex + ';text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-brain></use></svg> AI Advisory</div>' +
      '<div style="font-size:13px;line-height:1.7;color:var(--text)">' + adv + '</div>' +
      '</div>';
  }

  // ── Confidence badge ──
  var conf = Math.round((d.confidence||0)*100);
  var confColor = conf >= 70 ? 'var(--good,#16a34a)' : conf >= 40 ? 'var(--amber)' : 'var(--muted)';

  return '<div style="display:grid;grid-template-columns:140px 1fr;gap:20px;align-items:start">' +
    // Left: gauge
    '<div style="text-align:center">' +
      gaugeSvg +
      '<div style="font-size:10px;color:' + confColor + ';font-weight:700;margin-top:4px">Confidence: ' + conf + '%</div>' +
    '</div>' +
    // Right: domains + signals
    '<div>' +
      '<div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">Domain Breakdown</div>' +
      domainHtml +
      '<div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:12px;margin-bottom:8px">Signal Contributions</div>' +
      sigHtml +
    '</div>' +
  '</div>' +
  // Telemetry chips row
  '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:16px;padding-top:14px;border-top:1px solid var(--border)">' +
    '<span style="font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;align-self:center;margin-right:4px">Live Telemetry</span>' +
    chipHtml +
  '</div>' +
  sparkHtml +
  advHtml +
  // Why this number: the records behind each signal, and a place to dispute one (loaded on demand)
  '<div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--border)">' +
    '<button type="button" class="btn btn-secondary" id="prTraceBtn" data-cc-action="loadPredictiveTrace">Why this number?</button>' +
    '<div id="prTrace" role="region" aria-label="What this prediction was made from" aria-live="polite" style="margin-top:10px"></div>' +
  '</div>';
}

// ── Why this number ──
function _prEl(tag, props, kids){
  var node = document.createElement(tag);
  Object.keys(props || {}).forEach(function(k){
    if(k === 'text') node.textContent = props[k];
    else node.setAttribute(k, props[k]);
  });
  (kids || []).forEach(function(c){ if(c) node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
  return node;
}

async function loadPredictiveTrace() {
  var host = document.getElementById('prTrace');
  var btn = document.getElementById('prTraceBtn');
  if(!host) return;
  host.textContent = 'Loading...';
  if(btn) btn.disabled = true;
  try {
    var id = _prData && (_prData.prediction_id || _prData.id);
    var t = await ApiClient.request('/api/predictive-risk/trace' + (id ? '?prediction_id=' + encodeURIComponent(id) : ''),
                                    { actionId: 'command_centre.predictive_risk.trace' });
    host.textContent = '';
    host.appendChild(_prEl('p', { style: 'font-size:12px;color:var(--muted);margin:0 0 8px', text:
      'Computed ' + t.freshness.computed_at + ' from the records as they were then. ' +
      'The number is a weighted formula, not a decision: ' + t.formula + '. ' + (t.note || '') }));
    t.signals.forEach(function(s){
      var box = _prEl('section', { style: 'border:1px solid var(--border);border-radius:var(--radius);padding:10px 12px;margin-bottom:8px' });
      var share = s.direction === 'lowers' ? ' (lowers the score)' :
        (s.share_pct !== null && s.share_pct !== undefined ? ' (' + s.share_pct + '% of the score)' : '');
      box.appendChild(_prEl('div', { style: 'font-weight:700;font-size:13px', text: s.label + share }));
      box.appendChild(_prEl('p', { style: 'font-size:12px;margin:4px 0;color:var(--muted)', text: s.rule }));
      box.appendChild(_prEl('p', { style: 'font-size:12px;margin:2px 0;color:var(--muted)', text: 'Period: ' + s.window +
        '. Figure: ' + (s.figure === null || s.figure === undefined ? 'not supplied' : s.figure) +
        ', weight ' + s.weight + ', term ' + (s.term === null || s.term === undefined ? 'n/a' : s.term) + '.' }));
      if(t.traceable){
        var weighted = s.records.some(function(r){ return r.weight !== null && r.weight !== undefined; });
        var counted = s.none_found ? 'No completed exercise is on record, so this reads as 365 days.' :
          (s.count === null || s.count === undefined) ? 'The engine did not supply the records.' :
          s.count + (s.of ? ' of ' + s.of : '') + ' record(s) counted' +
            (s.truncated ? '; ' + s.records.length + ' are listed' + (weighted ? ', heaviest first.' : '.') : '.');
        box.appendChild(_prEl('p', { style: 'font-size:12px;margin:2px 0', text: counted }));
        if(s.categories && s.categories.length){
          box.appendChild(_prEl('p', { style: 'font-size:12px;margin:2px 0', text: 'Categories above appetite: ' + s.categories.join(', ') + '.' }));
        }
        if(s.records.length){
          var list = _prEl('ul', { style: 'margin:4px 0 4px 18px;padding:0;font-size:12px' });
          s.records.forEach(function(r){
            var href = (typeof r.url === 'string' && r.url.charAt(0) === '/' && r.url.charAt(1) !== '/') ? r.url : '/';
            var a = _prEl('a', { href: href, text: r.title });
            list.appendChild(_prEl('li', {}, [a, r.weight !== null && r.weight !== undefined ? ' (weight ' + r.weight + ')' : '']));
          });
          box.appendChild(list);
        }
        if(s.not_shown){
          box.appendChild(_prEl('p', { style: 'font-size:11px;color:var(--muted);margin:2px 0',
            text: s.not_shown + ' listed record(s) no longer exist or are not open to you.' }));
        }
      }
      (s.disputes || []).forEach(function(d){
        box.appendChild(_prEl('p', { style: 'font-size:12px;margin:4px 0;padding:6px 8px;background:var(--surface2);border-radius:6px',
          text: 'Disputed by ' + (d.author || 'a reviewer') + ' (' + d.created_at + '): ' + d.body }));
      });
      var field = _prEl('input', { type: 'text', maxlength: '1000', class: 'form-input', 'aria-label': 'Dispute the ' + s.label + ' signal',
        placeholder: 'What is wrong with this signal?', style: 'font-size:12px;padding:7px 10px' });
      var send = _prEl('button', { type: 'button', class: 'btn btn-secondary btn-sm', style: 'margin-top:6px', text: 'Record the dispute' });
      send.addEventListener('click', async function(){
        var body = field.value.trim();
        if(!body) return;
        send.disabled = true;
        try {
          await ApiClient.request('/api/predictive-risk/' + encodeURIComponent(t.prediction_id) + '/disputes',
            { method: 'POST', body: { signal: s.key, body: body }, actionId: 'command_centre.predictive_risk.dispute' });
          loadPredictiveTrace();
        } catch(e){
          send.disabled = false;
          if(typeof showToast === 'function') showToast((e && e.detail) || 'The dispute could not be recorded', 'error');
        }
      });
      var dispute = _prEl('details', { style: 'margin-top:6px' }, [
        _prEl('summary', { style: 'cursor:pointer;font-size:12px;color:var(--muted)', text: 'Dispute this signal' }),
        _prEl('div', { style: 'margin-top:6px' }, [field, send])]);
      box.appendChild(dispute);
      host.appendChild(box);
    });
    host.appendChild(_prEl('p', { style: 'font-size:11px;color:var(--muted)', text:
      'A dispute is a note beside the number. It does not change the prediction, the records or the formula.' }));
  } catch(e){
    host.textContent = (e && e.detail) || 'The trace could not be loaded.';
  } finally {
    if(btn) btn.disabled = false;
  }
}

function _hexToRgb(hex) {
  // Converts #rrggbb to "r,g,b" for use in rgba()
  var r = parseInt(hex.slice(1,3),16)||0;
  var g = parseInt(hex.slice(3,5),16)||0;
  var b = parseInt(hex.slice(5,7),16)||0;
  return r + ',' + g + ',' + b;
}

function _prTimeAgo(ts) {
  if(!ts) return '';
  var s = Math.floor((Date.now() - new Date(ts.includes('T')?ts:ts+'Z').getTime()) / 1000);
  if(s < 60) return 'just now';
  if(s < 3600) return Math.floor(s/60) + 'm ago';
  return Math.floor(s/3600) + 'h ago';
}

async function acknowledgePrediction() {
  try {
    await ApiClient.request('/api/predictive-risk/acknowledge', { method: 'POST', actionId: 'command_centre.prediction.ack' });
    var btn = document.getElementById('prAckBtn');
    if(btn) btn.style.display = 'none';
    showToast('Risk alert acknowledged');
  } catch(e){
    showToast(e.detail || 'Failed to acknowledge','error');
  }
}

// ── The first screen: what needs action, what changed, what lacks proof, what can be reported ──
(function(){
  var grid = document.getElementById('ccFirstScreenGrid');
  var failed = document.getElementById('ccFirstScreenFailed');
  if(!grid) return;
  function el(tag, props, children){
    var node = document.createElement(tag);
    Object.keys(props || {}).forEach(function(k){
      if(k === 'text') node.textContent = props[k];
      else if(k === 'style') node.setAttribute('style', props[k]);
      else node.setAttribute(k, props[k]);
    });
    (children || []).forEach(function(c){ if(c) node.appendChild(c); });
    return node;
  }
  function figure(value, label){
    var shown = (value === null || value === undefined) ? 'n/a' : String(value);
    return el('div', {style:'min-width:70px'}, [
      el('div', {text: shown, style:'font-size:24px;font-weight:800;line-height:1.1'}),
      el('div', {text: label, style:'font-size:11px;color:var(--muted)'})]);
  }
  function safeLink(url){ return (typeof url === 'string' && url.charAt(0) === '/' && url.charAt(1) !== '/') ? url : '/'; }
  var FIGURES = {
    action: [['overdue','Overdue'], ['needs_you','Needs you'], ['due_soon','Due soon'], ['waiting','Waiting on others']],
    changed: [['to_look_at','To look at again'], ['unread','Unread changes']],
    proof: [['without_proof','Without current proof'], ['waiting_review','Waiting for a reviewer']]
  };
  function card(p){
    var box = el('div', {class:'panel-card', style:'padding:14px'});
    box.appendChild(el('div', {text:p.title, style:'font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.4px;color:var(--muted);margin-bottom:8px'}));
    if(p.state === 'unavailable'){
      box.appendChild(el('div', {text:'n/a', style:'font-size:24px;font-weight:800;color:var(--muted)'}));
      box.appendChild(el('div', {text:p.note || 'This could not be read just now. That is not a count of zero.', style:'font-size:12px;color:var(--muted);margin-top:4px'}));
      return box;
    }
    if(p.state === 'not_measured'){
      box.appendChild(el('div', {text:'Not measured', style:'font-size:16px;font-weight:700;color:var(--muted)'}));
      box.appendChild(el('div', {text:p.note || '', style:'font-size:12px;color:var(--muted);margin-top:4px'}));
      return box;
    }
    if(p.key === 'report'){
      (p.presets || []).forEach(function(r){
        var line = el('div', {style:'margin-bottom:6px;font-size:13px'});
        line.appendChild(el('strong', {text:r.label}));
        line.appendChild(el('span', {text:' - ' + r.sections_open + ' of ' + r.sections_total + ' sections open to you', style:'color:var(--muted)'}));
        box.appendChild(line);
      });
      box.appendChild(el('a', {href:'/reports', text:'Open Reports', class:'btn btn-secondary btn-sm'}));
      if(p.last_run) box.appendChild(el('div', {text:'Last saved run: ' + p.last_run.name + ', ' + p.last_run.at, style:'font-size:11px;color:var(--muted);margin-top:8px'}));
      return box;
    }
    var row = el('div', {style:'display:flex;gap:14px;flex-wrap:wrap;margin-bottom:8px'});
    (FIGURES[p.key] || []).forEach(function(f){ row.appendChild(figure((p.counts || {})[f[0]], f[1])); });
    box.appendChild(row);
    (p.items || []).forEach(function(it){
      box.appendChild(el('div', {style:'font-size:12px;margin-top:3px'}, [
        el('a', {href:safeLink(it.link), text:it.title}),
        it.label ? el('span', {text:' (' + it.label + (it.due ? ', due ' + String(it.due).slice(0, 10) : '') + ')', style:'color:var(--muted)'}) : null]));
    });
    if(p.state === 'partial' && p.note) box.appendChild(el('div', {text:p.note, style:'font-size:11px;color:var(--muted);margin-top:6px'}));
    if(p.definition) box.appendChild(el('div', {text:p.definition, style:'font-size:11px;color:var(--muted);margin-top:6px'}));
    box.appendChild(el('a', {href:safeLink(p.link), text:'Open the list', style:'display:inline-block;font-size:12px;margin-top:8px'}));
    return box;
  }
  async function load(){
    failed.style.display = 'none';
    try{
      var data = await ApiClient.request('/api/command-centre/first-screen', {actionId: 'command_centre.first_screen'});
      grid.textContent = '';
      (data.panels || []).forEach(function(p){ grid.appendChild(card(p)); });
      var asOf = document.getElementById('ccFirstScreenAsOf');
      if(asOf && data.as_of) asOf.textContent = 'Read ' + String(data.as_of).slice(0, 16) + ' UTC';
    }catch(e){
      grid.textContent = '';
      failed.style.display = 'block';
    }
  }
  var retry = document.getElementById('ccFirstScreenRetry');
  if(retry) retry.addEventListener('click', load);
  load();
})();

// ── Button handlers ──
async function exportReport(){
  if ((document.getElementById('ccPageConfig') || {dataset: {}}).dataset.isAdmin === '1') {
  showToast('Generating compliance export...', 'info');
  try {
    const run = await ApiClient.request('/api/reports/quick-run', {
      method: 'POST', body: { report_type: 'compliance_summary' }, actionId: 'command_centre.export_report.run',
    });
    if (!run || !run.run_id) throw new Error('No saved run came back');
    showToast('Export ready, opening Reports', 'success');
    window.location.href = '/reports?run=' + encodeURIComponent(run.run_id);
  } catch(e) {
    showToast(e.detail || 'Export failed, try again', 'error');
  }
  } else {
  showToast('Export requires admin access', 'info');
  }
}

async function generateBoardReport(){
  showToast('Generating executive brief...', 'info');
  try {
    const run = await ApiClient.request('/api/reports/quick-run', {
      method: 'POST', body: { report_type: 'preset_board' }, actionId: 'command_centre.board_report.run',
    });
    if (!run || !run.run_id) throw new Error('No saved run came back');
    showToast('Board report ready, opening Reports', 'success');
    window.location.href = '/reports?run=' + encodeURIComponent(run.run_id);
  } catch(e) {
    console.error('Board report error:', e);
    showToast(e.detail || 'Failed to generate board report', 'error');
  }
}

// Command Centre actions under strict script policy: markup names an action, a link or a filter as data, and this
// one listener maps it to a fixed function. Links must be the application's own paths.
(function(){
  'use strict';
  var actions={
    openTrainer:function(){var b=document.getElementById('trainerBubble');if(b)b.click();},
    exportReport:function(){exportReport();},
    generateBoardReport:function(){generateBoardReport();},
    scrollOverdue:function(){var t=document.getElementById('ccOverdueTable');if(t)t.scrollIntoView({behavior:'smooth'});},
    openNotifications:function(){var b=document.getElementById('notifBtn');if(b)b.click();},
    togglePredictiveRisk:function(){togglePredictiveRisk();},
    refreshPredictiveRisk:function(){loadPredictiveRisk(true);},
    acknowledgePrediction:function(){acknowledgePrediction();},
    loadPredictiveTrace:function(){loadPredictiveTrace();}
  };
  document.addEventListener('click',function(event){
    var el=event.target instanceof Element?
      event.target.closest('[data-cc-action],[data-cc-href],[data-cc-filter],[data-cc-ack],[data-cc-stop]'):null;
    if(!el||el.hasAttribute('data-cc-stop'))return;
    var d=el.dataset;
    if(d.ccHref!==undefined){if(/^\/(?!\/)/.test(d.ccHref))window.location.href=d.ccHref;return;}
    if(d.ccFilter!==undefined){if(/^[a-z]+$/.test(d.ccFilter))filterOverdue(d.ccFilter,el);return;}
    if(d.ccAck!==undefined){if(/^\d+$/.test(d.ccAck))ackAdvisory(Number(d.ccAck),el);return;}
    var fn=actions[d.ccAction];
    if(fn)fn(event,el);else console.error('Command Centre action refused: '+d.ccAction);
  });
})();
