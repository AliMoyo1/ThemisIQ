/* AI Governance: decisions on an AI use. The Decisions tab of a system and the queue of open requests.
   Pages build their DOM from text nodes only: nothing that comes from the server is ever parsed as markup.
   Needs ai_governance_common.js and api_client.js. */
(function (global) {
  'use strict';

  var AIGov = global.AIGov, el = AIGov.el;
  var API = '/ai-governance/api';

  var STATE_KIND = { none: 'muted', approved: 'good', approved_with_conditions: 'good', needs_re_review: 'warn',
    expired: 'warn', rejected: 'bad', revoked: 'bad' };
  var STATUS_LABEL = { proposed: 'Waiting for a decision', approved: 'Approved', approved_with_conditions: 'Approved with conditions',
    rejected: 'Not approved', returned: 'Returned for changes', withdrawn: 'Withdrawn' };
  var OUTCOMES = [
    { id: 'approve', label: 'Approve', hint: 'The use may go ahead as described.' },
    { id: 'approve_with_conditions', label: 'Approve with conditions', hint: 'It may go ahead if the named conditions are kept.' },
    { id: 'return', label: 'Return for changes', hint: 'Send it back with what is needed. This is not a decision.' },
    { id: 'reject', label: 'Reject', hint: 'It may not go ahead as described.' }];
  var STEP_STATE = { not_started: 'Not started', in_progress: 'In progress', complete: 'Done', no_access: 'No access', unavailable: 'Could not be read' };
  var NEED = { required: 'Needed', recommended: 'Recommended', not_applicable: 'Not applicable', needs_review: 'Needs review' };

  function when(value) { return AIGov.date(value) || 'Not recorded'; }

  function named(text, who, at) { return text + (who ? ' by ' + who : '') + (at ? ' on ' + when(at) : ''); }

  // ── A decision's brief: what it is being decided on ──────────────────────

  function briefList(manifest) {
    var parts = [];
    var steps = manifest.checklist.steps;
    parts.push(el('h3', { class: 'aig-h3', text: 'Steps' }));
    parts.push(el('ul', { class: 'aig-list' }, steps.map(function (s) {
      var kids = [el('strong', { text: s.title }), AIGov.chip(NEED[s.effective] || s.effective, s.effective === 'required' ? 'bad' : 'muted')];
      if (s.effective !== 'not_applicable') kids.push(AIGov.chip(STEP_STATE[s.state] || s.state, s.state === 'complete' ? 'good' : 'muted'));
      if (s.override) kids.push(el('span', { class: 'aig-hint', text: 'Ruled out: ' + s.override.reason }));
      (s.records || []).forEach(function (r) {
        if (r.restricted) kids.push(el('span', { class: 'aig-muted', text: 'A record you cannot open' }));
        else if (r.title) kids.push(r.url ? el('a', { href: r.url, text: r.title }) : el('span', { class: 'aig-muted', text: r.title }), AIGov.chip(r.status || 'recorded'));
      });
      return el('li', {}, kids);
    })));
    var assessments = manifest.assessments;
    parts.push(el('h3', { class: 'aig-h3', text: 'AI impact assessments' }));
    if (!Array.isArray(assessments)) {
      parts.push(el('p', { class: 'aig-note-muted', text: 'You do not have access to AI impact assessments.' }));
    } else if (!assessments.length) {
      parts.push(el('p', { class: 'aig-note-muted', text: 'None recorded.' }));
    } else {
      parts.push(el('ul', { class: 'aig-list' }, assessments.map(function (a) {
        var label = a.restricted ? 'A record you cannot open' : a.ref + ': ' + a.title;
        return el('li', {}, [a.url ? el('a', { href: a.url, text: label }) : el('span', { text: label }),
          a.restricted ? null : AIGov.chip(a.status || 'recorded'),
          !a.restricted && a.classification ? el('span', { class: 'aig-muted', text: 'Classification: ' + a.classification }) : null]);
      })));
    }
    parts.push(el('h3', { class: 'aig-h3', text: 'AI controls and their proof' }));
    if (!manifest.controls.length) {
      parts.push(el('p', { class: 'aig-note-muted', text: 'No AI controls are recorded for this use, or you cannot see them.' }));
    } else {
      parts.push(el('ul', { class: 'aig-list' }, manifest.controls.map(function (c) {
        if (c.restricted) return el('li', { class: 'aig-muted', text: 'A control you cannot open' });
        var label = (c.ref ? c.ref + ' ' : '') + c.title;
        return el('li', {}, [el('span', { text: label }),
          el('span', { class: 'aig-muted', text: (c.implemented ? 'Implemented. ' : 'Not implemented. ') + 'Open the control to review its current mappings and proof.' })]);
      })));
    }
    var open = manifest.quality.open;
    parts.push(el('h3', { class: 'aig-h3', text: 'Quality checks' }));
    parts.push(open.length ? el('ul', { class: 'aig-list' }, open.map(function (f) {
      return el('li', {}, [AIGov.chip(f.severity === 'error' ? 'Needs doing' : 'Check', f.severity === 'error' ? 'bad' : 'warn'), el('span', { text: f.rule.replace(/_/g, ' ') })]);
    })) : el('p', { class: 'aig-note-muted', text: 'Nothing open.' }));
    if (manifest.quality.unchecked.length) parts.push(el('p', { class: 'aig-note-warn', text: 'Could not be checked: ' + manifest.quality.unchecked.join(', ') + '.' }));
    return parts;
  }

  // ── The panel on the system's Decisions tab ──────────────────────────────

  AIGov.decisionsPanel = function (host, config) {
    var id = config.applicationId;
    var status = el('div', { class: 'aig-say', role: 'status' });
    var body = el('div', {});
    host.appendChild(status);
    host.appendChild(body);

    function fail(err) { AIGov.say(status, AIGov.errorText(err), 'bad'); }
    function reload() { AIGov.say(status, ''); AIGov.clear(body); load(); if (config.onChanged) config.onChanged(); }

    function askDialog() {
      AIGov.dialog('Ask for a decision', function (box, close) {
        var note = el('textarea', { rows: '3', maxlength: '1000' });
        var out = el('div', { class: 'aig-say', role: 'status' });
        box.appendChild(el('p', { class: 'aig-muted', text: 'A decider will see what this use is and where each required step stands, and then decide.' }));
        box.appendChild(AIGov.field('aigAskNote', 'A note for the decider (optional)', note).row);
        box.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: 'Ask for a decision', on: { click: function () {
            AIGov.say(out, 'Sending...');
            AIGov.api(API + '/systems/' + id + '/decisions', 'POST', { note: note.value.trim() || null })
              .then(function () { close(); reload(); }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
          } } }), el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
        box.appendChild(out);
      });
    }

    function reasonDialog(title, label, verb, send) {
      AIGov.dialog(title, function (box, close) {
        var reason = el('textarea', { rows: '3', maxlength: '1000' });
        var out = el('div', { class: 'aig-say', role: 'status' });
        box.appendChild(AIGov.field('aigReason', label, reason).row);
        box.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: verb, on: { click: function () {
            AIGov.say(out, 'Saving...');
            send(reason.value).then(function () { close(); reload(); }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
          } } }), el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
        box.appendChild(out);
      });
    }

    function decideDialog(request) {
      AIGov.dialog('Decide: ' + (config.name || 'this AI use'), function (box, close) {
        var loading = el('p', { class: 'aig-muted', text: 'Loading the brief...' });
        box.appendChild(loading);
        AIGov.api(API + '/systems/' + id + '/decision-brief').then(function (brief) {
          box.removeChild(loading);
          if (brief.changed_since_standing.length) {
            box.appendChild(el('div', { class: 'aig-banner aig-banner-warn' }, [el('strong', { text: 'Since the last decision' }),
              el('ul', {}, brief.changed_since_standing.map(function (line) { return el('li', { text: line }); }))]));
          }
          if (brief.unresolved.length) {
            box.appendChild(el('div', { class: 'aig-banner aig-banner-bad', role: 'note' }, [
              el('strong', { text: 'Required steps are not done: ' }), brief.unresolved.map(function (u) { return u.title; }).join(', ') + '. ' +
              'You can still approve, with a reason that is recorded.']));
          }
          box.appendChild(el('div', { class: 'aig-brief' }, briefList(brief.manifest)));

          var outcome = 'approve';
          var radios = el('fieldset', { class: 'aig-fieldset' }, [el('legend', { text: 'Your decision' })]);
          var conditionRows = el('div', {});
          var extras = el('div', {});
          OUTCOMES.forEach(function (o) {
            var radio = el('input', { type: 'radio', name: 'aigOutcome', value: o.id, checked: o.id === 'approve' });
            radio.addEventListener('change', function () { outcome = o.id; paint(); });
            radios.appendChild(el('label', { class: 'aig-radio' }, [radio, el('span', {}, [el('strong', { text: o.label }), el('span', { class: 'aig-hint', text: ' ' + o.hint })])]));
          });
          box.appendChild(radios);
          var rationale = el('textarea', { rows: '3', maxlength: '1000' });
          var expires = el('input', { type: 'date' });
          var override = el('textarea', { rows: '2', maxlength: '1000' });
          var rationaleField = AIGov.field('aigRationale', 'Why', rationale, 'Needed to return or reject. Optional when approving.');
          box.appendChild(rationaleField.row);
          box.appendChild(extras);
          var out = el('div', { class: 'aig-say', role: 'status' });
          var conditionInputs = [];

          function addCondition() {
            var n = conditionInputs.length + 1;
            var text = el('input', { type: 'text', maxlength: '1000' });
            var due = el('input', { type: 'date' });
            conditionInputs.push({ text: text, due: due });
            conditionRows.appendChild(el('div', { class: 'aig-impact-fields' }, [
              AIGov.field('aigCond' + n, 'Condition ' + n, text).row, AIGov.field('aigCondDue' + n, 'Due (optional)', due).row]));
          }

          function paint() {
            AIGov.clear(extras);
            var approving = outcome === 'approve' || outcome === 'approve_with_conditions';
            if (approving) extras.appendChild(AIGov.field('aigExpires', 'Valid until (optional)', expires, 'After this date the approval reads as expired and asks for a new decision.').row);
            if (outcome === 'approve_with_conditions') {
              extras.appendChild(conditionRows);
              if (!conditionInputs.length) addCondition();
              extras.appendChild(el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Add a condition', on: { click: addCondition } }));
            }
            if (approving && brief.needs_override) {
              extras.appendChild(AIGov.field('aigOverride', 'Why this goes ahead with required steps not done', override,
                'Recorded with the decision and visible to anyone who reads it.').row);
            }
          }
          paint();

          box.appendChild(el('div', { class: 'aig-actions' }, [
            el('button', { type: 'button', class: 'btn btn-primary', text: 'Record the decision', on: { click: function () {
              var body = { outcome: outcome, rationale: rationale.value.trim() || null, brief_hash: brief.hash, version: request.version };
              if (outcome === 'approve' || outcome === 'approve_with_conditions') {
                body.expires_at = expires.value || null;
                if (brief.needs_override) body.override_reason = override.value.trim() || null;
              }
              if (outcome === 'approve_with_conditions') {
                body.conditions = conditionInputs.map(function (c) { return { text: c.text.value.trim(), due_date: c.due.value || null }; })
                  .filter(function (c) { return c.text; });
              }
              AIGov.say(out, 'Saving...');
              AIGov.api(API + '/decisions/' + request.id + '/decide', 'POST', body)
                .then(function () { close(); reload(); }).catch(function (err) { AIGov.say(out, AIGov.errorText(err), 'bad'); });
            } } }), el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
          box.appendChild(out);
        }).catch(function (err) { loading.textContent = AIGov.errorText(err); });
      });
    }

    function signedOnDialog(decision) {
      AIGov.dialog('What it was decided on', function (box, close) {
        var loading = el('p', { class: 'aig-muted', text: 'Loading...' });
        box.appendChild(loading);
        AIGov.api(API + '/decisions/' + decision.id).then(function (data) {
          box.removeChild(loading);
          var d = data.decision;
          box.appendChild(el('p', { class: 'aig-muted', text: 'Signed on ' + when(d.decided_at) + ' against AI profile version ' + d.profile_version +
            ', tier ' + d.tier + ', rules ' + d.rule_version + '. Record ' + d.manifest_hash + '.' }));
          if (d.manifest) box.appendChild(el('div', { class: 'aig-brief' }, briefList(d.manifest)));
          box.appendChild(el('div', { class: 'aig-actions' }, [
            el('a', { class: 'btn btn-secondary', href: API + '/decisions/' + decision.id + '/export', text: 'Download the record' }),
            el('button', { type: 'button', class: 'btn btn-ghost', text: 'Close', on: { click: close } })]));
        }).catch(function (err) { loading.textContent = AIGov.errorText(err); });
      });
    }

    function conditionsBlock(decision, canChange) {
      if (!decision.conditions.length) return null;
      return el('div', {}, [el('h3', { class: 'aig-h3', text: 'Conditions' }), el('ul', { class: 'aig-list' }, decision.conditions.map(function (c) {
        var kids = [el('span', { text: c.text }), AIGov.chip(c.status === 'met' ? 'Met' : 'Open', c.status === 'met' ? 'good' : 'warn')];
        if (c.due_date) kids.push(el('span', { class: 'aig-muted', text: 'Due ' + c.due_date }));
        if (c.status === 'met') kids.push(el('span', { class: 'aig-muted', text: named('Met', c.met_by, c.met_at) + (c.note ? ': ' + c.note : '') }));
        if (canChange && decision.status !== 'rejected') {
          kids.push(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: c.status === 'met' ? 'Reopen' : 'Mark as met',
            'aria-label': (c.status === 'met' ? 'Reopen the condition: ' : 'Mark as met: ') + c.text, on: { click: function () {
              AIGov.api(API + '/decision-conditions/' + c.id, 'PUT', { met: c.status !== 'met' }).then(reload).catch(fail);
            } } }));
        }
        return el('li', {}, kids);
      }))]);
    }

    function render(data) {
      AIGov.clear(body);
      var s = data.state, can = data.can;
      var head = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigDecState' }, [el('h2', { id: 'aigDecState', class: 'aig-h3', text: 'Standing' })]);
      var stateKids = [AIGov.chip(s.label, STATE_KIND[s.state] || 'muted')];
      if (s.waiting) stateKids.push(' ', AIGov.chip('A request is waiting', 'info'));
      head.appendChild(el('p', {}, stateKids));
      if (s.reasons.length) head.appendChild(el('ul', {}, s.reasons.map(function (r) { return el('li', { text: r }); })));
      if (s.state === 'needs_re_review' || s.state === 'expired') {
        head.appendChild(el('p', { class: 'aig-hint', text: 'The earlier decision below is unchanged. Ask for a new decision to bring it up to date.' }));
      }
      var actions = [];
      if (can.request) actions.push(el('button', { type: 'button', class: 'btn btn-primary', text: 'Ask for a decision', on: { click: askDialog } }));
      if (can.revoke) actions.push(el('button', { type: 'button', class: 'btn btn-ghost', text: 'Revoke the approval', on: { click: function () {
        reasonDialog('Revoke the approval', 'Why is it being revoked?', 'Revoke', function (reason) {
          return AIGov.api(API + '/decisions/' + data.latest.id + '/revoke', 'POST', { reason: reason });
        });
      } } }));
      if (actions.length) head.appendChild(el('div', { class: 'aig-actions' }, actions));
      body.appendChild(head);

      if (data.oversight && data.oversight.tracks) {
        var oversight = data.oversight.tracks;
        var labels = { design: 'Design', operation: 'Operation' };
        var summaries = ['design', 'operation'].map(function (track) {
          var record = oversight[track];
          var label = record.status === 'not_recorded' ? 'Not recorded' :
            record.profile_changed ? 'Profile changed' : record.status === 'reviewed' ? 'Reviewed' : 'Draft';
          return el('li', { text: labels[track] + ': ' + label });
        });
        body.appendChild(el('section', { class: 'aig-panel', 'aria-labelledby': 'aigDecOversight' }, [
          el('h2', { id: 'aigDecOversight', class: 'aig-h3', text: 'Human oversight' }),
          el('p', { class: 'aig-hint', text: 'Live arrangement status. It does not change the signed decision or establish legal conformity.' }),
          el('ul', {}, summaries),
          el('a', { class: 'btn btn-secondary btn-sm', href: '#oversight', text: 'Open oversight' })
        ]));
      }

      if (data.open_request) {
        var r = data.open_request;
        var box = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigDecOpen' }, [el('h2', { id: 'aigDecOpen', class: 'aig-h3', text: 'Waiting for a decision' }),
          el('p', { text: named('Asked', r.requested_by, r.requested_at) + '.' })]);
        if (r.request_note) box.appendChild(el('p', { text: 'Note: ' + r.request_note }));
        var openActions = [];
        if (can.decide) openActions.push(el('button', { type: 'button', class: 'btn btn-primary', text: 'Review and decide', on: { click: function () { decideDialog(r); } } }));
        if (can.withdraw) openActions.push(el('button', { type: 'button', class: 'btn btn-ghost', text: 'Withdraw the request', on: { click: function () {
          AIGov.api(API + '/decisions/' + r.id + '/withdraw', 'POST', {}).then(reload).catch(fail);
        } } }));
        if (can.decide_blocked) box.appendChild(el('p', { class: 'aig-note-warn', text: can.decide_blocked }));
        if (openActions.length) box.appendChild(el('div', { class: 'aig-actions' }, openActions));
        body.appendChild(box);
      }

      if (data.latest) {
        var d = data.latest;
        var latest = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigDecLatest' }, [
          el('h2', { id: 'aigDecLatest', class: 'aig-h3', text: 'Latest decision' }),
          el('p', {}, [AIGov.chip(STATUS_LABEL[d.status] || d.status, STATE_KIND[d.status] || 'muted'), ' ',
            el('span', { class: 'aig-muted', text: named('Decided', d.decided_by, d.decided_at) })])]);
        if (d.rationale) latest.appendChild(el('p', { text: 'Why: ' + d.rationale }));
        if (d.expires_at) latest.appendChild(el('p', { text: 'Valid until ' + d.expires_at + '.' }));
        if (d.override_reason) latest.appendChild(el('p', { class: 'aig-note-warn', text: 'Went ahead with required steps not done: ' + d.override_reason }));
        if (d.revoked_at) latest.appendChild(el('p', { class: 'aig-note-warn', text: named('Revoked', d.revoked_by, d.revoked_at) + ': ' + d.revoked_reason }));
        if (!d.separation_enforced) latest.appendChild(el('p', { class: 'aig-hint', text: 'Made while separation of duties was off for this organization.' }));
        var cond = conditionsBlock(d, can.conditions);
        if (cond) latest.appendChild(cond);
        latest.appendChild(el('div', { class: 'aig-actions' }, [el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'What it was decided on',
          on: { click: function () { signedOnDialog(d); } } })]));
        body.appendChild(latest);
      } else if (!data.open_request) {
        body.appendChild(el('p', { class: 'aig-note-muted', text: 'No decision has been recorded for this use.' }));
      }

      var history = data.history.filter(function (h) { return !data.latest || h.id !== data.latest.id; });
      if (history.length) {
        var rows = history.map(function (h) {
          return el('tr', {}, [el('td', { text: when(h.decided_at) }), el('td', {}, [AIGov.chip(STATUS_LABEL[h.status] || h.status, STATE_KIND[h.status] || 'muted')]),
            el('td', { text: h.decided_by || 'Not recorded' }), el('td', { text: h.rationale || '' }),
            el('td', {}, [h.status === 'approved' || h.status === 'approved_with_conditions' || h.status === 'rejected'
              ? el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'What it was decided on', on: { click: function () { signedOnDialog(h); } } }) : null])]);
        });
        body.appendChild(el('section', { class: 'aig-panel', 'aria-labelledby': 'aigDecHist' }, [el('h2', { id: 'aigDecHist', class: 'aig-h3', text: 'Earlier decisions' }),
          el('div', { class: 'aig-tablewrap' }, [el('table', { class: 'aig-table' }, [
            el('thead', {}, [el('tr', {}, ['When', 'Outcome', 'By', 'Why', ''].map(function (h) { return el('th', { scope: 'col', text: h }); }))]),
            el('tbody', {}, rows)])])]));
      }
      body.appendChild(el('p', { class: 'aig-hint', text: 'A decision here is a judgement about the use. Accepting a risk with exposure is a separate signed decision in the risk register.' }));
    }

    function load() {
      AIGov.say(status, 'Loading...');
      AIGov.api(API + '/systems/' + id + '/decisions').then(function (data) { AIGov.say(status, ''); render(data); }).catch(fail);
    }
    load();
  };

  // ── The queue ────────────────────────────────────────────────────────────

  AIGov.decisionQueue = function (root) {
    var status = el('div', { class: 'aig-say', role: 'status' });
    var body = el('div', {});
    root.appendChild(status);
    root.appendChild(body);
    AIGov.say(status, 'Loading...');
    AIGov.api(API + '/decisions').then(function (data) {
      AIGov.say(status, '');
      var requests = data.requests, reviews = data.re_reviews;
      body.appendChild(el('h2', { class: 'aig-h2', text: 'Waiting for a decision' }));
      if (!requests.length) body.appendChild(el('div', { class: 'aig-empty', text: 'No AI use is waiting for a decision.' }));
      else body.appendChild(el('div', { class: 'aig-tablewrap' }, [el('table', { class: 'aig-table' }, [
        el('thead', {}, [el('tr', {}, ['AI system', 'Asked by', 'Asked', 'Note', ''].map(function (h) { return el('th', { scope: 'col', text: h }); }))]),
        el('tbody', {}, requests.map(function (r) {
          return el('tr', {}, [el('td', {}, [el('a', { href: r.url, text: r.name })]), el('td', { text: r.requested_by || 'Not recorded' }),
            el('td', { text: when(r.requested_at) }), el('td', { text: r.note || '' }),
            el('td', {}, [r.yours ? AIGov.chip('Yours', 'info') : null])]);
        }))])]));
      body.appendChild(el('h2', { class: 'aig-h2', text: 'Needs re-review' }));
      if (!reviews.length) body.appendChild(el('div', { class: 'aig-empty', text: 'No approval needs a new decision.' }));
      else body.appendChild(el('div', { class: 'aig-tablewrap' }, [el('table', { class: 'aig-table' }, [
        el('thead', {}, [el('tr', {}, ['AI system', 'Why', 'Decided'].map(function (h) { return el('th', { scope: 'col', text: h }); }))]),
        el('tbody', {}, reviews.map(function (r) {
          return el('tr', {}, [el('td', {}, [el('a', { href: r.url, text: r.name })]),
            el('td', {}, [AIGov.chip(r.label, 'warn'), el('ul', {}, r.reasons.map(function (x) { return el('li', { text: x }); }))]),
            el('td', { text: when(r.decided_at) })]);
        }))])]));
    }).catch(function (err) { AIGov.say(status, AIGov.errorText(err), 'bad'); });
  };
}(window));
