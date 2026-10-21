/* Governance: the connected view of one record, and the changes waiting for a second look
   (plans/2026-10-governance-rework/03 sections 1 and 2).

   Everything a person sees is read just now through their own access, and is drawn as text nodes only: nothing that comes
   from the server is ever parsed as markup. */
(function (global) {
  'use strict';

  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'on') Object.keys(value).forEach(function (name) { node.addEventListener(name, value[name]); });
      else node.setAttribute(key, value === true ? '' : value);
    });
    [].concat(kids === undefined ? [] : kids).forEach(function (kid) {
      if (kid === null || kid === undefined || kid === false) return;
      node.appendChild(typeof kid === 'string' ? document.createTextNode(kid) : kid);
    });
    return node;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }
  function chip(text, kind) { return el('span', { class: 'gc-chip' + (kind ? ' gc-chip-' + kind : ''), text: text }); }
  function say(node, text, bad) {
    node.textContent = text || '';
    node.className = 'gc-say' + (bad ? ' gc-say-bad' : '');
    node.setAttribute('role', bad ? 'alert' : 'status');
  }
  function safe(url) { return typeof url === 'string' && url.charAt(0) === '/' && url.charAt(1) !== '/' ? url : null; }
  function link(url, text) { var href = safe(url); return href ? el('a', { href: href, text: text }) : el('span', { text: text }); }
  function request(url, method, body) { return global.ApiClient.request(url, { method: method || 'GET', body: body }); }
  function errorText(err) { return (err && err.detail) || 'Something went wrong. Please try again.'; }

  var TONE = { good: 'good', warn: 'warn', bad: 'bad', muted: 'muted' };

  function changesList(entries, done, canAct) {
    var list = el('ul', { class: 'gc-list' });
    entries.forEach(function (entry) {
      var head = [chip(entry.kind_label, 'warn')];
      if (entry.status !== 'open') head.push(chip(entry.status === 'confirmed' ? 'Needs a second look' : 'No action needed', entry.status === 'confirmed' ? 'bad' : 'muted'));
      var body = [el('div', { class: 'gc-row' }, head.concat([
        el('strong', {}, [link(entry.target.url, entry.target.title)]),
        el('span', { class: 'gc-muted' }, ['changed: ', link(entry.source.url, entry.source.title)])]))];
      if (entry.changes.length) {
        body.push(el('ul', { class: 'gc-changes' }, entry.changes.map(function (c) {
          return el('li', { text: c.label + ': ' + (c.before === null ? 'not set' : c.before) + ' to ' + (c.after === null ? 'not set' : c.after) });
        })));
      }
      var meta = [entry.changed_at ? 'Changed ' + entry.changed_at : null, entry.changed_by ? 'by ' + entry.changed_by : null,
        entry.decided_by ? 'Decided by ' + entry.decided_by + (entry.decided_at ? ' on ' + entry.decided_at.slice(0, 10) : '') : null,
        entry.reason ? 'Reason: ' + entry.reason : null].filter(Boolean);
      if (meta.length) body.push(el('p', { class: 'gc-muted', text: meta.join('. ') + '.' }));
      if (canAct && entry.can_review) {
        var reason = el('input', { type: 'text', maxlength: '500', 'aria-label': 'Why this needs no action', placeholder: 'Why this needs no action' });
        var out = el('div', { class: 'gc-say', role: 'status' });
        body.push(el('div', { class: 'gc-actions' }, [
          el('button', { type: 'button', class: 'btn btn-primary btn-sm', text: 'It needs a second look', on: { click: function () {
            decide(entry, 'confirmed', '', out, done);
          } } }),
          reason,
          el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'No action needed', on: { click: function () {
            decide(entry, 'dismissed', reason.value, out, done);
          } } })]));
        body.push(out);
      }
      list.appendChild(el('li', { id: 'target-' + entry.id }, [el('div', {}, body)]));
    });
    return list;
  }

  function decide(entry, decision, reason, out, done) {
    say(out, 'Saving...');
    request('/governance/api/changes/' + entry.id + '/decide', 'POST', { decision: decision, reason: reason })
      .then(function () { say(out, ''); done(); })
      .catch(function (err) { say(out, errorText(err), true); });
  }

  // ── The connected view of one record ──────────────────────────────────────

  function entity(root) {
    var module = root.getAttribute('data-module'), type = root.getAttribute('data-type'), id = root.getAttribute('data-id');
    var status = el('div', { class: 'gc-say', role: 'status' });
    root.appendChild(status);
    var body = el('div', {});
    root.appendChild(body);
    say(status, 'Loading...');

    function load() {
      return request('/governance/api/connected/' + encodeURIComponent(module) + '/' + encodeURIComponent(type) + '/' + encodeURIComponent(id))
        .then(function (data) { say(status, ''); render(data); })
        .catch(function (err) { say(status, err && err.status === 404 ? 'This record was not found.' : errorText(err), true); });
    }

    function render(data) {
      clear(body);
      var e = data.entity;
      body.appendChild(el('header', { class: 'gc-head' }, [
        el('p', { class: 'gc-muted', text: e.kind_label + ' · ' + e.module_title }),
        el('h1', { class: 'gc-h1', text: e.title }),
        el('dl', { class: 'gc-facts' }, [
          fact('Owner', e.owner || 'Not recorded'), fact('Business unit', e.business_unit || 'Not recorded'),
          fact('Last changed', e.updated_at || 'Not recorded')]),
        safe(e.url) ? el('p', {}, [el('a', { class: 'btn btn-secondary btn-sm', href: e.url, text: 'Open it in its own module' })]) : null]));
      body.appendChild(el('p', { class: 'gc-note', text: data.note }));

      body.appendChild(card('Changes to look at', data.changes.state, data.changes.note, function () {
        return changesList(data.changes.items, load, true);
      }));
      if (data.connections.length === 0 && data.unavailable.length === 0) {
        body.appendChild(card('Connected records', 'empty', 'No record you may open is connected to this one yet.'));
      }
      data.unavailable.forEach(function (u) { body.appendChild(card(u.title, 'unavailable', u.note)); });
      data.connections.forEach(function (section) {
        body.appendChild(card(section.title + ' (' + section.items.length + ')', 'ok', null, function () {
          var ul = el('ul', { class: 'gc-list' });
          section.items.forEach(function (item) {
            ul.appendChild(el('li', {}, [el('div', { class: 'gc-row' }, [
              el('strong', {}, [link(item.url, item.title)]), el('span', { class: 'gc-muted', text: item.kind_label }),
              el('span', { class: 'gc-muted', text: item.relationship }),
              item.state === 'disputed' ? chip('Disputed: somebody declined this connection', 'bad')
                : item.confirmed ? null : chip('Proposed, not confirmed', 'warn')])]));
          });
          return ul;
        }));
      });
      body.appendChild(card('Proof held in the Evidence Vault', data.proof.state, data.proof.note, function () {
        var ul = el('ul', { class: 'gc-list' });
        data.proof.items.forEach(function (item) {
          ul.appendChild(el('li', {}, [el('div', { class: 'gc-row' }, [
            el('strong', {}, [link(item.url, item.title)]), el('span', { class: 'gc-muted', text: 'Version ' + item.version }),
            chip(item.state, TONE[item.tone] || 'muted'),
            item.expiry_date ? el('span', { class: 'gc-muted', text: 'Expires ' + item.expiry_date }) : null])]));
        });
        return ul;
      }));
    }

    function fact(label, value) { return el('div', { class: 'gc-fact' }, [el('dt', { text: label }), el('dd', { text: value })]); }

    function card(title, state, note, build) {
      var box = el('section', { class: 'gc-card', 'aria-label': title }, [el('h2', { class: 'gc-h2', text: title })]);
      if (state === 'ok' && build) box.appendChild(build());
      else box.appendChild(el('p', { class: state === 'unavailable' ? 'gc-warn' : 'gc-muted', text: note || 'Nothing here yet.' }));
      return box;
    }

    load();
  }

  // ── Changes waiting for a second look ─────────────────────────────────────

  function changes(root) {
    var status = el('div', { class: 'gc-say', role: 'status' });
    var host = el('div', {});
    root.appendChild(status);
    root.appendChild(host);
    function load() {
      say(status, 'Loading...');
      return request('/governance/api/changes').then(function (data) {
        say(status, '');
        clear(host);
        if (!data.items.length) {
          host.appendChild(el('p', { class: 'gc-note', text: 'Nothing is waiting. When a record that others depend on changes, the connected records you may review appear here.' }));
          return;
        }
        host.appendChild(changesList(data.items, load, true));
      }).catch(function (err) { say(status, errorText(err), true); });
    }
    load();
  }

  global.GovConnected = { entity: entity, changes: changes };
}(window));
