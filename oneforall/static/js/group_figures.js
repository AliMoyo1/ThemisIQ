(function () {
  'use strict';
  const root = document.getElementById('groupFigures');
  if (!root) return;
  const get = id => document.getElementById(id);
  function el(tag, value, className) {
    const item = document.createElement(tag);
    item.textContent = value == null ? '' : String(value);
    if (className) item.className = className;
    return item;
  }
  function message(error) { return (error && (error.detail || error.message)) || 'The figures could not be loaded.'; }
  function number(value) { return value == null ? 'n/a' : (Number.isInteger(value) ? String(value) : value.toFixed(1)); }
  function trend(figure) {
    if (figure.previous == null || figure.value == null || figure.previous === figure.value) return '';
    return figure.value > figure.previous ? `up from ${number(figure.previous)}` : `down from ${number(figure.previous)}`;
  }
  function renderEntity(entity) {
    const box = el('article', '', 'gf-entity');
    box.append(el('h2', entity.name));
    if (entity.state !== 'reporting') {
      box.append(el('small', entity.last_reported ? `Not reporting. Last figures ${entity.last_reported}.` : 'Not reporting. No figures have been published.'));
      return box;
    }
    box.append(el('small', `Reporting. As of ${entity.last_reported}.`));
    const grid = el('div', '', 'gf-grid');
    entity.figures.forEach(figure => {
      const card = el('div', '', 'gf-card');
      const state = figure.state === 'measured' ? '' : ` (${figure.state.replaceAll('_', ' ')})`;
      card.append(el('b', figure.value == null ? 'n/a' : number(figure.value)));
      card.append(el('span', figure.label + state));
      const note = [figure.window, trend(figure), figure.restated ? 'restated: ' + (figure.restatement_reason || '') : ''].filter(Boolean).join(' · ');
      if (note) card.append(el('span', note));
      grid.append(card);
    });
    if (!entity.figures.length) grid.append(el('p', 'No figures are visible to your role.'));
    box.append(grid);
    return box;
  }
  function renderTotals(totals) {
    const target = get('gfTotals');
    target.replaceChildren();
    if (!totals.length) return;
    const box = el('article', '', 'gf-entity');
    box.append(el('h2', 'Group totals'));
    box.append(el('small', 'Counts only, over the organizations that are reporting.'));
    const table = el('table', '', 'gf-table');
    const head = el('tr');
    ['Figure', 'Total', 'Organizations counted'].forEach(text => head.append(el('th', text)));
    table.append(head);
    totals.forEach(total => {
      const row = el('tr');
      row.append(el('td', total.label), el('td', number(total.value)), el('td', `${total.entities_counted} of ${total.entities_total}`));
      table.append(row);
    });
    box.append(table);
    target.append(box);
  }
  let latest = 0;
  async function show(which, orgId) {
    const mine = ++latest;  // a slower, earlier answer must not replace the view the person has since chosen
    get('gfStatus').textContent = 'Loading...';
    try {
      const query = which === 'subsidiary' ? `?view=subsidiary&org_id=${encodeURIComponent(orgId)}` : `?view=${which}`;
      const data = await ApiClient.request(`/governance/api/group/figures${query}`);
      if (mine !== latest) return;
      renderTotals(data.totals || []);
      get('gfEntities').replaceChildren(...data.entities.map(renderEntity));
      get('gfStatus').textContent = '';
    } catch (error) {
      if (mine !== latest) return;
      get('gfEntities').replaceChildren();
      renderTotals([]);
      get('gfStatus').textContent = message(error);
    }
  }
  async function loadCorrections(views) {
    const panel = get('gfCorrections');
    if (!views.can_restate && !views.can_review_restatement) return;
    panel.hidden = false;
    const form = get('gfPropose');
    form.hidden = !views.can_restate;
    try {
      if (views.can_restate && !form.measure_key.options.length) {
        const own = await ApiClient.request('/governance/api/group/figures?view=own');
        own.entities[0].figures.forEach(figure => {
          const option = document.createElement('option');
          option.value = figure.key; option.textContent = `${figure.label} (now ${figure.value == null ? 'n/a' : figure.value})`;
          form.measure_key.append(option);
        });
      }
      const data = await ApiClient.request('/governance/api/group/figures/restatements');
      const rows = get('gfCorrectionRows');
      rows.replaceChildren();
      data.items.forEach(item => {
        const row = el('div', '', 'gf-card');
        row.append(el('b', `${item.label}: ${number(item.old_value)} to ${number(item.new_value)}`));
        row.append(el('span', `${item.status}${item.period_text ? ' · ' + item.period_text : ''} · ${item.reason}`));
        if (item.review_reason) row.append(el('span', `Decision: ${item.review_reason}`));
        if (item.can_review) {
          ['approved', 'rejected'].forEach(decision => {
            const button = el('button', decision === 'approved' ? 'Approve' : 'Reject', 'btn btn-secondary');
            button.type = 'button';
            button.addEventListener('click', async () => {
              const reason = window.prompt('Reason for this decision (10 to 500 characters)');
              if (!reason) return;
              try {
                await ApiClient.request(`/governance/api/group/figures/restatements/${item.id}/review`, {method: 'POST', body: {decision, reason}});
                loadCorrections(views);
              } catch (error) { get('gfStatus').textContent = message(error); }
            });
            row.append(button);
          });
        }
        rows.append(row);
      });
      if (!data.items.length) rows.append(el('p', 'No corrections yet.'));
    } catch (error) { get('gfStatus').textContent = message(error); }
    if (!form.dataset.bound) {
      form.dataset.bound = '1';
      form.addEventListener('submit', async event => {
        event.preventDefault();
        const data = new FormData(form);
        try {
          await ApiClient.request('/governance/api/group/figures/restatements', {method: 'POST', body: {
            measure_key: data.get('measure_key'), new_value: Number(data.get('new_value')),
            period: data.get('period'), reason: data.get('reason')}});
          form.reset(); get('gfStatus').textContent = 'Correction proposed for review.';
          loadCorrections(views);
        } catch (error) { get('gfStatus').textContent = message(error); }
      });
    }
  }
  const issueLabels = {breach_type: 'Type', severity: 'Severity', status: 'Status', discovery_date: 'Discovered',
    reported_date: 'Reported', affected_count: 'Affected', notification_required: 'Notification required',
    authority_notified: 'Authority notified', authority_notify_date: 'Authority notified on', regulation: 'Regulation',
    request_type: 'Type', received_date: 'Received', deadline_date: 'Deadline', risk_level: 'Risk', updated: 'Updated',
    dpia_required: 'DPIA required', active: 'Active', withdrawn: 'Withdrawn', expired: 'Expired', revoked: 'Revoked', other: 'Other'};
  function issueCell(value) { return value === null || value === undefined ? '' : (value === 1 ? 'Yes' : value === 0 ? 'No' : value); }
  async function loadIssues(page) {
    const form = get('gfIssueForm');
    const orgId = form.org_id.value, type = form.issue_type.value;
    if (!orgId || !type) return;
    const table = get('gfIssueTable');
    try {
      const data = await ApiClient.request(`/governance/api/group/issues?org_id=${encodeURIComponent(orgId)}&issue_type=${encodeURIComponent(type)}&page=${page}`);
      table.replaceChildren();
      get('gfIssueNote').textContent = data.state === 'reporting'
        ? `${data.label} for ${data.name}: ${data.total} listed, as of ${data.as_of}.${data.truncated ? ' The list was cut at its limit.' : ''}`
        : `${data.name} is not reporting this register${data.as_of ? '. Last published ' + data.as_of : ''}.`;
      const columns = [];
      data.rows.forEach(row => Object.keys(row.fields).forEach(key => { if (!columns.includes(key)) columns.push(key); }));
      const head = el('tr');
      head.append(el('th', 'Reference'));
      columns.forEach(key => head.append(el('th', issueLabels[key] || key.replaceAll('_', ' '))));
      if (data.rows.length) table.append(head);
      data.rows.forEach(row => {
        const line = el('tr');
        line.append(el('td', row.ref));
        columns.forEach(key => line.append(el('td', issueCell(row.fields[key]))));
        table.append(line);
      });
      const last = Math.ceil(data.total / data.page_size) || 1;
      const prev = get('gfIssuePrev'), next = get('gfIssueNext');
      prev.hidden = data.page <= 1; next.hidden = data.page >= last;
      prev.onclick = () => loadIssues(data.page - 1); next.onclick = () => loadIssues(data.page + 1);
    } catch (error) { get('gfIssueNote').textContent = message(error); }
  }
  async function initIssues() {
    let data;
    try { data = await ApiClient.request('/governance/api/group/issues/views'); } catch (error) { return; }
    if (!data.subsidiaries.length) return;
    const form = get('gfIssueForm');
    get('gfIssues').hidden = false;
    data.subsidiaries.forEach(item => {
      const option = el('option', item.name); option.value = item.org_id; form.org_id.append(option);
    });
    const fill = () => {
      const chosen = data.subsidiaries.find(item => String(item.org_id) === form.org_id.value);
      form.issue_type.replaceChildren();
      (chosen ? chosen.types : []).forEach(type => { const option = el('option', type.label); option.value = type.key; form.issue_type.append(option); });
    };
    form.org_id.addEventListener('change', fill); fill();
    form.addEventListener('submit', event => { event.preventDefault(); loadIssues(1); });
  }
  async function openPack(id) {
    const target = get('gfPackDetail');
    try {
      const pack = await ApiClient.request(`/governance/api/group/packs/${id}`);
      target.replaceChildren();
      const box = el('article', '', 'gf-entity');
      box.append(el('h2', `${pack.title} (${pack.period})`));
      box.append(el('small', `${pack.status === 'issued' ? 'Signed off by ' + pack.reviewed_by : 'Not signed off (' + pack.status + ')'}. Frozen ${pack.created_at} by ${pack.created_by}. Fingerprint ${pack.content_hash.slice(0, 16)}.`));
      box.append(el('p', pack.verified ? 'Integrity check passed: every figure matches the frozen record.' : 'Integrity check FAILED: do not rely on this pack.', 'gf-status'));
      ['pdf', 'xlsx'].forEach(format => {
        const link = el('a', format === 'pdf' ? 'Download PDF' : 'Download Excel', 'btn btn-secondary');
        link.href = `/governance/api/group/packs/${pack.id}/export?format=${format}`;
        box.append(link);
      });
      if (pack.corrections.length) {
        const notice = el('div', '', 'gf-card');
        notice.append(el('b', 'Corrections since this pack was frozen'));
        pack.corrections.forEach(fix => notice.append(el('span', `${fix.name}: ${fix.label} was ${fix.pack_value} and is now ${fix.corrected_value}. ${fix.reason || ''}`)));
        box.append(notice);
      }
      target.append(box, ...pack.entities.map(renderEntity));
    } catch (error) { get('gfStatus').textContent = message(error); }
  }
  async function loadPacks() {
    let data;
    try { data = await ApiClient.request('/governance/api/group/packs'); } catch (error) { return; }
    get('gfPacks').hidden = false;
    get('gfPackForm').hidden = !data.can_create;
    const rows = get('gfPackRows');
    rows.replaceChildren();
    data.items.forEach(item => {
      const row = el('div', '', 'gf-card');
      row.append(el('b', `${item.title} (${item.period_text})`));
      row.append(el('span', `${item.status} · frozen ${item.created_at} by ${item.created_name || 'unknown'}`));
      const open = el('button', 'Open', 'btn btn-secondary');
      open.type = 'button';
      open.addEventListener('click', () => openPack(item.id));
      row.append(open);
      if (item.can_review) {
        [['issued', 'Sign off'], ['rejected', 'Reject']].forEach(([decision, text]) => {
          const button = el('button', text, 'btn btn-secondary');
          button.type = 'button';
          button.addEventListener('click', async () => {
            const note = window.prompt('Reason for this decision (10 to 500 characters)');
            if (!note) return;
            try {
              await ApiClient.request(`/governance/api/group/packs/${item.id}/review`, {method: 'POST', body: {decision, note}});
              loadPacks();
            } catch (error) { get('gfStatus').textContent = message(error); }
          });
          row.append(button);
        });
      }
      rows.append(row);
    });
    if (!data.items.length) rows.append(el('p', 'No packs yet.'));
    const form = get('gfPackForm');
    if (!form.dataset.bound) {
      form.dataset.bound = '1';
      form.addEventListener('submit', async event => {
        event.preventDefault();
        const values = new FormData(form);
        try {
          await ApiClient.request('/governance/api/group/packs', {method: 'POST', body: {title: values.get('title'), period: values.get('period')}});
          form.reset(); get('gfStatus').textContent = 'Pack frozen. A different person must sign it off.';
          loadPacks();
        } catch (error) { get('gfStatus').textContent = message(error); }
      });
    }
  }
  async function init() {
    try {
      const views = await ApiClient.request('/governance/api/group/figures/views');
      loadCorrections(views);
      initIssues();
      loadPacks();
      const tabs = get('gfTabs');
      const entries = [['own', `${views.own.name} alone`, null]];
      if (views.group) entries.push(['group', 'Whole group', null]);
      views.subsidiaries.forEach(item => entries.push(['subsidiary', item.name, item.org_id]));
      entries.forEach(([which, label, orgId], index) => {
        const button = el('button', label, 'btn btn-secondary');
        button.type = 'button';
        button.setAttribute('aria-pressed', index === 0 ? 'true' : 'false');
        button.addEventListener('click', () => {
          tabs.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', 'false'));
          button.setAttribute('aria-pressed', 'true');
          show(which, orgId);
        });
        tabs.append(button);
      });
      show('own', null);
    } catch (error) {
      get('gfStatus').textContent = message(error);
    }
  }
  init();
})();
