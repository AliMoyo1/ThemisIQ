(function () {
  'use strict';
  function escapeText(value) {
    var node = document.createElement('span');
    node.textContent = String(value == null ? '' : value);
    return node.innerHTML;
  }
  function render(box, items) {
    if (!items.length) {
      box.textContent = 'No reviewable control suggestions for this DPIA.';
      return;
    }
    box.innerHTML = '<h4>Controls that may already cover this</h4>' +
      '<p>Suggestions are unverified until a specialist accepts them. Review the control before relying on it.</p>' +
      items.map(function (item) {
        return '<div class="sn-control-suggestion" style="padding:12px 0;border-bottom:1px solid var(--border)">' +
          '<a href="' + escapeText(item.url) + '" target="_blank" rel="noopener">' + escapeText(item.ref) +
          ' · ' + escapeText(item.title) + '</a>' +
          '<div>' + escapeText(item.reason) + ' · Control status: ' + escapeText(item.control_status || 'Not recorded') + '</div>' +
          '<button type="button" data-control-action="accept" data-control-id="' + Number(item.control_id) + '">Accept link</button> ' +
          '<button type="button" data-control-action="dismiss" data-control-id="' + Number(item.control_id) + '">Dismiss</button>' +
          '</div>';
      }).join('');
  }
  window.snLoadDpiaControlSuggestions = async function (id) {
    var box = document.getElementById('snDpiaControlSuggestions');
    if (!box || Number(box.dataset.dpiaId) !== Number(id)) return;
    try {
      var items = await ApiClient.request('/sentinel/api/dpias/' + encodeURIComponent(id) + '/control-suggestions');
      if (box.isConnected && Number(box.dataset.dpiaId) === Number(id)) render(box, items);
    } catch (error) {
      if (box.isConnected) box.textContent = 'Control suggestions could not be loaded. You can still save this DPIA.';
    }
  };
  document.addEventListener('click', async function (event) {
    var button = event.target.closest('[data-control-action][data-control-id]');
    var box = button && button.closest('#snDpiaControlSuggestions');
    if (!box) return;
    var action = button.dataset.controlAction;
    var id = Number(box.dataset.dpiaId), controlId = Number(button.dataset.controlId);
    if (!id || !controlId || (action !== 'accept' && action !== 'dismiss')) return;
    button.disabled = true;
    try {
      await ApiClient.request('/sentinel/api/dpias/' + id + '/control-suggestions/' + controlId,
        {method: 'POST', body: JSON.stringify({action: action})});
      await window.snLoadDpiaControlSuggestions(id);
    } catch (error) {
      button.disabled = false;
      if (window.showToast) showToast('The control decision could not be saved.', 'error');
    }
  });
})();
