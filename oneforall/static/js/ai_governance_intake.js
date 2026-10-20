/* AI Governance: describe an AI use. A draft can be saved after any step and resumed later; a returned request opens
   with the reviewer's note. Needs ai_governance_common.js and api_client.js. */
(function (global) {
  'use strict';

  var AIGov = global.AIGov, el = AIGov.el;

  var STEPS = [
    { title: 'About the use', hint: 'The essentials. You can save and come back.' },
    { title: 'A few more questions', hint: 'These sharpen the first screening. Skip what you do not know yet.' },
    { title: 'Check and submit', hint: 'Look it over, see if it is already registered, then send it for review.' },
  ];

  AIGov.intake = function (root, config) {
    var vocab = null, people = {}, units = [];
    var state = { id: config.intakeId || 0, version: null, status: 'draft', step: 0, reviewNote: null, applicationId: null };
    var idempotencyKey = (global.crypto && global.crypto.randomUUID) ? global.crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2);
    var ctl = {};            // question key -> {get(), set(value), node}
    var panels = [];
    var banner = el('div', { class: 'aig-banner', hidden: true });
    var summary = el('div', { class: 'aig-errorsummary', role: 'alert', tabindex: '-1', hidden: true });
    var stepper = el('ol', { class: 'aig-steps', 'aria-label': 'Steps' });
    var form = el('form', { class: 'aig-form', novalidate: 'novalidate' });
    var say = el('div', { class: 'aig-say', role: 'status' });
    var nav = el('div', { class: 'aig-actions' });

    root.appendChild(banner); root.appendChild(stepper); root.appendChild(summary); root.appendChild(form);
    form.appendChild(el('div', { class: 'aig-panels' }));
    root.appendChild(nav); root.appendChild(say);
    form.addEventListener('submit', function (event) { event.preventDefault(); });

    // ── Controls ────────────────────────────────────────────────────────────

    function addText(key, label, opts) {
      opts = opts || {};
      var input = el(opts.multiline ? 'textarea' : 'input', opts.multiline ? { rows: opts.rows || '3', maxlength: String(opts.max || 1000) }
        : { type: opts.type || 'text', maxlength: String(opts.max || 200), autocomplete: 'off' });
      var field = AIGov.field('q_' + key, label + (opts.required ? ' (required)' : ''), input, opts.hint);
      ctl[key] = { node: field.row, input: input, get: function () { return input.value.trim() || null; }, set: function (v) { input.value = v || ''; } };
      return field.row;
    }

    function addSelect(key, label, options, opts) {
      opts = opts || {};
      var select = AIGov.select(options, '', 'Choose');
      var field = AIGov.field('q_' + key, label + (opts.required ? ' (required)' : ''), select, opts.hint);
      ctl[key] = { node: field.row, input: select,
        get: function () { return select.value ? (opts.numeric ? parseInt(select.value, 10) : select.value) : null; },
        set: function (v) { select.value = v === null || v === undefined ? '' : String(v); } };
      return field.row;
    }

    function addChecks(key, label, table, opts) {
      opts = opts || {};
      var group = el('fieldset', { class: 'aig-fieldset', id: 'q_' + key, tabindex: '-1' }, [el('legend', { text: label + (opts.required ? ' (required)' : '') })]);
      if (opts.hint) group.appendChild(el('div', { class: 'aig-hint', text: opts.hint }));
      var boxes = {};
      Object.keys(table).forEach(function (value) {
        var box = el('input', { type: 'checkbox', value: value });
        box.addEventListener('change', function () {
          if (opts.exclusive && box.checked) {
            Object.keys(boxes).forEach(function (other) { if (other !== value && (value === opts.exclusive || other === opts.exclusive)) boxes[other].checked = false; });
          }
          if (opts.onChange) opts.onChange();
        });
        boxes[value] = box;
        group.appendChild(el('label', { class: 'aig-check' }, [box, table[value]]));
      });
      ctl[key] = { node: group, input: group, get: function () {
        return Object.keys(boxes).filter(function (v) { return boxes[v].checked; });
      }, set: function (list) { Object.keys(boxes).forEach(function (v) { boxes[v].checked = (list || []).indexOf(v) >= 0; }); } };
      return group;
    }

    function addYesNo(key, label, hint) {
      var group = el('fieldset', { class: 'aig-fieldset', id: 'q_' + key, tabindex: '-1' }, [el('legend', { text: label })]);
      if (hint) group.appendChild(el('div', { class: 'aig-hint', text: hint }));
      var radios = {};
      [['yes', 'Yes'], ['no', 'No'], ['unknown', 'Not sure']].forEach(function (pair) {
        var radio = el('input', { type: 'radio', name: 'q_' + key, value: pair[0] });
        radios[pair[0]] = radio;
        group.appendChild(el('label', { class: 'aig-check' }, [radio, pair[1]]));
      });
      ctl[key] = { node: group, input: group, get: function () {
        return radios.yes.checked ? true : radios.no.checked ? false : null;
      }, set: function (v) { radios.yes.checked = v === true; radios.no.checked = v === false; radios.unknown.checked = v === null || v === undefined; } };
      return group;
    }

    function addPerson(key, label, opts) {
      opts = opts || {};
      var shown = el('div', { class: 'aig-chosen', id: 'q_' + key + '_shown' });
      var search = el('input', { type: 'search', autocomplete: 'off', 'aria-describedby': 'q_' + key + '_shown' });
      var results = el('div', { class: 'aig-results', role: 'listbox', 'aria-label': label });
      var value = null;
      function show() { shown.textContent = value ? 'Chosen: ' + (people[value] || 'person #' + value) : 'Nobody chosen yet.'; }
      var field = AIGov.field('q_' + key, label + (opts.required ? ' (required)' : ''), search, opts.hint);
      field.row.appendChild(shown); field.row.appendChild(results);
      search.addEventListener('input', AIGov.debounce(function () {
        var text = search.value.trim();
        AIGov.clear(results);
        if (text.length < 2) return;
        AIGov.api('/ai-governance/api/people' + AIGov.qs({ q: text })).then(function (data) {
          AIGov.clear(results);
          if (!data.items.length) results.appendChild(el('p', { class: 'aig-muted', text: 'Nobody with that name.' }));
          data.items.forEach(function (p) {
            people[p.id] = p.name;
            results.appendChild(el('button', { type: 'button', class: 'aig-result', role: 'option', text: p.name, on: { click: function () {
              value = p.id; show(); AIGov.clear(results); search.value = '';
            } } }));
          });
        });
      }, 250));
      ctl[key] = { node: field.row, input: search, get: function () { return value; }, set: function (v) { value = v || null; show(); } };
      show();
      return field.row;
    }

    // ── Questions, by step ──────────────────────────────────────────────────

    function build() {
      var p1 = el('div', { class: 'aig-panel-step' }), p2 = el('div', { class: 'aig-panel-step' }), p3 = el('div', { class: 'aig-panel-step' });
      p1.appendChild(addText('name', 'What is it called?', { required: true, max: 120 }));
      p1.appendChild(addText('purpose', 'What is it for?', { required: true, multiline: true, max: 2000, hint: 'The task it helps with and who benefits.' }));
      p1.appendChild(addSelect('deployment', 'How is it provided?', Object.keys(vocab.deployment).map(function (k) { return { id: k, name: vocab.deployment[k] }; }), { required: true }));
      p1.appendChild(addText('provider_name', 'Provider or product name', { hint: 'Leave empty for something built in-house.' }));
      p1.appendChild(addPerson('owner_user_id', 'Who owns it?', { required: true, hint: 'Type a name. This person answers questions about the use.' }));
      p1.appendChild(addSelect('business_unit_id', 'Which business unit?', units.map(function (u) { return { id: u.id, name: u.name }; }), { numeric: true, hint: 'Only people in this unit and above it can see the request.' }));
      p1.appendChild(addText('intended_users', 'Who will use it?', { required: true, max: 500, hint: 'For example "support agents" or "all staff".' }));
      p1.appendChild(addChecks('data_categories', 'What kinds of data does it use?', vocab.data_categories, { required: true, hint: 'Tick every kind it will see.', onChange: sensitiveNote }));
      var note = el('div', { class: 'aig-banner aig-banner-info', id: 'sensitiveNote', hidden: true,
        text: 'Special-category and health data need extra care. The reviewers will look at this use closely.' });
      p1.appendChild(note);
      p1.appendChild(addText('planned_use', 'How do you plan to use it?', { multiline: true, max: 1000 }));

      p2.appendChild(addSelect('capability_type', 'What does it mainly do?', Object.keys(vocab.capability_type).map(function (k) { return { id: k, name: vocab.capability_type[k] }; })));
      p2.appendChild(addChecks('affected_people', 'Who is affected by what it does?', vocab.affected_people, { exclusive: 'none', onChange: peopleNote }));
      var decisionsRow = addYesNo('affects_decisions', 'Does its output feed decisions with legal or similarly significant effects on those people?',
        'For example hiring, credit, access to a service or a benefit.');
      decisionsRow.id = 'q_affects_decisions_row';
      p2.appendChild(decisionsRow);
      p2.appendChild(addSelect('autonomy', 'How much does it decide on its own?', Object.keys(vocab.autonomy).map(function (k) { return { id: k, name: vocab.autonomy[k] }; })));
      p2.appendChild(addYesNo('external_access', 'Do people outside the organization use it or see what it produces?'));
      p2.appendChild(addChecks('jurisdictions', 'Whose laws may apply?', vocab.jurisdictions, { hint: 'Where the people affected, or the data, are.' }));
      p2.appendChild(addText('human_oversight', 'Who can review, override or stop its output?', { multiline: true, max: 1000 }));
      p2.appendChild(addText('model_changes', 'Do you expect the model or the provider to change?', { max: 500 }));
      p2.appendChild(addText('target_launch', 'When do you plan to start?', { type: 'date', max: 40 }));
      panels = [p1, p2, p3];
      form.firstChild.appendChild(p1); form.firstChild.appendChild(p2); form.firstChild.appendChild(p3);
    }

    function sensitiveNote() {
      var picked = ctl.data_categories.get();
      document.getElementById('sensitiveNote').hidden = !(picked.indexOf('sensitive_personal') >= 0 || picked.indexOf('health') >= 0);
    }
    function peopleNote() {
      var picked = ctl.affected_people.get();
      var row = document.getElementById('q_affects_decisions_row');
      if (row) row.hidden = !picked.length || (picked.length === 1 && picked[0] === 'none');
    }

    // ── State of the form ───────────────────────────────────────────────────

    function answers() {
      var out = {};
      Object.keys(ctl).forEach(function (key) { out[key] = ctl[key].get(); });
      return out;
    }
    function fill(values) {
      Object.keys(ctl).forEach(function (key) { if (key in values) ctl[key].set(values[key]); });
      sensitiveNote(); peopleNote();
    }
    function locked() { return !config.canEdit || ['submitted', 'approved', 'rejected'].indexOf(state.status) >= 0; }

    function showSummary(message, fields) {
      AIGov.clear(summary);
      Object.keys(ctl).forEach(function (key) {
        var input = ctl[key].input;
        input.removeAttribute('aria-invalid');
        var old = ctl[key].node.querySelector('.aig-fielderror');
        if (old) old.remove();
      });
      if (!message) { summary.hidden = true; return; }
      summary.hidden = false;
      summary.appendChild(el('p', { text: message }));
      var keys = fields ? Object.keys(fields) : [];
      if (keys.length) {
        var list = el('ul', {});
        keys.forEach(function (key) {
          var target = ctl[key];
          list.appendChild(el('li', {}, [el('a', { href: '#q_' + key, text: fields[key], on: { click: function (event) {
            event.preventDefault(); var step = stepOf(key); if (step !== null) gotoStep(step); if (target) target.input.focus(); } } })]));
          if (target) {
            target.input.setAttribute('aria-invalid', 'true');
            target.node.appendChild(el('div', { class: 'aig-fielderror', text: fields[key] }));
          }
        });
        summary.appendChild(list);
      }
      summary.focus();
    }
    function stepOf(key) {
      for (var i = 0; i < panels.length - 1; i++) if (panels[i].querySelector('#q_' + key + ', [for="q_' + key + '"], #q_' + key + '_row')) return i;
      return null;
    }

    function renderStepper() {
      AIGov.clear(stepper);
      STEPS.forEach(function (step, index) {
        stepper.appendChild(el('li', { class: 'aig-step' + (index === state.step ? ' is-current' : index < state.step ? ' is-done' : ''),
          'aria-current': index === state.step ? 'step' : null }, [el('button', { type: 'button', text: (index + 1) + '. ' + step.title,
          on: { click: function () { gotoStep(index); } } })]));
      });
    }

    function renderBanner() {
      banner.hidden = true;
      if (state.status === 'returned' && state.reviewNote) {
        banner.hidden = false; banner.className = 'aig-banner aig-banner-warn';
        banner.textContent = 'A reviewer asked for changes: ' + state.reviewNote;
      } else if (state.status === 'submitted') {
        banner.hidden = false; banner.className = 'aig-banner aig-banner-info'; banner.textContent = 'This request is waiting for review. It can no longer be edited.';
      } else if (state.status === 'approved') {
        banner.hidden = false; banner.className = 'aig-banner aig-banner-good';
        AIGov.clear(banner);
        banner.appendChild(document.createTextNode('This request was accepted. '));
        if (state.applicationId && config.canEdit) banner.appendChild(el('a', { href: '/ai-governance/systems/' + state.applicationId, text: 'Open the AI system' }));
      } else if (state.status === 'rejected') {
        banner.hidden = false; banner.className = 'aig-banner aig-banner-bad';
        banner.textContent = 'This request was not accepted' + (state.reviewNote ? ': ' + state.reviewNote : '.');
      }
    }

    function gotoStep(index) {
      state.step = index;
      panels.forEach(function (panel, i) { panel.hidden = i !== index; });
      renderStepper(); renderNav();
      if (index === 2) renderReview();
      var heading = panels[index].querySelector('input, select, textarea');
      if (heading && !locked()) heading.focus();
    }

    function renderNav() {
      AIGov.clear(nav);
      var disabled = locked();
      if (state.step > 0) nav.appendChild(el('button', { type: 'button', class: 'btn btn-ghost', text: 'Back', on: { click: function () { gotoStep(state.step - 1); } } }));
      if (!disabled) nav.appendChild(el('button', { type: 'button', class: 'btn btn-secondary', text: 'Save draft', on: { click: function () { save(null); } } }));
      if (state.step < 2) nav.appendChild(el('button', { type: 'button', class: 'btn btn-primary', text: 'Continue', on: { click: function () {
        if (disabled) gotoStep(state.step + 1); else save(state.step + 1); } } }));
      else if (!disabled) nav.appendChild(el('button', { type: 'button', class: 'btn btn-primary', text: 'Submit for review', on: { click: submit } }));
      Object.keys(ctl).forEach(function (key) { [].forEach.call(ctl[key].node.querySelectorAll('input, select, textarea, button'), function (n) { n.disabled = disabled; }); });
    }

    // ── Talking to the server ───────────────────────────────────────────────

    function adopt(intake) {
      state.id = intake.id; state.version = intake.version; state.status = intake.status;
      state.reviewNote = intake.review_note; state.applicationId = intake.application_id;
      if (config.intakeId !== intake.id) { global.history.replaceState(null, '', '/ai-governance/requests/' + intake.id); config.intakeId = intake.id; }
      renderBanner();
    }

    function save(thenStep) {
      showSummary(null);
      AIGov.say(say, 'Saving...');
      var request = state.id
        ? AIGov.api('/ai-governance/api/requests/' + state.id, 'PUT', { answers: answers(), version: state.version })
        : AIGov.api('/ai-governance/api/requests', 'POST', { answers: answers(), idempotency_key: idempotencyKey, source_ref: config.sourceRef || null });
      return request.then(function (data) {
        adopt(data.intake);
        AIGov.say(say, 'Draft saved.', 'good');
        if (thenStep !== null && thenStep !== undefined) gotoStep(thenStep);
        return true;
      }).catch(function (err) {
        AIGov.say(say, '');
        showSummary(AIGov.errorText(err), AIGov.fieldErrors(err));
        return false;
      });
    }

    function submit() {
      save(null).then(function (saved) {
        if (!saved) return;
        AIGov.say(say, 'Submitting...');
        AIGov.api('/ai-governance/api/requests/' + state.id + '/submit', 'POST', { version: state.version }).then(function (data) {
          adopt(data.intake);
          AIGov.say(say, 'Submitted. A reviewer will look at it.', 'good');
          renderNav(); renderReview();
        }).catch(function (err) {
          AIGov.say(say, '');
          var missing = err.body && err.body.missing;
          var fields = {};
          (missing || []).forEach(function (key) { fields[key] = 'Answer: ' + (vocab.labels[key] || key); });
          showSummary(AIGov.errorText(err), missing ? fields : AIGov.fieldErrors(err));
        });
      });
    }

    function row(label, value) { return el('div', { class: 'aig-fact' }, [el('dt', { text: label }), el('dd', { text: value || 'Not answered' })]); }
    function words(table, value) { return Array.isArray(value) ? value.map(function (v) { return table[v] || v; }).join(', ') : (table[value] || value); }

    function renderReview() {
      var box = panels[2];
      AIGov.clear(box);
      var a = answers();
      box.appendChild(el('h2', { class: 'aig-h3', text: 'What you have told us' }));
      box.appendChild(el('dl', { class: 'aig-facts' }, [
        row('Name', a.name), row('Purpose', a.purpose), row('Provided', words(vocab.deployment, a.deployment)), row('Provider', a.provider_name),
        row('Owner', a.owner_user_id ? (people[a.owner_user_id] || 'Chosen') : ''), row('Intended users', a.intended_users),
        row('Kinds of data', words(vocab.data_categories, a.data_categories)), row('Who is affected', words(vocab.affected_people, a.affected_people)),
        row('How much it decides', words(vocab.autonomy, a.autonomy))]));
      var dups = el('section', { class: 'aig-panel' }, [el('h3', { class: 'aig-h3', text: 'Is this one of these?' })]);
      box.appendChild(dups);
      if (config.canEdit && a.name && a.name.length >= 3) {
        AIGov.api('/ai-governance/api/duplicates' + AIGov.qs({ name: a.name, provider: a.provider_name })).then(function (data) {
          if (!data.items.length) { dups.appendChild(el('p', { class: 'aig-muted', text: 'No similar application you can see.' })); return; }
          dups.appendChild(el('p', { text: 'These look similar. If yours is one of them, say so in the purpose; the reviewer will link it instead of adding a second one.' }));
          dups.appendChild(el('ul', {}, data.items.map(function (d) {
            return el('li', {}, [el('a', { href: d.url, target: '_blank', rel: 'noopener', text: d.name }), ' (' + d.reason.toLowerCase() + ')']);
          })));
        }).catch(function () { dups.appendChild(el('p', { class: 'aig-muted', text: 'Could not check for similar applications just now.' })); });
      } else { dups.appendChild(el('p', { class: 'aig-muted', text: config.canEdit ? 'Add a name to check for similar applications.' : 'Similar-use review is handled by the governance team.' })); }
      if (state.id) {
        AIGov.api('/ai-governance/api/requests/' + state.id).then(function (data) {
          var s = data.intake.screening;
          var tier = el('section', { class: 'aig-panel' }, [el('h3', { class: 'aig-h3', text: 'First screening' }),
            el('p', {}, [AIGov.tierChip(s.tier, false), ' ', el('span', { class: 'aig-muted', text: 'Internal screening only. A reviewer decides.' })])]);
          if (s.reasons.length) tier.appendChild(el('ul', {}, s.reasons.map(function (r) { return el('li', { text: r.text }); })));
          if (s.missing.length) tier.appendChild(el('p', { class: 'aig-hint', text: 'Not answered yet: ' + s.missing.map(function (f) { return vocab.labels[f] || f; }).join(', ') + '.' }));
          box.appendChild(tier);
        });
      }
    }

    // ── Start ───────────────────────────────────────────────────────────────

    AIGov.say(say, 'Loading...');
    Promise.all([AIGov.api('/ai-governance/api/vocabulary'), AIGov.api('/ai-governance/api/business-units'),
      config.intakeId ? AIGov.api('/ai-governance/api/requests/' + config.intakeId) : Promise.resolve(null)]).then(function (parts) {
      vocab = parts[0]; units = parts[1].items;
      build();
      var intake = parts[2] && parts[2].intake;
      if (intake) {
        adopt(intake); fill(intake.answers);
        if (intake.owner_name) people[intake.answers.owner_user_id] = intake.owner_name;
        if (intake.answers.owner_user_id) ctl.owner_user_id.set(intake.answers.owner_user_id);
      } else {
        fill({ business_unit_id: parts[1].default || null, owner_user_id: config.userId || null });
        if (config.userId) people[config.userId] = config.userName;
        ctl.owner_user_id.set(config.userId || null);
        if (config.sourceName) {
          ctl.name.set(config.sourceName);
          if (config.sourceRef.indexOf('vendor:') === 0) ctl.provider_name.set(config.sourceName);
        }
      }
      AIGov.say(say, '');
      gotoStep(0);
    }).catch(function (err) { AIGov.say(say, AIGov.errorText(err), 'bad'); });
  };
}(window));
