/* AI Governance: what is measured about a use (the Monitoring tab), recorded evaluation runs, the regulatory change queue,
   and "Explain this status". Pages build their DOM from text nodes only.
   Needs ai_governance_common.js and api_client.js. */
(function (global) {
  'use strict';

  var AIGov = global.AIGov, el = AIGov.el;
  var API = '/ai-governance/api';

  var SOURCE_STATE = { attention: ['Look at this', 'warn'], ok: ['As it should be', 'good'], not_measured: ['Not measured', 'muted'],
    no_access: ['No access', 'muted'], unavailable: ['Could not be read', 'warn'] };
  var RUN_STATE = { passed: 'good', failed: 'bad', interrupted: 'warn', ungated: 'muted' };
  var EVALUATORS = { deterministic: 'Fixed checks', human: 'Reviewed by a person', model_graded: 'Graded by a model' };
  var RETENTIONS = { none: 'Nothing kept', summary: 'Summary kept', full: 'Cases kept' };

  function when(value) { return AIGov.date(value) || 'Not recorded'; }

  function scoreText(run) {
    return Object.keys(run.scores).map(function (k) {
      var floor = run.thresholds[k];
      return k.replace(/_/g, ' ') + ' ' + run.scores[k] + (floor !== undefined ? ' (needs ' + floor + ')' : '');
    }).join(', ') || 'No scores';
  }

  // ── The Monitoring tab ───────────────────────────────────────────────────

  AIGov.monitoringPanel = function (host, config) {
    var id = config.applicationId;
    var status = el('div', { class: 'aig-say', role: 'status' });
    var body = el('div', {});
    host.appendChild(status);
    host.appendChild(body);

    function fail(err) { AIGov.say(status, AIGov.errorText(err), 'bad'); }
    function reload() { AIGov.clear(body); load(); }

    function recordDialog() {
      AIGov.dialog('Record an evaluation run', function (box, close) {
        var fields = {};
        function text(key, label, hint) {
          var input = el('input', { type: 'text', maxlength: '200' });
          fields[key] = input;
          box.appendChild(AIGov.field('aigEv_' + key, label, input, hint).row);
        }
        box.appendChild(el('p', { class: 'aig-muted', text: 'ThemisIQ does not run evaluations. Record one that was run, with what it was run against. No prompts or answers are kept.' }));
        text('name', 'Name of the run');
        text('test_set_name', 'Test set');
        text('test_set_version', 'Test set version');
        text('rubric_version', 'Rubric version');
        text('subject_version', 'Version of what was evaluated', 'The model or service version, for example the release date.');
        var evaluator = AIGov.select(Object.keys(EVALUATORS).map(function (k) { return { id: k, name: EVALUATORS[k] }; }), 'deterministic');
        box.appendChild(AIGov.field('aigEv_evaluator', 'Evaluated by', evaluator).row);
        var statusSel = AIGov.select([{ id: 'completed', name: 'Completed' }, { id: 'failed', name: 'Failed' },
          { id: 'cancelled', name: 'Cancelled' }, { id: 'error', name: 'Ended with an error' }], 'completed');
        box.appendChild(AIGov.field('aigEv_status', 'How it ended', statusSel).row);
        var started = el('input', { type: 'date' }), finished = el('input', { type: 'date' });
        box.appendChild(AIGov.field('aigEv_started', 'Started', started).row);
        box.appendChild(AIGov.field('aigEv_finished', 'Finished', finished).row);
        var scores = el('textarea', { rows: '4' });
        box.appendChild(AIGov.field('aigEv_scores', 'Scores', scores, 'One per line as "dimension: score from 0 to 100". Add "needs N" for a threshold, for example "citation validity: 97.5 needs 95".').row);
        var cases = el('input', { type: 'number', min: '0' }), failed = el('input', { type: 'number', min: '0' });
        box.appendChild(AIGov.field('aigEv_cases', 'Cases run', cases).row);
        box.appendChild(AIGov.field('aigEv_failed', 'Cases failed', failed).row);
        var retention = AIGov.select(Object.keys(RETENTIONS).map(function (k) { return { id: k, name: RETENTIONS[k] }; }), 'none');
        box.appendChild(AIGov.field('aigEv_retention', 'What was kept of the cases', retention).row);
        var out = el('div', { class: 'aig-say', role: 'status' });
        box.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: 'Record the run', on: { click: function () {
            var scoreMap = {}, thresholdMap = {};
            scores.value.split('\n').forEach(function (line) {
              var m = line.match(/^\s*([^:]+?)\s*:\s*([0-9.]+)\s*(?:needs\s*([0-9.]+))?\s*$/i);
              if (!m) return;
              scoreMap[m[1].trim()] = parseFloat(m[2]);
              if (m[3] !== undefined) thresholdMap[m[1].trim()] = parseFloat(m[3]);
            });
            var body = { name: fields.name.value, test_set_name: fields.test_set_name.value, test_set_version: fields.test_set_version.value,
              rubric_version: fields.rubric_version.value, subject_version: fields.subject_version.value, evaluator: evaluator.value,
              status: statusSel.value, started_at: started.value || null, finished_at: finished.value || null,
              scores: scoreMap, thresholds: thresholdMap, cases_total: cases.value === '' ? null : parseInt(cases.value, 10),
              cases_failed: failed.value === '' ? null : parseInt(failed.value, 10), retention: retention.value };
            AIGov.say(out, 'Saving...');
            AIGov.api(API + '/systems/' + id + '/evaluations', 'POST', body).then(function () { close(); reload(); })
              .catch(function (err) {
                var fe = AIGov.fieldErrors(err);
                AIGov.say(out, AIGov.errorText(err) + (fe ? ' ' + Object.keys(fe).map(function (k) { return fe[k]; }).join(' ') : ''), 'bad');
              });
          } } }), el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
        box.appendChild(out);
      });
    }

    function reviewDialog(run, outcome) {
      AIGov.dialog(outcome === 'accepted' ? 'Accept this run' : 'Open a finding', function (box, close) {
        var note = el('textarea', { rows: '3', maxlength: '1000' });
        var out = el('div', { class: 'aig-say', role: 'status' });
        box.appendChild(el('p', { class: 'aig-muted', text: outcome === 'accepted'
          ? 'Accepting says the run is sound evidence. It does not certify the use or approve anything.'
          : 'A finding becomes a high priority task for the owner. It does not mark a control failed or withdraw an approval.' }));
        box.appendChild(AIGov.field('aigEvNote', outcome === 'accepted' ? 'Note (optional)' : 'What is the finding?', note).row);
        box.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: outcome === 'accepted' ? 'Accept' : 'Open the finding', on: { click: function () {
            AIGov.say(out, 'Saving...');
            AIGov.api(API + '/evaluations/' + run.id + '/review', 'POST', { outcome: outcome, note: note.value, version: run.version })
              .then(function () { close(); reload(); }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
          } } }), el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
        box.appendChild(out);
      });
    }

    function renderRuns(data) {
      var section = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigRunsH' }, [el('h2', { id: 'aigRunsH', class: 'aig-h3', text: 'Evaluation runs' })]);
      if (data.can.record) section.appendChild(el('div', { class: 'aig-actions' }, [el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Record an evaluation run', on: { click: recordDialog } })]));
      if (!data.runs.length) {
        section.appendChild(el('p', { class: 'aig-note-muted', text: 'No evaluation has been recorded for this use.' }));
        return section;
      }
      if (data.comparison) {
        var moved = data.comparison.dimensions.filter(function (d) { return d.change; }).map(function (d) {
          return d.dimension.replace(/_/g, ' ') + ' ' + (d.change > 0 ? '+' : '') + d.change; });
        var alike = data.comparison.same_test_set && data.comparison.same_rubric ? '' : ' The test set or the rubric differs, so the scores are not a like for like comparison.';
        section.appendChild(el('p', { class: 'aig-hint', text: 'Compared with the run before it on the same test set: ' + (moved.join(', ') || 'no score moved') + '.' + alike }));
      }
      var rows = data.runs.map(function (run) {
        var actions = [];
        if (data.can.review && !run.review_outcome) {
          if (run.state === 'passed') actions.push(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Accept', 'aria-label': 'Accept the run: ' + run.name,
            on: { click: function () { reviewDialog(run, 'accepted'); } } }));
          if (run.state === 'failed' || run.state === 'interrupted') actions.push(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Open a finding',
            'aria-label': 'Open a finding about the run: ' + run.name, on: { click: function () { reviewDialog(run, 'finding'); } } }));
        }
        return el('tr', {}, [
          el('td', {}, [el('strong', { text: run.name }), el('div', { class: 'aig-hint', text: run.test_set_name + ' ' + run.test_set_version + ', rubric ' + run.rubric_version })]),
          el('td', {}, [AIGov.chip(run.state_label, RUN_STATE[run.state] || 'muted'), run.stale ? AIGov.chip('Out of date', 'warn') : null,
            run.review_outcome ? AIGov.chip(run.review_outcome === 'accepted' ? 'Accepted' : 'Finding opened', run.review_outcome === 'accepted' ? 'good' : 'warn') : null]),
          el('td', { text: scoreText(run) }), el('td', { text: run.subject_version }), el('td', { text: EVALUATORS[run.evaluator] || run.evaluator }),
          el('td', { text: when(run.finished_at) }), el('td', {}, actions)]);
      });
      section.appendChild(el('div', { class: 'aig-tablewrap' }, [el('table', { class: 'aig-table' }, [
        el('thead', {}, [el('tr', {}, ['Run', 'Result', 'Scores', 'Evaluated', 'By', 'Finished', ''].map(function (h) { return el('th', { scope: 'col', text: h }); }))]),
        el('tbody', {}, rows)])]));
      return section;
    }

    function load() {
      AIGov.say(status, 'Loading...');
      Promise.all([AIGov.api(API + '/systems/' + id + '/monitoring'), AIGov.api(API + '/systems/' + id + '/evaluations')]).then(function (parts) {
        AIGov.say(status, '');
        var monitor = parts[0], runs = parts[1];
        var list = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigMonH' }, [el('h2', { id: 'aigMonH', class: 'aig-h3', text: 'What is measured' })]);
        if (monitor.attention.length) list.appendChild(el('p', { class: 'aig-note-warn', text: monitor.attention.length + ' source' + (monitor.attention.length === 1 ? '' : 's') + ' to look at.' }));
        if (monitor.unavailable.length) list.appendChild(el('p', { class: 'aig-note-warn', text: 'Could not be read just now: ' + monitor.unavailable.join(', ') + '. That is not a clean result.' }));
        monitor.sources.forEach(function (s) {
          var label = SOURCE_STATE[s.state] || [s.state, 'muted'];
          var item = el('div', { class: 'aig-source' }, [el('h3', { class: 'aig-h3' }, [s.title + ' ', AIGov.chip(label[0], label[1])])]);
          if (s.items.length) item.appendChild(el('ul', { class: 'aig-list' }, s.items.map(function (i) {
            return el('li', {}, [i.url ? el('a', { href: i.url, text: i.title }) : el('span', { text: i.title }), i.detail ? el('span', { class: 'aig-muted', text: i.detail }) : null]);
          })));
          if (s.note) item.appendChild(el('p', { class: 'aig-note-muted', text: s.note }));
          list.appendChild(item);
        });
        body.appendChild(list);
        body.appendChild(renderRuns(runs));
      }).catch(fail);
    }
    load();
  };

  // ── Explain this status ──────────────────────────────────────────────────

  AIGov.explainDialog = function (applicationId, name) {
    AIGov.dialog('Why is ' + (name || 'this use') + ' in this state?', function (box, close) {
      var holder = el('div', {});
      var out = el('div', { class: 'aig-say', role: 'status', text: 'Working it out...' });
      box.appendChild(holder);
      box.appendChild(out);
      function show(useAi) {
        AIGov.clear(holder);
        AIGov.say(out, 'Working it out...');
        AIGov.api(API + '/systems/' + applicationId + '/explain' + AIGov.qs({ ai: useAi ? 1 : 0 })).then(function (data) {
          AIGov.say(out, '');
          holder.appendChild(el('p', { class: 'aig-hint', text: data.mode === 'ai'
            ? 'Written by a model from the facts below, and checked: a sentence that does not cite a fact is left out.'
            : 'Built from the rules. Each sentence is a fact you can open.' }));
          if (data.note) holder.appendChild(el('p', { class: 'aig-note-warn', text: data.note }));
          var byId = {};
          data.facts.forEach(function (f) { byId[f.id] = f; });
          holder.appendChild(el('ul', { class: 'aig-list' }, data.sentences.map(function (s) {
            var links = s.cites.map(function (c) {
              var f = byId[c];
              return f && f.url ? el('a', { href: f.url, text: c, 'aria-label': 'Open the source of fact ' + c }) : el('span', { class: 'aig-muted', text: c });
            });
            var kids = [el('span', { text: s.text }), el('span', { class: 'aig-muted' }, ['(', ].concat(links.reduce(function (acc, n, i) {
              if (i) acc.push(', ');
              acc.push(n);
              return acc;
            }, []), [')']))];
            return el('li', {}, kids);
          })));
          var actions = [];
          if (data.mode === 'rules') actions.push(el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Rephrase with AI', on: { click: function () { show(true); } } }));
          actions.push(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Close', on: { click: close } }));
          holder.appendChild(el('div', { class: 'aig-actions' }, actions));
        }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
      }
      show(false);
    });
  };

  // ── Regulatory changes ───────────────────────────────────────────────────

  AIGov.regulatoryQueue = function (root) {
    var status = el('div', { class: 'aig-say', role: 'status' });
    var note = el('p', { class: 'aig-hint' });
    var filters = el('form', { class: 'aig-filters', role: 'search', 'aria-label': 'Filter regulatory changes' });
    var tableWrap = el('div', { class: 'aig-tablewrap' });
    [filters, note, status, tableWrap].forEach(function (n) { root.appendChild(n); });
    filters.addEventListener('submit', function (event) { event.preventDefault(); });
    var current = 'candidate';
    var select = AIGov.select([{ id: 'candidate', name: 'Waiting for review' }, { id: 'confirmed', name: 'Confirmed' }, { id: 'dismissed', name: 'Dismissed' }], current);
    select.addEventListener('change', function () { current = select.value; load(); });
    filters.appendChild(AIGov.field('aigRegStatus', 'Show', select).row);
    var refreshBtn = el('button', { type: 'button', class: 'btn btn-secondary', hidden: true,
      text: 'Look for AI uses affected by new changes' });
    refreshBtn.addEventListener('click', function () {
      AIGov.say(status, 'Looking...');
      AIGov.api(API + '/regulatory/refresh', 'POST', {}).then(function (data) {
        AIGov.say(status, data.created + ' proposed' + (data.reopened ? ', ' + data.reopened + ' proposed again' : '') + '.', 'good');
        load();
      }).catch(function (err) { AIGov.say(status, AIGov.errorText(err), 'bad'); });
    });
    filters.appendChild(refreshBtn);

    function reviewDialog(item, decision) {
      AIGov.dialog(decision === 'confirm' ? 'Confirm this change concerns the use' : 'Dismiss this change', function (box, close) {
        var reason = el('textarea', { rows: '3', maxlength: '1000' });
        var out = el('div', { class: 'aig-say', role: 'status' });
        box.appendChild(el('p', { class: 'aig-muted', text: decision === 'confirm'
          ? 'This makes one task for the owner of the use. Check the source before you confirm.'
          : 'It will not come back unless the change itself is changed.' }));
        box.appendChild(AIGov.field('aigRegReason', decision === 'confirm' ? 'Note for the owner (optional)' : 'Why does it not concern this use?', reason).row);
        box.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: decision === 'confirm' ? 'Confirm' : 'Dismiss', on: { click: function () {
            AIGov.say(out, 'Saving...');
            AIGov.api(API + '/regulatory/' + item.id + '/review', 'POST', { decision: decision, reason: reason.value, version: item.version })
              .then(function () { close(); load(); }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
          } } }), el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
        box.appendChild(out);
      });
    }

    function load() {
      AIGov.say(status, 'Loading...');
      AIGov.clear(tableWrap);
      AIGov.api(API + '/regulatory' + AIGov.qs({ status: current })).then(function (data) {
        AIGov.say(status, '');
        note.textContent = data.note;
        refreshBtn.hidden = !data.can_review;
        if (!data.items.length) { tableWrap.appendChild(el('div', { class: 'aig-empty', text: 'Nothing here.' })); return; }
        var rows = data.items.map(function (i) {
          var actions = [];
          if (data.can_review && i.status === 'candidate') {
            actions.push(el('button', { type: 'button', class: 'btn btn-primary btn-sm', text: 'Confirm', 'aria-label': 'Confirm: ' + i.title + ' for ' + i.system,
              on: { click: function () { reviewDialog(i, 'confirm'); } } }));
            actions.push(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Dismiss', 'aria-label': 'Dismiss: ' + i.title + ' for ' + i.system,
              on: { click: function () { reviewDialog(i, 'dismiss'); } } }));
          }
          return el('tr', {}, [
            el('td', {}, [el('strong', { text: i.title }), el('div', { class: 'aig-hint', text: i.framework_name + (i.effective_date ? ', effective ' + i.effective_date : '') }),
              i.source_url ? el('a', { href: i.source_url, text: 'Source', rel: 'noopener noreferrer', target: '_blank' }) : null]),
            el('td', {}, [el('a', { href: i.url, text: i.system })]), el('td', { text: i.basis || '' }),
            el('td', {}, [AIGov.chip(i.status === 'candidate' ? 'Waiting' : (i.status === 'confirmed' ? 'Confirmed' : 'Dismissed'),
              i.status === 'confirmed' ? 'good' : (i.status === 'dismissed' ? 'muted' : 'warn')), i.review_note ? el('div', { class: 'aig-hint', text: i.review_note }) : null]),
            el('td', {}, actions)]);
        });
        tableWrap.appendChild(el('table', { class: 'aig-table' }, [
          el('thead', {}, [el('tr', {}, ['Change', 'AI use', 'Why it was proposed', 'Status', ''].map(function (h) { return el('th', { scope: 'col', text: h }); }))]),
          el('tbody', {}, rows)]));
      }).catch(function (err) { AIGov.say(status, AIGov.errorText(err), 'bad'); });
    }
    load();
  };
}(window));
