/**
 * Shared modal dialog manager (PLAN-36 T02).
 *
 * Canonical markup: outer `.modal-overlay` (also the click-to-close
 * backdrop), inner `.modal`, visible state `.open`. Owns: open/close,
 * initial focus, Tab/Shift+Tab focus trap, Escape, backdrop click,
 * focus restoration to the trigger, and body scroll lock.
 *
 * Usage: ModalManager.open('someModalId') / ModalManager.close('someModalId')
 * in place of the old `document.getElementById(id).classList.add('open')`.
 */
(function () {
  var openStack = [];   // ids of open modals, most-recently-opened last
  var triggerEls = {};  // id -> element focused just before open()
  var closeGuards = {}; // id -> function(): boolean (false blocks close)
  var scrollLockCount = 0;

  var FOCUSABLE_SELECTOR =
    'a[href],button:not([disabled]),textarea:not([disabled]),' +
    'input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

  function overlayEl(id) { return document.getElementById(id); }
  function dialogEl(overlay) { return overlay ? overlay.querySelector('.modal') : null; }

  function focusableEls(container) {
    if (!container) return [];
    return Array.prototype.filter.call(
      container.querySelectorAll(FOCUSABLE_SELECTOR),
      function (el) { return el.offsetParent !== null; } // skip hidden elements
    );
  }

  function lockScroll() {
    if (scrollLockCount === 0) document.body.style.overflow = 'hidden';
    scrollLockCount++;
  }

  function unlockScroll() {
    scrollLockCount = Math.max(0, scrollLockCount - 1);
    if (scrollLockCount === 0) document.body.style.overflow = '';
  }

  function topId() { return openStack[openStack.length - 1]; }

  function onKeydown(e) {
    var id = topId();
    if (!id) return;
    if (e.key === 'Escape') {
      e.stopPropagation();
      close(id);
      return;
    }
    if (e.key !== 'Tab') return;
    var dialog = dialogEl(overlayEl(id));
    var items = focusableEls(dialog);
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

  function onOverlayClick(e) {
    if (e.target === e.currentTarget) close(e.currentTarget.id);
  }

  function open(id) {
    var overlay = overlayEl(id);
    if (!overlay || overlay.classList.contains('open')) return;

    triggerEls[id] = document.activeElement;
    overlay.classList.add('open');
    openStack.push(id);
    lockScroll();
    overlay.addEventListener('click', onOverlayClick);
    if (openStack.length === 1) document.addEventListener('keydown', onKeydown, true);

    var dialog = dialogEl(overlay);
    var items = focusableEls(dialog);
    if (items.length) {
      items[0].focus();
    } else if (dialog) {
      if (!dialog.hasAttribute('tabindex')) dialog.setAttribute('tabindex', '-1');
      dialog.focus();
    }
  }

  function close(id, opts) {
    opts = opts || {};
    var idx = openStack.indexOf(id);
    if (idx === -1) return;
    if (!opts.force && closeGuards[id] && !closeGuards[id]()) return;

    var overlay = overlayEl(id);
    if (overlay) {
      overlay.classList.remove('open');
      overlay.removeEventListener('click', onOverlayClick);
    }
    openStack.splice(idx, 1);
    unlockScroll();
    if (!openStack.length) document.removeEventListener('keydown', onKeydown, true);

    var trigger = triggerEls[id];
    delete triggerEls[id];
    if (trigger && typeof trigger.focus === 'function') trigger.focus();
  }

  /** Register fn(): boolean, called before a non-forced close(id); return
   * false to block (e.g. an in-flight or dirty destructive form). */
  function registerCloseGuard(id, fn) { closeGuards[id] = fn; }

  function isOpen(id) { return openStack.indexOf(id) !== -1; }

  window.ModalManager = {
    open: open,
    close: close,
    isOpen: isOpen,
    registerCloseGuard: registerCloseGuard,
  };
})();
