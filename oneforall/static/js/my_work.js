/* PLAN-36 P01: read-only, URL-filtered My Work with personal saved filters. */
(function () {
  'use strict';
  const labels = {
    overdue: 'Overdue', needs_my_action: 'Needs My Action',
    due_soon: 'Due Soon', waiting_on_others: 'Waiting On Others',
    recently_completed: 'Recently Completed'
  };
  const order = ['overdue', 'needs_my_action', 'due_soon', 'waiting_on_others', 'recently_completed'];
  const sections = document.getElementById('myWorkSections');
  const note = document.getElementById('myWorkPendingNote');
  const more = document.getElementById('myWorkMore');
  const saved = document.getElementById('myWorkSaved');
  const controls = document.querySelector('.mywork-controls');
  const ownerId = Number(controls.dataset.userId);
  let views = [];
  let cursor = null;
  let loaded = Object.fromEntries(order.map(name => [name, []]));
  let counts = {};

  function esc(value) {
    const div = document.createElement('div');
    div.textContent = String(value == null ? '' : value);
    return div.innerHTML;
  }
  function filterParams() {
    return {
      q: document.getElementById('myWorkQ').value.trim(),
      source: document.getElementById('myWorkSource').value,
      section: document.getElementById('myWorkSection').value
    };
  }
  function setFilters(filters) {
    for (const key of ['q', 'source', 'section']) {
      const el = document.getElementById('myWork' + (key === 'q' ? 'Q' : key[0].toUpperCase() + key.slice(1)));
      el.value = filters[key] || '';
    }
  }
  function paramsFromUrl() {
    const url = new URL(location.href);
    return {q: url.searchParams.get('q') || '', source: url.searchParams.get('source') || '',
            section: url.searchParams.get('section') || ''};
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
      const cards = items.map(it => {
        const due = it.due_date ? ' · Due ' + esc(it.due_date.slice(0, 10)) : '';
        const link = typeof it.link === 'string' && it.link.startsWith('/') && !it.link.startsWith('//') ? it.link : '/';
        return '<a class="mywork-item" href="' + esc(link) + '"><span><span class="mywork-item-title">' +
          esc(it.title) + '</span><span class="mywork-item-meta">' + esc(it.source_module) +
          due + '</span></span></a>';
      }).join('');
      wrap.innerHTML = '<div class="mywork-section-head"><h2 class="mywork-section-title">' + labels[name] +
        '</h2><span class="mywork-section-count">' + items.length + ' of ' + total +
        '</span></div>' + (cards || '<div class="mywork-empty">' +
        (total ? 'Load more to see these items.' : 'Nothing here.') + '</div>');
      sections.appendChild(wrap);
    }
  }
  async function load(reset) {
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
      for (const name of order) loaded[name].push(...(data.sections[name] || []));
      counts = data.counts || {};
      cursor = data.next_cursor;
      more.hidden = !cursor;
      render();
      const unavailable = (data.source_states || []).filter(x =>
        x.state === 'degraded' || x.state === 'scope_limited' || x.state === 'disabled' || x.truncated);
      note.style.display = unavailable.length ? '' : 'none';
      note.textContent = unavailable.length ?
        'Some sources could not be fully checked: ' + unavailable.map(x => x.source.replace(/_/g, ' ')).join(', ') +
        '. Their counts may be incomplete.' : '';
    } catch (error) {
      note.style.display = '';
      note.textContent = error && error.detail ? String(error.detail) : 'Could not load My Work. Try again.';
    } finally {
      more.disabled = false;
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
  window.addEventListener('pageshow', event => { if (event.persisted) load(true); });
  setFilters(paramsFromUrl());
  loadViews();
  load(false);
})();
