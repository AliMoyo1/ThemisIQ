(function () {
  'use strict';
  const root = document.getElementById('groupCases');
  if (!root) return;
  const get = id => document.getElementById(id);
  let page = 1;
  let selected = null;
  function el(tag, value, className) {
    const item = document.createElement(tag);
    item.textContent = value == null ? '' : String(value);
    if (className) item.className = className;
    return item;
  }
  function errorMessage(error) { return error.detail || error.message || 'The case could not be loaded.'; }
  async function load(nextPage) {
    try {
      const data = await ApiClient.request(`/evidence/api/group/cases?page=${nextPage}`);
      page = nextPage;
      get('gcCreate').hidden = !data.can_manage;
      const list = get('gcList');
      if (nextPage === 1) list.replaceChildren();
      for (const row of data.items) {
        const card = el('article', '', 'gc-card');
        card.append(el('strong', `${row.reference} · ${row.title}`));
        card.append(el('small', `${row.status.replaceAll('_', ' ')} · ${row.request_count} proof requests`));
        const button = el('button', 'Open case', 'btn btn-secondary');
        button.type = 'button';
        button.addEventListener('click', () => openCase(row.id));
        const actions = el('div', '', 'gc-actions');
        actions.append(button);
        card.append(actions);
        list.append(card);
      }
      if (!list.childElementCount) list.append(el('p', 'No group cases yet.'));
      get('gcMore').hidden = !data.has_more;
    } catch (error) { get('gcStatus').textContent = errorMessage(error); }
  }
  async function openCase(id) {
    try {
      const data = await ApiClient.request(`/evidence/api/group/cases/${id}`);
      selected = id;
      get('gcDetailPanel').hidden = false;
      const caseRow = data.case;
      const detail = get('gcDetail');
      detail.replaceChildren(el('p', `${caseRow.reference} · ${caseRow.title}`),
        el('p', caseRow.position), el('p', `Status: ${caseRow.status.replaceAll('_', ' ')}`));
      if (caseRow.close_reason) detail.append(el('p', `Conclusion: ${caseRow.close_reason}`));
      get('gcLink').hidden = !data.can_manage;
      get('gcClose').hidden = !data.can_close;
      const requests = get('gcRequests');
      requests.replaceChildren();
      for (const row of data.requests) {
        const card = el('div', '', 'gc-card');
        card.append(el('strong', `#${row.id} · ${row.requirement_ref}`));
        card.append(el('small', `Source organization ${row.source_org_id} · ${row.status} · verdict ${row.verdict || 'pending'}`));
        requests.append(card);
      }
      if (!data.requests.length) requests.append(el('p', 'Link a proof request to document the evidence sought.'));
      const events = get('gcEvents');
      events.replaceChildren();
      for (const row of data.events) events.append(el('div', `${row.action.replaceAll('_', ' ')} · ${row.detail}`, 'gc-card'));
    } catch (error) { get('gcStatus').textContent = errorMessage(error); }
  }
  async function post(path, body, message) {
    get('gcStatus').textContent = 'Saving…';
    try {
      const result = await ApiClient.request(path, {method: 'POST', body, actionId: 'group.case'});
      get('gcStatus').textContent = message;
      await load(1);
      if (selected) await openCase(selected);
      return result;
    } catch (error) { get('gcStatus').textContent = errorMessage(error); }
  }
  get('gcCreate').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const result = await post('/evidence/api/group/cases', Object.fromEntries(data.entries()), 'Case created.');
    if (result) { form.reset(); await openCase(result.id); }
  });
  get('gcLink').addEventListener('submit', async event => {
    event.preventDefault();
    if (!selected) return;
    const form = event.currentTarget;
    const result = await post(`/evidence/api/group/cases/${selected}/requests`,
      {request_id: Number(new FormData(form).get('request_id'))}, 'Proof request linked.');
    if (result) form.reset();
  });
  get('gcClose').addEventListener('submit', async event => {
    event.preventDefault();
    if (!selected) return;
    await post(`/evidence/api/group/cases/${selected}/close`,
      {reason: new FormData(event.currentTarget).get('reason')}, 'Case closed.');
  });
  get('gcMore').addEventListener('click', () => load(page + 1));
  load(1).then(() => {
    const requested = Number(new URLSearchParams(location.search).get('case'));
    if (Number.isSafeInteger(requested) && requested > 0) openCase(requested);
  });
})();
