function esc(s){if(!s&&s!==0)return '';var d=document.createElement('div');d.textContent=String(s);return d.innerHTML.replace(/"/g,'&quot;').replace(/'/g,'&#39;');}

async function createFramework(e) {
  e.preventDefault();
  var form = document.getElementById('newFwForm');
  var fd = new FormData(form);
  var modules = Array.from(form.querySelectorAll('input[name="modules"]:checked')).map(function(c){return c.value;}).join(',');
  var body = {
    name: fd.get('name'),
    description: fd.get('description'),
    color: fd.get('color'),
    relevant_modules: modules,
  };
  var btn = document.getElementById('createFwBtn');
  btn.textContent = 'Creating...';
  btn.disabled = true;
  try {
    var resp = await fetch('/admin/api/frameworks', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (!resp.ok) { var d = await resp.json(); throw new Error(d.error || 'Failed'); }
    showToast('Framework created successfully', 'success');
    ModalManager.close('newFwModal');
    setTimeout(function(){ location.reload(); }, 600);
  } catch (err) {
    showToast('Error: ' + err.message, 'error');
    btn.textContent = 'Create Framework';
    btn.disabled = false;
  }
}

async function toggleFramework(fwId, active) {
  var toggle = document.getElementById('fw-toggle-' + fwId);
  var track = document.getElementById('fw-track-' + fwId);
  var thumb = document.getElementById('fw-thumb-' + fwId);
  var label = document.getElementById('fw-label-' + fwId);

  var endpoint = active ? '/api/frameworks/' + fwId + '/activate' : '/api/frameworks/' + fwId + '/deactivate';
  try {
    var resp = await fetch(endpoint, { method: 'POST' });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);

    track.style.background = active ? '#22c55e' : 'var(--surface3)';
    thumb.style.left = active ? '20px' : '2px';
    label.textContent = active ? 'Active' : 'Inactive';
    label.style.color = active ? '#22c55e' : 'var(--muted)';
    toggle.checked = active;
    showToast((active ? 'Activated' : 'Deactivated') + ' framework', 'success');
  } catch (err) {
    toggle.checked = !active;
    showToast('Failed: ' + err.message, 'error');
  }
}

async function aiGenerateControls(fwId, fwName) {
  var btn = document.getElementById('fw-ai-btn-' + fwId);
  if (!btn) return;
  btn.textContent = 'Generating...';
  btn.disabled = true;
  btn.style.opacity = '0.6';
  btn.style.cursor = 'wait';

  try {
    var resp = await fetch('/api/frameworks/' + fwId + '/controls/ai-generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({count: 15}),
    });
    var data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Failed');

    var cell = document.getElementById('fw-controls-' + fwId);
    cell.innerHTML = '<span data-s="s8a79397">' + esc(data.inserted) + '</span>';
    showToast('Generated ' + data.inserted + ' controls for ' + esc(fwName), 'success');
  } catch (err) {
    btn.textContent = 'AI Generate';
    btn.disabled = false;
    btn.style.opacity = '1';
    btn.style.cursor = 'pointer';
    showToast('Error: ' + err.message, 'error');
  }
}
document.querySelectorAll('.js-generate-controls').forEach(function (button) {
  button.addEventListener('click', function () {
    aiGenerateControls(Number(button.dataset.frameworkId), button.dataset.frameworkName);
  });
});

document.getElementById('seedBtn')?.addEventListener('click', seedControls);
document.getElementById('newFwOpenBtn')?.addEventListener('click', function () {
  ModalManager.open('newFwModal');
});
document.querySelectorAll('.js-close-fw-modal').forEach(function (button) {
  button.addEventListener('click', function () {
    ModalManager.close('newFwModal');
  });
});
document.getElementById('newFwForm')?.addEventListener('submit', createFramework);
document.querySelectorAll('input[data-framework-id][id^="fw-toggle-"]').forEach(function (toggle) {
  toggle.addEventListener('change', function () {
    var fwId = Number(toggle.dataset.frameworkId);
    if (Number.isSafeInteger(fwId) && fwId > 0) toggleFramework(fwId, toggle.checked);
  });
});

async function seedControls() {
  var btn = document.getElementById('seedBtn');
  btn.textContent = 'Seeding...';
  btn.disabled = true;
  try {
    var resp = await fetch('/admin/api/frameworks/seed-controls', {method: 'POST'});
    var data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Failed');
    showToast('Seeded ' + data.seeded + ' controls', 'success');
    if (data.seeded > 0) setTimeout(function(){ location.reload(); }, 800);
    else { btn.textContent = 'Seed Controls'; btn.disabled = false; }
  } catch (err) {
    btn.textContent = 'Seed Controls';
    btn.disabled = false;
    showToast('Error: ' + err.message, 'error');
  }
}

function showToast(msg, type) {
  var existing = document.querySelectorAll('.ofa-toast');
  existing.forEach(function(t){ t.remove(); });
  var t = document.createElement('div');
  t.className = 'ofa-toast';
  t.style.cssText = 'position:fixed; bottom:24px; right:24px; padding:12px 20px; border-radius:10px; font-size:13px; font-weight:500; z-index:9999; box-shadow:0 4px 12px rgba(0,0,0,0.15); animation:toastIn 0.3s ease;';
  t.style.background = type === 'success' ? '#f0fdf4' : '#fef2f2';
  t.style.color = type === 'success' ? '#16a34a' : '#dc2626';
  t.style.border = '1px solid ' + (type === 'success' ? 'rgba(22,163,74,0.2)' : 'rgba(220,38,38,0.2)');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(function(){ t.style.opacity = '0'; t.style.transition = 'opacity 0.3s'; }, 2500);
  setTimeout(function(){ t.remove(); }, 2800);
}
