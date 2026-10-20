/* Human-reviewed jurisdiction rule cards and multi-jurisdiction breach obligations. */
(function () {
  'use strict';
  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }
  function toast(message, kind) {
    if (window.showToast) window.showToast(message, kind || 'error');
  }
  function request(url, method, body) {
    return window.ApiClient.request(url, {method: method || 'GET', body: body, actionId: url});
  }
  function errorText(error) { return (error && error.message) || 'The request could not be completed.'; }
  var cards = [];
  var currentBreach = null;

  async function loadCards() {
    var root = document.getElementById('snRuleCards');
    if (!root) return;
    root.textContent = 'Loading reviewed rule cards...';
    try {
      cards = (await request('/sentinel/api/jurisdiction-cards')).items || [];
      if (!cards.length) {
        root.innerHTML = '<p>No rule cards yet. Draft the legal interpretation and have a DPO approve it before relying on a countdown.</p>';
        return;
      }
      root.innerHTML = cards.map(function (card) {
        var approved = card.state === 'approved';
        return '<div class="card" style="margin:10px 0;padding:14px">' +
          '<div style="display:flex;justify-content:space-between;gap:12px"><strong>' + esc(card.jurisdiction_key) +
          ' · ' + esc(card.notice_type) + ' · version ' + esc(card.version) + '</strong><span>' +
          (approved ? 'Approved by DPO' : 'Draft, no operational clock') + '</span></div>' +
          '<p>' + esc(card.rule_summary) + '</p><small>Trigger: ' + esc(card.trigger_definition) +
          ' · ' + esc(card.timezone) + ' · ' +
          (card.asap ? 'As soon as practicable' : esc(card.deadline_hours) + ' hours') +
          ' · effective ' + esc(card.effective_from) + (card.effective_to ? ' to ' + esc(card.effective_to) : '') +
          '</small><div><a href="' + esc(card.source_url) + '" target="_blank" rel="noopener noreferrer">' +
          esc(card.source_title) + '</a>' +
          (!approved && document.getElementById('snRuleCardPanel').dataset.canApprove === 'true'
            ? ' <button type="button" class="btn btn-sm btn-secondary" data-approve-card="' +
            esc(card.id) + '">Approve as DPO</button>' : '') + '</div></div>';
      }).join('');
    } catch (error) {
      root.textContent = 'Rule cards are unavailable. Try again later.';
    }
  }

  var oldLoadJurisdictions = window.snLoadJurisdictions;
  window.snLoadJurisdictions = async function () {
    if (oldLoadJurisdictions) await oldLoadJurisdictions.apply(this, arguments);
    await loadCards();
  };

  var createButton = document.getElementById('snCreateRuleCard');
  if (createButton) createButton.addEventListener('click', function () {
    var root = document.getElementById('snRuleCardForm');
    root.innerHTML = '<form id="snRuleForm" class="card" style="margin:12px 0;padding:16px">' +
      '<h3>Draft a notification rule card</h3>' +
      '<p>This is an interpretation record. It needs DPO approval before a clock can run.</p>' +
      '<div class="form-group"><label>Jurisdiction key <input name="jurisdiction_key" required maxlength="64"></label></div>' +
      '<div class="form-group"><label>Notice type <select name="notice_type"><option value="authority">Authority</option><option value="subjects">Affected people</option></select></label></div>' +
      '<div class="form-group"><label>Source title <input name="source_title" required></label></div>' +
      '<div class="form-group"><label>HTTPS source URL <input name="source_url" type="url" required></label></div>' +
      '<div class="form-group"><label>Reviewed rule summary <textarea name="rule_summary" required></textarea></label></div>' +
      '<div class="form-group"><label>Trigger definition <textarea name="trigger_definition" required></textarea></label></div>' +
      '<div class="form-group"><label>IANA timezone <input name="timezone" value="UTC" required></label></div>' +
      '<div class="form-group"><label>Effective from <input name="effective_from" type="date" required></label></div>' +
      '<div class="form-group"><label>Effective to, if known <input name="effective_to" type="date"></label></div>' +
      '<div class="form-group"><label>Deadline hours <input name="deadline_hours" type="number" min="1" max="8760"></label></div>' +
      '<div class="form-group"><label><input name="asap" type="checkbox"> No fixed hours, as soon as practicable</label></div>' +
      '<button type="submit" class="btn btn-primary">Save draft</button> ' +
      '<button type="button" class="btn btn-secondary" id="snCancelRule">Cancel</button></form>';
    document.getElementById('snCancelRule').onclick = function () { root.replaceChildren(); };
    document.getElementById('snRuleForm').onsubmit = async function (event) {
      event.preventDefault();
      var form = new FormData(event.target);
      var asap = form.has('asap');
      var payload = Object.fromEntries(form.entries());
      payload.asap = asap;
      payload.deadline_hours = asap ? null : Number(payload.deadline_hours);
      try {
        await request('/sentinel/api/jurisdiction-cards', 'POST', payload);
        root.replaceChildren();
        await loadCards();
        toast('Draft rule card saved.', 'success');
      } catch (error) { toast(errorText(error)); }
    };
  });
  var cardRoot = document.getElementById('snRuleCards');
  if (cardRoot) cardRoot.addEventListener('click', async function (event) {
    var button = event.target.closest('[data-approve-card]');
    if (!button) return;
    button.disabled = true;
    try {
      await request('/sentinel/api/jurisdiction-cards/' + Number(button.dataset.approveCard) + '/approve', 'POST');
      await loadCards();
      toast('Rule card approved.', 'success');
    } catch (error) { button.disabled = false; toast(errorText(error)); }
  });

  window.snOpenBreachObligations = async function (breachId) {
    currentBreach = breachId;
    var panel = document.getElementById('snBreachObligationPanel');
    var canManage = panel && panel.dataset.canManage === 'true';
    if (!panel) return;
    panel.style.display = 'block';
    panel.textContent = 'Loading jurisdiction obligations...';
    try {
      var responses = await Promise.all([
        request('/sentinel/api/breaches/' + breachId + '/obligations'),
        request('/sentinel/api/jurisdiction-cards')
      ]);
      cards = responses[1].items || [];
      var items = responses[0].items || [];
      var options = cards.map(function (card) {
        return '<option value="' + esc(card.id) + '">' + esc(card.jurisdiction_key) + ' · ' +
          esc(card.notice_type) + ' · v' + esc(card.version) + ' (' + esc(card.state) + ')</option>';
      }).join('');
      panel.innerHTML = '<div style="display:flex;justify-content:space-between"><h3>Jurisdiction obligations for breach #' +
        esc(breachId) + '</h3><button type="button" class="btn btn-secondary" id="snCloseObligations">Close</button></div>' +
        '<p>Each jurisdiction and notice type has its own source, trigger, owner and decision. A legacy countdown is only indicative.</p>' +
        (items.length ? items.map(function (item) {
          var clock = item.clock || {};
          return '<div class="card" style="margin:10px 0;padding:14px"><strong>' + esc(item.jurisdiction_key) +
            ' · ' + esc(item.notice_type) + ' · v' + esc(item.version) + '</strong><div>Clock: ' +
            esc(clock.state || 'unresolved') + (clock.deadline_at ? ' · ' + esc(clock.deadline_at) : '') +
            '</div><div>Applicability: ' + esc(item.applicability) + ' · decision: ' + esc(item.decision) +
            '</div><small>Source: <a href="' + esc(item.source_url) + '" target="_blank" rel="noopener noreferrer">' +
            esc(item.source_title) + '</a> · trigger: ' + esc(item.trigger_source || 'not confirmed') + '</small>' +
            (canManage ? '<form data-obligation-facts="' + esc(item.id) + '" style="margin-top:8px">' +
            '<label>Applicability <select name="applicability"><option value="under_review"' +
            (item.applicability === 'under_review' ? ' selected' : '') + '>Under review</option>' +
            '<option value="applies"' + (item.applicability === 'applies' ? ' selected' : '') +
            '>Applies</option><option value="not_applicable"' +
            (item.applicability === 'not_applicable' ? ' selected' : '') + '>Not applicable</option></select></label> ' +
            '<label>Trigger with timezone <input name="trigger_at" value="' + esc(item.trigger_at || '') +
            '" placeholder="2026-10-16T12:00:00+02:00"></label> ' +
            '<label>Trigger evidence <input name="trigger_source" maxlength="2000" value="' +
            esc(item.trigger_source || '') + '"></label> ' +
            '<button type="submit" class="btn btn-sm btn-secondary">Update facts</button></form>' +
            '<form data-obligation-decision="' + esc(item.id) + '" style="margin-top:8px"><select name="decision">' +
            '<option value="notify">Notify</option><option value="do_not_notify">Do not notify</option>' +
            '<option value="deferred">Deferred</option></select> ' +
            '<input name="reason" required minlength="10" placeholder="Reason for this decision"> ' +
            '<button type="submit" class="btn btn-sm btn-secondary">Record decision</button></form>' : '') + '</div>';
        }).join('') : '<p>No obligations recorded. Add each jurisdiction requiring an applicability review.</p>') +
        (canManage && cards.length ? '<form id="snAddObligation" class="card" style="padding:14px"><h4>Add obligation</h4>' +
          '<label>Rule card <select name="rule_card_id" required>' + options + '</select></label> ' +
          '<label>Applicability <select name="applicability"><option value="under_review">Under review</option>' +
          '<option value="applies">Applies</option><option value="not_applicable">Not applicable</option></select></label> ' +
          '<label>Confirmed trigger, local time <input type="datetime-local" name="trigger_at"></label> ' +
          '<label>Trigger evidence <input name="trigger_source" maxlength="2000" placeholder="Record or interview that established this trigger"></label> ' +
          '<button type="submit" class="btn btn-primary">Add obligation</button></form>' :
          (canManage ? '<p>Draft and approve a rule card in Jurisdiction Manager before adding a sourced obligation.</p>' : '')) +
        '<div id="snBreachRelated"></div>';
      if (window.RelatedItems) window.RelatedItems.mount(
        document.getElementById('snBreachRelated'), 'sentinel', 'breach', breachId, {canEdit: canManage});
      document.getElementById('snCloseObligations').onclick = function () { panel.style.display = 'none'; };
      var add = document.getElementById('snAddObligation');
      if (add) add.onsubmit = async function (event) {
        event.preventDefault();
        var form = new FormData(add);
        var raw = form.get('trigger_at');
        var payload = {rule_card_id: Number(form.get('rule_card_id')),
          applicability: form.get('applicability'), trigger_at: raw ? new Date(raw).toISOString() : null,
          trigger_source: form.get('trigger_source')};
        try {
          await request('/sentinel/api/breaches/' + currentBreach + '/obligations', 'POST', payload);
          await window.snOpenBreachObligations(currentBreach);
          toast('Obligation added.', 'success');
        } catch (error) { toast(errorText(error)); }
      };
      panel.querySelectorAll('[data-obligation-decision]').forEach(function (form) {
        form.onsubmit = async function (event) {
          event.preventDefault();
          var values = new FormData(form);
          try {
            await request('/sentinel/api/breach-obligations/' + Number(form.dataset.obligationDecision) +
              '/decision', 'POST', {decision: values.get('decision'), reason: values.get('reason')});
            await window.snOpenBreachObligations(currentBreach);
            toast('Decision recorded.', 'success');
          } catch (error) { toast(errorText(error)); }
        };
      });
      panel.querySelectorAll('[data-obligation-facts]').forEach(function (form) {
        form.onsubmit = async function (event) {
          event.preventDefault();
          var values = new FormData(form);
          try {
            await request('/sentinel/api/breach-obligations/' + Number(form.dataset.obligationFacts) +
              '/facts', 'PUT', {applicability: values.get('applicability'),
                trigger_at: values.get('trigger_at') || null, trigger_source: values.get('trigger_source')});
            await window.snOpenBreachObligations(currentBreach);
            toast('Facts updated. Any previous notice decision needs review.', 'success');
          } catch (error) { toast(errorText(error)); }
        };
      });
    } catch (error) { panel.textContent = 'Obligations are unavailable. ' + errorText(error); }
  };
})();
