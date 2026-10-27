/* AI Governance: the workspace of one AI use. Every tab loads on its own, so a source that is slow, denied or down
   affects only its tab, and says which of those it is. Needs ai_governance_common.js and api_client.js. */
(function (global) {
  'use strict';

  var AIGov = global.AIGov, el = AIGov.el;

  var TAB_TITLES = { overview: 'Overview', review_desk: 'Review desk', assessments: 'Assessments', risks_controls: 'Risks & controls',
    data_vendors: 'Data & vendors', evidence: 'Evidence', oversight: 'Human oversight', decisions: 'Decisions', monitoring: 'Monitoring',
    activity: 'Activity' };
  var TAB_VERBS = { assessments: ['assesses'], risks_controls: ['covers', 'affects', 'impacts'],
    data_vendors: ['uses_data', 'provided_by', 'supports', 'depends_on'] };
  var KIND_NAMES = { 'sentinel/aiia': 'AI impact assessment', 'sentinel/dpia': 'DPIA', 'orm/aims': 'AI management assessment',
    'bcm/incident': 'continuity incident', 'orm/event': 'operational event', 'sentinel/breach': 'breach', 'erm/obligation': 'regulatory obligation',
    'governance/data_asset': 'data asset', 'governance/process': 'business process', 'governance/application': 'application',
    'sentinel/vendor': 'privacy vendor', 'grid/vendor': 'audit vendor', 'bcm/vendor': 'continuity vendor' };
  var QUIET = { no_access: 'aig-note-muted', unavailable: 'aig-note-warn', not_started: 'aig-note-muted', not_measured: 'aig-note-muted', empty: 'aig-note-muted' };

  AIGov.workspace = function (root, config) {
    var id = config.applicationId;
    var system = null, kinds = [];
    var tablist = el('div', { class: 'aig-tabs', role: 'tablist', 'aria-label': 'Sections of this AI system' });
    var panel = el('div', { class: 'aig-tabpanel', role: 'tabpanel', tabindex: '0' });
    var status = el('div', { class: 'aig-say', role: 'status' });
    var current = (global.location.hash || '#overview').slice(1);
    if (!TAB_TITLES[current]) current = 'overview';
    root.appendChild(tablist); root.appendChild(status); root.appendChild(panel);

    // The review desk is for reviewers: what it loads needs the right to review.
    function tabOrder() {
      return Object.keys(TAB_TITLES).filter(function (tab) { return tab !== 'review_desk' || (system && system.can.review); });
    }

    function renderTabs() {
      AIGov.clear(tablist);
      tabOrder().forEach(function (tab) {
        tablist.appendChild(el('button', { type: 'button', role: 'tab', id: 'aigtab_' + tab, class: 'aig-tab' + (tab === current ? ' is-current' : ''),
          'aria-selected': tab === current ? 'true' : 'false', 'aria-controls': 'aigpanel', tabindex: tab === current ? '0' : '-1', text: TAB_TITLES[tab],
          on: { click: function () { open(tab); }, keydown: function (event) {
            var order = tabOrder(), at = order.indexOf(tab), next = null;
            if (event.key === 'ArrowRight') next = order[(at + 1) % order.length];
            else if (event.key === 'ArrowLeft') next = order[(at + order.length - 1) % order.length];
            else if (event.key === 'Home') next = order[0];
            else if (event.key === 'End') next = order[order.length - 1];
            if (next) { event.preventDefault(); open(next); document.getElementById('aigtab_' + next).focus(); }
          } } }));
      });
      panel.id = 'aigpanel';
      panel.setAttribute('aria-labelledby', 'aigtab_' + current);
    }

    function open(tab) {
      current = tab;
      global.history.replaceState(null, '', global.location.pathname + global.location.search + '#' + tab);
      renderTabs();
      if (tab === 'overview') renderOverview(); else loadTab(tab);
    }

    // ── Overview ────────────────────────────────────────────────────────────

    function refresh() {
      return AIGov.api('/ai-governance/api/systems/' + id).then(function (data) {
        system = data; renderHeader(); return data;
      });
    }

    function renderHeader() {
      var a = system.application, p = system.profile, host = document.getElementById('aigHeader');
      if (!host) return;
      AIGov.clear(host);
      var chips = [];
      if (p) chips.push(AIGov.tierChip(p.tier, p.adopted_tier !== null));
      if (!a.active) chips.push(AIGov.chip('Retired', 'muted'));
      host.appendChild(el('div', { class: 'aig-chips' }, chips));
      host.appendChild(el('dl', { class: 'aig-facts aig-facts-inline' }, [
        fact('Owner', a.owner || 'No owner'), fact('Business unit', a.business_unit || 'Whole organization'), fact('Department', a.department),
        fact('Provider', a.vendor), fact('Hosting', a.hosting),
        fact('Criticality', a.criticality ? a.criticality.charAt(0).toUpperCase() + a.criticality.slice(1) : null)]));
      if (!a.active && a.retired_reason) host.appendChild(el('p', { class: 'aig-banner aig-banner-warn', text: 'Retired: ' + a.retired_reason }));
    }

    function fact(label, value) { return el('div', { class: 'aig-fact' }, [el('dt', { text: label }), el('dd', { text: value || 'Not recorded' })]); }
    function words(table, value) { return Array.isArray(value) ? value.map(function (v) { return table[v] || v; }).join(', ') : (table[value] || value); }
    function yn(v) { return v === true ? 'Yes' : v === false ? 'No' : null; }

    function renderOverview() {
      AIGov.clear(panel);
      AIGov.say(status, '');
      var p = system.profile, can = system.can, L = system.labels;
      if (system.next_actions.length) {
        panel.appendChild(el('section', { class: 'aig-panel', 'aria-labelledby': 'aigNextH' }, [
          el('h2', { id: 'aigNextH', class: 'aig-h3', text: 'Next steps' }),
          el('ul', {}, system.next_actions.map(function (n) { return el('li', { text: n.text }); }))]));
      }
      if (!p) {
        var box = el('section', { class: 'aig-panel' }, [el('h2', { class: 'aig-h3', text: 'AI profile' }),
          el('p', { class: 'aig-muted', text: 'This application has no AI profile yet, so it is not counted as an AI use.' })]);
        if (can.review) box.appendChild(el('button', { type: 'button', class: 'btn btn-primary btn-sm', text: 'Add the AI profile', on: { click: function () { profileDialog(null); } } }));
        panel.appendChild(box);
      } else {
        panel.appendChild(el('section', { class: 'aig-panel', 'aria-labelledby': 'aigProfH' }, [
          el('h2', { id: 'aigProfH', class: 'aig-h3', text: 'AI profile' }),
          el('dl', { class: 'aig-facts' }, [
            fact('External register reference', p.external_ref),
            fact('Imported source review', p.import_review_state || 'Not imported'),
            fact('Workbook claimed status', p.import_claimed_status),
            fact('Purpose', p.purpose), fact('What it does', words(L.capability_type, p.capability_type)), fact('Provided', words(L.deployment, p.deployment)),
            fact('Provider or model', p.provider_note), fact('Sponsor', p.sponsor_name), fact('Intended users', p.intended_users), fact('Kinds of data', words(L.data_categories, p.data_categories)),
            fact('Who is affected', words(L.affected_people, p.affected_people)), fact('How much it decides', words(L.autonomy, p.autonomy)),
            fact('Affects decisions about people', yn(p.affects_decisions)), fact('Outside access', yn(p.external_access)),
            fact('Jurisdictions', words(L.jurisdictions, p.jurisdictions)), fact('Human oversight', p.human_oversight), fact('Target launch', p.target_launch),
            fact('Last reviewed', AIGov.date(p.last_reviewed_at)), fact('Next review', AIGov.date(p.next_review_at) || 'Not scheduled')]),
          can.review ? el('div', { class: 'aig-actions' }, [
            el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Edit profile', on: { click: function () { profileDialog(p); } } }),
            el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Mark as reviewed today', on: { click: markReviewed } }),
            p.import_review_state === 'pending' || p.import_review_state === 'disputed'
              ? el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Review imported facts',
                  on: { click: function () { reasonDialog('Review imported source facts', 'What did you verify against the source?',
                    'Record source review', 'import-review', { control: AIGov.select([
                      { id: 'reviewed', name: 'Reviewed source facts' }, { id: 'disputed', name: 'Disputed source facts' }
                    ], '', 'Choose an outcome'), label: 'Source review result',
                    body: function (reason) { return { reason: reason, version: p.version,
                      decision: document.getElementById('aigDlgExtra').value }; } }); } } }) : null]) : null]));
        var tier = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigTierH' }, [el('h2', { id: 'aigTierH', class: 'aig-h3', text: 'Tier' }),
          el('p', {}, [AIGov.tierChip(p.tier, p.adopted_tier !== null), ' ', el('span', { class: 'aig-muted', text:
            p.adopted_tier ? 'Adopted by a reviewer on ' + AIGov.date(p.adopted_at) + '. Provisional reading: ' + (L.tiers[p.provisional_tier] || 'Needs review') + '.'
              : 'Provisional, from rules ' + (p.tier_rule_version || 'v1') + '. A reviewer can adopt a tier of their own.' })])]);
        if (p.adopted_tier_reason) tier.appendChild(el('p', { text: 'Reason: ' + p.adopted_tier_reason }));
        if (p.tier_reasons.length) tier.appendChild(el('ul', {}, p.tier_reasons.map(function (r) { return el('li', { text: r.text }); })));
        if (p.missing.length) tier.appendChild(el('p', { class: 'aig-hint', text: 'Not answered: ' + p.missing.map(function (f) { return f.replace(/_/g, ' '); }).join(', ') + '.' }));
        tier.appendChild(el('p', { class: 'aig-hint', text: 'An internal screening aid, not a legal classification. It does not approve or reject the use.' }));
        if (can.review) tier.appendChild(el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Adopt a tier', on: { click: tierDialog } }));
        panel.appendChild(tier);
      }
      var guidanceHost = el('div', {});
      panel.appendChild(guidanceHost);
      if (p) renderGuidance(guidanceHost);
      if (p && can.packs) panel.appendChild(el('section', { class: 'aig-panel' }, [
        el('h2', { class: 'aig-h3', text: 'Review packs' }),
        el('p', { class: 'aig-muted', text: 'Prepare a dated account of this use for one named reviewer. Preview its content before sharing.' }),
        el('a', { class: 'btn btn-secondary btn-sm', href: '/ai-governance/packs?application_id=' + id, text: 'Prepare or manage packs' })]));
      if (can.review) {
        var a = system.application;
        panel.appendChild(el('section', { class: 'aig-panel' }, [el('h2', { class: 'aig-h3', text: a.active ? 'Retire this use' : 'Restore this use' }),
          el('p', { class: 'aig-muted', text: a.active ? 'Retiring keeps its history, assessments and links. It is never deleted.' : 'Bring this use back into the active inventory.' }),
          el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: a.active ? 'Retire' : 'Restore', on: { click: a.active ? retireDialog : restore } })]));
      }
    }

    function markReviewed() {
      AIGov.api('/ai-governance/api/systems/' + id + '/reviewed', 'POST', {}).then(refresh).then(renderOverview)
        .catch(function (err) { AIGov.say(status, AIGov.errorText(err), 'bad'); });
    }
    function restore() {
      AIGov.api('/ai-governance/api/systems/' + id + '/restore', 'POST', {}).then(refresh).then(renderOverview)
        .catch(function (err) { AIGov.say(status, AIGov.errorText(err), 'bad'); });
    }

    function reasonDialog(title, label, action, path, extra) {
      AIGov.dialog(title, function (box, close) {
        var text = el('textarea', { rows: '3', maxlength: '1000' });
        var out = el('div', { class: 'aig-say' });
        var extraControl = extra ? extra.control : null;
        if (extraControl) box.appendChild(AIGov.field('aigDlgExtra', extra.label, extraControl).row);
        box.appendChild(AIGov.field('aigDlgReason', label, text).row);
        box.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: action, on: { click: function () {
            var body = { reason: text.value };
            if (extra) body = extra.body(text.value);
            AIGov.say(out, 'Saving...');
            AIGov.api('/ai-governance/api/systems/' + id + '/' + path, 'POST', body).then(function () { close(); return refresh(); })
              .then(renderOverview).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
          } } }),
          el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
        box.appendChild(out);
      });
    }
    function retireDialog() { reasonDialog('Retire this AI use', 'Why is it being retired?', 'Retire', 'retire'); }
    function tierDialog() {
      var select = AIGov.select([{ id: 'lower', name: 'Lower' }, { id: 'moderate', name: 'Moderate' }, { id: 'elevated', name: 'Elevated' }], system.profile.adopted_tier || '', 'Choose a tier');
      reasonDialog('Adopt a tier', 'Why this tier?', 'Adopt', 'tier', { label: 'Tier', control: select,
        body: function (reason) { return { tier: select.value, reason: reason, version: system.profile.version }; } });
    }

    function profileDialog(profile) {
      var L = system.labels, fields = {};
      AIGov.dialog(profile ? 'Edit the AI profile' : 'Add the AI profile', function (box, close) {
        var form = el('form', { class: 'aig-form', novalidate: 'novalidate' });
        form.addEventListener('submit', function (event) { event.preventDefault(); });
        function text(key, label, opts) {
          opts = opts || {};
          var input = el(opts.multiline ? 'textarea' : 'input', opts.multiline ? { rows: '3', maxlength: '2000' } : { type: opts.type || 'text', maxlength: '200' });
          input.value = profile && profile[key] ? profile[key] : '';
          fields[key] = { get: function () { return input.value.trim() || null; }, input: input };
          form.appendChild(AIGov.field('pf_' + key, label, input).row);
        }
        function choice(key, label, table) {
          var select = AIGov.select(Object.keys(table).map(function (k) { return { id: k, name: table[k] }; }), profile ? profile[key] : '', 'Not answered');
          fields[key] = { get: function () { return select.value || null; }, input: select };
          form.appendChild(AIGov.field('pf_' + key, label, select).row);
        }
        function checks(key, label, table) {
          var group = el('fieldset', { class: 'aig-fieldset', id: 'pf_' + key }, [el('legend', { text: label })]);
          var boxes = {};
          Object.keys(table).forEach(function (v) {
            var b = el('input', { type: 'checkbox', value: v, checked: profile && (profile[key] || []).indexOf(v) >= 0 });
            boxes[v] = b; group.appendChild(el('label', { class: 'aig-check' }, [b, table[v]]));
          });
          fields[key] = { get: function () { return Object.keys(boxes).filter(function (v) { return boxes[v].checked; }); }, input: group };
          form.appendChild(group);
        }
        function yesno(key, label) {
          var select = AIGov.select([{ id: 'yes', name: 'Yes' }, { id: 'no', name: 'No' }], profile && profile[key] !== null && profile[key] !== undefined ? (profile[key] ? 'yes' : 'no') : '', 'Not sure');
          fields[key] = { get: function () { return select.value === 'yes' ? true : select.value === 'no' ? false : null; }, input: select };
          form.appendChild(AIGov.field('pf_' + key, label, select).row);
        }
        text('purpose', 'Purpose', { multiline: true });
        choice('capability_type', 'What it does', L.capability_type);
        choice('deployment', 'How it is provided', L.deployment);
        text('provider_name', 'Provider or model');
        if (profile) fields.provider_name.input.value = profile.provider_note || '';
        text('intended_users', 'Intended users');
        var sponsor = el('select', {}, [el('option', { value: '', text: 'No sponsor named' })]);
        if (profile && profile.sponsor_user_id && profile.sponsor_name) {
          sponsor.appendChild(el('option', { value: String(profile.sponsor_user_id), text: profile.sponsor_name, selected: true }));
        }
        fields.sponsor_user_id = { get: function () { return sponsor.value ? parseInt(sponsor.value, 10) : null; }, input: sponsor };
        var sponsorSearch = el('input', { type: 'search', maxlength: '100', placeholder: 'Search colleagues by name' });
        form.appendChild(AIGov.field('pf_sponsor_search', 'Find a sponsor', sponsorSearch).row);
        form.appendChild(AIGov.field('pf_sponsor_user_id', 'Accountable sponsor', sponsor,
          'Choose a person in this organization who sponsors the proposed use.').row);
        var sponsorLookup = 0;
        function findSponsors() {
          var lookup = ++sponsorLookup, selected = sponsor.value;
          var chosen = sponsor.options[sponsor.selectedIndex];
          var chosenName = chosen ? chosen.text : '';
          AIGov.api('/ai-governance/api/people?q=' + encodeURIComponent(sponsorSearch.value.trim())).then(function (data) {
            if (lookup !== sponsorLookup) return;
            AIGov.clear(sponsor);
            sponsor.appendChild(el('option', { value: '', text: 'No sponsor named' }));
            if (selected && !(data.items || []).some(function (p) { return String(p.id) === selected; })) {
              sponsor.appendChild(el('option', { value: selected, text: chosenName || 'Selected sponsor' }));
            }
            (data.items || []).forEach(function (person) {
              sponsor.appendChild(el('option', { value: String(person.id), text: person.name }));
            });
            sponsor.value = selected;
            if (sponsor.value !== selected) sponsor.value = '';
          }).catch(function () { /* Keep the current choice if the lookup is unavailable. */ });
        }
        sponsorSearch.addEventListener('input', findSponsors);
        findSponsors();
        checks('data_categories', 'Kinds of data', L.data_categories);
        checks('affected_people', 'Who is affected', L.affected_people);
        choice('autonomy', 'How much it decides', L.autonomy);
        yesno('affects_decisions', 'Feeds decisions with significant effects on people');
        yesno('external_access', 'People outside the organization use it or see its output');
        checks('jurisdictions', 'Jurisdictions', L.jurisdictions);
        text('human_oversight', 'Human oversight', { multiline: true });
        text('target_launch', 'Target launch', { type: 'date' });
        var cadence = el('input', { type: 'number', min: '1', max: '60', step: '1' });
        cadence.value = profile && profile.review_cadence_months ? profile.review_cadence_months : '';
        form.appendChild(AIGov.field('pf_cadence', 'Review every (months)', cadence).row);
        var out = el('div', { class: 'aig-say' });
        form.appendChild(out);
        form.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: 'Save', on: { click: function () {
            var answers = {};
            Object.keys(fields).forEach(function (k) { answers[k] = fields[k].get(); });
            if (cadence.value) answers.review_cadence_months = parseInt(cadence.value, 10);
            AIGov.say(out, 'Saving...');
            var request = profile
              ? AIGov.api('/ai-governance/api/systems/' + id + '/profile', 'PUT', { answers: answers, version: profile.version })
              : AIGov.api('/ai-governance/api/systems/' + id + '/profile', 'POST', { answers: answers });
            request.then(function () { close(); return refresh(); }).then(renderOverview).catch(function (err) {
              var fe = AIGov.fieldErrors(err);
              AIGov.say(out, AIGov.errorText(err) + (fe ? ' ' + Object.keys(fe).map(function (k) { return fe[k]; }).join(' ') : ''), 'bad');
            });
          } } }),
          el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
        box.appendChild(form);
      });
    }

    // ── The other tabs ──────────────────────────────────────────────────────

    function loadTab(tab) {
      AIGov.clear(panel);
      if (tab === 'oversight') {
        panel.removeAttribute('aria-busy');
        AIGov.say(status, '');
        AIGov.oversightPanel(panel, { applicationId: id, canReview: system.can.review,
          canDecide: system.can.decide, viewerId: system.viewer_id });
        return;
      }
      if (tab === 'monitoring') {
        panel.removeAttribute('aria-busy');
        AIGov.say(status, '');
        AIGov.monitoringPanel(panel, { applicationId: id });
        return;
      }
      if (tab === 'decisions') {
        panel.removeAttribute('aria-busy');
        AIGov.say(status, '');
        AIGov.decisionsPanel(panel, { applicationId: id, name: system.application.name, onChanged: refresh });
        return;
      }
      if (tab === 'review_desk') {
        panel.removeAttribute('aria-busy');
        AIGov.say(status, '');
        AIGov.outstandingPanel(panel, { applicationId: id });
        AIGov.precedentsPanel(panel, { subjectKind: 'application', subjectId: id, canReview: system.can.review });
        if (system.source_request) {
          AIGov.questionsPanel(panel, { intakeId: system.source_request.id, canAsk: system.can.review });
        }
        AIGov.responsesPanel(panel, { applicationId: id });
        return;
      }
      AIGov.say(status, 'Loading...');
      panel.setAttribute('aria-busy', 'true');
      AIGov.api('/ai-governance/api/systems/' + id + '/tabs/' + tab).then(function (data) {
        if (current !== tab) return;
        panel.removeAttribute('aria-busy');
        AIGov.say(status, '');
        renderTab(tab, data);
      }).catch(function (err) {
        if (current !== tab) return;
        panel.removeAttribute('aria-busy');
        AIGov.say(status, AIGov.errorText(err), 'bad');
      });
    }

    function renderTab(tab, data) {
      AIGov.clear(panel);
      if (tab === 'assessments') { var checklistHost = el('div', {}); panel.appendChild(checklistHost); renderChecklist(checklistHost); }
      data.sections.forEach(function (section) { panel.appendChild(renderSection(tab, section)); });
      if (tab === 'risks_controls') { var controlsHost = el('div', {}); panel.appendChild(controlsHost); renderControls(controlsHost); }
      if (TAB_VERBS[tab] && system.can.link) {
        panel.appendChild(el('div', { class: 'aig-actions' }, [el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Link a record',
          on: { click: function () { linkDialog(tab); } } })]));
      }
      if (tab === 'evidence') {
        panel.appendChild(el('p', { class: 'aig-hint' }, ['Attach evidence in the ', el('a', { href: '/evidence/', text: 'Evidence Vault' }),
          ': choose the item, then link it to this application.']));
      }
    }

    function renderSection(tab, section) {
      var box = el('section', { class: 'aig-panel' }, [el('h2', { class: 'aig-h3', text: section.title })]);
      if (section.state === 'ok') {
        box.appendChild(el('ul', { class: 'aig-list' }, section.items.map(function (item) {
          var head = item.url ? el('a', { href: item.url, text: item.title }) : el('span', { text: item.title });
          var meta = [item.status ? AIGov.chip(item.status) : null, item.subtitle ? el('span', { class: 'aig-muted', text: item.subtitle }) : null,
            item.source ? el('span', { class: 'aig-muted', text: item.source }) : null, item.updated_at ? el('span', { class: 'aig-muted', text: item.updated_at }) : null];
          var remove = item.link_id && system.can.link ? el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Remove link',
            'aria-label': 'Remove the link to ' + item.title, on: { click: function () { removeLink(item, tab); } } }) : null;
          return el('li', {}, [head, el('span', { class: 'aig-meta' }, meta), remove]);
        })));
      } else {
        box.appendChild(el('p', { class: QUIET[section.state] || 'aig-note-muted', text: section.note || 'Nothing here yet.' }));
      }
      return box;
    }

    function removeLink(item, tab) {
      AIGov.dialog('Remove this link?', function (box, close) {
        box.appendChild(el('p', { text: 'The link to "' + item.title + '" will be removed. The record itself is not touched.' }));
        var out = el('div', { class: 'aig-say' });
        box.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: 'Remove link', on: { click: function () {
            AIGov.api('/api/links/' + item.link_id, 'DELETE').then(function () { close(); loadTab(tab); })
              .catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
          } } }), el('button', { type: 'button', class: 'btn btn-ghost', text: 'Keep it', on: { click: close } })]));
        box.appendChild(out);
      });
    }

    function linkDialog(tab) {
      var allowed = kinds.filter(function (k) { return TAB_VERBS[tab].indexOf(k.verb) >= 0; });
      AIGov.dialog('Link a record', function (box, close) {
        var choose = AIGov.select(allowed.map(function (k, i) { return { id: i, name: k.label + ': ' + (KIND_NAMES[k.module + '/' + k.type] || k.type) }; }), '', 'What are you linking?');
        var search = el('input', { type: 'search', autocomplete: 'off' });
        var results = el('div', { class: 'aig-results' });
        var out = el('div', { class: 'aig-say' });
        box.appendChild(AIGov.field('aigLinkKind', 'Kind of link', choose).row);
        box.appendChild(AIGov.field('aigLinkSearch', 'Find the record', search, 'Leave empty to list the first few you can open.').row);
        box.appendChild(results);
        box.appendChild(out);
        function find() {
          AIGov.clear(results);
          if (choose.value === '') return;
          var kind = allowed[parseInt(choose.value, 10)];
          AIGov.api('/ai-governance/api/systems/' + id + '/link-candidates' + AIGov.qs({ verb: kind.verb, module: kind.module, type: kind.type, q: search.value.trim() })).then(function (data) {
            if (!data.items.length) { results.appendChild(el('p', { class: 'aig-muted', text: 'No record you can open matches.' })); return; }
            data.items.forEach(function (r) {
              results.appendChild(el('div', { class: 'aig-result-row' }, [el('span', { text: r.title }), el('button', { type: 'button', class: 'btn btn-primary btn-sm', text: 'Link',
                'aria-label': 'Link ' + r.title, on: { click: function () { create(kind, r); } } })]));
            });
          }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
        }
        function create(kind, record) {
          var other = { module: kind.module, type: kind.type, id: record.id }, app = { module: 'governance', type: 'application', id: id };
          var source = kind.direction === 'incoming' ? other : app, target = kind.direction === 'incoming' ? app : other;
          AIGov.say(out, 'Linking...');
          AIGov.api('/api/links', 'POST', { source_module: source.module, source_type: source.type, source_id: source.id,
            target_module: target.module, target_type: target.type, target_id: target.id, relationship: kind.verb }).then(function () {
            close(); loadTab(tab);
          }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
        }
        choose.addEventListener('change', find);
        search.addEventListener('input', AIGov.debounce(find, 250));
        box.appendChild(el('div', { class: 'aig-actions' }, [el('button', { type: 'button', class: 'btn btn-ghost', text: 'Close', on: { click: close } })]));
      });
    }

    // ── Guidance: the path to a decision, the checklist, AI controls with proof, quality checks ─────

    var STATE_LABEL = { not_started: 'Not started', in_progress: 'In progress', complete: 'Done', no_access: 'No access', unavailable: 'Could not be read' };
    var NEED_LABEL = { required: 'Needed', recommended: 'Recommended', not_applicable: 'Not applicable', needs_review: 'Needs review' };
    var NEED_KIND = { required: 'bad', recommended: 'info', not_applicable: 'muted', needs_review: 'warn' };

    function stateChip(step) {
      var kind = step.state === 'complete' ? 'good' : (step.state === 'unavailable' ? 'warn' : 'muted');
      return AIGov.chip(STATE_LABEL[step.state] || step.state, kind);
    }

    function renderGuidance(host) {
      AIGov.clear(host);
      host.appendChild(el('div', { class: 'aig-actions' }, [el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Explain this status',
        on: { click: function () { AIGov.explainDialog(id, system.application.name); } } })]));
      var pathHost = el('div', {}), qualityHost = el('div', {});
      host.appendChild(pathHost); host.appendChild(qualityHost);
      renderPath(pathHost);
      renderQuality(qualityHost, function () { renderGuidance(host); });
    }

    function renderPath(host) {
      AIGov.api('/ai-governance/api/systems/' + id + '/checklist').then(function (data) {
        if (!data.profile || !data.steps.length) return;
        var box = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigPathH' }, [el('h2', { id: 'aigPathH', class: 'aig-h3', text: 'Path to a decision' })]);
        box.appendChild(el('ol', { class: 'aig-path' }, data.steps.map(function (s) {
          return el('li', {}, [
            el('a', { href: '#assessments', text: s.title, on: { click: function (event) { event.preventDefault(); open('assessments'); } } }),
            AIGov.chip(NEED_LABEL[s.effective], NEED_KIND[s.effective]),
            s.effective === 'not_applicable' ? null : stateChip(s),
            s.stale ? AIGov.chip('Out of date', 'warn') : null]);
        })));
        if (data.unresolved.length) {
          var names = data.steps.filter(function (s) { return data.unresolved.indexOf(s.key) >= 0; }).map(function (s) { return s.title; });
          box.appendChild(el('p', { class: 'aig-hint', text: 'A decision waits for: ' + names.join(', ') + '.' }));
        }
        host.appendChild(box);
      }).catch(function () { /* the rest of the overview does not depend on it */ });
    }

    function renderQuality(host, again) {
      AIGov.api('/ai-governance/api/systems/' + id + '/quality').then(function (data) {
        var open_ = data.findings.filter(function (f) { return !f.dismissed; });
        var set_aside = data.findings.filter(function (f) { return f.dismissed; });
        var box = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigQualH' }, [
          el('h2', { id: 'aigQualH', class: 'aig-h3', text: open_.length ? 'Quality checks (' + open_.length + ' open)' : 'Quality checks' })]);
        if (!data.findings.length && !data.unchecked.length) box.appendChild(el('p', { class: 'aig-note-muted', text: 'The checks found nothing to act on (rules ' + data.rule_version + ').' }));
        if (open_.length) {
          box.appendChild(el('ul', { class: 'aig-list' }, open_.map(function (f) {
            var kids = [AIGov.chip(f.severity === 'error' ? 'Needs doing' : 'Check', f.severity === 'error' ? 'bad' : 'warn'),
              el('span', {}, [el('strong', { text: f.title }), el('div', { class: 'aig-hint', text: f.why + ' (rule ' + f.rule + ' ' + f.rule_version + ')' })]),
              el('a', { class: 'btn btn-secondary btn-sm', href: f.fix.url, text: f.fix.label })];
            if (system.can.review) kids.push(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Set aside',
              'aria-label': 'Set aside: ' + f.title, on: { click: function () { dismissDialog(f, again); } } }));
            return el('li', {}, kids);
          })));
        }
        if (data.unchecked.length) box.appendChild(el('p', { class: 'aig-note-warn', text: 'Could not be checked just now: ' + data.unchecked.join(', ') + '. This is not a clean result.' }));
        if (set_aside.length) {
          var details = el('details', {}, [el('summary', { text: 'Set aside (' + set_aside.length + ')' })]);
          details.appendChild(el('ul', { class: 'aig-list' }, set_aside.map(function (f) {
            var kids = [el('span', {}, [el('strong', { text: f.title }),
              el('div', { class: 'aig-hint', text: 'Set aside by ' + (f.dismissed.by || 'someone') + ' on ' + f.dismissed.at + ': ' + f.dismissed.reason +
                (f.dismissed.expires_at ? ' (until ' + f.dismissed.expires_at + ')' : '') })])];
            if (system.can.review) kids.push(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Reopen', on: { click: function () {
              AIGov.api('/ai-governance/api/systems/' + id + '/quality/dismiss' + AIGov.qs({ key: f.key }), 'DELETE').then(again)
                .catch(function (err) { AIGov.say(status, AIGov.errorText(err), 'bad'); });
            } } }));
            return el('li', {}, kids);
          })));
          box.appendChild(details);
        }
        host.appendChild(box);
      }).catch(function (err) { host.appendChild(el('p', { class: 'aig-note-warn', text: 'The quality checks could not be loaded: ' + AIGov.errorText(err) })); });
    }

    function dismissDialog(finding, done) {
      AIGov.dialog('Set this check aside', function (box, close) {
        box.appendChild(el('p', { text: finding.title }));
        var reason = el('textarea', { rows: '3', maxlength: '500' });
        var until = el('input', { type: 'date' });
        var out = el('div', { class: 'aig-say' });
        box.appendChild(AIGov.field('aigDismissWhy', 'Why is this not a problem?', reason).row);
        box.appendChild(AIGov.field('aigDismissUntil', 'Until (optional)', until, 'It comes back on this date, or at once if the facts change.').row);
        box.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: 'Set aside', on: { click: function () {
            AIGov.say(out, 'Saving...');
            AIGov.api('/ai-governance/api/systems/' + id + '/quality/dismiss', 'POST', { key: finding.key, reason: reason.value, expires_at: until.value || null })
              .then(function () { close(); done(); }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
          } } }), el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
        box.appendChild(out);
      });
    }

    function renderChecklist(host) {
      AIGov.api('/ai-governance/api/systems/' + id + '/checklist').then(function (data) {
        var box = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigCheckH' }, [el('h2', { id: 'aigCheckH', class: 'aig-h3', text: 'What this use needs' })]);
        if (!data.profile) {
          box.appendChild(el('p', { class: 'aig-note-muted', text: 'Add the AI profile first. The steps follow from its answers.' }));
          host.appendChild(box);
          return;
        }
        box.appendChild(el('p', { class: 'aig-hint', text: 'Worked out from the profile by rules ' + data.rule_version + '. Each step opens the form that does the work; nothing is copied here.' }));
        var table = el('table', { class: 'aig-table' }, [el('thead', {}, [el('tr', {}, ['Step', 'Needed', 'Where it stands', ''].map(function (h) { return el('th', { scope: 'col', text: h }); }))])]);
        var body = el('tbody', {});
        data.steps.forEach(function (s) {
          var why = el('ul', {}, s.reasons.map(function (r) { return el('li', { text: r }); }));
          var applies = s.effective !== 'not_applicable' || s.records.length > 0;
          var stands = applies ? [stateChip(s)] : [el('span', { class: 'aig-muted', text: 'Nothing to do' })];
          if (s.stale) stands.push(AIGov.chip('Out of date', 'warn'));
          if (s.records.length) stands.push(el('ul', {}, s.records.map(function (r) {
            return el('li', {}, [r.url ? el('a', { href: r.url + (r.url.indexOf('?') >= 0 ? '&' : '?') + 'aig_return=' + id, text: r.title }) : r.title, ' ', AIGov.chip(r.status || 'recorded')]);
          })));
          if (applies && s.state === 'no_access') stands.push(el('div', { class: 'aig-hint', text: 'You do not have access to these records.' }));
          var needed = [AIGov.chip(NEED_LABEL[s.effective], NEED_KIND[s.effective]), why];
          if (s.override) {
            needed.push(el('div', { class: 'aig-hint', text: 'Marked not applicable by ' + (s.override.set_by || 'a reviewer') + ' on ' + AIGov.date(s.override.set_at) + ': ' + s.override.reason }));
            if (s.override.out_of_date) needed.push(AIGov.chip('Judged against older facts: look again', 'warn'));
          }
          var actions = [];
          if (s.effective !== 'not_applicable' && s.state === 'not_started') actions.push(el('a', { class: 'btn btn-secondary btn-sm', href: s.action.url, text: s.action.label }));
          if (system.can.review && s.applicability === 'required' && !(s.override && !s.override.out_of_date)) {
            actions.push(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Not applicable', 'aria-label': 'Mark ' + s.title + ' not applicable',
              on: { click: function () { notApplicableDialog(s, function () { open('assessments'); }); } } }));
          }
          if (system.can.review && s.override) {
            actions.push(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Put back', 'aria-label': 'Put ' + s.title + ' back as needed', on: { click: function () {
              AIGov.api('/ai-governance/api/systems/' + id + '/checklist/' + encodeURIComponent(s.key), 'DELETE').then(function () { open('assessments'); })
                .catch(function (err) { AIGov.say(status, AIGov.errorText(err), 'bad'); });
            } } }));
          }
          body.appendChild(el('tr', {}, [el('td', {}, [el('strong', { text: s.title }), el('div', { class: 'aig-hint', text: s.module })]),
            el('td', {}, needed), el('td', {}, stands), el('td', {}, actions)]));
        });
        table.appendChild(body);
        box.appendChild(el('div', { class: 'aig-tablewrap' }, [table]));
        host.appendChild(box);
      }).catch(function (err) { host.appendChild(el('p', { class: 'aig-note-warn', text: 'The checklist could not be loaded: ' + AIGov.errorText(err) })); });
    }

    function notApplicableDialog(step, done) {
      AIGov.dialog('Mark "' + step.title + '" not applicable', function (box, close) {
        var reason = el('textarea', { rows: '3', maxlength: '500' });
        var out = el('div', { class: 'aig-say' });
        box.appendChild(el('p', { class: 'aig-muted', text: 'The rules say this step is needed. Say why it is not, so the next reviewer can see your reasoning. If the use changes you will be asked to look again.' }));
        box.appendChild(AIGov.field('aigNaWhy', 'Why does this not apply?', reason).row);
        box.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: 'Save', on: { click: function () {
            AIGov.say(out, 'Saving...');
            AIGov.api('/ai-governance/api/systems/' + id + '/checklist/' + encodeURIComponent(step.key), 'PUT', { reason: reason.value })
              .then(function () { close(); done(); }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
          } } }), el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
        box.appendChild(out);
      });
    }

    function renderControls(host) {
      AIGov.api('/ai-governance/api/systems/' + id + '/controls').then(function (data) {
        var box = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigCtlH' }, [el('h2', { id: 'aigCtlH', class: 'aig-h3', text: 'AI controls and their proof' })]);
        if (!data.access) {
          box.appendChild(el('p', { class: 'aig-note-muted', text: 'You do not have access to AI management assessments, so their controls are not shown.' }));
          host.appendChild(box);
          return;
        }
        if (!data.items.length) {
          box.appendChild(el('p', { class: 'aig-note-muted', text: 'No AI controls are recorded for this use. They appear when an AI management assessment lists them.' }));
          host.appendChild(box);
          return;
        }
        box.appendChild(el('p', { class: 'aig-hint', text: 'Applicable, implemented and proof are separate facts. A file attached to a control is not an accepted test.' }));
        var table = el('table', { class: 'aig-table' }, [el('thead', {}, [el('tr', {}, ['Control', 'Applicable', 'Implemented', 'Mapped to', 'Proof', ''].map(function (h) { return el('th', { scope: 'col', text: h }); }))])]);
        var body = el('tbody', {});
        data.items.forEach(function (item) {
          var proof = item.proof;
          var proofText = !item.mapped ? 'Cannot show: not mapped'
            : (proof.current + ' current' + (proof.verified ? ', ' + proof.verified + ' verified' : '') + (proof.expired ? ', ' + proof.expired + ' expired' : ''));
          var mapped = item.mapped_to.length ? el('ul', {}, item.mapped_to.map(function (m) { return el('li', {}, [(m.ref ? m.ref + ' ' : '') + m.title]); })) : el('span', { class: 'aig-muted', text: 'Not mapped' });
          body.appendChild(el('tr', {}, [
            el('td', {}, [el('strong', { text: (item.control.ref ? item.control.ref + ' ' : '') + item.control.title }), el('div', { class: 'aig-hint', text: item.assessment.ref + ': ' + item.assessment.title })]),
            el('td', { text: item.applicable ? 'Yes' : 'No' }), el('td', { text: item.implemented ? 'Yes' : 'No' }), el('td', {}, [mapped]),
            el('td', {}, [el('span', { text: proofText })].concat(proof.items.slice(0, 3).map(function (p) {
              return el('div', {}, [el('a', { href: p.url, text: p.title }), ' ', AIGov.chip(p.expired ? 'Expired' : 'Current', p.expired ? 'warn' : 'good')]);
            }))),
            el('td', {}, system.can.review ? [el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Map', 'aria-label': 'Map ' + item.control.title + ' to a canonical control',
              on: { click: function () { mapDialog(item, function () { open('risks_controls'); }); } } })] : [])]));
        });
        table.appendChild(body);
        box.appendChild(el('div', { class: 'aig-tablewrap' }, [table]));
        host.appendChild(box);
      }).catch(function (err) { host.appendChild(el('p', { class: 'aig-note-warn', text: 'The AI controls could not be loaded: ' + AIGov.errorText(err) })); });
    }

    function mapDialog(item, done) {
      AIGov.dialog('Map "' + item.control.title + '" to a canonical control', function (box, close) {
        var search = el('input', { type: 'search', autocomplete: 'off' });
        var results = el('div', { class: 'aig-results' });
        var out = el('div', { class: 'aig-say' });
        box.appendChild(el('p', { class: 'aig-muted', text: 'Proof held for the canonical control then shows against this AI control. Nothing is mapped until you choose.' }));
        box.appendChild(AIGov.field('aigMapSearch', 'Find a canonical control', search, 'Type at least two letters. Suggestions are listed first.').row);
        box.appendChild(results);
        box.appendChild(out);
        function show(list, note) {
          AIGov.clear(results);
          if (note) results.appendChild(el('p', { class: 'aig-hint', text: note }));
          if (!list.length) { results.appendChild(el('p', { class: 'aig-muted', text: 'No canonical control matches.' })); return; }
          list.forEach(function (c) {
            results.appendChild(el('div', { class: 'aig-result-row' }, [el('span', { text: (c.ref ? c.ref + ' ' : '') + c.title + (c.reason ? ' (' + c.reason + ')' : '') }),
              el('button', { type: 'button', class: 'btn btn-primary btn-sm', text: 'Map', 'aria-label': 'Map to ' + c.title, on: { click: function () {
                AIGov.say(out, 'Saving...');
                AIGov.api('/ai-governance/api/control-mappings', 'PUT', { ai_control_id: item.control.id, canonical_control_id: c.id })
                  .then(function () { close(); done(); }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
              } } })]));
          });
        }
        AIGov.api('/ai-governance/api/controls/' + item.control.id + '/suggestions').then(function (d) { show(d.items, 'Suggested from the titles:'); })
          .catch(function () { show([], ''); });
        search.addEventListener('input', AIGov.debounce(function () {
          if (search.value.trim().length < 2) return;
          AIGov.api('/ai-governance/api/canonical-controls' + AIGov.qs({ q: search.value.trim() })).then(function (d) { show(d.items, ''); })
            .catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
        }, 250));
        if (item.mapped_to.length) {
          box.appendChild(el('div', { class: 'aig-actions' }, item.mapped_to.map(function (m) {
            return el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Remove the mapping to ' + m.title, on: { click: function () {
              AIGov.api('/ai-governance/api/control-mappings' + AIGov.qs({ ai_control_id: item.control.id, canonical_control_id: m.id }), 'DELETE')
                .then(function () { close(); done(); }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
            } } });
          })));
        }
      });
    }

    // ── Start ───────────────────────────────────────────────────────────────

    AIGov.say(status, 'Loading...');
    Promise.all([refresh(), AIGov.api('/ai-governance/api/link-kinds')]).then(function (parts) {
      kinds = parts[1].items;
      if (current === 'review_desk' && !system.can.review) current = 'overview';
      open(current);
      // Links from other panels point at a tab of this page by its hash.
      global.addEventListener('hashchange', function () {
        var tab = (global.location.hash || '#overview').slice(1);
        if (tab !== current && tabOrder().indexOf(tab) >= 0) open(tab);
      });
    }).catch(function (err) { AIGov.say(status, AIGov.errorText(err), 'bad'); });
  };
}(window));
