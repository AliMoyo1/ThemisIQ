/**
 * PLAN-35 T10: sanitized markdown rendering for ARIA policy content.
 *
 * Replaces every direct `marked.parse(...)` -> innerHTML call in ARIA pages.
 * marked() on its own passes raw HTML/script through unchanged -- it is a
 * markdown-to-HTML converter, not a sanitizer. This wraps it with DOMPurify
 * using an explicit allowlist (never a blocklist) so unknown/future tags
 * default to stripped, not passed through.
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
  // emphasis, lists, blockquotes, code, tables, and links to external
  // standards/regulations. It never legitimately needs scripts, forms,
  // embedded frames/objects, inline styles, or images (an inline <img src>
  // pointed at an attacker's server is a read-receipt/beacon even when the
  // image itself is inert -- branding/logos go through the server-side
  // template system, never through markdown body text).
  var ALLOWED_TAGS = [
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'br', 'hr',
    'strong', 'em', 'b', 'i', 'u', 's', 'del',
    'ul', 'ol', 'li',
    'blockquote',
    'code', 'pre',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'a',
  ];
  var ALLOWED_ATTR = ['href', 'title', 'align', 'colspan', 'rowspan'];
  // http/https/mailto only -- blocks javascript:, data:, vbscript: and any
  // other scheme a crafted markdown link could use to run script or exfiltrate
  // data on click. A bare #fragment is also allowed (safe: client-side only).
  var ALLOWED_URI_REGEXP = /^(?:https?|mailto):|^#/i;

  var hooksInstalled = false;
  function installHooksOnce() {
    if (hooksInstalled || typeof window.DOMPurify === 'undefined') return;
    hooksInstalled = true;
    // Every external link opens in a new tab without giving the destination
    // page a handle back to this one (reverse tabnabbing) -- DOMPurify's
    // allowlist alone doesn't add this, it has to be a hook.
    DOMPurify.addHook('afterSanitizeAttributes', function (node) {
      if (node.tagName === 'A' && node.hasAttribute('href')) {
        node.setAttribute('target', '_blank');
        node.setAttribute('rel', 'noopener noreferrer nofollow');
      }
    });
  }

  /**
   * Renders markdown to sanitized HTML. Never throws -- an unparseable
   * input (or a missing vendor library) renders as empty rather than
   * leaving stale/unrelated content on screen or crashing the caller.
   */
  function render(markdownText) {
    if (typeof markdownText !== 'string' || !markdownText.trim()) return '';
    if (typeof window.marked === 'undefined' || typeof window.DOMPurify === 'undefined') return '';
    installHooksOnce();
    var rawHtml;
    try {
      rawHtml = window.marked.parse(markdownText, { gfm: true, breaks: false });
    } catch (e) {
      console.error('aria_markdown.js: marked.parse failed', e);
      return '';
    }
    return window.DOMPurify.sanitize(rawHtml, {
      ALLOWED_TAGS: ALLOWED_TAGS,
      ALLOWED_ATTR: ALLOWED_ATTR,
      ALLOWED_URI_REGEXP: ALLOWED_URI_REGEXP,
      FORBID_TAGS: ['style', 'script', 'iframe', 'object', 'embed', 'form', 'input', 'button', 'img', 'svg'],
      FORBID_ATTR: ['style', 'onerror', 'onload', 'onclick'],
      RETURN_TRUSTED_TYPE: false,
    });
  }

  /** Convenience: render markdown directly into an element's innerHTML. */
  function renderInto(el, markdownText) {
    if (!el) return;
    el.innerHTML = render(markdownText);
  }

  window.AriaMarkdown = { render: render, renderInto: renderInto };
})();
