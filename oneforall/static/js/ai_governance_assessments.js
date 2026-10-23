/* AI Governance: the AI impact assessment list and form (moved here from Sentinel, plans/ai-governance/06).
   Pages build their DOM from text nodes only: nothing that comes from the server is ever parsed as markup.
   Needs ai_governance_common.js and api_client.js. */
(function (global) {
  'use strict';

  var AIGov = global.AIGov, el = AIGov.el;

  var STATUS_LABEL = { draft: 'Draft', in_progress: 'In progress', completed: 'Completed', approved: 'Approved' };
  var STATUS_KIND = { draft: 'muted', in_progress: 'info', completed: 'good', approved: 'good' };
  var AUTONOMY = { decision_support: 'Decision support', human_in_loop: 'Human in the loop', automated: 'Automated' };
  var ENVIRONMENT = { on_prem: 'On premises', cloud: 'Cloud', hybrid: 'Hybrid' };
  var RESIDUAL = { very_low: 'Very low', low: 'Low', moderate: 'Moderate', high: 'High', critical: 'Critical' };
  var DATA_CATEGORIES = ['Personal', 'Transactional', 'Operational', 'Behavioural'];
  var BAND_KIND = { very_low: 'good', low: 'good', moderate: 'warn', medium: 'warn', high: 'bad', critical: 'bad' };
  var STATUS_ORDER = ['draft', 'in_progress', 'completed', 'approved'];

  function statusChip(status) { return AIGov.chip(STATUS_LABEL[status] || status, STATUS_KIND[status]); }

  function documentLink(row, kind, text) {
    return el('a', { class: kind, href: '/ai-governance/api/assessments/' + row.id + '/document', download: true, text: text,
      'aria-label': text + ' of ' + (row.ref_number || 'this assessment') });
  }

  function classChip(value) {
    if (!value) return AIGov.chip('Not scored', 'muted');
    if (value === 'unrated') return AIGov.chip('Unrated: no active rating framework', 'muted');
    var label = String(value).replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
    return AIGov.chip(label, BAND_KIND[String(value).toLowerCase()] || 'info');
  }

  function table(headers, rows) {
    var head = el('tr', {}, headers.map(function (h) { return el('th', { scope: 'col', text: h }); }));
    return el('table', { class: 'aig-table' }, [el('thead', {}, [head]), el('tbody', {}, rows)]);
  }

  // ── Pickers shared by the list and the form ──────────────────────────────

  /* Choose an AI system the person may open, found by typing. `done(system)` gets {id, name}. */
  function chooseSystem(done) {
    AIGov.dialog('Choose an AI system', function (box, close) {
      var search = el('input', { type: 'search', autocomplete: 'off' });
      var results = el('div', { class: 'aig-results' });
      var out = el('div', { class: 'aig-say', role: 'status' });
      box.appendChild(AIGov.field('aigSystemSearch', 'Find an AI system', search, 'Type part of its name. Leave empty to list the first few.').row);
      box.appendChild(results);
      box.appendChild(out);
      var ticket = 0;
      function find() {
        var mine = ++ticket;
        AIGov.api('/ai-governance/api/systems' + AIGov.qs({ q: search.value.trim(), state: 'all', page_size: 10 })).then(function (data) {
          if (mine !== ticket) return;
          AIGov.clear(results);
          if (!data.items.length) { results.appendChild(el('p', { class: 'aig-muted', text: 'No AI system you can open matches.' })); return; }
          data.items.forEach(function (system) {
            results.appendChild(el('div', { class: 'aig-result-row' }, [el('span', { text: system.name }),
              el('button', { type: 'button', class: 'btn btn-primary btn-sm', text: 'Choose', 'aria-label': 'Choose ' + system.name,
                on: { click: function () { close(); done({ id: system.id, name: system.name }); } } })]));
          });
        }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
      }
      search.addEventListener('input', AIGov.debounce(find, 250));
      box.appendChild(el('div', { class: 'aig-actions' }, [el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
      find();
    });
  }

  /* Choose a RoPA or a DPIA the writer may open. `done(record)` gets {id, ref, title}. */
  function chooseRecord(kind, done) {
    var noun = kind === 'ropa' ? 'RoPA' : 'DPIA';
    AIGov.dialog('Choose a ' + noun, function (box, close) {
      var search = el('input', { type: 'search', autocomplete: 'off' });
      var results = el('div', { class: 'aig-results' });
      var out = el('div', { class: 'aig-say', role: 'status' });
      box.appendChild(AIGov.field('aigRecordSearch', 'Find a ' + noun, search, 'Type part of its reference or name.').row);
      box.appendChild(results);
      box.appendChild(out);
      var ticket = 0;
      function find() {
        var mine = ++ticket;
        AIGov.api('/ai-governance/api/assessments/link-options' + AIGov.qs({ kind: kind, q: search.value.trim() })).then(function (data) {
          if (mine !== ticket) return;
          AIGov.clear(results);
          if (!data.items.length) { results.appendChild(el('p', { class: 'aig-muted', text: 'No ' + noun + ' you can open matches.' })); return; }
          data.items.forEach(function (record) {
            var label = (record.ref ? record.ref + ' ' : '') + record.title;
            results.appendChild(el('div', { class: 'aig-result-row' }, [el('span', { text: label }),
              el('button', { type: 'button', class: 'btn btn-primary btn-sm', text: 'Choose', 'aria-label': 'Choose ' + label,
                on: { click: function () { close(); done(record); } } })]));
          });
        }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
      }
      search.addEventListener('input', AIGov.debounce(find, 250));
      box.appendChild(el('div', { class: 'aig-actions' }, [el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
      find();
    });
  }

  // ── Impact dimensions ────────────────────────────────────────────────────

  function openDimensions(onSaved) {
    AIGov.dialog('Impact dimensions', function (box, close) {
      var rows = el('div', { class: 'aig-dim-rows' });
      var out = el('div', { class: 'aig-say', role: 'status' });
      var counter = 0;
      function addRow(dim) {
        var n = ++counter;
        var name = el('input', { type: 'text', maxlength: '100', value: dim.name || '' });
        var active = el('input', { type: 'checkbox', checked: dim.is_active !== false });
        var wrap = el('div', { class: 'aig-dim-row', 'data-id': dim.id || '' }, [
          AIGov.field('aigDimName' + n, 'Dimension name', name).row,
          el('label', { class: 'aig-check' }, [active, 'Offered on new assessments'])]);
        wrap.getValue = function () { return { id: dim.id || null, name: name.value.trim(), is_active: active.checked }; };
        rows.appendChild(wrap);
      }
      box.appendChild(el('p', { class: 'aig-muted', text: 'Rename a dimension and its scored history follows it. Untick "Offered" to stop offering it on new assessments without losing past scores.' }));
      box.appendChild(rows);
      box.appendChild(out);
      AIGov.api('/ai-governance/api/assessment-dimensions').then(function (data) { data.items.forEach(addRow); })
        .catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
      box.appendChild(el('div', { class: 'aig-actions' }, [
        el('button', { type: 'button', class: 'btn btn-secondary', text: 'Add a dimension', on: { click: function () { addRow({}); } } }),
        el('button', { type: 'button', class: 'btn btn-primary', text: 'Save dimensions', on: { click: function () {
          var dims = [];
          [].forEach.call(rows.children, function (row, index) {
            var value = row.getValue();
            if (!value.name) return;
            value.order_idx = index + 1;
            dims.push(value);
          });
          AIGov.say(out, 'Saving...');
          AIGov.api('/ai-governance/api/assessment-dimensions', 'PUT', { dimensions: dims }).then(function () {
            close();
            if (onSaved) onSaved();
          }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
        } } }),
        el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
    });
  }

  // ── The list ─────────────────────────────────────────────────────────────

  AIGov.assessmentList = function (root, config) {
    config = config || {};
    var params = new URLSearchParams(global.location.search);
    var current = { q: params.get('q') || '', status: params.get('status') || '', linked: params.get('linked') || '',
      page: parseInt(params.get('page') || '1', 10) || 1 };
    var filterBar = el('form', { class: 'aig-filters', role: 'search', 'aria-label': 'Filter AI impact assessments' });
    var say = el('div', { class: 'aig-say', role: 'status' });
    var tableWrap = el('div', { class: 'aig-tablewrap' });
    var pagerBox = el('div', { class: 'aig-pager' });
    [filterBar, say, tableWrap, pagerBox].forEach(function (node) { root.appendChild(node); });
    filterBar.addEventListener('submit', function (event) { event.preventDefault(); });
    var controls = {};
    var counter = 0;

    function syncUrl() {
      var query = {};
      ['q', 'status', 'linked'].forEach(function (key) { if (current[key]) query[key] = current[key]; });
      if (current.page > 1) query.page = current.page;
      global.history.replaceState(null, '', global.location.pathname + AIGov.qs(query));
    }

    function load() {
      var ticket = ++counter;
      syncUrl();
      tableWrap.setAttribute('aria-busy', 'true');
      AIGov.say(say, 'Loading...');
      return AIGov.api('/ai-governance/api/assessments' + AIGov.qs({ q: current.q, status: current.status, linked: current.linked, page: current.page }))
        .then(function (data) {
          if (ticket !== counter) return;
          tableWrap.removeAttribute('aria-busy');
          AIGov.say(say, '');
          render(data);
        }).catch(function (err) {
          if (ticket !== counter) return;
          tableWrap.removeAttribute('aria-busy');
          AIGov.clear(tableWrap);
          AIGov.say(say, AIGov.errorText(err), 'bad');
        });
    }

    function filtersActive() { return !!(current.q || current.status || current.linked); }

    function linkDialog(row) {
      chooseSystem(function (system) {
        AIGov.say(say, 'Linking...');
        AIGov.api('/ai-governance/api/assessments/' + row.id, 'PUT', { application_id: system.id, version: row.version })
          .then(function () { return load(); })
          .then(function () { AIGov.say(say, 'Linked to ' + system.name + '.', 'good'); })
          .catch(function (err) { AIGov.say(say, AIGov.errorText(err), 'bad'); });
      });
    }

    function systemCell(row, canManage) {
      var app = row.application;
      if (app && app.restricted) return el('td', { class: 'aig-muted', text: 'A system you cannot open' });
      if (app) return el('td', {}, [el('a', { href: app.url, text: app.name })]);
      var kids = [el('span', { class: 'aig-muted', text: 'Not linked' })];
      if (canManage) kids.push(' ', el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Link to a system',
        'aria-label': 'Link ' + row.ref_number + ' to an AI system', on: { click: function () { linkDialog(row); } } }));
      return el('td', {}, kids);
    }

    function render(data) {
      AIGov.clear(tableWrap);
      AIGov.pager(pagerBox, data.page, data.pages, data.total, data.page_size, function (page) { current.page = page; load(); });
      if (!data.items.length) {
        var box = el('div', { class: 'aig-empty' });
        if (filtersActive()) {
          box.appendChild(el('p', { text: 'No assessments match these filters.' }));
          box.appendChild(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Clear filters', on: { click: function () {
            current.q = current.status = current.linked = ''; current.page = 1;
            controls.q.value = ''; controls.status.value = ''; controls.linked.value = '';
            load();
          } } }));
        } else {
          box.appendChild(el('p', { text: 'No AI impact assessments have been recorded yet.' }));
          if (data.can.manage) box.appendChild(el('a', { class: 'btn btn-primary btn-sm', href: '/ai-governance/assessments/new', text: 'New assessment' }));
        }
        tableWrap.appendChild(box);
        return;
      }
      var rows = data.items.map(function (row) {
        return el('tr', {}, [
          el('td', {}, [el('span', { class: 'aig-ref', text: row.ref_number })]),
          el('td', {}, [el('a', { href: row.url, text: row.title })]),
          systemCell(row, data.can.manage),
          el('td', { text: AUTONOMY[row.autonomy_level] || row.autonomy_level || 'Not recorded' }),
          el('td', {}, [classChip(row.overall_classification)]),
          el('td', {}, [statusChip(row.status)]),
          el('td', { text: row.business_unit || 'Whole organization' }),
          el('td', { text: AIGov.date(row.updated_at) }),
          el('td', {}, [documentLink(row, 'btn btn-ghost btn-sm', 'PDF')])]);
      });
      tableWrap.appendChild(table(['Reference', 'Title', 'AI system', 'Autonomy', 'Classification', 'Status', 'Business unit', 'Updated', 'Document'], rows));
    }

    var search = el('input', { type: 'search', value: current.q, autocomplete: 'off' });
    search.addEventListener('input', AIGov.debounce(function () { current.q = search.value.trim(); current.page = 1; load(); }, 300));
    controls.q = search;
    filterBar.appendChild(AIGov.field('aigf_q', 'Search title, system or reference', search).row);

    var statusSelect = AIGov.select(STATUS_ORDER.map(function (s) { return { id: s, name: STATUS_LABEL[s] }; }), current.status, 'All');
    statusSelect.addEventListener('change', function () { current.status = statusSelect.value; current.page = 1; load(); });
    controls.status = statusSelect;
    filterBar.appendChild(AIGov.field('aigf_status', 'Status', statusSelect).row);

    var linkedSelect = AIGov.select([{ id: 'any', name: 'Linked to an AI system' }, { id: 'none', name: 'Not linked to an AI system' }], current.linked, 'All');
    linkedSelect.addEventListener('change', function () { current.linked = linkedSelect.value; current.page = 1; load(); });
    controls.linked = linkedSelect;
    filterBar.appendChild(AIGov.field('aigf_linked', 'AI system', linkedSelect).row);

    if (config.dimensionsButton) config.dimensionsButton.addEventListener('click', function () { openDimensions(load); });
    load();
  };

  // ── The form ─────────────────────────────────────────────────────────────

  AIGov.assessmentForm = function (root, config) {
    var id = config.assessmentId || 0;
    var startApp = config.applicationId || 0;
    var header = document.getElementById('aigAssessmentHeader');
    var titleNode = document.getElementById('aigAssessmentTitle');
    var say = el('div', { class: 'aig-say', role: 'status' });
    var summary = el('div', { class: 'aig-errorsummary', role: 'alert', tabindex: '-1', hidden: true });
    // Hidden until the dimensions, the unit choices and any record or profile it starts from have arrived, so nothing
    // typed before then can be overwritten by what loads.
    var form = el('form', { class: 'aig-form aig-assessment-form', novalidate: 'novalidate', hidden: true });
    form.addEventListener('submit', function (event) { event.preventDefault(); });
    [say, summary, form].forEach(function (node) { root.appendChild(node); });

    var fields = {};      // key -> {get, input}
    var impactRows = [];  // [{name, applicable, notes, likelihood, impact, active}]
    var state = { version: null, can: { manage: true }, application: null, ropa: null, dpia: null, units: [], restricted: {} };

    function listField(key, label, control, hint) {
      return AIGov.field('as_' + key, label, control, hint).row;
    }

    function text(key, label, opts) {
      opts = opts || {};
      var input = el(opts.multiline ? 'textarea' : 'input', opts.multiline ? { rows: opts.rows || '3', maxlength: String(opts.max || 4000) } : { type: 'text', maxlength: String(opts.max || 200) });
      fields[key] = { input: input, get: function () { var v = input.value.trim(); return v === '' ? null : v; }, set: function (v) { input.value = v == null ? '' : v; } };
      return listField(key, label, input, opts.hint);
    }

    function choice(key, label, map, placeholder) {
      var select = AIGov.select(Object.keys(map).map(function (k) { return { id: k, name: map[k] }; }), '', placeholder);
      fields[key] = { input: select, get: function () { return select.value || null; }, set: function (v) { select.value = v || ''; } };
      return listField(key, label, select);
    }

    function yesNo(key, label) {
      var box = el('input', { type: 'checkbox' });
      fields[key] = { input: box, get: function () { return box.checked ? 1 : 0; }, set: function (v) { box.checked = !!v; } };
      box.id = 'as_' + key;
      return el('div', { class: 'aig-field' }, [el('label', { class: 'aig-check', for: 'as_' + key }, [box, label])]);
    }

    function chips(key, label, values) {
      var group = el('fieldset', { class: 'aig-fieldset', id: 'as_' + key }, [el('legend', { text: label })]);
      var boxes = {};
      values.forEach(function (v) {
        var box = el('input', { type: 'checkbox', value: v });
        boxes[v] = box;
        group.appendChild(el('label', { class: 'aig-check' }, [box, v]));
      });
      fields[key] = { input: group, get: function () { return values.filter(function (v) { return boxes[v].checked; }); },
        set: function (list) { values.forEach(function (v) { boxes[v].checked = (list || []).indexOf(v) >= 0; }); } };
      return group;
    }

    // A reference chosen in a dialog: shows what is chosen and offers Change and Clear.
    function reference(key, label, choose, hint) {
      var shown = el('span', { class: 'aig-chosen' });
      var holder = el('div', { class: 'aig-field' }, [el('span', { class: 'aig-label', id: 'as_' + key + '_label', text: label }), shown]);
      var change = el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Choose', 'aria-describedby': 'as_' + key + '_label' });
      var clear = el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Clear', 'aria-label': 'Clear ' + label });
      var value = null;
      function paint() {
        AIGov.clear(shown);
        var restricted = state.restricted[key];
        if (restricted) shown.appendChild(document.createTextNode('A record you cannot open is linked. It stays as it is.'));
        else if (value) shown.appendChild(value.url ? el('a', { href: value.url, text: value.label }) : document.createTextNode(value.label));
        else shown.appendChild(document.createTextNode('None'));
        change.textContent = value ? 'Change' : 'Choose';
        clear.hidden = !value || restricted;
        change.hidden = !!restricted;
        change.disabled = clear.disabled = !state.can.manage;
      }
      change.addEventListener('click', function () { choose(function (picked) { value = picked; paint(); }); });
      clear.addEventListener('click', function () { value = null; paint(); });
      holder.appendChild(el('div', { class: 'aig-actions' }, [change, clear]));
      if (hint) holder.appendChild(el('div', { class: 'aig-hint', text: hint }));
      fields[key] = { input: holder,
        get: function () { return state.restricted[key] ? undefined : (value ? value.id : null); },
        set: function (v) { value = v; paint(); }, paint: paint };
      return holder;
    }

    // ── The four sections ────────────────────────────────────────────────

    function section(title, kids) {
      var h = el('h2', { class: 'aig-h3', text: title });
      return el('section', { class: 'aig-panel', 'aria-label': title }, [h].concat(kids));
    }

    var thirdPartyDetails = text('third_party_details', 'Third-party details', { multiline: true, rows: '2', max: 2000, hint: 'The vendor, the model and the interface used.' });
    var basics = section('Basics', [
      text('title', 'Title', { hint: 'For example: Customer churn prediction model.' }),
      text('ai_system_name', 'AI system name'),
      reference('application_id', 'AI system in the inventory', function (done) {
        chooseSystem(function (system) { done({ id: system.id, label: system.name, url: '/ai-governance/systems/' + system.id }); });
      }, 'Choose the system this assessment is about. It then shows on that system\'s Assessments tab.'),
      text('department', 'Department'),
      text('owner', 'Owner'),
      text('system_description', 'System description', { multiline: true }),
      text('business_process', 'Business process supported', { max: 500 }),
      choice('deployment_env', 'Deployment environment', ENVIRONMENT, 'Not recorded'),
      choice('autonomy_level', 'Autonomy level', AUTONOMY),
      yesNo('third_party', 'Uses third-party AI components'),
      thirdPartyDetails,
      text('outputs_decisions', 'Outputs and decisions generated', { multiline: true, rows: '2', max: 2000 }),
      yesNo('influences_customers', 'Influences customer or financial decisions')]);

    var impactGrid = el('div', { class: 'aig-impact-grid', id: 'as_impacts' });
    var impacts = section('Impacts', [
      chips('data_categories', 'Data categories processed', DATA_CATEGORIES),
      yesNo('sensitive_data', 'Involves sensitive data'),
      text('stakeholders_direct', 'Direct stakeholders', { multiline: true, rows: '2', max: 2000 }),
      text('stakeholders_indirect', 'Indirect stakeholders', { multiline: true, rows: '2', max: 2000 }),
      el('p', { class: 'aig-hint', text: 'Score each dimension for likelihood and impact from 1 (very low) to 5 (very high). Untick a dimension to leave it out of the classification without losing its notes. The classification uses the same rating framework as the risk register.' }),
      impactGrid]);

    var classBox = el('div', { class: 'aig-classification' });
    var mitigation = section('Mitigation', [
      text('mitigation_measures', 'Required mitigation measures', { multiline: true, rows: '5', hint: 'The controls that reduce the risks identified above.' }),
      choice('residual_classification', 'Residual classification after mitigation', RESIDUAL, 'Not assessed'),
      classBox]);

    var unitSelect = AIGov.select([], '', 'The AI system\'s unit, or mine');
    fields.business_unit_id = { input: unitSelect, get: function () { return unitSelect.value ? parseInt(unitSelect.value, 10) : undefined; },
      set: function (v) { if (v != null) unitSelect.value = String(v); } };
    var review = section('Review', [
      choice('status', 'Status', { draft: 'Draft', in_progress: 'In progress', completed: 'Completed', approved: 'Approved' }),
      reference('ropa_id', 'Linked RoPA', function (done) {
        chooseRecord('ropa', function (r) { done({ id: r.id, label: (r.ref ? r.ref + ' ' : '') + r.title, url: '/sentinel/?open=ropa:' + r.id }); });
      }),
      reference('dpia_id', 'Linked DPIA', function (done) {
        chooseRecord('dpia', function (r) { done({ id: r.id, label: (r.ref ? r.ref + ' ' : '') + r.title, url: '/sentinel/?open=dpia:' + r.id }); });
      }),
      AIGov.field('as_business_unit_id', 'Business unit', unitSelect, 'Leave as it is to file the assessment under the AI system\'s unit, or yours.').row]);

    var profileHost = el('div', { class: 'aig-panel', id: 'as_assurance_details' });
    var profileDefinition = null;

    var actions = el('div', { class: 'aig-actions' });
    var saveBtn = el('button', { type: 'button', class: 'btn btn-primary', text: id ? 'Save changes' : 'Create assessment' });
    actions.appendChild(saveBtn);
    var deleteBtn = el('button', { type: 'button', class: 'btn btn-ghost', text: 'Delete this assessment', hidden: !id });
    actions.appendChild(deleteBtn);
    [basics, impacts, mitigation, review, profileHost, actions].forEach(function (node) { form.appendChild(node); });

    // ── Impact rows ──────────────────────────────────────────────────────

    function scoreSelect(idValue, label, current) {
      var select = el('select', {});
      select.appendChild(el('option', { value: '', text: 'Not scored' }));
      [1, 2, 3, 4, 5].forEach(function (n) {
        select.appendChild(el('option', { value: String(n), text: String(n), selected: current === n ? true : null }));
      });
      return { select: select, row: AIGov.field(idValue, label, select).row };
    }

    function renderImpacts(rows) {
      AIGov.clear(impactGrid);
      impactRows = rows.map(function (row, index) {
        var applicable = el('input', { type: 'checkbox', checked: row.applicable !== false });
        var notes = el('input', { type: 'text', maxlength: '1000', value: row.description || '' });
        var likelihood = scoreSelect('as_imp' + index + '_l', 'Likelihood (1 to 5)', row.likelihood);
        var impact = scoreSelect('as_imp' + index + '_i', 'Impact (1 to 5)', row.impact);
        var legend = row.dimension_name + (row.active === false ? ' (no longer offered)' : '');
        impactGrid.appendChild(el('fieldset', { class: 'aig-fieldset aig-impact' }, [
          el('legend', { text: legend }),
          el('label', { class: 'aig-check' }, [applicable, 'Counts toward the classification']),
          el('div', { class: 'aig-impact-fields' }, [AIGov.field('as_imp' + index + '_n', 'Notes', notes).row, likelihood.row, impact.row])]));
        return { name: row.dimension_name, applicable: applicable, notes: notes, likelihood: likelihood.select, impact: impact.select };
      });
    }

    function impactPayload() {
      return impactRows.map(function (r) {
        return { dimension_name: r.name, applicable: r.applicable.checked ? 1 : 0, description: r.notes.value.trim() || null,
          likelihood: r.likelihood.value ? parseInt(r.likelihood.value, 10) : null, impact: r.impact.value ? parseInt(r.impact.value, 10) : null };
      });
    }

    // ── Loading and showing ──────────────────────────────────────────────

    function paintHeader(a) {
      AIGov.clear(header);
      if (!a) return;
      header.appendChild(el('div', { class: 'aig-chips' }, [
        el('span', { class: 'aig-ref', text: a.ref_number }), ' ', statusChip(a.status), ' ', classChip(a.overall_classification)]));
      var system = a.application;
      var line = [];
      if (system && system.restricted) line.push('AI system: one you cannot open.');
      else if (system) line.push('AI system: ', el('a', { href: system.url, text: system.name }));
      else line.push('Not linked to an AI system.');
      if (a.business_unit) line.push(' Business unit: ' + a.business_unit + '.');
      header.appendChild(el('p', { class: 'aig-muted' }, line));
      header.appendChild(el('p', {}, [documentLink(a, 'btn btn-secondary btn-sm', 'Download PDF')]));
      if (a.title) titleNode.textContent = a.title;
    }

    function paintClassification(a) {
      AIGov.clear(classBox);
      classBox.appendChild(el('p', { class: 'aig-hint', text: 'Overall classification, computed when you save:' }));
      classBox.appendChild(a ? classChip(a.overall_classification) : classChip(null));
    }

    function apply(a, prefill) {
      state.version = a ? a.version : null;
      state.can = a ? a.can : state.can;
      Object.keys(fields).forEach(function (key) {
        if (!fields[key].set) return;
        if (key === 'application_id') {
          state.restricted[key] = !!(a && a.application && a.application.restricted);
          fields[key].set(a && a.application && !a.application.restricted ? { id: a.application.id, label: a.application.name, url: a.application.url } : null);
          return;
        }
        if (key === 'ropa_id' || key === 'dpia_id') {
          var rec = a && a[key === 'ropa_id' ? 'ropa' : 'dpia'];
          state.restricted[key] = !!(rec && rec.restricted);
          fields[key].set(rec && !rec.restricted ? { id: rec.id, label: (rec.ref ? rec.ref + ' ' : '') + rec.title, url: rec.url } : null);
          return;
        }
        if (key === 'business_unit_id') { fields[key].set(a ? a.business_unit_id : null); return; }
        var source = a || prefill || {};
        fields[key].set(source[key] !== undefined ? source[key] : (key === 'autonomy_level' ? 'decision_support' : (key === 'status' ? 'draft' : null)));
      });
      thirdPartyVisibility();
      paintHeader(a);
      paintClassification(a);
    }

    function thirdPartyVisibility() {
      var on = fields.third_party.input.checked;
      thirdPartyDetails.hidden = !on;
    }
    fields.third_party.input.addEventListener('change', thirdPartyVisibility);

    function setReadOnly() {
      [].forEach.call(form.querySelectorAll('input, select, textarea'), function (control) { control.disabled = true; });
      saveBtn.hidden = true;
      deleteBtn.hidden = true;
      form.insertBefore(el('p', { class: 'aig-banner aig-banner-info', text: 'You can read this assessment but not change it.' }), form.firstChild);
    }

    // ── Saving ───────────────────────────────────────────────────────────

    function body() {
      var out = {};
      Object.keys(fields).forEach(function (key) {
        if (!fields[key].get) return;
        var value = fields[key].get();
        if (value !== undefined) out[key] = value;
      });
      out.impacts = impactPayload();
      Object.assign(out, RecordProfileFields.values(profileHost));
      if (id) out.version = state.version;
      return out;
    }

    function showErrors(err) {
      var fe = AIGov.fieldErrors(err);
      AIGov.clear(summary);
      if (fe) {
        summary.hidden = false;
        summary.appendChild(el('p', { text: 'Some answers need fixing.' }));
        summary.appendChild(el('ul', {}, Object.keys(fe).map(function (k) { return el('li', { text: fe[k] }); })));
        summary.focus();
        AIGov.say(say, '');
      } else {
        summary.hidden = true;
        var stale = err && err.body && err.body.current_version != null;
        AIGov.say(say, AIGov.errorText(err) + (stale ? ' Reload the page to see their version.' : ''), 'bad');
      }
    }

    saveBtn.addEventListener('click', function () {
      summary.hidden = true;
      saveBtn.disabled = true;
      AIGov.say(say, 'Saving...');
      var payload;
      try { payload = body(); }
      catch (err) { AIGov.say(say, err.message, 'bad'); saveBtn.disabled = false; return; }
      var request = id
        ? AIGov.api('/ai-governance/api/assessments/' + id, 'PUT', payload)
        : AIGov.api('/ai-governance/api/assessments', 'POST', payload);
      request.then(function (data) {
        var a = data.assessment;
        var created = !id;
        id = a.id;
        renderImpacts(a.impacts);
        apply(a);
        RecordProfileFields.mount(profileHost, profileDefinition, a);
        saveBtn.textContent = 'Save changes';
        deleteBtn.hidden = !a.can.manage;
        if (created) global.history.replaceState(null, '', '/ai-governance/assessments/' + id);
        AIGov.say(say, created ? 'Assessment ' + a.ref_number + ' created.' : 'Saved.', 'good');
      }).catch(showErrors).then(function () { saveBtn.disabled = false; });
    });

    deleteBtn.addEventListener('click', function () {
      AIGov.dialog('Delete this assessment?', function (box, close) {
        var out = el('div', { class: 'aig-say', role: 'status' });
        box.appendChild(el('p', { text: 'The assessment and its impact scores are removed. This cannot be undone.' }));
        box.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: 'Delete', on: { click: function () {
            AIGov.api('/ai-governance/api/assessments/' + id, 'DELETE').then(function () {
              global.location.assign('/ai-governance/assessments');
            }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
          } } }),
          el('button', { type: 'button', class: 'btn btn-ghost', text: 'Keep it', on: { click: close } })]));
        box.appendChild(out);
      });
    });

    // ── Start ────────────────────────────────────────────────────────────

    AIGov.say(say, 'Loading...');
    var calls = [
      AIGov.api('/ai-governance/api/assessment-dimensions'),
      AIGov.api('/ai-governance/api/business-units').catch(function () { return { items: [] }; }),
      id ? AIGov.api('/ai-governance/api/assessments/' + id) : Promise.resolve(null),
      !id && startApp ? AIGov.api('/ai-governance/api/systems/' + startApp + '/aiia-prefill').catch(function () { return null; }) : Promise.resolve(null),
      AIGov.api('/ai-governance/api/assessment-profile')];
    Promise.all(calls).then(function (parts) {
      var dims = parts[0].items, units = parts[1].items, loaded = parts[2], prefilled = parts[3];
      profileDefinition = parts[4];
      units.forEach(function (u) { unitSelect.appendChild(el('option', { value: String(u.id), text: u.name })); });
      AIGov.say(say, '');
      form.hidden = false;
      if (loaded) {
        var a = loaded.assessment;
        renderImpacts(a.impacts);
        apply(a);
        RecordProfileFields.mount(profileHost, profileDefinition, a);
        if (!a.can.manage) setReadOnly();
        return;
      }
      renderImpacts(dims.filter(function (d) { return d.is_active; }).map(function (d) {
        return { dimension_name: d.name, applicable: true, description: '', likelihood: null, impact: null, active: true };
      }));
      var start = {};
      if (prefilled && prefilled.fields) {
        Object.keys(prefilled.fields).forEach(function (k) { start[k] = prefilled.fields[k]; });
      }
      apply(null, start);
      RecordProfileFields.mount(profileHost, profileDefinition, start);
      if (prefilled && prefilled.fields && prefilled.fields.application_id) {
        fields.application_id.set({ id: prefilled.fields.application_id, label: prefilled.fields.ai_system_name || 'This AI system',
          url: '/ai-governance/systems/' + prefilled.fields.application_id });
        form.insertBefore(el('p', { class: 'aig-banner aig-banner-info', text:
          'Started from the AI profile of ' + (prefilled.source ? prefilled.source.name : 'this system') + ', last updated ' +
          AIGov.date(prefilled.source && prefilled.source.updated_at) + '. Check each answer: the assessment keeps its own copy and a later change to the profile does not rewrite it.' }), form.firstChild);
      } else if (startApp) {
        fields.application_id.set({ id: startApp, label: 'AI system ' + startApp, url: '/ai-governance/systems/' + startApp });
      }
    }).catch(function (err) { AIGov.say(say, AIGov.errorText(err), 'bad'); });
  };
}(window));
