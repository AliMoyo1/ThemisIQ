/* Official-source watch and extractive Ask Sentinel. No legal text enters HTML. */
(function () {
  'use strict';
  var root = document.getElementById('snLawMonitor');
  if (!root || !window.ApiClient) return;
  var schedule = document.getElementById('snLawSchedule');
  var sources = document.getElementById('snLawSources');
  var review = document.getElementById('snLawReview');
  var askForm = document.getElementById('snAskLawForm');
  var jurisdictionPicker = document.getElementById('snAskLawJurisdiction');
  var answer = document.getElementById('snAskLawAnswer');
  var canManage = root.dataset.canManage === 'true';
  var canApprove = root.dataset.canApprove === 'true';

  function el(tag, text, className) {
    var node = document.createElement(tag);
    if (text != null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }
  function clear(node) { node.replaceChildren(); }
  function req(url, method, body) {
    return window.ApiClient.request(url, { method: method || 'GET', body: body, actionId: url });
  }
  function failure(node, error) {
    node.textContent = (error && error.message) || 'The source check failed. Retry or ask an administrator.';
  }

  async function load() {
    sources.textContent = 'Loading official sources…';
    try {
      var data = await req('/sentinel/api/law-monitor');
      clear(schedule); clear(sources); clear(review); clear(jurisdictionPicker);
      jurisdictionPicker.appendChild(el('option', 'All active jurisdictions'));
      jurisdictionPicker.firstChild.value = '';
      var select = el('select');
      select.setAttribute('aria-label', 'Source check interval');
      [['24h', 'Every 24 hours'], ['weekly', 'Weekly'], ['monthly', 'Every 30 days']].forEach(function (entry) {
        var option = el('option', entry[1]); option.value = entry[0];
        select.appendChild(option);
      });
      select.value = data.cadence;
      if (canManage) {
        var label = el('label', 'Check official sites: ');
        label.appendChild(select);
        schedule.appendChild(label);
        var save = el('button', 'Save schedule', 'btn btn-secondary');
        save.type = 'button';
        save.addEventListener('click', async function () {
          save.disabled = true;
          try { await req('/sentinel/api/law-monitor/cadence', 'PUT', {cadence: select.value});
            await load();
          } catch (error) { failure(review, error); } finally { save.disabled = false; }
        });
        schedule.appendChild(save);
      } else {
        schedule.appendChild(el('span', 'Official sites checked ' + select.selectedOptions[0].textContent.toLowerCase() + '.'));
      }
      schedule.appendChild(el('p', data.cost_note || '', 'muted'));
      var retention = el('p', 'Review captured source copies after ' + data.retention_days +
        ' days. Legal holds remain in place. This setting marks copies for review; it never deletes them automatically.');
      schedule.appendChild(retention);
      if (canApprove) {
        var days = el('input'); days.type = 'number'; days.min = '30'; days.max = '3650';
        days.value = data.retention_days; days.setAttribute('aria-label', 'Source capture retention review days');
        var saveRetention = el('button', 'Save review period', 'btn btn-secondary');
        saveRetention.type = 'button';
        saveRetention.addEventListener('click', async function () {
          saveRetention.disabled = true;
          try { await req('/sentinel/api/law-monitor/retention', 'PUT', {days: Number(days.value)}); await load(); }
          catch (error) { failure(review, error); } finally { saveRetention.disabled = false; }
        });
        schedule.appendChild(days); schedule.appendChild(saveRetention);
      }
      var names = new Set();
      (data.sources || []).forEach(function (source) {
        if (!names.has(source.jurisdiction)) {
          names.add(source.jurisdiction);
          var option = el('option', source.jurisdiction);
          option.value = source.jurisdiction;
          jurisdictionPicker.appendChild(option);
        }
        var card = el('div', null, 'card');
        card.style.margin = '10px 0'; card.style.padding = '14px';
        card.appendChild(el('strong', source.jurisdiction + ' · ' + source.title + ' · ' + source.source_type));
        var link = el('a', ' Open authority source ↗');
        link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        card.appendChild(link);
        var last = source.latest_capture;
        card.appendChild(el('p', 'Last check: ' + (source.last_checked_at || 'not yet checked') +
          ' · ' + (source.last_result || 'awaiting first capture') +
          ' · ' + (last ? 'capture ' + last.id + ' (' + last.review_state + ')' : 'no capture')));
        if (source.last_error) card.appendChild(el('p', 'Check failed: ' + source.last_error));
        if (canManage) {
          var check = el('button', 'Check now', 'btn btn-secondary'); check.type = 'button';
          check.addEventListener('click', async function () {
            check.disabled = true; review.textContent = 'Checking pinned authority page…';
            try { await req('/sentinel/api/law-monitor/check', 'POST', {source_key: source.key}); await load(); }
            catch (error) { failure(review, error); } finally { check.disabled = false; }
          });
          card.appendChild(check);
        }
        if (last) {
          var inspect = el('button', 'Proof & change', 'btn btn-secondary'); inspect.type = 'button';
          inspect.addEventListener('click', function () { showCapture(last.id); });
          card.appendChild(inspect);
        }
        if (source.approved_capture && (!last || source.approved_capture.id !== last.id)) {
          var older = el('button', 'Last approved capture', 'btn btn-secondary'); older.type = 'button';
          older.addEventListener('click', function () { showCapture(source.approved_capture.id); });
          card.appendChild(older);
        }
        if ((source.recent_captures || []).length > 1) {
          var history = el('div'); history.style.marginTop = '8px';
          history.appendChild(el('small', 'Recent captured versions: '));
          source.recent_captures.forEach(function (capture) {
            var version = el('button', '#' + capture.id + ' ' + capture.review_state, 'btn btn-secondary');
            version.type = 'button'; version.addEventListener('click', function () { showCapture(capture.id); });
            history.appendChild(version);
          });
          card.appendChild(history);
        }
        sources.appendChild(card);
      });
      if (!(data.sources || []).length) sources.appendChild(el('p', 'No pinned official source for the active jurisdictions yet. Ask Sentinel will abstain.'));
      if ((data.uncovered || []).length) {
        sources.appendChild(el('p', 'No verified monitored source yet: ' + data.uncovered.join(', ') + '. Add one after source review.'));
        data.uncovered.forEach(function (jurisdiction) {
          var option = el('option', jurisdiction);
          option.value = jurisdiction;
          jurisdictionPicker.appendChild(option);
        });
      }
    } catch (error) { failure(sources, error); }
  }

  async function showCapture(id) {
    review.textContent = 'Verifying stored capture…';
    try {
      var item = await req('/sentinel/api/law-monitor/captures/' + id);
      clear(review);
      var panel = el('div', null, 'card');
      panel.style.marginTop = '12px'; panel.style.padding = '16px';
      panel.appendChild(el('strong', 'Capture ' + item.id + ' · ' + item.jurisdiction_key));
      panel.appendChild(el('p', item.proof));
      if (item.hash_verified) {
        var sourceLink = el('a', 'Open pinned authority page ↗');
        sourceLink.href = item.source_url; sourceLink.target = '_blank'; sourceLink.rel = 'noopener noreferrer';
        panel.appendChild(sourceLink);
      }
      panel.appendChild(el('p', 'Captured ' + item.captured_at + ' · SHA-256 ' + item.raw_sha256));
      panel.appendChild(el('small', 'Extracted-text SHA-256 ' + item.text_sha256));
      panel.appendChild(el('p', 'Stored-byte integrity: ' + (item.hash_verified ? 'verified' : 'FAILED')));
      panel.appendChild(el('p', 'Review: ' + item.review_state +
        (item.review_note ? ' · ' + item.review_note : '')));
      if (item.review_overdue) panel.appendChild(el('p', 'Review overdue: this change has been waiting for more than seven days.'));
      if (item.retention_review_due) panel.appendChild(el('p', 'Retention review due. Check the approved schedule and any legal hold before disposition.'));
      panel.appendChild(el('p', item.legal_hold ? 'Legal hold active: ' + item.hold_reason : 'No legal hold recorded.'));
      var diff = el('pre', item.change_excerpt || 'No textual difference recorded.');
      diff.style.whiteSpace = 'pre-wrap'; diff.style.maxHeight = '260px'; diff.style.overflow = 'auto';
      panel.appendChild(diff);
      var snapshot = el('details');
      snapshot.appendChild(el('summary', 'View complete captured text'));
      var capturedText = el('pre', item.captured_text || 'No captured text available.');
      capturedText.style.whiteSpace = 'pre-wrap'; capturedText.style.maxHeight = '360px';
      capturedText.style.overflow = 'auto';
      snapshot.appendChild(capturedText); panel.appendChild(snapshot);
      var impact = el('div', 'Checking connected records in your scope…');
      panel.appendChild(impact);
      req('/sentinel/api/law-monitor/captures/' + id + '/impact').then(function (summary) {
        clear(impact);
        impact.appendChild(el('strong', 'Connected review preview · ' + summary.jurisdiction));
        impact.appendChild(el('p', summary.action));
        var paths = {RoPA: '/sentinel/ropa', DPIA: '/sentinel/dpia', Breach: '/sentinel/breaches', DSR: '/sentinel/dsr'};
        Object.keys(summary.records_in_your_scope || {}).forEach(function (kind) {
          var link = el('a', kind + ': ' + summary.records_in_your_scope[kind] + ' visible records');
          link.href = paths[kind]; link.style.marginRight = '12px'; impact.appendChild(link);
        });
        impact.appendChild(el('p', 'Versioned rule cards: ' + summary.rule_cards));
      }).catch(function (error) { failure(impact, error); });
      if (canApprove) {
        var holdReason = el('input'); holdReason.type = 'text'; holdReason.maxLength = 1000;
        holdReason.placeholder = 'Reason for placing or releasing a hold';
        holdReason.setAttribute('aria-label', 'Legal hold reason');
        var holdButton = el('button', item.legal_hold ? 'Release legal hold' : 'Place legal hold', 'btn btn-secondary');
        holdButton.type = 'button';
        holdButton.addEventListener('click', async function () {
          holdButton.disabled = true;
          try { await req('/sentinel/api/law-monitor/captures/' + id + '/hold', 'POST',
            {enabled: !item.legal_hold, reason: holdReason.value}); await showCapture(id); }
          catch (error) { failure(review, error); } finally { holdButton.disabled = false; }
        });
        panel.appendChild(holdReason); panel.appendChild(holdButton);
      }
      if (canApprove && item.review_state === 'pending' && item.hash_verified && item.is_latest) {
        var note = el('textarea'); note.placeholder = 'Review reason and legal significance';
        note.setAttribute('aria-label', 'Review reason and legal significance');
        note.maxLength = 2000; note.style.width = '100%';
        panel.appendChild(note);
        ['approved', 'rejected'].forEach(function (decision) {
          var button = el('button', decision === 'approved' ? 'Approve for retrieval' : 'Reject capture', 'btn btn-secondary');
          button.type = 'button';
          button.addEventListener('click', async function () {
            button.disabled = true;
            try { await req('/sentinel/api/law-monitor/captures/' + id + '/review', 'POST',
              {decision: decision, note: note.value}); await load(); }
            catch (error) { failure(review, error); } finally { button.disabled = false; }
          });
          panel.appendChild(button);
        });
      }
      review.appendChild(panel);
    } catch (error) { failure(review, error); }
  }

  askForm.addEventListener('submit', async function (event) {
    event.preventDefault(); answer.textContent = 'Searching approved authority captures…';
    try {
      var result = await req('/sentinel/api/ask-law', 'POST', {
        question: document.getElementById('snAskLawQuestion').value,
        jurisdiction: jurisdictionPicker.value || null,
        ai_draft: !!(document.getElementById('snAskLawAiDraft') &&
          document.getElementById('snAskLawAiDraft').checked)
      });
      clear(answer); answer.appendChild(el('p', result.answer));
      if (result.mode) answer.appendChild(el('strong', result.mode + ' · verify every claim against the source.'));
      if (result.draft_status) answer.appendChild(el('p', result.draft_status));
      (result.citations || []).forEach(function (citation, index) {
        var card = el('div', null, 'card');
        card.style.margin = '10px 0'; card.style.padding = '14px';
        card.appendChild(el('strong', '[' + (index + 1) + '] ' + citation.jurisdiction +
          ' · capture ' + citation.capture_id + ', line ' + citation.excerpt_line + ' · ' + citation.captured_at));
        card.appendChild(el('p', citation.excerpt));
        if (citation.newer_unapproved_capture_exists) {
          card.appendChild(el('p', 'A newer source capture is not approved for retrieval. This passage may be superseded.'));
        }
        var link = el('a', 'Read official source ↗');
        link.href = citation.source_url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        card.appendChild(link);
        card.appendChild(el('small', ' · SHA-256 ' + citation.sha256));
        answer.appendChild(card);
      });
    } catch (error) { failure(answer, error); }
  });
  window.snLivingLawRefresh = load;
  if (document.getElementById('view-jurisdictions').classList.contains('active')) load();
})();
