async function loadKeys() {
  const resp = await fetch('/api/admin/api-keys');
  const keys = await resp.json();
  const tbody = document.getElementById('keysBody');
  if (!keys.length) { tbody.innerHTML = '<tr><td colspan="8" data-s="sc0add8c">No API keys. Generate one to enable external integrations.</td></tr>'; return; }
  tbody.innerHTML = keys.map(k => `
    <tr data-s="sc91b18f">
      <td data-s="s26c9a4e">${esc(k.name)}</td>
      <td data-s="s9388ed6">${esc(k.org_name||'Legacy key')}</td>
      <td data-s="s4abde30">${esc(k.key_prefix)}</td>
      <td data-s="s40dee16">${esc(k.scopes)}</td>
      <td data-s="s40dee16">${esc(k.last_used_at||'Never')}</td>
      <td data-s="s40dee16">${esc(k.expires_at||'No expiry (rotate)')}</td>
      <td data-s="s9c0b302"><span data-sv="padding:2px 8px;border-radius:4px;font-size:11px;background:${k.is_active?'var(--good-soft)':'var(--bad-soft)'};color:${k.is_active?'var(--good)':'var(--bad)'};">${k.is_active?'Active':'Revoked'}</span></td>
      <td data-s="s9c0b302">${k.is_active && Number.isSafeInteger(Number(k.id)) && Number(k.id) > 0 ? `<button class="btn btn-secondary" data-s="s6868a33" data-revoke-id="${Number(k.id)}">Revoke</button>` : '—'}</td>
    </tr>
  `).join('');
}

async function openNewKey() {
  const select = document.getElementById('keyOrg');
  select.replaceChildren(new Option('Choose an organization', ''));
  document.getElementById('keyUnit').replaceChildren(new Option('All business units', ''));
  try {
    const response = await fetch('/super-admin/api/orgs');
    if (response.ok) {
      const orgs = await response.json();
      orgs.filter(org => org.status === 'active').forEach(org => select.add(new Option(org.name, org.id)));
    }
  } catch (_) { /* The form remains unselectable until organizations load. */ }
  ModalManager.open('newKeyModal');
}

async function loadKeyUnits() {
  const select = document.getElementById('keyUnit');
  const orgId = document.getElementById('keyOrg').value;
  select.replaceChildren(new Option('All business units', ''));
  if (!orgId) return;
  try {
    const response = await fetch(`/api/admin/api-keys/business-units?org_id=${encodeURIComponent(orgId)}`);
    if (response.ok) {
      const units = await response.json();
      if (document.getElementById('keyOrg').value === orgId) {
        units.forEach(unit => select.add(new Option(unit.name, unit.id)));
      }
    }
  } catch (_) { /* The server validates any selected unit before issuance. */ }
}

async function generateKey(e) {
  e.preventDefault();
  const body = {
    name: document.getElementById('keyName').value,
    org_id: document.getElementById('keyOrg').value,
    scopes: Array.from(document.getElementById('keyScopes').selectedOptions, option => option.value).join(','),
    business_unit_id: document.getElementById('keyUnit').value || null
  };
  const resp = await fetch('/api/admin/api-keys', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
  if (resp.ok) {
    const data = await resp.json();
    ModalManager.close('newKeyModal');
    document.getElementById('keyForm').reset();
    document.getElementById('revealKey').textContent = data.key;
    ModalManager.open('revealModal');
    loadKeys();
  } else {
    const error = await resp.json().catch(() => ({}));
    alert(error.error || 'Could not create the API key.');
  }
}

function copyKey() {
  const key = document.getElementById('revealKey').textContent;
  navigator.clipboard.writeText(key).then(() => { alert('Copied!'); });
}

async function revokeKey(id) {
  if (!confirm('Revoke this API key? This cannot be undone.')) return;
  await fetch(`/api/admin/api-keys/${id}`, { method:'DELETE' });
  loadKeys();
}

function esc(s) { const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('newKeyButton').addEventListener('click', openNewKey);
  document.getElementById('keyOrg').addEventListener('change', loadKeyUnits);
  document.getElementById('keyForm').addEventListener('submit', generateKey);
  document.getElementById('copyKeyButton').addEventListener('click', copyKey);
  document.querySelectorAll('[data-close-modal]').forEach(button => {
    button.addEventListener('click', () => ModalManager.close(button.dataset.closeModal));
  });
  document.getElementById('keysBody').addEventListener('click', event => {
    const button = event.target.closest('[data-revoke-id]');
    if (button && event.currentTarget.contains(button)) revokeKey(Number(button.dataset.revokeId));
  });
  loadKeys();
});
