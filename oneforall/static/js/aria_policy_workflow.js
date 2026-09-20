/**
 * PLAN-35 T10: browser behavior for the ARIA policy authoring workflow.
 *
 * Shared by ai_generator.html (My Drafts, the draft editor, build/preview,
 * confirm) and documents.html (version history, submit/decide approvals,
 * publication status). Every DOM lookup here defaults to a no-op when the
 * expected element isn't on the current page, so this one file is safe to
 * load on both without page-specific guards at the call site.
 *
 * Depends on: static/js/aria_markdown.js (window.AriaMarkdown),
 * static/js/aria_pdf_viewer.js (window.AriaPdfViewer), and the platform
 * shell's global esc()/showToast() (templates/base_shell.html).
 */
(function () {
  'use strict';

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  function toast(message, type) {
    if (typeof window.showToast === 'function') window.showToast(message, type);
  }

  // ─────────────────────────────────────────────────────────────────────
  // Shared fetch helper (section 11: "Handle 401/403/409/413/429/503/504
  // explicitly; never discard local edits on error.") Every call site gets
  // a consistent {ok, status, data} shape; data.error.message is always
  // populated, from the server's own envelope when present or a status-code
  // fallback otherwise, so callers never have to guess at the shape.
  // ─────────────────────────────────────────────────────────────────────

  var STATUS_MESSAGES = {
    401: 'Your session has expired. Please log in again.',
    403: 'You do not have permission to do that.',
    409: 'This changed since you last loaded it. Reload and try again.',
    413: 'That is too large.',
    429: 'Too many requests. Please wait a moment and try again.',
    503: 'The service is temporarily unavailable. Please try again shortly.',
    504: 'The request timed out. Please try again.',
  };

  async function apiFetch(url, options) {
    options = options || {};
    var opts = { credentials: 'same-origin' };
    for (var k in options) opts[k] = options[k];
    var resp;
    try {
      resp = await fetch(url, opts);
    } catch (e) {
      return {
        ok: false, status: 0,
        data: { ok: false, error: { code: 'NETWORK_ERROR', retryable: true,
          message: 'Network error. Check your connection and try again.' } },
      };
    }
    var data = null;
    try { data = await resp.json(); } catch (e) { data = null; }
    if (!resp.ok) {
      var fallback = STATUS_MESSAGES[resp.status] || ('Request failed (HTTP ' + resp.status + ').');
      if (!data || typeof data !== 'object') data = {};
      if (!data.error) data.error = { code: 'HTTP_' + resp.status, retryable: false, message: fallback };
      else if (!data.error.message) data.error.message = fallback;
      data.ok = false;
    }
    return { ok: resp.ok, status: resp.status, data: data || {} };
  }

  function jsonPost(obj) {
    return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(obj || {}) };
  }
  function jsonPut(obj) {
    return { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(obj || {}) };
  }

  var api = {
    listMyDrafts: function () { return apiFetch('/aria/api/policy-drafts'); },
    getDraft: function (id) { return apiFetch('/aria/api/policy-drafts/' + encodeURIComponent(id)); },
    saveDraft: function (id, body) { return apiFetch('/aria/api/policy-drafts/' + encodeURIComponent(id), jsonPut(body)); },
    discardDraft: function (id, lockVersion) {
      return apiFetch('/aria/api/policy-drafts/' + encodeURIComponent(id) + '/discard', jsonPost({ expected_lock_version: lockVersion }));
    },
    recoverDraft: function (id) { return apiFetch('/aria/api/policy-drafts/' + encodeURIComponent(id) + '/recover', jsonPost({})); },
    buildDraft: function (id, templateId, lockVersion) {
      return apiFetch('/aria/api/policy-drafts/' + encodeURIComponent(id) + '/build',
        jsonPost({ template_id: templateId, expected_lock_version: lockVersion }));
    },
    confirmDraft: function (id, buildId, lockVersion) {
      return apiFetch('/aria/api/policy-drafts/' + encodeURIComponent(id) + '/confirm',
        jsonPost({ build_id: buildId, expected_lock_version: lockVersion }));
    },
    startRevision: function (docId, copiedFromVersionId) {
      return apiFetch('/aria/api/documents/' + encodeURIComponent(docId) + '/revision-drafts',
        jsonPost({ copied_from_version_id: copiedFromVersionId || null }));
    },
    listTemplates: function () { return apiFetch('/aria/api/templates'); },

    listVersions: function (docId) { return apiFetch('/aria/api/documents/' + encodeURIComponent(docId) + '/policy-versions'); },
    getVersion: function (versionId) { return apiFetch('/aria/api/policy-versions/' + versionId); },
    listApprovers: function (versionId) { return apiFetch('/aria/api/policy-versions/' + versionId + '/approvers'); },
    submitForApproval: function (versionId, approverId, note, requestId, lockVersion) {
      return apiFetch('/aria/api/policy-versions/' + versionId + '/submit-approval', jsonPost({
        approver_id: approverId, request_note: note, request_id: requestId, expected_lock_version: lockVersion,
      }));
    },
    listMyApprovals: function () { return apiFetch('/aria/api/policy-approvals?assigned_to=me'); },
    decideApproval: function (approvalId, decision, comments, lockVersion) {
      return apiFetch('/aria/api/policy-approvals/' + approvalId + '/decide',
        jsonPost({ decision: decision, comments: comments, expected_lock_version: lockVersion }));
    },
    withdrawApproval: function (approvalId, reason, lockVersion) {
      return apiFetch('/aria/api/policy-approvals/' + approvalId + '/withdraw',
        jsonPost({ reason: reason, expected_lock_version: lockVersion }));
    },
    publicationStatus: function (docId) { return apiFetch('/aria/api/documents/' + encodeURIComponent(docId) + '/publication-status'); },
    retryPublication: function (jobId) { return apiFetch('/aria/api/publication-jobs/' + jobId + '/retry', jsonPost({})); },
  };

  function errMsg(res, fallback) {
    return (res.data && res.data.error && res.data.error.message) || fallback;
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Draft editor (ai_generator.html)
  // ═══════════════════════════════════════════════════════════════════════

  var editorState = { draft: null, dirty: false, savedBodySnapshot: '' };
  var unsavedWarningInstalled = false;

  function installUnsavedWarning() {
    if (unsavedWarningInstalled) return;
    unsavedWarningInstalled = true;
    window.addEventListener('beforeunload', function (e) {
      if (editorState.dirty) {
        e.preventDefault();
        e.returnValue = '';
      }
    });
  }

  function setUnsavedIndicator(dirty) {
    var un = $('draftUnsavedIndicator'), sv = $('draftSavedIndicator');
    if (un) un.style.display = dirty ? '' : 'none';
    if (sv) sv.style.display = dirty ? 'none' : '';
  }

  function onEditorInput() {
    var el = $('draftEditor');
    if (!el) return;
    editorState.dirty = (el.value !== editorState.savedBodySnapshot);
    setUnsavedIndicator(editorState.dirty);
    // section 11 point 4: any edit invalidates the last build -- disable
    // confirm immediately rather than waiting for the next save round-trip.
    var confirmBtn = $('workflowConfirmBtn');
    if (confirmBtn) confirmBtn.disabled = true;
  }

  function switchEditorView(which) {
    var editEl = $('draftEditor'), previewEl = $('policyContent');
    var editTab = $('editorTabEdit'), previewTab = $('editorTabPreview');
    if (!editEl || !previewEl) return;
    if (which === 'preview') {
      window.AriaMarkdown.renderInto(previewEl, editEl.value);
      editEl.style.display = 'none';
      previewEl.style.display = '';
      if (editTab) { editTab.classList.remove('active'); editTab.setAttribute('aria-selected', 'false'); }
      if (previewTab) { previewTab.classList.add('active'); previewTab.setAttribute('aria-selected', 'true'); }
    } else {
      editEl.style.display = '';
      previewEl.style.display = 'none';
      if (editTab) { editTab.classList.add('active'); editTab.setAttribute('aria-selected', 'true'); }
      if (previewTab) { previewTab.classList.remove('active'); previewTab.setAttribute('aria-selected', 'false'); }
      editEl.focus();
    }
  }

  function renderDraftStatus(draft) {
    var bar = $('draftStatusBar');
    if (!bar) return;
    var scopeLabel = draft.business_unit_id ? ('Business unit #' + draft.business_unit_id) : 'Organization-wide';
    var refLabel = draft.reserved_doc_id || (draft.source_document_id ? 'Revision' : '—');
    var versionLabel = (draft.version_major != null) ? (draft.version_major + '.' + draft.version_minor) : '—';
    bar.innerHTML =
      '<span class="aria-draft-status-chip">Draft saved</span>' +
      '<span>' + esc(scopeLabel) + '</span>' +
      '<span class="aria-draft-status-sep">&middot;</span>' +
      '<span>Ref ' + esc(refLabel) + ' v' + esc(versionLabel) + '</span>' +
      '<span class="aria-draft-status-sep">&middot;</span>' +
      '<a href="#" id="draftStatusMyDraftsLink">My Drafts</a>';
    bar.style.display = '';
    var link = $('draftStatusMyDraftsLink');
    if (link) link.addEventListener('click', function (e) { e.preventDefault(); toggleMyDrafts(true); });
  }

  async function loadTemplatesInto(selectEl, currentTemplateId) {
    if (!selectEl) return;
    var res = await api.listTemplates();
    selectEl.innerHTML = '';
    if (!res.ok) {
      selectEl.innerHTML = '<option value="">(could not load templates)</option>';
      return;
    }
    // /aria/api/templates is a pre-existing endpoint (predates this
    // workflow) that returns a bare JSON array, not the {ok, ...} envelope
    // every routes_policy_workflow.py endpoint uses -- confirmed directly
    // against the running server, not assumed from the other endpoints'
    // convention.
    var templates = Array.isArray(res.data) ? res.data : [];
    if (!templates.length) {
      selectEl.innerHTML = '<option value="">(no templates available)</option>';
      return;
    }
    templates.forEach(function (t) {
      var opt = document.createElement('option');
      opt.value = String(t.id);
      opt.textContent = t.name + (t.is_default ? ' (default)' : '');
      selectEl.appendChild(opt);
    });
    if (currentTemplateId) {
      selectEl.value = String(currentTemplateId);
    } else {
      var def = templates.filter(function (t) { return t.is_default; })[0];
      if (def) selectEl.value = String(def.id);
    }
  }

  function enterDraftEditingMode(draft) {
    installUnsavedWarning();
    editorState.draft = draft;
    editorState.dirty = false;
    editorState.savedBodySnapshot = draft.body || '';

    var emptyState = $('emptyState');
    if (emptyState) emptyState.style.display = 'none';
    var loadingState = $('loadingState');
    if (loadingState) loadingState.classList.remove('active');
    var outputBody = $('outputBody');
    if (outputBody) outputBody.style.display = '';
    var outputActions = $('outputActions');
    if (outputActions) outputActions.style.display = '';

    var editEl = $('draftEditor');
    if (editEl) editEl.value = draft.body || '';
    switchEditorView('edit');
    setUnsavedIndicator(false);
    renderDraftStatus(draft);

    var panel = $('workflowPanel');
    if (panel) panel.style.display = '';
    var confirmBtn = $('workflowConfirmBtn');
    if (confirmBtn) confirmBtn.disabled = true;
    var previewSection = $('workflowPreviewSection');
    if (previewSection) previewSection.style.display = 'none';

    loadTemplatesInto($('workflowTemplateSelect'), draft.template_id);

    // Keeps the pre-existing Copy/Markdown/Word/Print buttons (which key
    // off this module-level variable, not the draft object) working
    // unchanged for a resumed or freshly-generated draft alike.
    window.lastGenerated = draft.body || '';
  }

  async function loadDraftById(draftId) {
    var res = await api.getDraft(draftId);
    if (!res.ok) {
      toast(errMsg(res, 'Could not load that draft.'), 'error');
      return null;
    }
    enterDraftEditingMode(res.data.draft);
    return res.data.draft;
  }

  async function saveDraft() {
    var draft = editorState.draft;
    var editEl = $('draftEditor');
    if (!draft || !editEl) return;
    var btn = $('draftSaveBtn');
    if (btn) btn.disabled = true;
    var res = await api.saveDraft(draft.id, { body: editEl.value, expected_lock_version: draft.lock_version });
    if (btn) btn.disabled = false;
    if (!res.ok) {
      // Never discard local edits on error -- the textarea keeps whatever
      // the user typed regardless of what happened here.
      toast(errMsg(res, 'Save failed.'), 'error');
      return;
    }
    editorState.draft = res.data.draft;
    editorState.savedBodySnapshot = editEl.value;
    editorState.dirty = false;
    setUnsavedIndicator(false);
    toast('Draft saved.', 'success');
    refreshMyDrafts();
  }

  async function buildDraft() {
    var draft = editorState.draft;
    var select = $('workflowTemplateSelect');
    if (!draft || !select || !select.value) {
      toast('Choose a template first.', 'error');
      return;
    }
    if (editorState.dirty) {
      toast('Save your edits before building a preview.', 'error');
      return;
    }
    var btn = $('workflowBuildBtn');
    var progress = $('workflowBuildProgress');
    if (btn) btn.disabled = true;
    if (progress) progress.style.display = '';
    var res = await api.buildDraft(draft.id, parseInt(select.value, 10), draft.lock_version);
    if (btn) btn.disabled = false;
    if (progress) progress.style.display = 'none';
    if (!res.ok) {
      toast(errMsg(res, 'Build failed.'), 'error');
      return;
    }
    editorState.draft = res.data.draft;
    var previewSection = $('workflowPreviewSection');
    if (previewSection) previewSection.style.display = '';
    var templateName = select.options[select.selectedIndex] ? select.options[select.selectedIndex].textContent : '';
    var tEl = $('workflowPreviewTemplate'); if (tEl) tEl.textContent = templateName;
    var vEl = $('workflowPreviewVersion');
    if (vEl) vEl.textContent = (res.data.draft.version_major != null) ? (res.data.draft.version_major + '.' + res.data.draft.version_minor) : '—';

    var pdfContainer = $('workflowPdfContainer');
    var confirmBtn = $('workflowConfirmBtn');
    if (pdfContainer && res.data.preview_url) {
      var result = await window.AriaPdfViewer.render(pdfContainer, res.data.preview_url);
      if (confirmBtn) confirmBtn.disabled = !!result.error;
    } else if (confirmBtn) {
      confirmBtn.disabled = false;
    }
    toast('Preview ready.', 'success');
  }

  function backToEditing() {
    switchEditorView('edit');
    var previewSection = $('workflowPreviewSection');
    if (previewSection) previewSection.style.display = 'none';
  }

  async function confirmDraft() {
    var draft = editorState.draft;
    if (!draft || !draft.build_id) return;
    var btn = $('workflowConfirmBtn');
    if (btn) btn.disabled = true;
    var res = await api.confirmDraft(draft.id, draft.build_id, draft.lock_version);
    if (!res.ok) {
      if (btn) btn.disabled = false;
      toast(errMsg(res, 'Confirm failed.'), 'error');
      return;
    }
    editorState.dirty = false; // confirmed -- no more unsaved-edit warning needed for this draft
    toast('Version confirmed. Opening the document…', 'success');
    setTimeout(function () {
      window.location.href = res.data.detail_url || ('/aria/documents?open=' + encodeURIComponent(res.data.doc_id));
    }, 800);
  }

  // ── My Drafts list ──────────────────────────────────────────────────────

  var myDraftsOpen = false;
  function toggleMyDrafts(forceOpen) {
    var list = $('myDraftsList'), chevron = $('myDraftsChevron');
    myDraftsOpen = (forceOpen === true) ? true : !myDraftsOpen;
    if (list) list.style.display = myDraftsOpen ? '' : 'none';
    if (chevron) chevron.classList.toggle('open', myDraftsOpen);
  }

  function draftTitleFromMetadata(d) {
    if (d.metadata_json) {
      try {
        var meta = JSON.parse(d.metadata_json);
        if (meta && meta.title) return meta.title;
      } catch (e) { /* fall through */ }
    }
    return d.reserved_doc_id || 'Untitled draft';
  }

  async function refreshMyDrafts() {
    var section = $('myDraftsSection'), list = $('myDraftsList'), count = $('myDraftsCount');
    if (!section || !list) return;
    var res = await api.listMyDrafts();
    if (!res.ok) return;
    var drafts = (res.data && res.data.drafts) || [];
    if (!drafts.length) {
      section.style.display = 'none';
      return;
    }
    section.style.display = '';
    if (count) count.textContent = String(drafts.length);
    list.innerHTML = drafts.map(function (d) {
      var title = draftTitleFromMetadata(d);
      var when = (d.updated_at || '').slice(0, 10);
      return (
        '<div class="recent-item">' +
          '<div class="recent-item-info">' +
            '<div class="recent-item-title" title="' + esc(title) + '">' + esc(title) + '</div>' +
            '<div class="recent-item-fw">' + esc(d.state) + ' &middot; updated ' + esc(when) + '</div>' +
          '</div>' +
          '<a href="/aria/ai-generator?draft=' + encodeURIComponent(d.id) + '" class="recent-item-open">Resume →</a>' +
        '</div>'
      );
    }).join('');
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Document workflow panel (documents.html): version history, submit,
  // approvals, publication status. Everything below is namespaced so it is
  // safe to call from a page that has none of these elements -- each
  // renderer takes an explicit container rather than assuming a fixed id,
  // since documents.html mounts these inside its own edit modal.
  // ═══════════════════════════════════════════════════════════════════════

  var STATE_BADGE_CLASS = {
    draft: 'badge-draft', pending: 'badge-progress', approved: 'badge-complete',
    rejected: 'badge-overdue', withdrawn: 'badge-draft', legacy: 'badge-draft',
  };

  function stateBadge(state) {
    var cls = STATE_BADGE_CLASS[state] || 'badge-draft';
    return '<span class="badge ' + cls + '">' + esc(state) + '</span>';
  }

  /** Renders the version history (current + candidate + past) for a
   * managed document into `container`. `doc` needs at least doc_id. */
  async function renderVersionHistory(container, doc) {
    if (!container) return;
    container.innerHTML = '<div class="aria-workflow-hint">Loading version history…</div>';
    var res = await api.listVersions(doc.doc_id);
    if (!res.ok) {
      container.innerHTML = '<div class="aria-workflow-hint">' + esc(errMsg(res, 'Could not load version history.')) + '</div>';
      return;
    }
    var versions = res.data.versions || [];
    if (!versions.length) {
      container.innerHTML = '<div class="aria-workflow-hint">No versions yet.</div>';
      return;
    }
    container.innerHTML = versions.map(function (v) {
      var isCurrent = v.id === doc.current_policy_version_id;
      var actions = (
        '<a href="/aria/api/policy-versions/' + v.id + '/download">Download</a>'
      );
      var approvalLine = '';
      if (v.state === 'approved' && v.approved_at) {
        approvalLine = '<div class="aria-version-meta">Approved ' + esc((v.approved_at || '').slice(0, 10)) + '</div>';
      }
      return (
        '<div class="aria-version-row' + (isCurrent ? ' aria-version-current' : '') + '">' +
          '<div class="aria-version-main">' +
            '<strong>v' + esc(v.version) + '</strong> ' + stateBadge(v.state) +
            (isCurrent ? ' <span class="aria-version-tag">Current</span>' : '') +
            approvalLine +
          '</div>' +
          '<div class="aria-version-actions">' + actions + '</div>' +
        '</div>'
      );
    }).join('');
  }

  /** Renders "evidence synchronization needs attention" + retry for the
   * document's current version, when relevant. No-op (renders nothing)
   * when publication is fine or not yet applicable. */
  async function renderPublicationStatus(container, doc) {
    if (!container) return;
    container.innerHTML = '';
    var res = await api.publicationStatus(doc.doc_id);
    if (!res.ok || !res.data.job) return;
    var job = res.data.job;
    if (!(job.state === 'failed' || job.needs_attention)) return;
    var retryBtn = job.id
      ? '<button type="button" class="btn btn-ghost" style="font-size:12px;padding:4px 10px" data-retry-job="' + job.id + '">Retry now</button>'
      : '';
    container.innerHTML =
      '<div class="aria-publication-warning">' +
        '<span>Approved, but evidence synchronization needs attention.' +
        (job.last_error ? (' <span class="aria-workflow-hint">(' + esc(job.last_error) + ')</span>') : '') +
        '</span>' + retryBtn +
      '</div>';
    var btn = container.querySelector('[data-retry-job]');
    if (btn) {
      btn.addEventListener('click', async function () {
        btn.disabled = true;
        var r = await api.retryPublication(job.id);
        if (r.ok) {
          toast('Retry scheduled.', 'success');
          renderPublicationStatus(container, doc);
        } else {
          btn.disabled = false;
          toast(errMsg(r, 'Retry failed.'), 'error');
        }
      });
    }
  }

  /** Starts a revision draft for `doc` and navigates to the editor. */
  async function startRevision(doc, copiedFromVersionId) {
    var res = await api.startRevision(doc.doc_id, copiedFromVersionId);
    if (!res.ok) {
      toast(errMsg(res, 'Could not start a revision.'), 'error');
      return;
    }
    window.location.href = '/aria/ai-generator?draft=' + encodeURIComponent(res.data.draft.id);
  }

  /** Submit-for-approval mini-form: wires `formEl` (must contain a
   * <select> and a submit <button>, found by data attributes) for the
   * given confirmed, not-yet-submitted version. onSubmitted (optional): a
   * real JS function called after a successful submit, so the caller can
   * refresh whatever it displayed the version/publication state in.
   *
   * PLAN-35 T11 review fix: this used to read formEl.dataset.onSubmitted
   * and check `typeof ... === 'function'` before calling it -- a DOM
   * dataset property is a live HTML data-* attribute, which the DOM spec
   * defines as always a string (or undefined if absent), so that check
   * could never be true and the callback could never run no matter what a
   * caller assigned to it. Nothing in this codebase ever assigned it
   * either, so the bug was fully invisible in practice: the form always
   * just hid itself with no follow-up refresh. */
  async function initSubmitForApprovalForm(formEl, selectEl, noteEl, emptyEl, btnEl, version, onSubmitted) {
    if (!formEl || !selectEl || !btnEl) return;
    var res = await api.listApprovers(version.id);
    var approvers = (res.ok && res.data.approvers) || [];
    if (!approvers.length) {
      formEl.style.display = 'none';
      if (emptyEl) emptyEl.style.display = '';
      return;
    }
    if (emptyEl) emptyEl.style.display = 'none';
    formEl.style.display = '';
    selectEl.innerHTML = approvers.map(function (a) {
      return '<option value="' + a.id + '">' + esc(a.full_name || a.username) + '</option>';
    }).join('');
    btnEl.onclick = async function () {
      btnEl.disabled = true;
      var requestId = 'ui-' + version.id + '-' + Date.now();
      var r = await api.submitForApproval(
        version.id, parseInt(selectEl.value, 10), noteEl ? noteEl.value : '', requestId, version.lock_version
      );
      btnEl.disabled = false;
      if (!r.ok) {
        toast(errMsg(r, 'Submit failed.'), 'error');
        return;
      }
      toast('Submitted for approval.', 'success');
      formEl.style.display = 'none';
      if (typeof onSubmitted === 'function') onSubmitted();
    };
  }

  // ── Pending approvals (a manager's own queue) ───────────────────────────

  async function renderPendingApprovals(container, onOpenDecision) {
    if (!container) return;
    container.innerHTML = '<div class="aria-workflow-hint">Loading…</div>';
    var res = await api.listMyApprovals();
    if (!res.ok) {
      container.innerHTML = '<div class="aria-workflow-hint">' + esc(errMsg(res, 'Could not load pending approvals.')) + '</div>';
      return;
    }
    var approvals = res.data.approvals || [];
    if (!approvals.length) {
      container.innerHTML = '<div class="aria-workflow-hint">Nothing is waiting on your approval right now.</div>';
      return;
    }
    container.innerHTML = approvals.map(function (a) {
      return (
        '<div class="recent-item">' +
          '<div class="recent-item-info">' +
            '<div class="recent-item-title">' + esc(a.doc_id || ('Approval #' + a.id)) + '</div>' +
            '<div class="recent-item-fw">Requested ' + esc((a.requested_at || '').slice(0, 10)) + '</div>' +
          '</div>' +
          '<a href="#" class="recent-item-open" data-decide-approval="' + a.id + '">Review →</a>' +
        '</div>'
      );
    }).join('');
    Array.prototype.forEach.call(container.querySelectorAll('[data-decide-approval]'), function (link) {
      link.addEventListener('click', function (e) {
        e.preventDefault();
        var id = parseInt(link.getAttribute('data-decide-approval'), 10);
        var approval = approvals.filter(function (a) { return a.id === id; })[0];
        if (approval && typeof onOpenDecision === 'function') onOpenDecision(approval);
      });
    });
  }

  /** Renders the exact submitted preview + approve/reject controls into
   * `container`. Rejection requires a non-empty comment (enforced
   * client-side for immediate feedback; the server enforces it too). */
  async function renderApprovalDecision(container, approval, onDecided) {
    if (!container) return;
    container.innerHTML = '<div class="aria-workflow-hint">Loading the submitted preview…</div>';
    var pdfContainer = document.createElement('div');
    pdfContainer.className = 'aria-pdf-container';
    var commentEl = document.createElement('textarea');
    commentEl.className = 'aria-approval-comment';
    commentEl.setAttribute('aria-label', 'Decision comment');
    commentEl.placeholder = 'Comment (required to reject)';

    var approveBtn = document.createElement('button');
    approveBtn.type = 'button';
    approveBtn.className = 'btn btn-primary';
    approveBtn.textContent = 'Approve';
    var rejectBtn = document.createElement('button');
    rejectBtn.type = 'button';
    rejectBtn.className = 'btn btn-ghost';
    rejectBtn.style.color = 'var(--red,#dc2626)';
    rejectBtn.textContent = 'Reject';

    var actionsRow = document.createElement('div');
    actionsRow.className = 'aria-workflow-row';
    actionsRow.style.justifyContent = 'flex-end';
    actionsRow.appendChild(approveBtn);
    actionsRow.appendChild(rejectBtn);

    container.innerHTML = '';
    container.appendChild(pdfContainer);
    container.appendChild(commentEl);
    container.appendChild(actionsRow);

    window.AriaPdfViewer.render(pdfContainer, '/aria/api/policy-versions/' + approval.policy_version_id + '/preview');

    async function decide(decision) {
      if (decision === 'reject' && !commentEl.value.trim()) {
        toast('A comment is required to reject.', 'error');
        commentEl.focus();
        return;
      }
      approveBtn.disabled = true;
      rejectBtn.disabled = true;
      var res = await api.decideApproval(approval.id, decision, commentEl.value.trim(), approval.lock_version);
      if (!res.ok) {
        approveBtn.disabled = false;
        rejectBtn.disabled = false;
        // A stale token reloads state with a message (section 11 point 8)
        // rather than silently retrying against data that already changed.
        toast(errMsg(res, 'Decision failed.'), 'error');
        if (res.status === 409 && typeof onDecided === 'function') onDecided(res.data.approval || approval);
        return;
      }
      toast(decision === 'approve' ? 'Approved.' : 'Rejected.', 'success');
      if (typeof onDecided === 'function') onDecided(res.data.approval);
    }
    approveBtn.addEventListener('click', function () { decide('approve'); });
    rejectBtn.addEventListener('click', function () { decide('reject'); });
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Public API
  // ═══════════════════════════════════════════════════════════════════════

  window.AriaPolicyWorkflow = {
    api: api,
    ui: {
      onEditorInput: onEditorInput,
      switchEditorView: switchEditorView,
      saveDraft: saveDraft,
      buildDraft: buildDraft,
      backToEditing: backToEditing,
      confirmDraft: confirmDraft,
      toggleMyDrafts: toggleMyDrafts,
      refreshMyDrafts: refreshMyDrafts,
      loadDraftById: loadDraftById,
      enterDraftEditingMode: enterDraftEditingMode,

      renderVersionHistory: renderVersionHistory,
      renderPublicationStatus: renderPublicationStatus,
      startRevision: startRevision,
      initSubmitForApprovalForm: initSubmitForApprovalForm,
      renderPendingApprovals: renderPendingApprovals,
      renderApprovalDecision: renderApprovalDecision,
      stateBadge: stateBadge,
    },
  };
})();
