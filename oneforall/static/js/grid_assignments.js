(function () {
  'use strict';
  const root = document.getElementById('gridAssignments');
  if (!root) return;
  const get = id => document.getElementById(id);
  let current = null;
  function el(tag, value, className) {
    const node = document.createElement(tag);
    node.textContent = value == null ? '' : String(value);
    if (className) node.className = className;
    return node;
  }
  function button(label, kind, onClick) {
    const b = el('button', label, 'btn ' + (kind || 'btn-secondary'));
    b.type = 'button';
    b.addEventListener('click', onClick);
    return b;
  }
  function say(text) { get('gaStatus').textContent = text; }
  function message(error) { return (error && (error.detail || error.message)) || 'That did not work. Reload the page and try again.'; }
  // The page is redrawn before success is announced, so nothing typed after the message lands in a form about to go.
  async function call(path, body, done, refresh) {
    say('Saving…');
    let result;
    try {
      result = await ApiClient.request(path, {method: 'POST', body, actionId: 'grid.assignment'});
    } catch (error) { say(message(error)); return null; }
    if (refresh) await refresh(result);
    if (done) say(done);
    return result || true;
  }
  function summaryCard(row, extra) {
    const card = el('div', '', 'ga-card');
    card.append(el('strong', row.title));
    card.append(el('small', `${row.audit} · ${row.state_label} · due ${row.due_date} · ${row.accepted} of ${row.items} accepted` + (extra ? ` · ${extra}` : '')));
    const actions = el('div', '', 'ga-actions');
    actions.append(button('Open', 'btn-secondary', () => open(row.id)));
    card.append(actions);
    return card;
  }
  async function load() {
    let data;
    try { data = await ApiClient.request('/grid/api/assignments'); } catch (error) { say(message(error)); return; }
    const answer = get('gaAnswer');
    answer.replaceChildren(...data.to_answer.map(r => summaryCard(r)));
    if (!data.to_answer.length) answer.append(el('p', 'Nothing has been sent to you.', 'ga-muted'));
    const review = get('gaReview');
    review.replaceChildren(...data.to_review.map(r => summaryCard(r)));
    get('gaReviewPanel').hidden = !data.to_review.length;
    get('gaManagePanel').hidden = !data.can_create && !data.managed.length;
    const managed = get('gaManaged');
    managed.replaceChildren(...data.managed.map(r => summaryCard(r, r.assignee)));
    if (!data.managed.length) managed.append(el('p', 'No assignments yet.', 'ga-muted'));
    get('gaCreate').hidden = !data.can_create;
    if (data.can_create && !get('gaCreate').dataset.loaded) await loadAudits();
  }
  async function loadAudits() {
    const form = get('gaCreate');
    form.dataset.loaded = '1';
    try {
      const audits = await ApiClient.request('/grid/api/assignments/audits');
      form.elements.audit_id.append(...audits.items.map(a => new Option(a.name, a.id)));
    } catch (error) { say(message(error)); }
  }
  async function loadAudit(auditId) {
    const box = get('gaControls');
    const form = get('gaCreate');
    box.replaceChildren(el('legend', 'Controls (up to 50)'));
    if (!auditId) return;
    let data;
    try { data = await ApiClient.request('/grid/api/assignments/audits/' + encodeURIComponent(auditId)); }
    catch (error) { say(message(error)); return; }
    data.controls.forEach(c => {
      const label = el('label', '');
      const box1 = document.createElement('input');
      box1.type = 'checkbox'; box1.name = 'control'; box1.value = c.id; box1.disabled = c.busy;
      label.append(box1, el('span', `${c.ref || ''} ${c.name}` + (c.busy ? ' (already sent in another assignment)' : '')));
      box.append(label);
    });
    if (!data.controls.length) box.append(el('p', 'This audit has no controls yet.', 'ga-muted'));
    form.elements.assignee_id.replaceChildren(...data.respondents.map(p => new Option(p.name, p.id)));
    form.elements.reviewer_id.replaceChildren(...data.reviewers.map(p => new Option(p.name, p.id)));
    if (!form.elements.title.value) form.elements.title.value = `${data.audit.name}: questions`;
  }
  get('gaCreate').elements.audit_id.addEventListener('change', event => loadAudit(event.target.value));
  get('gaCreate').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.target;
    const controls = [...form.querySelectorAll('input[name="control"]:checked')].map(i => Number(i.value));
    if (!controls.length) { say('Choose at least one control.'); return; }
    await call('/grid/api/assignments', {
      audit_id: Number(form.elements.audit_id.value), control_ids: controls,
      assignee_id: Number(form.elements.assignee_id.value), reviewer_id: Number(form.elements.reviewer_id.value),
      due_date: form.elements.due_date.value, title: form.elements.title.value,
      instructions: form.elements.instructions.value}, 'Saved as a draft. Check it, then send it.',
      async made => { await load(); await open(made.id, true); });
  });

  function itemView(item, data) {
    const box = el('article', '', 'ga-item');
    const head = el('div', '', 'ga-actions');
    head.append(el('strong', `${item.ref || ''} ${item.name}`));
    const chip = el('span', item.review_state.replace('_', ' '), 'ga-chip is-' + item.review_state);
    head.append(chip);
    box.append(head);
    if (item.description) box.append(el('p', item.description, 'ga-muted'));
    if (item.required_evidence.length) box.append(el('p', 'Evidence required: ' + item.required_evidence.join(', '), 'ga-muted'));
    if (item.review_note) box.append(el('p', 'Reviewer: ' + item.review_note, 'ga-note'));
    const editable = data.can_answer && item.review_state !== 'accepted';
    if (editable) {
      const form = el('form', '', 'ga-form');
      const response = document.createElement('textarea');
      response.name = 'response'; response.rows = 4; response.maxLength = 4000; response.value = item.response;
      const observation = document.createElement('textarea');
      observation.name = 'observation'; observation.rows = 2; observation.maxLength = 2000; observation.value = item.observation;
      const l1 = el('label', 'Your answer', 'ga-wide'); l1.append(response);
      const l2 = el('label', 'Anything the reviewer should know', 'ga-wide'); l2.append(observation);
      const save = el('button', 'Save answer', 'btn btn-primary'); save.type = 'submit';
      form.append(l1, l2, save);
      form.addEventListener('submit', async event => {
        event.preventDefault();
        await call(`/grid/api/assignments/${data.id}/items/${item.id}/answer`,
          {version: current.version, response: response.value, observation: observation.value}, 'Answer saved.',
          () => open(data.id, true));
      });
      box.append(form);
    } else {
      box.append(el('p', item.response || 'No answer yet.', 'ga-note'));
      if (item.observation) box.append(el('p', item.observation, 'ga-note ga-muted'));
    }
    const proofList = el('div', '');
    proofList.append(el('h3', 'Proof'));
    if (!item.proof.length) proofList.append(el('p', 'No proof chosen.', 'ga-muted'));
    item.proof.forEach(p => {
      const row = el('div', '', 'ga-actions');
      row.append(el('span', `${p.title} (version ${p.version}) · ${p.review}` + (p.changed ? ' · changed since it was chosen' : '')));
      if (editable) row.append(button('Remove', 'btn-secondary', async () => {
        await call(`/grid/api/assignments/${data.id}/items/${item.id}/proof/${p.id}/remove`, {version: current.version},
          'Proof removed.', () => open(data.id, true));
      }));
      proofList.append(row);
    });
    if (editable) {
      const search = el('form', '', 'ga-form');
      const q = document.createElement('input');
      q.type = 'search'; q.name = 'q'; q.maxLength = 100; q.placeholder = 'Search your Evidence Vault files';
      const label = el('label', 'Attach existing proof', 'ga-wide'); label.append(q);
      const find = el('button', 'Search', 'btn btn-secondary'); find.type = 'submit';
      const results = el('div', '', 'ga-wide');
      search.append(label, find, results);
      search.addEventListener('submit', async event => {
        event.preventDefault();
        let found;
        try { found = await ApiClient.request(`/grid/api/assignments/${data.id}/proof-choices?q=${encodeURIComponent(q.value)}`); }
        catch (error) { say(message(error)); return; }
        results.replaceChildren(...found.items.map(f => {
          const row = el('div', '', 'ga-actions');
          row.append(el('span', `${f.title} (version ${f.version})`));
          row.append(button('Choose', 'btn-secondary', async () => {
            await call(`/grid/api/assignments/${data.id}/items/${item.id}/proof`, {version: current.version, evidence_id: f.id},
              'Proof chosen.', () => open(data.id, true));
          }));
          return row;
        }));
        if (!found.items.length) results.append(el('p', 'No current file you can open matches. Upload it in the Evidence Vault first.', 'ga-muted'));
      });
      proofList.append(search);
    }
    box.append(proofList);
    if (data.can_review && ['unreviewed', 'resubmitted'].includes(item.review_state)) {
      const form = el('form', '', 'ga-form');
      const note = document.createElement('textarea');
      note.name = 'note'; note.rows = 2; note.maxLength = 1000;
      const label = el('label', 'Note (required when asking for a change)', 'ga-wide'); label.append(note);
      const actions = el('div', '', 'ga-actions ga-wide');
      actions.append(button('Accept answer and proof', 'btn-primary', () => review(data, item, 'accept', note.value)));
      actions.append(button('Request a change', 'btn-secondary', () => review(data, item, 'changes', note.value)));
      form.append(label, actions);
      box.append(form);
    }
    return box;
  }
  async function review(data, item, decision, note) {
    await call(`/grid/api/assignments/${data.id}/items/${item.id}/review`, {version: current.version, decision, note},
      decision === 'accept' ? 'Answer accepted.' : 'Change requested.', refresh);
  }
  async function open(id, keepStatus) {
    let data;
    try { data = await ApiClient.request('/grid/api/assignments/' + encodeURIComponent(id)); } catch (error) { say(message(error)); return; }
    current = data;
    if (!keepStatus) say('');
    get('gaDetail').hidden = false;
    get('gaTitle').textContent = data.title;
    const meta = [data.audit, data.state_label, 'due ' + data.due_date];
    if (data.role === 'staff') meta.push('answered by ' + (data.assignee || ''), 'reviewed by ' + (data.reviewer || ''));
    get('gaMeta').textContent = meta.join(' · ');
    get('gaInstructions').textContent = data.instructions || '';
    get('gaStaff').hidden = !data.can_manage;
    get('gaLaunch').hidden = !(data.can_manage && data.state === 'draft');
    get('gaCancel').hidden = !data.can_manage;
    get('gaSubmit').hidden = !data.can_answer;
    get('gaItems').replaceChildren(...data.items.map(item => itemView(item, data)));
    const events = get('gaEvents');
    events.replaceChildren();
    if (data.events) {
      events.append(el('h3', 'History'));
      data.events.forEach(e => events.append(el('p', `${String(e.created_at).slice(0, 16)} · ${e.actor || ''} · ${e.action.replace('_', ' ')}` + (e.detail && (e.detail.reason || e.detail.note) ? `: ${e.detail.reason || e.detail.note}` : ''), 'ga-muted')));
    }
    get('gaDetail').scrollIntoView({block: 'start'});
  }
  async function refresh() { await load(); await open(current.id, true); }
  get('gaLaunch').addEventListener('click', () =>
    call(`/grid/api/assignments/${current.id}/launch`, {version: current.version}, 'Sent. The person has been told.', refresh));
  get('gaSubmit').addEventListener('click', () =>
    call(`/grid/api/assignments/${current.id}/submit`, {version: current.version}, 'Sent for review.', refresh));
  get('gaCancel').addEventListener('submit', event => {
    event.preventDefault();
    return call(`/grid/api/assignments/${current.id}/cancel`, {version: current.version, reason: event.target.elements.reason.value},
      'Cancelled.', async () => { event.target.reset(); await refresh(); });
  });
  load().then(() => {
    const wanted = new URLSearchParams(window.location.search).get('open');
    if (wanted && /^\d+$/.test(wanted)) open(Number(wanted));
  });
})();
