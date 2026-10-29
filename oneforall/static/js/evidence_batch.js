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
    row[`${name}Edited`] = true;
    if (name === 'scope') row.replaceVerified = null;
    row.reviewed = false;
    refresh();
  };
  async function verifyReplacement(row) {
    row.replaceVerified = null;
    row.reviewed = false;
    if (!/^[1-9][0-9]*$/.test(row.replaceId) || !Number.isSafeInteger(Number(row.replaceId))) {
      row.message = 'Enter the current Vault document ID to replace.';
      refresh(); return;
    }
    row.state = 'checking'; row.message = 'Checking the current version and filing scope…'; refresh();
    try {
      const item = await ApiClient.request(`/evidence/api/items/${row.replaceId}`, {
        actionId: 'evidence.batch_check_version'
      });
      const targetScope = item.business_unit_id == null ? 'organization' : `unit:${item.business_unit_id}`;
      if (item.status !== 'current' || item.category === 'generated_record' || row.scope !== targetScope) {
        row.message = 'Choose a current, replaceable Vault document in the same filing scope.';
      } else {
        row.replaceVerified = {id: item.id, title: item.title, version: item.version,
          category: item.category, reviewDue: item.review_due_date || '', fileName: item.file_name || ''};
        row.message = `Checked: ${item.title}, version ${item.version}. Review the new file and confirm before upload.`;
      }
    } catch (error) {
      row.message = error.status === 404 ? 'That Vault document is unavailable in your scope.' :
        (error.detail || 'Could not check the current Vault document.');
    }
    row.state = 'staged'; refresh();
  }
  async function suggest(row) {
    row.reviewed = false; row.state = 'extracting'; row.message = 'Extracting locally for review…'; refresh();
    const body = new FormData(); body.append('file', row.file);
    try {
      const result = await ApiClient.request('/evidence/api/batch/suggest', {
        method: 'POST', body, timeoutMs: 60000, actionId: 'evidence.batch_suggest'
      });
      const hints = result.suggestions || {};
      row.suggestions = hints;
      if (hints.title && !row.titleEdited) row.title = hints.title.value;
      const types = {Policy:'policy', Procedure:'procedure', Record:'general'};
      if (hints.doc_type && !row.categoryEdited && types[hints.doc_type.value])
        row.category = types[hints.doc_type.value];
      if (hints.review_date && !row.reviewDueEdited) row.reviewDue = hints.review_date.value;
      row.reviewed = false; row.state = 'staged';
      row.message = 'Suggestions extracted. Check each value against the original before filing.';
    } catch (error) {
      row.state = 'staged'; row.message = error.detail || 'Suggestions unavailable. Review the original manually.';
    }
    refresh();
  }
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
      const versionMode = select([['new', 'New document'], ['replace', 'New version of a Vault document']],
        row.versionMode, value => {
          row.versionMode = value; row.replaceVerified = null; row.reviewed = false; refresh();
        });
      grid.appendChild(field('File as', versionMode));
      const reviewed = input('', () => {}, 'checkbox');
      reviewed.checked = row.reviewed;
      reviewed.addEventListener('change', () => { row.reviewed = reviewed.checked; updateSummary(); });
      grid.appendChild(field('Checked for filing', reviewed));
      card.appendChild(grid);
      if (row.versionMode === 'replace') {
        const replacement = element('div', '', 'eb-replacement');
        replacement.appendChild(field('Current Vault document ID', input(row.replaceId, value => {
          row.replaceId = value.trim(); row.replaceVerified = null; row.reviewed = false; refresh();
        })));
        const check = element('button', 'Check current version', 'btn btn-secondary');
        check.type = 'button'; check.disabled = busy || row.state === 'checking' || row.state === 'uploaded';
        check.addEventListener('click', () => verifyReplacement(row));
        replacement.appendChild(check);
        if (row.replaceVerified) {
          const link = element('a', `Open ${row.replaceVerified.title} · v${row.replaceVerified.version}`, 'eb-note');
          link.href = `/evidence/?open=item:${row.replaceVerified.id}`;
          replacement.appendChild(link);
        }
        card.appendChild(replacement);
        if (row.replaceVerified) {
          const before = row.replaceVerified;
          const compare = element('div', '', 'eb-compare');
          compare.appendChild(element('strong', 'Compare before filing'));
          [['Title', before.title, row.title], ['Type', before.category, row.category],
            ['Review due', before.reviewDue || 'Not set', row.reviewDue || 'Not set'],
            ['File', before.fileName || 'No file', row.file.name]].forEach(([label, oldValue, newValue]) => {
              const line = element('p', `${label}: ${oldValue} → ${newValue}`);
              if (oldValue !== newValue) line.classList.add('is-changed');
              compare.appendChild(line);
            });
          compare.appendChild(element('small', 'This compares metadata only. Open both files to review content changes. Carried links require a new review.'));
          card.appendChild(compare);
        }
      }
      if (row.suggestions) {
        const hints = element('div', '', 'eb-note');
        Object.entries(row.suggestions).forEach(([name, item]) => {
          hints.appendChild(element('p', `${name.replaceAll('_', ' ')}: ${item.value} · ${item.anchor} · ${item.kind}${item.note ? ` · ${item.note}` : ''}`));
        });
        card.appendChild(hints);
      }
      const state = element('p', row.message || 'Waiting for review', 'eb-state');
      state.dataset.state = row.state;
      card.appendChild(state);
      if (row.state === 'duplicate' && Number.isSafeInteger(row.existingId) && row.existingId > 0) {
        const link = element('a', 'Review the existing Vault file', 'btn btn-secondary');
        link.href = `/evidence/?open=item:${row.existingId}`;
        card.appendChild(link);
      }
      if (row.state !== 'uploaded' && !['extracting', 'checking'].includes(row.state) && !busy) {
        if (/\.(docx|pdf)$/i.test(row.file.name) && row.file.size <= 25 * 1024 * 1024 && row.state !== 'extracting') {
          const extract = element('button', 'Extract suggestions', 'btn btn-secondary');
          extract.type = 'button'; extract.addEventListener('click', () => suggest(row));
          card.appendChild(extract);
        }
        const remove = element('button', 'Remove from queue', 'btn btn-secondary');
        remove.type = 'button';
        remove.addEventListener('click', () => { rows.splice(index, 1); refresh(); });
        card.appendChild(remove);
      }
      if (row.state === 'uploaded' || ['extracting', 'checking'].includes(row.state) || busy)
        card.querySelectorAll('input,select').forEach(node => node.disabled = true);
      queue.appendChild(card);
    });
    updateSummary();
  }
  function updateSummary() {
    const ready = rows.filter(row => row.reviewed && !['uploaded','extracting','checking'].includes(row.state) &&
      row.file.size <= 100 * 1024 * 1024 && row.scope && row.title.trim() &&
      (row.versionMode !== 'replace' || row.replaceVerified?.id === Number(row.replaceId)));
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
        versionMode: 'new', replaceId: '', replaceVerified: null,
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
      if (!row.reviewed || row.state === 'uploaded' || row.file.size > 100 * 1024 * 1024 || !row.scope || !row.title.trim() ||
          (row.versionMode === 'replace' && row.replaceVerified?.id !== Number(row.replaceId))) continue;
      row.state = 'uploading'; row.message = 'Uploading and checking…'; refresh();
      const body = new FormData();
      body.append('file', row.file); body.append('title', row.title.trim());
      body.append('category', row.category); body.append('filing_scope', row.scope);
      if (row.versionMode === 'replace') body.append('replace_id', row.replaceId);
      if (row.reviewDue) body.append('review_due_date', row.reviewDue);
      try {
        await ApiClient.request('/evidence/api/items', {method: 'POST', body, timeoutMs: 120000,
          actionId: 'evidence.batch_upload'});
        row.state = 'uploaded'; row.message = row.versionMode === 'replace' ?
          'New version filed. Review the carried links and supported claims.' :
          'Filed in the Vault. Link it to the supported claim for independent review.';
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
