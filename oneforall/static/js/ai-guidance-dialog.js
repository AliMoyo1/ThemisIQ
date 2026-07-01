/**
 * Reusable "Guide the AI" dialog.
 *
 * Lets a user add optional free-text guidance before an AI generation call
 * (e.g. "emphasise remote work scenarios", "keep it under 2 pages"). The
 * returned text is passed through as user input to the backend, which wraps
 * it in <user_input> tags before it reaches the model - it can never override
 * the system prompt's rules.
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
        '<div class="ai-guidance-overlay" style="position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:9999;display:flex;align-items:center;justify-content:center">' +
          '<div style="background:var(--surface,#fff);border:1px solid var(--border,#ddd);border-radius:12px;padding:22px;width:460px;max-width:92vw;box-shadow:0 12px 40px rgba(0,0,0,.25)">' +
            '<div style="font-size:16px;font-weight:700;margin-bottom:6px;color:var(--text,#111)">' + _esc(title) + '</div>' +
            '<div style="font-size:12.5px;color:var(--muted,#666);margin-bottom:12px">Optional. Tell the AI what to emphasise, include, or avoid. This cannot override its safety or accuracy rules.</div>' +
            '<textarea id="aiGuidanceInput" rows="5" maxlength="' + maxLength + '" placeholder="' + _esc(placeholder) + '" style="width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid var(--border,#ddd);border-radius:8px;background:var(--surface2,#f8f8f8);color:var(--text,#111);font-size:13.5px;resize:vertical"></textarea>' +
            '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:14px">' +
              '<button type="button" id="aiGuidanceSkip" style="padding:8px 14px;border:1px solid var(--border,#ddd);border-radius:8px;background:transparent;color:var(--text,#111);cursor:pointer;font-size:13px">Skip</button>' +
              '<button type="button" id="aiGuidanceGo" style="padding:8px 16px;border:none;border-radius:8px;background:var(--accent,#2563eb);color:#fff;cursor:pointer;font-size:13px;font-weight:600">Continue</button>' +
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
