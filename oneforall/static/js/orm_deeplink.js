/* ── PLAN-06 deep-link boot handler ── */
(function(){
  var openParam = new URLSearchParams(window.location.search).get('open');
  if(!openParam) return;
  var sep = openParam.indexOf(':');
  if(sep < 1) return;
  var etype = openParam.slice(0, sep);
  var eid = parseInt(openParam.slice(sep + 1), 10);
  if(!eid) return;
  window.history.replaceState({}, '', window.location.pathname);
  var tries = 0;
  function attempt(){
    tries++;
    try { _plan06_fn(eid); } catch(e){ if(tries < 20) setTimeout(attempt, 250); }
  }
  var _plan06_openers = {
    'event': function(id){ ormOpenEventDrawer(id); }
  };
  var _plan06_fn = _plan06_openers[etype];
  if(!_plan06_fn) return;
  attempt();
})();
