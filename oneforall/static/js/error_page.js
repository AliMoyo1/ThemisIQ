// Error page "Go Back" under strict script policy: step back when there is a page to return to, else follow the link home.
document.addEventListener('click', function (event) {
  var link = event.target instanceof Element ? event.target.closest('[data-history-back]') : null;
  if (link && window.history.length > 1) {
    event.preventDefault();
    window.history.back();
  }
});
