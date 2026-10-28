(function () {
  'use strict';
  const root = document.getElementById('evidenceBatch');
  if (!root) return;
  const picker = document.getElementById('ebFiles');
  const queue = document.getElementById('ebQueue');
  const summary = document.getElementById('ebSummary');
  const upload = document.getElementById('ebUpload');
  let scopes = [];
  let rows = [];
  let busy = false;
  const categories = [
    ['general', 'General'], ['policy', 'Policy'], ['certificate', 'Certificate'],
    ['screenshot', 'Screenshot'], ['report', 'Report'], ['audit_completion', 'Audit completion'],
    ['control_assessment', 'Control assessment'], ['risk_assessment', 'Risk assessment'],
    ['incident_record', 'Incident record'], ['breach_record', 'Breach record'],
    ['procedure', 'Procedure'], ['training', 'Training record']
  ];
  const element = (tag, content, className) => {
    const node = document.createElement(tag);
    node.textContent = content || '';
    if (className) node.className = className;
    return node;
  };
  const field = (label, node) => {
    const wrapper = element('label', '');
    wrapper.appendChild(element('span', label));
    wrapper.appendChild(node);
    return wrapper;
  };
  const select = (options, value, onChange) => {
    const node = document.createElement('select');
    node.appendChild(new Option('Choose…', ''));
    options.forEach(([key, label]) => node.appendChild(new Option(label, key)));
    node.value = value || '';
    node.addEventListener('change', () => onChange(node.value));
    return node;
  };
  const input = (value, onChange, type = 'text') => {
    const node = document.createElement('input');
    node.type = type; node.value = value || '';
    node.addEventListener('change', () => onChange(node.value));
    return node;
  };
  const edit = (row, name, value) => {
    row[name] = value;
    row.reviewed = false;
    refresh();
  };
  function refresh() {
    queue.replaceChildren();
    rows.forEach((row, index) => {
      const card = element('article', '', 'eb-row');
      card.appendChild(element('div', row.file.name, 'eb-name'));
      const grid = element('div', '', 'eb-grid');
      grid.appendChild(field('Title', input(row.title, value => edit(row, 'title', value))));
      grid.appendChild(field('Filing scope', select(scopes, row.scope, value => edit(row, 'scope', value))));
      grid.appendChild(field('Category', select(categories, row.category, value => edit(row, 'category', value))));
      grid.appendChild(field('Review due', input(row.reviewDue, value => edit(row, 'reviewDue', value), 'date')));
      const reviewed = input('', () => {}, 'checkbox');
      reviewed.checked = row.reviewed;
      reviewed.addEventListener('change', () => { row.reviewed = reviewed.checked; updateSummary(); });
      grid.appendChild(field('Checked for filing', reviewed));
      card.appendChild(grid);
      const state = element('p', row.message || 'Waiting for review', 'eb-state');
      state.dataset.state = row.state;
      card.appendChild(state);
      if (row.state === 'duplicate' && Number.isSafeInteger(row.existingId) && row.existingId > 0) {
        const link = element('a', 'Review the existing Vault file', 'btn btn-secondary');
        link.href = `/evidence/?open=item:${row.existingId}`;
        card.appendChild(link);
      }
      if (row.state !== 'uploaded' && !busy) {
        const remove = element('button', 'Remove from queue', 'btn btn-secondary');
        remove.type = 'button';
        remove.addEventListener('click', () => { rows.splice(index, 1); refresh(); });
        card.appendChild(remove);
      }
      if (row.state === 'uploaded' || busy) card.querySelectorAll('input,select').forEach(node => node.disabled = true);
      queue.appendChild(card);
    });
    updateSummary();
  }
  function updateSummary() {
    const ready = rows.filter(row => row.reviewed && row.state !== 'uploaded' && row.file.size <= 100 * 1024 * 1024 && row.scope && row.title.trim());
    upload.disabled = busy || !ready.length;
    picker.disabled = busy || !scopes.length;
    document.getElementById('ebClear').disabled = busy;
    const complete = rows.filter(row => row.state === 'uploaded').length;
    summary.textContent = `${rows.length} staged · ${ready.length} reviewed and ready · ${complete} uploaded`;
  }
  picker.addEventListener('change', () => {
    const selected = Array.from(picker.files || []);
    if (rows.length + selected.length > 50) {
      summary.textContent = 'A queue can contain at most 50 files. Clear completed files or choose fewer.';
      picker.value = '';
      return;
    }
    selected.forEach(file => {
      const oversized = file.size > 100 * 1024 * 1024;
      rows.push({file, title: file.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim(),
        scope: scopes.length === 1 ? scopes[0][0] : '', category: 'general', reviewDue: '',
        reviewed: false, state: oversized ? 'failed' : 'staged',
        message: oversized ? 'File exceeds the 100 MB limit' : 'Waiting for review'});
    });
    picker.value = '';
    refresh();
  });
  upload.addEventListener('click', async () => {
    if (busy) return;
    busy = true; refresh();
    for (const row of rows) {
      if (!row.reviewed || row.state === 'uploaded' || row.file.size > 100 * 1024 * 1024 || !row.scope || !row.title.trim()) continue;
      row.state = 'uploading'; row.message = 'Uploading and checking…'; refresh();
      const body = new FormData();
      body.append('file', row.file); body.append('title', row.title.trim());
      body.append('category', row.category); body.append('filing_scope', row.scope);
      if (row.reviewDue) body.append('review_due_date', row.reviewDue);
      try {
        await ApiClient.request('/evidence/api/items', {method: 'POST', body, timeoutMs: 120000,
          actionId: 'evidence.batch_upload'});
        row.state = 'uploaded'; row.message = 'Filed in the Vault. Link it to the supported claim for independent review.';
      } catch (error) {
        row.state = error.status === 409 ? 'duplicate' : 'failed';
        if (error.status === 409) {
          row.existingId = error.body && !error.body.hidden ? Number(error.body.existing_id) : null;
          row.message = error.body && error.body.hidden ?
            'This file already exists in a place you cannot open.' : 'Possible duplicate. Review it in the Vault before retrying.';
        } else row.message = error.detail || 'Upload failed. Review this file before retrying.';
        row.reviewed = false;
      }
      refresh();
    }
    busy = false; refresh();
  });
  document.getElementById('ebClear').addEventListener('click', () => {
    if (busy) return;
    rows = rows.filter(row => row.state !== 'uploaded');
    refresh();
  });
  ApiClient.request('/evidence/api/company-views', {actionId: 'evidence.batch_scopes'})
    .then(data => {
      if (data.can_file_org_wide && data.organization)
        scopes.push(['organization', `${data.organization.name} · organization-wide`]);
      (data.units || []).forEach(unit => scopes.push([`unit:${unit.id}`, unit.name]));
      picker.disabled = !scopes.length;
      summary.textContent = scopes.length ? 'Choose files, then check each filing scope.' : 'No authorized filing scope is available.';
    })
    .catch(error => { picker.disabled = true; summary.textContent = error.detail || 'Filing scopes are unavailable.'; });
})();
