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
      const note = [figure.window, trend(figure)].filter(Boolean).join(' · ');
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
  async function show(which, orgId) {
    get('gfStatus').textContent = 'Loading...';
    try {
      const query = which === 'subsidiary' ? `?view=subsidiary&org_id=${encodeURIComponent(orgId)}` : `?view=${which}`;
      const data = await ApiClient.request(`/governance/api/group/figures${query}`);
      renderTotals(data.totals || []);
      get('gfEntities').replaceChildren(...data.entities.map(renderEntity));
      get('gfStatus').textContent = '';
    } catch (error) {
      get('gfEntities').replaceChildren();
      renderTotals([]);
      get('gfStatus').textContent = message(error);
    }
  }
  async function init() {
    try {
      const views = await ApiClient.request('/governance/api/group/figures/views');
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
