(() => {
  const panel = document.getElementById('framework-register-preview');
  if (!panel) return;
  const title = document.getElementById('framework-register-title');
  const summary = document.getElementById('framework-register-summary');
  const gaps = document.getElementById('framework-register-gaps');
  const generate = document.getElementById('framework-register-generate');
  let frameworkId = null;
  let activeAuditId = null;
  let matchedAuditFrameworkId = null;
  let matchedAuditId = null;
  document.querySelectorAll('[data-framework-register]').forEach(button => {
    button.addEventListener('click', async event => {
      event.stopPropagation();
      frameworkId = Number(button.dataset.frameworkRegister);
      activeAuditId = frameworkId === matchedAuditFrameworkId ? matchedAuditId : null;
      panel.hidden = false;
      title.textContent = `Auditor register preview · ${button.closest('.fw-card').querySelector('.fw-card-name').textContent}`;
      summary.textContent = 'Reading authorized source records…';
      gaps.replaceChildren();
      generate.disabled = true;
      panel.scrollIntoView({behavior:'smooth', block:'start'});
      try {
        const auditParam = activeAuditId ? `&audit_id=${activeAuditId}` : '';
        const response = await fetch(`/api/reports/register-preview?report_type=framework_auditor_register&framework_id=${frameworkId}${auditParam}`);
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Preview failed.');
        if (frameworkId !== Number(result.framework.id)) return;
        const counts = result.counts;
        const auditSummary = result.audit ? ` · ${counts.audit_controls} audit controls · ${counts.audit_findings} findings · ${counts.audit_evidence} audit Vault links` : '';
        summary.textContent = `${counts.controls} controls · ${counts.documents} controlled documents · ${counts.evidence} evidence relationships${auditSummary} · ${result.total_gaps} gaps. As of ${result.as_of}.`;
        result.gaps.forEach(gap => {
          const item = document.createElement('p');
          item.textContent = `${gap.control_ref}: ${gap.gap}`;
          gaps.append(item);
        });
        if (result.total_gaps > result.gaps.length) {
          const item = document.createElement('p');
          item.textContent = `Showing ${result.gaps.length} of ${result.total_gaps} gaps in preview; the frozen register contains every authorized detail row.`;
          gaps.append(item);
        }
        generate.disabled = false;
      } catch (error) { summary.textContent = error.message; }
    });
  });
  const requestedFramework = new URLSearchParams(window.location.search).get('register_framework');
  if (requestedFramework && /^\d+$/.test(requestedFramework)) {
    const button = [...document.querySelectorAll('[data-framework-register]')]
      .find(item => item.dataset.frameworkRegister === requestedFramework);
    if (button) button.click();
  }
  const requestedAuditId = new URLSearchParams(window.location.search).get('register_from_grid_audit');
  if (requestedAuditId && /^\d+$/.test(requestedAuditId)) {
    fetch(`/grid/api/audits/${requestedAuditId}`).then(response => {
      if (!response.ok) throw new Error('Audit not available in your scope.');
      return response.json();
    }).then(audit => {
      // GRID and ARIA have separate framework ID spaces. Match a unique
      // displayed name; never treat the GRID numeric ID as an ARIA ID.
      const names = Array.isArray(audit.framework_names) && audit.framework_names.length
        ? audit.framework_names : [audit.framework_name];
      const buttons = [...document.querySelectorAll('[data-framework-register]')];
      const matches = buttons.filter(item => names.length === 1 &&
        item.closest('.fw-card')?.querySelector('.fw-card-name')?.textContent.trim() === names[0]);
      if (matches.length === 1) {
        matchedAuditId = Number(requestedAuditId);
        matchedAuditFrameworkId = Number(matches[0].dataset.frameworkRegister);
        matches[0].click();
        const note = document.createElement('p');
        note.textContent = 'This register includes the selected GRID audit controls, findings and Vault links. GRID statuses do not imply ARIA control acceptance.';
        panel.append(note);
      } else {
        panel.hidden = false;
        summary.textContent = 'Select a framework. The audit pack requires an unambiguous matching framework.';
      }
    }).catch(error => {
      panel.hidden = false;
      summary.textContent = error.message;
    });
  }
  generate.addEventListener('click', async () => {
    if (!frameworkId) return;
    generate.disabled = true;
    summary.textContent = 'Generating a frozen, scoped register…';
    try {
      const response = await fetch('/api/reports/quick-run', {method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({report_type:'framework_auditor_register',framework_id:frameworkId,
          ...(activeAuditId ? {audit_id:activeAuditId} : {})})});
      const result = await response.json();
      if (!response.ok || !result.run_id) throw new Error(result.error || 'Register generation failed.');
      if (result.status === 'pending') {
        await window.themisWaitReportRun(result.run_id, stage => {
          summary.textContent = `Generating a frozen, scoped register · ${stage.replaceAll('_', ' ')}…`;
        });
      }
      window.location.assign(`/reports?run=${Number(result.run_id)}`);
    } catch (error) { summary.textContent = error.message; generate.disabled = false; }
  });
})();
