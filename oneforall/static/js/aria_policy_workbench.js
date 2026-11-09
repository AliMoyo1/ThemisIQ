// Policy workbench (moved from its template for strict script policy).
(function () {
  'use strict';
  var DOC_ID = document.getElementById('wbPageConfig').dataset.docId;

  function esc(s) {
    // Quotes too: some values are written into attributes.
    return (s == null ? '' : String(s)).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function versionLabel(v) {
    return 'v' + esc(v.version) + ' ' + window.AriaPolicyWorkflow.ui.stateBadge(v.state);
  }

  function renderCurrentCard(state) {
    var el = document.getElementById('wbCurrentCard');
    var v = state.current_version;
    if (!v) {
      el.innerHTML = '<div class="wb-empty">Not yet published.</div>';
      return;
    }
    var approvedLine = v.approved_at
      ? ('<div class="aria-version-meta">Approved ' + esc(v.approved_at.slice(0, 10)) + '</div>') : '';
    el.innerHTML =
      '<div class="wb-row"><strong>' + versionLabel(v) + '</strong></div>' +
      approvedLine +
      '<div class="wb-row"><a href="/aria/api/policy-versions/' + v.id + '/download">Download</a></div>';
  }

  function renderDraftCard(state, doc) {
    var el = document.getElementById('wbDraftCard');
    var d = state.draft;
    if (!d) {
      if (state.can_start_revision) {
        el.innerHTML = '<button type="button" class="btn btn-primary" data-s="s1561182" id="wbStartRevisionBtn">Start a revision</button>';
        document.getElementById('wbStartRevisionBtn').onclick = function () {
          window.AriaPolicyWorkflow.ui.startRevision(doc);
        };
      } else {
        el.innerHTML = '<div class="wb-empty">No open draft. You do not have permission to start a revision of this document.</div>';
      }
      return;
    }
    var when = (d.updated_at || '').slice(0, 10);
    el.innerHTML =
      '<div class="wb-row">' + window.AriaPolicyWorkflow.ui.stateBadge(d.state) +
      '<span class="aria-version-meta">updated ' + esc(when) + '</span></div>' +
      (d.can_edit
        ? '<div class="wb-row"><a href="/aria/ai-generator?draft=' + encodeURIComponent(d.id) + '">Continue editing &rarr;</a></div>'
        : '<div class="wb-empty">Owned by another author.</div>');
  }

  function renderCandidateCard(state) {
    var el = document.getElementById('wbCandidateCard');
    var c = state.candidate;
    if (!c) {
      el.innerHTML = '<div class="wb-empty">No candidate version in progress.</div>';
      return;
    }
    el.innerHTML = '<div class="wb-row"><strong>' + versionLabel(c) + '</strong></div>';
  }

  async function renderSubmitSection(state) {
    var section = document.getElementById('wbSubmitSection');
    var sv = state.submittable_version;
    if (!sv || !sv.can_submit) {
      section.style.display = 'none';
      return;
    }
    section.style.display = '';
    await window.AriaPolicyWorkflow.ui.initSubmitForApprovalForm(
      document.getElementById('wbSubmitForm'), document.getElementById('wbApproverSelect'),
      document.getElementById('wbSubmitNote'), document.getElementById('wbSubmitEmpty'),
      document.getElementById('wbSubmitBtn'), sv,
      function () { section.style.display = 'none'; loadWorkbench(); }
    );
  }

  /** active_approval targets whichever version currently needs a decision
   * -- current_version, for a brand-new document's first approval cycle
   * (there is no separate candidate row yet in that case), or candidate,
   * for a revision. Rendered in its own section rather than nested inside
   * either card so it is never missed regardless of which slot it's on. */
  function renderApprovalSection(state) {
    var section = document.getElementById('wbApprovalSection');
    var a = state.active_approval;
    if (!a) {
      section.style.display = 'none';
      return;
    }
    section.style.display = '';
    var onVersion = (state.candidate && state.candidate.id === a.policy_version_id)
      ? state.candidate : state.current_version;
    document.getElementById('wbApprovalMeta').textContent =
      'v' + (onVersion ? onVersion.version : '?') + ' · ' + a.status +
      (a.requested_at ? (', requested ' + a.requested_at.slice(0, 10)) : '');

    var bodyEl = document.getElementById('wbApprovalBody');
    bodyEl.innerHTML = '';
    if (a.can_withdraw) {
      var withdrawBtn = document.createElement('button');
      withdrawBtn.type = 'button';
      withdrawBtn.className = 'btn btn-ghost';
      withdrawBtn.style.cssText = 'font-size:12px;padding:6px 14px';
      withdrawBtn.textContent = 'Withdraw';
      withdrawBtn.onclick = async function () {
        var reason = window.prompt('Reason for withdrawing this submission:');
        if (!reason || !reason.trim()) return;
        var res = await window.AriaPolicyWorkflow.api.withdrawApproval(a.id, reason.trim(), a.lock_version);
        if (res.ok) { loadWorkbench(); }
        else if (window.showToast) { window.showToast((res.data.error && res.data.error.message) || 'Withdraw failed.', 'error'); }
      };
      bodyEl.appendChild(withdrawBtn);
    }
    if (a.can_decide) {
      var decisionEl = document.createElement('div');
      decisionEl.style.marginTop = '10px';
      bodyEl.appendChild(decisionEl);
      window.AriaPolicyWorkflow.ui.renderApprovalDecision(decisionEl, a, function () { loadWorkbench(); });
    }
  }

  function renderCompareChoices(history) {
    var left = document.getElementById('wbCompareLeft');
    var right = document.getElementById('wbCompareRight');
    var button = document.getElementById('wbCompareBtn');
    var options = (history || []).map(function (version) {
      return '<option value="' + Number(version.id) + '">v' + esc(version.version) +
        ' · ' + esc(version.state) + '</option>';
    }).join('');
    left.innerHTML = options;
    right.innerHTML = options;
    if ((history || []).length > 1) {
      left.value = String(history[history.length - 1].id);
      right.value = String(history[0].id);
      button.disabled = false;
    } else {
      button.disabled = true;
      document.getElementById('wbCompareResult').textContent =
        'Two retained versions are needed for comparison.';
    }
  }

  async function compareVersions() {
    var left = Number(document.getElementById('wbCompareLeft').value);
    var right = Number(document.getElementById('wbCompareRight').value);
    var result = document.getElementById('wbCompareResult');
    if (!left || !right) return;
    result.textContent = 'Comparing versions…';
    try {
      var data = await ApiClient.request('/aria/api/documents/' +
        encodeURIComponent(DOC_ID) + '/compare?left=' + left + '&right=' + right);
      result.innerHTML =
        '<div class="wb-grid">' +
        '<div><h3>Earlier version</h3><pre data-compare-left data-s="s8d2e5f3"></pre></div>' +
        '<div><h3>Later version</h3><pre data-compare-right data-s="s8d2e5f3"></pre></div>' +
        '</div><h3>Normalized text changes</h3>' +
        '<pre data-compare-diff data-s="s60a5286"></pre>';
      function summary(side) {
        return JSON.stringify({
          version: side.version.version, state: side.version.state,
          approved_at: side.version.approved_at,
          metadata: side.metadata,
          artifact_hashes: {
            input: side.version.input_sha256,
            source: side.version.source_sha256,
            branded: side.version.branded_sha256,
            preview: side.version.preview_sha256,
            template: side.version.template_sha256
          },
          normalized_text_sha256: side.normalized_text_sha256,
          text_truncated: side.text_truncated,
          approval_history: side.approval_history
        }, null, 2);
      }
      result.querySelector('[data-compare-left]').textContent = summary(data.left);
      result.querySelector('[data-compare-right]').textContent = summary(data.right);
      result.querySelector('[data-compare-diff]').textContent =
        data.normalized_diff === null ?
          'Normalized text is unavailable for one or both retained versions. Compare metadata and artifact hashes above.' :
          (data.normalized_diff.join('\n') || 'No normalized text changes.') +
          (data.diff_truncated ? '\nDiff truncated for display.' : '');
    } catch (error) {
      result.textContent = error.detail || 'Could not compare these versions.';
    }
  }
  document.getElementById('wbCompareBtn').addEventListener('click', compareVersions);

  async function loadWorkbench() {
    var res = await window.AriaPolicyWorkflow.api.getWorkbench(DOC_ID);
    if (!res.ok) {
      document.getElementById('wbDocLabel').textContent =
        (res.data.error && res.data.error.message) || 'Could not load this document.';
      return;
    }
    var doc = res.data.document;
    document.getElementById('wbDocLabel').textContent = (doc.title || doc.doc_id) + ' · ' + doc.doc_id;

    renderCurrentCard(res.data);
    renderDraftCard(res.data, doc);
    renderCandidateCard(res.data);
    renderSubmitSection(res.data);
    renderApprovalSection(res.data);
    window.AriaPolicyWorkflow.ui.renderVersionHistory(document.getElementById('wbHistoryCard'), doc);
    renderCompareChoices(res.data.history);
    window.AriaPolicyWorkflow.ui.renderPublicationStatus(document.getElementById('wbPublicationStatus'), doc);
    try {
      var capability = await ApiClient.request('/api/capability-state/aria-authoring');
      var hint = document.getElementById('wbAuthoringState');
      if (capability.state !== 'available' && capability.state !== 'forbidden') {
        hint.textContent = capability.message;
        hint.style.display = '';
        var start = document.getElementById('wbStartRevisionBtn');
        if (start) start.remove();
        document.getElementById('wbSubmitSection').style.display = 'none';
      } else {
        hint.style.display = 'none';
      }
    } catch (error) {
      var start = document.getElementById('wbStartRevisionBtn');
      if (start) start.remove();
      document.getElementById('wbSubmitSection').style.display = 'none';
    }
  }

  window.loadWorkbench = loadWorkbench;
  loadWorkbench();
})();
