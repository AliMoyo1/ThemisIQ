/* Human oversight is an organization record, not a legal conformity finding. */
(function (global) {
  'use strict';

  var AIGov = global.AIGov, el = AIGov.el;
  var TRACKS = [
    { id: 'design', title: 'Design controls', description: 'How people will observe and control this use before it operates.' },
    { id: 'operation', title: 'Operating practice', description: 'How the responsible team observes, intervenes and escalates in day-to-day use.' }
  ];
  var FIELDS = [
    { id: 'monitoring_method', title: 'What people monitor', hint: 'Name the signals, who checks them and when.' },
    { id: 'intervention_method', title: 'How people intervene', hint: 'Explain what a person can change, override or pause.' },
    { id: 'stop_procedure', title: 'How to stop the use', hint: 'Give a concrete stop or fallback procedure.' },
    { id: 'escalation_path', title: 'When and where to escalate', hint: 'Name the route for concerns and incidents.' }
  ];

  AIGov.oversightPanel = function (host, config) {
    var base = '/ai-governance/api/systems/' + config.applicationId + '/oversight/';
    var status = el('div', { class: 'aig-say', role: 'status' });
    var cards = el('div', { class: 'aig-oversight-grid' });
    host.appendChild(el('p', { class: 'aig-hint', text: 'Record your team\'s human oversight arrangement. A reviewed record is an internal review, not a legal conformity decision.' }));
    host.appendChild(status);
    host.appendChild(cards);

    function fieldView(label, value) {
      return el('div', { class: 'aig-oversight-field' }, [el('strong', { text: label }),
        el('span', { text: value || 'Not recorded yet' })]);
    }

    function versionView(version, historical) {
      var box = el('div', {});
      var state = version.profile_changed ? 'Profile changed since this version' :
        (version.status === 'reviewed' ? 'Reviewed' : 'Draft, awaiting review');
      box.appendChild(el('div', { class: 'aig-meta' }, [
        AIGov.chip('Version ' + version.version),
        AIGov.chip(state, version.profile_changed ? 'warn' : version.status === 'reviewed' ? 'good' : 'muted')]));
      box.appendChild(el('p', { class: 'aig-hint', text: 'Recorded by ' + (version.author_name || 'a colleague') + ' on ' + AIGov.date(version.authored_at) +
        (version.reviewed_at ? '. Reviewed by ' + (version.reviewer_name || 'a colleague') + ' on ' + AIGov.date(version.reviewed_at) : '') + '.' }));
      box.appendChild(fieldView('Responsible person', version.responsible_name));
      FIELDS.forEach(function (field) { box.appendChild(fieldView(field.title, version[field.id])); });
      if (historical) box.className = 'aig-oversight-history-entry';
      return box;
    }

    function render(track, data) {
      var record = data.oversight, current = record.current;
      var card = el('section', { class: 'aig-panel' }, [el('h2', { class: 'aig-h3', text: track.title }),
        el('p', { class: 'aig-hint', text: track.description })]);
      if (!record.profile_version) {
        card.appendChild(el('p', { class: 'aig-note-warn', text: 'Add the AI profile before recording this arrangement.' }));
      } else if (current) {
        card.appendChild(versionView(current, false));
      } else {
        card.appendChild(el('p', { class: 'aig-note-muted', text: 'No arrangement recorded. Start with a draft that names the responsible person and procedures.' }));
      }
      var actions = el('div', { class: 'aig-actions' });
      if (record.profile_version && config.canReview) {
        actions.appendChild(el('button', { type: 'button', class: 'btn btn-secondary btn-sm',
          text: current ? 'Create a new version' : 'Create draft',
          on: { click: function () { edit(track, record); } } }));
      }
      if (current && current.status === 'draft' && !current.profile_changed && config.canDecide &&
          current.authored_by !== config.viewerId && current.responsible_user_id &&
          FIELDS.every(function (field) { return !!current[field.id]; })) {
        actions.appendChild(el('button', { type: 'button', class: 'btn btn-primary btn-sm', text: 'Review this version',
          on: { click: function () { review(track, record); } } }));
      }
      card.appendChild(actions);
      if (current && current.status === 'draft' && current.authored_by === config.viewerId) {
        card.appendChild(el('p', { class: 'aig-hint', text: 'Ask another authorized reviewer to review this version.' }));
      }
      if (record.history.length) {
        var history = el('details', { class: 'aig-oversight-history' },
          [el('summary', { text: 'Earlier versions (' + record.history.length + ' shown)' })]);
        record.history.forEach(function (version) { history.appendChild(versionView(version, true)); });
        card.appendChild(history);
      }
      var slot = cards.querySelector('[data-track="' + track.id + '"]');
      card.setAttribute('data-track', track.id);
      if (slot) cards.replaceChild(card, slot); else cards.appendChild(card);
    }

    function load(track) {
      return AIGov.api(base + track.id).then(function (data) { render(track, data); return data; })
        .catch(function (err) {
          var slot = cards.querySelector('[data-track="' + track.id + '"]');
          var note = el('section', { class: 'aig-panel', 'data-track': track.id }, [
            el('h2', { class: 'aig-h3', text: track.title }),
            el('p', { class: 'aig-note-warn', text: AIGov.errorText(err) })]);
          if (slot) cards.replaceChild(note, slot); else cards.appendChild(note);
        });
    }

    function edit(track, record) {
      var current = record.current || {};
      AIGov.dialog('Oversight draft: ' + track.title, function (box, close) {
        var form = el('form', { class: 'aig-form' });
        var output = el('div', { class: 'aig-say', role: 'status' });
        var selected = current.responsible_user_id || null;
        var selectedName = current.responsible_name || '';
        var search = el('input', { type: 'search', value: selectedName, autocomplete: 'off', placeholder: 'Search people' });
        var found = el('div', { class: 'aig-queue', role: 'group', 'aria-label': 'People matching the search' });
        var chosen = el('div', { class: 'aig-chosen', text: selected ? 'Chosen: ' + selectedName : 'No person chosen' });
        var queryNumber = 0;
        var searchPeople = AIGov.debounce(function () {
          var q = search.value.trim();
          if (q.length < 2) return;
          var requestNumber = ++queryNumber;
          AIGov.api('/ai-governance/api/systems/' + config.applicationId + '/oversight-people' + AIGov.qs({ q: q })).then(function (data) {
            if (requestNumber !== queryNumber || search.value.trim() !== q) return;
            AIGov.clear(found);
            (data.items || []).forEach(function (person) {
              found.appendChild(el('button', { type: 'button', class: 'aig-queue-item', text: person.name,
                on: { click: function () { selected = person.id; selectedName = person.name;
                  search.value = person.name; chosen.textContent = 'Chosen: ' + person.name; AIGov.clear(found); } } }));
            });
          }).catch(function (err) { AIGov.say(output, AIGov.errorText(err), 'bad'); });
        }, 220);
        search.addEventListener('input', function () {
          selected = null;
          chosen.textContent = 'Choose a person from the results';
          AIGov.clear(found);
          queryNumber += 1;
          searchPeople();
        });
        form.appendChild(AIGov.field('aigOversightPerson', 'Responsible person', search,
          'Choose a person from the search results.').row);
        form.appendChild(chosen);
        form.appendChild(found);
        var inputs = {};
        FIELDS.forEach(function (field) {
          inputs[field.id] = el('textarea', { rows: '3', maxlength: '2000', value: current[field.id] || '' });
          form.appendChild(AIGov.field('aigOversight_' + field.id, field.title, inputs[field.id], field.hint).row);
        });
        form.appendChild(output);
        form.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'submit', class: 'btn btn-primary', text: 'Save draft' }),
          el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
        form.addEventListener('submit', function (event) {
          event.preventDefault();
          var arrangement = { responsible_user_id: selected };
          FIELDS.forEach(function (field) { arrangement[field.id] = inputs[field.id].value; });
          AIGov.say(output, 'Saving...');
          AIGov.api(base + track.id, 'PUT', { revision: record.revision, arrangement: arrangement })
            .then(function () { close(); AIGov.say(status, 'Oversight draft saved.'); return load(track); })
            .catch(function (err) { AIGov.say(output, AIGov.errorText(err), 'bad'); });
        });
        box.appendChild(form);
      });
    }

    function review(track, record) {
      AIGov.dialog('Review ' + track.title, function (box, close) {
        var output = el('div', { class: 'aig-say', role: 'status' });
        box.appendChild(el('p', { text: 'Confirm that you reviewed version ' + record.current.version + ' against the current AI profile. This records an internal review only.' }));
        box.appendChild(output);
        box.appendChild(el('div', { class: 'aig-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary', text: 'Mark reviewed', on: { click: function () {
            AIGov.say(output, 'Recording review...');
            AIGov.api(base + track.id + '/review', 'POST', { revision: record.revision })
              .then(function () { close(); AIGov.say(status, 'Review recorded.'); return load(track); })
              .catch(function (err) { AIGov.say(output, AIGov.errorText(err), 'bad'); });
          } } }), el('button', { type: 'button', class: 'btn btn-ghost', text: 'Cancel', on: { click: close } })]));
      });
    }

    TRACKS.forEach(function (track) { load(track); });
  };
})(window);
