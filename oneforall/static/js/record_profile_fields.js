/* Shared supplementary record fields. Labels and accepted values come from the
   same server definition that validates saves and generates readiness gaps. */
(function (global) {
  'use strict';

  function node(tag, className, content) {
    var out = document.createElement(tag);
    if (className) out.className = className;
    if (content != null) out.textContent = content;
    return out;
  }

  function valueOf(input, field) {
    if (field.kind === 'bool') return input.value === '' ? '' : input.value === '1';
    if (field.kind === 'multiselect') return input.value.split(/[\n;,]/).map(function (part) { return part.trim(); }).filter(Boolean);
    return input.value.trim();
  }

  function valueText(value, field) {
    if (value == null || value === '') return '';
    if (field.kind === 'bool') return value === true || value === 1 || value === '1' ? '1' : '0';
    return Array.isArray(value) ? value.join('\n') : String(value);
  }

  function render(host, profile, record) {
    host.replaceChildren();
    var header = node('div', 'rp-heading', 'Additional record details');
    host.appendChild(header);
    if (record.readiness && typeof record.readiness.needed === 'number') {
      host.appendChild(node('p', 'rp-note', 'Recorded answers: ' + record.readiness.made + ' of ' +
        record.readiness.needed + ' applicable fields. A specialist must review the content.'));
    }
    var note = node('p', 'rp-note', 'These answers remain part of this record. Empty answers stay visible as gaps in its exported review copy.');
    host.appendChild(note);
    if (profile.regime.status !== 'approved') {
      host.appendChild(node('p', 'rp-note', profile.regime.status === 'internal_template'
        ? 'These are internal assurance prompts. The independent decision is recorded in AI Governance Decisions.'
        : 'Jurisdiction wording and legal references are not approved for filing. A privacy specialist must verify them.'));
    }
    var fields = {};
    profile.sections.forEach(function (section) {
      var detailFields = section.fields.filter(function (field) { return field.store === 'details'; });
      if (!detailFields.length) return;
      var panel = node('section', 'rp-section');
      panel.appendChild(node('h3', '', section.label));
      detailFields.forEach(function (field) {
        var wrap = node('div', 'rp-field');
        var id = 'rp_' + profile.record + '_' + field.key;
        var label = node('label', '', field.label + (field.required ? ' · needed for readiness' : ''));
        label.htmlFor = id;
        wrap.appendChild(label);
        var input;
        if (field.kind === 'select' || field.kind === 'bool') {
          input = node('select');
          input.appendChild(new Option('Not recorded', ''));
          var options = field.kind === 'bool' ? [['1', 'Yes'], ['0', 'No']] : field.options;
          options.forEach(function (option) { input.appendChild(new Option(option[1], option[0])); });
        } else if (field.kind === 'date') {
          input = node('input');
          input.type = 'date';
        } else {
          input = node('textarea');
          input.rows = field.kind === 'longtext' ? 3 : 2;
          input.maxLength = field.kind === 'multiselect' ? 10000 : (field.limit || 4000);
          if (field.kind === 'multiselect') input.placeholder = 'One item per line';
        }
        input.id = id;
        var current = valueText(record[field.key], field);
        if (input.tagName === 'SELECT' && current && !Array.from(input.options).some(function (option) { return option.value === current; })) {
          input.appendChild(new Option('Previously recorded: ' + current, current));
        }
        input.value = current;
        fields[field.key] = { input: input, definition: field };
        wrap.appendChild(input);
        if (field.help) wrap.appendChild(node('p', 'rp-note', field.help));
        if (field.anchor) wrap.appendChild(node('small', 'rp-anchor', 'Reference: ' + field.anchor + ' · specialist review required'));
        panel.appendChild(wrap);
      });
      host.appendChild(panel);
    });
    host._recordProfileFields = fields;
    host.dataset.ready = 'true';
  }

  async function mount(host, url, record) {
    host.dataset.ready = 'false';
    host.replaceChildren(node('p', 'rp-note', 'Loading additional fields…'));
    var stamp = (host._recordProfileStamp || 0) + 1;
    host._recordProfileStamp = stamp;
    var profile;
    if (typeof url === 'object') profile = url;
    else {
      var response = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error('Additional fields could not be loaded. Please try again.');
      profile = await response.json();
    }
    if (stamp === host._recordProfileStamp && host.isConnected) render(host, profile, record || {});
    return profile;
  }

  function fillRegulations(select, profile, recordedValue) {
    if (!select || !Array.isArray(profile.regulations)) return;
    var current = select.value || recordedValue || '';
    select.replaceChildren(new Option('Select jurisdiction…', ''));
    profile.regulations.forEach(function (regime) {
      select.appendChild(new Option(regime.name + (regime.status === 'unverified' ? ' · verify locally' : ''), regime.key));
    });
    if (current && !Array.from(select.options).some(function (option) { return option.value === current; })) {
      select.appendChild(new Option(current + ' · review', current));
    }
    select.value = current;
  }

  function fillLegalBasis(select, profile, recordedValue) {
    if (!select || !profile || !Array.isArray(profile.sections)) return;
    var fields = profile.sections.reduce(function (all, section) { return all.concat(section.fields || []); }, []);
    var basis = fields.find(function (field) { return field.key === 'legal_basis'; });
    if (!basis) return;
    var current = select.value || recordedValue || '';
    select.replaceChildren(new Option('Select a basis…', ''));
    (basis.options || []).forEach(function (option) { select.appendChild(new Option(option[1], option[0])); });
    if (current && !Array.from(select.options).some(function (option) { return option.value === current; })) {
      select.appendChild(new Option('Previously recorded: ' + current + ' · verify', current));
    }
    select.value = current;
  }

  function values(host) {
    if (!host || host.dataset.ready !== 'true') throw new Error('Wait for the additional fields to load before saving.');
    var out = {};
    Object.keys(host._recordProfileFields).forEach(function (key) {
      var item = host._recordProfileFields[key];
      out[key] = valueOf(item.input, item.definition);
    });
    return out;
  }

  global.RecordProfileFields = { mount: mount, values: values, fillRegulations: fillRegulations, fillLegalBasis: fillLegalBasis };
}(window));
