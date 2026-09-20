/**
 * PLAN-35 T10/T11: sanitized markdown rendering for ARIA policy content.
 *
 * Replaces every direct `marked.parse(...)` -> innerHTML call in ARIA pages.
 * marked() on its own passes raw HTML/script through unchanged -- it is a
 * markdown-to-HTML converter, not a sanitizer. This wraps it with DOMPurify
 * using an explicit allowlist (never a blocklist) so unknown/future tags
 * default to stripped, not passed through.
 *
 * Section 7.2 of the plan is explicit and narrower than "just prevent XSS":
 * "Render links as plain text in this release; disable raw HTML, images,
 * SVG, MathML, styles, forms, and event attributes. If either library
 * fails to load, render with textContent and disable the HTML preview.
 * Never fall back to unsanitized innerHTML." T10 originally kept `<a>`
 * clickable (with a target/rel hook) and returned an empty string when a
 * vendor library failed to load -- both were real, independently
 * XSS-safe, but neither is what this section actually specifies, caught
 * by a T11 review pass that checked the plan's exact wording rather than
 * re-deriving "safe enough" from first principles.
 *
 * Depends on window.marked (static/vendor/aria-policy/marked.umd.js) and
 * window.DOMPurify (static/vendor/aria-policy/purify.min.js) already being
 * loaded via <script> tags before this file.
 */
(function () {
  'use strict';

  if (typeof window.marked === 'undefined' || typeof window.DOMPurify === 'undefined') {
    // Fail loud in the console rather than silently rendering nothing --
    // a missing vendor script is a deployment bug, not a runtime condition
    // to degrade gracefully around.
    console.error('aria_markdown.js: marked/DOMPurify not loaded -- check script order.');
  }

  // Formatting a policy document plausibly needs: headings, paragraphs,
  // emphasis, lists, blockquotes, code, and tables. It never legitimately
  // needs scripts, forms, embedded frames/objects, inline styles, images
  // (an inline <img src> pointed at an attacker's server is a
  // read-receipt/beacon even when the image itself is inert --
  // branding/logos go through the server-side template system, never
  // through markdown body text), or links: section 7.2 renders links as
  // plain text in this release, so `a` is deliberately absent -- DOMPurify
  // drops a non-allowed tag's own start/end tags but keeps its text
  // content by default, which is exactly "plain text", not "gone".
  var ALLOWED_TAGS = [
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'br', 'hr',
    'strong', 'em', 'b', 'i', 'u', 's', 'del',
    'ul', 'ol', 'li',
    'blockquote',
    'code', 'pre',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
  ];
  var ALLOWED_ATTR = ['align', 'colspan', 'rowspan'];

  /** True once both vendor libraries are confirmed loaded. Callers use
   * this to decide whether to offer a reading-preview toggle at all --
   * section 7.2: "disable the HTML preview" when a library failed to
   * load, not just degrade what render()/renderInto() produce. */
  function isAvailable() {
    return typeof window.marked !== 'undefined' && typeof window.DOMPurify !== 'undefined';
  }

  var textEscapeEl = null;
  function escapeText(text) {
    if (!textEscapeEl) textEscapeEl = document.createElement('div');
    textEscapeEl.textContent = text;
    return textEscapeEl.innerHTML;
  }

  /**
   * Renders markdown to sanitized HTML. Never throws. When marked/DOMPurify
   * are unavailable, or the input fails to parse, returns the input
   * HTML-escaped rather than an empty string -- section 7.2's "render with
   * textContent" fallback, expressed as a string so callers using innerHTML
   * (render()) and callers setting textContent directly (renderInto()
   * below) both end up showing the same real, safe, unstyled text instead
   * of nothing.
   */
  function render(markdownText) {
    if (typeof markdownText !== 'string' || !markdownText.trim()) return '';
    if (!isAvailable()) return escapeText(markdownText);
    var rawHtml;
    try {
      rawHtml = window.marked.parse(markdownText, { gfm: true, breaks: false });
    } catch (e) {
      console.error('aria_markdown.js: marked.parse failed', e);
      return escapeText(markdownText);
    }
    return window.DOMPurify.sanitize(rawHtml, {
      ALLOWED_TAGS: ALLOWED_TAGS,
      ALLOWED_ATTR: ALLOWED_ATTR,
      FORBID_TAGS: ['style', 'script', 'iframe', 'object', 'embed', 'form', 'input', 'button', 'img', 'svg', 'a', 'math'],
      FORBID_ATTR: ['style', 'onerror', 'onload', 'onclick', 'href', 'src', 'xlink:href'],
      RETURN_TRUSTED_TYPE: false,
    });
  }

  /** Convenience: render markdown directly into an element. Sets
   * textContent (never innerHTML) when the vendor libraries are
   * unavailable, matching section 7.2 literally rather than routing
   * through render()'s escaped-HTML-string fallback. */
  function renderInto(el, markdownText) {
    if (!el) return;
    if (!isAvailable()) {
      el.textContent = markdownText || '';
      return;
    }
    el.innerHTML = render(markdownText);
  }

  window.AriaMarkdown = { render: render, renderInto: renderInto, isAvailable: isAvailable };
})();
