// Evidence campaigns (moved from its template for strict script policy).
(function () {
  'use strict';

  function esc(s) {
    if (s == null) return '';
    // Quotes too: some values are written into attributes.
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function badge(status) {
    return '<span class="ec-badge ec-badge-' + esc(status) + '">' + esc(status.replace('_', ' ')) + '</span>';
  }

  // ── Tabs ─────────────────────────────────────────────────────────────
  var tabs = { campaigns: loadCampaigns, mine: function () { loadRequests('mine'); }, review: function () { loadRequests('review'); } };
  document.querySelectorAll('.ec-tab').forEach(function (t) {
    t.addEventListener('click', function () {
      document.querySelectorAll('.ec-tab').forEach(function (x) { x.classList.remove('active'); });
      t.classList.add('active');
      ['campaigns', 'mine', 'review'].forEach(function (k) {
        document.getElementById('ec' + k.charAt(0).toUpperCase() + k.slice(1) + 'Tab').style.display = (k === t.getAttribute('data-tab')) ? '' : 'none';
      });
      tabs[t.getAttribute('data-tab')]();
    });
  });

  // ── Campaigns ────────────────────────────────────────────────────────
  async function loadCampaigns() {
    var el = document.getElementById('ecCampaignsTab');
    el.innerHTML = '<div class="ec-empty">Loading…</div>';
    try {
      var data = await ApiClient.request('/evidence-campaigns/api/campaigns');
      var campaigns = data.campaigns || [];
      if (!campaigns.length) { el.innerHTML = '<div class="ec-empty">No campaigns yet.</div>'; return; }
      el.innerHTML = campaigns.map(function (c) {
        var cov = c.coverage || {};
        return '<div class="ec-card">' +
          '<div class="ec-row">' +
            '<div><strong>' + esc(c.name) + '</strong> ' + badge(c.status) +
              '<div class="ec-meta">Due ' + esc((c.due_date || '').slice(0, 10)) + (c.recurrence !== 'none' ? (' · recurs ' + esc(c.recurrence)) : '') + '</div></div>' +
            (c.status !== 'closed' ? '<button type="button" class="btn btn-ghost" data-s="s562fe77" data-close-campaign="' + c.id + '" data-name="' + esc(c.name) + '">Close</button>' : '') +
          '</div>' +
          '<div class="ec-coverage" data-s="s8a77e5a">' +
            '<span>Requested ' + cov.requested + '</span><span>Submitted ' + cov.submitted + '</span>' +
            '<span>In review ' + cov.in_review + '</span><span>Accepted ' + cov.accepted + '</span>' +
            '<span>Returned ' + cov.returned + '</span><span>Overdue ' + cov.overdue + '</span>' +
            '<span>Cancelled ' + cov.cancelled + '</span>' +
          '</div>' +
        '</div>';
      }).join('');
      Array.prototype.forEach.call(el.querySelectorAll('[data-close-campaign]'), function (btn) {
        btn.addEventListener('click', function () { closeCampaign(parseInt(btn.getAttribute('data-close-campaign'), 10), btn.getAttribute('data-name')); });
      });
    } catch (err) {
      el.innerHTML = '<div class="ec-empty">Could not load campaigns' + (err && err.detail ? ': ' + esc(err.detail) : '.') + '</div>';
    }
  }

  async function closeCampaign(id, name) {
    try {
      await ApiClient.request('/evidence-campaigns/api/campaigns/' + id + '/close', { method: 'POST', body: {} });
      loadCampaigns();
    } catch (err) {
      if (err && err.status === 409) {
        var reason = window.prompt((err.detail || 'Unresolved requests remain.') + '\n\nForce-close anyway? Enter a reason, or cancel to leave it open.');
        if (reason && reason.trim()) {
          try {
            await ApiClient.request('/evidence-campaigns/api/campaigns/' + id + '/close', { method: 'POST', body: { force: true, reason: reason.trim() } });
            loadCampaigns();
          } catch (err2) {
            if (window.showToast) showToast((err2 && err2.detail) || 'Close failed.', 'error');
          }
        }
      } else if (window.showToast) {
        showToast((err && err.detail) || 'Close failed.', 'error');
      }
    }
  }

  document.getElementById('ecNewCampaignBtn').addEventListener('click', async function () {
    var name = window.prompt('Campaign name:');
    if (!name || !name.trim()) return;
    var due = window.prompt('Due date (YYYY-MM-DD):');
    if (!due || !due.trim()) return;
    var recurrence = window.prompt("Recurrence -- 'none', 'monthly', 'quarterly', or 'annual':", 'none') || 'none';
    try {
      await ApiClient.request('/evidence-campaigns/api/campaigns', {
        method: 'POST', body: { name: name.trim(), due_date: due.trim(), recurrence: recurrence.trim() },
      });
      loadCampaigns();
    } catch (err) {
      if (window.showToast) showToast((err && err.detail) || 'Create failed.', 'error');
    }
  });

  document.getElementById('ecNewRequestBtn').addEventListener('click', async function () {
    var title = window.prompt('What evidence is being requested (title)?');
    if (!title || !title.trim()) return;
    var assigneeId = window.prompt('Assignee user id:');
    if (!assigneeId) return;
    var reviewerId = window.prompt('Reviewer user id:');
    if (!reviewerId) return;
    var due = window.prompt('Due date (YYYY-MM-DD):');
    if (!due || !due.trim()) return;
    var moduleName = window.prompt("Which module is this for (e.g. 'grid', 'bcm', 'erm')?", 'evidence') || 'evidence';
    var entityType = window.prompt('Entity type (e.g. control, plan, risk):', 'general') || 'general';
    var entityId = window.prompt('Entity id (the record this evidence is for):', '0') || '0';
    try {
      await ApiClient.request('/evidence-campaigns/api/requests', {
        method: 'POST',
        body: {
          title: title.trim(), assignee_id: parseInt(assigneeId, 10), reviewer_id: parseInt(reviewerId, 10),
          due_date: due.trim(), module: moduleName.trim(), entity_type: entityType.trim(), entity_id: entityId,
        },
      });
      if (window.showToast) showToast('Request created.', 'success');
      loadCampaigns();
    } catch (err) {
      if (window.showToast) showToast((err && err.detail) || 'Create failed.', 'error');
    }
  });

  // ── My Requests / For My Review ─────────────────────────────────────
  async function loadRequests(which) {
    var el = document.getElementById(which === 'mine' ? 'ecMineTab' : 'ecReviewTab');
    el.innerHTML = '<div class="ec-empty">Loading…</div>';
    var qs = which === 'mine' ? '?assignee=me' : '?reviewer=me';
    try {
      var data = await ApiClient.request('/evidence-campaigns/api/requests' + qs);
      var reqs = data.requests || [];
      if (!reqs.length) { el.innerHTML = '<div class="ec-empty">Nothing here right now.</div>'; return; }
      el.innerHTML = reqs.map(function (r) {
        var actions = '';
        if (which === 'mine' && ['requested', 'returned', 'overdue'].indexOf(r.status) !== -1) {
          actions = '<button type="button" class="btn btn-primary" data-s="s562fe77" data-submit="' + r.id + '" data-lock="' + r.lock_version + '">Submit evidence</button>';
        } else if (which === 'review' && r.status === 'submitted') {
          actions = '<button type="button" class="btn btn-ghost" data-s="s562fe77" data-start-review="' + r.id + '" data-lock="' + r.lock_version + '">Start review</button>';
        } else if (which === 'review' && r.status === 'in_review') {
          actions = '<button type="button" class="btn btn-primary" data-s="s562fe77" data-decide="' + r.id + '" data-decision="accept" data-lock="' + r.lock_version + '">Accept</button> ' +
                    '<button type="button" class="btn btn-ghost" data-s="s562fe77" data-decide="' + r.id + '" data-decision="return" data-lock="' + r.lock_version + '">Return</button>';
        }
        return '<div class="ec-card"><div class="ec-row">' +
          '<div><strong>' + esc(r.title) + '</strong> ' + badge(r.status) +
            '<div class="ec-meta">Due ' + esc((r.due_date || '').slice(0, 10)) + '</div></div>' +
          '<div>' + actions + '</div>' +
        '</div></div>';
      }).join('');
      Array.prototype.forEach.call(el.querySelectorAll('[data-submit]'), function (btn) {
        btn.addEventListener('click', function () { submitRequest(parseInt(btn.getAttribute('data-submit'), 10), parseInt(btn.getAttribute('data-lock'), 10)); });
      });
      Array.prototype.forEach.call(el.querySelectorAll('[data-start-review]'), function (btn) {
        btn.addEventListener('click', async function () {
          try {
            await ApiClient.request('/evidence-campaigns/api/requests/' + btn.getAttribute('data-start-review') + '/start-review', {
              method: 'POST', body: { expected_lock_version: parseInt(btn.getAttribute('data-lock'), 10) },
            });
            loadRequests('review');
          } catch (err) { if (window.showToast) showToast((err && err.detail) || 'Failed.', 'error'); }
        });
      });
      Array.prototype.forEach.call(el.querySelectorAll('[data-decide]'), function (btn) {
        btn.addEventListener('click', async function () {
          var decision = btn.getAttribute('data-decision');
          var notes = decision === 'return' ? window.prompt('Reason for returning (required):') : window.prompt('Notes (optional):') || '';
          if (decision === 'return' && (!notes || !notes.trim())) return;
          try {
            await ApiClient.request('/evidence-campaigns/api/requests/' + btn.getAttribute('data-decide') + '/decide', {
              method: 'POST', body: { decision: decision, notes: notes || '', expected_lock_version: parseInt(btn.getAttribute('data-lock'), 10) },
            });
            loadRequests('review');
          } catch (err) { if (window.showToast) showToast((err && err.detail) || 'Failed.', 'error'); }
        });
      });
    } catch (err) {
      el.innerHTML = '<div class="ec-empty">Could not load' + (err && err.detail ? ': ' + esc(err.detail) : '.') + '</div>';
    }
  }

  async function submitRequest(requestId, lockVersion) {
    var q = window.prompt('Search your uploaded evidence by title:');
    if (q === null) return;
    var found;
    try {
      found = await ApiClient.request('/evidence/api/items?q=' + encodeURIComponent(q || ''));
    } catch (err) {
      if (window.showToast) showToast('Could not search evidence.', 'error');
      return;
    }
    var items = (found && found.items) || [];
    if (!items.length) {
      if (window.showToast) showToast('No matching evidence found. Upload it in Evidence Vault first.', 'error');
      return;
    }
    var choice = window.prompt(
      'Matching evidence:\n' + items.map(function (it, i) { return (i + 1) + '. ' + it.title + ' (id ' + it.id + ')'; }).join('\n') +
      '\n\nEnter the id of the evidence item to submit:'
    );
    var evidenceId = parseInt(choice || '', 10);
    if (!evidenceId) return;
    try {
      await ApiClient.request('/evidence-campaigns/api/requests/' + requestId + '/submit', {
        method: 'POST', body: { evidence_id: evidenceId, expected_lock_version: lockVersion },
      });
      if (window.showToast) showToast('Submitted.', 'success');
      loadRequests('mine');
    } catch (err) {
      if (window.showToast) showToast((err && err.detail) || 'Submit failed.', 'error');
    }
  }

  loadCampaigns();
})();
