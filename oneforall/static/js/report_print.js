// The report print view (core/report_kit/render_html.py), under strict script policy.
(function () {
  'use strict';
  // Browsers before Chrome or Edge 131 leave out the page margin boxes (footer and page numbers): say so.
  var m = /(?:Chrome|Edg)\/(\d+)/.exec(navigator.userAgent);
  if (!m || parseInt(m[1], 10) < 131) document.documentElement.classList.add('no-margin-boxes');
  document.addEventListener('click', function (event) {
    if (event.target instanceof Element && event.target.closest('[data-report-print]')) window.print();
  });
})();
