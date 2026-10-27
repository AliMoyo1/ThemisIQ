/* Independent specialist review of Sentinel-backed regulatory candidates. */
(function () {
  'use strict';
  var target = document.getElementById('regSourceCandidateList');
  if (!target || !window.ApiClient) return;

  function node(tag, value) {
    var element = document.createElement(tag);
    if (value !== undefined) element.textContent = String(value);
    return element;
  }
  async function load() {
    target.textContent = 'Loading candidates…';
    try {
      var rows = await window.ApiClient.request('/governance/api/regulatory-source-candidates');
      target.replaceChildren();
      if (!rows.length) { target.textContent = 'No captured changes await a decision.'; return; }
      rows.forEach(function (item) {
        var card = node('article'); card.className = 'gov-card';
        var heading = node('h4', item.title); card.appendChild(heading);
        card.appendChild(node('p', item.framework_name + ' · Capture #' + item.capture_id));
        if (item.summary) card.appendChild(node('p', item.summary));
        if (item.affected_refs) card.appendChild(node('p', 'Proposed control references: ' + item.affected_refs));
        var proof = node('a', 'Inspect source capture');
        proof.href = '/sentinel/jurisdictions?law_source=' + encodeURIComponent(item.source_key) +
          '&law_capture=' + encodeURIComponent(item.capture_id);
        card.appendChild(proof);
        card.appendChild(node('p', 'Inspect capture #' + item.capture_id + ' in Sentinel before deciding.'));
        var reason = node('textarea'); reason.maxLength = 2000;
        reason.setAttribute('aria-label', 'Independent review reason for ' + item.title);
        reason.placeholder = 'Explain the legal and control impact, or why this is not applicable';
        card.appendChild(reason);
        var status = node('p'); status.setAttribute('role', 'status');
        ['approved', 'rejected'].forEach(function (decision) {
          var button = node('button', decision === 'approved' ? 'Approve and map controls' : 'Reject change');
          button.type = 'button'; button.className = 'gov-btn ghost small';
          button.addEventListener('click', async function () {
            button.disabled = true;
            try {
              var result = await window.ApiClient.request(
                '/governance/api/regulatory-source-candidates/' + item.id + '/decision',
                {method: 'POST', body: {decision: decision, note: reason.value}, actionId: 'regulatory-source-review'});
              status.textContent = decision === 'approved'
                ? 'Approved. Exact reference matching processed ' + result.drift.tasks + ' task(s).'
                : 'Candidate rejected with a review record.';
              await load();
              if (typeof window.govLoadReg === 'function') window.govLoadReg();
            } catch (error) { status.textContent = error.message || 'Decision failed'; button.disabled = false; }
          });
          card.appendChild(button);
        });
        card.appendChild(status); target.appendChild(card);
      });
    } catch (error) { target.textContent = error.message || 'Could not load source candidates.'; }
  }
  window.govLoadSourceCandidates = load;
  load();
}());
