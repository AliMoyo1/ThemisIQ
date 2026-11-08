(function(){
'use strict';

const PROVIDERS = [
  { id:'google',          icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-mail></use></svg>',  name:'Google',        sub:'Gmail / Workspace' },
  { id:'microsoft_smtp',  icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-mail></use></svg>',  name:'Microsoft',     sub:'Office 365 SMTP' },
  { id:'microsoft_graph', icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-cloud></use></svg>',  name:'Microsoft',     sub:'Graph API (service acct)' },
  { id:'smtp',            icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-wrench></use></svg>',  name:'Custom SMTP',   sub:'Any SMTP server' },
  { id:'console',         icon:'<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-monitor></use></svg>',  name:'Console only',  sub:'Log, no emails sent' },
];

let currentProvider = '';

// ── Render provider cards ──────────────────────────────────────────────────
function renderProviders(selectedId) {
  const grid = document.getElementById('provGrid');
  grid.innerHTML = PROVIDERS.map(p => `
    <button type="button" class="prov-card${p.id===selectedId?' selected':''}" data-provider-id="${p.id}" aria-pressed="${p.id===selectedId}">
      <div class="prov-icon">${p.icon}</div>
      <div class="prov-name">${p.name}</div>
      <div class="prov-sub">${p.sub}</div>
    </button>
  `).join('');
}

window.selectProvider = function(id) {
  currentProvider = id;
  renderProviders(id);
  // Show/hide sections
  document.querySelectorAll('.ef-section').forEach(s => s.classList.remove('active'));
  const sec = document.getElementById('sec-' + id);
  if (sec) sec.classList.add('active');
  else document.getElementById('sec-none').classList.add('active');
  document.getElementById('saveRow').style.display = 'flex';
};

// ── Load current config ────────────────────────────────────────────────────
// PLAN-36 T03 (findings.md F04): loadConfig() itself stays IIFE-scoped (it
// already worked correctly when called internally, e.g. after a successful
// save) -- resetConfig() below is the window-attached entry point the
// Reset button actually needs, so it always resolved even before this fix.
const DIRTY_FIELD_IDS = ['fSmtpUser','fSmtpPass','fSmtpFrom','fSmtpUserMs','fSmtpPassMs','fSmtpFromMs',
  'fSmtpHostCustom','fSmtpPortCustom','fSmtpUserCustom','fSmtpPassCustom','fSmtpFromCustom',
  'fTenantId','fClientId','fClientSecret','fGraphFrom','fPrivacyBackup'];
let lastLoadedSnapshot = null;

function snapshotForm() {
  const s = {};
  DIRTY_FIELD_IDS.forEach(id => { const el = document.getElementById(id); if (el) s[id] = el.value; });
  return s;
}
function isFormDirty() {
  if (!lastLoadedSnapshot) return false;
  const now = snapshotForm();
  return DIRTY_FIELD_IDS.some(id => (now[id] || '') !== (lastLoadedSnapshot[id] || ''));
}

async function loadConfig(throwOnError) {
  let cfg;
  try {
    cfg = await ApiClient.request('/api/admin/email-config', { actionId: 'email.config.load' });
  } catch (e) {
    console.error('loadConfig failed', e);
    if (throwOnError) throw new Error(e.detail || 'Failed to load configuration.');
    return;
  }
  try {
    const prov = cfg.provider || cfg.resolved_provider || 'console';
    selectProvider(prov);

    // Populate fields
    const set = (id, val) => { const el=document.getElementById(id); if(el&&val) el.value=val; };
    set('fSmtpUser',      cfg.smtp_user);
    set('fSmtpPass',      cfg.smtp_pass);
    set('fSmtpFrom',      cfg.smtp_from);
    set('fSmtpUserMs',    cfg.smtp_user);
    set('fSmtpPassMs',    cfg.smtp_pass);
    set('fSmtpFromMs',    cfg.smtp_from);
    set('fSmtpHostCustom', cfg.smtp_host);
    set('fSmtpPortCustom', cfg.smtp_port);
    set('fSmtpUserCustom', cfg.smtp_user);
    set('fSmtpPassCustom', cfg.smtp_pass);
    set('fSmtpFromCustom', cfg.smtp_from);
    set('fTenantId',      cfg.ms_tenant_id);
    set('fClientId',      cfg.ms_client_id);
    set('fClientSecret',  cfg.ms_client_secret);
    set('fGraphFrom',     cfg.smtp_from);
    document.getElementById('fPrivacyBackup').value = cfg.privacy_backup_email || '';

    // Sidebar status: what the sender really is, not which provider happens to be selected
    const h = cfg.health || {};
    const sb = document.getElementById('sidebarStatus');
    const badge = document.getElementById('statusBadge');
    const label = (PROVIDERS.find(p => p.id === cfg.resolved_provider) || {}).name || cfg.resolved_provider || 'none';
    let tone = 'unconfigured', word = 'Not configured', sub = 'No mail provider is set up. Nothing is sent.';
    if (cfg.resolved_provider === 'console') {
      word = 'Console only'; sub = 'Messages are logged, not sent.';
    } else if (h.configured) {
      tone = 'configured'; word = 'Configured: ' + label;
      sub = 'Credentials are present. The test below shows whether the provider accepts mail.';
    } else if (cfg.resolved_provider) {
      tone = 'error'; word = 'Incomplete: ' + label;
      sub = 'A provider is selected but a host, user or password is missing. Nothing is sent.';
    }
    sb.textContent = '';
    const head = document.createElement('div');
    head.style.fontWeight = '700';
    head.textContent = '\u25CF ' + word;
    const detail = document.createElement('div');
    detail.style.fontSize = '11px';
    detail.textContent = sub;
    sb.appendChild(head);
    sb.appendChild(detail);
    badge.textContent = '';
    const pill = document.createElement('span');
    pill.className = 'status-badge ' + tone;
    pill.textContent = '\u25CF ' + word;
    badge.appendChild(pill);

    const warn = document.getElementById('healthWarnings');
    warn.textContent = '';
    const notes = (h.warnings && h.warnings.length) ? h.warnings : ['No problems found in the sender configuration.'];
    notes.forEach(text => { const li = document.createElement('li'); li.textContent = text; warn.appendChild(li); });
    document.getElementById('clearSecretsRow').hidden = h.credential_source !== 'stored_obscured';
    document.getElementById('secretsNote').hidden = !!cfg.secrets_in_database_allowed;
    ['fSmtpPass', 'fSmtpPassMs', 'fSmtpPassCustom', 'fClientSecret'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.disabled = !cfg.secrets_in_database_allowed;
    });

    if (cfg.last_test_result) {
      document.getElementById('lastTestInfo').textContent =
        'Last test: ' + cfg.last_test_result + '  (' + cfg.last_test_at + ')' +
        (cfg.last_receipt ? '. Receipt: ' + cfg.last_receipt : '');
    }

    lastLoadedSnapshot = snapshotForm();
  } catch(e) {
    console.error('loadConfig failed', e);
    if (throwOnError) throw (e instanceof Error ? e : new Error('Network error -- please check your connection and try again.'));
  }
}

// ── Reset: reload the last persisted server configuration ─────────────────
window.resetConfig = async function() {
  if (isFormDirty() && !confirm('Discard unsaved changes and reload the saved configuration?')) return;
  const btn = document.querySelector('#saveRow button.btn-secondary');
  const original = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'Resetting…'; }
  try {
    await loadConfig(true);
    typeof showToast === 'function' && showToast('Configuration reloaded');
  } catch (e) {
    const msg = 'Failed to reload configuration: ' + e.message;
    typeof showToast === 'function' ? showToast(msg, 'error') : alert(msg);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = original; }
  }
};

// ── Save config ────────────────────────────────────────────────────────────
window.saveConfig = async function() {
  const prov = currentProvider;
  const get  = id => { const el=document.getElementById(id); return el ? el.value.trim() : ''; };

  let body = { provider: prov, privacy_backup_email: get('fPrivacyBackup') };

  if (prov === 'google') {
    body.smtp_host  = 'smtp.gmail.com';
    body.smtp_port  = '587';
    body.smtp_user  = get('fSmtpUser');
    body.smtp_pass  = get('fSmtpPass');
    body.smtp_from  = get('fSmtpFrom');
  } else if (prov === 'microsoft_smtp') {
    body.smtp_host  = 'smtp.office365.com';
    body.smtp_port  = '587';
    body.smtp_user  = get('fSmtpUserMs');
    body.smtp_pass  = get('fSmtpPassMs');
    body.smtp_from  = get('fSmtpFromMs');
  } else if (prov === 'microsoft_graph') {
    body.ms_tenant_id    = get('fTenantId');
    body.ms_client_id    = get('fClientId');
    body.ms_client_secret = get('fClientSecret');
    body.smtp_from       = get('fGraphFrom');
  } else if (prov === 'smtp') {
    body.smtp_host  = get('fSmtpHostCustom');
    body.smtp_port  = get('fSmtpPortCustom');
    body.smtp_user  = get('fSmtpUserCustom');
    body.smtp_pass  = get('fSmtpPassCustom');
    body.smtp_from  = get('fSmtpFromCustom');
  }
  // console: just saves provider=console

  try {
    const out = await ApiClient.request('/api/admin/email-config', { method: 'POST', body, actionId: 'email.config.save' });
    if (typeof showToast === 'function') {
      showToast('Email configuration saved', 'success');
      if (out && out.notice) showToast(out.notice, 'error');
    }
    loadConfig();
  } catch (e) {
    if (typeof showToast === 'function') showToast(e.detail || 'Save failed', 'error');
  }
};

// ── Test ────────────────────────────────────────────────────────────────────
window.runTest = async function() {
  const btn = document.getElementById('testBtn');
  const res = document.getElementById('testResult');
  btn.disabled = true;
  btn.textContent = 'Sending…';
  res.className = 'test-result';
  res.style.display = 'none';

  try {
    const data = await ApiClient.request('/api/admin/email-test', { method: 'POST', actionId: 'email.test' });
    res.style.display = 'block';
    if (data.ok) {
      res.className = 'test-result ok';
      res.textContent = `✓ ${data.detail || 'Test email sent to ' + data.to}`;
    } else {
      res.className = 'test-result fail';
      res.textContent = `✗ ${data.detail || 'Failed'}`;
    }
    document.getElementById('receiptRow').style.display = data.confirm_receipt ? 'block' : 'none';
    loadConfig(); // refresh last-test info
    loadQueue();
  } catch(e) {
    res.style.display = 'block';
    res.className = 'test-result fail';
    res.textContent = `✗ ${e.detail || 'Request failed, check server logs'}`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg> Send Test Email`;
  }
};

// ── Delivery queue ───────────────────────────────────────────────────────────
let queuePaused = false;

window.togglePause = async function() {
  try {
    await ApiClient.request('/api/admin/email-outbox/pause', { method: 'POST', body: { paused: !queuePaused }, actionId: 'email.outbox.pause' });
  } catch (e) {
    if (typeof showToast === 'function') showToast(e.detail || 'Sending could not be paused or resumed', 'error');
  }
  loadQueue();
};

async function loadQueue() {
  const box = document.getElementById('queueCounts');
  const list = document.getElementById('queueAttention');
  try {
    const data = await ApiClient.request('/api/admin/email-outbox', { actionId: 'email.outbox.load' });
    const c = data.counts || {};
    const order = ['queued', 'retry_due', 'provider_accepted', 'logged_only', 'suppressed', 'permanent_failure'];
    box.textContent = order.map(k => k.replace(/_/g, ' ') + ': ' + (c[k] || 0)).join('  \u00B7  ');
    queuePaused = !!data.paused;
    const note = document.getElementById('queuePaused');
    note.hidden = !queuePaused;
    note.textContent = queuePaused
      ? 'Sending is paused. Critical messages still go; everything else waits until you resume.' : '';
    document.getElementById('pauseBtn').textContent = queuePaused ? 'Resume sending' : 'Pause sending';
    const names = Object.keys(data.by_provider || {});
    document.getElementById('queueProviders').textContent = names.length
      ? 'Last 30 days by provider: ' + names.map(n => n + ' (' + Object.entries(data.by_provider[n])
          .map(([k, v]) => k.replace(/_/g, ' ') + ' ' + v).join(', ') + ')').join('; ')
      : '';
    list.textContent = '';
    (data.attention || []).forEach(item => {
      const li = document.createElement('li');
      li.style.padding = '6px 0';
      li.style.borderTop = '1px solid var(--border)';
      const title = document.createElement('div');
      title.style.fontWeight = '600';
      title.textContent = item.template_key + ' (' + String(item.status).replace(/_/g, ' ') + ')';
      const why = document.createElement('div');
      why.style.color = 'var(--muted)';
      why.textContent = (item.last_error || item.suppress_reason || 'waiting') + '. Attempts: ' + (item.attempts || 0);
      const again = document.createElement('button');
      again.type = 'button';
      again.className = 'btn btn-secondary';
      again.textContent = 'Send again';
      again.addEventListener('click', () => requeueMessage(item.id));
      li.appendChild(title);
      li.appendChild(why);
      li.appendChild(again);
      list.appendChild(li);
    });
  } catch (e) {
    box.textContent = 'The delivery queue could not be loaded.';
  }
}

async function requeueMessage(id) {
  try {
    await ApiClient.request('/api/admin/email-outbox/' + encodeURIComponent(id) + '/requeue', { method: 'POST', actionId: 'email.outbox.requeue' });
    if (typeof showToast === 'function') showToast('The message is queued again', 'success');
  } catch (e) {
    if (typeof showToast === 'function') showToast(e.detail || 'The message could not be queued again', 'error');
  }
  loadQueue();
}

window.clearStoredSecrets = async function() {
  if (!confirm('Clear the stored password? Do this only after it is set in the service environment: mail stops if it is not.')) return;
  try {
    await ApiClient.request('/api/admin/email-config/clear-secrets', { method: 'POST', body: { confirm: true }, actionId: 'email.secrets.clear' });
    if (typeof showToast === 'function') showToast('Stored secrets cleared', 'success');
    loadConfig();
  } catch (e) {
    if (typeof showToast === 'function') showToast(e.detail || 'The stored secrets could not be cleared', 'error');
  }
};

window.confirmReceipt = async function(received) {
  try {
    const out = await ApiClient.request('/api/admin/email-test/receipt', { method: 'POST', body: { received: received }, actionId: 'email.test.receipt' });
    document.getElementById('receiptRow').style.display = 'none';
    document.getElementById('lastTestInfo').textContent = 'Receipt: ' + out.last_receipt;
  } catch (e) {
    if (typeof showToast === 'function') showToast(e.detail || 'Your answer could not be saved', 'error');
  }
};

// ── Init ────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
  document.getElementById('provGrid').addEventListener('click', function(event) {
    const card = event.target.closest('button[data-provider-id]');
    if (card && this.contains(card)) selectProvider(card.dataset.providerId);
  });
  [
    ['saveEmailConfigBtn', saveConfig],
    ['resetEmailConfigBtn', resetConfig],
    ['testBtn', runTest],
    ['receiptYesBtn', () => confirmReceipt(true)],
    ['receiptNoBtn', () => confirmReceipt(false)],
    ['clearSecretsBtn', clearStoredSecrets],
    ['pauseBtn', togglePause],
  ].forEach(([id, action]) => document.getElementById(id)?.addEventListener('click', action));
  renderProviders('');
  loadConfig();
  loadQueue();

  // Show admin's email in test section
  fetch('/api/notifications').then(r=>r.json()).then(d=>{
    // User email is not in the notifications API but we can get it from context
  }).catch(()=>{});
});

})();
