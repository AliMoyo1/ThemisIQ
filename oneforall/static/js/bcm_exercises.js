/* PLAN-36 P08: BCM exercise lifecycle workspace. */
(function () {
  'use strict';
  var root = document.getElementById('view-exercises');
  if (!root) return;
  var canManage = root.dataset.canManage === 'true';
  var currentUser = Number(root.dataset.userId);
  var overlay = null, previousFocus = null, activeId = null, workspace = null, people = [];

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function id(value) { return Number(value) || 0; }
  function req(path, method, body) {
    return ApiClient.request(path, {method:method || 'GET', body:body, actionId:'bcm.exercise.workspace'});
  }
  function base() { return '/bcm/api/exercises/' + activeId; }
  function field(label, name, value, type, required) {
    return '<label style="display:block;margin:8px 0">' + esc(label) +
      '<input class="form-input" style="display:block;width:100%" type="' + (type || 'text') +
      '" name="' + esc(name) + '" value="' + esc(value) + '"' + (required ? ' required' : '') + '></label>';
  }
  function area(label, name, value, required) {
    return '<label style="display:block;margin:8px 0">' + esc(label) +
      '<textarea class="form-input" style="display:block;width:100%" name="' + esc(name) + '"' +
      (required ? ' required' : '') + '>' + esc(value) + '</textarea></label>';
  }
  function btn(action, label, disabled) {
    return '<button type="button" class="btn btn-secondary" data-ex-action="' + esc(action) + '"' +
      (disabled ? ' disabled' : '') + '>' + esc(label) + '</button>';
  }
  function section(title, content) {
    return '<section style="padding:14px 0;border-bottom:1px solid var(--border)"><h3>' +
      esc(title) + '</h3>' + content + '</section>';
  }
  function personSelect(name, managersOnly, selectedId) {
    var selected = people.filter(function (p) { return !managersOnly || p.can_manage; });
    return '<select class="form-input" name="' + esc(name) + '" required><option value="">Choose a person</option>' +
      selected.map(function (p) { return '<option value="' + id(p.id) + '"' + (id(p.id) === id(selectedId) ? ' selected' : '') + '>' + esc(p.full_name) + '</option>'; }).join('') +
      '</select>';
  }
  function render() {
    if (!overlay || !workspace) return;
    var e = workspace.exercise, state = e.status === 'in_progress' ? 'running' :
      e.status === 'completed' ? 'completed_awaiting_review' : e.status;
    var isReviewer = currentUser === id(e.reviewer_id), isOwner = currentUser === id(e.owner_id);
    var html = '';
    html += section('Exercise', '<p><strong>Status:</strong> ' + esc(state.replace(/_/g,' ')) +
      ' · <strong>Scheduled:</strong> ' + esc(e.scheduled_date || 'Not scheduled') +
      ' · <strong>Effectiveness:</strong> ' + (e.effectiveness_score == null ? 'Not reviewed' : esc(e.effectiveness_score) + '%') +
      '</p><p>' + esc(e.description || e.scenario || '') + '</p>' +
      '<p><strong>Objectives:</strong> ' + esc(e.objectives || 'Not recorded') + '</p>' +
      (workspace.prior_exercise ? '<p>Prior run #' + id(workspace.prior_exercise.id) +
        ': ' + esc(workspace.prior_exercise.effectiveness_score) + '% (same scenario and scope)</p>' : ''));
    if (canManage && state === 'planned') {
      html += section('Owner and reviewer', '<form data-ex-form="metadata">' +
        '<label>Owner ' + personSelect('owner_id',true,e.owner_id) + '</label>' +
        '<label>Reviewer ' + personSelect('reviewer_id',true,e.reviewer_id) + '</label>' +
        '<button class="btn btn-primary">Save assignments</button></form>');
    }
    var readiness = workspace.readiness.map(function (item) {
      return '<li>' + (canManage && state === 'planned' ?
        '<button type="button" class="btn btn-secondary" data-ex-readiness="' + id(item.id) +
        '" aria-label="' + (item.is_done ? 'Mark incomplete: ' : 'Mark complete: ') + esc(item.label) +
        '" aria-pressed="' + (item.is_done ? 'true' : 'false') + '">' + (item.is_done ? '✓' : '○') + '</button> ' :
        (item.is_done ? '✓ ' : '○ ')) + esc(item.label) + '</li>';
    }).join('');
    html += section('Readiness', '<ul>' + readiness + '</ul>');
    var participants = workspace.participants.map(function (p) {
      return '<li>' + esc(p.full_name) + ' — ' + esc(p.role) + ' (' +
        (p.confirmed_at ? 'confirmed' : 'awaiting confirmation') + ')</li>';
    }).join('');
    var mine = workspace.participants.some(function (p) { return id(p.user_id) === currentUser && !p.confirmed_at; });
    html += section('Participants', '<ul>' + (participants || '<li>No participants yet</li>') + '</ul>' +
      (mine && state === 'planned' ? btn('confirm', 'Confirm my role') : '') +
      (canManage && state === 'planned' ? '<form data-ex-form="participant">' +
        '<label>Participant ' + personSelect('user_id', false) + '</label>' +
        field('Role','role','', 'text', true) + '<button class="btn btn-primary">Add participant</button></form>' : ''));
    if (canManage && ['planned','ready','running','completed_awaiting_review'].indexOf(state) >= 0) {
      var next = {'planned':'ready','ready':'running','running':'completed_awaiting_review',
        'completed_awaiting_review':'closed'}[state];
      html += section('Lifecycle', btn('transition:' + next, 'Move to ' + next.replace(/_/g,' ')) +
        (state === 'planned' || state === 'ready' || state === 'running' ?
          '<form data-ex-form="cancel">' + field('Cancellation reason','reason','', 'text', true) +
          '<button class="btn btn-secondary">Cancel exercise</button></form>' : ''));
    }
    var events = workspace.events.map(function (v) {
      return '<li><time>' + esc(v.occurred_at) + '</time> · ' + esc(v.event_type) +
        ' · ' + esc(v.note) + '</li>';
    }).join('');
    html += section('Execution log', '<ol>' + (events || '<li>No events yet</li>') + '</ol>' +
      (canManage && state === 'running' ? '<form data-ex-form="event"><label>Event type <select class="form-input" name="event_type">' +
        '<option value="inject">Inject</option><option value="observation">Observation</option><option value="decision">Decision</option>' +
        '</select></label>' + area('Event details','note','',true) +
        '<button class="btn btn-primary">Log event</button></form>' : ''));
    if (state === 'completed_awaiting_review' || state === 'closed') {
      var review = '<p><strong>Results:</strong> ' + esc(e.aar_results || 'Not recorded') +
        '<br><strong>Strengths:</strong> ' + esc(e.aar_strengths || 'Not recorded') +
        '<br><strong>Gaps:</strong> ' + esc(e.aar_gaps || 'Not recorded') +
        '<br><strong>Lessons:</strong> ' + esc(e.aar_lessons || 'Not recorded') + '</p>';
      if (canManage && !e.aar_signed_off_at && (isOwner || isReviewer)) {
        review += '<form data-ex-form="review">' +
          area('Results','aar_results',e.aar_results,true) +
          area('Strengths','aar_strengths',e.aar_strengths) +
          area('Gaps','aar_gaps',e.aar_gaps) +
          area('Lessons learned','aar_lessons',e.aar_lessons,true) +
          field('Objectives met','objectives_met',e.objectives_met,'number',true) +
          field('Objectives total','objectives_total',e.objectives_total,'number',true) +
          '<button class="btn btn-primary">Save review</button></form>';
      }
      if (canManage && !e.aar_signed_off_at && isReviewer && e.aar_results)
        review += btn('signoff','Sign off review');
      if (e.aar_signed_off_at) review += '<p>Signed off ' + esc(e.aar_signed_off_at) + '</p>';
      html += section('After-action review', review);
    }
    var actions = workspace.actions.map(function (a) {
      return '<li><a href="/tasks?open=' + id(a.task_id) + '">' + esc(a.title || 'Task') +
        '</a> · ' + esc(a.status || 'missing') + ' · due ' + esc(a.due_date || 'unset') +
        (a.verified_at ? ' · verified ' + esc(a.verified_at) :
          canManage && isReviewer && state === 'completed_awaiting_review' && a.status === 'done' ?
            '<form data-ex-form="verify" data-action-id="' + id(a.id) + '">' +
            field('Scoped Evidence Vault item ID','evidence_id','', 'number',true) +
            '<button class="btn btn-secondary">Verify with evidence</button></form>' : '') + '</li>';
    }).join('');
    var add = canManage && (state === 'running' || state === 'completed_awaiting_review') && !e.aar_signed_off_at ?
      '<form data-ex-form="action">' + field('Action title','title','', 'text',true) +
      area('Description','description','') + field('Due date','due_date','', 'date',true) +
      '<label>Owner ' + personSelect('owner_id',false) + '</label>' +
      '<button class="btn btn-primary">Create corrective task</button></form>' : '';
    html += section('Corrective actions', '<ul>' + (actions || '<li>No corrective actions</li>') + '</ul>' + add);
    if (state === 'closed')
      html += section('Retained report', '<a class="btn btn-secondary" href="' + base() +
        '/report">Download signed after-action JSON</a><p>SHA-256: ' + esc(e.report_hash || '') + '</p>');
    overlay.querySelector('[data-ex-content]').innerHTML = html;
    overlay.querySelector('[data-ex-title]').textContent = e.title || 'Exercise workspace';
  }
  async function reload() {
    workspace = await req(base() + '/workspace');
    render();
    if (typeof window.bcmLoadExercises === 'function') window.bcmLoadExercises();
  }
  function close() {
    if (!overlay) return;
    overlay.remove();
    overlay = null; workspace = null; activeId = null;
    document.removeEventListener('keydown', keydown);
    if (previousFocus && previousFocus.isConnected) previousFocus.focus();
  }
  function keydown(event) {
    if (event.key === 'Escape') { close(); return; }
    if (event.key !== 'Tab' || !overlay) return;
    var focusable = Array.from(overlay.querySelectorAll('button:not([disabled]),a[href],input,select,textarea'))
      .filter(function (node) { return node.offsetParent !== null; });
    if (!focusable.length) return;
    var first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
  async function open(exerciseId) {
    if (!exerciseId) return;
    close();
    activeId = exerciseId;
    previousFocus = document.activeElement;
    overlay = document.createElement('div');
    overlay.className = 'bcm-doc-overlay';
    overlay.innerHTML = '<div class="bcm-doc-panel" role="dialog" aria-modal="true" aria-labelledby="bcmExDialogTitle">' +
      '<div class="bcm-doc-head"><h2 id="bcmExDialogTitle" data-ex-title>Exercise workspace</h2>' +
      '<button type="button" class="btn btn-secondary" data-ex-close>Close</button></div>' +
      '<div class="bcm-doc-body" style="white-space:normal;font-family:inherit" data-ex-content>Loading…</div></div>';
    document.body.appendChild(overlay);
    document.addEventListener('keydown', keydown);
    overlay.querySelector('[data-ex-close]').focus();
    try {
      if (canManage) people = await req(base() + '/participants/eligible');
      await reload();
    } catch (error) {
      overlay.querySelector('[data-ex-content]').textContent = error.message || 'Unable to load exercise';
    }
  }
  window.bcmOpenExerciseWorkspace = open;
  async function mutate(path, method, body) {
    try { await req(path, method, body); await reload(); }
    catch (error) { window.alert(error.message || 'Could not save exercise'); }
  }
  document.addEventListener('click', function (event) {
    var opener = event.target.closest('[data-ex-workspace]');
    if (opener) { open(id(opener.dataset.exWorkspace)); return; }
    if (!overlay) return;
    if (event.target === overlay || event.target.closest('[data-ex-close]')) { close(); return; }
    var check = event.target.closest('[data-ex-readiness]');
    if (check) {
      mutate(base() + '/readiness/' + id(check.dataset.exReadiness), 'PUT',
        {done:check.getAttribute('aria-pressed') !== 'true'});
      return;
    }
    var action = event.target.closest('[data-ex-action]');
    if (!action) return;
    if (action.dataset.exAction === 'confirm')
      mutate(base() + '/participants/confirm','POST',{});
    else if (action.dataset.exAction === 'signoff')
      mutate(base() + '/review/sign-off','POST',{});
    else if (action.dataset.exAction.indexOf('transition:') === 0)
      mutate(base() + '/transition','POST',{target:action.dataset.exAction.slice(11)});
  });
  document.addEventListener('submit', function (event) {
    var form = event.target.closest('[data-ex-form]');
    if (!form || !overlay || !overlay.contains(form)) return;
    event.preventDefault();
    var data = Object.fromEntries(new FormData(form).entries());
    var kind = form.dataset.exForm;
    if (kind === 'cancel') mutate(base() + '/transition','POST',{target:'cancelled',reason:data.reason});
    if (kind === 'metadata') mutate(base(),'PUT',data);
    if (kind === 'participant') mutate(base() + '/participants','POST',data);
    if (kind === 'event') mutate(base() + '/events','POST',data);
    if (kind === 'review') mutate(base() + '/review','PUT',data);
    if (kind === 'action') mutate(base() + '/actions','POST',data);
    if (kind === 'verify') mutate(base() + '/actions/' + id(form.dataset.actionId) + '/verify','POST',data);
  });
}());
