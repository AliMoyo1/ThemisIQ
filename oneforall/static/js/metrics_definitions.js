(function(){
  var list = document.getElementById('metricsList');
  var failed = document.getElementById('metricsFailed');
  var GROUPS = [['cc', 'Command Centre'], ['bcm', 'Business continuity'], ['sentinel', 'Privacy'], ['vault', 'Evidence Vault']];
  function el(tag, props, kids){
    var n = document.createElement(tag);
    Object.keys(props || {}).forEach(function(k){ if(k === 'text') n.textContent = props[k]; else if(k === 'style') n.style.cssText = props[k]; else n.setAttribute(k, props[k]); });
    (kids || []).forEach(function(c){ if(c) n.appendChild(c); });
    return n;
  }
  function row(dl, label, value){
    if(value === null || value === undefined || value === '') return;
    dl.appendChild(el('dt', {text: label})); dl.appendChild(el('dd', {text: value}));
  }
  function render(defs){
    list.textContent = '';
    GROUPS.forEach(function(g){
      var items = defs.filter(function(d){ return d.key.indexOf(g[0] + '.') === 0; });
      if(!items.length) return;
      var wrap = el('section', {class: 'metrics-group'}, [el('h2', {text: g[1]})]);
      items.forEach(function(d){
        var dl = el('dl');
        row(dl, 'Means', d.definition);
        row(dl, 'Rows counted', d.eligibility);
        row(dl, 'A share of', d.denominator);
        row(dl, 'Window', d.window);
        row(dl, 'Who sees what', d.scope);
        row(dl, 'Figure owner', d.ownership === 'organization' ? 'Organization-wide, shared across its business units.' :
          d.ownership === 'mixed_sources' ? 'Combined from the named sources, each with its own owner and access rule.' :
          'Source rows belong to a business unit or to the organization. The viewer sees only permitted rows.');
        row(dl, 'Refreshed', d.refresh);
        row(dl, 'Left out', d.exclusions);
        var card = el('div', {class: 'metrics-card'}, [
          el('h3', {text: d.label}), el('div', {class: 'metrics-key', text: d.key}), dl]);
        if(typeof d.drilldown === 'string' && d.drilldown.charAt(0) === '/'){
          card.appendChild(el('a', {href: d.drilldown, text: d.exact ? 'Open the rows that are counted' : 'Open the module (the list is not filtered to these rows)', style: 'font-size:12.5px;display:inline-block;margin-top:8px'}));
        }
        wrap.appendChild(card);
      });
      list.appendChild(wrap);
    });
  }
  async function load(){
    failed.style.display = 'none';
    try{
      var data = await ApiClient.request('/api/metrics/definitions', {actionId: 'metrics.definitions'});
      render(data.definitions || []);
    }catch(e){
      list.textContent = '';
      failed.style.display = 'block';
    }
  }
  document.getElementById('metricsRetry').addEventListener('click', load);
  document.addEventListener('DOMContentLoaded', load);
})();
