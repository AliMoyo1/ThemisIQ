(function () {
  /* ── State ───────────────────────────────────────────────────────────── */
  var body      = document.getElementById('chatBody');
  var empty     = document.getElementById('chatEmpty');
  var inputEl   = document.getElementById('chatInput');
  var sendBtn   = document.getElementById('chatSend');
  var form      = document.getElementById('askForm');
  var counter   = document.getElementById('charCounter');
  var USER_INI  = document.querySelector('.ask-wrap').dataset.userInitials || '?';
  var exportLog = [];   // [{role:'user'|'aria', text:'...', ts:'...'}]
  var conversationHistory = [];   // [{role:'user'|'assistant', content:'...'}] last 3 Q&A pairs

  /* ── Textarea auto-grow + char count ────────────────────────────────── */
  inputEl.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    var n = this.value.length;
    counter.textContent = n + ' / 2000';
    counter.className = 'char-counter' + (n > 1900 ? ' over' : n > 1500 ? ' warn' : '');
    sendBtn.disabled = n === 0 || n > 2000;
  });
  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });

  /* ── Framework filter badge ──────────────────────────────────────────── */
  function updateFwBadge() {
    var val  = document.getElementById('fwFilter').value;
    var badge = document.getElementById('fwActiveBadge');
    badge.style.display = val ? 'flex' : 'none';
    if (val) document.getElementById('fwBadgeText').textContent = val;
  }
  document.getElementById('fwFilter').addEventListener('change', updateFwBadge);
  function clearFwFilter() {
    document.getElementById('fwFilter').value = '';
    updateFwBadge();
  }
  document.getElementById('clearFwFilterBtn').addEventListener('click', clearFwFilter);

  /* ── Suggestion chips + history items ───────────────────────────────── */
  document.querySelectorAll('.sug-chip, .history-item').forEach(function (el) {
    el.addEventListener('click', function () {
      var q = el.dataset.q;
      if (!q) return;
      inputEl.value = q;
      inputEl.dispatchEvent(new Event('input'));
      inputEl.focus();
      form.requestSubmit();
    });
  });

  /* ── New chat ────────────────────────────────────────────────────────── */
  document.getElementById('newChatBtn').addEventListener('click', function () {
    // Remove all messages except the empty state
    var msgs = body.querySelectorAll('.msg');
    msgs.forEach(function (m) { m.remove(); });
    empty.style.display = 'block';
    exportLog = [];
    conversationHistory = [];
  });

  /* ── Rebuild index ───────────────────────────────────────────────────── */
  var rebuildBtn = document.getElementById('rebuildBtn');
  if (rebuildBtn) {
    rebuildBtn.addEventListener('click', async function () {
      rebuildBtn.disabled = true;
      rebuildBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:13px;height:13px"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg> Rebuilding…';
      try {
        var r = await fetch('/aria/api/ask/rebuild', { method: 'POST' });
        var j = await r.json();
        if (j.ok) { if (typeof showToast === 'function') showToast('Indexed ' + j.chunks_indexed + ' chunks'); }
        else       { if (typeof showToast === 'function') showToast(j.error || 'Rebuild failed', 'error'); }
      } catch (e) { if (typeof showToast === 'function') showToast(e.message, 'error'); }
      rebuildBtn.disabled = false;
      rebuildBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:13px;height:13px"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg> Rebuild Index';
    });
  }

  /* ── Helpers ─────────────────────────────────────────────────────────── */
  function esc(s) {
    return String(s || '').replace(/[&<>"']/g, function (m) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m];
    });
  }

  function mdToHtml(md) {
    var lines = (md || '').split('\n');
    var html = '', listType = null, buf = [];
    function inline(text) {
      return esc(text)
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>');
    }
    function flushPara() {
      if (buf.length) {
        html += '<p>' + inline(buf.join(' ')) + '</p>';
        buf = [];
      }
    }
    function closeList() { if (listType) { html += '</' + listType + '>'; listType = null; } }
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trimEnd();
      if (!line.trim()) { flushPara(); closeList(); continue; }
      var bullet   = line.match(/^\s*[-*]\s+(.*)/);
      var numbered = line.match(/^\s*\d+\.\s+(.*)/);
      if (bullet || numbered) {
        flushPara();
        var want = bullet ? 'ul' : 'ol';
        if (listType !== want) { closeList(); html += '<' + want + '>'; listType = want; }
        var content = inline((bullet || numbered)[1]);
        html += '<li>' + content + '</li>';
      } else {
        closeList();
        buf.push(line);
      }
    }
    flushPara(); closeList();
    return html;
  }

  function citTypeClass(t) {
    var m = {'document':'document','control':'control','risk':'risk'};
    return 'cit-type-' + (m[(t||'').toLowerCase()] || 'document');
  }

  function renderCitations(cits) {
    if (!cits || !cits.length) return '';
    var cards = cits.map(function (c) {
      var type    = (c.content_type || 'source').toLowerCase();
      var typeLabel = type.toUpperCase();
      var path = c.url_path || '';
      var href = '#';
      if (typeof path === 'string' && path.startsWith('/') && !path.startsWith('//') && !path.includes('\\')) {
        try { if (new URL(path, location.origin).origin === location.origin) href = path; } catch (e) { /* invalid path */ }
      }
      return '<a class="cit-card" href="' + esc(href) + '">' +
        '<span class="cit-type-badge ' + citTypeClass(type) + '">' + esc(typeLabel) + '</span>' +
        '<span class="cit-title" title="' + esc(c.title) + '">' + esc(c.title || 'Source') + '</span>' +
        (c.section ? '<span class="cit-section">' + esc(c.section) + '</span>' : '') +
        '<span class="cit-open">Open →</span>' +
        '</a>';
    }).join('');
    return '<div class="citations">' + cards + '</div>';
  }

  /* ── Add user message ────────────────────────────────────────────────── */
  function addUserMsg(q) {
    if (empty) empty.style.display = 'none';
    var el = document.createElement('div');
    el.className = 'msg msg-user';
    el.innerHTML = '<div class="msg-avatar">' + esc(USER_INI) + '</div>' +
      '<div class="msg-content">' +
        '<div class="msg-meta">You</div>' +
        '<div class="msg-bubble"><p>' + esc(q) + '</p></div>' +
      '</div>';
    body.appendChild(el);
    body.scrollTop = body.scrollHeight;
    exportLog.push({ role: 'user', text: q, ts: new Date().toISOString() });
  }

  /* ── Thinking trace (replaces the old 3-dot typing indicator) ─────────── */
  function addThinking() {
    var el = document.createElement('div');
    el.className = 'msg msg-bot';
    el.innerHTML = '<div class="msg-avatar">A</div>' +
      '<div class="msg-content"><div class="msg-bubble"></div></div>';
    body.appendChild(el);
    var mount = el.querySelector('.msg-bubble');
    var trace = window.ThinkingTrace.open(mount, {
      variant: 'steps',
      activeLabel: 'Thinking',
      rows: [
        { primary: 'Searching the knowledge base' },
        { primary: 'Reading the most relevant sources' },
        { primary: 'Writing the answer' }
      ]
    });
    body.scrollTop = body.scrollHeight;
    return { el: el, trace: trace };
  }

  /* ── Render ARIA response ────────────────────────────────────────────── */
  function renderBotMsg(result) {
    var el = document.createElement('div');
    var covered = result.covered;
    el.className = 'msg msg-bot' + (covered ? '' : ' msg-not-covered');
    var logId = Number(result.log_id);
    if (!Number.isSafeInteger(logId) || logId < 1) logId = 0;
    var chunks = Number(result.chunks_retrieved);
    if (!Number.isSafeInteger(chunks) || chunks < 0) chunks = 0;
    var latency = Number(result.latency_ms);
    if (!Number.isSafeInteger(latency) || latency < 0) latency = 0;

    var contentHtml;
    if (covered) {
      contentHtml =
        '<div class="msg-meta">ARIA · ' + chunks + ' source' + (chunks !== 1 ? 's' : '') + '</div>' +
        '<div class="msg-bubble">' +
          mdToHtml(result.answer || '') +
          renderCitations(result.citations) +
        '</div>';
    } else {
      var owner = result.nearest_owner ? ' Try asking <strong>' + esc(result.nearest_owner) + '</strong>.' : '';
      contentHtml =
        '<div class="msg-meta">ARIA · no matching policy</div>' +
        '<div class="msg-bubble">' +
          '<div class="nc-label"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:12px;height:12px"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg> Not in our policy library</div>' +
          '<p>' + mdToHtml(result.answer || '') + owner + '</p>' +
        '</div>';
    }

    contentHtml +=
      '<div class="msg-actions">' +
        '<span class="msg-latency">' + latency + 'ms</span>' +
        '<button type="button" class="msg-action-btn" title="Copy response" data-action="copy">⧉</button>' +
        (logId ? '<button type="button" class="msg-action-btn" title="Helpful" data-action="feedback" data-feedback="1" data-log-id="' + logId + '"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-thumbs-up></use></svg></button>' +
                 '<button type="button" class="msg-action-btn" title="Not helpful" data-action="feedback" data-feedback="-1" data-log-id="' + logId + '"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-thumbs-down></use></svg></button>' : '') +
      '</div>';

    el.innerHTML = '<div class="msg-avatar">A</div>' +
      '<div class="msg-content">' + contentHtml + '</div>';

    exportLog.push({
      role: 'aria',
      text: (result.answer || ''),
      covered: covered,
      ts: new Date().toISOString(),
    });
    return el;
  }

  /* ── Send feedback ───────────────────────────────────────────────────── */
  async function sendFeedback(logId, value, btn) {
    var f = new FormData();
    f.append('log_id', logId);
    f.append('feedback', value);
    try {
      await fetch('/aria/api/ask/feedback', { method: 'POST', body: f });
      // Mark thumb active, deactivate sibling
      var actions = btn.closest('.msg-actions');
      actions.querySelectorAll('.msg-action-btn').forEach(function (b) {
        b.classList.remove('thumbed-up', 'thumbed-down');
      });
      btn.classList.add(value === 1 ? 'thumbed-up' : 'thumbed-down');
    } catch (e) { /* silent */ }
  }

  /* ── Copy response ───────────────────────────────────────────────────── */
  function copyMsg(btn) {
    var bubble = btn.closest('.msg-content').querySelector('.msg-bubble');
    var text   = bubble ? bubble.innerText : '';
    navigator.clipboard.writeText(text).then(function () {
      if (typeof showToast === 'function') showToast('Copied to clipboard');
    });
  }

  body.addEventListener('click', function (event) {
    var btn = event.target.closest('button[data-action]');
    if (!btn || !body.contains(btn)) return;
    if (btn.dataset.action === 'copy') copyMsg(btn);
    if (btn.dataset.action === 'feedback') {
      var logId = Number(btn.dataset.logId);
      var value = Number(btn.dataset.feedback);
      if (Number.isSafeInteger(logId) && logId > 0 && (value === 1 || value === -1)) {
        sendFeedback(logId, value, btn);
      }
    }
  });

  /* ── Export chat ─────────────────────────────────────────────────────── */
  function exportChat() {
    if (!exportLog.length) {
      if (typeof showToast === 'function') showToast('No conversation to export yet.', 'warn');
      return;
    }
    var lines = ['# Ask ARIA: Conversation Export', ''];
    exportLog.forEach(function (m) {
      if (m.role === 'user') {
        lines.push('## Question');
        lines.push(m.text);
      } else {
        lines.push('**ARIA:**');
        lines.push(m.text);
        lines.push('');
        lines.push('---');
      }
      lines.push('');
    });
    var blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
    var a    = document.createElement('a');
    a.href   = URL.createObjectURL(blob);
    a.download = 'aria-conversation-' + new Date().toISOString().slice(0, 10) + '.md';
    a.click();
  }
  document.getElementById('exportChatBtn').addEventListener('click', exportChat);

  /* ── Ask ─────────────────────────────────────────────────────────────── */
  async function doAsk(question) {
    addUserMsg(question);
    var thinking = addThinking();
    sendBtn.disabled = true;

    var fwFilter = document.getElementById('fwFilter').value;
    var fd = new FormData();
    fd.append('question', question);
    if (fwFilter) fd.append('framework_filter', fwFilter);
    if (conversationHistory.length) {
      fd.append('history', JSON.stringify(conversationHistory.slice(-6)));
    }

    try {
      var resp = await fetch('/aria/api/ask', { method: 'POST', body: fd });
      var data = await resp.json();

      if (!resp.ok || !data.success) {
        thinking.trace.destroy();
        thinking.el.remove();
        var errEl = document.createElement('div');
        errEl.className = 'msg msg-bot';
        errEl.innerHTML = '<div class="msg-avatar">A</div>' +
          '<div class="msg-content"><div class="msg-meta">ARIA · error</div>' +
          '<div class="msg-bubble"><p>' + esc(data.error || 'Something went wrong. Please try again.') + '</p></div>' +
          '</div>';
        body.appendChild(errEl);
      } else {
        var chunks = data.chunks_retrieved || 0;
        thinking.trace.settle({
          appendRows: chunks ? [{ primary: 'Found ' + chunks + ' source' + (chunks !== 1 ? 's' : '') }] : []
        });
        body.appendChild(renderBotMsg(data));
        conversationHistory.push({role: 'user', content: question});
        conversationHistory.push({role: 'assistant', content: data.answer || ''});
        if (conversationHistory.length > 6) conversationHistory = conversationHistory.slice(-6);
      }
      body.scrollTop = body.scrollHeight;
    } catch (e) {
      thinking.trace.destroy();
      thinking.el.remove();
      var netErrEl = document.createElement('div');
      netErrEl.className = 'msg msg-bot';
      netErrEl.innerHTML = '<div class="msg-avatar">A</div>' +
        '<div class="msg-content"><div class="msg-meta">ARIA · error</div>' +
        '<div class="msg-bubble"><p>Connection error. Please check your network and try again.</p></div>' +
        '</div>';
      body.appendChild(netErrEl);
      body.scrollTop = body.scrollHeight;
    }
    sendBtn.disabled = false;
    inputEl.focus();
  }

  sendBtn.addEventListener('click', function () { form.requestSubmit(); });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var q = inputEl.value.trim();
    if (!q || q.length > 2000 || sendBtn.disabled) return;
    inputEl.value = '';
    inputEl.style.height = 'auto';
    counter.textContent = '0 / 2000';
    counter.className = 'char-counter';
    sendBtn.disabled = true;
    doAsk(q);
  });

  /* ── Initial send button state ───────────────────────────────────────── */
  sendBtn.disabled = true;
}());

