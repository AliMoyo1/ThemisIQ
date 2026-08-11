/**
 * Reusable "agent thinking" trace widget.
 *
 * Renders a collapsible header ("Thinking" -> "Thought for Ns") above a list
 * of steps that reveal one at a time while a real async call is in flight,
 * then settles into a done state the moment that call actually resolves.
 * Stays expandable after the fact so a user can re-open it to see what ran.
 *
 * Unlike a canned/demo timer, this widget is driven by the real request
 * lifecycle: it never claims "done" before settle() is called, and it never
 * gets stuck mid-sequence if the real call finishes before every optimistic
 * row has had its turn -- settle() reveals whatever is left immediately.
 *
 * Usage:
 *   var trace = window.ThinkingTrace.open(mountEl, {
 *     variant: 'steps',              // steps | reasoning | search | coding
 *     activeLabel: 'Thinking',
 *     rows: [{ primary: 'Searching the knowledge base' },
 *            { primary: 'Reading the most relevant sources' },
 *            { primary: 'Writing the answer' }]
 *   });
 *   // ... after the real call resolves:
 *   trace.settle({ doneLabel: 'Thought for 6 seconds' });
 *
 * variant notes:
 *   steps      row list, spinner -> muted checkmarks (default)
 *   reasoning  prose rows, no checkmarks, relaxed line-height
 *   search     query row + source rows (secondary = domain, href = link)
 *   coding     tool-trace rows (secondary = filename, mono; add/del diff stat)
 */
