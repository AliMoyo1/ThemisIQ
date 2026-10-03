/* BCM AI document viewer. Keep its content private to this module. */
(function () {
  'use strict';

  var currentContent = '';
  var currentTitle = '';
  var returnFocus = null;

  function root() {
    return document.getElementById('bcmDocViewerRoot');
  }

  function focusable(panel) {
    return Array.from(panel.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'));
  }

  window.bcmOpenDocViewer = function (title, content) {
    var mount = root();
    if (!mount) return;
    if (!mount.firstElementChild) returnFocus = document.activeElement;
    currentTitle = title == null ? '' : String(title);
    currentContent = content == null ? '' : String(content);
    mount.innerHTML =
      '<div class="bcm-doc-overlay">' +
        '<div class="bcm-doc-panel" tabindex="-1" role="dialog" aria-modal="true" aria-labelledby="bcmDocTitle">' +
          '<div class="bcm-doc-head">' +
            '<div style="font-size:14px;font-weight:700;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" id="bcmDocTitle"></div>' +
            '<div style="display:flex;gap:6px;flex-shrink:0" id="bcmDocHeadBtns">' +
              '<button type="button" class="btn btn-sm btn-secondary" data-bcm-doc-action="copy">Copy</button>' +
              '<button type="button" class="btn btn-sm btn-secondary" data-bcm-doc-action="download">Download</button>' +
              '<button type="button" class="btn btn-sm btn-secondary" data-bcm-doc-action="close" aria-label="Close document viewer">&#10005;</button>' +
            '</div>' +
          '</div>' +
          '<div class="bcm-doc-body" id="bcmDocViewerBody"></div>' +
        '</div>' +
      '</div>';
    mount.querySelector('#bcmDocTitle').textContent = currentTitle;
    mount.querySelector('#bcmDocViewerBody').textContent = currentContent;
    mount.querySelector('[data-bcm-doc-action="copy"]').focus();
  };

  window.bcmCloseDocViewer = function () {
    var mount = root();
    if (!mount || !mount.firstElementChild) return;
    mount.replaceChildren();
    currentContent = '';
    currentTitle = '';
    if (returnFocus && returnFocus.isConnected && typeof returnFocus.focus === 'function') returnFocus.focus();
    returnFocus = null;
  };

  window.bcmDownloadDoc = function (name) {
    var blob = new Blob([currentContent], {type: 'text/plain'});
    var url = URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.href = url;
    link.download = (name || currentTitle || 'bcm-document').replace(/[^a-z0-9]/gi, '_').toLowerCase() + '.txt';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  };

  document.addEventListener('click', function (event) {
    var mount = root();
    if (!mount || !mount.firstElementChild || !mount.contains(event.target)) return;
    if (event.target.classList.contains('bcm-doc-overlay')) {
      window.bcmCloseDocViewer();
      return;
    }
    var button = event.target.closest('[data-bcm-doc-action]');
    if (!button || !mount.contains(button)) return;
    var action = button.dataset.bcmDocAction;
    if (action === 'close') window.bcmCloseDocViewer();
    if (action === 'download') window.bcmDownloadDoc(currentTitle);
    if (action === 'copy') {
      Promise.resolve().then(function () {
        if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') throw new Error('Clipboard unavailable');
        return navigator.clipboard.writeText(currentContent);
      }).then(function () {
        if (typeof showToast === 'function') showToast('Copied!');
      }).catch(function () {
        if (typeof showToast === 'function') showToast('Could not copy document', 'error');
      });
    }
  });

  document.addEventListener('keydown', function (event) {
    var mount = root();
    if (!mount || !mount.firstElementChild) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      window.bcmCloseDocViewer();
      return;
    }
    if (event.key !== 'Tab') return;
    var panel = mount.querySelector('.bcm-doc-panel');
    var items = focusable(panel);
    if (!items.length) { event.preventDefault(); panel.focus(); return; }
    var first = items[0];
    var last = items[items.length - 1];
    if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) {
      event.preventDefault(); first.focus();
    }
  });
})();
