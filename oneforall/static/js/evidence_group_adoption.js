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
      card.append(actions);
      const detail = el('div', ''); card.append(detail);
      actions.addEventListener('click', event => {
        const control = event.target.closest('button[data-action]');
        if (!control) return;
        detail.replaceChildren();
        if (control.dataset.action === 'propose') proposal(row, detail);
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
})();