(function () {
  var STYLE_ID = 'thinkingTraceStyles';
  var DEFAULT_STEP_DELAY = 900;

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent =
      '@keyframes tt-shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}' +
      '@keyframes tt-spin{to{transform:rotate(360deg)}}' +
      '@keyframes tt-fade-in{from{opacity:0}to{opacity:1}}' +
      '@keyframes tt-fade-up{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}' +
      '.tt-root{display:flex;flex-direction:column;width:100%;font-size:13px}' +
      '.tt-header{display:flex;align-items:center;gap:8px;width:fit-content;margin:-4px -6px;padding:4px 6px;' +
        'border:none;background:transparent;border-radius:8px;cursor:pointer;transition:background-color .1s}' +
      '.tt-header:hover{background:var(--surface2)}' +
      '.tt-label-active{background-image:linear-gradient(90deg,var(--muted) 35%,var(--text) 50%,var(--muted) 65%);' +
        'background-size:200% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;' +
        'animation:tt-shimmer 1.4s linear infinite;font-weight:500;white-space:nowrap;font-size:13px}' +
      '.tt-label-done{color:var(--text-mid);font-weight:500;white-space:nowrap;font-size:13px;animation:tt-fade-in 350ms ease-out both}' +
      '.tt-chevron{transition:transform .3s cubic-bezier(.23,1,.32,1);flex-shrink:0}' +
      '.tt-chevron.tt-open{transform:rotate(180deg)}' +
      '.tt-body{display:grid;grid-template-rows:0fr;opacity:0;transition:grid-template-rows .4s cubic-bezier(.23,1,.32,1),opacity .4s cubic-bezier(.23,1,.32,1)}' +
      '.tt-body.tt-open{grid-template-rows:1fr;opacity:1}' +
      '.tt-body-inner{overflow:hidden}' +
      '.tt-trace{position:relative;margin:4px 0 0 5px;padding-left:16px}' +
      '.tt-rail{position:absolute;left:3px;top:-8px;width:1px;background:var(--border2);' +
        'transition:height .5s cubic-bezier(.23,1,.32,1)}' +
      '.tt-rows{display:flex;flex-direction:column;gap:2px;padding:4px 0}' +
      '.tt-row{display:flex;align-items:center;gap:8px;min-height:28px;width:100%;padding:2px 6px;' +
        'border-radius:6px;text-align:left;border:none;background:transparent;color:inherit;' +
        'font:inherit;text-decoration:none;cursor:default;box-sizing:border-box}' +
      'a.tt-row,button.tt-row{cursor:pointer;transition:background-color .15s}' +
      'a.tt-row:hover,button.tt-row:hover{background:var(--surface2)}' +
      'button.tt-row[aria-pressed="true"]{background:var(--surface3)}' +
      '.tt-row-primary{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12.5px;font-weight:500;color:var(--text)}' +
      '.tt-variant-reasoning .tt-row-primary{white-space:normal;line-height:1.55;font-weight:400;color:var(--text-mid)}' +
      '.tt-row-secondary{flex-shrink:0;font-size:11.5px;color:var(--muted)}' +
      '.tt-row-mono{font-family:var(--mono,monospace)}' +
      '.tt-row-diff{flex-shrink:0;font-family:var(--mono,monospace);font-size:11px;font-variant-numeric:tabular-nums}' +
      '.tt-diff-add{color:var(--good)}.tt-diff-del{color:var(--bad)}' +
      '.tt-check{flex-shrink:0}' +
      '.tt-spinner{flex-shrink:0;width:12px;height:12px;border-radius:50%;border:1.5px solid var(--border2);' +
        'border-top-color:var(--text-mid);animation:tt-spin 700ms linear infinite}' +
      '.tt-dot{flex-shrink:0;display:flex;align-items:center;justify-content:center;width:14px;height:14px;' +
        'border-radius:50%;color:#fff}' +
      '.tt-query{display:flex;align-items:center;gap:8px;min-height:24px;padding:2px 6px;font-size:12.5px;color:var(--text-mid)}' +
      '.tt-more{padding:2px 6px;font-size:12px;color:var(--muted)}' +
      '@media (prefers-reduced-motion:reduce){.tt-label-active,.tt-spinner{animation:none}.tt-label-active{color:var(--text-mid);background:none}}';
    document.head.appendChild(style);
  }

  var SPARK_PATH = 'M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z';
  var CHECK_PATH = 'M20 6L9 17l-5-5';
  var CHEVRON_PATH = 'M6 9l6 6 6-6';
  var SEARCH_ICON = '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>';
  var DOT_TONES = ['var(--accent)', 'var(--warn)', 'var(--good)'];

  function svg(attrs, inner) {
    var a = '';
    for (var k in attrs) a += ' ' + k + '="' + attrs[k] + '"';
    return '<svg' + a + '>' + inner + '</svg>';
  }

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = String(s == null ? '' : s);
    return d.innerHTML;
  }

  function renderRow(row, variant, checked, working) {
    var lead = '';
    if (variant === 'search') {
      lead = '<span class="tt-dot" style="background:' + row._tone + '">' +
        svg({ width: 9, height: 9, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': 2.5 },
          '<circle cx="12" cy="12" r="9"/><path d="M3.5 12h17M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>') +
        '</span>';
    } else if (variant === 'steps' || variant === 'coding') {
      lead = checked
        ? svg({ width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none', stroke: 'var(--muted)', 'stroke-width': 2.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, '<path d="' + CHECK_PATH + '"/>')
        : (working ? '<span class="tt-spinner"></span>' : '');
    }
    var secondary = row.secondary
      ? '<span class="tt-row-secondary' + (row.mono ? ' tt-row-mono' : '') + '">' + esc(row.secondary) + '</span>'
      : '';
    var diff = row.add !== undefined
      ? '<span class="tt-row-diff"><span class="tt-diff-add">+' + row.add + '</span> <span class="tt-diff-del">−' + row.del + '</span></span>'
      : '';
    return lead + '<span class="tt-row-primary">' + esc(row.primary) + '</span>' + secondary + diff;
  }

  function ThinkingTrace(container, opts) {
    injectStyles();
    opts = opts || {};
    var variant = opts.variant || 'steps';
    var rows = (opts.rows || []).map(function (r, i) {
      return Object.assign({}, r, { _tone: DOT_TONES[i % DOT_TONES.length] });
    });
    var activeLabel = opts.activeLabel || 'Thinking';
    var stepDelay = opts.stepDelay || DEFAULT_STEP_DELAY;
    var startedAt = Date.now();

    var root = document.createElement('div');
    root.className = 'tt-root tt-variant-' + variant;

    var header = document.createElement('button');
    header.type = 'button';
    header.className = 'tt-header';
    var labelHtml =
      svg({ width: 15, height: 15, viewBox: '0 0 24 24', fill: 'var(--text-mid)' }, '<path d="' + SPARK_PATH + '"/>') +
      '<span class="tt-label-active">' + esc(activeLabel) + '</span>' +
      svg({ width: 13, height: 13, viewBox: '0 0 24 24', fill: 'none', stroke: 'var(--muted)', 'stroke-width': 2.2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', class: 'tt-chevron tt-open' }, '<path d="' + CHEVRON_PATH + '"/>');
    header.innerHTML = labelHtml;
    root.appendChild(header);

    var body = document.createElement('div');
    body.className = 'tt-body tt-open';
    var bodyInner = document.createElement('div');
    bodyInner.className = 'tt-body-inner';
    var trace = document.createElement('div');
    trace.className = 'tt-trace';
    var rail = document.createElement('span');
    rail.className = 'tt-rail';
    rail.setAttribute('aria-hidden', 'true');
    var rowsWrap = document.createElement('div');
    rowsWrap.className = 'tt-rows';

    if (opts.query) {
      var q = document.createElement('div');
      q.className = 'tt-query';
      q.innerHTML = svg({ width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none', stroke: 'var(--muted)', 'stroke-width': 2, 'stroke-linecap': 'round' }, SEARCH_ICON) +
        '<span>' + esc(opts.query) + '</span>';
      rowsWrap.appendChild(q);
    }

    trace.appendChild(rail);
    trace.appendChild(rowsWrap);
    bodyInner.appendChild(trace);
    body.appendChild(bodyInner);
    root.appendChild(body);
    container.appendChild(root);

    var manualExpanded = null; // null = follow auto behaviour
    var working = true;
    var revealed = 0;
    var stepTimer = null;
    var collapseTimer = null;

    function setExpanded(expanded) {
      body.classList.toggle('tt-open', expanded);
      header.querySelector('.tt-chevron').classList.toggle('tt-open', expanded);
      header.setAttribute('aria-expanded', String(expanded));
    }

    function isExpanded() {
      return manualExpanded === null ? working || revealed < rows.length : manualExpanded;
    }

    header.addEventListener('click', function () {
      manualExpanded = !isExpanded();
      setExpanded(manualExpanded);
    });

    function rowEl(row, i) {
      var el;
      if (variant === 'search' && row.href) {
        el = document.createElement('a');
        el.href = row.href;
        el.target = '_blank';
        el.rel = 'noreferrer';
      } else if (variant === 'coding') {
        el = document.createElement('button');
        el.type = 'button';
        el.setAttribute('aria-pressed', 'false');
        el.addEventListener('click', function () {
          var pressed = el.getAttribute('aria-pressed') === 'true';
          el.setAttribute('aria-pressed', String(!pressed));
        });
      } else {
        el = document.createElement('div');
      }
      el.className = 'tt-row';
      el.style.animation = 'tt-fade-up 320ms cubic-bezier(.23,1,.32,1) ' + (i * 100) + 'ms both';
      el.innerHTML = renderRow(row, variant, true, working);
      return el;
    }

    function renderUpTo(n, checkedAll) {
      rowsWrap.querySelectorAll('.tt-row').forEach(function (e) { e.remove(); });
      for (var i = 0; i < n; i++) {
        rowsWrap.appendChild(rowEl(rows[i], i));
      }
      // spinner on the row currently "in progress"
      if (!checkedAll && working && n < rows.length) {
        var pending = rows[n];
        if (pending && (variant === 'steps' || variant === 'coding')) {
          var el = document.createElement('div');
          el.className = 'tt-row';
          el.style.animation = 'tt-fade-up 320ms cubic-bezier(.23,1,.32,1) both';
          el.innerHTML = renderRow(pending, variant, false, true);
          rowsWrap.appendChild(el);
        }
      }
      revealed = n;
      requestAnimationFrame(function () {
        rail.style.height = Math.max(0, trace.offsetHeight - 8) + 'px';
      });
    }

    function scheduleNext() {
      if (revealed >= rows.length - 1) return; // hold on the last row until settle()
      stepTimer = setTimeout(function () {
        renderUpTo(revealed + 1, false);
        scheduleNext();
      }, stepDelay);
    }

    setExpanded(true);
    renderUpTo(0, false);
    scheduleNext();

    function settle(finalOpts) {
      finalOpts = finalOpts || {};
      clearTimeout(stepTimer);
      working = false;

      if (finalOpts.appendRows && finalOpts.appendRows.length) {
        finalOpts.appendRows.forEach(function (r, i) {
          rows.push(Object.assign({}, r, { _tone: DOT_TONES[(rows.length + i) % DOT_TONES.length] }));
        });
      }
      renderUpTo(rows.length, true);

      var secs = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
      var doneLabel = finalOpts.doneLabel || ('Thought for ' + secs + (secs === 1 ? ' second' : ' seconds'));
      var labelEl = header.querySelector('.tt-label-active, .tt-label-done');
      labelEl.outerHTML = '<span class="tt-label-done">' + esc(doneLabel) + '</span>';

      if (variant === 'search' && finalOpts.moreCount) {
        var more = document.createElement('span');
        more.className = 'tt-more';
        more.style.animation = 'tt-fade-in 300ms ease-out both';
        more.textContent = '+' + finalOpts.moreCount + ' more';
        rowsWrap.appendChild(more);
      }

      if (manualExpanded === null) {
        collapseTimer = setTimeout(function () {
          if (manualExpanded === null) setExpanded(false);
        }, 900);
      }
    }

    function destroy() {
      clearTimeout(stepTimer);
      clearTimeout(collapseTimer);
      if (root.parentNode) root.parentNode.removeChild(root);
    }

    return { el: root, settle: settle, destroy: destroy };
  }

  window.ThinkingTrace = {
    open: function (container, opts) {
      return ThinkingTrace(container, opts);
    }
  };
})();
