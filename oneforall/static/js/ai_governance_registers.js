(() => {
  'use strict';
  const root = document.getElementById('aiRegisters');
  if (!root) return;
  const notice = document.getElementById('registerNotice');
  const preview = document.getElementById('registerPreview');
  let current = null;
  const say = (message, bad = false) => { notice.textContent = message; notice.classList.toggle('aig-say-bad', bad); };
  async function json(response) {
    try { return await response.json(); } catch (_) { return {}; }
  }
  function option(select, id, name) {
    const el = document.createElement('option'); el.value = String(id); el.textContent = name; select.append(el);
  }
  async function choices() {
    try {
      const units = await fetch('/ai-governance/api/business-units');
      if (units.ok) {
        const payload = await json(units);
        (payload.items || []).forEach(row => {
          ['systemsUnit', 'riskUnit'].forEach(id => { const select = document.getElementById(id); if (select) option(select, row.id, row.name); });
        });
      }
      const assessment = document.getElementById('riskAssessment');
      if (assessment) {
        const response = await fetch('/orm/api/aims');
        if (response.ok) (await json(response)).forEach(row => {
          option(assessment, row.id, `${row.ref} · ${row.title}`);
          assessment.lastElementChild.dataset.unit = row.business_unit_id || '';
        });
        assessment.addEventListener('change', () => {
          const riskUnit = document.getElementById('riskUnit');
          if (riskUnit) riskUnit.value = assessment.selectedOptions[0]?.dataset.unit || '';
        });
      }
    } catch (_) { say('Choices could not be loaded. Refresh and try again.', true); }
  }
  root.querySelectorAll('[data-register-export]').forEach(button => button.addEventListener('click', async () => {
    button.disabled = true; say('Generating a complete saved register…');
    try {
      const response = await fetch('/api/reports/quick-run', {method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({report_type:button.dataset.registerExport})});
      const result = await json(response);
      if (!response.ok || !result.run_id) throw new Error(result.error || 'The register could not be generated.');
      if (result.status === 'pending') {
        await window.themisWaitReportRun(result.run_id, stage =>
          say(`Generating a complete saved register · ${stage.replaceAll('_', ' ')}…`));
      }
      window.location.assign(`/reports?run=${Number(result.run_id)}`);
    } catch (error) { say(error.message, true); button.disabled = false; }
  }));
  root.querySelectorAll('[data-register-preview]').forEach(button => button.addEventListener('click', async () => {
    button.disabled = true; say('Checking records in your scope…');
    try {
      const type = encodeURIComponent(button.dataset.registerPreview);
      const response = await fetch('/api/reports/register-preview?report_type=' + type);
      const result = await json(response);
      if (!response.ok) throw new Error(result.error || 'Coverage preview unavailable.');
      const panel = document.getElementById('registerCoverage');
      const body = document.getElementById('registerCoverageBody'); body.replaceChildren();
      Object.entries(result.counts || {}).forEach(([name, count]) => {
        const line = document.createElement('p'); line.textContent = `${name.replaceAll('_',' ')}: ${count}`;
        body.append(line);
      });
      const gap = document.createElement('p'); gap.textContent =
        `${result.total_gaps} data-quality gap(s). Open the saved register for every detailed record.`;
      body.append(gap); panel.hidden = false; say('Coverage preview ready.');
    } catch (error) { say(error.message, true); } finally { button.disabled = false; }
  }));
  function render(result) {
    current = result; preview.hidden = false;
    document.getElementById('registerSummary').textContent =
      `${result.rows.length} rows in ${result.kind === 'ai_systems' ? 'AI systems' : 'AI risks'} · preview #${result.batch_id}. ` +
      'Existing references remain in their owning module. Only selected new rows can be created.';
    const warningBox = document.getElementById('registerWarnings'); warningBox.replaceChildren();
    if (!(result.warnings || []).length) warningBox.textContent = 'No discrepancies detected by this template profile.';
    (result.warnings || []).forEach(w => {
      const key = `${w.code}:${w.ref || ''}`;
      const label = document.createElement('label'); label.style.display='block';
      const input = document.createElement('input'); input.type='checkbox'; input.className='register-warning'; input.value=key;
      label.append(input, document.createTextNode(` Reviewed: ${w.code.replaceAll('_',' ')}${w.ref ? ` · ${w.ref}` : ''}`));
      warningBox.append(label);
    });
    const body = document.getElementById('registerRows'); body.replaceChildren();
    result.rows.forEach(row => {
      const tr = document.createElement('tr');
      const ref = row.external_ref || row.ref;
      const check = document.createElement('input'); check.type='checkbox'; check.className='register-row';
      check.value=ref; check.checked=row.outcome==='create'; check.disabled=row.outcome!=='create';
      const td = document.createElement('td'); td.append(check); tr.append(td);
      [ref, row.name || row.description, row.outcome].forEach(value => {
        const cell=document.createElement('td'); cell.textContent=value || ''; tr.append(cell);
      }); body.append(tr);
      if (row.existing_id) {
        const link=document.createElement('a');
        link.href = result.kind === 'ai_systems'
          ? `/ai-governance/systems/${Number(row.existing_id)}` : '/orm/aims';
        link.textContent = 'Review existing record'; tr.lastElementChild.append(' · ', link);
      }
    });
    preview.scrollIntoView({behavior:'smooth',block:'start'});
  }
  ['systemsRegisterImport','risksRegisterImport'].forEach(id => {
    const form=document.getElementById(id); if (!form) return;
    form.addEventListener('submit', async event => {
      event.preventDefault(); say('Checking workbook locally on the server…');
      const button=form.querySelector('button'); button.disabled=true;
      try {
        const response=await fetch('/ai-governance/api/register-import/preview',{method:'POST',body:new FormData(form)});
        const data=await json(response);
        if (!response.ok) throw new Error(data.error || 'The workbook could not be previewed.');
        render(data); say('Preview ready. Review the rows and every discrepancy before confirming.');
      } catch(error) { say(error.message,true); } finally { button.disabled=false; }
    });
  });
  document.getElementById('registerConfirm').addEventListener('click', async event => {
    if (!current) return;
    const acknowledged=[...root.querySelectorAll('.register-warning:checked')].map(el=>el.value);
    const selected=[...root.querySelectorAll('.register-row:checked')].map(el=>el.value);
    if (acknowledged.length !== (current.warnings || []).length) { say('Review and check every discrepancy first.',true); return; }
    if (!selected.length) { say('Select at least one new row to create.',true); return; }
    event.currentTarget.disabled=true;
    try {
      const response=await fetch(`/ai-governance/api/register-import/${Number(current.batch_id)}/confirm`,{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({version:current.version,acknowledged,selected})});
      const result=await json(response);
      if (!response.ok) throw new Error(result.error || 'Import confirmation failed.');
      say(`${result.created.length} draft records created. Open the owning module to review their facts and decisions.`);
      preview.hidden=true; current=null;
    } catch(error) { say(error.message,true); } finally { event.currentTarget.disabled=false; }
  });
  choices();
})();
