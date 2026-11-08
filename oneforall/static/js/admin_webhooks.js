async function loadWebhooks() {
  const resp = await fetch('/api/admin/webhooks');
  const hooks = await resp.json();
  const tbody = document.getElementById('webhooksBody');
  if (!hooks.length) { tbody.innerHTML = '<tr><td colspan="5" style="padding:40px;text-align:center;color:var(--muted);">No webhooks configured.</td></tr>'; return; }
  tbody.innerHTML = hooks.filter(h => Number.isSafeInteger(Number(h.id)) && Number(h.id) > 0).map(h => `
    <tr style="border-bottom:1px solid var(--border-soft);">
      <td style="padding:10px 14px;font-weight:500;font-size:13px;">${esc(h.name)}</td>
      <td style="padding:10px 14px;font-size:12px;color:var(--muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(h.url)}</td>
      <td style="padding:10px 14px;font-size:11px;color:var(--muted);">${(h.events||'').split(',').map(e=>'<span style="padding:1px 5px;border-radius:3px;background:var(--surface3);margin-right:3px;">'+esc(e)+'</span>').join('')}</td>
      <td style="padding:10px 14px;text-align:center;"><span style="padding:2px 8px;border-radius:4px;font-size:11px;background:${h.is_active?'var(--good-soft)':'var(--bad-soft)'};color:${h.is_active?'var(--good)':'var(--bad)'};">${h.is_active?'Active':'Disabled'}</span></td>
      <td style="padding:10px 14px;text-align:center;display:flex;gap:4px;justify-content:center;">
        <button id="test-btn-${Number(h.id)}" data-webhook-action="test" data-webhook-id="${Number(h.id)}" class="btn btn-secondary" style="font-size:11px;padding:3px 8px;">Test</button>
        <button data-webhook-action="logs" data-webhook-id="${Number(h.id)}" class="btn btn-secondary" style="font-size:11px;padding:3px 8px;">Logs</button>
        <button data-webhook-action="delete" data-webhook-id="${Number(h.id)}" class="btn btn-secondary" style="font-size:11px;padding:3px 8px;color:var(--bad);">Del</button>
      </td>
    </tr>
  `).join('');
}

function openNewWebhook() { ModalManager.open('newWhModal'); }

async function createWebhook(e) {
  e.preventDefault();
  const events = [...document.querySelectorAll('.wh-event:checked')].map(el => el.value);
  if (!events.length) { alert('Select at least one event'); return; }
  const body = { name: document.getElementById('whName').value, url: document.getElementById('whUrl').value, events };
  const resp = await fetch('/api/admin/webhooks', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
  if (resp.ok) {
    ModalManager.close('newWhModal');
    document.getElementById('whForm').reset();
    loadWebhooks();
  }
}

async function testWebhook(id) {
  const btn = document.getElementById(`test-btn-${id}`);
  if (!btn || btn.disabled) return; // suppress double-click / repeat-click while a test is in flight
  btn.disabled = true;
  btn.removeAttribute('title');
  btn.textContent = 'Sending...';
  btn.style.color = '';
  try {
    await ApiClient.request(`/api/admin/webhooks/${id}/test`, { method: 'POST', actionId: 'webhooks.test' });
    btn.textContent = 'Delivered';
    btn.style.color = 'var(--good)';
  } catch (err) {
    btn.textContent = 'Failed';
    btn.style.color = 'var(--bad)';
    if (err instanceof ApiClient.ApiError && err.detail) btn.title = err.detail;
  } finally {
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = 'Test';
      btn.style.color = '';
    }, 2000);
  }
}

async function viewLogs(id) {
  const resp = await fetch(`/api/admin/webhooks/${id}/logs`);
  const logs = await resp.json();
  const section = document.getElementById('logSection');
  section.style.display = 'block';
  const el = document.getElementById('logList');
  if (!logs.length) { el.innerHTML = '<div style="color:var(--muted);font-size:12px;">No delivery attempts yet.</div>'; return; }
  el.innerHTML = logs.map(l => `
    <div style="display:flex;align-items:center;gap:10px;padding:6px 10px;border-radius:4px;background:var(--surface2);margin-bottom:4px;">
      <span style="width:8px;height:8px;border-radius:50%;background:${l.success?'var(--good)':'var(--bad)'};"></span>
      <span style="font-size:12px;flex:1;">${esc(l.event)}</span>
      <span style="font-size:11px;color:var(--muted);">HTTP ${esc(String(l.response_code||'—'))}</span>
      <span style="font-size:11px;color:var(--muted);">${esc(l.attempted_at||'')}</span>
    </div>
  `).join('');
  section.scrollIntoView({ behavior:'smooth' });
}

async function deleteWebhook(id) {
  if (!confirm('Delete this webhook?')) return;
  await fetch(`/api/admin/webhooks/${id}`, { method:'DELETE' });
  loadWebhooks();
}

function esc(s) { const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('newWebhookButton').addEventListener('click', openNewWebhook);
  document.getElementById('closeWebhookModal').addEventListener('click', () => ModalManager.close('newWhModal'));
  document.getElementById('whForm').addEventListener('submit', createWebhook);
  document.getElementById('webhooksBody').addEventListener('click', event => {
    const button = event.target.closest('[data-webhook-action][data-webhook-id]');
    if (!button) return;
    const id = Number(button.dataset.webhookId);
    if (!Number.isSafeInteger(id) || id <= 0) return;
    if (button.dataset.webhookAction === 'test') testWebhook(id);
    else if (button.dataset.webhookAction === 'logs') viewLogs(id);
    else if (button.dataset.webhookAction === 'delete') deleteWebhook(id);
  });
  loadWebhooks();
});
