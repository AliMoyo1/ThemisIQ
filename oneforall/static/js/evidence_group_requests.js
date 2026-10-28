(function () {
  'use strict';
  const root = document.getElementById('groupRequests');
  if (!root) return;
  const byId = id => document.getElementById(id);
  const status = byId('grStatus');
  const list = byId('grList');
  let page = 1;
  let rows = [];
  let relationships = [];
  let hasMore = false;

  function node(tag, value, className) {
    const el = document.createElement(tag);
    el.textContent = value == null ? '' : String(value);
    if (className) el.className = className;
    return el;
  }
  function field(label, name, value, type) {
    const wrap = node('label', label, 'gr-control');
    const input = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    input.name = name;
    if (type !== 'textarea') input.type = type || 'text';
    input.value = value || '';
    input.required = true;
    wrap.append(input);
    return wrap;
  }
  function formButton(label) {
    const b = node('button', label, 'btn btn-primary');
    b.type = 'submit';
    return b;
  }
  function action(label, kind) {
    const b = node('button', label, 'btn btn-secondary');
    b.type = 'button';
    b.dataset.action = kind;
    return b;
  }
  function iso(value) {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) throw new Error('Choose a valid date and time.');
    return parsed.toISOString();
  }
  function localDateTime(value) {
    if (!value) return '';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return '';
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  }
  async function save(path, body, message) {
    status.textContent = 'Saving…';
    try {
      await ApiClient.request(path, {method: 'POST', body, actionId: 'group.request'});
      status.textContent = message;
      await load(1);
    } catch (error) {
      status.textContent = error.detail || error.message || 'Could not save this request.';
    }
  }
  function payload(form) {
    const data = new FormData(form);
    return {
      requirement_ref: data.get('requirement_ref'), purpose: data.get('purpose'),
      needed_by: iso(data.get('needed_by')),
      period_start: data.get('period_start') || null,
      period_end: data.get('period_end') || null
    };
  }
  function renderCreate() {
    const form = byId('grCreate');
    form.hidden = !relationships.length;
    byId('grNoRelationships').hidden = !!relationships.length;
    const selector = form.elements.relationship_id;
    selector.replaceChildren(new Option('Choose a source company', ''));
    relationships.forEach(row => selector.append(new Option(row.source_name, String(row.id))));
  }
  function renderCard(row) {
    const card = node('article', '', 'gr-card');
    card.append(node('strong', `${row.requirement_ref} · ${row.status.replaceAll('_', ' ')}`));
    card.append(node('small', row.purpose));
    card.append(node('small', `Needed by ${row.needed_by} · period ${row.period_start || 'unspecified'} to ${row.period_end || 'unspecified'}`));
    if (row.decision_reason) card.append(node('small', `Review: ${row.decision_reason}`));
    if (row.is_source && row.source_mapping) {
      card.append(node('small', `Source mapping: ${row.source_mapping.module} / ${row.source_mapping.entity_type} #${row.source_mapping.entity_id}`));
    }
    if (row.released_publication_id) {
      const link = node('a', 'Open released document', 'btn btn-secondary');
      link.href = `/evidence/api/group/publications/${encodeURIComponent(row.released_publication_id)}`;
      card.append(link);
    }
    const actions = node('div', '', 'gr-actions');
    if (row.can_revise) actions.append(action('Clarify and resend', 'revise'));
    if (row.can_map && row.status === 'requested') actions.append(action('Map source record', 'map'));
    if (row.can_map && row.status === 'requested') actions.append(action('Record decision', 'review'));
    if (row.can_fulfill && row.status === 'approved') actions.append(action('Fulfill with released document', 'fulfill'));
    card.append(actions);
    const detail = node('div', '', 'gr-detail');
    detail.hidden = true;
    card.append(detail);
    actions.addEventListener('click', event => {
      const control = event.target.closest('[data-action]');
      if (!control) return;
      detail.replaceChildren();
      detail.hidden = false;
      if (control.dataset.action === 'revise') reviseForm(row, detail);
      if (control.dataset.action === 'map') mapForm(row, detail);
      if (control.dataset.action === 'review') reviewForm(row, detail);
      if (control.dataset.action === 'fulfill') fulfillForm(row, detail);
    });
    return card;
  }
  function reviseForm(row, detail) {
    const form = document.createElement('form');
    form.className = 'gr-form';
    form.append(field('Requirement reference', 'requirement_ref', row.requirement_ref));
    form.append(field('Purpose', 'purpose', row.purpose, 'textarea'));
    form.append(field('Needed by', 'needed_by', localDateTime(row.needed_by), 'datetime-local'));
    form.append(field('Period from', 'period_start', row.period_start, 'date'));
    form.append(field('Period to', 'period_end', row.period_end, 'date'));
    form.elements.period_start.required = false;
    form.elements.period_end.required = false;
    form.append(formButton('Resend requirement'));
    form.addEventListener('submit', event => {
      event.preventDefault();
      try { save(`/evidence/api/group/requests/${row.id}/revision`, payload(form), 'Requirement resent.'); }
      catch (error) { status.textContent = error.message; }
    });
    detail.append(form);
  }
  function mapForm(row, detail) {
    const form = document.createElement('form');
    form.className = 'gr-form';
    const kind = node('label', 'Your source record', 'gr-control');
    const select = document.createElement('select');
    select.name = 'kind';
    const kinds = [
      ['aria/control', 'Governance control'], ['aria/document', 'Governance document'],
      ['grid/audit', 'Audit'], ['grid/control', 'Audit control'],
      ['bcm/plan', 'Continuity plan'], ['sentinel/dpia', 'DPIA'],
      ['erm/risk', 'Enterprise risk'], ['governance/application', 'AI use']
    ];
    kinds.forEach(([value, label]) => select.append(new Option(label, value)));
    kind.append(select);
    const search = field('Search records you may open', 'search', '', 'search');
    search.querySelector('input').required = false;
    const results = node('select', '');
    results.name = 'entity_id';
    results.required = true;
    const searchStatus = node('span', '', 'gr-wide');
    form.append(kind, search, results, searchStatus, formButton('Map source record'));
    let seq = 0;
    async function lookup() {
      const current = ++seq;
      const [module, entityType] = select.value.split('/');
      const q = search.querySelector('input').value.trim();
      if (q.length < 2) { results.replaceChildren(new Option('Enter at least 2 characters', '')); return; }
      searchStatus.textContent = 'Searching…';
      try {
        const matches = await ApiClient.request(`/evidence/api/search-entities?module=${encodeURIComponent(module)}&entity_type=${encodeURIComponent(entityType)}&q=${encodeURIComponent(q)}`,
          {actionId: 'group.request.map.search'});
        if (current !== seq) return;
        results.replaceChildren(new Option('Choose a source record', ''));
        matches.forEach(item => results.append(new Option(item.name, String(item.id))));
        searchStatus.textContent = `${matches.length} matches in your scope`;
      } catch (error) { if (current === seq) searchStatus.textContent = error.detail || 'Search unavailable.'; }
    }
    let timer;
    search.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(lookup, 250); });
    select.addEventListener('change', lookup);
    form.addEventListener('submit', event => {
      event.preventDefault();
      const [module, entity_type] = select.value.split('/');
      save(`/evidence/api/group/requests/${row.id}/mapping`,
        {module, entity_type, entity_id: Number(results.value)}, 'Source record mapped.');
    });
    detail.append(form);
    lookup();
  }
  function reviewForm(row, detail) {
    const form = document.createElement('form');
    form.className = 'gr-form';
    const label = node('label', 'Review outcome', 'gr-control');
    const select = document.createElement('select');
    select.name = 'decision';
    [['approved', 'Approved for fulfillment'], ['clarification', 'Need clarification'],
      ['no_proof', 'No proof available'], ['declined', 'Declined']]
      .forEach(([key, title]) => select.append(new Option(title, key)));
    label.append(select);
    form.append(label, field('Decision explanation', 'reason', '', 'textarea'), formButton('Record review'));
    form.addEventListener('submit', event => {
      event.preventDefault();
      save(`/evidence/api/group/requests/${row.id}/decisions`,
        {decision: select.value, reason: form.elements.reason.value}, 'Review recorded.');
    });
    detail.append(form);
  }
  async function fulfillForm(row, detail) {
    detail.append(node('p', 'Loading eligible releases…'));
    try {
      const data = await ApiClient.request(`/evidence/api/group/requests/${row.id}/release-candidates`,
        {actionId: 'group.request.release_candidates'});
      detail.replaceChildren();
      if (!data.items.length) {
        detail.append(node('p', 'No eligible current release. Review rights, publish the exact version, and grant the named requester access in Group sharing.'));
        return;
      }
      const form = document.createElement('form');
      form.className = 'gr-form';
      const label = node('label', 'Approved released version', 'gr-control');
      const select = document.createElement('select');
      select.name = 'publication_id';
      data.items.forEach(item => select.append(new Option(`${item.title} · v${item.version}`, String(item.id))));
      label.append(select);
      form.append(label, formButton('Fulfill request'));
      form.addEventListener('submit', event => {
        event.preventDefault();
        save(`/evidence/api/group/requests/${row.id}/fulfillment`,
          {publication_id: Number(select.value)}, 'Request fulfilled.');
      });
      detail.append(form);
    } catch (error) { detail.replaceChildren(node('p', error.detail || 'Eligible releases are unavailable.')); }
  }
  function render() {
    list.replaceChildren();
    if (!rows.length) list.append(node('p', 'No proof requests in your scope.'));
    rows.forEach(row => list.append(renderCard(row)));
    byId('grMore').hidden = !hasMore;
    renderCreate();
  }
  async function load(nextPage) {
    try {
      const data = await ApiClient.request(`/evidence/api/group/requests?page=${nextPage}`, {actionId: 'group.request.list'});
      rows = nextPage === 1 ? data.items : rows.concat(data.items);
      relationships = data.relationships;
      hasMore = data.has_more;
      page = nextPage;
      render();
    } catch (error) { status.textContent = error.detail || 'Proof requests are unavailable.'; }
  }
  byId('grCreate').addEventListener('submit', event => {
    event.preventDefault();
    try {
      const relationId = Number(event.target.elements.relationship_id.value);
      if (!relationId) throw new Error('Choose a source company.');
      save(`/evidence/api/group/relationships/${relationId}/requests`, payload(event.target), 'Request sent to source team.');
    } catch (error) { status.textContent = error.message; }
  });
  byId('grMore').addEventListener('click', () => load(page + 1));
  load(1);
})();
