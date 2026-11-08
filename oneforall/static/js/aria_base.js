/* Chart.js defaults for ARIA */
if (typeof Chart !== 'undefined') {
  Chart.defaults.font.family = "'Plus Jakarta Sans', sans-serif";
  Chart.defaults.color = '#6b7280';
  Chart.defaults.borderColor = 'rgba(0,0,0,0.06)';
}
/* Sidebar frameworks are now rendered via the shared aria_sidebar.html partial */

/* ── Ask ARIA floating widget ── */
(function() {
  function esc(s){if(!s&&s!==0)return '';var d=document.createElement('div');d.textContent=String(s);return d.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;');}

  const fab = document.getElementById('askFab');
  const drawer = document.getElementById('askDrawer');
  if (!fab || !drawer) return;

  const body = document.getElementById('askDrawerBody');
  const empty = document.getElementById('askDrawerEmpty');
  const input = document.getElementById('askDrawerInput');
  const send = document.getElementById('askDrawerSend');
  const closeBtn = document.getElementById('askDrawerClose');

  function openDrawer() {
    drawer.classList.add('open');
    fab.classList.add('hidden');
    try { sessionStorage.setItem('aria.askDrawer.open', '1'); } catch(e) {}
    // DialogFocus.trap() focuses the first focusable element (the header
    // close button, which comes before the input in DOM order) -- the
    // existing 180ms-delayed focus onto the input specifically runs right
    // after and wins, preserving today's behavior; the trap's actual job
    // here is the Tab containment and the restore-to-FAB on close, not
    // the initial-focus choice.
    if (typeof DialogFocus !== 'undefined') DialogFocus.trap(drawer);
    setTimeout(() => input.focus(), 180);
  }
  function closeDrawer() {
    drawer.classList.remove('open');
    fab.classList.remove('hidden');
    try { sessionStorage.setItem('aria.askDrawer.open', '0'); } catch(e) {}
    if (typeof DialogFocus !== 'undefined') DialogFocus.release();
  }

  try { if (sessionStorage.getItem('aria.askDrawer.open') === '1') openDrawer(); } catch(e) {}
  fab.addEventListener('click', openDrawer);
  closeBtn.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && drawer.classList.contains('open')) closeDrawer();
  });

  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 110) + 'px';
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitQuestion(); }
  });
  send.addEventListener('click', submitQuestion);

  document.querySelectorAll('.ask-chip').forEach(chip => {
    chip.addEventListener('click', () => { input.value = chip.dataset.q || chip.textContent; submitQuestion(); });
  });

  function mdToHtml(s) {
    if (!s) return '';
    s = s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    s = s.replace(/`([^`]+)`/g,'<code>$1</code>');
    s = s.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
    s = s.replace(/(^|[^*])\*([^*\n]+)\*/g,'$1<em>$2</em>');
    return s.split(/\n\n+/).map(p => {
      if (/^\s*[-*]\s/m.test(p)) return '<ul>'+p.split(/\n/).filter(l=>/^\s*[-*]\s/.test(l)).map(l=>'<li>'+l.replace(/^\s*[-*]\s+/,'')+'</li>').join('')+'</ul>';
      if (/^\s*\d+\.\s/m.test(p)) return '<ol>'+p.split(/\n/).filter(l=>/^\s*\d+\.\s/.test(l)).map(l=>'<li>'+l.replace(/^\s*\d+\.\s+/,'')+'</li>').join('')+'</ol>';
      return '<p>'+p.replace(/\n/g,'<br>')+'</p>';
    }).join('');
  }

  function addMessage(cls, html) {
    const div = document.createElement('div');
    div.className = 'ask-msg ' + cls;
    div.innerHTML = html;
    if (empty && empty.parentNode) empty.remove();
    body.appendChild(div);
    body.scrollTop = body.scrollHeight;
    return div;
  }

  function addTyping() {
    const div = document.createElement('div');
    div.className = 'ask-typing'; div.id = 'askTyping';
    div.innerHTML = '<span></span><span></span><span></span>';
    body.appendChild(div); body.scrollTop = body.scrollHeight;
  }

  function removeTyping() { const t = document.getElementById('askTyping'); if (t) t.remove(); }

  async function submitQuestion() {
    const q = (input.value || '').trim();
    if (!q || q.length > 2000) return;
    addMessage('user', '<p>'+q.replace(/</g,'&lt;').replace(/\n/g,'<br>')+'</p>');
    input.value = ''; input.style.height = 'auto'; send.disabled = true;
    addTyping();
    try {
      const fd = new FormData(); fd.append('question', q);
      const res = await fetch('/aria/api/ask', { method: 'POST', body: fd });
      const data = await res.json();
      removeTyping();
      if (!data.success) { addMessage('bot not-covered','<p><strong>Error.</strong> '+esc(data.error||'Try again.')+'</p>'); return; }
      let html = mdToHtml(data.answer || '');
      if (data.citations && data.citations.length) {
        html += '<div class="ask-cits"><div class="ask-cits-label">Sources</div><div>';
        data.citations.forEach(c => { var u=c.url_path||'#'; if(!/^\/(?!\/)/.test(u)) u='#'; html += '<a class="ask-cit" href="'+esc(u)+'" target="_blank" rel="noopener noreferrer">'+esc(c.title||'source')+'</a> '; });
        html += '</div></div>';
      }
      addMessage('bot'+(data.covered?'':' not-covered'), html);
    } catch(err) { removeTyping(); addMessage('bot not-covered','<p><strong>Network error.</strong></p>'); }
    finally { send.disabled = false; input.focus(); }
  }
})();
