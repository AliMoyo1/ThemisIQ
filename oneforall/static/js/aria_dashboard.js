(function(){
  // ── Animate the Control Status donut ──
  const ring = document.getElementById('ariaStatusDonut');
  const totals = {implemented: ring.dataset.implemented, in_progress: ring.dataset.inProgress, not_started: ring.dataset.notStarted};
  const circ = 2 * Math.PI * 56;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function paintStatusRing(values){
    const counts = [
      Math.max(0, Number(values.implemented) || 0),
      Math.max(0, Number(values.in_progress) || 0),
      Math.max(0, Number(values.not_started) || 0)
    ];
    const total = counts.reduce((sum, value) => sum + value, 0);
    const ids = ['ariaArcImpl', 'ariaArcProg', 'ariaArcNotStarted'];
    let angle = -90;
    function draw(){
      counts.forEach((count, index) => {
        const arc = document.getElementById(ids[index]);
        if(!arc) return;
        const fraction = total ? count / total : 0;
        arc.style.visibility = count ? 'visible' : 'hidden';
        arc.setAttribute('transform', 'rotate(' + angle + ' 70 70)');
        arc.setAttribute('stroke-dashoffset', String(circ * (1 - fraction)));
        angle += fraction * 360;
      });
    }
    if(reduceMotion) draw();
    else requestAnimationFrame(() => requestAnimationFrame(draw));
  }
  paintStatusRing(totals);

  // Live refresh from API
  async function refreshDashboard(){
    try {
      const resp = await fetch('/aria/api/dashboard');
      if(!resp.ok) return;
      const data = await resp.json();

      // Update stat cards
      if(data.totals){
        const t = data.totals;
        const pct = t.overall_pct || 0;
        const pctEl = document.getElementById('ariaCompliancePct');
        if(pctEl) pctEl.textContent = pct + '%';
        const barEl = document.getElementById('ariaComplianceBar');
        if(barEl) barEl.style.width = pct + '%';
      }
    } catch(e){
      // Silently fall back to server-rendered data
    }
  }

  // Refresh every 5 minutes
  setInterval(refreshDashboard, 300000);
})();

// ── Button handlers ──
function exportAriaReport(){
  if(typeof showToast === 'function') showToast('Generating export...', 'info');
  window.location = '/aria/export/excel';
}
// Success is shown only when a saved run exists: one call makes it, and the Reports page opens it.
async function generateAriaReport(){
  if(typeof showToast === 'function') showToast('Generating compliance report...', 'info');
  try{
    var resp = await fetch('/api/reports/quick-run', {method:'POST', headers:{'Content-Type':'application/json'},
                                                      body: JSON.stringify({report_type: 'compliance_summary'})});
    var data = await resp.json().catch(function(){ return {}; });
    if(!resp.ok || !data.run_id) throw new Error(data.error || 'The report could not be generated');
    if(typeof showToast === 'function') showToast('Report ready, opening Reports', 'success');
    window.location.href = '/reports?run=' + encodeURIComponent(data.run_id);
  }catch(e){
    if(typeof showToast === 'function') showToast(e.message || 'The report could not be generated', 'error');
  }
}

document.getElementById('ariaExportReport')?.addEventListener('click', exportAriaReport);
document.getElementById('ariaGenerateReport')?.addEventListener('click', generateAriaReport);
const onboard = document.getElementById('ariaOnboardBanner');
if (onboard) {
  try { if (localStorage.getItem('hide_aria_onboard')) onboard.style.display = 'none'; } catch (e) { /* storage unavailable */ }
  document.getElementById('ariaDismissOnboard')?.addEventListener('click', () => {
    onboard.style.display = 'none';
    try { localStorage.setItem('hide_aria_onboard', '1'); } catch (e) { /* storage unavailable */ }
  });
  onboard.querySelectorAll('.aria-onboard-check').forEach(input => input.addEventListener('change', () => {
    input.parentElement.style.opacity = input.checked ? '0.5' : '1';
  }));
  document.getElementById('ariaOnboardReport')?.addEventListener('click', event => {
    event.preventDefault();
    event.stopPropagation();
    generateAriaReport();
  });
}

/* ── PLAN-06 deep-link boot handler ── */
/* ARIA uses an SPA router (navigate) rather than simple drawer openers.
   Deep-linking a 'control' entity requires also knowing the framework_id
   to generate the correct route path. Not feasible with id alone.
   Skipping for now, add a control→framework lookup when available. */
(function(){
  var openParam = new URLSearchParams(window.location.search).get('open');
  if(!openParam) return;
  var sep = openParam.indexOf(':');
  if(sep < 1) return;
  window.history.replaceState({}, '', window.location.pathname);
  // No supported entity types for deep-link yet.
  var _plan06_openers = {};
  var etype = openParam.slice(0, sep);
  var _plan06_fn = _plan06_openers[etype];
  if(!_plan06_fn) return;
})();
