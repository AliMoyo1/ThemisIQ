(function(){
  try {
    if (localStorage.getItem('ofa-theme') === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
    }
  } catch (_) { /* A blocked storage API keeps the default Sage theme. */ }
})();
