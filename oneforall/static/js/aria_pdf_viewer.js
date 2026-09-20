/**
 * PLAN-35 T10: inline PDF preview for a draft build or a confirmed version,
 * using the vendored pdf.js (static/vendor/aria-policy/pdfjs/). Renders
 * every page to a <canvas> inside the given container -- no manual
 * download/open-in-new-tab needed for the happy path.
 *
 * pdf.js ships only as an ES module in this pinned version, which cannot
 * set a plain `window.pdfjsLib` global on its own the way a UMD build
 * would. Each page that uses this file must bridge it once via:
 *
 *   <script type="module">
 *     import * as pdfjsLib from '/static/vendor/aria-policy/pdfjs/pdf.min.mjs';
 *     window.pdfjsLib = pdfjsLib;
 *   </script>
 *
 * placed before this script (or anywhere before the first renderPdf()
 * call -- module scripts are deferred, but always finish before a user
 * can click anything that would trigger a render).
 */
(function () {
  'use strict';

  var WORKER_SRC = '/static/vendor/aria-policy/pdfjs/pdf.worker.min.mjs';
  var workerConfigured = false;

  function ensurePdfJs() {
    var lib = window.pdfjsLib;
    if (lib && !workerConfigured) {
      lib.GlobalWorkerOptions.workerSrc = WORKER_SRC;
      workerConfigured = true;
    }
    return lib || null;
  }

  function escapeHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function showError(container, message) {
    container.innerHTML = '<div class="aria-pdf-state aria-pdf-error" role="alert">' + escapeHtml(message) + '</div>';
  }

  /**
   * Fetches `url` and renders every page into `container` as canvases.
   * Never throws -- a failure renders a visible error state into the
   * container and resolves with {error}, since section 14's scenario C
   * explicitly requires "saved text survives, confirm stays disabled" when
   * the converter is missing/timed out, not a broken/blank screen.
   * Returns {pageCount} on success, {error, status?} on failure.
   */
  async function renderPdf(container, url, opts) {
    opts = opts || {};
    if (!container) return { error: 'No container element.' };
    container.innerHTML = '<div class="aria-pdf-state aria-pdf-loading" aria-live="polite">Loading preview…</div>';

    var lib = ensurePdfJs();
    if (!lib) {
      showError(container, 'PDF viewer failed to load. Refresh the page and try again.');
      return { error: 'pdfjsLib not loaded' };
    }

    var resp;
    try {
      resp = await fetch(url, { credentials: 'same-origin' });
    } catch (e) {
      showError(container, 'Could not reach the server for the preview. Check your connection and retry.');
      return { error: String((e && e.message) || e) };
    }

    if (!resp.ok) {
      var message = 'Preview unavailable (HTTP ' + resp.status + ').';
      try {
        var errBody = await resp.clone().json();
        if (errBody && errBody.error && errBody.error.message) message = errBody.error.message;
      } catch (e) { /* body wasn't JSON -- keep the generic message */ }
      showError(container, message);
      return { error: message, status: resp.status };
    }

    var buf;
    try {
      buf = await resp.arrayBuffer();
    } catch (e) {
      showError(container, 'The preview response could not be read.');
      return { error: String((e && e.message) || e) };
    }

    try {
      var pdf = await lib.getDocument({ data: buf }).promise;
      container.innerHTML = '';
      for (var pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
        var page = await pdf.getPage(pageNum);
        var viewport = page.getViewport({ scale: opts.scale || 1.2 });
        var canvas = document.createElement('canvas');
        canvas.className = 'aria-pdf-page';
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        canvas.setAttribute('role', 'img');
        canvas.setAttribute('aria-label', 'Preview page ' + pageNum + ' of ' + pdf.numPages);
        container.appendChild(canvas);
        await page.render({ canvasContext: canvas.getContext('2d'), viewport: viewport }).promise;
      }
      return { pageCount: pdf.numPages };
    } catch (e) {
      console.error('aria_pdf_viewer: render failed', e);
      showError(container, 'This file could not be displayed as a PDF preview.');
      return { error: String((e && e.message) || e) };
    }
  }

  window.AriaPdfViewer = { render: renderPdf };
})();
