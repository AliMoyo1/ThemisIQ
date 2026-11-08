(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var status = $('emailActionStatus');
  if (!$('emailAction')) return;

  var zone = $('utcOffset');
  for (var m = -720; m <= 840; m += 30) {
    var sign = m < 0 ? '-' : '+', a = Math.abs(m);
    var o = document.createElement('option');
    o.value = String(m);
    o.textContent = 'UTC' + sign + String(Math.floor(a / 60)).padStart(2, '0') + ':' + String(a % 60).padStart(2, '0');
    zone.appendChild(o);
  }

  // True while the person is editing quiet hours that are not saved yet. A save of something else (the time zone, say)
  // answers with the saved state, and drawing that over the draft would tick the box off and reset the times.
  var quietDraft = false;

  function render(p) {
    $('emailAction').checked = !!p.action;
    $('emailAction').disabled = false;
    $('emailModeGroup').disabled = !p.action;
    $('emailModeImmediate').checked = p.mode !== 'daily';
    $('emailModeDaily').checked = p.mode === 'daily';
    $('emailWeekly').checked = !!p.weekly;
    $('emailWeekly').disabled = false;
    if (!quietDraft) {
      $('quietOn').checked = !!p.quiet;
      $('quietStart').value = p.quiet ? p.quiet.start : '22:00';
      $('quietEnd').value = p.quiet ? p.quiet.end : '07:00';
    }
    $('quietOn').disabled = false;
    var offset = String(p.utc_offset || 0);
    if (!Array.prototype.some.call(zone.options, function (o) { return o.value === offset; })) {
      var extra = document.createElement('option');
      extra.value = offset;
      extra.textContent = 'UTC offset ' + offset + ' minutes';
      zone.appendChild(extra);
    }
    zone.value = offset;
    ['quietStart', 'quietEnd', 'quietSave'].forEach(function (id) { $(id).disabled = !$('quietOn').checked; });
    zone.disabled = false;
  }

  function save(change, message, savesQuiet) {
    return ApiClient.request('/api/my-email-preferences', { method: 'PUT', body: change, actionId: 'profile.email.save' })
      .then(function (p) {
        if (savesQuiet) quietDraft = false;   // what was being edited is now what is saved
        render(p);
        status.textContent = message(p);
      })
      .catch(function (e) {
        status.textContent = (e && e.detail) || 'Your choice could not be saved.';
        return ApiClient.request('/api/my-email-preferences', { actionId: 'profile.email.load' }).then(render);
      });
  }

  ApiClient.request('/api/my-email-preferences', { actionId: 'profile.email.load' }).then(render).catch(function () {
    status.textContent = 'Your email preferences could not be loaded.';
  });

  $('emailAction').addEventListener('change', function () {
    $('emailAction').disabled = true;
    save({ action: $('emailAction').checked }, function (p) {
      return p.action ? 'You will be emailed about actions that need you.'
                      : 'You will not be emailed about actions that need you. They are still in the app.';
    });
  });
  ['emailModeImmediate', 'emailModeDaily'].forEach(function (id) {
    $(id).addEventListener('change', function () {
      save({ mode: $(id).value }, function (p) {
        return p.mode === 'daily' ? 'You will get one summary a day, after 07:00 your time.'
                                  : 'You will be emailed one by one, as they happen.';
      });
    });
  });
  $('emailWeekly').addEventListener('change', function () {
    save({ weekly: $('emailWeekly').checked }, function (p) {
      return p.weekly ? 'You will get a summary every Monday.' : 'You will not get a weekly summary.';
    });
  });
  $('quietOn').addEventListener('change', function () {
    ['quietStart', 'quietEnd', 'quietSave'].forEach(function (id) { $(id).disabled = !$('quietOn').checked; });
    quietDraft = $('quietOn').checked;
    if (!$('quietOn').checked) {
      save({ quiet: null }, function () { return 'Quiet hours are off.'; }, true);
    }
  });
  ['quietStart', 'quietEnd'].forEach(function (id) {
    $(id).addEventListener('input', function () { quietDraft = true; });
  });
  $('quietSave').addEventListener('click', function () {
    save({ quiet: { start: $('quietStart').value, end: $('quietEnd').value }, utc_offset: parseInt(zone.value, 10) },
      function (p) { return 'Ordinary mail waits out ' + p.quiet.start + ' to ' + p.quiet.end + ', in your time zone.'; },
      true);
  });
  zone.addEventListener('change', function () {
    save({ utc_offset: parseInt(zone.value, 10) }, function () { return 'Your time zone is saved.'; });
  });
})();
