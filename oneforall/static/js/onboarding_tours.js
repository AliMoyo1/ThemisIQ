/* Guided tours and the getting-started checklist in the Themis panel.
   Content comes from /api/onboarding (written by us, no AI) and is rendered as text only. Nothing about the page is
   sent anywhere. Tours move between pages only to paths from that list. */
(function () {
  'use strict';
  var ACTIVE = 'tiq.tour.active';
  var data = null;
  var current = null; // {tour, index, el}
  var seq = 0;        // bumped on every step change, so a step still loading cannot show after it is stale
  var spot = null, pop = null;
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function load() {
    if (data) return Promise.resolve(data);
    return fetch('/api/onboarding', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error('onboarding ' + r.status); return r.json(); })
      .then(function (d) { data = d; return d; });
  }
  function store(kind) { return 'tiq.' + kind + '.' + (data ? data.user : ''); }
  function readList(kind) { try { return JSON.parse(localStorage.getItem(store(kind)) || '[]'); } catch (e) { return []; } }
  function addTo(kind, id) {
    var list = readList(kind);
    if (list.indexOf(id) < 0) list.push(id);
    try { localStorage.setItem(store(kind), JSON.stringify(list)); } catch (e) { /* storage off: progress is not kept */ }
  }
  function findTour(id) { return (data && data.tours || []).filter(function (t) { return t.id === id; })[0]; }
  function tourOf(state) { return state && (state.inline || findTour(state.tour)); }
  function safePath(p) { return typeof p === 'string' && p.charAt(0) === '/' && p.charAt(1) !== '/' && p.indexOf('\\') < 0; }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }

  // ── The Get started view ──
  function renderStart() {
    var view = document.getElementById('trainerStartView');
    if (!view) return;
    load().then(function (d) {
      var done = readList('tours.done');
      view.textContent = '';
      view.appendChild(el('h3', '', 'Getting started'));
      var list = el('ul');
      d.checklist.forEach(function (item) {
        var isDone = item.tour ? done.indexOf(item.tour) >= 0 : !!item.done;
        var li = el('li', isDone ? 'is-done' : '');
        var box = el('span', 'ts-check', isDone ? '✓' : '');
        box.setAttribute('aria-hidden', 'true');
        li.appendChild(box);
        var label = el('span', 'ts-label', item.label);
        li.appendChild(label);
        var sr = el('span', 'sr-only', isDone ? ' (done)' : ' (to do)');
        label.appendChild(sr);
        if (!isDone && item.href && safePath(item.href)) {
          var a = el('a', 'ts-btn', 'Set up'); a.href = item.href; li.appendChild(a);
        } else if (!isDone && item.tour) {
          var b = el('button', 'ts-btn', 'Start'); b.type = 'button';
          b.addEventListener('click', function () { start(item.tour); });
          li.appendChild(b);
        }
        list.appendChild(li);
      });
      view.appendChild(list);
      view.appendChild(el('h3', '', 'Guided tours'));
      var tours = el('ul');
      d.tours.forEach(function (t) {
        var li = el('li');
        var card = el('div', 'ts-tour');
        card.appendChild(el('strong', '', t.title));
        card.appendChild(el('span', '', t.summary));
        var again = done.indexOf(t.id) >= 0;
        var b = el('button', 'ts-btn' + (again ? ' is-again' : ''), again ? 'Take it again' : 'Start the tour');
        b.type = 'button';
        b.setAttribute('aria-label', (again ? 'Take again: ' : 'Start the tour: ') + t.title);
        b.addEventListener('click', function () { start(t.id); });
        card.appendChild(b);
        li.appendChild(card);
        tours.appendChild(li);
      });
      view.appendChild(tours);
    }).catch(function () {
      view.textContent = '';
      view.appendChild(el('p', '', 'Tours could not be loaded. Please try again later.'));
    });
  }

  function showView(name) {
    var ask = name !== 'start';
    var tabAsk = document.getElementById('trainerTabAsk'), tabStart = document.getElementById('trainerTabStart');
    if (!tabAsk || !tabStart) return;
    tabAsk.setAttribute('aria-selected', String(ask)); tabAsk.tabIndex = ask ? 0 : -1;
    tabStart.setAttribute('aria-selected', String(!ask)); tabStart.tabIndex = ask ? -1 : 0;
    document.getElementById('trainerAskView').hidden = !ask;
    document.getElementById('trainerStartView').hidden = ask;
    if (!ask) renderStart();
  }

  function openPanel(view) {
    var panel = document.getElementById('trainerPanel');
    if (panel && !panel.classList.contains('open') && typeof window.toggleTrainer === 'function') window.toggleTrainer();
    showView(view);
  }

  // ── The tour runner ──
  function save(state) {
    try {
      if (state) sessionStorage.setItem(ACTIVE, JSON.stringify(state)); else sessionStorage.removeItem(ACTIVE);
    } catch (e) { /* storage off: a tour cannot continue on another page */ }
  }
  function saved() { try { return JSON.parse(sessionStorage.getItem(ACTIVE) || 'null'); } catch (e) { return null; } }

  function start(id) {
    load().then(function () {
      if (!findTour(id)) return;
      var panel = document.getElementById('trainerPanel');
      if (panel && panel.classList.contains('open') && typeof window.toggleTrainer === 'function') window.toggleTrainer();
      save({ tour: id, index: 0 });
      go();
    });
  }

  function visible(node) {
    if (!node) return false;
    var r = node.getBoundingClientRect(), s = getComputedStyle(node);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'
      && r.right > 0 && r.left < window.innerWidth;
  }

  // A step names a CSS selector, or the visible label of a button or link (the guide's "Show me").
  function byLabel(label) {
    var want = label.toLowerCase();
    var nodes = document.querySelectorAll('button, a, [role="button"], input[type="submit"]');
    for (var i = 0; i < nodes.length; i++) {
      var text = (nodes[i].textContent || nodes[i].value || '').replace(/\s+/g, ' ').replace(/^[^a-z0-9]+/i, '').trim().toLowerCase();
      if (text.indexOf(want) === 0 && visible(nodes[i])) return nodes[i];
    }
    return null;
  }

  function waitFor(step, ms) {
    return new Promise(function (resolve) {
      var t0 = Date.now();
      (function poll() {
        var node = null;
        try { node = step.label ? byLabel(step.label) : document.querySelector(step.selector); } catch (e) { resolve(null); return; }
        if (visible(node)) { resolve(node); return; }
        if (Date.now() - t0 > ms) { resolve(null); return; }
        setTimeout(poll, 120);
      })();
    });
  }

  function hidePop() {
    if (spot) spot.style.display = 'none';
    if (pop) pop.style.display = 'none';
  }

  function go() {
    var my = ++seq;
    var state = saved();
    if (!state) return;
    var tour = tourOf(state);
    if (!tour || state.index < 0 || state.index >= tour.steps.length) { end(false); return; }
    var step = tour.steps[state.index];
    if (location.pathname !== step.path) {
      if (safePath(step.path)) location.assign(step.path); else end(false);
      return;
    }
    waitFor(step, 2500).then(function (node) {
      if (my !== seq) return;
      if (!node && step.optional) { move(state.direction || 1); return; }
      if (node) node.scrollIntoView({ block: 'center', inline: 'nearest', behavior: reduced ? 'auto' : 'smooth' });
      setTimeout(function () {
        if (my !== seq) return;
        current = { tour: tour, index: state.index, el: node };
        show(step);
      }, node && !reduced ? 260 : 0);
    });
  }

  function move(direction) {
    var state = saved();
    if (!state) return;
    var tour = tourOf(state);
    var next = state.index + direction;
    seq++; current = null; hidePop();
    if (next >= tour.steps.length) { end(true); return; }
    if (next < 0) next = 0;
    save({ tour: state.tour, index: next, direction: direction });
    go();
  }

  function ensureUi() {
    if (spot) return;
    spot = el('div', 'tour-spot'); spot.setAttribute('aria-hidden', 'true');
    pop = el('div', 'tour-pop');
    pop.setAttribute('role', 'dialog'); pop.setAttribute('aria-modal', 'false'); pop.setAttribute('aria-labelledby', 'tourPopTitle');
    pop.tabIndex = -1;
    document.body.appendChild(spot); document.body.appendChild(pop);
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
  }

  function show(step) {
    ensureUi();
    var tour = current.tour, i = current.index, last = i === tour.steps.length - 1;
    pop.textContent = '';
    pop.appendChild(el('div', 'tp-count', tour.steps.length > 1
      ? tour.title + ' · Step ' + (i + 1) + ' of ' + tour.steps.length : tour.title));
    var h = el('h2', '', step.title); h.id = 'tourPopTitle'; pop.appendChild(h);
    pop.appendChild(el('p', '', step.body));
    if (!current.el) pop.appendChild(el('p', 'tp-note', 'This part is not on screen right now. It may be in a menu, or need a wider window.'));
    var close = el('button', 'tp-end', '×'); close.type = 'button'; close.setAttribute('aria-label', 'End the tour');
    close.addEventListener('click', function () { end(false); });
    pop.appendChild(close);
    var actions = el('div', 'tp-actions');
    var next = el('button', 'tp-next', tour.steps.length === 1 ? 'Got it' : last ? 'Finish' : 'Next'); next.type = 'button';
    next.addEventListener('click', function () { move(1); });
    if (tour.steps.length > 1) {
      var back = el('button', '', 'Back'); back.type = 'button'; back.disabled = i === 0;
      back.addEventListener('click', function () { move(-1); });
      actions.appendChild(back);
    }
    actions.appendChild(next);
    pop.appendChild(actions);
    spot.style.display = current.el ? 'block' : 'none';
    pop.style.display = 'block';
    place();
    next.focus({ preventScroll: true });
  }

  function place() {
    if (!current || !pop || pop.style.display === 'none') return;
    var vw = window.innerWidth, vh = window.innerHeight, pw = pop.offsetWidth, ph = pop.offsetHeight, gap = 12;
    if (!current.el || !visible(current.el)) {
      spot.style.display = 'none';
      pop.style.left = Math.max(12, (vw - pw) / 2) + 'px';
      pop.style.top = Math.max(12, (vh - ph) / 2) + 'px';
      return;
    }
    var r = current.el.getBoundingClientRect(), pad = 6;
    spot.style.display = 'block';
    spot.style.left = (r.left - pad) + 'px'; spot.style.top = (r.top - pad) + 'px';
    spot.style.width = (r.width + pad * 2) + 'px'; spot.style.height = (r.height + pad * 2) + 'px';
    var left, top;
    if (r.right + gap + pw < vw) { left = r.right + gap; top = r.top; }
    else if (r.bottom + gap + ph < vh) { left = r.left; top = r.bottom + gap; }
    else { left = r.left; top = r.top - gap - ph; }
    pop.style.left = Math.min(Math.max(12, left), vw - pw - 12) + 'px';
    pop.style.top = Math.min(Math.max(12, top), vh - ph - 12) + 'px';
  }

  function end(finished) {
    var state = saved();
    save(null);
    seq++; current = null; hidePop();
    if (finished && state && !state.inline) { addTo('tours.done', state.tour); openPanel('start'); }
  }

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && current) { e.preventDefault(); end(false); }
  });

  document.addEventListener('DOMContentLoaded', function () {
    var tabs = document.querySelectorAll('.trainer-tabs [role="tab"]');
    Array.prototype.forEach.call(tabs, function (tab) {
      tab.addEventListener('click', function () { showView(tab.getAttribute('data-view')); });
      tab.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
          e.preventDefault();
          var other = tab.id === 'trainerTabAsk' ? 'start' : 'ask';
          showView(other);
          document.getElementById(other === 'ask' ? 'trainerTabAsk' : 'trainerTabStart').focus();
        }
      });
    });
    if (saved()) { load().then(go).catch(function () { save(null); }); return; }
    // First visit to the Command Centre: open Get started once.
    if (location.pathname === '/') {
      load().then(function () {
        if (readList('onboarding.seen').length) return;
        addTo('onboarding.seen', 'yes');
        openPanel('start');
      }).catch(function () { /* no tours available: nothing to show */ });
    }
  });

  // "Take me there" from a guide answer: open the page, then point at what the answer named. Paths come from the
  // server's knowledge base and are checked again here; nothing about the page is sent anywhere.
  function point(target) {
    if (!target || !safePath(target.path)) return;
    var panel = document.getElementById('trainerPanel');
    if (panel && panel.classList.contains('open') && typeof window.toggleTrainer === 'function') window.toggleTrainer();
    if (!target.show) { if (location.pathname !== target.path) location.assign(target.path); return; }
    var step = { path: target.path, title: target.title, body: 'Here it is.', optional: false };
    if (target.show.charAt(0) === '#' || target.show.charAt(0) === '.') step.selector = target.show; else step.label = target.show;
    save({ inline: { id: 'guide', title: 'Themis', steps: [step] }, index: 0 });
    go();
  }

  window.ThemisTours = { start: start, point: point, open: function () { openPanel('start'); } };
})();
