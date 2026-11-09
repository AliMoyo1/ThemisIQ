/* Pages may not write style attributes (the policy sends style-src-attr 'none'; plans/2026-11-zoom-and-style-policy.md,
   part 4). Two attributes stand in for the cases a stylesheet cannot express, and this file applies them through
   element.style, which the policy allows:

     data-sd="none|block|flex|..."  the element's starting display, set as element.style.display so scripts that
                                    show it with element.style.display = '' (or read it back) behave as before
     data-sv="color:#123456;..."    values filled in at run time (bar widths, record colours), checked first: only
                                    the properties listed below, no url(), no fixed positioning

   Fixed styles use data-s tokens in /static/css/style-tokens.css and need nothing from here.
   Loaded without defer at the top of the head, so it sees every element as the page is parsed and every element a
   script inserts later, before the browser paints. */
(function () {
  'use strict';
  var DISPLAY = /^(none|block|inline|inline-block|flex|inline-flex|grid|inline-grid|table|table-row|table-cell|table-row-group|table-header-group|list-item|contents|flow-root)$/;
  var PROPS = {};
  ('align-items aspect-ratio background background-color border border-bottom border-color border-left border-right ' +
   'border-top border-radius box-shadow box-sizing color cursor display fill flex flex-basis flex-direction ' +
   'flex-grow flex-shrink flex-wrap align-self grid-template-columns max-height min-height overflow-x overflow-y ' +
   'word-break ' +
   'font-family font-size font-style font-weight gap grid-column height inset justify-content left letter-spacing ' +
   'line-height margin margin-bottom margin-left margin-right margin-top max-width min-width opacity outline overflow ' +
   'padding padding-bottom padding-left padding-right padding-top position stop-color stop-opacity stroke ' +
   'stroke-dasharray stroke-dashoffset text-align text-decoration text-overflow text-transform top transform ' +
   'transition vertical-align visibility white-space width z-index').split(' ').forEach(function (p) { PROPS[p] = 1; });
  var REFUSED = /url\(|image-set|image\(|element\(|expression|attr\(|[\\@<>{}]/i;

  function declarations(text) {
    var out = [], depth = 0, cur = '';
    for (var i = 0; i < text.length; i++) {
      var ch = text.charAt(i);
      if (ch === '(') depth++;
      else if (ch === ')') depth = Math.max(0, depth - 1);
      else if (ch === ';' && depth === 0) { out.push(cur); cur = ''; continue; }
      cur += ch;
    }
    out.push(cur);
    return out;
  }

  function applyValues(el, text) {
    var todo = [];
    declarations(text).forEach(function (decl) {
      var at = decl.indexOf(':');
      if (at < 1) return;
      var prop = decl.slice(0, at).trim().toLowerCase();
      var value = decl.slice(at + 1).trim();
      var priority = '';
      if (/!\s*important$/i.test(value)) { priority = 'important'; value = value.replace(/\s*!\s*important$/i, ''); }
      if (!value || REFUSED.test(value)) return;
      if (prop.slice(0, 2) === '--' ? !/^--[a-z0-9-]+$/.test(prop) : !PROPS[prop]) return;
      if (prop === 'position' && !/^(static|relative|absolute)$/i.test(value)) return;
      if (prop === 'display' && !DISPLAY.test(value.toLowerCase())) return;
      // A script that set this property itself after inserting the element wins, as it did over the old attribute.
      if (el.style.getPropertyValue(prop) !== '') return;
      todo.push([prop, value, priority]);
    });
    todo.forEach(function (d) { el.style.setProperty(d[0], d[1], d[2]); });
  }

  function apply(el) {
    var display = el.getAttribute('data-sd');
    if (display !== null) {
      el.removeAttribute('data-sd');
      display = display.trim().toLowerCase();
      if (!el.style.display && DISPLAY.test(display)) el.style.display = display;
    }
    var values = el.getAttribute('data-sv');
    if (values !== null) {
      el.removeAttribute('data-sv');
      applyValues(el, values);
    }
  }

  function scan(node) {
    if (!node || node.nodeType !== 1) return;
    if (node.hasAttribute('data-sd') || node.hasAttribute('data-sv')) apply(node);
    if (node.firstElementChild) {
      var found = node.querySelectorAll('[data-sd],[data-sv]');
      for (var i = 0; i < found.length; i++) apply(found[i]);
    }
  }

  new MutationObserver(function (records) {
    for (var r = 0; r < records.length; r++) {
      var added = records[r].addedNodes;
      for (var n = 0; n < added.length; n++) scan(added[n]);
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
  scan(document.documentElement);
  document.addEventListener('DOMContentLoaded', function () { scan(document.documentElement); });
})();
