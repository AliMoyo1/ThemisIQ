/* Lightweight chart motion for SVG trends, report segments, and progress bars.
   Existing chart renderers own values, colors, tooltips, and navigation. */
(function () {
  'use strict';
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  var lineSelector = [
    '.an-chart-line',
    '.kri-sparkline polyline[fill="none"]',
    '#rptTrendChart polyline[fill="none"]',
    '.cc-trend-sparkline polyline[fill="none"]',
    '.premium-chart-line'
  ].join(',');
  var ringSelector = '.erm-ring-wrap circle[stroke-dasharray], .orm-ring-chart circle[stroke-dasharray], #rptDonut circle[stroke-dasharray], .premium-gauge-arc';
  var barSelector = [
    '.pbar-fill', '.fh-bar-fill', '.mh-bar-fill', '.mh-fill', '.risk-fill', '.dash-bar-fill', '.gauge-fill',
    '.cc-predictive-fill', '.erm-trend-fill', '.an-metric-bar',
    '.premium-chart-bar', '.kri-gauge-fill', '.assess-bar-fill', '.fw-bar-fill', '.fw-pbar-fill', '.seats-bar-fill'
  ].join(',');
  var verticalSelector = '.premium-chart-column, .mini-bar';
  var heatSelector = '.heat-cell, .orm-heat-cell';
  var observer = 'IntersectionObserver' in window
    ? new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          observer.unobserve(entry.target);
          animate(entry.target);
        });
      }, { threshold: 0.15 })
    : null;

  function animate(node) {
    if (reduceMotion.matches || typeof node.animate !== 'function') return;
    if (node.matches(lineSelector) && typeof node.getTotalLength === 'function') {
      var length;
      try { length = node.getTotalLength(); } catch (_) { return; }
      if (!Number.isFinite(length) || length < 2) return;
      node.animate([
        { strokeDasharray: String(length), strokeDashoffset: String(length), opacity: 0.35 },
        { strokeDasharray: String(length), strokeDashoffset: '0', opacity: 1 }
      ], { duration: 880, easing: 'cubic-bezier(.22,1,.36,1)' });
      return;
    }
    if (node.matches(ringSelector)) {
      var dash = node.getAttribute('stroke-dasharray');
      if (!dash) return;
      var parts = dash.trim().split(/[ ,]+/);
      var total = Number(parts[1] || parts[0]);
      var visible = Number(parts[0]);
      if (!Number.isFinite(total) || total <= 0 || !Number.isFinite(visible) || visible <= 0) return;
      node.animate([
        { strokeDasharray: '0 ' + total, opacity: 0.35 },
        { strokeDasharray: dash, opacity: 1 }
      ], { duration: 900, easing: 'cubic-bezier(.22,1,.36,1)' });
      return;
    }
    if (node.matches(heatSelector)) {
      node.animate([
        { transform: 'translateY(5px)', opacity: 0.55 },
        { transform: 'translateY(0)', opacity: 1 }
      ], { duration: 420, easing: 'cubic-bezier(.22,1,.36,1)' });
      return;
    }
    if (node.matches(verticalSelector)) {
      node.style.transformOrigin = 'bottom center';
      node.animate([
        { transform: 'scaleY(0)', opacity: 0.45 },
        { transform: 'scaleY(1)', opacity: 1 }
      ], { duration: 720, easing: 'cubic-bezier(.22,1,.36,1)' });
      return;
    }
    if (node.matches(barSelector)) {
      node.animate([
        { transform: 'scaleX(0)', opacity: 0.4 },
        { transform: 'scaleX(1)', opacity: 1 }
      ], { duration: 700, easing: 'cubic-bezier(.22,1,.36,1)' });
    }
  }

  var selector = lineSelector + ',' + ringSelector + ',' + barSelector + ',' + verticalSelector + ',' + heatSelector;
  function prepare(node) {
    if (node.getAttribute('data-premium-chart-ready') === '1') return;
    node.setAttribute('data-premium-chart-ready', '1');
    if (observer) observer.observe(node);
    else animate(node);
  }
  function scan(root) {
    if (root.nodeType !== 1) return;
    if (root.matches(selector)) prepare(root);
    root.querySelectorAll(selector).forEach(prepare);
  }
  var queued = false;
  var pending = [];
  function schedule(records) {
    records.forEach(function (record) {
      record.addedNodes.forEach(function (node) {
        if (node.nodeType === 1) pending.push(node);
      });
    });
    if (queued || !pending.length) return;
    queued = true;
    requestAnimationFrame(function () {
      queued = false;
      var added = pending;
      pending = [];
      added.forEach(scan);
    });
  }
  function start() {
    scan(document.body);
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
