/* PLAN-36 P01: read-only, URL-filtered My Work with personal saved filters. */
(function () {
  'use strict';
  const labels = {
    overdue: 'Overdue', needs_my_action: 'Needs My Action',
    due_soon: 'Due Soon', waiting_on_others: 'Waiting On Others',
    recently_changed: 'Recently Changed', recently_completed: 'Recently Completed'
  };
  const order = ['overdue', 'needs_my_action', 'due_soon', 'waiting_on_others', 'recently_changed', 'recently_completed'];
  const kindWords = {decide: 'Decide', review: 'Review', respond: 'Respond', do: 'Act', renew: 'Renew',
                     acknowledge: 'Read', wait: 'Waiting'};
  const sections = document.getElementById('myWorkSections');
  const note = document.getElementById('myWorkPendingNote');
  const more = document.getElementById('myWorkMore');
  const saved = document.getElementById('myWorkSaved');
  const controls = document.querySelector('.mywork-controls');
  const groupingNote = document.getElementById('myWorkGroupingNote');
  const ownerId = Number(controls.dataset.userId);
  let views = [];
  let cursor = null;
  let loaded = Object.fromEntries(order.map(name => [name, []]));
  let counts = {};
  let groups = {};
  let loadGeneration = 0;

  function esc(value) {
    const div = document.createElement('div');
    div.textContent = String(value == null ? '' : value);
    return div.innerHTML;
  }
  function filterParams() {
    return {
      q: document.getElementById('myWorkQ').value.trim(),
      source: document.getElementById('myWorkSource').value,
      section: document.getElementById('myWorkSection').value,
      group: document.getElementById('myWorkGroup').value
    };
  }
  function setFilters(filters) {
    for (const key of ['q', 'source', 'section', 'group']) {
      const el = document.getElementById('myWork' + (key === 'q' ? 'Q' : key[0].toUpperCase() + key.slice(1)));
      el.value = filters[key] || '';
    }
  }
  function paramsFromUrl() {
    const url = new URL(location.href);
    return {q: url.searchParams.get('q') || '', source: url.searchParams.get('source') || '',
            section: url.searchParams.get('section') || '', group: url.searchParams.get('group') || ''};
  }
  function syncUrl() {
    const url = new URL(location.href);
    for (const [key, value] of Object.entries(filterParams())) {
      if (value) url.searchParams.set(key, value);
      else url.searchParams.delete(key);
    }
    history.replaceState(null, '', url.pathname + url.search);
  }
  function render() {
    sections.innerHTML = '';
    for (const name of order) {
      const wrap = document.createElement('section');
      wrap.className = 'mywork-section';
      const items = loaded[name];
      const total = counts[name] || 0;
      const card = it => {
        const due = it.due_date ? ' · Due ' + esc(it.due_date.slice(0, 10)) : '';
        const link = typeof it.link === 'string' && it.link.startsWith('/') && !it.link.startsWith('//') ? it.link : '/';
        const kind = kindWords[it.action_kind] ? kindWords[it.action_kind] + ' · ' : '';
        const who = it.responsible === 'others' ? ' · Waiting on someone else' : '';
        const also = it.also_notified ? ' · You were also notified' : '';
        return '<a class="mywork-item" href="' + esc(link) + '"><span><span class="mywork-item-title">' +
          esc(it.title) + '</span><span class="mywork-item-meta">' + esc(kind + it.source_module) +
          due + esc(who + also) + '</span>' +
          (it.priority_basis ? '<span class="mywork-item-why">' + esc(it.priority_basis) + '</span>' : '') +
          '</span></a>';
      };
      let cards = '';
      if (document.getElementById('myWorkGroup').value) {
        const seen = [];
        items.forEach(it => {
          (it.group_keys || [it.group_key]).forEach(key => { if (seen.indexOf(key) < 0) seen.push(key); });
        });
        seen.sort((a, b) => ((groups[b] || {}).count || 0) - ((groups[a] || {}).count || 0));
        cards = seen.map(key => '<div class="mywork-group">' + esc((groups[key] || {}).label || key) + '</div>' +
          items.filter(it => (it.group_keys || [it.group_key]).includes(key)).map(card).join('')).join('');
      } else {
        cards = items.map(card).join('');
      }
      wrap.innerHTML = '<div class="mywork-section-head"><h2 class="mywork-section-title">' + labels[name] +
        '</h2><span class="mywork-section-count">' + items.length + ' of ' + total +
        '</span></div>' + (cards || '<div class="mywork-empty">' +
        (total ? 'Load more to see these items.' : 'Nothing here.') + '</div>');
      sections.appendChild(wrap);
    }
  }
  async function load(reset) {
    const generation = ++loadGeneration;
    if (reset) {
      cursor = null;
      loaded = Object.fromEntries(order.map(name => [name, []]));
      syncUrl();
    }
    const query = new URLSearchParams(filterParams());
    if (cursor) query.set('cursor', cursor);
    more.disabled = true;
    try {
      const data = await ApiClient.request('/api/my-work?' + query.toString());
      if (generation !== loadGeneration) return;
      for (const name of order) loaded[name].push(...(data.sections[name] || []));
      counts = data.counts || {};
      groups = Object.fromEntries((data.groups || []).map(g => [g.key, g]));
      cursor = data.next_cursor;
      more.hidden = !cursor;
      groupingNote.hidden = !['vendor', 'process'].includes(document.getElementById('myWorkGroup').value);
      render();
      const unavailable = (data.source_states || []).filter(x =>
        x.state === 'degraded' || x.state === 'scope_limited' || x.state === 'disabled' || x.truncated);
      note.style.display = unavailable.length ? '' : 'none';
      note.textContent = unavailable.length ?
        'Some sources could not be fully checked: ' + unavailable.map(x => x.source.replace(/_/g, ' ')).join(', ') +
        '. Their counts may be incomplete.' : '';
    } catch (error) {
      if (generation !== loadGeneration) return;
      note.style.display = '';
      note.textContent = error && error.detail ? String(error.detail) : 'Could not load My Work. Try again.';
    } finally {
      if (generation === loadGeneration) more.disabled = false;
    }
  }
  async function loadViews() {
    try {
      const data = await ApiClient.request('/api/saved-views?module=platform&view_key=my_work');
      views = data.views || [];
      saved.replaceChildren(new Option('Choose a filter', ''));
      views.forEach(view => saved.add(new Option(view.name, String(view.id))));
    } catch (_) {
      note.style.display = '';
      note.textContent = 'Saved filters are unavailable right now.';
    }
  }
  document.getElementById('myWorkApply').addEventListener('click', () => load(true));
  document.getElementById('myWorkQ').addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); load(true); }
  });
  more.addEventListener('click', () => load(false));
  saved.addEventListener('change', () => {
    const view = views.find(x => String(x.id) === saved.value);
    if (view) { setFilters(view.filter_params || {}); load(true); }
  });
  document.getElementById('myWorkSave').addEventListener('click', async () => {
    const name = prompt('Name this personal filter:');
    if (!name || !name.trim()) return;
    try {
      await ApiClient.request('/api/saved-views', {method: 'POST', body: {
        module: 'platform', view_key: 'my_work', name: name.trim(), filter_params: filterParams(), shared: false
      }});
      await loadViews();
    } catch (_) { note.style.display = ''; note.textContent = 'Could not save the filter.'; }
  });
  document.getElementById('myWorkDelete').addEventListener('click', async () => {
    const view = views.find(x => String(x.id) === saved.value);
    if (!view || Number(view.owner_user_id) !== ownerId || !confirm('Delete this saved filter?')) return;
    try {
      await ApiClient.request('/api/saved-views/' + view.id, {method: 'DELETE'});
      await loadViews();
    } catch (_) { note.style.display = ''; note.textContent = 'Could not delete the filter.'; }
  });
  // ── My team's: the work assigned to each person in the units this person heads ──
  const viewSwitch = document.getElementById('myWorkViews');
  const mineButton = document.getElementById('myWorkViewMine');
  const teamButton = document.getElementById('myWorkViewTeam');
  const teamPanel = document.getElementById('myTeam');
  const teamNote = document.getElementById('myTeamNote');
  const teamList = document.getElementById('myTeamList');
  const teamUnit = document.getElementById('myTeamUnit');
  let teamUnitsFilled = false;

  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text != null) el.textContent = text;
    return el;
  }
  function safeLink(value) {
    return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : '/';
  }
  function personCard(m) {
    const wrap = node('section', 'mywork-section');
    const head = node('div', 'mywork-section-head');
    head.appendChild(node('h2', 'mywork-section-title', m.name + (m.unit ? ' · ' + m.unit : '')));
    const c = m.counts || {};
    head.appendChild(node('span', 'mywork-person-counts',
      (c.overdue || 0) + ' overdue, ' + (c.due_soon || 0) + ' due soon, ' + (c.needs_my_action || 0) +
      ' to act on, ' + (c.waiting_on_others || 0) + ' waiting on others'));
    wrap.appendChild(head);
    (m.overdue || []).forEach(it => {
      const a = node('a', 'mywork-item');
      a.setAttribute('href', safeLink(it.link));
      const inner = node('span');
      inner.appendChild(node('span', 'mywork-item-title', it.title));
      inner.appendChild(node('span', 'mywork-item-meta', it.source + (it.due_date ? ' · Due ' + it.due_date : '')));
      a.appendChild(inner);
      wrap.appendChild(a);
    });
    if (!(m.overdue || []).length && !m.overdue_not_named) {
      wrap.appendChild(node('div', 'mywork-empty', 'Nothing overdue.'));
    }
    const later = (m.overdue_not_listed || 0) - (m.overdue_not_named || 0);
    if (later > 0) wrap.appendChild(node('div', 'mywork-person-note', later + ' more overdue item(s) are not listed here.'));
    if (m.overdue_not_named) {
      wrap.appendChild(node('div', 'mywork-person-note',
        m.overdue_not_named + ' overdue item(s) are in a module you cannot open, so they are counted and not named.'));
    }
    if (m.incomplete) {
      wrap.appendChild(node('div', 'mywork-person-note',
        'Some sources could not be read for this person, so the counts may be low.'));
    }
    return wrap;
  }
  function renderTeam(data) {
    if (!teamUnitsFilled) {
      (data.units || []).forEach(u => teamUnit.add(new Option(u.name, String(u.id))));
      teamUnitsFilled = true;
    }
    const members = data.members || [];
    let text = members.length + (data.total_members > members.length ? ' of ' + data.total_members : '') +
      ' people. Each count is the work assigned to that person. Notifications and shared queues, such as evidence ' +
      'expiring or open incidents, are not counted against anyone.';
    if (data.truncated) text += ' Only the first ' + members.length + ' are read; choose a unit to see the others.';
    teamNote.textContent = text;
    teamList.replaceChildren(...(members.length ? members.map(personCard)
      : [node('div', 'mywork-empty', 'There is nobody in these units yet.')]));
  }
  async function loadTeam() {
    teamList.setAttribute('aria-busy', 'true');
    try {
      const unit = teamUnit.value;
      const data = await ApiClient.request('/api/my-work/team' + (unit ? '?unit_id=' + encodeURIComponent(unit) : ''));
      renderTeam(data);
    } catch (error) {
      teamNote.textContent = error && error.detail ? String(error.detail) : 'Could not load your team. Try again.';
      teamList.replaceChildren();
    } finally {
      teamList.removeAttribute('aria-busy');
    }
  }
  function showView(team) {
    controls.hidden = team;
    groupingNote.hidden = team || !['vendor', 'process'].includes(document.getElementById('myWorkGroup').value);
    sections.hidden = team;
    note.hidden = team;
    more.hidden = team || !cursor;
    teamPanel.hidden = !team;
    mineButton.setAttribute('aria-pressed', String(!team));
    teamButton.setAttribute('aria-pressed', String(team));
    mineButton.className = team ? 'btn btn-secondary' : 'btn btn-primary';
    teamButton.className = team ? 'btn btn-primary' : 'btn btn-secondary';
    if (team) loadTeam();
  }
  mineButton.addEventListener('click', () => showView(false));
  teamButton.addEventListener('click', () => showView(true));
  teamUnit.addEventListener('change', loadTeam);
  // The choice is offered only to a person who heads a unit.
  async function offerTeam() {
    try {
      const data = await ApiClient.request('/api/my-work/team');
      if (data && data.is_manager) viewSwitch.hidden = false;
    } catch (_) { /* not offered: My Work itself is unaffected */ }
  }

  window.addEventListener('pageshow', event => { if (event.persisted) load(true); });
  setFilters(paramsFromUrl());
  loadViews();
  load(false);
  offerTeam();
})();
