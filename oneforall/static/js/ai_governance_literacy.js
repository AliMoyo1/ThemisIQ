/* AI literacy: current assignments, immutable course editions and coverage. All untrusted text is a text node. */
(function (global) {
  'use strict';
  var A = global.AIGov, el = A.el, API = '/ai-governance/api/literacy';
  function clear(node) { return A.clear(node); }
  function say(node, message, kind) { A.say(node, message, kind); }
  function date(value) { return A.date(value) || 'Not recorded'; }
  function button(label, click, primary) { return el('button', { type: 'button', class: 'btn ' + (primary ? 'btn-primary' : 'btn-secondary'), text: label, on: { click: click } }); }
  function confirmAction(title, message, proceed) {
    A.dialog(title, function (box, close) {
      box.appendChild(el('p', { text: message }));
      box.appendChild(el('div', { class: 'aig-actions' }, [
        button('Cancel', close),
        button('Continue', function () { close(); proceed(); }, true)
      ]));
    });
  }
  function courseLink(id) { return '/ai-governance/literacy/' + encodeURIComponent(id); }
  function statusLabel(value) { return ({ to_do: 'To do', overdue: 'Overdue', expired: 'Expired', completed: 'Completed' })[value] || value; }
  function statusChip(value) { return A.chip(statusLabel(value), value === 'completed' ? 'good' : (value === 'to_do' ? 'info' : 'warn')); }
  function error(status, err) { say(status, A.errorText(err), 'bad'); }

  function myCourses(host) {
    clear(host);
    var status = el('div', { role: 'status', class: 'aig-say', text: 'Loading your courses...' });
    var list = el('div');
    host.appendChild(status); host.appendChild(list);
    A.api(API + '/mine').then(function (data) {
      say(status, ''); clear(list);
      var items = data.items || [];
      if (!items.length) { list.appendChild(el('p', { class: 'aig-empty', text: 'No AI literacy courses are assigned to you.' })); return; }
      var cards = el('ul', { class: 'aig-literacy-cards' });
      items.forEach(function (item) {
        cards.appendChild(el('li', { class: 'aig-literacy-card' }, [
          el('h3', {}, el('a', { href: courseLink(item.id), text: item.title })),
          statusChip(item.state),
          item.summary ? el('p', { text: item.summary }) : null,
          el('p', { class: 'aig-muted', text: item.state === 'completed' ? 'Renews ' + date(item.renew_at) : 'Due ' + date(item.due_at) }),
          el('a', { href: courseLink(item.id), class: 'btn btn-secondary btn-sm', text: item.state === 'completed' ? 'Review course' : 'Open course' })
        ]));
      });
      list.appendChild(cards);
    }).catch(function (err) { error(status, err); });
  }

  function labeled(id, label, input, hint) { return A.field(id, label, input, hint).row; }
  function fieldInput(type, value, attrs) {
    var options = { type: type, value: value === null || value === undefined ? '' : String(value) };
    Object.keys(attrs || {}).forEach(function (key) { options[key] = attrs[key]; });
    return el('input', options);
  }
  function textarea(value, rows) { return el('textarea', { rows: rows || 4, text: value || '' }); }

  function manager(host) {
    clear(host);
    var status = el('div', { role: 'status', class: 'aig-say' });
    var list = el('div'), editor = el('div');
    host.appendChild(status); host.appendChild(list); host.appendChild(editor);
    var courses = [], roles = [], units = [], questionCounter = 0;
    function refresh(selected) {
      say(status, 'Loading courses...');
      Promise.all([A.api(API + '/courses'), A.api(API + '/units')]).then(function (results) {
        courses = results[0].items || []; roles = results[0].roles || []; units = results[1].items || [];
        say(status, ''); renderList();
        if (selected) {
          var found = courses.filter(function (item) { return item.id === selected; })[0];
          if (found) edit(found);
        }
      }).catch(function (err) { error(status, err); });
    }
    function renderList() {
      clear(list);
      var head = el('div', { class: 'aig-actions' }, [button('New course', function () { edit(null); }, true)]);
      list.appendChild(head);
      if (!courses.length) { list.appendChild(el('p', { class: 'aig-empty', text: 'No courses yet. Create a draft, choose its audience, then publish it.' })); return; }
      var cards = el('ul', { class: 'aig-literacy-cards' });
      courses.forEach(function (course) {
        cards.appendChild(el('li', { class: 'aig-literacy-card' }, [
          el('h3', { text: course.title }), A.chip(course.status),
          el('p', { class: 'aig-muted', text: 'Edition ' + course.current_version + ' · ' + (course.business_unit_id ? 'Business unit' : 'Organization wide') }),
          course.status === 'retired' ? el('p', { class: 'aig-muted', text: 'Retired. Past completions remain recorded.' }) :
            el('div', { class: 'aig-actions' }, [button('Edit working copy', function () { edit(course); }),
              course.status === 'active' ? button('View coverage', function () { showCoverage(course.id); }) : null])
        ]));
      });
      list.appendChild(cards);
    }
    function questionEditor(host, question, changed) {
      var box = el('div', { class: 'aig-literacy-question-edit' });
      var questionId = ++questionCounter;
      var prompt = fieldInput('text', question ? question.prompt : '', { maxlength: '1000' });
      var options = textarea(question ? (question.options || []).join('\n') : '', 4);
      var correct = fieldInput('number', question ? question.correct + 1 : 1, { min: '1', max: '6', step: '1' });
      box.appendChild(labeled('aigLiteracyPrompt' + questionId, 'Question', prompt));
      box.appendChild(labeled('aigLiteracyOptions' + questionId, 'Answer options, one per line', options, 'Add 2 to 6 options.'));
      box.appendChild(labeled('aigLiteracyCorrect' + questionId, 'Number of the correct option', correct, '1 is the first option. Learners never see this number.'));
      box.appendChild(button('Remove question', function () { box.remove(); if (changed) changed(); }));
      box.readQuestion = function () {
        return { prompt: prompt.value.trim(), options: options.value.split(/\r?\n/).map(function (s) { return s.trim(); }).filter(Boolean),
          correct: Number(correct.value) - 1 };
      };
      host.appendChild(box);
    }
    function edit(course) {
      clear(editor);
      var editing = !!course, state = course || {};
      var panel = el('section', { class: 'aig-panel' });
      panel.appendChild(el('h2', { class: 'aig-h2', text: editing ? 'Working copy: ' + course.title : 'New course' }));
      panel.appendChild(el('p', { class: 'aig-muted', text: editing ? 'Saved content stays in the working copy until publication. Audience and due time changes take effect when saved. Renewal changes apply to future completions.' : 'Start with a title, then add content and an audience.' }));
      var notice = el('div', { role: 'status', class: 'aig-say' });
      var form = el('form', { class: 'aig-literacy-editor' });
      var dirty = false;
      var publishButtons = [];
      function markDirty() {
        dirty = true;
        publishButtons.forEach(function (item) { item.disabled = true; });
        if (publishButtons.length) say(notice, 'Save the working copy before publishing.', 'bad');
      }
      form.addEventListener('input', markDirty);
      form.addEventListener('change', markDirty);
      var title = fieldInput('text', state.title || '', { maxlength: '200', required: true });
      var summary = textarea(state.summary, 2), body = textarea(state.body, 12);
      var unit = el('select'); unit.appendChild(el('option', { value: '', text: 'Organization wide' }));
      units.forEach(function (item) { unit.appendChild(el('option', { value: String(item.id), text: item.name, selected: item.id === state.business_unit_id })); });
      var renewal = fieldInput('number', state.renewal_months || 12, { min: '1', max: '60' });
      var due = fieldInput('number', state.due_days || 30, { min: '1', max: '365' });
      var owners = el('input', { type: 'checkbox', checked: !!state.audience_owners });
      var mark = fieldInput('number', state.pass_mark || 80, { min: '1', max: '100' });
      form.appendChild(labeled('aigLiteracyTitle', 'Course title', title));
      form.appendChild(labeled('aigLiteracySummary', 'Short summary', summary));
      form.appendChild(labeled('aigLiteracyUnit', 'Audience business unit', unit, 'People in this unit and its active child units.'));
      form.appendChild(labeled('aigLiteracyDue', 'Days to complete', due));
      form.appendChild(labeled('aigLiteracyRenew', 'Renew after months', renewal));
      form.appendChild(labeled('aigLiteracyMark', 'Pass mark for a knowledge check', mark));
      var roleBox = el('fieldset', { class: 'aig-fieldset aig-wide' }, [el('legend', { text: 'Audience' }),
        el('p', { class: 'aig-muted', text: 'Assign to people with any selected role or to owners of active AI uses.' })]);
      var roleGrid = el('div', { class: 'aig-literacy-roles' });
      var roleInputs = {};
      roles.forEach(function (role) {
        var check = el('input', { type: 'checkbox', checked: (state.audience_roles || []).indexOf(role) >= 0 });
        roleInputs[role] = check;
        roleGrid.appendChild(el('label', { class: 'aig-check' }, [check, role.replace(/_/g, ' ')]));
      });
      roleBox.appendChild(roleGrid);
      roleBox.appendChild(el('label', { class: 'aig-check' }, [owners, 'Owners of active AI uses']));
      form.appendChild(roleBox);
      var bodyRow = labeled('aigLiteracyBody', 'Course content', body, 'Plain text. Published editions are kept for historical completions.');
      bodyRow.classList.add('aig-wide'); form.appendChild(bodyRow);
      var questions = el('div', { class: 'aig-wide' });
      questions.appendChild(el('h3', { class: 'aig-h3', text: 'Knowledge check (optional)' }));
      questions.appendChild(el('p', { class: 'aig-muted', text: 'Without questions, learners explicitly acknowledge the course.' }));
      var questionList = el('div'); questions.appendChild(questionList);
      (state.questions || []).forEach(function (q) { questionEditor(questionList, q, markDirty); });
      questions.appendChild(button('Add question', function () {
        if (questionList.children.length >= 20) { say(notice, 'A course can have at most 20 questions.', 'bad'); return; }
        questionEditor(questionList, null, markDirty); markDirty();
      }));
      form.appendChild(questions);
      function payload() {
        return { title: title.value.trim(), summary: summary.value.trim(), body: body.value.trim(),
          business_unit_id: unit.value ? Number(unit.value) : null,
          renewal_months: Number(renewal.value), due_days: Number(due.value), pass_mark: Number(mark.value),
          audience_roles: roles.filter(function (r) { return roleInputs[r].checked; }),
          audience_owners: owners.checked,
          questions: Array.prototype.map.call(questionList.children, function (box) { return box.readQuestion(); }) };
      }
      function save(event) {
        event.preventDefault();
        if (!form.reportValidity()) return;
        say(notice, 'Saving...');
        var data = payload();
        if (editing) data.version = state.version;
        A.api(API + '/courses' + (editing ? '/' + state.id : ''), editing ? 'PUT' : 'POST', data)
          .then(function (result) { state = result.course; editing = true; say(notice, 'Saved.', 'good'); refresh(state.id); })
          .catch(function (err) { error(notice, err); });
      }
      form.addEventListener('submit', save);
      form.appendChild(el('button', { type: 'submit', class: 'btn btn-primary aig-wide', text: 'Save working copy' }));
      panel.appendChild(form);
      if (editing && state.status !== 'retired') {
        var actions = el('div', { class: 'aig-actions' });
        function publish(retake) {
          var text = retake ? 'Publish a new edition and require everyone to complete it again?' : 'Publish a new edition without a new retake requirement? New learners will see the latest edition.';
          if (dirty) { say(notice, 'Save the working copy before publishing.', 'bad'); return; }
          confirmAction('Publish course edition', text, function () {
            say(notice, 'Publishing...');
            A.api(API + '/courses/' + state.id + '/publish', 'POST', { version: state.version, retake: retake })
              .then(function (result) { say(notice, 'Edition ' + result.course.current_version + ' published.', 'good'); refresh(state.id); })
              .catch(function (err) { error(notice, err); });
          });
        }
        var requireRetake = button('Publish and require retake', function () { publish(true); }, true);
        publishButtons.push(requireRetake); actions.appendChild(requireRetake);
        if (state.current_version) {
          var noRetake = button('Publish without retake', function () { publish(false); });
          publishButtons.push(noRetake); actions.appendChild(noRetake);
        }
        actions.appendChild(button('Retire course', function () {
          confirmAction('Retire course', 'Retire this course? Existing completions stay in the record.', function () {
            A.api(API + '/courses/' + state.id + '/retire', 'POST', { version: state.version })
              .then(function () { clear(editor); refresh(); }).catch(function (err) { error(notice, err); });
          });
        }));
        panel.appendChild(actions);
      }
      panel.appendChild(notice); editor.appendChild(panel); title.focus();
    }
    function showCoverage(id) {
      var tab = document.querySelector('[data-literacy-tab="coverage"]');
      if (tab) tab.click();
      var reportPanel = tab ? document.getElementById(tab.getAttribute('aria-controls')) : null;
      if (reportPanel && reportPanel._showCoverage) reportPanel._showCoverage(id);
    }
    refresh();
  }

  function report(host) {
    clear(host);
    var status = el('div', { role: 'status', class: 'aig-say', text: 'Loading coverage...' });
    var list = el('div'), detail = el('div');
    host.appendChild(el('p', { class: 'aig-banner aig-banner-info', text: 'Coverage counts only AI literacy courses. BCM attestations and Sentinel training sessions remain separate records.' }));
    host.appendChild(status); host.appendChild(list); host.appendChild(detail);
    host._showCoverage = function (id) {
      clear(detail); say(status, 'Loading people...');
      A.api(API + '/coverage/' + encodeURIComponent(id)).then(function (data) {
        say(status, '');
        var course = data.course;
        detail.appendChild(el('h3', { class: 'aig-h2', text: course.title + ': people in your reporting scope' }));
        if (!course.people.length) { detail.appendChild(el('p', { class: 'aig-empty', text: 'No people in this audience and reporting scope.' })); return; }
        var wrap = el('div', { class: 'aig-tablewrap aig-literacy-report' });
        var table = el('table', { class: 'aig-table' });
        table.appendChild(el('thead', {}, el('tr', {}, ['Person', 'State', 'Due', 'Completed', 'Renews'].map(function (label) { return el('th', { scope: 'col', text: label }); }))));
        var body = el('tbody');
        course.people.forEach(function (person) {
          body.appendChild(el('tr', {}, [el('td', { text: person.name }), el('td', {}, statusChip(person.state)),
            el('td', { text: date(person.due_at) }), el('td', { text: date(person.completed_at) }), el('td', { text: date(person.renew_at) })]));
        });
        table.appendChild(body); wrap.appendChild(table); detail.appendChild(wrap);
        if (course.denominator > course.people.length) detail.appendChild(el('p', { class: 'aig-muted', text: 'Showing the first 200 people by name.' }));
      }).catch(function (err) { error(status, err); });
    };
    A.api(API + '/coverage').then(function (data) {
      say(status, '');
      var items = data.items || [];
      if (!items.length) { list.appendChild(el('p', { class: 'aig-empty', text: 'There are no active courses in your reporting scope.' })); return; }
      var cards = el('ul', { class: 'aig-literacy-cards' });
      items.forEach(function (course) {
        cards.appendChild(el('li', { class: 'aig-literacy-card' }, [
          el('h3', { text: course.title }),
          el('p', { text: course.completed + ' of ' + course.denominator + ' current' }),
          el('p', { class: 'aig-muted', text: course.overdue + ' overdue · ' + course.expired + ' expired · ' + course.to_do + ' to do' }),
          button('View people', function () { host._showCoverage(course.id); })
        ]));
      });
      list.appendChild(cards);
    }).catch(function (err) { error(status, err); });
  }

  function index(root) {
    var tabs = [], panels = [], names = [];
    if (root.dataset.canTake === '1') names.push(['mine', 'My courses', myCourses]);
    if (root.dataset.canManage === '1') names.push(['manage', 'Manage courses', manager]);
    if (root.dataset.canReport === '1') names.push(['coverage', 'Coverage', report]);
    var bar = el('div', { class: 'aig-tabs', role: 'tablist', 'aria-label': 'AI literacy' });
    root.appendChild(bar);
    names.forEach(function (entry, i) {
      var panel = el('section', { id: 'literacyPanel' + i, role: 'tabpanel', 'aria-labelledby': 'literacyTab' + i, hidden: i > 0, tabindex: '0' });
      var tab = el('button', { id: 'literacyTab' + i, type: 'button', role: 'tab', class: 'aig-tab' + (i === 0 ? ' is-current' : ''),
        'aria-controls': 'literacyPanel' + i, 'aria-selected': i === 0 ? 'true' : 'false', text: entry[1],
        'data-literacy-tab': entry[0], on: { click: function () { activate(i); } } });
      tabs.push(tab); panels.push(panel); bar.appendChild(tab); root.appendChild(panel);
    });
    function activate(index) {
      tabs.forEach(function (tab, i) {
        var chosen = i === index;
        tab.classList.toggle('is-current', chosen);
        tab.setAttribute('aria-selected', chosen ? 'true' : 'false');
        panels[i].hidden = !chosen;
      });
      if (!panels[index].dataset.loaded || names[index][0] !== 'mine') {
        panels[index].dataset.loaded = '1'; names[index][2](panels[index]);
      }
    }
    bar.addEventListener('keydown', function (event) {
      var current = tabs.indexOf(document.activeElement), next = current;
      if (current < 0) return;
      if (event.key === 'ArrowRight') next = (current + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') next = (current + tabs.length - 1) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      else return;
      event.preventDefault(); tabs[next].focus(); activate(next);
    });
    if (names.length) activate(0);
  }

  function learner(root) {
    var id = Number(root.dataset.courseId);
    var status = el('div', { role: 'status', class: 'aig-say', text: 'Loading the course...' });
    root.appendChild(status);
    A.api(API + '/' + encodeURIComponent(id) + '/learn').then(function (data) {
      say(status, '');
      var course = data.course;
      var panel = el('article', { class: 'aig-panel' });
      panel.appendChild(el('h2', { class: 'aig-h2', text: course.title }));
      panel.appendChild(el('div', { class: 'aig-meta' }, [statusChip(course.state),
        el('span', { class: 'aig-muted', text: 'Edition ' + course.version + (course.state === 'completed' ? ' · Renews ' + date(course.renew_at) : ' · Due ' + date(course.due_at)) })]));
      panel.appendChild(el('div', { class: 'aig-literacy-body', text: course.body }));
      root.appendChild(panel);
      if (course.state === 'completed') { root.appendChild(el('p', { class: 'aig-banner aig-banner-good', text: 'Your completion is current. You can review this edition whenever you need.' })); return; }
      var form = el('form', { class: 'aig-panel' });
      form.appendChild(el('h2', { class: 'aig-h2', text: course.questions.length ? 'Knowledge check' : 'Acknowledgement' }));
      var answerInputs = [];
      course.questions.forEach(function (question, index) {
        var fieldset = el('fieldset', { class: 'aig-literacy-question' });
        fieldset.appendChild(el('legend', { text: (index + 1) + '. ' + question.prompt }));
        var options = [];
        question.options.forEach(function (option, number) {
          var radio = el('input', { type: 'radio', name: 'question' + index, value: String(number), required: true });
          options.push(radio);
          fieldset.appendChild(el('label', { class: 'aig-radio' }, [radio, option]));
        });
        answerInputs.push(options); form.appendChild(fieldset);
      });
      var acknowledge = null;
      if (!course.questions.length) {
        acknowledge = el('input', { type: 'checkbox', required: true });
        form.appendChild(el('label', { class: 'aig-check' }, [acknowledge, 'I have read and understood this AI literacy course.']));
      } else form.appendChild(el('p', { class: 'aig-muted', text: 'Pass mark: ' + course.pass_mark + '%. If you miss it, you can review and try again.' }));
      var feedback = el('div', { role: 'status', class: 'aig-say' });
      form.appendChild(feedback);
      var submit = el('button', { type: 'submit', class: 'btn btn-primary', text: course.questions.length ? 'Submit answers' : 'Complete course' });
      form.appendChild(submit);
      form.addEventListener('submit', function (event) {
        event.preventDefault(); if (!form.reportValidity()) return;
        submit.disabled = true; say(feedback, 'Checking...');
        var answers = answerInputs.map(function (options) { return options.filter(function (r) { return r.checked; })[0]; })
          .map(function (r) { return Number(r.value); });
        A.api(API + '/' + encodeURIComponent(id) + '/complete', 'POST',
          { version: course.version, answers: answers, acknowledged: !!(acknowledge && acknowledge.checked) })
          .then(function (result) {
            if (result.result.passed) {
              say(feedback, 'Completed. Your next renewal is ' + date(result.result.renew_at) + '.', 'good');
              submit.remove();
            } else {
              say(feedback, 'Score ' + result.result.score + '%. Review questions ' + result.result.wrong_questions.join(', ') + ' and try again.', 'bad');
              submit.disabled = false;
            }
          }).catch(function (err) { error(feedback, err); submit.disabled = false; });
      });
      root.appendChild(form);
    }).catch(function (err) { error(status, err); });
  }

  var indexRoot = document.getElementById('aigLiteracy');
  if (indexRoot) index(indexRoot);
  var learnerRoot = document.getElementById('aigLiteracyCourse');
  if (learnerRoot) learner(learnerRoot);
}(window));
