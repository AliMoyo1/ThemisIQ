/* AI Governance: bring in the responses of an external form (plans/2026-10-governance-rework/01 section 4).

   Three steps, none of which creates a request until the last: read the file, check which column answers which question,
   look at every response and confirm. Everything from the file is shown as text. Text only, no markup from the server. */
(function (global) {
  'use strict';
  var A = global.AIGov, el = A.el;
  var API = '/ai-governance/api/import';

  var OUTCOME = {
    new: { text: 'New request', kind: 'info' },
    duplicate: { text: 'Already imported', kind: 'muted' },
    revision: { text: 'Correction of an earlier response', kind: 'warn' },
    error: { text: 'Cannot be imported', kind: 'bad' },
    replaced_in_file: { text: 'Replaced by a later row', kind: 'muted' }
  };
  var CREATES = ['new', 'revision'];

  function show(value) {
    if (value === null || value === undefined || value === '') return 'Not answered';
    if (Array.isArray(value)) return value.length ? value.join(', ') : 'Not answered';
    if (value === true) return 'Yes';
    if (value === false) return 'No';
    return String(value);
  }

  A.importer = function (root) {
    var state = { guide: null, units: [], file: null, mapping: null, batch: null, form: null };
    var status = el('div', { class: 'aig-say', role: 'status' });
    var guideBox = el('div', {});
    var uploadBox = el('div', {});
    var mappingBox = el('div', {});
    var rowsBox = el('div', {});
    var resultBox = el('div', {});
    var recentBox = el('div', {});
    [status, guideBox, uploadBox, mappingBox, rowsBox, resultBox, recentBox].forEach(function (n) { root.appendChild(n); });

    // ── The form the customer needs ──────────────────────────────────────────
    function renderGuide() {
      A.clear(guideBox);
      var g = state.guide;
      var table = el('table', { class: 'aig-table' }, [
        el('thead', {}, [el('tr', {}, ['Question to ask', 'Needed', 'Kind of answer'].map(function (h) { return el('th', { scope: 'col', text: h }); }))]),
        el('tbody', {}, g.questions.filter(function (q) { return q.kind !== 'key'; }).map(function (q) {
          var kind = { text: 'Text', choice: 'One choice', multi: 'Several choices', yes_no: 'Yes, no or not sure', date: 'A date',
            person: 'A name or email', extra: 'Text (kept with the requester)' }[q.kind] || q.kind;
          return el('tr', {}, [el('td', { text: q.question }), el('td', { text: q.required ? 'Yes' : 'Optional' }),
            el('td', { text: kind + (q.choices ? ': ' + q.choices.join('; ') : '') })]);
        }))]);
      guideBox.appendChild(el('details', { class: 'aig-panel' }, [
        el('summary', { text: 'What the form needs to ask (version ' + g.version + ')' }),
        el('p', { class: 'aig-muted', text: 'The requester answers a Google or Microsoft Form your organization controls. Export the responses as CSV or Excel and bring that file here. A person who answers the form never gets an account.' }),
        el('p', {}, [el('a', { class: 'btn btn-secondary btn-sm', href: API + '/template.csv', text: 'Download a CSV template' })]),
        el('div', { class: 'aig-tablewrap' }, [table])]));
    }

    // ── Step 1: the file ─────────────────────────────────────────────────────
    function renderUpload() {
      A.clear(uploadBox);
      var form = el('form', { class: 'aig-form aig-panel', novalidate: 'novalidate', 'aria-labelledby': 'aigImpUploadH' });
      form.appendChild(el('h2', { id: 'aigImpUploadH', class: 'aig-h3', text: '1. Read an export' }));
      var system = A.select(Object.keys(state.guide.source_systems).map(function (k) { return { id: k, name: state.guide.source_systems[k] }; }), 'google_forms');
      var name = el('input', { type: 'text', maxlength: '120', autocomplete: 'off' });
      var exported = el('input', { type: 'date' });
      var order = A.select([{ id: 'iso', name: 'Year first (2026-12-31)' }, { id: 'dmy', name: 'Day first (31/12/2026)' }, { id: 'mdy', name: 'Month first (12/31/2026)' }], 'iso');
      var unit = A.select(state.units, '', 'My business unit');
      var file = el('input', { type: 'file', accept: '.csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
      var out = el('div', { class: 'aig-say', role: 'status' });
      [A.field('aigImpSystem', 'Where the form was made', system), A.field('aigImpForm', 'Name of the form', name,
        'The same name each time, so a corrected response is recognized.'), A.field('aigImpDate', 'Date of the export (optional)', exported),
        A.field('aigImpOrder', 'How dates are written in the export', order, 'A date such as 03/04/2026 is only read in the order you choose.'),
        A.field('aigImpUnit', 'File the requests under', unit), A.field('aigImpFile', 'The export (.csv or .xlsx, up to 2 MB)', file)]
        .forEach(function (f) { form.appendChild(f.row); });
      var go = el('button', { type: 'submit', class: 'btn btn-primary', text: 'Read the file' });
      form.appendChild(el('div', { class: 'aig-actions' }, [go]));
      form.appendChild(out);
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        if (!file.files.length) { A.say(out, 'Choose the export file first.', 'bad'); return; }
        state.file = file.files[0];
        state.form = { source_system: system.value, form_name: name.value, export_date: exported.value, date_order: order.value,
          business_unit_id: unit.value };
        state.mapping = null;
        run(out);
      });
      uploadBox.appendChild(form);
    }

    function run(out) {
      var data = new FormData();
      data.append('file', state.file);
      Object.keys(state.form).forEach(function (key) { data.append(key, state.form[key] || ''); });
      if (state.mapping) data.append('mapping', JSON.stringify(state.mapping));
      A.say(out, 'Reading...');
      A.api(API + '/preview', 'POST', data).then(function (got) {
        A.say(out, '');
        state.batch = got.batch;
        state.mapping = got.batch.mapping;
        A.clear(resultBox);
        renderMapping(got.headers || []);
        renderRows();
        rowsBox.scrollIntoView && rowsBox.scrollIntoView({ block: 'start' });
      }).catch(function (err) {
        var fields = A.fieldErrors(err);
        var detail = fields ? Object.keys(fields).map(function (k) { return fields[k]; }).join(' ') : '';
        A.say(out, A.errorText(err) + (detail && detail !== A.errorText(err) ? ' ' + detail : ''), 'bad');
        if (err.body && err.body.headers && err.body.mapping) { state.mapping = err.body.mapping; renderMapping(err.body.headers); }
      });
    }

    // ── Step 2: which column answers which question ──────────────────────────
    function renderMapping(headers) {
      A.clear(mappingBox);
      var panel = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigImpMapH' }, [
        el('h2', { id: 'aigImpMapH', class: 'aig-h3', text: '2. Check which column answers which question' }),
        el('p', { class: 'aig-muted', text: 'Columns you leave as "Not used" are shown to you here and are not copied anywhere. The name of the AI use must be matched.' })]);
      var first = state.batch && state.batch.rows.length ? state.batch.rows[0] : null;
      var targets = [{ id: '', name: 'Not used' }].concat(state.guide.questions.map(function (q) { return { id: q.target, name: q.question }; }));
      var selects = {};
      var body = el('tbody', {});
      headers.forEach(function (header) {
        var select = A.select(targets, state.mapping && state.mapping[header] ? state.mapping[header] : '');
        select.setAttribute('aria-label', 'Question answered by the column ' + header);
        selects[header] = select;
        body.appendChild(el('tr', {}, [el('td', { text: header }), el('td', {}, [select])]));
      });
      panel.appendChild(el('div', { class: 'aig-tablewrap' }, [el('table', { class: 'aig-table' }, [
        el('thead', {}, [el('tr', {}, ['Column in the export', 'Answers this question'].map(function (h) { return el('th', { scope: 'col', text: h }); }))]),
        body])]));
      var out = el('div', { class: 'aig-say', role: 'status' });
      panel.appendChild(el('div', { class: 'aig-actions' }, [el('button', { type: 'button', class: 'btn btn-secondary', text: 'Read again with these columns',
        on: { click: function () {
          var chosen = {};
          Object.keys(selects).forEach(function (h) { chosen[h] = selects[h].value; });
          state.mapping = chosen;
          run(out);
        } } })]));
      panel.appendChild(out);
      mappingBox.appendChild(panel);
    }

    // ── Step 3: every response, then confirm ─────────────────────────────────
    function renderRows() {
      A.clear(rowsBox);
      var b = state.batch;
      var panel = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigImpRowsH' }, [
        el('h2', { id: 'aigImpRowsH', class: 'aig-h3', text: '3. Check the responses' })]);
      var chips = el('div', { class: 'aig-chips' });
      Object.keys(OUTCOME).forEach(function (k) {
        if (b.counts[k]) chips.appendChild(A.chip(b.counts[k] + ' ' + OUTCOME[k].text.toLowerCase(), OUTCOME[k].kind));
      });
      panel.appendChild(el('p', { class: 'aig-muted', text: b.row_count + ' responses were read from ' + (b.file_name || 'the file') + '. Nothing has been created yet.' }));
      panel.appendChild(chips);
      var controls = {};
      var body = el('tbody', {});
      b.rows.forEach(function (row) {
        var meta = OUTCOME[row.outcome] || { text: row.outcome, kind: 'muted' };
        var cell = el('td', {}, [A.chip(meta.text, meta.kind)]);
        if (row.outcome === 'duplicate') cell.appendChild(el('div', { class: 'aig-hint', text: 'Same answers as request ' + row.existing_id + '.' }));
        if (row.outcome === 'revision') {
          var lines = row.diff.map(function (d) {
            return el('li', { text: d.label + ': ' + show(d.before) + ' became ' + show(d.after) });
          });
          cell.appendChild(el('details', {}, [el('summary', { text: 'Differences from request ' + row.existing_id
            + (row.prior_status === 'approved' ? ' (already accepted; it will not be changed)' : '') }), el('ul', {}, lines)]));
        }
        var issues = el('td', {}, row.issues.map(function (i) {
          return el('div', { class: 'aig-hint', text: (i.level === 'error' ? 'Cannot import: ' : '') + i.message });
        }));
        if (row.missing.length) {
          issues.appendChild(el('div', { class: 'aig-hint', text: 'Still to answer before it can be submitted: ' + row.missing.join(', ').replace(/_/g, ' ') + '.' }));
        }
        var ownerCell = el('td', {});
        var include = null, owner = null;
        if (CREATES.indexOf(row.outcome) >= 0) {
          include = el('input', { type: 'checkbox', checked: true, 'aria-label': 'Create a request for row ' + row.row_number });
          var options = [{ id: '', name: 'Leave the owner open' }].concat(row.owner_candidates.map(function (c) {
            return { id: c.id, name: c.name + (c.email ? ' (' + c.email + ')' : '') + ', matched by ' + c.by };
          }));
          var preset = row.owner_candidates.filter(function (c) { return c.by === 'email'; });
          owner = A.select(options, preset.length === 1 ? preset[0].id : '');
          owner.setAttribute('aria-label', 'Owner for row ' + row.row_number);
          ownerCell.appendChild(owner);
          ownerCell.appendChild(el('div', { class: 'aig-hint', text: row.owner_hint ? 'The form said: ' + row.owner_hint : 'The form did not name an owner.' }));
          if (row.matches && row.matches.length) {
            ownerCell.appendChild(el('div', { class: 'aig-hint' }, ['Could already exist: '].concat(row.matches.slice(0, 3).map(function (m, i) {
              return el('span', {}, [i ? ', ' : '', el('a', { href: m.url, target: '_blank', rel: 'noopener', text: m.name })]);
            }))));
          }
        }
        controls[row.row_number] = { include: include, owner: owner };
        body.appendChild(el('tr', {}, [
          el('td', {}, [include || el('span', { class: 'aig-muted', text: 'Row ' + row.row_number })]),
          el('td', {}, [el('strong', { text: row.answers.name || 'No name' }),
            el('div', { class: 'aig-muted', text: 'Row ' + row.row_number + (row.requester.name ? ', from ' + row.requester.name : '') })]),
          cell, issues, ownerCell]));
      });
      panel.appendChild(el('div', { class: 'aig-tablewrap' }, [el('table', { class: 'aig-table' }, [
        el('thead', {}, [el('tr', {}, ['Include', 'Response', 'What will happen', 'Things to know', 'Owner'].map(function (h) { return el('th', { scope: 'col', text: h }); }))]),
        body])]));
      var out = el('div', { class: 'aig-say', role: 'status' });
      var canCreate = b.rows.some(function (r) { return CREATES.indexOf(r.outcome) >= 0; });
      var confirm = el('button', { type: 'button', class: 'btn btn-primary', text: 'Create the draft requests', disabled: !canCreate, on: { click: function () {
        var rows = {};
        Object.keys(controls).forEach(function (n) {
          var c = controls[n];
          if (!c.include) return;
          rows[n] = { include: c.include.checked, owner_user_id: c.owner && c.owner.value ? parseInt(c.owner.value, 10) : null };
        });
        confirm.disabled = true;
        A.say(out, 'Creating...');
        A.api(API + '/batches/' + b.id + '/confirm', 'POST', { version: b.version, rows: rows }).then(function (done) {
          A.say(out, '');
          renderResult(done);
        }).catch(function (err) { confirm.disabled = false; A.say(out, A.errorText(err), 'bad'); });
      } } });
      var discard = el('button', { type: 'button', class: 'btn btn-ghost', text: 'Discard this import', on: { click: function () {
        A.api(API + '/batches/' + b.id + '/discard', 'POST', { version: b.version }).then(function () {
          A.clear(mappingBox); A.clear(rowsBox); A.say(status, 'The import was discarded. Nothing was created.', 'good');
          loadRecent();
        }).catch(function (err) { A.say(out, A.errorText(err), 'bad'); });
      } } });
      panel.appendChild(el('div', { class: 'aig-actions' }, [confirm, discard]));
      panel.appendChild(out);
      rowsBox.appendChild(panel);
    }

    function renderResult(done) {
      A.clear(mappingBox); A.clear(rowsBox); A.clear(resultBox);
      var s = done.summary || {};
      var panel = el('section', { class: 'aig-panel', 'aria-labelledby': 'aigImpDoneH' }, [
        el('h2', { id: 'aigImpDoneH', class: 'aig-h3', text: 'Done' }),
        el('p', { text: s.created + ' new and ' + s.revised + ' corrected requests were created as drafts. ' + s.duplicates
          + ' were already imported and ' + s.skipped + ' were left out.' })]);
      if (done.created && done.created.length) {
        panel.appendChild(el('p', { class: 'aig-muted', text: 'Each draft is yours to complete. Answer what is missing, name an owner if it is still open, and submit it for review.' }));
        panel.appendChild(el('ul', { class: 'aig-list' }, done.created.map(function (c) {
          return el('li', {}, [el('a', { href: '/ai-governance/requests/' + c.intake_id, text: c.name || 'Untitled' }),
            c.revision > 1 ? A.chip('Revision ' + c.revision, 'warn') : null,
            c.owner_user_id ? null : A.chip('Owner still open', 'warn')]);
        })));
      }
      resultBox.appendChild(panel);
      loadRecent();
    }

    function loadRecent() {
      A.api(API + '/batches').then(function (data) {
        A.clear(recentBox);
        if (!data.batches.length) return;
        recentBox.appendChild(el('section', { class: 'aig-panel', 'aria-labelledby': 'aigImpRecentH' }, [
          el('h2', { id: 'aigImpRecentH', class: 'aig-h3', text: 'Recent imports' }),
          el('ul', { class: 'aig-list' }, data.batches.slice(0, 8).map(function (r) {
            return el('li', {}, [el('span', { text: r.form_name + ', ' + A.date(r.created_at) }),
              A.chip({ previewed: 'Waiting for confirmation', confirmed: 'Confirmed', discarded: 'Discarded', confirming: 'Confirming' }[r.status] || r.status,
                r.status === 'confirmed' ? 'good' : 'muted'),
              el('span', { class: 'aig-muted', text: r.row_count + ' responses' })]);
          }))]));
      }).catch(function () { /* the import itself is the job of this page */ });
    }

    A.say(status, 'Loading...');
    Promise.all([A.api(API + '/guide'), A.api('/ai-governance/api/business-units')]).then(function (parts) {
      A.say(status, '');
      state.guide = parts[0];
      state.units = (parts[1].items || []).map(function (u) { return { id: u.id, name: u.name }; });
      renderGuide();
      renderUpload();
      loadRecent();
    }).catch(function (err) { A.say(status, A.errorText(err), 'bad'); });
  };
}(window));
