/* Governance Timeline: render audit events without executable HTML. */
(function () {
  'use strict';

  const container = document.getElementById('tlContainer');
  const pager = document.getElementById('tlPager');
  const total = document.getElementById('tlTotal');
  const selector = document.getElementById('tlModuleFilter');
  if (!container || !pager || !total || !selector) return;

  let days = 7;
  let moduleName = '';
  let page = 1;
  let request = 0;

  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = String(value ?? '');
    return node;
  }

  function colorOf(raw) {
    return typeof raw === 'string' && /^#[0-9a-fA-F]{6}$/.test(raw) ? raw : '#64748b';
  }

  function drawEvents(events) {
    const fragment = document.createDocumentFragment();
    let lastDay = '';
    events.forEach(function (event) {
      const day = String(event.created_at || '').slice(0, 10);
      if (day !== lastDay) {
        lastDay = day;
        const parsed = /^\d{4}-\d{2}-\d{2}$/.test(day) ? new Date(day + 'T00:00:00') : null;
        const label = parsed && !Number.isNaN(parsed.valueOf())
          ? parsed.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })
          : day;
        fragment.appendChild(element('div', 'tl-day-header', label));
      }
      const row = element('div', 'tl-event');
      const color = colorOf(event.color);
      const dot = element('div', 'tl-dot');
      dot.style.backgroundColor = color;
      row.appendChild(dot);
      const body = element('div', 'tl-body');
      body.appendChild(element('div', 'tl-label', event.label));
      const meta = element('div', 'tl-meta');
      meta.appendChild(element('span', '', String(event.created_at || '').slice(11, 16)));
      const moduleChip = element('span', 'tl-meta-chip', String(event.module || '').toUpperCase());
      moduleChip.style.backgroundColor = color + '20';
      moduleChip.style.color = color;
      meta.appendChild(moduleChip);
      meta.appendChild(element('span', '', event.username));
      if (event.entity_type_label && event.entity_id) {
        meta.appendChild(element('span', '', String(event.entity_type_label) + ' #' + String(event.entity_id)));
      }
      body.appendChild(meta);
      if (event.details) body.appendChild(element('div', 'tl-details', event.details));
      row.appendChild(body);
      fragment.appendChild(row);
    });
    container.replaceChildren(fragment);
  }

  async function load() {
    const thisRequest = ++request;
    container.replaceChildren(element('div', 'tl-spinner', 'Loading timeline...'));
    pager.replaceChildren();
    const params = new URLSearchParams({ days: String(days), page: String(page) });
    if (moduleName) params.set('module', moduleName);
    try {
      const response = await fetch('/api/timeline?' + params.toString(), { credentials: 'same-origin' });
      if (!response.ok) throw new Error('Timeline unavailable');
      const data = await response.json();
      if (thisRequest !== request) return;
      total.textContent = String(Number(data.total) || 0) + ' events';
      if (selector.options.length === 1 && Array.isArray(data.modules)) {
        data.modules.forEach(function (name) {
          if (typeof name !== 'string') return;
          const option = element('option', '', name.toUpperCase());
          option.value = name;
          selector.appendChild(option);
        });
      }
      const events = Array.isArray(data.events) ? data.events : [];
      if (!events.length) {
        container.replaceChildren(element('div', 'tl-empty', 'No events found for this period.'));
        return;
      }
      drawEvents(events);
      if (page < (Number(data.pages) || 1)) {
        const more = element('button', 'tl-load-more', 'Load more');
        more.type = 'button';
        more.addEventListener('click', function () { page += 1; load(); });
        pager.replaceChildren(more);
      }
    } catch (error) {
      if (thisRequest === request) {
        total.textContent = '';
        container.replaceChildren(element('div', 'tl-empty', 'Timeline could not be loaded. Try again.'));
      }
    }
  }

  document.querySelectorAll('.tl-chip').forEach(function (chip) {
    chip.addEventListener('click', function () {
      document.querySelectorAll('.tl-chip').forEach(function (item) { item.classList.remove('active'); });
      chip.classList.add('active');
      days = Number(chip.dataset.days) || 7;
      page = 1;
      load();
    });
  });
  selector.addEventListener('change', function () {
    moduleName = selector.value;
    page = 1;
    load();
  });
  load();
}());
