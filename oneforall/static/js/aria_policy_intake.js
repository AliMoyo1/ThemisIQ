(() => {
  const byId = id => document.getElementById(id);
  const list = byId('intake-list');
  let current = null;
  let candidate = null;
  let pdfCopy = null;
  const keys = ['title', 'version', 'doc_type', 'owner', 'approver', 'effective_date', 'review_date'];
  const labels = {title:'Title',version:'Version',doc_type:'Document type',owner:'Owner',approver:'Approver',effective_date:'Effective date',review_date:'Review date'};
  const types = ['Policy','Procedure','Standard','Guideline','Template','Record','Plan'];
  const status = (id, message) => { byId(id).textContent = message; };
  async function api(url, options) {
    const res = await fetch(url, options);
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(typeof data.error === 'object' ? data.error.message : (data.error || 'Request failed'));
    return data;
  }
  function field(key, suggestion, reviewed) {
    const label = document.createElement('label');
    if (key === 'title') label.className = 'wide';
    label.textContent = labels[key];
    const input = key === 'doc_type' ? document.createElement('select') : document.createElement('input');
    input.id = 'intake-field-' + key;
    if (key === 'doc_type') {
      const placeholder = document.createElement('option');
      placeholder.value = ''; placeholder.textContent = 'Choose document type';
      input.append(placeholder);
      types.forEach(type => { const option = document.createElement('option'); option.value = option.textContent = type; input.append(option); });
    }
    if (key.endsWith('_date')) input.type = 'date';
    input.value = reviewed[key] || suggestion?.value || '';
    label.append(input);
    const hint = document.createElement('small');
    hint.textContent = suggestion ? `Suggested from ${suggestion.anchor} (${suggestion.kind})` : 'No value found in source';
    label.append(hint);
    return label;
  }
  function renderLinks(data) {
    const links = byId('intake-links'); links.replaceChildren();
    data.links.forEach(link => {
      const wrap = document.createElement('label'); wrap.className = 'intake-suggestion';
      const check = document.createElement('input'); check.type = 'checkbox'; check.value = link.id; check.className = 'intake-link'; check.checked = link.state === 'confirmed'; check.disabled = data.state !== 'needs_review';
      const body = document.createElement('span');
      const head = document.createElement('strong'); head.textContent = `${link.framework} · ${link.ref} · ${link.name}`;
      const hint = document.createElement('small'); hint.textContent = `${link.match_method.replace('_',' ')} · ${link.anchor}: ${link.excerpt.slice(0, 220)}`;
      body.append(head, hint); wrap.append(check, body); links.append(wrap);
    });
    if (!data.links.length) links.textContent = 'No matches proposed. Search a control and select its source clause below.';
  }
  function show(data) {
    current = data;
    byId('intake-review').hidden = false;
    byId('intake-source-link').href = '/aria/api/policy-imports/' + encodeURIComponent(data.id) + '/source';
    byId('intake-text-state').textContent = data.extracted.text_status === 'extracted' ? 'Text extracted locally' : 'No readable text; review the original manually';
    const fields = byId('intake-fields'); fields.replaceChildren();
    keys.forEach(k => fields.append(field(k, data.extracted.metadata[k], data.reviewed || {})));
    const text = data.extracted.spans.map(s => `${s.anchor}\n${s.text}`).join('\n\n');
    byId('intake-source-text').textContent = text || 'No extractable text. The original file can still be reviewed and registered.';
    renderLinks(data);
    byId('intake-manual-link').hidden = data.state !== 'needs_review';
    const anchor = byId('intake-control-anchor'); anchor.replaceChildren();
    data.extracted.spans.forEach(span => { const option=document.createElement('option'); option.value=span.anchor; option.textContent=`${span.anchor}: ${span.text.slice(0, 80)}`; anchor.append(option); });
    byId('intake-register').hidden = data.state !== 'needs_review';
    byId('intake-version-match').hidden = data.state !== 'needs_review';
    byId('intake-version-results').replaceChildren(new Option('Create a new policy', ''));
    byId('intake-attestation').hidden = data.state !== 'registered' || data.external_status === 'verified';
    byId('intake-composition').hidden = data.state !== 'registered' || data.pending_replacement ||
      !data.file_name.toLowerCase().endsWith('.docx');
    byId('intake-pdf-cover').hidden = data.state !== 'registered' || data.pending_replacement ||
      !data.file_name.toLowerCase().endsWith('.pdf');
    byId('intake-compose-review').hidden = !data.composition_draft;
    byId('intake-candidate-file').hidden = !data.composition_draft;
    candidate = data.composition_draft;
    byId('intake-compose-submit').hidden = !!candidate;
    if (candidate) {
      byId('intake-candidate-file').href = '/aria/api/policy-imports/' + encodeURIComponent(data.id) + '/candidate/' + encodeURIComponent(candidate.id);
      byId('intake-build-preview').hidden = candidate.state !== 'editing';
      setPreview(candidate);
    } else {
      byId('intake-compose-submit').hidden = false;
      byId('intake-preview-link').hidden = true;
      byId('intake-preview-frame').hidden = true;
    }
    byId('intake-original-compare').textContent = text || 'No extractable text.';
    status('intake-action-status', data.external_status === 'verified' ? 'External approval was verified by a specialist.' : '');
    list.querySelectorAll('[data-import-id]').forEach(button => button.setAttribute('aria-current', String(button.dataset.importId === data.id)));
  }
  function setPreview(draft) {
    const ready = draft.state === 'ready' && !!draft.build_id;
    const url = ready ? `/aria/api/policy-drafts/${encodeURIComponent(draft.id)}/preview?build_id=${encodeURIComponent(draft.build_id)}` : '';
    byId('intake-preview-link').hidden = !ready;
    byId('intake-preview-frame').hidden = !ready;
    if (ready) { byId('intake-preview-link').href = url; byId('intake-preview-frame').src = url; }
    byId('intake-confirm-candidate').disabled = !ready || !byId('intake-compare-attest').checked;
  }
  async function open(id) { try { show(await api('/aria/api/policy-imports/' + encodeURIComponent(id))); } catch (e) { status('intake-action-status', e.message); } }
  list.addEventListener('click', e => { const button = e.target.closest('[data-import-id]'); if (button) open(button.dataset.importId); });
  const upload = byId('intake-upload');
  if (upload) upload.addEventListener('submit', async e => {
    e.preventDefault();
    const files = [...byId('intake-files').files].slice(0, 20);
    if (!files.length) return;
    const button = upload.querySelector('button[type=submit]'); button.disabled = true;
    try {
      for (let i = 0; i < files.length; i++) {
        status('intake-upload-status', `Staging ${i + 1} of ${files.length}: ${files[i].name}`);
        const form = new FormData(); form.append('file', files[i]);
        form.append('business_unit_id', byId('intake-bu').value);
        form.append('org_wide', byId('intake-orgwide').checked ? 'true' : 'false');
        const data = await api('/aria/api/policy-imports', {method:'POST',body:form});
        if (!data.duplicate_existing) {
          const item = document.createElement('button'); item.type='button'; item.className='intake-item'; item.dataset.importId=data.id;
          const strong=document.createElement('strong'); strong.textContent=data.extracted.metadata.title?.value || files[i].name;
          const small=document.createElement('span'); small.textContent=files[i].name + ' · needs review'; item.append(strong,small); list.prepend(item);
        }
        await open(data.id);
        if (data.duplicate_existing) status('intake-upload-status', 'This exact file is already in your visible import queue. Opened the existing record.');
      }
      status('intake-upload-status', `${files.length} document(s) staged for review.`);
    } catch (err) { status('intake-upload-status', err.message); }
    finally { button.disabled = false; }
  });
  byId('intake-register').addEventListener('click', async () => {
    if (!current) return;
    const metadata = Object.fromEntries(keys.map(k => [k, byId('intake-field-' + k).value]));
    const accepted_link_ids = [...document.querySelectorAll('.intake-link:checked')].map(c => Number(c.value));
    try {
      const selected = byId('intake-version-results').value;
      const existing_document_id = selected ? Number(selected) : null;
      const result = await api('/aria/api/policy-imports/' + encodeURIComponent(current.id) + '/register',
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({metadata,accepted_link_ids,existing_document_id})});
      status('intake-action-status', result.pending_replacement ?
        'Replacement staged under the existing policy. Its current approved version is unchanged until independent verification.' :
        `Registered document ${result.document_id}. An independent approver can now verify external approval.`);
      await open(current.id);
    } catch(err) { status('intake-action-status', err.message); }
  });
  byId('intake-version-search').addEventListener('click', async () => {
    if (!current || current.state !== 'needs_review') return;
    try {
      const data = await api(`/aria/api/policy-imports/${encodeURIComponent(current.id)}/version-candidates?q=${encodeURIComponent(byId('intake-version-query').value.trim())}`);
      const select = byId('intake-version-results');
      select.replaceChildren(new Option('Create a new policy', ''));
      data.documents.forEach(doc => select.add(new Option(`${doc.doc_id} · ${doc.title} · current ${doc.version}`, String(doc.id))));
      status('intake-action-status', data.documents.length ? 'Choose the approved policy this file updates.' : 'No eligible policy found in this ownership scope.');
    } catch(err) { status('intake-action-status', err.message); }
  });
  byId('intake-verify').addEventListener('click', async () => {
    if (!current) return;
    const body = {approver:byId('intake-approver').value,approved_at:byId('intake-date').value,proof:byId('intake-proof').value};
    try {
      const result = await api('/aria/api/policy-imports/' + encodeURIComponent(current.id) + '/verify-external',
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      await open(current.id);
      status('intake-action-status', result.replacement_adopted ?
        'The annual replacement is now current. The previous approved version remains available in the Vault.' :
        'External approval verified. The imported policy is now in force.');
    } catch(err) { status('intake-action-status', err.message); }
  });
  byId('intake-control-search').addEventListener('click', async () => {
    try {
      const q = byId('intake-control-query').value.trim();
      const data = await api('/aria/api/policy-import-controls?q=' + encodeURIComponent(q));
      const results = byId('intake-control-results'); results.replaceChildren();
      data.controls.forEach(control => { const option=document.createElement('option'); option.value=control.id;
        option.textContent=`${control.framework} · ${control.ref} · ${control.name}`; results.append(option); });
      status('intake-action-status', data.controls.length ? `${data.controls.length} control(s) found.` : 'No matching active controls.');
    } catch(err) { status('intake-action-status', err.message); }
  });
  byId('intake-control-add').addEventListener('click', async () => {
    if (!current) return;
    try {
      const data = await api('/aria/api/policy-imports/' + encodeURIComponent(current.id) + '/manual-link',
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
          control_id:Number(byId('intake-control-results').value),anchor:byId('intake-control-anchor').value,
          relationship:byId('intake-control-relation').value})});
      const checked = new Set([...document.querySelectorAll('.intake-link:checked')].map(c => Number(c.value)));
      current.links = data.links;
      renderLinks(current);
      document.querySelectorAll('.intake-link').forEach(c => { c.checked = checked.has(Number(c.value)); });
      status('intake-action-status', 'Mapping added to the review list. Confirm it before registration.');
    } catch(err) { status('intake-action-status', err.message); }
  });
  const mode = byId('intake-compose-mode');
  mode.addEventListener('change', () => {
    const replacing = mode.value !== 'replace_cover';
    byId('intake-compose-body-wrap').hidden = !replacing;
    byId('intake-compose-diagram-wrap').hidden = !replacing;
    byId('intake-cover-text-wrap').hidden = mode.value === 'replace_body';
    byId('intake-cover-logo-wrap').hidden = mode.value === 'replace_body';
  });
  byId('intake-compare-attest').addEventListener('change', () => { if (candidate) setPreview(candidate); });
  async function loadOutline() {
    if (!current || current.state !== 'registered' || !current.file_name.toLowerCase().endsWith('.docx')) return;
    const data = await api('/aria/api/policy-imports/' + encodeURIComponent(current.id) + '/outline');
    const choices = byId('intake-compose-boundary'); choices.replaceChildren();
    const blocks = byId('intake-compose-blocks'); blocks.replaceChildren();
    data.blocks.forEach(block => {
      if (block.index > 0) {
        const option = document.createElement('option'); option.value = block.index;
        option.textContent = `${block.index}: ${block.preview || block.kind}`; choices.append(option);
      }
      const row = document.createElement('label');
      const check = document.createElement('input'); check.type = 'checkbox'; check.value = block.index; check.className = 'intake-exclude';
      const label = document.createElement('span'); label.textContent = `Exclude ${block.index}: ${block.preview || block.kind}`;
      row.append(check, label); blocks.append(row);
    });
  }
  function showPdfCopy(copy) {
    pdfCopy = copy;
    const visible = !!copy;
    byId('intake-pdf-candidate').hidden = !visible;
    byId('intake-pdf-review').hidden = !visible;
    byId('intake-pdf-approve').hidden = !visible || !copy.can_decide;
    byId('intake-pdf-reject').hidden = !visible || !copy.can_decide;
    if (visible) {
      const original = '/aria/api/policy-imports/' + encodeURIComponent(current.id) + '/source';
      const rendition = `/aria/api/policy-imports/${encodeURIComponent(current.id)}/pdf-cover/${encodeURIComponent(copy.id)}`;
      byId('intake-pdf-candidate').href = rendition;
      byId('intake-pdf-original').src = original;
      byId('intake-pdf-output').src = rendition;
      status('intake-action-status', copy.state === 'approved' ? 'Presentation copy approved and stored in the Vault.' :
        copy.state === 'rejected' ? 'Presentation copy rejected.' : 'Review copy pending independent comparison.');
    }
  }
  async function loadPdf() {
    if (!current || current.state !== 'registered' || !current.file_name.toLowerCase().endsWith('.pdf')) return;
    const data = await api('/aria/api/policy-imports/' + encodeURIComponent(current.id) + '/pdf-pages');
    const select = byId('intake-pdf-boundary'); select.replaceChildren();
    for (let n = 2; n <= data.pages; n++) { const option = document.createElement('option'); option.value = n - 1; option.textContent = `Page ${n}`; select.append(option); }
    showPdfCopy(data.latest);
  }
  byId('intake-pdf-create').addEventListener('click', async () => {
    if (!current) return;
    const button=byId('intake-pdf-create'); button.disabled=true;
    try {
      const result = await api(`/aria/api/policy-imports/${encodeURIComponent(current.id)}/pdf-cover`,
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({first_body_page:Number(byId('intake-pdf-boundary').value)})});
      showPdfCopy({id:result.rendition_id,state:result.state,can_decide:false});
      status('intake-action-status', 'Review copy created. Ask a different policy approver to compare and decide.');
    } catch(err) { status('intake-action-status', err.message); }
    finally { button.disabled=false; }
  });
  async function decidePdf(approve) {
    if (!pdfCopy || !current) return;
    try {
      const result = await api(`/aria/api/policy-imports/${encodeURIComponent(current.id)}/pdf-cover/${encodeURIComponent(pdfCopy.id)}/decide`,
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approve,note:byId('intake-pdf-note').value})});
      pdfCopy.state=result.state; pdfCopy.can_decide=false; showPdfCopy(pdfCopy);
    } catch(err) { status('intake-action-status', err.message); }
  }
  byId('intake-pdf-approve').addEventListener('click', () => decidePdf(true));
  byId('intake-pdf-reject').addEventListener('click', () => decidePdf(false));
  function diagram() {
    const raw = byId('intake-diagram-nodes').value.trim();
    if (!raw) return [];
    const nodes = raw.split(/\r?\n/).filter(Boolean).map(line => {
      const separator = line.indexOf(':');
      if (separator < 1) throw new Error('Use ID: label for each diagram node.');
      return {id:line.slice(0, separator).trim(),label:line.slice(separator + 1).trim()};
    });
    const edges = byId('intake-diagram-edges').value.trim().split(/\r?\n/).filter(Boolean).map(line => {
      const parts = line.split('>');
      if (parts.length !== 2) throw new Error('Use FROM>TO for each diagram edge.');
      return {from:parts[0].trim(),to:parts[1].trim()};
    });
    return [{kind:byId('intake-diagram-kind').value,caption:byId('intake-diagram-caption').value,
      alt_text:byId('intake-diagram-alt').value,nodes,edges}];
  }
  byId('intake-compose-submit').addEventListener('click', async () => {
    if (!current) return;
    const button = byId('intake-compose-submit'); button.disabled = true;
    try {
      async function imageBase64(file, label) {
        if (!file) return '';
        if (file.size > 2 * 1024 * 1024 || !['image/png', 'image/jpeg'].includes(file.type)) {
          throw new Error(`Choose a PNG or JPEG ${label} under 2 MB.`);
        }
        const bytes = new Uint8Array(await file.arrayBuffer());
        let binary = '';
        for (let i = 0; i < bytes.length; i += 8192) {
          binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
        }
        return btoa(binary);
      }
      const coverLogo = mode.value === 'replace_body' ? '' :
        await imageBase64(byId('intake-cover-logo').files[0], 'logo');
      const figureFile = byId('intake-figure').files[0];
      const figure = mode.value === 'replace_cover' || !figureFile ? null :
        {image_base64:await imageBase64(figureFile, 'figure'),
          caption:byId('intake-figure-caption').value,alt_text:byId('intake-figure-alt').value};
      const selection = {mode:mode.value,boundary:Number(byId('intake-compose-boundary').value),
        exclude_blocks:[...document.querySelectorAll('.intake-exclude:checked')].map(c => Number(c.value)),
        clear_headers:byId('intake-compose-clear-headers').checked,
        cover_text:mode.value === 'replace_body' ? '' : byId('intake-cover-text').value,
        cover_logo_base64:coverLogo,
        replacement_body:byId('intake-compose-body').value,diagrams:diagram(),figure};
      const result = await api('/aria/api/policy-imports/' + encodeURIComponent(current.id) + '/compose',
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(selection)});
      candidate = {id:result.draft_id,state:'editing',lock_version:result.lock_version};
      byId('intake-compose-review').hidden = false;
      byId('intake-candidate-file').hidden = false;
      byId('intake-candidate-file').href = '/aria/api/policy-imports/' + encodeURIComponent(current.id) + '/candidate/' + encodeURIComponent(candidate.id);
      byId('intake-original-compare').textContent = current.extracted.spans.map(s => `${s.anchor}: ${s.text}`).join('\n\n');
      byId('intake-build-preview').hidden = false;
      byId('intake-compare-attest').checked = false;
      setPreview(candidate);
      status('intake-action-status', 'Candidate created. Build the PDF, compare it with the original, then confirm it for internal approval.');
    } catch (err) { status('intake-action-status', err.message); }
    finally { button.disabled = false; }
  });
  byId('intake-build-preview').addEventListener('click', async () => {
    if (!candidate) return;
    const button = byId('intake-build-preview'); button.disabled = true;
    try {
      const result = await api(`/aria/api/policy-drafts/${encodeURIComponent(candidate.id)}/build`,
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_lock_version:candidate.lock_version})});
      candidate = result.draft;
      button.hidden = true;
      setPreview(candidate);
      status('intake-action-status', 'Review the exact PDF and original before confirming.');
    } catch (err) { status('intake-action-status', err.message); }
    finally { button.disabled = false; }
  });
  byId('intake-confirm-candidate').addEventListener('click', async () => {
    if (!candidate || !byId('intake-compare-attest').checked) return;
    try {
      const result = await api(`/aria/api/policy-drafts/${encodeURIComponent(candidate.id)}/confirm`,
        {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({build_id:candidate.build_id,expected_lock_version:candidate.lock_version})});
      byId('intake-confirm-candidate').disabled = true;
      byId('intake-workbench-link').hidden = false;
      byId('intake-workbench-link').href = `/aria/documents/${encodeURIComponent(result.doc_id)}/workbench`;
      status('intake-action-status', 'Candidate version recorded. Open the workbench to request independent approval. The existing approved version remains current.');
    } catch (err) { status('intake-action-status', err.message); }
  });
  const oldOpen = open;
  open = async id => { await oldOpen(id); try { await loadOutline(); await loadPdf(); } catch (err) { status('intake-action-status', err.message); } };
})();
