/* AI Governance: the specialist Overview and the portfolio Monitoring list (plans/2026-10-governance-rework/01).

   Every number comes from the server with its state. A card never shows a number for a source that could not be read
   or that nothing defines: it says "Unavailable" or "Not measured" and why. Text only, no markup from the server. */
(function (global) {
  'use strict';
  var A = global.AIGov, el = A.el;

  var STATE_CHIP = {
    not_measured: { text: 'Not measured', kind: 'muted' },
    unavailable: { text: 'Unavailable', kind: 'bad' },
    partial: { text: 'Partial', kind: 'warn' },
    stale: { text: 'Out of date', kind: 'warn' }
  };

  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

  /* One sentence of supporting facts for a card, built from its structured detail. */
  function facts(m) {
    var d = m.detail || {};
    switch (m.key) {
      case 'new_requests':
        return m.value === 0 ? 'Nothing is waiting for a first review.'
          : (d.oldest_days === null || d.oldest_days === undefined ? '' : 'The oldest currently submitted request is ' + plural(d.oldest_days, 'day', 'days') + ' old.');
      case 'awaiting_decision':
        return m.value === 0 ? 'No decision is being waited for.'
          : plural(d.yours_to_decide || 0, 'request is', 'requests are') + ' yours to decide.';
      case 'approved_with_conditions':
        if (!m.value) return 'No approval has an open condition.';
        return plural(d.open_conditions, 'open condition', 'open conditions') + ', ' + d.overdue_conditions + ' overdue'
          + (d.next_due ? '; the next is due ' + d.next_due + '.' : '.');
      case 'reviews_due':
        return d.overdue + ' of them ' + (d.overdue === 1 ? 'is' : 'are') + ' already past the review date.';
      case 'evaluation_oversight_gaps':
        return [plural(d.evaluation_failed, 'failed evaluation', 'failed evaluations'),
          plural(d.evaluation_stale, 'out of date evaluation', 'out of date evaluations'),
          plural(d.oversight_attention, 'oversight arrangement to review', 'oversight arrangements to review')].join(', ') + '.';
      case 'my_requests':
        return plural(d.draft, 'draft', 'drafts') + ', ' + d.submitted + ' submitted, ' + d.returned + ' sent back to you.';
      default:
        return '';
    }
  }

  function card(m) {
    var id = 'aigCard_' + m.key;
    var chip = STATE_CHIP[m.state];
    var value = el('p', { class: 'aig-card-value' });
    if (m.value === null || m.value === undefined) {
      value.appendChild(A.chip(chip ? chip.text : 'No value', chip ? chip.kind : 'muted'));
    } else {
      value.appendChild(el('span', { class: 'aig-card-number', text: String(m.value) }));
      if (chip) value.appendChild(A.chip(chip.text, chip.kind));
    }
    var node = el('section', { class: 'aig-card aig-card-' + m.state, 'aria-labelledby': id }, [
      el('h2', { id: id, class: 'aig-card-label', text: m.label }), value]);
    var sentence = m.value === null || m.value === undefined ? '' : facts(m);
    if (sentence) node.appendChild(el('p', { class: 'aig-card-facts', text: sentence }));
    if (m.note) node.appendChild(el('p', { class: 'aig-card-note', text: m.note }));
    if (m.sources && m.sources.missing && m.sources.missing.length) {
      node.appendChild(el('p', { class: 'aig-card-note', text: 'Missing: ' + m.sources.missing.join(', ') + '.' }));
    }
    if (m.denominator) node.appendChild(el('p', { class: 'aig-card-def', text: m.denominator.value + ' ' + m.denominator.label + '.' }));
    node.appendChild(el('p', { class: 'aig-card-def', text: m.definition }));
    if (m.drilldown) {
      node.appendChild(el('a', { class: 'aig-card-link', href: m.drilldown, 'aria-label': 'Open the list behind ' + m.label, text: 'Open the list' }));
    }
    return node;
  }

  function agingTable(buckets, total) {
    var table = el('table', { class: 'aig-table aig-aging' }, [
      el('caption', { class: 'aig-muted', text: 'Currently submitted requests by age, including those with open questions' }),
      el('thead', {}, [el('tr', {}, [el('th', { scope: 'col', text: 'Waiting' }), el('th', { scope: 'col', text: 'Requests' }),
        el('th', { scope: 'col', text: 'Share' })])])]);
    var body = el('tbody');
    buckets.forEach(function (b) {
      body.appendChild(el('tr', {}, [el('td', { text: b.label }), el('td', { text: String(b.count) }),
        el('td', {}, [el('meter', { min: '0', max: String(Math.max(total, 1)), value: String(b.count),
          'aria-label': b.label + ': ' + b.count + ' of ' + total })])]));
    });
    table.appendChild(body);
    return table;
  }

  function funnel(f) {
    var box = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigFunnelH' }, [
      el('h2', { id: 'aigFunnelH', class: 'aig-h3', text: 'Requests by stage, ' + (f.window || '') })]);
    if (f.state === 'unavailable') {
      box.appendChild(el('p', { class: 'aig-note-muted', text: f.note }));
      return box;
    }
    var total = (f.denominator && f.denominator.value) || 0;
    var list = el('ol', { class: 'aig-funnel' });
    ((f.detail && f.detail.stages) || []).forEach(function (s) {
      var line = el('li', { class: 'aig-funnel-stage' });
      line.appendChild(el('span', { class: 'aig-funnel-label', text: s.label }));
      if (s.state === 'measured') {
        line.appendChild(el('span', { class: 'aig-funnel-count', text: String(s.value) }));
        line.appendChild(el('meter', { min: '0', max: String(Math.max(total, 1)), value: String(s.value),
          'aria-label': s.label + ': ' + s.value + ' of ' + total }));
      } else {
        line.appendChild(A.chip('Not measured', 'muted'));
        if (s.note) line.appendChild(el('span', { class: 'aig-muted', text: s.note }));
      }
      list.appendChild(line);
    });
    box.appendChild(list);
    box.appendChild(el('p', { class: 'aig-hint', text: f.definition }));
    return box;
  }

  function portfolioCharts(charts) {
    var box = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigPortfolioH' }, [
      el('h2', { id: 'aigPortfolioH', class: 'aig-h3', text: 'Portfolio signals' })]);
    if (!charts || charts.state === 'unavailable') {
      box.appendChild(el('p', { class: 'aig-note-muted', text: charts ? charts.definition : 'Portfolio data is unavailable.' }));
      return box;
    }
    var total = charts.included;
    var note = charts.state === 'partial'
      ? 'Partial: only the first ' + charts.limit + ' active uses are included. Counts below do not describe the entire portfolio.'
      : total + ' active AI uses in your scope.';
    box.appendChild(el('p', { class: 'aig-muted', text: note + ' As of ' + charts.as_of + '.' }));

    var evaluations = el('div', { class: 'aig-chart', 'aria-labelledby': 'aigEvalH' }, [
      el('h3', { id: 'aigEvalH', class: 'aig-chart-title', text: 'Latest evaluation outcome' })]);
    var outcomes = [
      ['passed', 'Passed and current', 'evaluation_current'],
      ['failed', 'Failed or did not finish', 'evaluation_failed'],
      ['stale', 'Out of date', 'evaluation_stale'],
      ['not_measured', 'Not measured', 'no_evaluation']
    ];
    var evalList = el('ul', { class: 'aig-chart-list' });
    outcomes.forEach(function (entry) {
      var count = charts.evaluations[entry[0]];
      evalList.appendChild(el('li', { class: 'aig-chart-row' }, [
        el('span', { text: entry[1] }),
        el('strong', { text: String(count) }),
        el('meter', { min: '0', max: String(Math.max(total, 1)), value: String(count),
          'aria-label': entry[1] + ': ' + count + ' of ' + total }),
        el('a', { href: '/ai-governance/monitoring' + A.qs({ focus: entry[2] }), text: 'View uses',
          'aria-label': 'View uses with evaluation outcome ' + entry[1] })
      ]));
    });
    evaluations.appendChild(evalList);
    box.appendChild(evaluations);

    var byTier = el('div', { class: 'aig-chart', 'aria-labelledby': 'aigTierH' }, [
      el('h3', { id: 'aigTierH', class: 'aig-chart-title', text: 'Uses needing attention by tier' })]);
    var tiers = el('ul', { class: 'aig-chart-list' });
    Object.keys(charts.tiers).forEach(function (key) {
      var tier = charts.tiers[key];
      if (!tier.total) return;
      tiers.appendChild(el('li', { class: 'aig-chart-row' }, [
        el('span', { text: tier.label }),
        el('strong', { text: tier.attention + ' of ' + tier.total }),
        el('meter', { min: '0', max: String(tier.total), value: String(tier.attention),
          'aria-label': tier.label + ': ' + tier.attention + ' of ' + tier.total + ' need attention' }),
        el('a', { href: '/ai-governance/systems' + A.qs({ tier: key }), text: 'View tier',
          'aria-label': 'View AI uses in tier ' + tier.label })
      ]));
    });
    if (!tiers.childElementCount) tiers.appendChild(el('li', { class: 'aig-muted', text: 'No active AI uses to group by tier.' }));
    byTier.appendChild(tiers);
    box.appendChild(byTier);
    box.appendChild(el('p', { class: 'aig-hint', text: charts.definition }));
    return box;
  }

  A.overview = function (root) {
    var status = el('div', { class: 'aig-say', role: 'status' });
    root.appendChild(status);
    A.say(status, 'Loading...');
    A.api('/ai-governance/api/overview').then(function (data) {
      A.say(status, '');
      root.appendChild(el('p', { class: 'aig-muted', text: data.scope.text + ' As of ' + data.as_of + '.' }));
      var grid = el('div', { class: 'aig-cards' });
      data.cards.forEach(function (m) { grid.appendChild(card(m)); });
      root.appendChild(grid);
      if (data.viewer.specialist) {
        var cols = el('div', { class: 'aig-two' });
        if (data.funnel) cols.appendChild(funnel(data.funnel));
        if (data.aging && data.aging.length) {
          var submittedTotal = data.aging.reduce(function (count, bucket) { return count + bucket.count; }, 0);
          cols.appendChild(el('section', { class: 'aig-panel' }, [agingTable(data.aging, submittedTotal)]));
        }
        root.appendChild(cols);
        root.appendChild(portfolioCharts(data.charts));
      } else {
        root.appendChild(el('p', { class: 'aig-note-muted',
          text: 'You see your own requests and the AI uses you own. Reviewers and deciders see the portfolio numbers.' }));
      }
    }).catch(function (err) { A.say(status, A.errorText(err), 'bad'); });
  };

  /* The portfolio: every use in scope, with what needs looking at first. */
  var FOCUS = [
    ['', 'All uses'], ['gaps', 'Needs attention'], ['evaluation_oversight', 'Evaluation and oversight'],
    ['evaluation_current', 'Evaluation passed and current'],
    ['evaluation_failed', 'Evaluation failed'], ['evaluation_stale', 'Evaluation out of date'],
    ['no_evaluation', 'Evaluation not measured'], ['no_oversight', 'Oversight not measured'],
    ['oversight_attention', 'Oversight to review'], ['review_overdue', 'Review overdue'],
    ['material_change', 'Needs a new decision'], ['condition_overdue', 'Condition overdue']
  ];

  A.portfolio = function (root) {
    var params = new URLSearchParams(global.location.search);
    var focus = params.get('focus') || '';
    var status = el('div', { class: 'aig-say', role: 'status' });
    var select = el('select', {});
    FOCUS.forEach(function (f) { select.appendChild(el('option', { value: f[0], text: f[1], selected: f[0] === focus ? true : null })); });
    var summary = el('p', { class: 'aig-muted' });
    var wrap = el('div', { class: 'aig-tablewrap' });
    root.appendChild(el('div', { class: 'aig-filters' }, [A.field('aigFocus', 'Show', select).row]));
    [summary, status, wrap].forEach(function (n) { root.appendChild(n); });

    function load() {
      A.say(status, 'Loading...');
      A.api('/ai-governance/api/portfolio' + A.qs({ focus: select.value })).then(function (data) {
        A.say(status, '');
        A.clear(wrap);
        var c = data.counts;
        summary.textContent = data.total_uses + ' active AI uses in your scope; ' + data.with_gaps + ' with something to look at. '
          + c.no_evaluation + ' have no evaluation with a pass or fail threshold and ' + c.no_oversight
          + ' have no oversight arrangement: those are not measured, and are not counted as passing.'
          + (data.state === 'partial' ? ' Only the first ' + data.limit + ' uses are included.' : '');
        if (!data.uses.length) {
          wrap.appendChild(el('p', { class: 'aig-empty', text: select.value ? 'No use matches this filter.' : 'There are no active AI uses in your scope.' }));
          return;
        }
        var table = el('table', { class: 'aig-table' }, [el('thead', {}, [el('tr', {}, ['AI use', 'Business unit', 'Owner', 'Tier',
          'Needs attention', 'Not measured'].map(function (h) { return el('th', { scope: 'col', text: h }); }))])]);
        var body = el('tbody');
        data.uses.forEach(function (u) {
          body.appendChild(el('tr', {}, [
            el('td', {}, [el('a', { href: u.url, text: u.name })]),
            el('td', { text: u.business_unit || 'Whole organization' }),
            el('td', { text: u.owner || 'No owner' }),
            el('td', {}, [A.tierChip(u.tier, null)]),
            el('td', {}, u.flags.length ? u.flags.map(function (f) { return el('div', {}, [A.chip(f.label, 'warn')]); })
              : [el('span', { class: 'aig-muted', text: 'Nothing to look at' })]),
            el('td', {}, u.not_measured.length ? u.not_measured.map(function (f) { return el('div', {}, [A.chip(f.label, 'muted')]); }) : [])]));
        });
        table.appendChild(body);
        wrap.appendChild(table);
      }).catch(function (err) { A.say(status, A.errorText(err), 'bad'); });
    }
    select.addEventListener('change', function () {
      var url = new URL(global.location.href);
      if (select.value) url.searchParams.set('focus', select.value); else url.searchParams.delete('focus');
      global.history.replaceState(null, '', url);
      load();
    });
    load();
  };
}(window));
