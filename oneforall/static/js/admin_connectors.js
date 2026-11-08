async function _post(url, body, actionId) {
  try {
    return await ApiClient.request(url, { method: 'POST', body, actionId });
  } catch (err) {
    return { ok: false, detail: err.detail };
  }
}

async function loadStatus() {
  try {
    const d = await ApiClient.request('/api/admin/connectors', { actionId: 'connectors.status' });
    setStatus('slack', d.slack_configured);
    setStatus('teams', d.teams_configured);
    setStatus('whatsapp', d.whatsapp_configured);
  } catch (err) {
    console.error('loadStatus failed', err);
  }
}

function setStatus(which, on) {
  var el = document.getElementById(which + 'Status');
  var removeBtn = document.getElementById(which + 'RemoveBtn');
  if (!el) return;
  if (on) {
    el.textContent = 'Configured';
    el.className = 'conn-status on';
    if (removeBtn) removeBtn.style.display = '';
  } else {
    el.textContent = 'Not configured';
    el.className = 'conn-status off';
    if (removeBtn) removeBtn.style.display = 'none';
  }
}

function showMsg(id, ok, text) {
  const el = document.getElementById(id);
  el.className = 'test-msg ' + (ok ? 'ok' : 'fail');
  el.textContent = text;
  el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', 5000);
}

async function saveConnectors() {
  const slack = document.getElementById('slackUrl').value.trim();
  const teams = document.getElementById('teamsUrl').value.trim();
  const wa = document.getElementById('whatsappUrl').value.trim();
  const d = await _post('/api/admin/connectors', {
    slack_webhook_url: slack || '__unchanged__',
    teams_webhook_url: teams || '__unchanged__',
    whatsapp_webhook_url: wa || '__unchanged__',
  }, 'connectors.save');
  showMsg('saveMsg', d.ok, d.ok ? 'Saved.' : (d.detail || 'Save failed.'));
  if (d.ok) {
    document.getElementById('slackUrl').value = '';
    document.getElementById('teamsUrl').value = '';
    document.getElementById('whatsappUrl').value = '';
    loadStatus();
  }
}

async function testSlack() {
  const d = await _post('/api/admin/connectors/test-slack', {}, 'connectors.slack.test');
  showMsg('slackTestMsg', d.ok, d.ok ? 'Test message sent to Slack.' : (d.detail || 'Failed.'));
}

async function testTeams() {
  const d = await _post('/api/admin/connectors/test-teams', {}, 'connectors.teams.test');
  showMsg('teamsTestMsg', d.ok, d.ok ? 'Test message sent to Teams.' : (d.detail || 'Failed.'));
}

async function removeSlack() {
  if (!confirm('Remove Slack webhook?')) return;
  try {
    await ApiClient.request('/api/admin/connectors/slack', { method: 'DELETE', actionId: 'connectors.slack.remove' });
  } catch (err) {
    showMsg('slackTestMsg', false, err.detail || 'Remove failed.');
    return;
  }
  loadStatus();
}

async function removeTeams() {
  if (!confirm('Remove Teams webhook?')) return;
  try {
    await ApiClient.request('/api/admin/connectors/teams', { method: 'DELETE', actionId: 'connectors.teams.remove' });
  } catch (err) {
    showMsg('teamsTestMsg', false, err.detail || 'Remove failed.');
    return;
  }
  loadStatus();
}

async function testWhatsapp() {
  const d = await _post('/api/admin/connectors/test-whatsapp', {}, 'connectors.whatsapp.test');
  showMsg('whatsappTestMsg', d.ok, d.ok ? 'Test message sent to WhatsApp.' : (d.detail || 'Failed.'));
}

async function removeWhatsapp() {
  if (!confirm('Remove WhatsApp webhook?')) return;
  try {
    await ApiClient.request('/api/admin/connectors/whatsapp', { method: 'DELETE', actionId: 'connectors.whatsapp.remove' });
  } catch (err) {
    showMsg('whatsappTestMsg', false, err.detail || 'Remove failed.');
    return;
  }
  loadStatus();
}

document.addEventListener('DOMContentLoaded', loadStatus);

[
  ['slackTestBtn', testSlack],
  ['slackRemoveBtn', removeSlack],
  ['teamsTestBtn', testTeams],
  ['teamsRemoveBtn', removeTeams],
  ['whatsappTestBtn', testWhatsapp],
  ['whatsappRemoveBtn', removeWhatsapp],
  ['saveConnectorsBtn', saveConnectors],
].forEach(function ([id, action]) {
  document.getElementById(id)?.addEventListener('click', action);
});
