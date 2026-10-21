/* Features page interactions. Every example is illustrative; the page reads in full without this script. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const root = document.documentElement;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const pressOne = (group, el) => $$('[aria-pressed]', group).forEach(b => b.setAttribute('aria-pressed', String(b === el)));
  const onView = (el, fn) => {
    if (!el) return;
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { io.disconnect(); fn(); } }, { threshold: 0.35 });
    io.observe(el);
  };

  // Theme and menu: same stored preference as the landing page.
  const themeToggle = $('#theme-toggle');
  function applyTheme(theme) {
    const dusk = theme === 'dusk';
    root.dataset.theme = dusk ? 'dusk' : 'sage';
    themeToggle.setAttribute('aria-pressed', String(dusk));
    themeToggle.setAttribute('aria-label', dusk ? 'Switch to sage theme' : 'Switch to dusk theme');
    $('#theme-label').textContent = dusk ? 'Sage' : 'Dusk';
    $('.theme-icon').textContent = dusk ? '☀' : '☾';
    try { localStorage.setItem('themisIQ-connected-signals-theme', root.dataset.theme); } catch (_) {}
  }
  try { if (localStorage.getItem('themisIQ-connected-signals-theme') === 'dusk') applyTheme('dusk'); } catch (_) {}
  themeToggle.addEventListener('click', () => applyTheme(root.dataset.theme === 'sage' ? 'dusk' : 'sage'));
  const menu = $('#menu-toggle'), links = $('#nav-links');
  const closeMenu = () => { links.dataset.open = 'false'; menu.setAttribute('aria-expanded', 'false'); };
  menu.addEventListener('click', () => { const open = links.dataset.open !== 'true'; links.dataset.open = String(open); menu.setAttribute('aria-expanded', String(open)); });
  $$('a', links).forEach(a => a.addEventListener('click', closeMenu));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenu(); });

  // Section bar follows the reader.
  const barLinks = $$('#fp-sectionbar a');
  const sections = barLinks.map(a => $(a.getAttribute('href'))).filter(Boolean);
  const spy = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (!e.isIntersecting) return;
      barLinks.forEach(a => {
        const on = a.getAttribute('href') === '#' + e.target.id;
        a.classList.toggle('is-current', on);
        if (on) a.scrollIntoView({ block: 'nearest', inline: 'center', behavior: reduced ? 'auto' : 'smooth' });
      });
    });
  }, { rootMargin: '-45% 0px -50% 0px' });
  sections.forEach(s => spy.observe(s));

  // Sections ease in.
  if (!reduced) {
    const reveal = new IntersectionObserver(entries => entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('is-in'); reveal.unobserve(e.target); } }), { threshold: 0.12 });
    $$('.fp-head, .fp-modtabs, .fp-study, .fp-why-tile, .fp-guards, .fp-tile, .fp-fw-col, .fp-index').forEach(el => { el.classList.add('fp-reveal'); reveal.observe(el); });
  }

  // Search the capability index: areas with a match open, the rest step aside.
  const query = $('#fp-query'), count = $('#fp-search-count'), noResults = $('#fp-noresults');
  const areas = $$('.fp-area');
  const items = $$('.fp-index li');
  items.forEach(li => { li.dataset.text = li.textContent; });
  function escapeRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  function filter() {
    const q = query.value.trim().toLowerCase();
    let shown = 0;
    items.forEach(li => {
      const match = !q || li.dataset.text.toLowerCase().includes(q);
      li.hidden = !match;
      if (match) shown++;
      // Highlight the match with text nodes only; the source text never becomes markup.
      li.textContent = '';
      const text = li.dataset.text;
      if (match && q) {
        text.split(new RegExp('(' + escapeRe(q) + ')', 'ig')).forEach(p => {
          if (p.toLowerCase() === q) { const m = document.createElement('mark'); m.className = 'fp-hit'; m.textContent = p; li.append(m); } else li.append(p);
        });
      } else li.append(text);
    });
    $$('.fp-index .fp-cap-group').forEach(g => { g.hidden = !$$('li', g).some(li => !li.hidden); });
    areas.forEach(a => {
      const hit = $$('li', a).some(li => !li.hidden);
      a.hidden = !!q && !hit;
      if (q && hit && !a.open) { a.open = true; a.dataset.auto = '1'; }
      if (!q && a.dataset.auto) { a.open = false; delete a.dataset.auto; }
    });
    count.textContent = q ? `${shown} match${shown === 1 ? '' : 'es'}` : '';
    noResults.hidden = !(q && shown === 0);
  }
  query.addEventListener('input', filter);
  $('#fp-clear').addEventListener('click', () => { query.value = ''; filter(); query.focus(); });

  // Tabs with arrow keys.
  function tabs(list, onSelect) {
    const tabsEls = $$('[role="tab"]', list);
    const select = (t, focus) => {
      tabsEls.forEach(x => { const on = x === t; x.setAttribute('aria-selected', String(on)); x.tabIndex = on ? 0 : -1; });
      if (focus) t.focus();
      onSelect(t, tabsEls.indexOf(t));
    };
    tabsEls.forEach((t, i) => {
      t.addEventListener('click', () => select(t, false));
      t.addEventListener('keydown', e => {
        const k = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
        if (k) { e.preventDefault(); select(tabsEls[(i + k + tabsEls.length) % tabsEls.length], true); }
        else if (e.key === 'Home') { e.preventDefault(); select(tabsEls[0], true); }
        else if (e.key === 'End') { e.preventDefault(); select(tabsEls[tabsEls.length - 1], true); }
      });
    });
    return i => select(tabsEls[i], false);
  }
  // A stepper that can play itself once, then hands control to the reader.
  function stepper(listEl, steps, render, replayBtn, autoplay = true) {
    let timer = null;
    const stop = () => { clearTimeout(timer); timer = null; };
    tabs(listEl, (t, i) => { stop(); render(i); $$('[role="tab"]', listEl).forEach((x, j) => x.classList.toggle('is-done', j < i)); });
    function play() {
      let i = 0;
      const next = () => {
        $$('[role="tab"]', listEl).forEach((x, j) => { x.setAttribute('aria-selected', String(j === i)); x.tabIndex = j === i ? 0 : -1; x.classList.toggle('is-done', j < i); });
        render(i);
        if (++i < steps) timer = setTimeout(next, 2300);
      };
      stop(); next();
    }
    if (replayBtn) replayBtn.addEventListener('click', play);
    if (autoplay && !reduced) onView(listEl.closest('.fp-study'), play);
  }

  // Module switcher. Links such as #privacy open their tab; #all-privacy opens that area of the index.
  const panels = $$('.fp-panel');
  const modtabs = $('.fp-modtabs');
  const showModule = tabs(modtabs, t => {
    panels.forEach(p => { p.hidden = p.id !== t.dataset.tab; });
    modtabs.scrollTo({ left: t.offsetLeft - 12, behavior: reduced ? 'auto' : 'smooth' }); // keeps the chosen tab in view on a phone
  });
  function follow(id, smooth) {
    const panel = panels.find(p => p.id === id);
    if (panel) {
      showModule(panels.indexOf(panel));
      $('.fp-modtabs').scrollIntoView({ block: 'start', behavior: smooth && !reduced ? 'smooth' : 'auto' });
      return true;
    }
    const area = areas.find(a => a.id === id);
    if (area) area.open = true;
    return false;
  }
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href^="#"]');
    if (a && a.getAttribute('href').length > 1 && follow(a.getAttribute('href').slice(1), true)) {
      e.preventDefault();
      history.replaceState(null, '', a.getAttribute('href'));
    }
  });
  if (location.hash) follow(location.hash.slice(1), false);
  addEventListener('hashchange', () => follow(location.hash.slice(1), true));

  // AI across the platform.
  const AI = {
    aria: ['Governance · ARIA', 'Write an access control policy for ISO 27001 A.5.15, with remote work in mind.', '<strong>Draft ready for review.</strong> Purpose, scope, policy statements, roles and review cycle, written for your organisation. Remote access is covered under section 4.', 'Source: control A.5.15 and your linked records · Approved before it is published', 'records'],
    sentinel: ['Privacy · Sentinel', 'Draft a DPIA for the new customer analytics platform.', '<strong>DPIA draft ready.</strong> Processing description, necessity, risks to people and proposed safeguards, using the linked record of processing.', 'Source: the linked record of processing · Reviewed by your DPO', 'personal'],
    bcm: ['Resilience · BCM', 'Draft a continuity plan for losing the primary data centre.', '<strong>Plan draft ready.</strong> Activation criteria, recovery steps against the processes’ recovery objectives, roles and communications.', 'Source: your business impact analysis · A person approves the plan', 'records'],
    erm: ['Enterprise risk · ERM', 'Scan for emerging regulatory risks in payments.', '<strong>Three developments to review.</strong> Each comes with its cited source, checked before use, and a suggested link to your register.', 'Source: trusted sites only · Citations verified', 'external'],
    grid: ['Audit · GRID', 'Write the narrative for the Q3 access control audit.', '<strong>Narrative ready for review.</strong> Scope, what was tested, findings and corrective actions, from the audit record.', 'Source: the audit, its findings and evidence · Signed off by the lead auditor', 'records'],
    aig: ['AI Governance', 'Explain the ticket summarizer to its reviewers.', '<strong>In plain words:</strong> it reads support tickets, summarises them for agents and never sends a reply on its own. Customer data stays in your systems.', 'Source: the AI use’s intake and profile', 'records'],
  };
  const assistant = $('.fp-assistant');
  const allowed = { records: true, personal: true, external: true };
  let aiKey = 'aria';
  function renderAI() {
    const [mod, ask, answer, src, needs] = AI[aiKey];
    $('#fp-ai-module').textContent = mod;
    $('#fp-ai-ask').textContent = ask;
    $('#fp-ai-answer').innerHTML = answer; // fixed copy from this file, never user input
    $('#fp-ai-source').textContent = src;
    const refused = !allowed[needs];
    assistant.classList.toggle('is-refused', refused);
    $('#fp-refusal').hidden = !refused;
  }
  tabs($('.fp-study-tabs'), t => { aiKey = t.dataset.ai; assistant.style.setProperty('--m', getComputedStyle(t).getPropertyValue('--m')); renderAI(); });
  $$('.fp-policy-chips button').forEach(b => b.addEventListener('click', () => {
    const on = b.getAttribute('aria-pressed') !== 'true';
    b.setAttribute('aria-pressed', String(on)); allowed[b.dataset.data] = on; renderAI();
  }));

  // Policy authoring studio.
  const PS = [
    ['Generate', 'Pick a control and a document type. ARIA writes a complete first draft in the voice the standard expects. Add your own instructions, or write one integrated document for the control and its equivalents in other standards.', 'Working draft'],
    ['Edit', 'Work on the draft in the Policy Workbench. Save as you go, discard a draft or bring it back. Every author is recorded.', 'Editing · saved'],
    ['Preview in your template', 'See the finished document in your own branded template as a PDF before anything is official.', 'PDF preview'],
    ['Approve', 'Send the version to an approver. The author and the person who submitted it can never approve it. Compare any two versions line by line.', 'Awaiting approval'],
    ['Publish', 'The approved version is filed in the Evidence Vault and attached as evidence to the matching audit controls. Start a revision any time without touching what was approved.', 'Published · v1.0'],
  ];
  const doc = $('.fp-doc');
  stepper($('[data-study="policy"] .fp-steps'), PS.length, i => {
    $('#fp-ps-title').textContent = PS[i][0]; $('#fp-ps-text').textContent = PS[i][1]; $('#fp-doc-state').textContent = PS[i][2];
    doc.dataset.step = String(i);
  }, $('[data-replay="policy"]'));
  function docTitle() {
    const type = $('.fp-doctypes [aria-pressed="true"]').dataset.doctype;
    const integrated = $('#fp-integrated').checked;
    $('#fp-doc-type').textContent = `Access Control ${type}`;
    $('#fp-doc-meta').textContent = integrated ? 'ISO 27001 A.5.15 · ISO 27701 · SOC 2 CC6.1 · integrated' : 'ISO 27001 · A.5.15';
  }
  $$('.fp-doctypes button').forEach(b => b.addEventListener('click', () => { pressOne(b.parentElement, b); docTitle(); }));
  $('#fp-integrated').addEventListener('change', docTitle);

  // IMS: what the selected standards share.
  const IMS = {
    integrated: { 'Management review': ['9001', '14001', '45001', '27001'], 'Document control': ['9001', '14001', '45001', '27001'], 'Internal audit': ['9001', '14001', '45001', '27001'], 'Corrective action': ['9001', '14001', '45001', '27001'], 'Leadership commitment': ['9001', '14001', '45001', '27001'] },
    partial: { 'Competence and awareness': ['9001', '45001', '27001'], 'Operational planning': ['9001', '14001', '45001'], 'Supplier control': ['9001', '27001'] },
    unique: { 'Customer property': ['9001'], 'Environmental aspects': ['14001'], 'Hazard identification': ['45001'], 'Access control': ['27001'] },
  };
  function renderIMS() {
    const sel = $$('.fp-standards [aria-pressed="true"]').map(b => b.dataset.std);
    const put = (id, names) => {
      const ul = $(id); ul.textContent = '';
      names.forEach(n => { const li = document.createElement('li'); li.textContent = n; ul.append(li); });
      return names.length;
    };
    const covers = (std) => std.filter(s => sel.includes(s)).length;
    let integrated = [], partial = [], unique = [];
    for (const group of Object.values(IMS)) for (const [name, std] of Object.entries(group)) {
      const c = covers(std);
      if (sel.length >= 2 && c === sel.length) integrated.push(name);
      else if (c >= 2) partial.push(name);
      else if (c === 1) unique.push(name);
    }
    put('#fp-ims-integrated', sel.length < 2 ? ['Select two or more standards'] : integrated);
    put('#fp-ims-partial', partial);
    put('#fp-ims-unique', unique);
  }
  $$('.fp-standards button').forEach(b => b.addEventListener('click', () => { b.setAttribute('aria-pressed', String(b.getAttribute('aria-pressed') !== 'true')); renderIMS(); }));
  renderIMS();

  // Privacy: rule library, obligations and clocks.
  const RULES = {
    eu: ['European Union · GDPR', 'Supervisory authority notice', 72], uk: ['United Kingdom · UK GDPR', 'Regulator notice', 72],
    zw: ['Zimbabwe · CDPA', 'Authority notice', 24], za: ['South Africa · POPIA', 'Regulator notice, as soon as reasonably possible', 0],
    ke: ['Kenya · DPA 2019', 'Commissioner notice', 72], ng: ['Nigeria · NDPA 2023', 'Commission notice', 72], gh: ['Ghana · DPA 2012', 'Commission notice, as soon as reasonably possible', 0],
    ae: ['United Arab Emirates · PDPL', 'Office notice, as soon as reasonably possible', 0], sa: ['Saudi Arabia · PDPL', 'Authority notice', 72],
    qa: ['Qatar · PDPPL', 'Department notice', 72], bh: ['Bahrain · PDPL', 'Authority notice', 72], ca: ['California · CCPA and CPRA', 'Consumer notice, as soon as reasonably possible', 0],
    br: ['Brazil · LGPD', 'Authority notice', 72], cn: ['Canada · PIPEDA', 'Commissioner notice, as soon as feasible', 0], cpp: ['Canada · CPPA, proposed', 'Indicative only: not an approved card', -1],
    in: ['India · DPDP Act', 'Board notice', 72], sg: ['Singapore · PDPA', 'Commission notice', 72], au: ['Australia · Privacy Act', 'Commissioner notice, as soon as practicable', 0],
    nz: ['New Zealand · Privacy Act', 'Commissioner notice, as soon as practicable', 0], jp: ['Japan · APPI', 'Commission notice, promptly', 0], kr: ['South Korea · PIPA', 'Commission notice', 72],
  };
  const started = Date.now() - (5 * 3600 + 40 * 60) * 1000; // illustrative: trigger recorded 5 h 40 m ago
  const obligations = $('#fp-obligations');
  function addObligation(key) {
    if ($(`li[data-j="${key}"]`, obligations)) { $(`li[data-j="${key}"]`, obligations).remove(); $(`.fp-cards [data-j="${key}"]`).classList.remove('is-added'); return; }
    const [name, notice, hours] = RULES[key];
    const li = document.createElement('li'); li.dataset.j = key;
    const b = document.createElement('b'); b.textContent = name;
    const s = document.createElement('span'); s.textContent = notice;
    const t = document.createElement('time'); t.dataset.hours = String(hours);
    const d = document.createElement('button'); d.type = 'button'; d.className = 'fp-decide'; d.textContent = 'Decide';
    li.append(b, s, t, d); obligations.append(li);
    $(`.fp-cards [data-j="${key}"]`).classList.add('is-added');
    tickClocks();
  }
  function tickClocks() {
    $$('time', obligations).forEach(t => {
      const h = Number(t.dataset.hours);
      if (h === 0) { t.textContent = 'ASAP'; return; }
      if (h < 0) { t.textContent = 'Indicative'; return; }
      const left = Math.max(0, h * 3600 - Math.floor((Date.now() - started) / 1000));
      const hh = String(Math.floor(left / 3600)).padStart(2, '0'), mm = String(Math.floor(left % 3600 / 60)).padStart(2, '0'), ss = String(left % 60).padStart(2, '0');
      t.textContent = `${hh}:${mm}:${ss}`;
    });
  }
  setInterval(tickClocks, 1000); tickClocks();
  $('.fp-cards [data-j="eu"]').classList.add('is-added');
  $$('.fp-cards button').forEach(b => b.addEventListener('click', () => addObligation(b.dataset.j)));
  obligations.addEventListener('click', e => {
    const d = e.target.closest('.fp-decide'); if (!d) return;
    const next = { undefined: 'notify', notify: 'no', no: undefined }[d.dataset.state];
    if (next) d.dataset.state = next; else delete d.dataset.state;
    d.textContent = { notify: 'Notify · recorded', no: 'Not notifying · reason recorded' }[next] || 'Decide';
  });
  $$('.fp-regions button').forEach(b => b.addEventListener('click', () => {
    pressOne(b.parentElement, b);
    $$('#fp-rule-cards li').forEach(li => { li.hidden = b.dataset.region !== 'all' && li.dataset.region !== b.dataset.region; });
  }));

  // BCM escalation.
  const SEV = { critical: '15 minutes passed', high: '30 minutes passed', medium: '60 minutes passed' };
  const esc = $$('#fp-escalation li');
  let escTimer = [];
  function playEscalation() {
    escTimer.forEach(clearTimeout); escTimer = [];
    esc.forEach(li => li.classList.remove('is-lit'));
    esc.forEach((li, i) => escTimer.push(setTimeout(() => li.classList.add('is-lit'), reduced ? 0 : i * 900)));
  }
  $$('.fp-sev button').forEach(b => b.addEventListener('click', () => { pressOne(b.parentElement, b); $('#fp-esc-window').textContent = SEV[b.dataset.sev]; playEscalation(); }));
  $('[data-replay="escalation"]').addEventListener('click', playEscalation);
  onView($('[data-study="escalation"]'), playEscalation);

  // ERM scenarios.
  const SC = {
    baseline: { cyber: [42, 'Watch'], ops: [36, 'Stable'], comp: [30, 'Stable'], sig: ['erm'] },
    exercise: { cyber: [44, 'Watch'], ops: [68, 'Rising'], comp: [38, 'Watch'], sig: ['bcm', 'orm', 'erm'] },
    gaps: { cyber: [74, 'Rising'], ops: [46, 'Watch'], comp: [66, 'Rising'], sig: ['aria', 'grid', 'sentinel', 'erm'] },
  };
  function renderScenario(k) {
    const s = SC[k];
    [['cyber', '#fp-r-cyber'], ['ops', '#fp-r-ops'], ['comp', '#fp-r-comp']].forEach(([r, id]) => {
      $(`[data-r="${r}"]`).style.setProperty('--v', s[r][0] + '%'); $(id).textContent = s[r][1];
    });
    $$('.fp-sc-signals span').forEach(sp => sp.classList.toggle('is-on', s.sig.includes(sp.dataset.sig)));
  }
  $$('.fp-scenarios button').forEach(b => b.addEventListener('click', () => { pressOne(b.parentElement, b); renderScenario(b.dataset.sc); }));
  renderScenario('baseline');

  // ORM events.
  const EV = [
    ['Change approval before release', 'Failed changes this month: rising', 'Payments recovery plan'],
    ['Access reviews completed on time', 'Exposed records: one event', 'Customer data incident plan'],
    ['Supplier performance monitored', 'Supplier incidents: rising', 'Third-party continuity plan'],
  ];
  $$('.fp-events button').forEach(b => b.addEventListener('click', () => {
    pressOne(b.parentElement, b); const e = EV[Number(b.dataset.ev)];
    [['#fp-ev-ctrl', 0], ['#fp-ev-kri', 1], ['#fp-ev-bcm', 2]].forEach(([id, i]) => { const dd = $(id); dd.textContent = e[i]; dd.style.animation = 'none'; void dd.offsetWidth; dd.style.animation = ''; });
  }));

  // AI Governance journey.
  const AG = [
    ['Register', 'Describe the AI use in a guided intake. It stays a draft until you submit it.'],
    ['Review', 'A reviewer accepts it into the inventory. Its tier follows the answers, and a reviewer can adopt a different tier with a reason.'],
    ['Assess', 'Impact assessments, prefilled from the use, with a checklist of what is left before a decision.'],
    ['Decide', 'Someone other than the person who asked approves, sets conditions, returns or rejects, on a frozen record of what they were shown.'],
    ['Watch', 'Evaluations, human oversight reviewed by a second person, and regulatory changes checked against affected uses.'],
    ['Prove', 'Review packs for auditors and a full history.'],
  ];
  stepper($('[data-study="aig"] .fp-steps'), AG.length, i => {
    $('#fp-aig-title').textContent = AG[i][0]; $('#fp-aig-text').textContent = AG[i][1];
    $$('#fp-aig-check li').forEach(li => li.classList.toggle('is-done', Number(li.dataset.k) <= i));
  }, $('[data-replay="aig"]'));

  // Connected governance.
  const map = $('.fp-map'), vendor = $('#fp-vendor'), note = $('#fp-signal-note');
  vendor.addEventListener('click', () => {
    const open = !map.classList.contains('is-open');
    map.classList.toggle('is-open', open); vendor.setAttribute('aria-pressed', String(open));
    if (!open) map.classList.remove('is-signal');
    note.textContent = open ? 'Four records across four modules depend on this vendor.' : 'Select the vendor to see what it connects to.';
  });
  $('#fp-raise').addEventListener('click', () => {
    map.classList.add('is-open'); vendor.setAttribute('aria-pressed', 'true');
    const on = !map.classList.contains('is-signal'); map.classList.toggle('is-signal', on);
    note.textContent = on ? 'Risk level raised. Each owner is asked to look again, and confirms or dismisses with a reason.' : 'Four records across four modules depend on this vendor.';
  });
})();
