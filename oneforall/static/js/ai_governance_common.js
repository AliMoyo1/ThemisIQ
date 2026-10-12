/* AI Governance: small helpers shared by its pages.
   Pages build their DOM from text nodes only: nothing that comes from the server is ever parsed as markup. */
(function (global) {
  'use strict';

  var AIGov = global.AIGov = global.AIGov || {};

  /* el('div', {class: 'x', text: 'hello', 'aria-label': 'y', on: {click: fn}}, [child, 'text']) */
  AIGov.el = function (tag, attrs, kids) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'on') Object.keys(value).forEach(function (name) { node.addEventListener(name, value[name]); });
      else if (key === 'value') node.value = value;
      else if (key === 'checked') node.checked = !!value;
      else if (key === 'disabled') node.disabled = !!value;
      else node.setAttribute(key, value === true ? '' : value);
    });
    [].concat(kids === undefined ? [] : kids).forEach(function (kid) {
      if (kid === null || kid === undefined || kid === false) return;
      node.appendChild(typeof kid === 'string' ? document.createTextNode(kid) : kid);
    });
    return node;
  };
  var el = AIGov.el;

  AIGov.clear = function (node) { while (node.firstChild) node.removeChild(node.firstChild); return node; };

  /* The shared fetch wrapper throws ApiError(detail, body); callers show .detail, which is always safe to display. */
  AIGov.api = function (url, method, body) {
    return ApiClient.request(url, { method: method || 'GET', body: body });
  };

  AIGov.qs = function (params) {
    var parts = [];
    Object.keys(params).forEach(function (key) {
      var value = params[key];
      if (value === null || value === undefined || value === '') return;
      parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(value));
    });
    return parts.length ? '?' + parts.join('&') : '';
  };

  AIGov.debounce = function (fn, ms) {
    var timer = null;
    return function () {
      var args = arguments, self = this;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(self, args); }, ms);
    };
  };

  AIGov.date = function (value) { return value ? String(value).slice(0, 10) : ''; };

  var TIER_LABEL = { needs_review: 'Needs review', lower: 'Lower', moderate: 'Moderate', elevated: 'Elevated' };
  AIGov.tierChip = function (tier, adopted) {
    var chip = el('span', { class: 'aig-chip aig-tier-' + (TIER_LABEL[tier] ? tier : 'needs_review'),
      text: TIER_LABEL[tier] || 'Needs review' });
    if (adopted === false) chip.setAttribute('title', 'Provisional: the rules\' reading of the answers, not yet adopted by a reviewer');
    if (adopted === true) chip.setAttribute('title', 'Adopted by a reviewer');
    return chip;
  };
  AIGov.chip = function (text, kind) { return el('span', { class: 'aig-chip' + (kind ? ' aig-chip-' + kind : ''), text: text }); };

  /* Live status line: role=status for progress, role=alert for a problem. */
  AIGov.say = function (node, message, kind) {
    node.textContent = message || '';
    node.className = 'aig-say' + (kind ? ' aig-say-' + kind : '');
    node.setAttribute('role', kind === 'bad' ? 'alert' : 'status');
  };

  AIGov.errorText = function (err) { return (err && err.detail) || 'Something went wrong. Please try again.'; };

  /* A sentence list from the server's field errors: {field: sentence}. */
  AIGov.fieldErrors = function (err) {
    var body = err && err.body;
    return body && body.errors && typeof body.errors === 'object' ? body.errors : null;
  };

  /* Modal dialog with focus held inside and Escape to close; content is built by `build(close)`. */
  AIGov.dialog = function (title, build) {
    var returnTo = document.activeElement;
    var overlay = el('div', { class: 'aig-overlay' });
    var box = el('div', { class: 'aig-dialog', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'aigDialogTitle' });
    function close() {
      document.removeEventListener('keydown', onKey, true);
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      if (returnTo && returnTo.focus) returnTo.focus();
    }
    function onKey(event) {
      if (event.key === 'Escape') { event.stopPropagation(); close(); return; }
      if (event.key !== 'Tab') return;
      var focusable = box.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])');
      if (!focusable.length) return;
      var first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    box.appendChild(el('h2', { id: 'aigDialogTitle', class: 'aig-dialog-title', text: title }));
    build(box, close);
    overlay.appendChild(box);
    overlay.addEventListener('mousedown', function (event) { if (event.target === overlay) close(); });
    document.body.appendChild(overlay);
    document.addEventListener('keydown', onKey, true);
    var focus = box.querySelector('input, select, textarea, button');
    if (focus) focus.focus();
    return close;
  };

  /* A labelled form control: returns {row, input}. */
  AIGov.field = function (id, labelText, input, hint) {
    input.id = id;
    var row = el('div', { class: 'aig-field' }, [el('label', { for: id, text: labelText })]);
    if (hint) {
      var hintId = id + 'Hint';
      row.appendChild(el('div', { class: 'aig-hint', id: hintId, text: hint }));
      input.setAttribute('aria-describedby', hintId);
    }
    row.appendChild(input);
    return { row: row, input: input };
  };

  AIGov.select = function (options, selected, placeholder) {
    var select = el('select', {});
    if (placeholder !== undefined) select.appendChild(el('option', { value: '', text: placeholder }));
    options.forEach(function (o) {
      select.appendChild(el('option', { value: String(o.id), text: o.name, selected: String(o.id) === String(selected) ? true : null }));
    });
    return select;
  };

  /* Pager: Previous / Next with the range shown. */
  AIGov.pager = function (container, page, pages, total, size, go) {
    AIGov.clear(container);
    if (!total) return;
    var from = (page - 1) * size + 1, to = Math.min(total, page * size);
    container.appendChild(el('span', { class: 'aig-muted', text: 'Showing ' + from + ' to ' + to + ' of ' + total }));
    var prev = el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Previous', disabled: page <= 1,
      on: { click: function () { go(page - 1); } } });
    var next = el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Next', disabled: page >= pages,
      on: { click: function () { go(page + 1); } } });
    container.appendChild(prev);
    container.appendChild(next);
  };
}(window));
