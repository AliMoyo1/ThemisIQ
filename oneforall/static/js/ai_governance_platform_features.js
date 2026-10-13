/* ThemisIQ platform AI feature oversight. Server text is rendered as text nodes. */
(function (global) {
  'use strict';
  var A = global.AIGov, el = A.el, API = '/ai-governance/api/platform-features';
  var host = document.getElementById('aigPlatformFeatures');
  if (!host) return;
  var items = [], query = '', state = 'all';
  var status = el('div', { class: 'aig-say', role: 'status', text: 'Loading platform features...' });
  var content = el('div');
  host.appendChild(status);
  host.appendChild(content);

  function button(label, onClick, primary) {
    return el('button', { type: 'button', class: 'btn ' + (primary ? 'btn-primary' : 'btn-secondary'), text: label,
      on: { click: onClick } });
  }
  function showError(err) { A.say(status, A.errorText(err), 'bad'); }
  function date(value) { return A.date(value) || 'Not set'; }
  function stateLabel(item) {
    if (item.review_state === 'overdue') return 'Review overdue';
    if (item.review_state === 'reviewed') return 'Reviewed';
    return 'Not reviewed';
  }
  function reviewChip(item) {
    return A.chip(stateLabel(item), item.review_state === 'reviewed' ? 'good' :
      (item.review_state === 'overdue' ? 'bad' : 'warn'));
  }
  function summary() {
    var reviewed = items.filter(function (item) { return item.review_state === 'reviewed'; }).length;
    var overdue = items.filter(function (item) { return item.review_state === 'overdue'; }).length;
    var pending = items.length - reviewed - overdue;
    var wrap = el('div', { class: 'aig-platform-summary' });
    [[items.length, 'Registered call sites'], [reviewed, 'Reviewed'], [overdue, 'Review overdue'],
      [pending, 'Not reviewed']].forEach(function (pair) {
      wrap.appendChild(el('div', { class: 'aig-platform-stat' }, [
        el('strong', { text: String(pair[0]) }), el('span', { text: pair[1] })]));
    });
    return wrap;
  }
  function definition(label, value) {
    return el('div', {}, [el('dt', { text: label }), el('dd', { text: value })]);
  }
  function card(item) {
    var box = el('li', { class: 'aig-platform-card' });
    var head = el('div', { class: 'aig-platform-top' }, [
      el('div', {}, [el('h2', { text: item.label }), el('div', { class: 'aig-platform-key', text: item.key })]),
      el('div', { class: 'aig-chips' }, [reviewChip(item), A.chip(item.deployment.replace('_', ' '))])
    ]);
    var meta = el('dl', { class: 'aig-platform-meta' }, [
      definition('Data sent', item.categories.join(', ')),
      definition('Owner', item.owner || 'Not recorded'),
      definition('Successful calls', String(item.usage.successful)),
      definition('Refused / errors', item.usage.refused + ' / ' + item.usage.errors),
      definition('Last successful use', date(item.usage.last_used_at)),
      definition('Next review', date(item.review_due)),
      definition('Last reviewed', item.last_reviewed_at ? date(item.last_reviewed_at) +
        (item.last_reviewed_by_name ? ' by ' + item.last_reviewed_by_name : '') : 'Not recorded')
    ]);
    var actions = el('div', { class: 'aig-platform-actions' }, [
      button('Open oversight notes', function () { edit(item); }),
      item.review_state !== 'reviewed' ? button('Mark reviewed', function () { confirmReview(item); }) : null
    ]);
    box.appendChild(head); box.appendChild(meta); box.appendChild(actions);
    return box;
  }
  function render() {
    A.clear(content);
    content.appendChild(summary());
    var search = el('input', { type: 'search', value: query, placeholder: 'Search features, keys, owners or categories',
      'aria-label': 'Search platform AI features', on: { input: function () { query = this.value; renderList(); } } });
    var select = el('select', { 'aria-label': 'Filter by review state', on: { change: function () { state = this.value; renderList(); } } });
    [['all', 'All review states'], ['not_reviewed', 'Not reviewed'], ['overdue', 'Overdue'],
      ['reviewed', 'Reviewed']].forEach(function (choice) {
      select.appendChild(el('option', { value: choice[0], text: choice[1] }));
    });
    select.value = state;
    var tools = el('div', { class: 'aig-platform-tools' }, [
      el('div', { class: 'aig-field' }, [el('label', { text: 'Find a feature' }), search]),
      el('div', { class: 'aig-field' }, [el('label', { text: 'Review state' }), select])
    ]);
    var count = el('p', { class: 'aig-muted', role: 'status' });
    var list = el('ul', { class: 'aig-platform-list' });
    content.appendChild(tools); content.appendChild(count); content.appendChild(list);
    function renderList() {
      A.clear(list);
      var needle = query.toLowerCase().trim();
      var shown = items.filter(function (item) {
        return (state === 'all' || item.review_state === state) &&
          (!needle || [item.label, item.key, item.owner].concat(item.categories).join(' ').toLowerCase().indexOf(needle) >= 0);
      });
      count.textContent = shown.length + ' of ' + items.length + ' features';
      if (!shown.length) { list.appendChild(el('li', { class: 'aig-empty', text: 'No features match these filters.' })); return; }
      shown.forEach(function (item) { list.appendChild(card(item)); });
    }
    renderList();
  }
  function field(label, control, hint) {
    var row = el('div', { class: 'aig-field' });
    var id = 'aigPlatform' + label.replace(/[^a-zA-Z]/g, '');
    control.id = id;
    row.appendChild(el('label', { for: id, text: label })); row.appendChild(control);
    if (hint) row.appendChild(el('small', { class: 'aig-muted', text: hint }));
    return row;
  }
  function edit(item) {
    A.dialog(item.label, function (box, close) {
      box.classList.add('aig-platform-dialog');
      var notice = el('p', { class: 'aig-muted', text: 'Changing notes clears the completed review. Save, then mark the feature reviewed.' });
      var owner = el('input', { type: 'text', maxlength: 160, value: item.owner });
      var provider = el('textarea', { rows: 3, maxlength: 500, text: item.provider_note });
      var limits = el('textarea', { rows: 4, maxlength: 2000, text: item.known_limitations });
      var incident = el('textarea', { rows: 3, maxlength: 1000, text: item.incident_path });
      var deployment = el('select');
      [['in_service', 'In service'], ['paused', 'Paused'], ['retired', 'Retired']].forEach(function (choice) {
        deployment.appendChild(el('option', { value: choice[0], text: choice[1] }));
      });
      deployment.value = item.deployment;
      var due = el('input', { type: 'date', value: item.review_due || '' });
      var feedback = el('p', { class: 'aig-say', role: 'status' });
      var save = el('button', { type: 'submit', class: 'btn btn-primary', text: 'Save notes' });
      var form = el('form', { class: 'aig-form' }, [notice,
        field('Owner', owner), field('Provider and model', provider, 'Record what is known; this does not configure a provider.'),
        field('Known limitations', limits), field('Incident path', incident, 'How a platform AI issue is reported and escalated.'),
        field('Deployment decision', deployment, 'This records the decision; it does not switch a feature on or off.'),
        field('Next review', due), feedback,
        el('div', { class: 'aig-actions' }, [save, button('Cancel', close)])
      ]);
      form.addEventListener('submit', function (event) {
        event.preventDefault(); save.disabled = true; A.say(feedback, 'Saving...');
        A.api(API + '/' + encodeURIComponent(item.key), 'PUT', {
          version: item.version, owner: owner.value, provider_note: provider.value,
          known_limitations: limits.value, incident_path: incident.value,
          deployment: deployment.value, review_due: due.value
        }).then(function () { close(); refresh(); }).catch(function (err) {
          save.disabled = false; A.say(feedback, A.errorText(err), 'bad');
        });
      });
      box.appendChild(form);
    });
  }
  function confirmReview(item) {
    A.dialog('Complete feature review', function (box, close) {
      box.appendChild(el('p', { text: 'Confirm that the recorded owner, provider, limitations, incident path and next review date have been checked for ' + item.label + '.' }));
      var feedback = el('p', { class: 'aig-say', role: 'status' });
      var confirm = button('Mark reviewed', function () {
        confirm.disabled = true; A.say(feedback, 'Recording review...');
        A.api(API + '/' + encodeURIComponent(item.key) + '/review', 'POST', { version: item.version })
          .then(function () { close(); refresh(); }).catch(function (err) {
            confirm.disabled = false; A.say(feedback, A.errorText(err), 'bad');
          });
      }, true);
      box.appendChild(feedback);
      box.appendChild(el('div', { class: 'aig-actions' }, [confirm, button('Cancel', close)]));
    });
  }
  function refresh() {
    A.say(status, 'Loading platform features...');
    A.api(API).then(function (data) { items = data.items || []; A.say(status, ''); render(); })
      .catch(showError);
  }
  refresh();
})(window);
