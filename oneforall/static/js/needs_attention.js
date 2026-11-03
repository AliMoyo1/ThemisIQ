(function () {
  'use strict';
  const root = document.getElementById('needsAttention');
  if (!root) return;
  const get = id => document.getElementById(id);
  const SOURCE_NAMES = {grid_controls: 'GRID controls', aria_controls: 'ARIA controls', erm_risks: 'enterprise risks',
                        grid_audits: 'GRID audits', bcm: 'continuity exercises and plans'};
  let page = 1;
  let rulesLoaded = false;
  function el(tag, value, className) {
    const node = document.createElement(tag);
    node.textContent = value == null ? '' : String(value);
    if (className) node.className = className;
    return node;
  }
  function message(error) { return (error && (error.detail || error.message)) || 'Needs attention could not be loaded.'; }
  function safe(path) { return typeof path === 'string' && path.startsWith('/') && !path.startsWith('//'); }
  function chip(text, kind) { return el('span', text, 'na-chip' + (kind ? ' is-' + kind : '')); }

  function reviewForm(issue) {
    const form = el('form', '', 'na-form');
    form.hidden = true;
    const decision = document.createElement('select');
    decision.name = 'decision';
    decision.append(new Option('Not a real issue', 'false_positive'), new Option('Accepted exception', 'accepted_exception'));
    const reason = document.createElement('textarea');
    reason.name = 'reason'; reason.rows = 2; reason.maxLength = 1000; reason.required = true;
    const expires = document.createElement('input');
    expires.type = 'date'; expires.name = 'expires_on';
    const l1 = el('label', 'Decision'); l1.append(decision);
    const l2 = el('label', 'Look again on (optional)'); l2.append(expires);
    const l3 = el('label', 'Reason (at least 10 characters)', 'na-wide'); l3.append(reason);
    const save = el('button', 'Record review', 'btn btn-primary'); save.type = 'submit';
    form.append(l1, l2, l3, save);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      get('naStatus').textContent = 'Saving…';
      try {
        await ApiClient.request('/governance/api/attention/reviews', {method: 'POST', actionId: 'attention.review', body: {
          rule: issue.rule, source_type: issue.source_type, source_id: issue.source_id, fingerprint: issue.fingerprint,
          decision: decision.value, reason: reason.value, expires_on: expires.value || null}});
        await load();
        get('naStatus').textContent = 'Review recorded. The issue stays listed as reviewed, and opens again if its facts change.';
      } catch (error) { get('naStatus').textContent = message(error); }
    });
    return form;
  }

  function issueCard(issue, canReview) {
    const card = el('article', '', 'na-issue');
    const head = el('div', '', 'na-head');
    head.append(chip(issue.severity === 'error' ? 'Error' : 'Warning', issue.severity));
    if (safe(issue.link)) {
      const a = el('a', issue.title); a.href = issue.link; head.append(a);
    } else head.append(el('strong', issue.title));
    if (issue.state === 'reviewed') head.append(chip(issue.review.label, 'reviewed'));
    card.append(head);
    card.append(el('p', issue.why));
    card.append(el('small', 'To fix: ' + issue.fix));
    if (issue.reopened) card.append(el('small', 'Open again: ' + issue.reopened));
    if (issue.review) {
      card.append(el('small', `Reviewed by ${issue.review.by || 'a reviewer'} on ${issue.review.at}: ${issue.review.reason}` +
        (issue.review.expires_on ? ` (until ${issue.review.expires_on})` : '')));
    }
    if (canReview && issue.state === 'open') {
      const form = reviewForm(issue);
      const toggle = el('button', 'Review this issue', 'btn btn-secondary');
      toggle.type = 'button';
      toggle.setAttribute('aria-expanded', 'false');
      toggle.addEventListener('click', () => {
        form.hidden = !form.hidden;
        toggle.setAttribute('aria-expanded', String(!form.hidden));
      });
      const row = el('div', '', 'na-head'); row.append(toggle);
      card.append(row, form);
    }
    return card;
  }

  async function load() {
    const filters = get('naFilters').elements;
    const query = new URLSearchParams({severity: filters.severity.value, rule: filters.rule.value,
                                       state: filters.state.value, page: String(page)});
    let data;
    try { data = await ApiClient.request('/governance/api/attention?' + query.toString()); }
    catch (error) { get('naStatus').textContent = message(error); return; }
    if (!rulesLoaded) {
      rulesLoaded = true;
      Object.entries(data.rules).forEach(([key, rule]) => filters.rule.append(new Option(rule.label, key)));
    }
    const summary = get('naSummary');
    summary.replaceChildren(chip(`${data.counts.open.error || 0} errors`, 'error'),
                            chip(`${data.counts.open.warning || 0} warnings`, 'warning'),
                            chip(`${data.counts.reviewed} reviewed`, 'reviewed'));
    const missed = data.sources.filter(s => s.state !== 'checked');
    get('naSources').textContent = missed.length
      ? missed.map(s => (s.state === 'unavailable' ? 'Could not check ' : 'Only the first 2,000 checked for ') + (SOURCE_NAMES[s.source] || s.source)).join('. ') + '.'
      : '';
    const list = get('naList');
    list.replaceChildren();
    let lastRule = null;
    data.issues.forEach(issue => {
      if (issue.rule !== lastRule) {
        lastRule = issue.rule;
        list.append(el('h2', `${issue.label} (${data.by_rule[issue.rule]})`));
      }
      list.append(issueCard(issue, data.can_review));
    });
    if (!data.issues.length) list.append(el('p', filters.state.value === 'open' ? 'Nothing open needs attention in what you may see.' : 'No issues match.'));
    get('naPage').textContent = `Page ${data.page} of ${data.pages}`;
    get('naPrev').disabled = data.page <= 1;
    get('naNext').disabled = data.page >= data.pages;
    get('naNote').textContent = `Checks version ${data.rule_version}, as of ${data.as_of}. ${data.note}`;
  }
  get('naFilters').addEventListener('change', () => { page = 1; load(); });
  get('naPrev').addEventListener('click', () => { page = Math.max(1, page - 1); load(); });
  get('naNext').addEventListener('click', () => { page += 1; load(); });
  load();
})();
