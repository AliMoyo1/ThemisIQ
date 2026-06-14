// Tiny front-end helpers used across pages.

// ----- "Working on it" overlay -----
// Shown automatically on any form with data-ai="..."
// The attribute value becomes the sub-title (e.g. data-ai="Drafting your plan")
function bcmShowAiOverlay(subtitle) {
  let overlay = document.getElementById('ai-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'ai-overlay';
    overlay.className = 'ai-overlay';
    overlay.innerHTML = `
      <div class="ai-card">
        <div class="ai-title">Working on it</div>
        <div class="ai-sub" id="ai-overlay-sub">The copilot is thinking…</div>
        <div class="ai-dots"><span></span><span></span><span></span><span></span></div>
      </div>`;
    document.body.appendChild(overlay);
  }
  const sub = overlay.querySelector('#ai-overlay-sub');
  if (sub && subtitle) sub.textContent = subtitle;
  // Force reflow so the transition plays
  // eslint-disable-next-line no-unused-expressions
  overlay.offsetHeight;
  overlay.classList.add('show');
}

function bcmHideAiOverlay() {
  const overlay = document.getElementById('ai-overlay');
  if (overlay) overlay.classList.remove('show');
}

// Button loading state
function bcmLockSubmit(form) {
  const btn = form.querySelector('button[type="submit"], input[type="submit"]');
  if (!btn) return;
  btn.dataset.originalLabel = btn.innerHTML;
  btn.innerHTML = '<span class="spinner"></span> Working…';
  btn.disabled = true;
}

document.addEventListener('DOMContentLoaded', () => {
  // Auto-dismiss alerts after 5s
  document.querySelectorAll('.alert').forEach(el => {
    setTimeout(() => {
      el.style.transition = 'opacity 400ms ease';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 500);
    }, 5000);
  });

  // Confirm deletion forms
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', (e) => {
      const msg = form.dataset.confirm || 'Are you sure?';
      if (!window.confirm(msg)) e.preventDefault();
    });
  });

  // Any form marked data-ai triggers the overlay on submit
  document.querySelectorAll('form[data-ai]').forEach(form => {
    form.addEventListener('submit', (e) => {
      // Respect data-confirm cancellation
      if (form.hasAttribute('data-confirm')) {
        // defaultPrevented means the user clicked Cancel on the confirm
        // (this handler runs after the data-confirm handler thanks to registration order)
        if (e.defaultPrevented) return;
      }
      const label = form.getAttribute('data-ai') || 'The copilot is thinking…';
      bcmShowAiOverlay(label);
      bcmLockSubmit(form);
    });
  });

  // Hide the overlay if the page is restored from bfcache after back-navigation
  window.addEventListener('pageshow', () => bcmHideAiOverlay());

  // -------- Chatbot: inline "thinking" bubble + overlay suppression --------
  const chatForm = document.getElementById('chatForm');
  const chatStream = document.getElementById('stream');
  if (chatForm && chatStream) {
    chatForm.addEventListener('submit', (e) => {
      const input = document.getElementById('chatInput');
      const text = (input?.value || '').trim();
      if (!text) { e.preventDefault(); return; }

      // Optimistically echo the user's message
      const userMsg = document.createElement('div');
      userMsg.className = 'chat-msg user';
      userMsg.innerHTML = `
        <div class="bubble"></div>
        <div class="avatar-sm" style="background:#0f1116; color:#fff;">Y</div>`;
      userMsg.querySelector('.bubble').textContent = text;
      chatStream.appendChild(userMsg);

      // Add a thinking bubble
      const think = document.createElement('div');
      think.className = 'chat-msg assistant thinking';
      think.innerHTML = `
        <div class="avatar-sm">AI</div>
        <div class="bubble">Thinking <span class="ai-dots"><span></span><span></span><span></span></span></div>`;
      chatStream.appendChild(think);
      chatStream.scrollTop = chatStream.scrollHeight;

      bcmLockSubmit(chatForm);
    });
  }
});
