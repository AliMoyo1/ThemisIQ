/* Pinned authority sources and extractive Ask Sentinel. Captured text stays inert. */
(function () {
  'use strict';
  var root = document.getElementById('snLawMonitor');
  if (!root || !window.ApiClient) return;
  var schedule = document.getElementById('snLawSchedule');
  var sources = document.getElementById('snLawSources');
  var review = document.getElementById('snLawReview');
  var announcement = document.getElementById('snWatchAnnouncement');
  var inspector = document.getElementById('snWatchInspector');
  var workspace = inspector.parentElement;
  var inspectorTitle = document.getElementById('snInspectorTitle');
  var inspectorClose = document.getElementById('snInspectorClose');
  var backdrop = document.getElementById('snWatchBackdrop');
  var sourceSearch = document.getElementById('snSourceSearch');
  var sourceFilter = document.getElementById('snSourceFilter');
  var sourceCount = document.getElementById('snSourceCount');
  var askForm = document.getElementById('snAskLawForm');
  var jurisdictionPicker = document.getElementById('snAskLawJurisdiction');
  var answer = document.getElementById('snAskLawAnswer');
  var canManage = root.dataset.canManage === 'true';
  var canApprove = root.dataset.canApprove === 'true';
  var canPropose = root.dataset.canPropose === 'true';
  var smallScreen = window.matchMedia('(max-width: 900px)');
  var sourceItems = [];
  var uncovered = [];
  var selectedKey = null;
  var selectedCaptureId = null;
  var activeSourceButton = null;
  var checkFeedback = new Map();
  var checkingKeys = new Set();
  var listRequest = 0;
  var detailRequest = 0;

  function el(tag, text, className) {
    var node = document.createElement(tag);
    if (text != null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }
  function clear(node) { node.replaceChildren(); }
  function req(url, method, body) {
    return window.ApiClient.request(url, {method: method || 'GET', body: body, actionId: url});
  }
  function failure(node, error) {
    node.textContent = (error && error.message) || 'The request failed. Retry or ask an administrator.';
  }
  function parseUtc(value) {
    if (!value) return null;
    var text = String(value);
    if (/^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(text) && !/(Z|[+-]\d\d:?\d\d)$/i.test(text)) text += 'Z';
    var date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  function shortWhen(value) {
    var date = parseUtc(value);
    return date ? date.toLocaleString('en-GB', {dateStyle: 'medium', timeStyle: 'short'}) : 'Not yet checked';
  }
  function officialUrl(value) {
    try {
      var url = new URL(String(value));
      return url.protocol === 'https:' && !url.username && !url.password ? url.href : '';
    } catch (_) { return ''; }
  }
  function currentSource() { return sourceItems.find(function (item) { return item.key === selectedKey; }); }
  function sourceState(source) {
    if (source.last_result === 'error') return 'failed';
    if (source.latest_capture && source.latest_capture.review_state === 'pending') return 'review';
    if (!source.last_checked_at) return 'unchecked';
    return 'current';
  }
  function stateLabel(state) {
    return {failed: 'Check failed', review: 'Needs review', unchecked: 'Not checked', current: 'Checked'}[state];
  }
  function nextCheck(source) {
    var date = parseUtc(source.last_checked_at);
    return date && date.getTime() + 3600000 > Date.now() ? new Date(date.getTime() + 3600000) : null;
  }
  function button(label, onClick, className) {
    var node = el('button', label, className || 'btn btn-secondary');
    node.type = 'button'; node.addEventListener('click', onClick);
    return node;
  }
  function sourceLink(url, label) {
    var href = officialUrl(url);
    if (!href) return null;
    var link = el('a', label || 'Open authority source ↗', 'sn-source-link');
    link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer';
    return link;
  }
  function openInspector(opener) {
    if (!smallScreen.matches) return;
    activeSourceButton = opener || activeSourceButton;
    if (inspector.parentElement !== document.body) {
      document.body.appendChild(backdrop);
      document.body.appendChild(inspector);
    }
    inspector.classList.add('open');
    inspector.setAttribute('role', 'dialog'); inspector.setAttribute('aria-modal', 'true');
    inspector.removeAttribute('aria-hidden');
    backdrop.hidden = false;
    inspectorClose.focus();
  }
  function closeInspector() {
    inspector.classList.remove('open');
    inspector.removeAttribute('role'); inspector.removeAttribute('aria-modal');
    if (smallScreen.matches) inspector.setAttribute('aria-hidden', 'true');
    backdrop.hidden = true;
    (activeSourceButton && activeSourceButton.isConnected ? activeSourceButton : sourceSearch).focus();
    if (inspector.parentElement === document.body) {
      workspace.appendChild(backdrop);
      workspace.appendChild(inspector);
    }
  }
  inspectorClose.addEventListener('click', closeInspector);
  backdrop.addEventListener('click', closeInspector);
  inspector.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && smallScreen.matches) { event.preventDefault(); closeInspector(); }
    if (event.key !== 'Tab' || !smallScreen.matches) return;
    var focusable = Array.from(inspector.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),textarea:not([disabled]),summary'));
    if (!focusable.length) return;
    var first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  smallScreen.addEventListener('change', function () {
    if (!smallScreen.matches) { closeInspector(); inspector.removeAttribute('aria-hidden'); }
    else if (!inspector.classList.contains('open')) inspector.setAttribute('aria-hidden', 'true');
  });
  if (smallScreen.matches) inspector.setAttribute('aria-hidden', 'true');

  function renderSchedule(data) {
    clear(schedule);
    var select = el('select'); select.className = 'form-input';
    select.setAttribute('aria-label', 'Source check interval');
    [['24h', 'Every 24 hours'], ['weekly', 'Weekly'], ['monthly', 'Every 30 days']].forEach(function (entry) {
      var option = el('option', entry[1]); option.value = entry[0]; select.appendChild(option);
    });
    select.value = data.cadence;
    var toolbar = el('div', null, 'sn-schedule-toolbar');
    if (canManage) {
      var label = el('label', 'Check official sites'); label.appendChild(select); toolbar.appendChild(label);
      var save = button('Save schedule', async function () {
        save.disabled = true;
        try { await req('/sentinel/api/law-monitor/cadence', 'PUT', {cadence: select.value}); await load(); }
        catch (error) { failure(settingsStatus, error); }
        finally { save.disabled = false; }
      });
      toolbar.appendChild(save);
    } else {
      toolbar.appendChild(el('span', 'Official sites checked ' + select.selectedOptions[0].textContent.toLowerCase() + '.'));
    }
    schedule.appendChild(toolbar);
    var notes = el('div', null, 'sn-schedule-notes');
    notes.appendChild(el('p', data.cost_note || ''));
    notes.appendChild(el('p', 'Review captured source copies after ' + data.retention_days +
      ' days. Legal holds remain in place. This setting marks copies for review; it never deletes them automatically.'));
    schedule.appendChild(notes);
    var settingsStatus = el('p', null, 'sn-schedule-notes');
    if (canApprove) {
      var controls = el('div', null, 'sn-retention-controls');
      var days = el('input'); days.type = 'number'; days.min = '30'; days.max = '3650';
      days.value = data.retention_days; days.setAttribute('aria-label', 'Source capture retention review days');
      var saveRetention = button('Save review period', async function () {
        saveRetention.disabled = true;
        try { await req('/sentinel/api/law-monitor/retention', 'PUT', {days: Number(days.value)}); await load(); }
        catch (error) { failure(settingsStatus, error); }
        finally { saveRetention.disabled = false; }
      });
      controls.appendChild(days); controls.appendChild(saveRetention); schedule.appendChild(controls);
    }
    settingsStatus.setAttribute('role', 'status'); schedule.appendChild(settingsStatus);
  }

  function renderSources() {
    clear(sources);
    var query = sourceSearch.value.trim().toLocaleLowerCase();
    var state = sourceFilter.value;
    var visible = sourceItems.filter(function (source) {
      var matchesState = state === 'all' || sourceState(source) === state ||
        (state === 'review' && source.latest_capture && source.latest_capture.review_state === 'pending');
      return matchesState &&
        (!query || (source.jurisdiction + ' ' + source.title + ' ' + source.source_type).toLocaleLowerCase().includes(query));
    });
    sourceCount.textContent = visible.length + ' of ' + sourceItems.length;
    visible.forEach(function (source) {
      var row = el('article', null, 'sn-watch-source' + (source.key === selectedKey ? ' selected' : ''));
      var select = button('', function () { selectSource(source.key, select); }, 'sn-source-select');
      select.setAttribute('aria-label', 'View result for ' + source.jurisdiction + ': ' + source.title);
      select.setAttribute('aria-pressed', String(source.key === selectedKey));
      select.appendChild(el('span', source.jurisdiction, 'sn-entry-eyebrow'));
      select.appendChild(el('strong', source.title));
      select.appendChild(el('small', source.source_type));
      row.appendChild(select);
      var bottom = el('div', null, 'sn-source-row-bottom');
      var status = sourceState(source);
      var label = status === 'current' && source.latest_capture && source.latest_capture.review_state === 'approved'
        ? 'Approved capture' : stateLabel(status);
      bottom.appendChild(el('span', checkingKeys.has(source.key) ? 'Checking…' : label,
        'sn-status-pill ' + (status === 'review' ? 'pending' : status === 'failed' ? 'rejected' : '')));
      if (status === 'failed' && source.latest_capture && source.latest_capture.review_state === 'pending') {
        bottom.appendChild(el('span', 'Review pending', 'sn-status-pill pending'));
      }
      if (canManage) {
        var available = nextCheck(source);
        var check = button(checkingKeys.has(source.key) ? 'Checking…' : 'Check now', function () {
          checkSource(source.key, check);
        }, 'btn btn-secondary');
        check.disabled = checkingKeys.has(source.key) || !!available;
        if (available) check.title = 'Next manual check after ' + shortWhen(available.toISOString());
        bottom.appendChild(check);
      }
      row.appendChild(bottom); sources.appendChild(row);
      if (source.key === selectedKey) activeSourceButton = select;
    });
    if (!sourceItems.length) sources.appendChild(el('p', 'No pinned official source for the active jurisdictions yet. Ask Sentinel will abstain.', 'sn-empty-state'));
    else if (!visible.length) sources.appendChild(el('p', 'No sources match these filters.', 'sn-empty-state'));
    if (uncovered.length && state === 'all' && !query) {
      sources.appendChild(el('p', 'No verified monitored source yet: ' + uncovered.join(', ') + '. Add one after source review.', 'sn-empty-state'));
    }
  }
  sourceSearch.addEventListener('input', renderSources);
  sourceFilter.addEventListener('change', renderSources);
  function selectSource(key, opener) {
    if (!sourceItems.some(function (source) { return source.key === key; })) return;
    selectedKey = key; selectedCaptureId = null;
    inspector.scrollTop = 0;
    renderSources(); renderInspector(); openInspector(activeSourceButton || opener);
  }

  function resultText(source, feedback) {
    if (checkingKeys.has(source.key)) return ['Checking official source…', 'The result will appear here when the check completes.', ''];
    if (feedback && feedback.result === 'request_error') return ['Check could not start', feedback.error, 'failed'];
    if (feedback && feedback.result === 'error') return ['Source check failed', feedback.error || source.last_error || 'The source could not be safely captured.', 'failed'];
    if (feedback && feedback.result === 'unchanged') return ['No textual change detected', 'The checked text matched the last capture. No new version was stored.', ''];
    if (feedback && feedback.result === 'baseline_pending_review') return ['First capture needs review', 'A new baseline was stored. A DPO must review it before Ask Sentinel can retrieve it.', 'pending'];
    if (feedback && feedback.result === 'change_pending_review') return ['Changed text needs review', 'A new version was stored. This does not amend a law, rule card or operational deadline.', 'pending'];
    var state = sourceState(source);
    if (state === 'failed') return ['Last check failed', source.last_error || 'The source could not be safely captured. Do not infer that it is unchanged.', 'failed'];
    if (state === 'review') return ['Capture awaiting review', 'The captured version needs a DPO decision before it can be used for source retrieval.', 'pending'];
    if (state === 'unchecked') return ['No check yet', 'Run a check to capture the pinned authority source.', ''];
    if (source.last_result === 'unchanged') return ['No textual change on last check', 'The checked text matched the last capture. No new version was stored.', ''];
    if (source.latest_capture && source.latest_capture.review_state === 'approved') return ['Capture approved for retrieval', 'A DPO approved this captured version for Ask Sentinel retrieval.', ''];
    if (source.latest_capture && source.latest_capture.review_state === 'rejected') return ['Capture rejected', 'The captured version is not available to Ask Sentinel.', ''];
    return ['Last source check recorded', 'Review the capture and its approval state below.', ''];
  }

  function renderInspector() {
    var token = ++detailRequest;
    var source = currentSource();
    clear(review);
    inspectorTitle.textContent = source ? source.title : 'Source result';
    if (!source) {
      announcement.textContent = '';
      review.appendChild(el('p', 'Select a pinned source to see its check result and proof.', 'sn-empty-state'));
      return;
    }
    var context = el('div', source.jurisdiction + ' · ' + source.source_type, 'sn-inspector-source');
    review.appendChild(context);
    var feedback = checkFeedback.get(source.key);
    var result = resultText(source, feedback);
    announcement.textContent = result[0] + '. ' + result[1];
    var status = el('div', null, 'sn-inspector-state ' + result[2]);
    status.appendChild(el('strong', result[0])); status.appendChild(el('p', result[1]));
    review.appendChild(status);
    var meta = el('div', null, 'sn-inspector-meta');
    meta.appendChild(el('span', 'Last check: ' + shortWhen(source.last_checked_at)));
    if (source.latest_capture) meta.appendChild(el('span', 'Latest capture #' + source.latest_capture.id + ' · ' + source.latest_capture.review_state));
    if (source.approved_capture) meta.appendChild(el('span', 'Approved for retrieval: #' + source.approved_capture.id));
    review.appendChild(meta);
    var actions = el('div', null, 'sn-inspector-actions');
    var link = sourceLink(source.url); if (link) actions.appendChild(link);
    var available = nextCheck(source);
    if (canManage) {
      var check = button(checkingKeys.has(source.key) ? 'Checking…' : 'Check now', function () { checkSource(source.key, check); });
      check.disabled = checkingKeys.has(source.key) || !!available;
      actions.appendChild(check);
      if (available) actions.appendChild(el('span', 'Next manual check after ' + shortWhen(available.toISOString()), 'sn-entry-kind'));
    }
    review.appendChild(actions);
    if ((source.recent_captures || []).length) {
      var versions = el('div', null, 'sn-source-history');
      versions.appendChild(el('span', 'Captured versions'));
      source.recent_captures.forEach(function (capture) {
        versions.appendChild(button('#' + capture.id + ' · ' + capture.review_state, function () {
          selectedCaptureId = capture.id; renderInspector();
        }));
      });
      if (source.approved_capture && !source.recent_captures.some(function (capture) { return capture.id === source.approved_capture.id; })) {
        versions.appendChild(button('Last approved #' + source.approved_capture.id, function () {
          selectedCaptureId = source.approved_capture.id; renderInspector();
        }));
      }
      review.appendChild(versions);
    }
    var captureId = selectedCaptureId || (source.latest_capture && source.latest_capture.id);
    if (captureId) {
      var detail = el('div', 'Verifying stored capture…', 'sn-inspector-detail');
      review.appendChild(detail);
      loadCapture(source.key, captureId, token, detail);
    }
  }

  async function checkSource(key, opener) {
    var source = sourceItems.find(function (item) { return item.key === key; });
    if (!source || checkingKeys.has(key)) return;
    selectedKey = key; selectedCaptureId = null;
    inspector.scrollTop = 0;
    checkingKeys.add(key); checkFeedback.delete(key);
    renderSources(); renderInspector(); openInspector(activeSourceButton || opener);
    try {
      var result = await req('/sentinel/api/law-monitor/check', 'POST', {source_key: key});
      checkFeedback.set(key, result);
      if (selectedKey === key && result.capture_id) selectedCaptureId = result.capture_id;
    } catch (error) {
      checkFeedback.set(key, {result: 'request_error', error: (error && error.message) || 'The check could not start.'});
    } finally {
      checkingKeys.delete(key);
      if (!await load()) renderInspector();
    }
  }

  async function load() {
    var requestId = ++listRequest;
    if (!sourceItems.length) sources.textContent = 'Loading official sources…';
    try {
      var data = await req('/sentinel/api/law-monitor');
      if (requestId !== listRequest) return;
      var previousJurisdiction = jurisdictionPicker.value;
      renderSchedule(data);
      clear(jurisdictionPicker);
      var all = el('option', 'All active jurisdictions'); all.value = ''; jurisdictionPicker.appendChild(all);
      sourceItems = data.sources || [];
      uncovered = data.uncovered || [];
      sourceItems.forEach(function (source) {
        var feedback = checkFeedback.get(source.key);
        if (feedback && !checkingKeys.has(source.key) &&
            feedback.result !== 'request_error' &&
            source.last_result && feedback.result !== source.last_result) checkFeedback.delete(source.key);
      });
      var names = new Set();
      sourceItems.forEach(function (source) {
        if (names.has(source.jurisdiction)) return;
        names.add(source.jurisdiction);
        var option = el('option', source.jurisdiction); option.value = source.jurisdiction;
        jurisdictionPicker.appendChild(option);
      });
      uncovered.forEach(function (jurisdiction) {
        var option = el('option', jurisdiction); option.value = jurisdiction; jurisdictionPicker.appendChild(option);
      });
      jurisdictionPicker.value = previousJurisdiction;
      var deepLink = new URLSearchParams(window.location.search);
      var linkedKey = deepLink.get('law_source');
      var linkedCapture = Number(deepLink.get('law_capture'));
      if (linkedKey && sourceItems.some(function (item) { return item.key === linkedKey; })) {
        selectedKey = linkedKey;
        selectedCaptureId = Number.isSafeInteger(linkedCapture) && linkedCapture > 0 ? linkedCapture : null;
      }
      if (!currentSource()) { selectedKey = sourceItems[0] ? sourceItems[0].key : null; selectedCaptureId = null; }
      renderSources(); renderInspector();
      return true;
    } catch (error) { if (requestId === listRequest) failure(sources, error); return false; }
  }

  async function loadCapture(sourceKey, id, token, target) {
    try {
      var captureId = Number(id);
      if (!Number.isSafeInteger(captureId) || captureId <= 0) throw new Error('Invalid capture identifier.');
      var item = await req('/sentinel/api/law-monitor/captures/' + captureId);
      if (item.source_key !== sourceKey) throw new Error('Capture does not belong to this source.');
      if (token !== detailRequest || selectedKey !== sourceKey) return;
      clear(target);
      var proof = el('section'); proof.appendChild(el('h4', 'Proof and integrity'));
      proof.appendChild(el('p', item.proof));
      proof.appendChild(el('p', 'Captured ' + shortWhen(item.captured_at) + ' · Capture #' + item.id));
      proof.appendChild(el('p', 'Stored-byte integrity: ' + (item.hash_verified ? 'Verified' : 'FAILED')));
      proof.appendChild(el('p', 'Raw SHA-256: ' + item.raw_sha256, 'sn-inspector-hash'));
      proof.appendChild(el('p', 'Extracted-text SHA-256: ' + item.text_sha256, 'sn-inspector-hash'));
      if (item.hash_verified) {
        var link = sourceLink(item.source_url, 'Open pinned authority page ↗');
        if (link) proof.appendChild(link);
      }
      target.appendChild(proof);
      var change = el('section'); change.appendChild(el('h4', 'Recorded text change'));
      change.appendChild(el('pre', item.change_excerpt || 'No textual difference recorded.'));
      var snapshot = el('details'); snapshot.appendChild(el('summary', 'View complete captured text'));
      snapshot.appendChild(el('pre', item.captured_text || 'No captured text available.'));
      change.appendChild(snapshot); target.appendChild(change);
      if (canPropose && item.hash_verified && item.is_latest &&
          item.review_state === 'approved' && item.previous_capture_id && item.change_excerpt &&
          (item.framework_candidates || []).length) {
        var proposal = el('section');
        proposal.appendChild(el('h4', 'Propose a regulatory review'));
        proposal.appendChild(el('p', 'A second specialist decides whether this captured change affects the framework or controls.'));
        var framework = el('select'); framework.setAttribute('aria-label', 'Affected framework');
        item.framework_candidates.forEach(function (name) {
          var option = el('option', name); option.value = name; framework.appendChild(option);
        });
        var title = el('input'); title.placeholder = 'Change title'; title.maxLength = 240;
        title.setAttribute('aria-label', 'Change title');
        var summary = el('textarea'); summary.placeholder = 'Specialist interpretation and uncertainty';
        summary.maxLength = 3000; summary.setAttribute('aria-label', 'Specialist interpretation');
        var refs = el('input'); refs.placeholder = 'Exact affected control references, if verified';
        refs.maxLength = 1000; refs.setAttribute('aria-label', 'Affected control references');
        var result = el('p'); result.setAttribute('role', 'status');
        var submit = button('Send for independent review', async function () {
          submit.disabled = true;
          try {
            var saved = await req('/governance/api/regulatory-source-candidates', 'POST', {
              capture_id: captureId, framework_name: framework.value,
              title: title.value, summary: summary.value, affected_refs: refs.value
            });
            result.textContent = 'Candidate #' + saved.id + ' is awaiting an independent decision in Governance.';
          } catch (error) { failure(result, error); submit.disabled = false; }
        });
        proposal.append(framework, title, summary, refs, submit, result);
        target.appendChild(proposal);
      }
      if (canManage && item.hash_verified && item.previous_capture_id && item.change_excerpt) {
        var draftStatus = el('p'); draftStatus.setAttribute('role', 'status');
        var draftButton = button('Suggest a source-bound passage', async function () {
          draftButton.disabled = true;
          try {
            var draft = await req('/sentinel/api/law-monitor/captures/' + captureId + '/draft', 'POST', {});
            draftStatus.textContent = draft.verified
              ? 'Draft passage, verify before use: “' + draft.claim.quote + '” · Capture #' + draft.claim.capture_id
              : draft.reason;
          } catch (error) { failure(draftStatus, error); }
          finally { draftButton.disabled = false; }
        });
        target.append(draftButton, draftStatus);
      }
      var decision = el('section', null, 'sn-inspector-review');
      decision.appendChild(el('h4', 'Human review'));
      decision.appendChild(el('p', 'State: ' + item.review_state + (item.review_note ? ' · ' + item.review_note : '')));
      if (item.review_overdue) decision.appendChild(el('p', 'Review overdue by more than seven days.'));
      if (item.retention_review_due) decision.appendChild(el('p', 'Retention review due. Check the approved schedule and any legal hold.'));
      decision.appendChild(el('p', item.legal_hold ? 'Legal hold active: ' + item.hold_reason : 'No legal hold recorded.'));
      if (canApprove) {
        var holdReason = el('input'); holdReason.type = 'text'; holdReason.maxLength = 1000;
        holdReason.placeholder = 'Reason for placing or releasing a hold';
        holdReason.setAttribute('aria-label', 'Legal hold reason');
        var hold = button(item.legal_hold ? 'Release legal hold' : 'Place legal hold', async function () {
          hold.disabled = true;
          try {
            await req('/sentinel/api/law-monitor/captures/' + captureId + '/hold', 'POST',
              {enabled: !item.legal_hold, reason: holdReason.value});
            renderInspector();
          } catch (error) { failure(actionStatus, error); hold.disabled = false; }
        });
        decision.appendChild(holdReason); decision.appendChild(hold);
      }
      if (canApprove && item.review_state === 'pending' && item.hash_verified && item.is_latest) {
        var note = el('textarea'); note.placeholder = 'Review reason and legal significance';
        note.setAttribute('aria-label', 'Review reason and legal significance'); note.maxLength = 2000;
        decision.appendChild(note);
        ['approved', 'rejected'].forEach(function (value) {
          var action = button(value === 'approved' ? 'Approve for retrieval' : 'Reject capture', async function () {
            action.disabled = true;
            try {
              await req('/sentinel/api/law-monitor/captures/' + captureId + '/review', 'POST',
                {decision: value, note: note.value});
              checkFeedback.delete(sourceKey);
              await load();
            } catch (error) { failure(actionStatus, error); action.disabled = false; }
          });
          decision.appendChild(action);
        });
      }
      var actionStatus = el('p'); actionStatus.setAttribute('role', 'status');
      decision.appendChild(actionStatus); target.appendChild(decision);
      var impact = el('section'); impact.appendChild(el('h4', 'Connected records in your scope'));
      var impactBody = el('div', 'Checking connected records…'); impact.appendChild(impactBody);
      target.appendChild(impact);
      req('/sentinel/api/law-monitor/captures/' + captureId + '/impact').then(function (summary) {
        if (token !== detailRequest || selectedKey !== sourceKey) return;
        clear(impactBody);
        impactBody.appendChild(el('p', summary.action));
        var paths = {RoPA: '/sentinel/ropa', DPIA: '/sentinel/dpia', Breach: '/sentinel/breaches', DSR: '/sentinel/dsr'};
        Object.keys(summary.records_in_your_scope || {}).forEach(function (kind) {
          if (!Object.prototype.hasOwnProperty.call(paths, kind)) return;
          var link = el('a', kind + ': ' + summary.records_in_your_scope[kind] + ' visible records');
          link.href = paths[kind]; link.style.marginRight = '12px'; impactBody.appendChild(link);
        });
        impactBody.appendChild(el('p', 'Versioned rule cards: ' + summary.rule_cards));
      }).catch(function (error) { if (token === detailRequest) failure(impactBody, error); });
    } catch (error) { if (token === detailRequest) failure(target, error); }
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
        var link = sourceLink(citation.source_url, 'Read official source ↗');
        if (link) card.appendChild(link);
        card.appendChild(el('small', ' · SHA-256 ' + citation.sha256));
        answer.appendChild(card);
      });
    } catch (error) { failure(answer, error); }
  });
  window.snLivingLawRefresh = load;
  if (document.getElementById('view-jurisdictions').classList.contains('active')) load();
})();
