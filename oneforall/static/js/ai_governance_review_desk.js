/* AI Governance: the review desk (plans/2026-10-governance-rework/01 sections 5 and 6).

   Four panels, each loaded on its own so a failing source affects only itself:
     AIGov.outstandingPanel   what stands between the use and a decision, line by line
     AIGov.precedentsPanel    other uses this one may be, with why and what differs, and a specialist's verdict
     AIGov.questionsPanel     questions for a requester who has no account, taken out as text
     AIGov.responsesPanel     the response to the requester: draft, approve, download, record that it was sent
   Text only, no markup from the server. */
(function (global) {
  'use strict';
  var A = global.AIGov, el = A.el;

  var STATE_KIND = { complete: 'good', not_applicable: 'muted', not_yet_assessed: 'warn', waiting: 'info', failed: 'bad',
    unavailable: 'bad', no_access: 'muted' };

  // Links come from the server as paths inside this app; anything else is shown as text, never followed.
  function safe(url) { return typeof url === 'string' && url.charAt(0) === '/' && url.charAt(1) !== '/' ? url : null; }
  function link(url, text, attrs) {
    var href = safe(url);
    return href ? el('a', Object.assign({ href: href, text: text }, attrs || {})) : el('span', { text: text });
  }

  function load(host, title, url, render, ifMissing) {
    var box = el('section', { class: 'aig-panel', 'aria-label': title });
    var status = el('div', { class: 'aig-say', role: 'status' });
    box.appendChild(el('h2', { class: 'aig-h3', text: title }));
    box.appendChild(status);
    host.appendChild(box);
    A.say(status, 'Loading...');
    A.api(url).then(function (data) { A.say(status, ''); render(box, data, status); })
      .catch(function (err) {
        if (ifMissing && err && err.status === 404) A.say(status, ifMissing);
        else A.say(status, A.errorText(err), 'bad');
      });
    return box;
  }

  // ── Outstanding items ─────────────────────────────────────────────────────

  A.outstandingPanel = function (host, config) {
    return load(host, 'What is left before a decision', '/ai-governance/api/systems/' + config.applicationId + '/outstanding', function (box, data) {
      var summary = el('p', { class: 'aig-muted' });
      summary.textContent = data.ready_for_decision
        ? 'Nothing that blocks a decision is open. This does not approve the use.'
        : 'Not ready for a decision: ' + (data.blocking.length ? data.blocking.length + ' required item(s) are open. ' : '')
          + (data.unavailable.length ? data.unavailable.length + ' source(s) could not be read.' : '');
      box.appendChild(summary);
      box.appendChild(el('ul', { class: 'aig-list' }, data.lines.map(function (line) {
        var head = [A.chip(line.state_label, STATE_KIND[line.state]), el('strong', { text: line.title }),
          el('span', { class: 'aig-muted', text: line.module })];
        if (line.blocks_decision && line.state !== 'complete' && line.state !== 'not_applicable') head.push(A.chip('Blocks a decision', 'bad'));
        if (line.due) head.push(el('span', { class: 'aig-muted', text: 'Due ' + line.due }));
        var body = [el('div', { class: 'aig-hint', text: line.reason })];
        if (line.owner) body.push(el('div', { class: 'aig-hint', text: 'Owner: ' + line.owner.name }));
        if (line.records && line.records.length) {
          body.push(el('div', { class: 'aig-hint' }, ['Records: '].concat(line.records.map(function (r, i) {
            return el('span', {}, [i ? ', ' : '', link(r.url, r.title)]);
          }))));
        }
        if (line.resolution && safe(line.resolution.url)) body.push(link(line.resolution.url, line.resolution.label, { class: 'aig-hint' }));
        return el('li', {}, [el('div', {}, [el('div', { class: 'aig-meta' }, head)].concat(body))]);
      })));
      box.appendChild(el('p', { class: 'aig-hint', text: data.note + ' Rules ' + data.rule_version + '.' }));
    });
  };

  // ── Precedents ────────────────────────────────────────────────────────────

  var BAND_TITLE = { verified_same_use: 'Confirmed as the same use', possible_match: 'Possible match', related_precedent: 'Related precedent' };

  A.precedentsPanel = function (host, config) {
    var url = config.subjectKind === 'request'
      ? '/ai-governance/api/requests/' + config.subjectId + '/precedents'
      : '/ai-governance/api/systems/' + config.subjectId + '/precedents';
    var box = load(host, 'Has the organization seen something like this?', url, function (panel, data) {
      panel.appendChild(el('p', { class: 'aig-hint', text: data.note }));
      var any = false;
      Object.keys(BAND_TITLE).forEach(function (band) {
        var items = data.bands[band] || [];
        if (!items.length) return;
        any = true;
        panel.appendChild(el('h3', { class: 'aig-h3', text: BAND_TITLE[band] }));
        panel.appendChild(el('ul', { class: 'aig-list' }, items.map(function (c) { return candidate(c, config, function () { reload(); }); })));
        if (data.more && data.more[band]) panel.appendChild(el('p', { class: 'aig-hint', text: data.more[band] + ' more in this band are not shown.' }));
      });
      if (data.set_aside && data.set_aside.length) {
        panel.appendChild(el('details', {}, [el('summary', { text: data.set_aside.length + ' set aside as not related' }),
          el('ul', { class: 'aig-list' }, data.set_aside.map(function (c) { return candidate(c, config, function () { reload(); }); }))]));
      }
      if (!any && !(data.set_aside && data.set_aside.length)) {
        panel.appendChild(el('p', { class: 'aig-note-muted', text: 'No relevant record found among the AI uses you can open.' }));
      }
    }, config.subjectKind === 'request' ? null : 'Similar uses can be found once this use has an AI profile.');
    function reload() {
      var parent = box.parentNode;
      var next = A.precedentsPanel(document.createDocumentFragment(), config);
      parent.replaceChild(next, box);
      next.setAttribute('tabindex', '-1');
      next.focus();
    }
    return box;
  };

  function candidate(c, config, changed) {
    var head = [link(c.url, c.name), A.tierChip(c.tier, null)];
    c.reasons.forEach(function (r) { head.push(A.chip(r, 'info')); });
    if (!c.active) head.push(A.chip('Retired', 'muted'));
    var body = [el('div', { class: 'aig-hint', text: [c.owner ? 'Owner: ' + c.owner : 'No owner', c.business_unit || 'Whole organization',
      c.provider ? 'Provider: ' + c.provider : null, c.last_reviewed_at ? 'Last reviewed ' + c.last_reviewed_at : null].filter(Boolean).join('. ') + '.' })];
    if (c.decision) {
      body.push(el('div', { class: 'aig-hint', text: 'Its last signed decision: ' + c.decision.status.replace(/_/g, ' ')
        + (c.decision.decided_at ? ' on ' + c.decision.decided_at : '') + (c.decision.revoked ? ' (revoked)' : '')
        + '. That decision is about that use and does not apply to this one.' }));
    }
    if (c.evaluation) body.push(el('div', { class: 'aig-hint', text: 'Its latest evaluation: ' + c.evaluation.name + ', ' + c.evaluation.state + (c.evaluation.at ? ', ' + c.evaluation.at : '') + '.' }));
    if (c.differences && c.differences.length) {
      body.push(el('details', {}, [el('summary', { text: 'What differs (' + c.differences.length + ')' }),
        el('ul', {}, c.differences.map(function (d) { return el('li', { text: d.label + ': this one ' + d.this + '; that one ' + d.other }); }))]));
    }
    if (c.linked && c.linked.length) {
      body.push(el('div', { class: 'aig-hint' }, ['Linked records: '].concat(c.linked.map(function (l, i) {
        return el('span', {}, [i ? ', ' : '', link(l.url, l.title)]);
      }))));
    }
    if (c.verdict) body.push(el('div', { class: 'aig-hint', text: 'Marked ' + c.verdict.verdict.replace(/_/g, ' ') + ' by ' + (c.verdict.by || 'a specialist')
      + (c.verdict.note ? ': ' + c.verdict.note : '') }));
    if (config.canReview) {
      body.push(el('div', { class: 'aig-actions' }, [el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Say what it is',
        'aria-label': 'Say whether ' + c.name + ' is the same use', on: { click: function () { verdictDialog(c, config, changed); } } })]));
    }
    return el('li', {}, [el('div', {}, [el('div', { class: 'aig-meta' }, head)].concat(body))]);
  }

  function verdictDialog(c, config, changed) {
    A.dialog('Is ' + c.name + ' the same use?', function (box, close) {
      var verdict = A.select([{ id: 'same_use', name: 'The same use' }, { id: 'related', name: 'Related, not the same' },
        { id: 'not_related', name: 'Not related' }, { id: 'none', name: 'Take back my earlier answer' }], c.verdict ? c.verdict.verdict : 'related');
      var note = el('textarea', { rows: '3', maxlength: '500' });
      var out = el('div', { class: 'aig-say', role: 'status' });
      box.appendChild(el('p', { class: 'aig-muted', text: 'This records what you concluded. It links nothing, merges nothing and approves nothing.' }));
      box.appendChild(A.field('aigVerdict', 'What it is', verdict).row);
      box.appendChild(A.field('aigVerdictNote', 'Why (optional)', note).row);
      box.appendChild(el('div', { class: 'aig-actions' }, [
        el('button', { type: 'button', class: 'btn btn-primary', text: 'Save', on: { click: function () {
          A.say(out, 'Saving...');
          A.api('/ai-governance/api/precedents', 'PUT', { subject_kind: config.subjectKind, subject_id: config.subjectId,
            candidate_id: c.id, verdict: verdict.value === 'none' ? null : verdict.value, note: note.value }).then(function () {
            close(); changed();
          }).catch(function (err) { A.say(out, A.errorText(err), 'bad'); });
        } } }),
        el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
      box.appendChild(out);
    });
  }

  // ── Questions for the requester ───────────────────────────────────────────

  A.questionsPanel = function (host, config) {
    var base = '/ai-governance/api/requests/' + config.intakeId + '/questions';
    var box = el('section', { class: 'aig-panel', 'aria-label': 'Questions for the requester' });
    var body = el('div', {});
    var status = el('div', { class: 'aig-say', role: 'status' });
    box.appendChild(el('h2', { class: 'aig-h3', text: 'Questions for the requester' }));
    box.appendChild(status);
    box.appendChild(body);
    host.appendChild(box);

    function render(data) {
      A.clear(body);
      body.appendChild(el('p', { class: 'aig-hint', text: 'The requester has no account. Take the open questions out as text, send them the way your organization '
        + 'does, and record the answer here with where it came from.' }));
      if (!data.questions.length) body.appendChild(el('p', { class: 'aig-note-muted', text: 'No question has been asked.' }));
      body.appendChild(el('ul', { class: 'aig-list' }, data.questions.map(function (qn) {
        var lines = [el('div', { class: 'aig-meta' }, [el('strong', { text: qn.position + '. ' + qn.text }),
          A.chip({ open: 'Waiting for an answer', answered: 'Answered', withdrawn: 'Withdrawn' }[qn.status], { open: 'warn', answered: 'good', withdrawn: 'muted' }[qn.status])])];
        if (qn.answer) lines.push(el('div', { class: 'aig-hint', text: 'Answer: ' + qn.answer + ' (' + qn.answer_source + ', entered by ' + (qn.answered_by || 'a specialist') + ')' }));
        if (config.canAsk && qn.status === 'open') {
          lines.push(el('div', { class: 'aig-actions' }, [
            el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Record the answer', on: { click: function () { answerDialog(qn); } } }),
            el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Withdraw', on: { click: function () {
              A.api('/ai-governance/api/questions/' + qn.id + '/withdraw', 'POST', { version: qn.version }).then(refresh)
                .catch(function (err) { A.say(status, A.errorText(err), 'bad'); });
            } } })]));
        }
        return el('li', {}, [el('div', {}, lines)]);
      })));
      if (config.canAsk && data.can_ask) {
        var text = el('textarea', { rows: '3', maxlength: '2500' });
        body.appendChild(A.field('aigQuestions', 'Ask more (one question per line)', text,
          'Up to ' + data.limit + ' questions in all, each up to 500 characters.').row);
        var actions = [el('button', { type: 'button', class: 'btn btn-secondary', text: 'Add the questions', on: { click: function () {
          var lines = text.value.split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
          if (!lines.length) { A.say(status, 'Write at least one question.', 'bad'); return; }
          A.api(base, 'POST', { questions: lines }).then(function () { refresh(); }).catch(function (err) { A.say(status, A.errorText(err), 'bad'); });
        } } })];
        if (data.open) {
          actions.push(el('button', { type: 'button', class: 'btn btn-secondary', text: 'Take the open questions out as text', on: { click: exportDialog } }));
        }
        body.appendChild(el('div', { class: 'aig-actions' }, actions));
      }
    }

    function exportDialog() {
      A.api(base + '/export', 'POST', {}).then(function (done) {
        A.dialog('Questions to send', function (dialog, close) {
          var area = el('textarea', { rows: '10', readonly: 'readonly', 'aria-label': 'The questions as text' });
          area.value = done.text;
          dialog.appendChild(el('p', { class: 'aig-muted', text: 'Copy this into your email or message. Nothing has been sent from here.' }));
          dialog.appendChild(area);
          var out = el('div', { class: 'aig-say', role: 'status' });
          dialog.appendChild(el('div', { class: 'aig-actions' }, [
            el('button', { type: 'button', class: 'btn btn-primary', text: 'Copy', on: { click: function () {
              area.select();
              var done_ = global.navigator.clipboard && global.navigator.clipboard.writeText ? global.navigator.clipboard.writeText(area.value) : Promise.reject();
              done_.then(function () { A.say(out, 'Copied.', 'good'); }, function () { A.say(out, 'Select the text and copy it.', 'bad'); });
            } } }),
            el('button', { type: 'button', class: 'btn btn-ghost', text: 'Close', on: { click: close } })]));
          dialog.appendChild(out);
        });
      }).catch(function (err) { A.say(status, A.errorText(err), 'bad'); });
    }

    function answerDialog(qn) {
      A.dialog('Record the answer', function (dialog, close) {
        var answer = el('textarea', { rows: '4', maxlength: '2000' });
        var source = el('input', { type: 'text', maxlength: '120', placeholder: 'For example: email from the requester, 12 October' });
        var out = el('div', { class: 'aig-say', role: 'status' });
        dialog.appendChild(el('p', { class: 'aig-muted', text: qn.text }));
        dialog.appendChild(A.field('aigAnswer', 'The answer', answer).row);
        dialog.appendChild(A.field('aigAnswerSource', 'Where it came from', source).row);
        dialog.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: 'Save the answer', on: { click: function () {
            A.api('/ai-governance/api/questions/' + qn.id + '/answer', 'POST', { answer: answer.value, source: source.value, version: qn.version })
              .then(function () { close(); refresh(); }).catch(function (err) {
                var f = A.fieldErrors(err);
                A.say(out, A.errorText(err) + (f ? ' ' + Object.keys(f).map(function (k) { return f[k]; }).join(' ') : ''), 'bad');
              });
          } } }),
          el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
        dialog.appendChild(out);
      });
    }

    function refresh() {
      return A.api(base).then(function (data) { A.say(status, ''); render(data); })
        .catch(function (err) { A.say(status, A.errorText(err), 'bad'); });
    }
    A.say(status, 'Loading...');
    refresh();
    return box;
  };

  // ── The response to the requester ─────────────────────────────────────────

  var RESPONSE_STATUS = { draft: ['Draft', 'warn'], approved: ['Approved, not yet downloaded', 'info'], exported: ['Downloaded, not recorded as sent', 'info'],
    sent: ['Sent', 'good'], withdrawn: ['Withdrawn', 'muted'] };

  A.responsesPanel = function (host, config) {
    var base = '/ai-governance/api/systems/' + config.applicationId + '/responses';
    var box = el('section', { class: 'aig-panel', 'aria-label': 'Response to the requester' });
    var body = el('div', {});
    var status = el('div', { class: 'aig-say', role: 'status' });
    box.appendChild(el('h2', { class: 'aig-h3', text: 'Response to the requester' }));
    box.appendChild(el('p', { class: 'aig-hint', text: 'A short document that tells the requester the outcome. It is drafted from the signed decision, '
      + 'approved by someone other than the drafter, and sent by you. Downloading it is not sending it.' }));
    box.appendChild(status);
    box.appendChild(body);
    host.appendChild(box);

    function draft() {
      A.api(base, 'POST', {}).then(refresh).catch(function (err) { A.say(status, A.errorText(err), 'bad'); });
    }

    function render(data) {
      A.clear(body);
      var latest = data.responses[0];
      if (!latest || latest.status === 'withdrawn') {
        if (data.can_draft) {
          body.appendChild(el('button', { type: 'button', class: 'btn btn-primary', text: 'Draft a response', on: { click: draft } }));
        } else {
          body.appendChild(el('p', { class: 'aig-note-muted', text: 'A response can be drafted once a decision stands: approved, approved with conditions or not approved.' }));
        }
        if (latest) body.appendChild(el('p', { class: 'aig-hint', text: 'Revision ' + latest.revision + ' was withdrawn: ' + latest.withdraw_reason }));
        return;
      }
      var live = latest.stands;
      if (!live) {
        if (data.can_draft) {
          body.appendChild(el('p', { class: 'aig-note-warn', text: 'The decision this response rests on has been replaced, so it can no longer be approved '
            + 'or sent. Draft a new revision from the decision now in force.' }));
          body.appendChild(el('button', { type: 'button', class: 'btn btn-primary', text: 'Draft a new revision', on: { click: draft } }));
        } else {
          body.appendChild(el('p', { class: 'aig-note-warn', text: 'The decision this response rests on no longer stands (revoked, expired or '
            + 'changed), so it cannot be approved or sent.' }));
        }
      }
      var meta = RESPONSE_STATUS[latest.status] || [latest.status, 'muted'];
      body.appendChild(el('div', { class: 'aig-meta' }, [A.chip(meta[0], meta[1]), el('span', { class: 'aig-muted', text: 'Revision ' + latest.revision }),
        latest.frozen ? el('span', { class: 'aig-muted', text: 'Frozen: ' + latest.content_hash.slice(0, 12) }) : null]));
      var p = latest.preview;
      body.appendChild(el('dl', { class: 'aig-facts aig-facts-inline' }, [fact('Outcome', p.outcome.label), fact('Decision date', p.decision_date),
        fact('To review again by', p.review_due), fact('For', [p.requester.name, p.requester.organization].filter(Boolean).join(', ')),
        fact('Reference', p.source_reference), fact('Date of the response', p.response_date)]));
      if (p.conditions.length) {
        body.appendChild(el('h3', { class: 'aig-h3', text: 'Conditions, from the decision' }));
        body.appendChild(el('ul', {}, p.conditions.map(function (c) { return el('li', { text: c.text + (c.due_date ? ' (by ' + c.due_date + ')' : '') }); })));
      }
      if (latest.status === 'draft' && live) editor(latest);
      else {
        body.appendChild(el('h3', { class: 'aig-h3', text: 'Summary' }));
        body.appendChild(el('p', { text: p.summary || 'Not written' }));
        if (p.scope) body.appendChild(el('p', { class: 'aig-muted', text: 'Scope: ' + p.scope }));
        if (p.requester_actions.length) {
          body.appendChild(el('h3', { class: 'aig-h3', text: 'What the requester needs to do' }));
          body.appendChild(el('ul', {}, p.requester_actions.map(function (a) { return el('li', { text: a }); })));
        }
      }
      body.appendChild(el('p', { class: 'aig-hint', text: p.limitations }));
      var trail = [];
      if (latest.drafted_by) trail.push('Drafted by ' + latest.drafted_by);
      if (latest.approved_by) trail.push('approved by ' + latest.approved_by + ' on ' + A.date(latest.approved_at));
      if (latest.exported_at) trail.push('downloaded ' + latest.export_count + ' time(s), last on ' + A.date(latest.exported_at));
      if (latest.sent_at) trail.push('recorded as sent on ' + latest.sent_at + ' by ' + latest.sent_channel + (latest.sent_reference ? ' (' + latest.sent_reference + ')' : ''));
      if (trail.length) body.appendChild(el('p', { class: 'aig-muted', text: trail.join('; ') + '.' }));
      actions(latest, data, live);
    }

    function fact(label, value) {
      return el('div', { class: 'aig-fact' }, [el('dt', { text: label }), el('dd', { text: value || 'Not set' })]);
    }

    function editor(latest) {
      var summary = el('textarea', { rows: '5', maxlength: '2000' });
      summary.value = latest.summary || '';
      var scope = el('textarea', { rows: '2', maxlength: '1000' });
      scope.value = latest.scope || '';
      var actionsBox = el('textarea', { rows: '3', maxlength: '3000' });
      actionsBox.value = (latest.requester_actions || []).join('\n');
      var date = el('input', { type: 'date' });
      date.value = latest.response_date || '';
      var due = el('input', { type: 'date' });
      due.value = latest.review_due || '';
      var out = el('div', { class: 'aig-say', role: 'status' });
      body.appendChild(A.field('aigRespSummary', 'Summary for the requester', summary,
        'What was decided and why it matters to them, in plain words. No internal names or scores.').row);
      body.appendChild(A.field('aigRespScope', 'Scope of the outcome', scope).row);
      body.appendChild(A.field('aigRespActions', 'What the requester needs to do (one per line)', actionsBox).row);
      body.appendChild(A.field('aigRespDate', 'Date of the response', date).row);
      body.appendChild(A.field('aigRespDue', 'To review again by', due).row);
      body.appendChild(el('div', { class: 'aig-actions' }, [el('button', { type: 'button', class: 'btn btn-secondary', text: 'Save the draft', on: { click: function () {
        A.say(out, 'Saving...');
        A.api('/ai-governance/api/responses/' + latest.id, 'PUT', { version: latest.version, fields: {
          summary: summary.value, scope: scope.value, response_date: date.value, review_due: due.value,
          requester_actions: actionsBox.value.split('\n').map(function (s) { return s.trim(); }).filter(Boolean) } })
          .then(refresh).catch(function (err) {
            var f = A.fieldErrors(err);
            A.say(out, A.errorText(err) + (f ? ' ' + Object.keys(f).map(function (k) { return f[k]; }).join(' ') : ''), 'bad');
          });
      } } })]));
      body.appendChild(out);
    }

    function download(latest, format) {
      global.ApiClient.request('/ai-governance/api/responses/' + latest.id + '/export', { method: 'POST', body: { format: format }, expect: 'blob' })
        .then(function (file) {
          var url = global.URL.createObjectURL(file.blob);
          var anchor = el('a', { href: url, download: file.filename || ('response.' + format) });
          document.body.appendChild(anchor);
          anchor.click();
          document.body.removeChild(anchor);
          global.setTimeout(function () { global.URL.revokeObjectURL(url); }, 1000);
          refresh();
        }).catch(function (err) { A.say(status, A.errorText(err), 'bad'); });
    }

    function actions(latest, data, live) {
      var row = [];
      if (latest.status === 'draft' && data.can.approve && live) {
        row.push(el('button', { type: 'button', class: 'btn btn-primary', text: 'Approve for sending', on: { click: function () {
          A.api('/ai-governance/api/responses/' + latest.id + '/approve', 'POST', { version: latest.version }).then(refresh)
            .catch(function (err) { A.say(status, A.errorText(err), 'bad'); });
        } } }));
      }
      if (['approved', 'exported', 'sent'].indexOf(latest.status) >= 0 && live) {
        row.push(el('button', { type: 'button', class: 'btn btn-primary', text: 'Download PDF', on: { click: function () { download(latest, 'pdf'); } } }));
        row.push(el('button', { type: 'button', class: 'btn btn-secondary', text: 'Download JSON', on: { click: function () { download(latest, 'json'); } } }));
      }
      if (latest.status === 'exported') {
        row.push(el('button', { type: 'button', class: 'btn btn-secondary', text: 'Record that it was sent', on: { click: function () { sentDialog(latest); } } }));
      }
      row.push(el('button', { type: 'button', class: 'btn btn-ghost', text: 'Withdraw', on: { click: function () { withdrawDialog(latest); } } }));
      body.appendChild(el('div', { class: 'aig-actions' }, row));
    }

    function sentDialog(latest) {
      A.dialog('Record that the response was sent', function (dialog, close) {
        var date = el('input', { type: 'date' });
        var channel = el('input', { type: 'text', maxlength: '80', placeholder: 'For example: email to the requester' });
        var reference = el('input', { type: 'text', maxlength: '120' });
        var out = el('div', { class: 'aig-say', role: 'status' });
        dialog.appendChild(el('p', { class: 'aig-muted', text: 'Only you can say it was sent. ThemisIQ does not send it and a download is not a delivery.' }));
        dialog.appendChild(A.field('aigSentDate', 'Date sent', date).row);
        dialog.appendChild(A.field('aigSentChannel', 'Channel', channel).row);
        dialog.appendChild(A.field('aigSentRef', 'Reference (optional)', reference).row);
        dialog.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: 'Record it', on: { click: function () {
            A.api('/ai-governance/api/responses/' + latest.id + '/sent', 'POST', { version: latest.version, sent_at: date.value,
              channel: channel.value, reference: reference.value }).then(function () { close(); refresh(); }).catch(function (err) {
              var f = A.fieldErrors(err);
              A.say(out, A.errorText(err) + (f ? ' ' + Object.keys(f).map(function (k) { return f[k]; }).join(' ') : ''), 'bad');
            });
          } } }),
          el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
        dialog.appendChild(out);
      });
    }

    function withdrawDialog(latest) {
      A.dialog('Withdraw this response', function (dialog, close) {
        var reason = el('textarea', { rows: '3', maxlength: '500' });
        var out = el('div', { class: 'aig-say', role: 'status' });
        dialog.appendChild(A.field('aigWithdrawReason', 'Why', reason).row);
        dialog.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: 'Withdraw', on: { click: function () {
            A.api('/ai-governance/api/responses/' + latest.id + '/withdraw', 'POST', { version: latest.version, reason: reason.value })
              .then(function () { close(); refresh(); }).catch(function (err) { A.say(out, A.errorText(err), 'bad'); });
          } } }),
          el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
        dialog.appendChild(out);
      });
    }

    function refresh() {
      return A.api(base).then(function (data) { A.say(status, ''); render(data); })
        .catch(function (err) { A.say(status, A.errorText(err), 'bad'); });
    }
    A.say(status, 'Loading...');
    refresh();
    return box;
  };
}(window));
