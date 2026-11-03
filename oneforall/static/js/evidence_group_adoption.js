(function () {
  'use strict';
  const root = document.getElementById('groupAdoption');
  if (!root) return;
  const list = document.getElementById('gaList');
  const status = document.getElementById('gaStatus');
  const more = document.getElementById('gaMore');
  let page = 1;
  let rows = [];
  let rights = {};

  const el = (tag, value, cls) => {
    const out = document.createElement(tag);
    out.textContent = value == null ? '' : String(value);
    if (cls) out.className = cls;
    return out;
  };
  function input(label, name, type, required) {
    const wrap = el('label', label);
    const control = document.createElement(type === 'textarea' ? 'textarea' : 'input');
    control.name = name;
    if (type !== 'textarea') control.type = type;
    control.required = required;
    wrap.append(control);
    return wrap;
  }
  function button(label, action) {
    const out = el('button', label, 'btn btn-secondary');
    out.type = 'button'; out.dataset.action = action;
    return out;
  }
  async function save(url, body, message) {
    status.textContent = 'Saving…';
    try {
      await ApiClient.request(url, {method: 'POST', body, actionId: 'group.policy.adoption'});
      status.textContent = message;
      await load(1);
    } catch (error) {
      status.textContent = error.detail || error.message || 'Could not save the decision.';
    }
  }
  function proposal(row, target) {
    const form = el('form', '', 'ga-form');
    const kind = el('label', 'Local outcome');
    const choice = document.createElement('select'); choice.name = 'proposed_state';
    [['adopted', 'Adopt'], ['adapted', 'Adapt to a local approved policy'],
      ['exception_requested', 'Request an exception'], ['declined', 'Decline with reason']]
      .forEach(([value, label]) => choice.append(new Option(label, value)));
    kind.append(choice);
    const effective = input('Effective date', 'effective_at', 'date', true);
    const local = input('Approved local policy version ID (adaptation only)', 'local_policy_version_id', 'number', false);
    function requirements() {
      const needed = ['adopted', 'adapted'].includes(choice.value);
      effective.querySelector('input').required = needed;
      local.hidden = choice.value !== 'adapted';
      local.querySelector('input').required = choice.value === 'adapted';
    }
    choice.addEventListener('change', requirements);
    const due = input('Local review due', 'review_due_at', 'date', true);
    const reason = input('Reason and local deviations', 'reason', 'textarea', true);
    reason.className = 'ga-wide';
    const send = el('button', 'Submit for independent review', 'btn btn-primary');
    send.type = 'submit'; send.className += ' ga-wide';
    form.append(kind, effective, local, due, reason, send);
    requirements();
    form.addEventListener('submit', event => {
      event.preventDefault();
      const data = new FormData(form);
      save(`/evidence/api/group/publications/${row.id}/adoptions`, {
        proposed_state: data.get('proposed_state'), reason: data.get('reason'),
        effective_at: data.get('effective_at') || null,
        review_due_at: data.get('review_due_at'),
        local_policy_version_id: data.get('local_policy_version_id') || null
      }, 'Local outcome sent for independent review.');
    });
    target.append(form);
  }
  function review(row, target) {
    const form = el('form', '', 'ga-form');
    const decision = el('label', 'Decision');
    const select = document.createElement('select'); select.name = 'decision';
    select.append(new Option('Approve the local outcome', 'approve'), new Option('Reject for correction', 'reject'));
    decision.append(select);
    const reason = input('Review explanation', 'reason', 'textarea', true);
    const send = el('button', 'Record independent review', 'btn btn-primary'); send.type = 'submit';
    form.append(decision, reason, send);
    form.addEventListener('submit', event => {
      event.preventDefault();
      save(`/evidence/api/group/adoptions/${row.adoption.id}/review`,
        {decision: select.value, reason: form.elements.reason.value}, 'Local review recorded.');
    });
    target.append(form);
  }
  function linkControl(row, target) {
    const form = el('form', '', 'ga-form');
    const kind = el('label', 'Control type');
    const select = document.createElement('select'); select.name = 'kind';
    [['aria/control', 'ARIA control'], ['grid/control', 'GRID audit control'],
      ['bcm/compliance_control', 'BCM compliance control'], ['orm/ai_control', 'AI control']]
      .forEach(([value, label]) => select.append(new Option(label, value)));
    kind.append(select);
    const id = input('Control ID', 'entity_id', 'number', true);
    const note = el('p', 'This records that your own control carries out the policy. It stays in your organization and is not proof that the control works.', 'ga-wide');
    const send = el('button', 'Link control', 'btn btn-primary'); send.type = 'submit';
    form.append(kind, id, note, send);
    form.addEventListener('submit', event => {
      event.preventDefault();
      const [module, entityType] = select.value.split('/');
      save(`/evidence/api/group/adoptions/${row.adoption.id}/controls`,
        {module, entity_type: entityType, entity_id: Number(form.elements.entity_id.value)}, 'Control linked.');
    });
    target.append(form);
  }
  async function loadRollup() {
    let data;
    try { data = await ApiClient.request('/evidence/api/group/adoptions/rollup', {actionId: 'group.policy.rollup'}); }
    catch (error) { return; }
    const panel = document.getElementById('gaRollup');
    const body = document.getElementById('gaRollupRows');
    panel.hidden = false;
    body.replaceChildren();
    if (!data.items.length) body.append(el('p', 'You have not published a policy version to a subsidiary.'));
    data.items.forEach(item => {
      const card = el('article', '', 'ga-card');
      card.append(el('h3', `${item.title} · v${item.version} · ${item.organization}`));
      const state = {no_decision: 'No decision yet', in_review: 'Decision in review'}[item.state]
        || item.state.replaceAll('_', ' ');
      card.append(el('p', item.decided_at
        ? `${state} · decided ${item.decided_at.slice(0, 10)}${item.effective_at ? ` · effective ${item.effective_at}` : ''} · next review ${item.review_due_at}`
        : `${state} · published ${String(item.published_at).slice(0, 10)}`));
      body.append(card);
    });
  }
  function render() {
    list.replaceChildren();
    if (!rows.length) list.append(el('p', 'No published parent policies are available in your named access.'));
    rows.forEach(row => {
      const card = el('article', '', 'ga-card');
      card.append(el('h3', `${row.title} · v${row.version}`));
      card.append(el('p', `From ${row.source_name} · release expires ${row.expires_at}`));
      const adoption = row.adoption;
      card.append(el('p', adoption ? `Local outcome: ${adoption.state.replaceAll('_', ' ')}${adoption.state === 'pending_review' ? ` · proposed ${adoption.proposed_state.replaceAll('_', ' ')}` : ''}` : 'Local outcome: pending'));
      if (adoption) card.append(el('p', `Review due ${adoption.review_due_at} · ${adoption.reason}`));
      const actions = el('div', '', 'ga-actions');
      const link = el('a', 'Open exact policy', 'btn btn-secondary');
      link.href = `/evidence/api/group/publications/${encodeURIComponent(row.id)}`;
      actions.append(link);
      if (rights.can_propose && (!adoption || adoption.state === 'rejected')) actions.append(button('Record local outcome', 'propose'));
      if (adoption && adoption.can_review) actions.append(button('Review outcome', 'review'));
      if (adoption && adoption.can_link) actions.append(button('Link a local control', 'link'));
      card.append(actions);
      if (adoption && adoption.controls && adoption.controls.length) {
        const linked = el('div', '', 'ga-actions');
        linked.append(el('span', 'Carried out by your controls:'));
        adoption.controls.forEach(control => {
          const open = el('a', control.title, 'btn btn-secondary');
          open.href = control.url;
          const remove = el('button', `Remove ${control.title}`, 'btn btn-secondary');
          remove.type = 'button';
          remove.addEventListener('click', () => save(`/evidence/api/group/adoption-controls/${control.id}/remove`, {},
            'Control link removed.'));
          linked.append(open, remove);
        });
        card.append(linked);
      }
      const detail = el('div', ''); card.append(detail);
      actions.addEventListener('click', event => {
        const control = event.target.closest('button[data-action]');
        if (!control) return;
        detail.replaceChildren();
        if (control.dataset.action === 'propose') proposal(row, detail);
        else if (control.dataset.action === 'link') linkControl(row, detail);
        else review(row, detail);
      });
      list.append(card);
    });
  }
  async function load(next) {
    try {
      const data = await ApiClient.request(`/evidence/api/group/adoptions?page=${next}`,
        {actionId: 'group.policy.list'});
      rows = next === 1 ? data.items : rows.concat(data.items);
      rights = data;
      page = next;
      more.hidden = !data.has_more;
      render();
    } catch (error) { status.textContent = error.detail || 'Policy adoption is unavailable.'; }
  }
  more.addEventListener('click', () => load(page + 1));
  load(1);
  loadRollup();
})();
