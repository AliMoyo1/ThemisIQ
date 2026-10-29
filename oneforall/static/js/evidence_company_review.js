(function () {
  'use strict';
  const root = document.getElementById('companyReview');
  if (!root) return;
  const status = document.getElementById('coStatus');
  const list = document.getElementById('coList');
  const more = document.getElementById('coMore');
  const filter = document.getElementById('coFilter');
  let rights = {}, page = 1;
  const el = (tag, value) => { const node = document.createElement(tag); node.textContent = value == null ? '' : String(value); return node; };
  async function api(url, opts) { return ApiClient.request(url, opts || {actionId:'evidence.company.read'}); }
  async function refresh() {
    const data = await api('/evidence/api/companies');
    rights = data;
    document.getElementById('coCreatePanel').hidden = !data.can_manage;
    await loadUnits();
    await load(1);
  }
  function renderUnit(row) {
    const card = el('article', ''); card.className = 'co-card';
    card.append(el('h3', row.unit_name));
    card.append(el('p', `Reviewed company: ${row.confirmed_company_name || 'none'}`));
    if (row.proposed_company_id) {
      card.append(el('p', `Awaiting review: ${row.proposed_company_name || 'company unavailable'} · ${row.proposed_reason}`));
      if (rights.can_review) {
        const form = document.createElement('form'); form.className = 'co-form';
        const reason = formField('Review reason', 'reason', 'textarea');
        const confirm = el('button', 'Confirm mapping'); confirm.type = 'button'; confirm.className = 'btn btn-primary';
        const reject = el('button', 'Reject mapping'); reject.type = 'button'; reject.className = 'btn btn-secondary';
        for (const [button, decision] of [[confirm, 'confirm'], [reject, 'reject']]) {
          button.addEventListener('click', () => save(`/evidence/api/units/${row.unit_id}/company/review`, {decision,reason:reason.lastChild.value}, 'Mapping review recorded.'));
        }
        form.append(reason, confirm, reject); card.append(form);
      }
    } else if (rights.can_manage && rights.catalogue.length) {
      const form = document.createElement('form'); form.className = 'co-form';
      const company = formField('Propose company for unit', 'company_id', 'select');
      for (const item of rights.catalogue) company.lastChild.append(new Option(item.name, item.id));
      const reason = formField('Reason / source of mapping', 'reason', 'textarea');
      const submit = el('button', 'Send mapping for review'); submit.type = 'submit'; submit.className = 'btn btn-secondary';
      form.append(company, reason, submit);
      form.addEventListener('submit', event => { event.preventDefault(); save(`/evidence/api/units/${row.unit_id}/company/propose`, {company_id:Number(company.lastChild.value),reason:reason.lastChild.value}, 'Mapping sent for independent review.'); });
      card.append(form);
    }
    return card;
  }
  async function loadUnits() {
    const host = document.getElementById('coUnitList');
    const data = await api('/evidence/api/unit-company-mappings');
    host.replaceChildren();
    (data.units || []).forEach(row => host.append(renderUnit(row)));
    if (!data.units.length) host.append(el('p', 'No business units are available in your scope.'));
  }
  function formField(label, name, kind) {
    const wrap = el('label', label), node = document.createElement(kind === 'select' ? 'select' : kind === 'textarea' ? 'textarea' : 'input');
    node.name = name; node.required = true;
    if (kind === 'textarea') node.maxLength = 500;
    wrap.append(node); return wrap;
  }
  async function save(url, body, message) {
    status.textContent = 'Saving…';
    try {
      await api(url, {method:'POST',body,actionId:'evidence.company.review'});
      status.textContent = message; await refresh();
    } catch (error) { status.textContent = error.detail || error.message || 'Could not save. Reload and try again.'; }
  }
  function render(row) {
    const card = el('article', ''); card.className = 'co-card';
    card.append(el('h3', row.title));
    const current = rights.catalogue.find(item => item.id === row.company_id);
    card.append(el('p', `Filing scope: ${row.filing_unit_name || 'organization-wide'} · Company: ${current ? current.name : 'unconfirmed'} · ${row.company_state || 'unconfirmed'}`));
    if (row.company_reason) card.append(el('p', `Latest reason: ${row.company_reason}`));
    if (rights.can_manage && row.company_state !== 'pending') {
      const form = document.createElement('form'); form.className = 'co-form';
      const company = formField('Propose company', 'company_id', 'select');
      for (const item of rights.catalogue) company.lastChild.append(new Option(item.name, item.id));
      const reason = formField('Reason / source of ownership', 'reason', 'textarea');
      const submit = el('button', 'Send for review'); submit.type = 'submit'; submit.className = 'btn btn-secondary';
      form.append(company, reason, submit);
      form.addEventListener('submit', event => { event.preventDefault(); save(`/evidence/api/items/${row.id}/company/propose`, {company_id:Number(company.lastChild.value),reason:reason.lastChild.value}, 'Assignment sent for independent review.'); });
      if (rights.catalogue.length) card.append(form);
    }
    if (rights.can_review && row.company_state === 'pending') {
      const form = document.createElement('form'); form.className = 'co-form';
      const reason = formField('Review reason', 'reason', 'textarea');
      const approve = el('button', 'Confirm'); approve.type = 'button'; approve.className = 'btn btn-primary';
      const reject = el('button', 'Reject'); reject.type = 'button'; reject.className = 'btn btn-secondary';
      for (const [button, decision] of [[approve, 'confirm'], [reject, 'reject']]) {
        button.addEventListener('click', () => save(`/evidence/api/items/${row.id}/company/review`, {decision,reason:reason.lastChild.value}, 'Review recorded.'));
      }
      form.append(reason, approve, reject); card.append(form);
    }
    const historyButton = el('button', 'Decision history'); historyButton.type = 'button'; historyButton.className = 'btn btn-secondary';
    const history = el('div', ''); history.hidden = true;
    historyButton.addEventListener('click', async () => {
      if (!history.hidden) { history.hidden = true; return; }
      try {
        const data = await api(`/evidence/api/items/${row.id}/company/history`);
        history.replaceChildren();
        (data.events || []).forEach(event => history.append(el('p', `${event.action} · ${event.created_at} · ${event.reason}`)));
        if (!data.events.length) history.append(el('p', 'No company decisions yet.'));
        history.hidden = false;
      } catch (_) { status.textContent = 'Decision history is unavailable.'; }
    });
    card.append(historyButton, history);
    return card;
  }
  async function load(next) {
    try {
      const query = new URLSearchParams({page:next,page_size:50});
      if (filter.value) query.set('company', filter.value);
      const data = await api('/evidence/api/items?' + query);
      if (next === 1) list.replaceChildren();
      data.items.forEach(row => list.append(render(row)));
      if (!data.items.length && next === 1) list.append(el('p', 'No documents in this view.'));
      page = next; more.hidden = page >= data.pages;
    } catch (error) { status.textContent = error.detail || error.message || 'Could not load documents.'; }
  }
  document.getElementById('coCreate').addEventListener('submit', event => {
    event.preventDefault(); save('/evidence/api/companies', {name:event.target.elements.name.value}, 'Company added.');
    event.target.reset();
  });
  filter.addEventListener('change', () => load(1));
  more.addEventListener('click', () => load(page + 1));
  refresh().catch(() => { status.textContent = 'Company labels are unavailable.'; });
}());
