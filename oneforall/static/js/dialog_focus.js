/**
 * Focus trap + restore for custom dialog-like panels that predate
 * ModalManager (PLAN-36 T02) and use their own bespoke open/close
 * functions and CSS -- slide-in drawers in ERM, ORM, Sentinel, People
 * Directory, Vendor Directory, Evidence's detail panel, etc. Rather than
 * migrate each one onto ModalManager's `.modal-overlay`/`.modal` markup
 * contract (a real visual risk for panels with bespoke width/position/
 * animation CSS), this gives them the same two keyboard properties a
 * dialog needs -- Tab stays inside it, and closing returns focus to
 * whatever opened it -- reusing the identical trap algorithm
 * modal_manager.js already uses.
 *
 * Usage: DialogFocus.trap(containerEl) when the panel opens (containerEl
 * is the panel itself, not its overlay backdrop). Release is automatic:
 * a MutationObserver watches for the container leaving the document and
 * releases then, restoring focus to whatever was focused before trap()
 * was called. This is deliberate, not an oversight -- several of these
 * drawers close themselves from many different call sites (a Cancel
 * button, a backdrop click, a post-save success path, an Escape
 * listener elsewhere in the same file), each doing its own
 * `el.remove()` or `.innerHTML=''`. Requiring every one of those sites
 * to remember to call a release() function is exactly the kind of thing
 * that gets missed once a fifth or sixth close path is added later;
 * watching for the DOM removal itself has no such gap. Callers may still
 * call DialogFocus.release() explicitly for an immediate restore without
 * waiting a tick for the observer, but it is not required for
 * correctness.
 */
(function () {
  var FOCUSABLE_SELECTOR =
    'a[href],button:not([disabled]),textarea:not([disabled]),' +
    'input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

  var current = null; // {container, trigger, observer}

  function focusableEls(container) {
    if (!container) return [];
    return Array.prototype.filter.call(
      container.querySelectorAll(FOCUSABLE_SELECTOR),
      function (el) { return el.offsetParent !== null; }
    );
  }

  function onKeydown(e) {
    if (e.key !== 'Tab' || !current) return;
    var items = focusableEls(current.container);
    if (!items.length) { e.preventDefault(); return; }
    var first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  function trap(container) {
    if (!container) return;
    if (current) release();
    var trigger = document.activeElement;
    var items = focusableEls(container);
    if (items.length) {
      items[0].focus();
    } else {
      if (!container.hasAttribute('tabindex')) container.setAttribute('tabindex', '-1');
      container.focus();
    }
    document.addEventListener('keydown', onKeydown, true);
    var observer = new MutationObserver(function () {
      if (current && current.container === container && !container.isConnected) release();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    current = { container: container, trigger: trigger, observer: observer };
  }

  function release() {
    if (!current) return;
    document.removeEventListener('keydown', onKeydown, true);
    current.observer.disconnect();
    var trigger = current.trigger;
    current = null;
    if (trigger && typeof trigger.focus === 'function') trigger.focus();
  }

  window.DialogFocus = { trap: trap, release: release };
})();
