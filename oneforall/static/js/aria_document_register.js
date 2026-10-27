(() => {
  const form = document.getElementById('doc-register-form');
  if (!form) return;
  const byId = id => document.getElementById(id);
  let preview = null;
  const status = message => { byId('doc-register-status').textContent = message; };
  async function request(url, options) {
    const response = await fetch(url, options);
    const body = await response.json();
    if (!response.ok || !body.ok) throw new Error(body.error || 'The request failed.');
    return body;
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    preview = null;
    byId('doc-register-preview').hidden = true;
    status('Checking workbook and matching document versions…');
    const data = new FormData();
    data.append('file', byId('doc-register-file').files[0]);
    data.append('business_unit_id', byId('doc-register-bu').value);
    data.append('org_wide', byId('doc-register-orgwide').checked ? 'true' : 'false');
    try {
      preview = await request('/aria/api/document-register/preview', {method:'POST', body:data});
      const matched = preview.rows.filter(row => row.outcome === 'matched').length;
      byId('doc-register-summary').textContent = `${preview.rows.length} rows; ${matched} exact scoped code/version matches; ${preview.rows.length - matched} need a source file or reviewed match.`;
      const warnings = byId('doc-register-warnings');
      warnings.replaceChildren();
      preview.warnings.forEach(warning => {
        const p = document.createElement('p');
        p.textContent = `${warning.code.replaceAll('_',' ')}${warning.ref ? ` · ${warning.ref}` : ''}${warning.versions ? ` · ${JSON.stringify(warning.versions)}` : ''}`;
        warnings.append(p);
      });
      const rows = byId('doc-register-rows');
      rows.replaceChildren();
      preview.rows.forEach(row => {
        const item = document.createElement('div');
        item.className = 'intake-item';
        item.textContent = `${row.code} · ${row.title} · v${row.version} · ${row.outcome === 'matched' ? 'Exact file match for review' : 'Source file needed'}`;
        rows.append(item);
      });
      byId('doc-register-ack').checked = false;
      byId('doc-register-preview').hidden = false;
      status('Review the discrepancies and row outcomes before filing.');
    } catch (error) { status(error.message); }
  });
  byId('doc-register-confirm').addEventListener('click', async () => {
    if (!preview || !byId('doc-register-ack').checked) { status('Review and acknowledge the workbook discrepancies.'); return; }
    const acknowledged = preview.warnings.map(warning => `${warning.code}:${warning.ref || ''}`);
    try {
      const result = await request(`/aria/api/document-register/${preview.batch_id}/confirm`,
        {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({version:preview.version, acknowledged})});
      preview = null;
      byId('doc-register-preview').hidden = true;
      status(`${result.claims} claims queued; ${result.matched} exact existing versions. Upload missing source files and review approval and control links separately.`);
    } catch (error) { status(error.message); }
  });
  document.querySelectorAll('[data-register-decision]').forEach(button => {
    button.addEventListener('click', async () => {
      const claim = button.closest('[data-register-claim]');
      try {
        const result = await request(`/aria/api/document-register/claims/${claim.dataset.registerClaim}/review`,
          {method:'POST', headers:{'Content-Type':'application/json'},
           body:JSON.stringify({version:Number(claim.dataset.claimVersion),decision:button.dataset.registerDecision})});
        claim.querySelector('span').textContent = `${result.state.replaceAll('_',' ')} · approval and control mapping still require review`;
        claim.querySelectorAll('[data-register-decision]').forEach(item => item.remove());
        status('Claim reviewed. Source policy approval was not changed.');
      } catch (error) { status(error.message); }
    });
  });
})();
