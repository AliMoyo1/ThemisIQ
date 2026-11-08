function updateSelection() {
  const sel = document.querySelector('input[name="mfa_policy"]:checked');
  document.querySelectorAll('.mfa-card').forEach(c => { c.style.borderColor = 'var(--border)'; c.style.boxShadow = 'none'; });
  if (sel) {
    const card = document.querySelector('.mfa-card[data-policy="' + sel.value + '"]');
    if (card) { card.style.borderColor = 'var(--accent)'; card.style.boxShadow = '0 0 0 1px var(--accent)'; }
    document.getElementById('lockoutWarning').style.display = (sel.value === 'all') ? 'block' : 'none';
  }
}
document.querySelectorAll('.mfa-card').forEach(card => {
  card.addEventListener('click', () => {
    const v = card.getAttribute('data-policy');
    const radio = document.querySelector('input[name="mfa_policy"][value="' + v + '"]');
    if (radio) { radio.checked = true; updateSelection(); }
  });
});
updateSelection();

async function savePolicy() {
  const sel = document.querySelector('input[name="mfa_policy"]:checked');
  if (!sel) return;
  const btn = document.getElementById('saveBtn');
  const status = document.getElementById('saveStatus');
  btn.disabled = true; status.textContent = 'Saving…';
  try {
    const resp = await fetch('/api/admin/security-settings', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ security: { require_mfa: sel.value } })
    });
    const data = await resp.json().catch(() => ({}));
    if (resp.ok && data.ok) {
      status.textContent = 'Saved ✓'; status.style.color = 'var(--good)';
    } else {
      status.textContent = 'Error: ' + (data.error || resp.status);
      status.style.color = 'var(--bad)';
    }
  } catch (_) {
    status.textContent = 'Could not save MFA policy. Try again.';
    status.style.color = 'var(--bad)';
  } finally {
    btn.disabled = false;
  }
  setTimeout(() => { status.textContent = ''; }, 3000);
}
document.getElementById('saveBtn').addEventListener('click', savePolicy);
