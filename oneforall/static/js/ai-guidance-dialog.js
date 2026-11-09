/**
 * Reusable "Guide the AI" dialog.
 *
 * Lets a user add optional free-text guidance before an AI generation call
 * (e.g. "emphasise remote work scenarios", "keep it under 2 pages"). The
 * returned text is passed through as user input to the backend, which wraps
 * it in <user_input> tags before it reaches the model. Model output still
 * requires normal review because untrusted guidance may influence an answer.
 *
 * Usage:
 *   var guidance = await window.openAiGuidanceDialog({
 *     title: 'Guide the AI',
 *     placeholder: 'e.g. Emphasise remote work scenarios...'
 *   });
 *   // guidance is the entered string, or null if skipped/cancelled
 */
(function () {
  window.openAiGuidanceDialog = function (opts) {
    opts = opts || {};
    var title = opts.title || 'Guide the AI';
    var placeholder = opts.placeholder ||
      'e.g. Emphasise remote work scenarios, keep it concise, use a formal tone...';
    var maxLength = opts.maxLength || 2000;

    return new Promise(function (resolve) {
      var existing = document.getElementById('aiGuidanceDialogRoot');
      if (existing) existing.remove();

      var root = document.createElement('div');
      root.id = 'aiGuidanceDialogRoot';
      root.innerHTML =
        '<div class="ai-guidance-overlay" data-s="s1f192ae" data-sd="flex">' +
          '<div data-s="sbd0f106">' +
            '<div data-s="s36f7b06">' + _esc(title) + '</div>' +
            '<div data-s="se6452a9">Optional. Tell the AI what to emphasise, include, or avoid. This cannot override its safety or accuracy rules.</div>' +
            '<textarea id="aiGuidanceInput" rows="5" maxlength="' + maxLength + '" placeholder="' + _esc(placeholder) + '" data-s="sf0671b7"></textarea>' +
            '<div data-s="s53c792b" data-sd="flex">' +
              '<button type="button" id="aiGuidanceSkip" data-s="s79a22c9">Skip</button>' +
              '<button type="button" id="aiGuidanceGo" data-s="s68b310c">Continue</button>' +
            '</div>' +
          '</div>' +
        '</div>';
      document.body.appendChild(root);

      var textarea = document.getElementById('aiGuidanceInput');
      var overlay = root.querySelector('.ai-guidance-overlay');
      textarea.focus();

      function cleanup(value) {
        root.remove();
        resolve(value);
      }

      document.getElementById('aiGuidanceSkip').addEventListener('click', function () { cleanup(null); });
      document.getElementById('aiGuidanceGo').addEventListener('click', function () { cleanup(textarea.value.trim()); });
      overlay.addEventListener('click', function (e) { if (e.target === overlay) cleanup(null); });
      textarea.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') cleanup(null);
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) cleanup(textarea.value.trim());
      });
    });
  };

  function _esc(s) {
    var d = document.createElement('div');
    d.textContent = String(s == null ? '' : s);
    return d.innerHTML;
  }
})();
