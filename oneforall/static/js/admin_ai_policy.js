(function () {
  var REASONS = {
    disabled: 'AI features were off',
    provider_not_allowed: 'the provider was not allowed',
    feature_blocked: 'the feature was off',
    category_not_allowed: 'a kind of data was not allowed',
    budget_exhausted: 'the monthly allowance was used up',
    user_budget_exhausted: 'the person\'s monthly allowance was used up',
    policy_unreadable: 'the policy could not be read'
  };
  var state = null;
  var orgId = null;

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'style') node.setAttribute('style', attrs[k]);
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { node.appendChild(c); });
    return node;
  }
  function url() { return '/api/admin/ai-policy' + (orgId ? '?org_id=' + encodeURIComponent(orgId) : ''); }
  function showError(message) {
    var box = document.getElementById('loadError');
    box.textContent = message || '';
    box.hidden = !message;
  }
  function chosen(listId) {
    return Array.prototype.map.call(document.querySelectorAll('#' + listId + ' input:checked'), function (i) { return i.value; });
  }

  function chip(text) {
    return el('span', {text: text, style: 'display:inline-block; padding:1px 8px; margin-right:4px; border-radius:10px; font-size:11px; background:var(--surface3); border:1px solid var(--border);'});
  }

  function renderEffects() {
    var allowedKinds = chosen('categoryList');
    var enabled = document.getElementById('enabled').checked;
    state.features.forEach(function (f) {
      var box = document.querySelector('#featureRows input[data-feature="' + f.id + '"]');
      var cell = document.querySelector('#featureRows [data-effect="' + f.id + '"]');
      var missing = f.categories.filter(function (c) { return allowedKinds.indexOf(c) < 0; });
      var text = 'On', color = 'var(--good)';
      if (!enabled) { text = 'Off: AI features are off'; color = 'var(--bad)'; }
      else if (!box.checked) { text = 'Off: this feature is switched off'; color = 'var(--bad)'; }
      else if (missing.length) { text = 'Off: ' + missing.map(function (c) { return state.categories[c] ? c : c; }).join(', ') + ' data is not allowed'; color = 'var(--bad)'; }
      cell.textContent = text;
      cell.style.color = color;
    });
  }

  function render(data) {
    state = data;
    var p = data.policy;
    document.getElementById('panel').hidden = false;
    document.getElementById('activeProvider').textContent = data.active_provider;
    document.getElementById('policyState').textContent = data.policy_unreadable
      ? 'The saved policy cannot be read. AI requests are blocked. Review these settings and save a replacement policy.'
      : p.review_required
        ? 'This policy predates recorded approval. AI requests are blocked until a policy manager reviews and confirms it.'
        : data.configured
          ? 'A policy is set for this organization.'
          : 'No policy has been approved for this organization. AI requests are blocked until a policy manager reviews and enables one.';
    document.getElementById('enabled').checked = !!p.enabled;
    document.getElementById('approvePolicy').checked = false;

    var g = data.governance;
    var rolloutOn = document.getElementById('rolloutOn');
    rolloutOn.checked = !!g.enabled;
    rolloutOn.disabled = !g.can_change;
    document.getElementById('rolloutSave').hidden = !g.can_change;
    document.getElementById('separationOn').checked = !!g.separation_required;
    document.getElementById('rolloutState').textContent = (g.chosen
      ? 'The AI Systems link, the "Uses AI?" questions and the Vault target are ' + (g.enabled ? 'shown' : 'hidden') + ' for this organization.'
      : 'No choice has been made, so this follows the platform default (' + (g.default ? 'shown' : 'hidden') + ').') +
      (g.can_change ? '' : ' A platform administrator turns this on or off.') +
      ' The AI impact assessments stay available either way.';

    var only = p.providers.length > 0;
    document.querySelector('input[name="providerMode"][value="' + (only ? 'only' : 'any') + '"]').checked = true;
    var providerList = document.getElementById('providerList');
    providerList.textContent = '';
    data.providers.forEach(function (name) {
      var box = el('input', {type: 'checkbox', value: name});
      box.checked = p.providers.indexOf(name) >= 0;
      providerList.appendChild(el('label', {style: 'display:flex; align-items:center; gap:6px; font-size:13px; cursor:pointer;'}, [box, el('span', {text: name})]));
    });
    syncProviderMode();

    var categoryList = document.getElementById('categoryList');
    categoryList.textContent = '';
    Object.keys(data.categories).forEach(function (key) {
      var box = el('input', {type: 'checkbox', value: key});
      box.checked = p.categories.indexOf(key) >= 0;
      box.addEventListener('change', renderEffects);
      categoryList.appendChild(el('label', {style: 'display:flex; align-items:flex-start; gap:8px; font-size:13px; cursor:pointer;'}, [
        box, el('span', {}, [el('strong', {text: key}), el('span', {text: ' - ' + data.categories[key], style: 'color:var(--muted);'})])]));
    });

    document.getElementById('budget').value = p.monthly_token_budget || '';
    document.getElementById('userBudget').value = p.monthly_user_token_budget || '';
    document.getElementById('budgetUsed').textContent = 'Charged or reserved this month: ' + data.usage.allowance_used.toLocaleString() + ' tokens';

    var rows = document.getElementById('featureRows');
    rows.textContent = '';
    data.features.forEach(function (f) {
      var box = el('input', {type: 'checkbox', 'data-feature': f.id, 'aria-label': 'Allow ' + f.label});
      box.checked = p.blocked_features.indexOf(f.id) < 0;
      box.addEventListener('change', renderEffects);
      var kinds = el('td', {style: 'padding:8px 14px;'}, f.categories.map(chip));
      rows.appendChild(el('tr', {style: 'border-bottom:1px solid var(--border-soft);'}, [
        el('td', {style: 'padding:8px 14px;'}, [box]),
        el('td', {text: f.label, style: 'padding:8px 14px; font-size:13px;'}),
        kinds,
        el('td', {'data-effect': f.id, style: 'padding:8px 14px; font-size:12px;'})
      ]));
    });
    document.getElementById('enabled').onchange = renderEffects;
    renderEffects();

    var u = data.usage;
    document.getElementById('usageTotals').textContent = u.calls + ' requests, ' + u.tokens.toLocaleString() + ' tokens, ' +
      u.refused + ' refused by this policy, ' + u.errors + ' failed (' + u.month + ').';
    var usageRows = document.getElementById('usageRows');
    usageRows.textContent = '';
    u.by_feature.forEach(function (r) {
      usageRows.appendChild(el('tr', {style: 'border-bottom:1px solid var(--border-soft);'}, [
        el('td', {text: r.label, style: 'padding:8px 14px; font-size:13px;'}),
        el('td', {text: String(r.ok), style: 'padding:8px 14px; text-align:right;'}),
        el('td', {text: String(r.refused), style: 'padding:8px 14px; text-align:right;'}),
        el('td', {text: String(r.error), style: 'padding:8px 14px; text-align:right;'}),
        el('td', {text: r.tokens.toLocaleString(), style: 'padding:8px 14px; text-align:right;'})
      ]));
    });
    document.getElementById('usageEmpty').hidden = u.by_feature.length > 0;
    if (u.recent_refusals.length) {
      var last = u.recent_refusals[0];
      document.getElementById('usageTotals').textContent += ' Latest refusal: ' + (REASONS[last.reason] || last.reason) + '.';
    }
  }

  function syncProviderMode() {
    var only = document.querySelector('input[name="providerMode"]:checked').value === 'only';
    Array.prototype.forEach.call(document.querySelectorAll('#providerList input'), function (i) { i.disabled = !only; });
  }

  async function load() {
    showError('');
    document.getElementById('panel').hidden = true;
    if (document.getElementById('orgPick') && !orgId) return;
    var resp = await fetch(url(), {credentials: 'same-origin'});
    var data = await resp.json().catch(function () { return {}; });
    if (!resp.ok) { showError(data.detail || data.error || 'The policy could not be loaded.'); return; }
    render(data);
  }

  async function save() {
    var btn = document.getElementById('saveBtn');
    var status = document.getElementById('saveStatus');
    var mode = document.querySelector('input[name="providerMode"]:checked').value;
    var budget = document.getElementById('budget').value.trim();
    var userBudget = document.getElementById('userBudget').value.trim();
    var body = {
      enabled: document.getElementById('enabled').checked,
      approval_confirmed: document.getElementById('approvePolicy').checked,
      providers: mode === 'only' ? chosen('providerList') : [],
      categories: chosen('categoryList'),
      blocked_features: Array.prototype.map.call(document.querySelectorAll('#featureRows input:not(:checked)'), function (i) { return i.getAttribute('data-feature'); }),
      monthly_token_budget: budget === '' ? null : Number(budget),
      monthly_user_token_budget: userBudget === '' ? null : Number(userBudget)
    };
    if (body.enabled && !document.getElementById('approvePolicy').checked) {
      status.textContent = 'Review and confirm the AI policy before enabling it.';
      status.style.color = 'var(--bad)';
      return;
    }
    if (mode === 'only' && !body.providers.length) {
      status.textContent = 'Choose at least one provider, or pick "Whichever provider the platform uses".';
      status.style.color = 'var(--bad)';
      return;
    }
    btn.disabled = true; status.style.color = 'var(--muted)'; status.textContent = 'Saving...';
    var resp = await fetch(url(), {method: 'PUT', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    var data = await resp.json().catch(function () { return {}; });
    btn.disabled = false;
    if (resp.ok && data.ok) {
      render(data);
      status.textContent = 'Saved'; status.style.color = 'var(--good)';
    } else {
      status.textContent = 'Not saved: ' + (data.error || data.detail || resp.status);
      status.style.color = 'var(--bad)';
    }
  }

  document.querySelectorAll('input[name="providerMode"]').forEach(function (r) { r.addEventListener('change', syncProviderMode); });
  document.getElementById('saveBtn').addEventListener('click', save);
  document.getElementById('separationSave').addEventListener('click', async function () {
    var status = document.getElementById('separationStatus');
    status.style.color = 'var(--muted)'; status.textContent = 'Saving...';
    var resp = await fetch('/api/admin/ai-decision-separation' + (orgId ? '?org_id=' + encodeURIComponent(orgId) : ''), {
      method: 'PUT', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({required: document.getElementById('separationOn').checked})});
    var data = await resp.json().catch(function () { return {}; });
    if (resp.ok && data.ok) { status.textContent = 'Saved'; status.style.color = 'var(--good)'; }
    else { status.textContent = 'Not saved: ' + (data.error || data.detail || resp.status); status.style.color = 'var(--bad)'; }
  });
  document.getElementById('rolloutSave').addEventListener('click', async function () {
    var status = document.getElementById('rolloutStatus');
    status.style.color = 'var(--muted)'; status.textContent = 'Saving...';
    var resp = await fetch('/api/admin/ai-governance' + (orgId ? '?org_id=' + encodeURIComponent(orgId) : ''), {
      method: 'PUT', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({enabled: document.getElementById('rolloutOn').checked})});
    var data = await resp.json().catch(function () { return {}; });
    if (resp.ok && data.ok) {
      status.textContent = 'Saved'; status.style.color = 'var(--good)';
      document.getElementById('rolloutState').textContent = 'The AI Systems link, the "Uses AI?" questions and the Vault target are ' +
        (data.governance.enabled ? 'shown' : 'hidden') + ' for this organization. The AI impact assessments stay available either way.';
    } else {
      status.textContent = 'Not saved: ' + (data.error || data.detail || resp.status);
      status.style.color = 'var(--bad)';
    }
  });

  var pick = document.getElementById('orgPick');
  if (pick) {
    fetch('/super-admin/api/orgs', {credentials: 'same-origin'}).then(function (r) { return r.json(); }).then(function (orgs) {
      orgs.forEach(function (o) { pick.appendChild(el('option', {value: String(o.id), text: o.name})); });
    });
    pick.addEventListener('change', function () { orgId = pick.value || null; load(); });
  }
  load();
}());
