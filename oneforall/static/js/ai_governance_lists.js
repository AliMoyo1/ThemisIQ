/* AI Governance: the inventory list, a person's own requests, and the reviewers' queue.
   Needs ai_governance_common.js and api_client.js. */
(function (global) {
  'use strict';

  var AIGov = global.AIGov, el = AIGov.el;

  // ── Inventory ─────────────────────────────────────────────────────────────

  var FILTERS = ['q', 'state', 'tier', 'use_type', 'owner', 'unit', 'provider'];

  AIGov.inventory = function (root, options) {
    options = options || {};
    var params = new URLSearchParams(global.location.search);
    var current = { q: '', state: 'active', tier: '', use_type: '', owner: '', unit: '', provider: '', page: 1, sort: 'name' };
    FILTERS.concat(['sort']).forEach(function (key) { if (params.get(key)) current[key] = params.get(key); });
    current.page = parseInt(params.get('page') || '1', 10) || 1;

    var filterBar = el('form', { class: 'aig-filters', role: 'search', 'aria-label': 'Filter AI systems' });
    var status = el('div', { class: 'aig-say', role: 'status' });
    var tableWrap = el('div', { class: 'aig-tablewrap' });
    var pagerBox = el('div', { class: 'aig-pager' });
    [filterBar, status, tableWrap, pagerBox].forEach(function (n) { root.appendChild(n); });
    filterBar.addEventListener('submit', function (event) { event.preventDefault(); });

    var controls = {};
    var counter = 0;

    function syncUrl() {
      var query = {};
      FILTERS.forEach(function (key) { if (current[key] && !(key === 'state' && current[key] === 'active')) query[key] = current[key]; });
      if (current.page > 1) query.page = current.page;
      if (current.sort !== 'name') query.sort = current.sort;
      global.history.replaceState(null, '', global.location.pathname + AIGov.qs(query));
    }

    function load() {
      var ticket = ++counter;
      syncUrl();
      tableWrap.setAttribute('aria-busy', 'true');
      AIGov.say(status, 'Loading...');
      AIGov.api('/ai-governance/api/systems' + AIGov.qs({
        q: current.q, state: current.state, tier: current.tier, use_type: current.use_type, owner: current.owner,
        unit: current.unit, provider: current.provider, page: current.page, sort: current.sort })).then(function (data) {
        if (ticket !== counter) return;
        tableWrap.removeAttribute('aria-busy');
        AIGov.say(status, '');
        render(data);
      }).catch(function (err) {
        if (ticket !== counter) return;
        tableWrap.removeAttribute('aria-busy');
        AIGov.clear(tableWrap);
        AIGov.say(status, AIGov.errorText(err), 'bad');
      });
    }

    function filtersActive() {
      return FILTERS.some(function (key) { return current[key] && !(key === 'state' && current[key] === 'active'); });
    }

    function render(data) {
      AIGov.clear(tableWrap);
      AIGov.pager(pagerBox, data.page, data.pages, data.total, data.page_size, function (page) { current.page = page; load(); });
      if (!data.items.length) {
        var box = el('div', { class: 'aig-empty' });
        if (filtersActive()) {
          box.appendChild(el('p', { text: 'No AI systems match these filters.' }));
          box.appendChild(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Clear filters', on: { click: function () {
            FILTERS.forEach(function (key) { current[key] = key === 'state' ? 'active' : ''; controls[key].value = current[key]; });
            current.page = 1; load();
          } } }));
        } else {
          box.appendChild(el('p', { text: 'No AI systems are registered yet.' }));
          if (options.canRegister) box.appendChild(el('a', { class: 'btn btn-primary btn-sm', href: '/ai-governance/register', text: 'Register an AI use' }));
        }
        tableWrap.appendChild(box);
        return;
      }
      var table = el('table', { class: 'aig-table' });
      var headRow = el('tr', {});
      [['name', 'Name'], [null, 'Owner'], [null, 'Business unit'], [null, 'Provider'], [null, 'Use'], ['tier', 'Tier'], ['review', 'Next review'], [null, 'Needs attention']]
        .forEach(function (col) {
          var th = el('th', { scope: 'col' });
          if (col[0]) {
            th.setAttribute('aria-sort', current.sort === col[0] ? 'ascending' : 'none');
            th.appendChild(el('button', { type: 'button', class: 'aig-sortbtn', text: col[1], on: { click: function () {
              current.sort = col[0]; current.page = 1; load(); } } }));
          } else { th.textContent = col[1]; }
          headRow.appendChild(th);
        });
      table.appendChild(el('thead', {}, [headRow]));
      var body = el('tbody', {});
      data.items.forEach(function (row) {
        body.appendChild(el('tr', {}, [
          el('td', {}, [el('a', { href: row.url, text: row.name }), row.active ? null : AIGov.chip('Retired', 'muted')]),
          el('td', { text: row.owner || 'None' }),
          el('td', { text: row.business_unit || 'Whole organization' }),
          el('td', { text: row.vendor || 'Not recorded' }),
          el('td', { text: row.use_type || 'Not recorded' }),
          el('td', {}, [AIGov.tierChip(row.tier, row.tier_adopted)]),
          el('td', { text: row.next_review_at || 'Not scheduled' }),
          el('td', {}, row.needs_action.map(function (reason) { return AIGov.chip(reason, 'warn'); })),
        ]));
      });
      table.appendChild(body);
      tableWrap.appendChild(table);
    }

    function addSelect(key, label, options2) {
      var select = AIGov.select(options2, current[key], 'All');
      select.addEventListener('change', function () { current[key] = select.value; current.page = 1; load(); });
      controls[key] = select;
      filterBar.appendChild(AIGov.field('aigf_' + key, label, select).row);
    }

    var search = el('input', { type: 'search', value: current.q, autocomplete: 'off' });
    search.addEventListener('input', AIGov.debounce(function () { current.q = search.value.trim(); current.page = 1; load(); }, 300));
    controls.q = search;
    filterBar.appendChild(AIGov.field('aigf_q', 'Search name or purpose', search).row);

    var stateSelect = AIGov.select([
      { id: 'active', name: 'Active' }, { id: 'needs_action', name: 'Needs attention' }, { id: 'review_due', name: 'Review due' },
      { id: 'retired', name: 'Retired' }, { id: 'all', name: 'All' }], current.state);
    stateSelect.addEventListener('change', function () { current.state = stateSelect.value; current.page = 1; load(); });
    controls.state = stateSelect;
    filterBar.appendChild(AIGov.field('aigf_state', 'Show', stateSelect).row);

    AIGov.api('/ai-governance/api/systems/choices').then(function (choices) {
      addSelect('tier', 'Tier', choices.tiers);
      addSelect('use_type', 'Use', choices.use_types);
      addSelect('owner', 'Owner', choices.owners);
      addSelect('unit', 'Business unit', choices.business_units);
      addSelect('provider', 'Provider', choices.vendors);
    }).catch(function () { /* the list still works without its extra filters */ });

    load();
  };

  // ── My requests ───────────────────────────────────────────────────────────

  var STATUS_LABEL = { draft: 'Draft', submitted: 'Waiting for review', returned: 'Needs your changes', approved: 'Accepted', rejected: 'Not accepted' };
  var STATUS_KIND = { draft: 'muted', submitted: 'info', returned: 'warn', approved: 'good', rejected: 'bad' };
  AIGov.statusChip = function (status) { return AIGov.chip(STATUS_LABEL[status] || status, STATUS_KIND[status]); };

  AIGov.requests = function (root) {
    var status = el('div', { class: 'aig-say', role: 'status' });
    var list = el('div', { class: 'aig-tablewrap' });
    root.appendChild(status);
    root.appendChild(list);
    AIGov.say(status, 'Loading...');
    AIGov.api('/ai-governance/api/requests').then(function (data) {
      AIGov.say(status, '');
      if (!data.items.length) {
        list.appendChild(el('div', { class: 'aig-empty' }, [
          el('p', { text: 'You have not described an AI use yet.' }),
          el('a', { class: 'btn btn-primary btn-sm', href: '/ai-governance/register', text: 'Register an AI use' })]));
        return;
      }
      var table = el('table', { class: 'aig-table' }, [el('thead', {}, [el('tr', {}, ['Name', 'Status', 'Last changed', ''].map(function (h) {
        return el('th', { scope: 'col', text: h }); }))])]);
      var body = el('tbody', {});
      data.items.forEach(function (row) {
        var name = row.answers.name || 'Untitled draft';
        var cells = [
          el('td', {}, [el('a', { href: '/ai-governance/requests/' + row.id, text: name }),
            row.status === 'returned' && row.review_note ? el('div', { class: 'aig-hint', text: 'Reviewer: ' + row.review_note }) : null,
            row.status === 'rejected' && row.review_note ? el('div', { class: 'aig-hint', text: 'Reason: ' + row.review_note }) : null]),
          el('td', {}, [AIGov.statusChip(row.status)]),
          el('td', { text: AIGov.date(row.updated_at) }),
          el('td', {}, [row.status === 'approved' && row.application_id
            ? el('a', { href: '/ai-governance/systems/' + row.application_id, text: 'Open the AI system' })
            : (row.status === 'draft' || row.status === 'returned') ? el('a', { href: '/ai-governance/requests/' + row.id, text: 'Continue' }) : null]),
        ];
        body.appendChild(el('tr', {}, cells));
      });
      table.appendChild(body);
      list.appendChild(table);
    }).catch(function (err) { AIGov.say(status, AIGov.errorText(err), 'bad'); });
  };

  // ── Review queue ──────────────────────────────────────────────────────────

  function labelled(vocab, key, value) {
    if (Array.isArray(value)) return value.map(function (v) { return (vocab[key] || {})[v] || v; }).join(', ');
    return (vocab[key] || {})[value] || value;
  }

  AIGov.review = function (root) {
    var vocab = {}, units = {};
    var queue = el('div', { class: 'aig-queue', role: 'group', 'aria-label': 'Requests waiting for review' });
    var detail = el('div', { class: 'aig-detail', tabindex: '-1' });
    var status = el('div', { class: 'aig-say', role: 'status' });
    root.appendChild(status);
    root.appendChild(el('div', { class: 'aig-split' }, [queue, detail]));
    var selected = null;

    // The outcome of a decision is announced up here, outside the detail panel, so it is still there when the queue
    // reloads and the decided request has gone from it.
    function announce(message, href, linkText) {
      AIGov.clear(status);
      status.className = 'aig-say aig-say-good';
      status.setAttribute('role', 'status');
      status.appendChild(document.createTextNode(message + ' '));
      if (href) status.appendChild(el('a', { href: href, text: linkText }));
    }

    function loadQueue(keepSelection, keepStatus) {
      if (!keepStatus) AIGov.say(status, 'Loading...');
      AIGov.api('/ai-governance/api/review/queue').then(function (data) {
        if (!keepStatus) AIGov.say(status, '');
        AIGov.clear(queue);
        if (!data.items.length) {
          queue.appendChild(el('p', { class: 'aig-empty', text: 'Nothing is waiting for review.' }));
          AIGov.clear(detail);
          selected = null;
          return;
        }
        data.items.forEach(function (row) {
          var button = el('button', { type: 'button', class: 'aig-queue-item' + (selected === row.id ? ' is-selected' : ''),
            'aria-current': selected === row.id ? 'true' : null, on: { click: function () { select(row.id); } } }, [
            el('strong', { text: row.answers.name || 'Untitled' }),
            el('span', { class: 'aig-muted', text: (row.author_name || 'Someone') + ', ' + AIGov.date(row.submitted_at) }),
            AIGov.tierChip(row.screening.tier, null)]);
          queue.appendChild(button);
        });
        if (keepSelection && selected && data.items.some(function (r) { return r.id === selected; })) select(selected);
        else if (!selected) select(data.items[0].id);
      }).catch(function (err) { AIGov.say(status, AIGov.errorText(err), 'bad'); });
    }

    function select(id) {
      selected = id;
      [].forEach.call(queue.children, function (item, index) { item.classList.toggle('is-selected', false); });
      AIGov.say(status, '');
      Promise.all([AIGov.api('/ai-governance/api/requests/' + id),
        AIGov.api('/ai-governance/api/review/requests/' + id + '/duplicates')]).then(function (parts) {
        renderDetail(parts[0].intake, parts[1].items || []);
        [].forEach.call(queue.querySelectorAll('.aig-queue-item'), function (btn) { btn.classList.remove('is-selected'); });
        var index = [].map.call(queue.children, function (c) { return c; });
        index.forEach(function (c) { if (c.textContent.indexOf(parts[0].intake.answers.name || 'Untitled') === 0) c.classList.add('is-selected'); });
      }).catch(function (err) { AIGov.say(status, AIGov.errorText(err), 'bad'); });
    }

    function fact(label, value) {
      return el('div', { class: 'aig-fact' }, [el('dt', { text: label }), el('dd', { text: value || 'Not answered' })]);
    }

    function renderDetail(intake, duplicates) {
      AIGov.clear(detail);
      var a = intake.answers, screening = intake.screening;
      detail.appendChild(el('h2', { class: 'aig-h2', text: a.name || 'Untitled' }));
      detail.appendChild(el('p', { class: 'aig-muted', text: 'Submitted by ' + (intake.author_name || 'someone') + ' on ' + AIGov.date(intake.submitted_at)
        + (intake.business_unit_id && units[intake.business_unit_id] ? ', ' + units[intake.business_unit_id] : '') }));
      detail.appendChild(el('dl', { class: 'aig-facts' }, [
        fact('Purpose', a.purpose), fact('Owner', intake.owner_name), fact('How it is provided', labelled(vocab, 'deployment', a.deployment)),
        fact('Provider', a.provider_name), fact('Intended users', a.intended_users), fact('Planned use', a.planned_use),
        fact('Kinds of data', labelled(vocab, 'data_categories', a.data_categories)),
        fact('Who is affected', labelled(vocab, 'affected_people', a.affected_people)),
        fact('How much it decides', labelled(vocab, 'autonomy', a.autonomy)),
        fact('Affects decisions about people', a.affects_decisions === true ? 'Yes' : a.affects_decisions === false ? 'No' : ''),
        fact('Outside access', a.external_access === true ? 'Yes' : a.external_access === false ? 'No' : ''),
        fact('Jurisdictions', labelled(vocab, 'jurisdictions', a.jurisdictions)), fact('Human oversight', a.human_oversight),
        fact('Planned model changes', a.model_changes), fact('Target launch', a.target_launch)]));

      var tierBox = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigTierH' }, [
        el('h3', { id: 'aigTierH', class: 'aig-h3', text: 'Provisional tier' }),
        el('p', {}, [AIGov.tierChip(screening.tier, false), ' ',
          el('span', { class: 'aig-muted', text: 'An internal screening aid. It is not a legal classification and approves nothing. Rules ' + screening.rule_version + '.' })])]);
      if (screening.reasons.length) tierBox.appendChild(el('ul', {}, screening.reasons.map(function (r) { return el('li', { text: r.text }); })));
      if (screening.missing.length) tierBox.appendChild(el('p', { class: 'aig-hint', text: 'Not answered: ' + screening.missing.map(function (f) { return vocab.labels[f] || f; }).join(', ') + '.' }));
      detail.appendChild(tierBox);

      var dupBox = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigDupH' }, [el('h3', { id: 'aigDupH', class: 'aig-h3', text: 'Could this already be in the inventory?' })]);
      if (duplicates.length) {
        dupBox.appendChild(el('ul', {}, duplicates.map(function (d) {
          return el('li', {}, [el('a', { href: d.url, text: d.name, target: '_blank', rel: 'noopener' }), ' ' + d.reason.toLowerCase() + (d.has_ai_profile ? ', already an AI system' : '')]);
        })));
      } else { dupBox.appendChild(el('p', { class: 'aig-muted', text: 'No similar application you can see.' })); }
      detail.appendChild(dupBox);

      if (intake.status !== 'submitted') {
        detail.appendChild(el('p', { class: 'aig-muted', text: 'This request is ' + (STATUS_LABEL[intake.status] || intake.status).toLowerCase() + '.' }));
        return;
      }
      detail.appendChild(decisionForm(intake, duplicates));
    }

    function decisionForm(intake, duplicates) {
      var a = intake.answers;
      var form = el('form', { class: 'aig-panel', 'aria-labelledby': 'aigDecideH', novalidate: 'novalidate' });
      form.appendChild(el('h3', { id: 'aigDecideH', class: 'aig-h3', text: 'Your decision' }));
      var out = el('div', { class: 'aig-say' });

      var modeNew = el('input', { type: 'radio', name: 'mode', value: 'new', checked: true });
      var modeLink = el('input', { type: 'radio', name: 'mode', value: 'link' });
      form.appendChild(el('fieldset', { class: 'aig-fieldset' }, [el('legend', { text: 'Add to the inventory' }),
        el('label', { class: 'aig-radio' }, [modeNew, 'Create a new application']),
        el('label', { class: 'aig-radio' }, [modeLink, 'Link to an application that already exists'])]));

      var newBox = el('div', {});
      var name = el('input', { type: 'text', value: a.name || '', maxlength: '120' });
      var vendor = el('input', { type: 'text', value: a.provider_name || '', maxlength: '200' });
      var criticality = AIGov.select([{ id: 'low', name: 'Low' }, { id: 'medium', name: 'Medium' }, { id: 'high', name: 'High' }, { id: 'critical', name: 'Critical' }], 'medium');
      [AIGov.field('aigNewName', 'Application name', name).row, AIGov.field('aigNewVendor', 'Provider (optional)', vendor).row,
        AIGov.field('aigNewCrit', 'Criticality', criticality).row].forEach(function (r) { newBox.appendChild(r); });

      var linkBox = el('div', { hidden: true });
      var search = el('input', { type: 'search', autocomplete: 'off' });
      var results = el('div', { class: 'aig-results', role: 'radiogroup', 'aria-label': 'Applications' });
      linkBox.appendChild(AIGov.field('aigLinkSearch', 'Find the application', search, 'Type at least two letters.').row);
      linkBox.appendChild(results);
      var chosen = null;
      function showApps(items) {
        AIGov.clear(results);
        if (!items.length) { results.appendChild(el('p', { class: 'aig-muted', text: 'No matching application you can open.' })); return; }
        items.forEach(function (app) {
          var radio = el('input', { type: 'radio', name: 'app', value: String(app.id) });
          radio.addEventListener('change', function () { chosen = app.id; });
          results.appendChild(el('label', { class: 'aig-radio' }, [radio, app.name]));
        });
      }
      showApps(duplicates.filter(function (d) { return !d.has_ai_profile; }).map(function (d) { return { id: d.id, name: d.name }; }));
      search.addEventListener('input', AIGov.debounce(function () {
        if (search.value.trim().length < 2) return;
        AIGov.api('/ai-governance/api/applications/search' + AIGov.qs({ q: search.value.trim() })).then(function (d) { showApps(d.items); });
      }, 300));

      function toggle() { newBox.hidden = !modeNew.checked; linkBox.hidden = modeNew.checked; }
      modeNew.addEventListener('change', toggle); modeLink.addEventListener('change', toggle);
      form.appendChild(newBox); form.appendChild(linkBox);

      var tier = AIGov.select([{ id: 'lower', name: 'Lower' }, { id: 'moderate', name: 'Moderate' }, { id: 'elevated', name: 'Elevated' }], '', 'Keep the provisional tier');
      var tierReason = el('textarea', { rows: '2', maxlength: '1000' });
      form.appendChild(AIGov.field('aigAdopt', 'Adopt a different tier (optional)', tier, 'Say why in the box below. The tier is a screening aid; it does not approve or reject the use.').row);
      form.appendChild(AIGov.field('aigAdoptWhy', 'Why this tier', tierReason).row);
      var note = el('textarea', { rows: '3', maxlength: '1000' });
      form.appendChild(AIGov.field('aigNote', 'Note to the author (required to return or reject)', note).row);

      function act(path, body, done) {
        AIGov.say(out, 'Saving...');
        body.version = intake.version;
        AIGov.api('/ai-governance/api/review/requests/' + intake.id + '/' + path, 'POST', body).then(function (data) {
          var result = done(data);
          announce(result.text, result.href, result.linkText);
          selected = null;
          loadQueue(false, true);
        }).catch(function (err) {
          var fields = AIGov.fieldErrors(err);
          AIGov.say(out, AIGov.errorText(err) + (fields ? ' ' + Object.keys(fields).map(function (k) { return fields[k]; }).join(' ') : ''), 'bad');
        });
      }

      var accept = el('button', { type: 'button', class: 'btn btn-primary', text: 'Accept', on: { click: function () {
        var body = { note: note.value };
        if (modeNew.checked) body.new_application = { name: name.value, vendor_name: vendor.value, criticality: criticality.value };
        else if (chosen) body.application_id = chosen;
        else { AIGov.say(out, 'Choose the application to link to.', 'bad'); return; }
        if (tier.value) { body.adopted_tier = tier.value; body.tier_reason = tierReason.value; }
        act('approve', body, function (data) {
          return { text: 'Accepted. "' + (a.name || 'The AI use') + '" is now in the inventory.',
                   href: '/ai-governance/systems/' + data.application_id, linkText: 'Open the AI system' };
        });
      } } });
      var back = el('button', { type: 'button', class: 'btn btn-secondary', text: 'Return to author', on: { click: function () {
        act('return', { note: note.value }, function () { return { text: 'Returned to the author.' }; }); } } });
      var reject = el('button', { type: 'button', class: 'btn btn-ghost', text: 'Reject', on: { click: function () {
        act('reject', { reason: note.value }, function () { return { text: 'Rejected.' }; }); } } });
      form.appendChild(el('div', { class: 'aig-actions' }, [accept, back, reject]));
      form.appendChild(out);
      return form;
    }

    // Vendors and processes that were said to use AI (or nobody knows) and that no AI use covers yet.
    var flagged = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigFlagH', hidden: true }, [
      el('h2', { id: 'aigFlagH', class: 'aig-h3', text: 'Said to use AI, not yet registered' })]);
    root.appendChild(flagged);
    function loadFlagged() {
      AIGov.api('/ai-governance/api/flags').then(function (data) {
        if (!data.items.length) { flagged.hidden = true; return; }
        flagged.hidden = false;
        [].slice.call(flagged.querySelectorAll('ul')).forEach(function (n) { n.remove(); });
        flagged.appendChild(el('ul', { class: 'aig-list' }, data.items.map(function (item) {
          return el('li', {}, [el('span', { text: item.name }),
            AIGov.chip(item.kind === 'vendor' ? 'Vendor' : 'Process', 'info'),
            AIGov.chip(item.answer === 'yes' ? 'Uses AI' : 'Not sure', item.answer === 'yes' ? 'warn' : 'muted'),
            item.note ? el('span', { class: 'aig-muted', text: item.note }) : null,
            el('a', { class: 'btn btn-secondary btn-sm', href: item.register_url, text: 'Start a request' })]);
        })));
      }).catch(function () { /* the queue above is the main job of this page */ });
    }

    Promise.all([AIGov.api('/ai-governance/api/vocabulary'), AIGov.api('/ai-governance/api/business-units')]).then(function (parts) {
      vocab = parts[0];
      parts[1].items.forEach(function (u) { units[u.id] = u.name; });
      loadFlagged();
      loadQueue(false);
    }).catch(function (err) { AIGov.say(status, AIGov.errorText(err), 'bad'); });
  };
}(window));
