/* Pricing calculator: a plain JavaScript port of the usage slider pricing table. Prices live in PRICING only. */
(() => {
  const root = document.getElementById('pricing-calculator');
  if (!root) return;

  // Proposed prices, USD per month, billed annually. Not approved yet: see plans/2026-10-landing-page/pricing.md.
  const PRICING = {
    currency: 'USD',
    locale: 'en-US',
    // All amounts are monthly billing. Annual billing charges ANNUAL_MONTHS of them a year (two months free).
    annualMonths: 10,
    extraModule: 500, // each core module beyond a package's own, Essentials and Professional
    aiGovernance: 800, // the premium module, as an add-on; included in Enterprise
    aiGovernanceStarter: 1000, // AI Governance on its own, up to 10 specialists
    // AI usage is included in every package (fair use, explained in the FAQ), so plans carry no request pricing.
    plans: [
      { id: 'essentials', name: 'Essentials', basePrice: 720, includedSeats: 10, perSeat: 20, maxSeats: 50, modules: 2,
        support: 'Email, next business day', highlights: ['For one team getting started'] },
      { id: 'professional', name: 'Professional', basePrice: 1800, includedSeats: 25, perSeat: 15, maxSeats: 250, modules: 4,
        support: 'Priority, named contact', highlights: ['For a growing programme'] },
      // Quote only. These figures are never shown; they decide when Enterprise is the better fit.
      { id: 'enterprise', name: 'Enterprise', quote: true, basePrice: 3600, includedSeats: 50, perSeat: 10, modules: 'all',
        support: 'Dedicated manager', highlights: ['For the whole organisation'] },
    ],
  };
  const AXES = [
    { key: 'seats', min: 5, max: 300, step: 5, start: 15, label: 'Named users', hint: 'Drag to find your fit', unit: n => n === 1 ? 'user' : 'users' },
  ];
  // Clickable modules. Pressed ones are selected to start with.
  const MODULES = [
    { id: 'governance', name: 'Governance', on: true }, { id: 'audit', name: 'Audit', on: true },
    { id: 'privacy', name: 'Privacy' }, { id: 'resilience', name: 'Resilience' },
    { id: 'erm', name: 'Enterprise risk' }, { id: 'orm', name: 'Operations risk' },
    { id: 'aig', name: 'AI Governance', premium: true },
  ];

  const plans = PRICING.plans;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const money = new Intl.NumberFormat(PRICING.locale, { style: 'currency', currency: PRICING.currency, minimumFractionDigits: 0, maximumFractionDigits: 0 });
  const plain = new Intl.NumberFormat(PRICING.locale, { maximumFractionDigits: 0 });
  const nonnegative = v => Math.max(0, Number.isFinite(v) ? v : 0);
  const fmt = (axis, v) => axis.format ? axis.format(v) : plain.format(v);
  const svg = paths => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths}</svg>`; // fixed icon markup only
  const ICON = {
    sliders: svg('<path d="M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3M14 2v4M8 10v4M16 18v4"/>'),
    check: svg('<path d="M20 6 9 17l-5-5"/>'),
    arrow: svg('<path d="M7 7h10v10M7 17 17 7"/>'),
  };
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };

  // Monthly estimate, unchanged from the component (graduated user tiers). Its request overage is unused: AI is included.
  function quoteUsagePlan(plan, usage) {
    const seats = nonnegative(usage.seats), requests = nonnegative(usage.requests);
    const billableSeats = Math.max(0, seats - nonnegative(plan.includedSeats));
    let seatPrice = billableSeats * nonnegative(plan.perSeat);
    if (plan.seatTiers && plan.seatTiers.length) {
      let boundary = 0; seatPrice = 0;
      const tiers = [...plan.seatTiers].sort((a, b) => a.upTo - b.upTo);
      for (const tier of tiers) {
        const end = Math.max(boundary, tier.upTo);
        seatPrice += Math.max(0, Math.min(billableSeats, end) - boundary) * nonnegative(tier.perSeat);
        boundary = end;
      }
      seatPrice += Math.max(0, billableSeats - boundary) * nonnegative(tiers[tiers.length - 1].perSeat);
    }
    const includedRequests = nonnegative(plan.includedRequests) + seats * nonnegative(plan.requestsPerSeat);
    const extraRequests = Math.max(0, requests - includedRequests);
    const requestPrice = Math.ceil(extraRequests / 1000) * nonnegative(plan.overagePer1k);
    const eligible = (plan.maxSeats === undefined || seats <= plan.maxSeats)
      && (plan.maxRequests === undefined || requests <= plan.maxRequests)
      && (extraRequests === 0 || plan.overagePer1k !== undefined);
    return { seats, requests, price: nonnegative(plan.basePrice) + seatPrice + requestPrice, includedRequests, eligible };
  }
  // ThemisIQ's modular part: extra core modules and the AI Governance add-on.
  function quote(plan, u) {
    const q = quoteUsagePlan(plan, u);
    q.addedModules = plan.modules === 'all' ? 0 : Math.max(0, u.modules - plan.modules);
    const addOns = plan.modules === 'all' ? 0 : q.addedModules * PRICING.extraModule + (u.aig ? PRICING.aiGovernance : 0);
    q.price = Math.round((q.price + addOns) * 100) / 100;
    return q;
  }

  const ROWS = [
    { label: 'Modules', value: (p, q, u) => p.modules === 'all' ? 'All, with AI Governance'
      : [`${p.modules} included`, q.addedModules ? `${q.addedModules} added` : '', u.aig ? 'AI Governance added' : ''].filter(Boolean).join(', ') },
    // Follows the slider: how the chosen number of users is covered by each package.
    { label: 'Your users', value: (p, q, u) => {
      if (p.maxSeats !== undefined && u.seats > p.maxSeats) return `Up to ${p.maxSeats} only`;
      if (p.quote) return u.seats < p.includedSeats ? `From ${p.includedSeats}` : `${plain.format(u.seats)}, volume pricing`;
      const extra = u.seats - p.includedSeats;
      return extra > 0 ? `${p.includedSeats} included + ${plain.format(extra)} extra` : `${plain.format(u.seats)}, all included`;
    } },
    { label: 'Each extra user', value: p => p.quote ? 'Volume pricing' : `${money.format(p.perSeat * periodMonths())}${periodUnit()}` },
    { label: 'AI assistants', value: () => 'Included' },
    { label: 'Support', value: p => p.support },
  ];

  // State. Requests stay at zero: AI usage is part of every package.
  const usage = { requests: 0 };
  let annual = true;
  const periodMonths = () => annual ? PRICING.annualMonths : 1;
  const periodUnit = () => annual ? '/yr' : '/mo';
  AXES.forEach(a => { usage[a.key] = a.start; });
  const picked = new Set(MODULES.filter(m => m.on).map(m => m.id));
  const syncModules = () => { usage.aig = picked.has('aig'); usage.modules = [...picked].filter(id => id !== 'aig').length; };
  syncModules();

  // Build: head with sliders.
  const head = el('div', 'pc-head');
  const headrow = el('div', 'pc-headrow');
  const h3 = el('h3'); h3.id = 'pc-heading'; h3.insertAdjacentHTML('afterbegin', ICON.sliders); h3.append('Pricing calculator');
  // Billing switch: annual shows the yearly price with two months free.
  const period = el('div', 'pc-period'); period.setAttribute('role', 'group'); period.setAttribute('aria-label', 'Billing period');
  const periodButtons = [['monthly', 'Monthly'], ['annual', 'Annual']].map(([id, label]) => {
    const b = el('button', '', label); b.type = 'button'; b.dataset.period = id;
    if (id === 'annual') b.append(el('small', '', '2 months free'));
    b.addEventListener('click', () => { annual = id === 'annual'; update(); });
    period.append(b);
    return b;
  });
  headrow.append(h3, period);
  const sliders = el('div', 'pc-sliders');
  const sliderParts = AXES.map(axis => {
    const id = `pc-${axis.key}`;
    const wrap = el('div', 'pc-slider');
    const label = el('div', 'pc-slider-label');
    const l = el('label', '', axis.label); l.htmlFor = id;
    label.append(l, el('span', '', axis.hint));
    const rail = el('div', 'pc-rail');
    const tip = el('div', 'pc-tip'); tip.setAttribute('aria-hidden', 'true');
    const track = el('div', 'pc-track'); track.setAttribute('aria-hidden', 'true');
    const fill = el('div', 'pc-fill'); track.append(fill);
    const input = el('input'); input.type = 'range'; input.id = id;
    input.min = axis.min; input.max = axis.max; input.step = axis.step; input.value = usage[axis.key];
    rail.append(tip, track, input);
    const ends = el('div', 'pc-ends'); ends.setAttribute('aria-hidden', 'true');
    ends.append(el('span', '', `${fmt(axis, axis.min)} ${axis.unit(axis.min)}`), el('span', '', `${fmt(axis, axis.max)} ${axis.unit(axis.max)}`));
    wrap.append(label, rail, ends);
    sliders.append(wrap);
    input.addEventListener('input', () => { usage[axis.key] = Number(input.value); update(); });
    return { axis, input, tip, fill };
  });
  // Modules: click to select. At least one stays selected.
  const mods = el('div', 'pc-modules');
  const modLabel = el('div', 'pc-slider-label');
  const modTitle = el('span', 'pc-modules-title', 'Modules'); modTitle.id = 'pc-modules-label';
  modLabel.append(modTitle, el('span', '', 'Click to select'));
  const chips = el('div', 'pc-chips'); chips.setAttribute('role', 'group'); chips.setAttribute('aria-labelledby', 'pc-modules-label');
  MODULES.forEach(m => {
    const b = el('button', `pc-chip${m.premium ? ' is-premium' : ''}`); b.type = 'button';
    b.setAttribute('aria-pressed', String(picked.has(m.id)));
    b.insertAdjacentHTML('afterbegin', ICON.check);
    b.append(m.name);
    if (m.premium) b.append(el('small', '', 'Premium'));
    b.addEventListener('click', () => {
      if (picked.has(m.id)) { if (picked.size === 1) return; picked.delete(m.id); } else picked.add(m.id);
      b.setAttribute('aria-pressed', String(picked.has(m.id)));
      syncModules(); update();
    });
    chips.append(b);
  });
  mods.append(modLabel, chips);
  head.append(headrow, sliders, mods);

  // Recommendation bar and screen reader status.
  const rec = el('div', 'pc-rec'); rec.insertAdjacentHTML('afterbegin', ICON.check);
  const recText = el('span'); rec.append(recText);
  const live = el('p', 'pc-sr'); live.setAttribute('role', 'status'); live.setAttribute('aria-live', 'polite'); live.setAttribute('aria-atomic', 'true');

  // Comparison table.
  const stage = el('div', 'pc-stage');
  const spot = el('div', 'pc-spot'); spot.setAttribute('aria-hidden', 'true'); spot.style.width = `${75 / plans.length}%`;
  const table = el('table'); table.setAttribute('aria-labelledby', 'pc-heading');
  const caption = el('caption', 'pc-sr');
  const colgroup = el('colgroup');
  const first = el('col'); first.style.width = '25%'; colgroup.append(first);
  plans.forEach(() => { const c = el('col'); c.style.width = `${75 / plans.length}%`; colgroup.append(c); });
  const thead = el('thead'), hr = el('tr'), corner = el('th'); corner.scope = 'col'; hr.append(corner);
  const heads = plans.map(p => {
    const th = el('th', 'pc-plan'); th.scope = 'col';
    const price = el('span', 'pc-price'); const roll = el('span', p.quote ? 'pc-roll pc-custom' : 'pc-roll'); price.append(roll);
    const unit = el('small');
    const row = el('div', 'pc-pricerow'); row.append(price, unit);
    th.append(el('span', 'pc-best', 'Best fit'), el('span', 'pc-name', p.name), row);
    const hl = el('p', 'pc-hl'); th.append(hl);
    hr.append(th);
    return { th, roll, unit, hl };
  });
  thead.append(hr);
  const tbody = el('tbody');
  const cells = ROWS.map(r => {
    const tr = el('tr'), th = el('th', '', r.label); th.scope = 'row'; tr.append(th);
    const tds = plans.map(() => { const td = el('td'); tr.append(td); return td; });
    tbody.append(tr);
    return tds;
  });
  const tfoot = el('tfoot'), fr = el('tr'), fth = el('th', '', 'Make it yours'); fth.scope = 'row'; fr.append(fth);
  const buttons = plans.map(p => {
    const td = el('td'), b = el('button', 'pc-choose'); b.type = 'button'; b.setAttribute('aria-label', `Choose ${p.name}`);
    b.addEventListener('click', () => choose(p));
    td.append(b); fr.append(td);
    return b;
  });
  tfoot.append(fr);
  table.append(caption, colgroup, thead, tbody, tfoot);
  stage.append(spot, table);
  root.replaceChildren(head, rec, live, stage);

  // Rolling digits: a column per digit, kept by position from the end so the reel slides between values.
  function roll(node, value) {
    const text = money.format(value);
    const keep = node._cols || new Map(), next = new Map(), order = [];
    Array.from(text).forEach((ch, i) => {
      const key = text.length - i, digit = /\d/.test(ch);
      let col = keep.get(key);
      if (!col || col._digit !== digit || (!digit && col.textContent !== ch)) {
        if (digit) {
          col = el('span', 'pc-digit'); const reel = el('span');
          for (let d = 0; d < 10; d++) reel.append(el('span', '', String(d)));
          col.append(reel);
        } else col = el('span', 'pc-char', ch);
        col._digit = digit;
      }
      if (digit) col.firstChild.style.transform = `translateY(-${Number(ch)}em)`;
      next.set(key, col); order.push(col);
    });
    node._cols = next;
    if (!node._sr) node._sr = el('span', 'pc-sr');
    // Re-attach only when the shape changes (for example $9,999 to $10,000); moving nodes would cancel the roll.
    if (node.children.length !== order.length + 1 || order.some((c, i) => node.children[i + 1] !== c)) node.replaceChildren(node._sr, ...order);
    node._sr.textContent = text;
    order.forEach(c => c.setAttribute('aria-hidden', 'true'));
  }
  // Counting figures.
  function count(td, amount) {
    let n = td.querySelector('.pc-count');
    if (!n) { td.textContent = ''; n = el('span', 'pc-count'); n._v = amount; td.append(n); }
    const from = n._v; cancelAnimationFrame(n._f);
    if (reduced || from === amount) { n._v = amount; n.textContent = plain.format(amount); return; }
    const start = performance.now();
    const tick = now => {
      const t = Math.min(1, (now - start) / 320);
      n._v = from + (amount - from) * (1 - (1 - t) ** 3);
      n.textContent = plain.format(n._v);
      if (t < 1) n._f = requestAnimationFrame(tick); else n._v = amount;
    };
    n._f = requestAnimationFrame(tick);
  }

  let announceTimer = 0, best = -1;
  function update() {
    sliderParts.forEach(({ axis, input, tip, fill }) => {
      const v = usage[axis.key];
      const f = axis.max === axis.min ? 0 : (v - axis.min) / (axis.max - axis.min);
      tip.style.left = `calc(${f * 100}% + ${10 - f * 20}px)`;
      tip.textContent = fmt(axis, v);
      fill.style.width = `${f * 100}%`;
      if (Number(input.value) !== v) input.value = v;
      input.setAttribute('aria-valuetext', `${fmt(axis, v)} ${axis.unit(v)}`);
    });
    const quotes = plans.map(p => quote(p, usage));
    // Enterprise wins with every module, past the Professional limit, or when its quote reference costs less.
    best = -1;
    quotes.forEach((q, i) => { if (q.eligible && (best < 0 || q.price < quotes[best].price)) best = i; });
    const ent = plans.findIndex(p => p.quote);
    if (ent >= 0 && usage.aig && usage.modules === MODULES.length - 1) best = ent;
    const users = `${plain.format(usage.seats)} ${usage.seats === 1 ? 'user' : 'users'}`;
    const onlyAig = usage.aig && usage.modules === 0;
    const months = periodMonths(), unit = periodUnit();
    const summary = best < 0 ? 'No package fits this estimate. Talk to us about a custom plan.'
      : onlyAig && usage.seats <= 10 ? `Only AI Governance? AI Governance Starter · ${money.format(PRICING.aiGovernanceStarter * months)}${unit} for up to 10 specialists`
      : plans[best].quote ? `${plans[best].name} fits best at ${users}. Request a quote.`
      : `Best value at ${users}: ${plans[best].name} · ${money.format(quotes[best].price * months)}${unit}`;
    recText.textContent = summary;
    corner.textContent = annual ? 'Your price, billed annually' : 'Your price, billed monthly';
    periodButtons.forEach(b => b.setAttribute('aria-pressed', String((b.dataset.period === 'annual') === annual)));
    caption.textContent = `Prices by package. ${summary}`;
    clearTimeout(announceTimer); announceTimer = setTimeout(() => { live.textContent = summary; }, 400);
    spot.style.transform = `translateX(${Math.max(0, best) * 100}%)`;
    spot.style.opacity = best < 0 ? '0' : '1';
    root.dataset.recommended = best >= 0 ? plans[best].id : '';
    plans.forEach((p, i) => {
      heads[i].th.classList.toggle('is-best', i === best);
      // A bigger package can cost less once add-ons pile up; say so instead of leaving a confusing higher price.
      const beaten = quotes[i].eligible && best > i;
      heads[i].th.classList.toggle('is-out', !quotes[i].eligible || beaten);
      heads[i].hl.textContent = beaten ? `${plans[best].name} costs less for this` : (p.highlights || []).join(' · ');
      if (p.quote) { heads[i].roll.textContent = 'Custom'; heads[i].unit.textContent = ''; }
      else { roll(heads[i].roll, quotes[i].price * months); heads[i].unit.textContent = unit; }
      ROWS.forEach((r, ri) => {
        const v = r.value(p, quotes[i], usage), td = cells[ri][i];
        if (v && typeof v === 'object') count(td, v.amount); else td.textContent = v;
      });
      const b = buttons[i];
      b.disabled = !quotes[i].eligible;
      b.classList.toggle('is-best', i === best);
      b.textContent = !quotes[i].eligible ? 'Not available' : p.quote ? 'Request quote ' : 'Choose ';
      b.setAttribute('aria-label', p.quote ? `Request a quote for ${p.name}` : `Choose ${p.name}`);
      if (quotes[i].eligible) b.insertAdjacentHTML('beforeend', ICON.arrow);
    });
  }
  update();

  // Choosing a package prefills the demo request. The value is a fixed plan id from this file, never free text.
  const status = document.getElementById('pc-status');
  const form = document.getElementById('demoForm');
  function choose(p) {
    stopTour();
    if (form) form.dataset.plan = p.id;
    status.textContent = p.quote ? `${p.name} quote requested. Tell us where to reach you.`
      : `${p.name} selected. Tell us where to reach you and we will set you up.`;
    const target = document.getElementById('demo') || document.getElementById('contact');
    if (target) target.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'center' });
    const name = form && form.elements.name;
    if (name) setTimeout(() => name.focus({ preventScroll: true }), reduced ? 0 : 600);
  }

  // A one-pass tour when the calculator comes into view: users grow, the best fit follows. Any touch stops it.
  const replay = document.getElementById('pc-replay');
  const idle = status.textContent;
  let frame = 0, touched = false;
  function stopTour() {
    touched = true; cancelAnimationFrame(frame);
    if (status.textContent === 'Try the slider. Your best fit follows.') status.textContent = idle;
  }
  function tour() {
    if (reduced) return;
    touched = false; status.textContent = 'Try the slider. Your best fit follows.';
    const axis = AXES[0], from = axis.min, to = 120, start = performance.now();
    const tick = now => {
      if (touched) return;
      const t = Math.min(1, Math.max(0, (now - start - 1500) / 4000));
      usage.seats = Math.round((from + (to - from) * t * t * (3 - 2 * t)) / axis.step) * axis.step;
      update();
      if (t < 1) frame = requestAnimationFrame(tick); else status.textContent = idle;
    };
    frame = requestAnimationFrame(tick);
  }
  ['pointerdown', 'keydown'].forEach(e => root.addEventListener(e, stopTour));
  root.addEventListener('focusin', stopTour);
  if (!reduced && replay) {
    replay.hidden = false;
    replay.addEventListener('click', () => { if (form) delete form.dataset.plan; tour(); });
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { io.disconnect(); if (!touched) tour(); } }, { threshold: 0.45 });
    io.observe(root);
  }
})();
