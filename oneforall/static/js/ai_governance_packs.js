/* Read-only AI review packs. Build all server-supplied content as text nodes. */
(function (global) {
  'use strict';
  var A = global.AIGov, el = A.el, API = '/ai-governance/api';

  function clear(node) { return A.clear(node); }
  function say(node, message, kind) { A.say(node, message, kind); }
  function link(pack) { return '/ai-governance/packs/' + encodeURIComponent(pack.id); }
  function date(value) { return A.date(value) || 'Not recorded'; }

  function packList(host, packs, managed) {
    clear(host);
    if (!packs.length) {
      host.appendChild(el('p', { class: 'aig-empty', text: managed ? 'No packs have been issued for this AI use.' : 'No review packs have been shared with you.' }));
      return;
    }
    var list = el('ul', { class: 'aig-pack-cards' });
    packs.forEach(function (pack) {
      var details = [pack.application_name, managed ? pack.recipient : pack.issued_by, 'Expires ' + date(pack.expires_at)];
      if (managed) details.push(pack.state);
      list.appendChild(el('li', { class: 'aig-pack-card' }, [
        el('a', { href: link(pack), class: 'aig-pack-card-title', text: pack.name }),
        el('p', { class: 'aig-muted', text: details.filter(Boolean).join(' · ') }),
        pack.purpose ? el('p', { text: pack.purpose }) : null,
        managed ? el('p', { class: 'aig-muted', text: pack.opened + ' opens or downloads' + (pack.last_opened_at ? ' · Last ' + date(pack.last_opened_at) : '') }) : null
      ]));
    });
    host.appendChild(list);
  }

  function mine(root) {
    var panel = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigMineTitle' });
    panel.appendChild(el('h2', { id: 'aigMineTitle', class: 'aig-h2', text: 'Shared with me' }));
    var status = el('div', { role: 'status', class: 'aig-say', text: 'Loading shared packs…' });
    var list = el('div');
    panel.appendChild(status); panel.appendChild(list); root.appendChild(panel);
    A.api(API + '/packs/mine').then(function (data) { say(status, ''); packList(list, data.packs || [], false); })
      .catch(function (error) {
        if (error.status === 403) { panel.remove(); return; }
        say(status, A.errorText(error), 'bad');
      });
  }

  function systemPicker(root) {
    var panel = el('section', { class: 'aig-panel' }, [el('h2', { class: 'aig-h2', text: 'Prepare a pack' }),
      el('p', { class: 'aig-muted', text: 'Choose the AI use you want to share.' })]);
    var input = el('input', { type: 'search', autocomplete: 'off', placeholder: 'Search AI uses' });
    panel.appendChild(A.field('aigPackSystemSearch', 'Find an AI use', input).row);
    var status = el('div', { class: 'aig-say', role: 'status' }), list = el('div');
    panel.appendChild(status); panel.appendChild(list); root.appendChild(panel);
    var sequence = 0;
    function search() {
      var own = ++sequence;
      say(status, 'Searching…');
      A.api(API + '/systems' + A.qs({ q: input.value.trim(), state: 'active', page_size: 30 }))
        .then(function (data) {
          if (own !== sequence) return;
          say(status, ''); clear(list);
          if (!(data.items || []).length) list.appendChild(el('p', { class: 'aig-empty', text: 'No AI uses found.' }));
          (data.items || []).forEach(function (item) {
            list.appendChild(el('a', { class: 'aig-result aig-pack-system-link', href: '/ai-governance/packs?application_id=' + encodeURIComponent(item.id), text: item.name }));
          });
        }).catch(function (error) { if (own === sequence) say(status, A.errorText(error), 'bad'); });
    }
    input.addEventListener('input', A.debounce(search, 250));
    search();
  }

  function sectionPreview(section, index) {
    var box = el('li', { class: 'aig-pack-preview-section' });
    var details = el('details', { open: index < 2 });
    details.appendChild(el('summary', {}, [el('strong', { text: section.title }),
      A.chip(String(section.state || '').replace(/_/g, ' ')),
      el('span', { class: 'aig-muted', text: ' ' + (section.items || []).length + ' items' })]));
    if (section.note) details.appendChild(el('p', { class: 'aig-muted', text: section.note }));
    if ((section.items || []).length) {
      details.appendChild(el('ul', { class: 'aig-pack-preview-items' }, section.items.map(function (item) {
        var entry = el('li', {}, [el('strong', { text: item.title }),
          item.status ? A.chip(item.status) : null,
          item.when ? el('span', { class: 'aig-muted', text: ' ' + date(item.when) }) : null]);
        if ((item.lines || []).length) entry.appendChild(el('ul', {}, item.lines.map(function (line) { return el('li', { text: line }); })));
        return entry;
      })));
    } else if (!section.note) details.appendChild(el('p', { class: 'aig-muted', text: 'Nothing recorded in this section.' }));
    box.appendChild(details);
    return box;
  }

  function prepare(root, appId) {
    var panel = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigPrepareTitle' });
    panel.appendChild(el('h2', { id: 'aigPrepareTitle', class: 'aig-h2', text: 'Prepare a pack' }));
    panel.appendChild(el('p', { class: 'aig-muted', text: 'The preview is a snapshot of what you can open now. Confirm the recipient and sections before issuing.' }));
    var form = el('form', { class: 'aig-form' });
    var name = el('input', { type: 'text', maxlength: '140', required: true });
    var purpose = el('textarea', { rows: '2', maxlength: '1000' });
    var recipientSearch = el('input', { type: 'search', autocomplete: 'off', placeholder: 'Name or email' });
    var recipientResults = el('div', { class: 'aig-pack-recipient-results' });
    var chosen = el('div', { class: 'aig-chosen', text: 'No recipient selected.' });
    var expiry = el('input', { type: 'number', min: '1', max: '90', value: '30', required: true });
    var people = el('input', { type: 'checkbox' });
    var notes = el('input', { type: 'checkbox' });
    var download = el('input', { type: 'checkbox' });
    var previewButton = el('button', { type: 'submit', class: 'btn btn-secondary', text: 'Preview pack' });
    var issueButton = el('button', { type: 'button', class: 'btn btn-primary', text: 'Issue this pack', hidden: true });
    var message = el('div', { class: 'aig-say', role: 'status' });
    var previewBox = el('div');
    var recipientId = null, token = null, recipientRequest = 0;
    form.appendChild(A.field('aigPackName', 'Pack name', name).row);
    form.appendChild(A.field('aigPackPurpose', 'Purpose', purpose).row);
    form.appendChild(A.field('aigPackRecipient', 'Recipient', recipientSearch, 'Search for a person who can receive review packs.').row);
    form.appendChild(chosen); form.appendChild(recipientResults);
    form.appendChild(A.field('aigPackExpiry', 'Expires after days', expiry, 'Choose 1 to 90 days.').row);
    [[people, 'Include names of people'], [notes, 'Include notes'], [download, 'Allow the recipient to download JSON']].forEach(function (entry) {
      form.appendChild(el('label', { class: 'aig-check' }, [entry[0], el('span', { text: entry[1] })]));
    });
    form.appendChild(el('div', { class: 'aig-actions' }, [previewButton, issueButton]));
    panel.appendChild(form); panel.appendChild(message); panel.appendChild(previewBox); root.appendChild(panel);

    function invalidate() { token = null; issueButton.hidden = true; clear(previewBox); say(message, ''); }
    function options() {
      return { name: name.value.trim(), purpose: purpose.value.trim(), recipient_id: recipientId,
        expires_days: Number(expiry.value), include_people: people.checked, include_notes: notes.checked, allow_download: download.checked };
    }
    [name, purpose, expiry, people, notes, download].forEach(function (input) { input.addEventListener('input', invalidate); input.addEventListener('change', invalidate); });
    recipientSearch.addEventListener('input', function () {
      recipientId = null; chosen.textContent = 'No recipient selected.'; invalidate(); clear(recipientResults);
    });
    recipientSearch.addEventListener('input', A.debounce(function () {
      var q = recipientSearch.value.trim(), own = ++recipientRequest;
      if (q.length < 2) return;
      A.api(API + '/pack-recipients' + A.qs({ q: q })).then(function (response) {
        if (own !== recipientRequest) return;
        var rows = response.items || [];
        if (!rows.length) recipientResults.appendChild(el('p', { class: 'aig-muted', text: 'No eligible people found.' }));
        rows.forEach(function (person) {
          recipientResults.appendChild(el('button', { type: 'button', class: 'aig-result', text: person.name + ' · ' + person.email,
            on: { click: function () {
              recipientRequest++;
              recipientId = person.id; chosen.textContent = 'Selected: ' + person.name + ' · ' + person.email;
              recipientSearch.value = person.name; clear(recipientResults); invalidate();
            } } }));
        });
      }).catch(function (error) { if (own === recipientRequest) say(message, A.errorText(error), 'bad'); });
    }, 250));
    form.addEventListener('submit', function (event) {
      event.preventDefault(); invalidate();
      previewButton.disabled = true; say(message, 'Preparing preview…');
      A.api(API + '/systems/' + appId + '/packs/preview', 'POST', options()).then(function (result) {
        clear(previewBox); say(message, 'Preview prepared. Review the details below.');
        previewBox.appendChild(el('h3', { class: 'aig-h3', text: 'What will be shared' }));
        previewBox.appendChild(el('p', { class: 'aig-muted', text: result.manifest.disclaimer || '' }));
        previewBox.appendChild(el('p', { text: 'Recipient: ' + (result.recipient ? result.recipient.name : 'Not selected') }));
        previewBox.appendChild(el('p', { text: 'Expires after ' + result.options.expires_days + ' days. Download ' + (result.options.allow_download ? 'allowed' : 'disabled') + '.' }));
        previewBox.appendChild(el('ul', { class: 'aig-pack-preview-list' }, (result.manifest.sections || []).map(sectionPreview)));
        if (result.manifest.summary && result.manifest.summary.not_shown && result.manifest.summary.not_shown.length) {
          previewBox.appendChild(el('p', { class: 'aig-banner aig-banner-warn', text: 'Not included: ' + result.manifest.summary.not_shown.join(', ') }));
        }
        var problems = result.problems || {};
        if (Object.keys(problems).length) {
          var warning = el('div', { class: 'aig-errorsummary' }, [el('p', { text: 'Fix these details before issuing:' })]);
          warning.appendChild(el('ul', {}, Object.keys(problems).map(function (key) { return el('li', { text: problems[key] }); })));
          previewBox.appendChild(warning);
        } else { token = result.hash; issueButton.hidden = false; }
      }).catch(function (error) { say(message, A.errorText(error), 'bad'); })
        .finally(function () { previewButton.disabled = false; });
    });
    issueButton.addEventListener('click', function () {
      if (!token) return;
      var expected = token;
      issueButton.disabled = true; say(message, 'Issuing pack…');
      A.api(API + '/systems/' + appId + '/packs', 'POST', Object.assign(options(), { expected_hash: expected }))
        .then(function (result) { global.location.assign(link(result.pack)); })
        .catch(function (error) { invalidate(); say(message, error.status === 409 ? 'The record changed. Preview the pack again before issuing.' : A.errorText(error), 'bad'); })
        .finally(function () { issueButton.disabled = false; });
    });
  }

  function issued(root, appId) {
    var panel = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigIssuedTitle' });
    panel.appendChild(el('h2', { id: 'aigIssuedTitle', class: 'aig-h2', text: 'Issued for this AI use' }));
    var status = el('div', { class: 'aig-say', role: 'status', text: 'Loading issued packs…' }), list = el('div');
    panel.appendChild(status); panel.appendChild(list); root.appendChild(panel);
    A.api(API + '/systems/' + appId + '/packs').then(function (data) { say(status, ''); packList(list, data.packs || [], true); })
      .catch(function (error) { say(status, A.errorText(error), 'bad'); });
  }

  function manage(root) {
    var id = root.dataset.packId, version = Number(root.dataset.version), state = root.dataset.state;
    root.appendChild(el('h2', { class: 'aig-h2', text: 'Pack management' }));
    var status = el('div', { class: 'aig-say', role: 'status' });
    root.appendChild(status);
    if (state === 'open') root.appendChild(el('button', { type: 'button', class: 'btn btn-secondary', text: 'Withdraw access', on: { click: function () {
      A.dialog('Withdraw this pack', function (box, close) {
        box.appendChild(el('p', { text: 'The recipient will lose access immediately. The issued record and access history remain available to managers.' }));
        var reason = el('textarea', { rows: '3', maxlength: '500' });
        box.appendChild(A.field('aigPackRevokeReason', 'Reason for withdrawal', reason).row);
        var feedback = el('div', { class: 'aig-say', role: 'status' });
        var confirm = el('button', { type: 'button', class: 'btn btn-primary', text: 'Withdraw access', on: { click: function () {
          confirm.disabled = true;
          A.api(API + '/packs/' + id + '/revoke', 'POST', { reason: reason.value.trim(), version: version })
            .then(function () { close(); global.location.reload(); })
            .catch(function (error) { say(feedback, A.errorText(error), 'bad'); confirm.disabled = false; });
        } } });
        box.appendChild(el('div', { class: 'aig-actions' }, [confirm, el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
        box.appendChild(feedback);
      });
    } } }));
    var changes = el('div'), history = el('div'); root.appendChild(changes); root.appendChild(history);
    say(status, 'Loading management details…');
    Promise.all([A.api(API + '/packs/' + id + '/changes'), A.api(API + '/packs/' + id + '/history')])
      .then(function (results) {
        say(status, '');
        var diff = results[0], log = results[1];
        changes.appendChild(el('h3', { class: 'aig-h3', text: 'Since this snapshot' }));
        changes.appendChild(el('p', { text: diff.same ? 'The current record matches this snapshot.' : 'The current record has changed since this snapshot.' }));
        if (!diff.same) changes.appendChild(el('ul', {}, (diff.changed || []).map(function (value) { return el('li', { text: typeof value === 'string' ? value : (value.title || value.key || 'Changed section') }); })));
        history.appendChild(el('h3', { class: 'aig-h3', text: 'Access history' }));
        if (!log.events.length) history.appendChild(el('p', { class: 'aig-muted', text: 'No access yet.' }));
        else history.appendChild(el('ul', { class: 'aig-pack-history' }, log.events.map(function (event) {
          return el('li', { text: date(event.at) + ' · ' + (event.who || 'Unknown user') + ' · ' + event.action + (event.reason ? ' · ' + event.reason : '') });
        })));
      }).catch(function (error) { say(status, A.errorText(error), 'bad'); });
  }

  function mount() {
    var listing = document.getElementById('aigPacks');
    if (listing) {
      var canManage = listing.dataset.canManage === '1', appId = Number(listing.dataset.applicationId);
      if (canManage) { if (appId > 0) { prepare(listing, appId); issued(listing, appId); } else systemPicker(listing); }
      mine(listing);
    }
    var detail = document.getElementById('aigPackManage');
    if (detail) manage(detail);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
}(window));
