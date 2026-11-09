/* ORM KRI library catalogue and picker. */
(function () {
  'use strict';

var KRI_LIBRARY=[
  {name:'Monthly Fraud Events',description:'Number of fraud incidents per month',metric_type:'count',unit:'events',threshold_warn:3,threshold_crit:8,frequency:'monthly',auto_update_event_type:'fraud'},
  {name:'System Downtime Hours',description:'Total unplanned downtime hours per month',metric_type:'duration',unit:'hours',threshold_warn:4,threshold_crit:12,frequency:'monthly',auto_update_event_type:'outage'},
  {name:'Process Failure Rate',description:'Process failure incidents per month',metric_type:'count',unit:'events',threshold_warn:5,threshold_crit:15,frequency:'monthly',auto_update_event_type:'process_failure'},
  {name:'Human Error Incidents',description:'Human error events per month',metric_type:'count',unit:'events',threshold_warn:3,threshold_crit:8,frequency:'monthly',auto_update_event_type:'human_error'},
  {name:'Vendor Failures',description:'Supplier/vendor failure incidents per quarter',metric_type:'count',unit:'events',threshold_warn:2,threshold_crit:5,frequency:'quarterly',auto_update_event_type:'vendor_failure'},
  {name:'Customer-Impacting Events',description:'Events directly affecting customers per month',metric_type:'count',unit:'events',threshold_warn:3,threshold_crit:10,frequency:'monthly',auto_update_event_type:'customer_impact'},
  {name:'Data Breach / Security Incidents',description:'Security and data breach events',metric_type:'count',unit:'events',threshold_warn:1,threshold_crit:3,frequency:'monthly',auto_update_event_type:'system_failure'},
  {name:'Financial Loss per Month',description:'Total operational loss ($) per month',metric_type:'amount',unit:'$',threshold_warn:10000,threshold_crit:50000,frequency:'monthly',auto_update_event_type:''},
  {name:'Average Resolution Time',description:'Average days to resolve operational events',metric_type:'duration',unit:'days',threshold_warn:5,threshold_crit:14,frequency:'monthly',auto_update_event_type:''},
  {name:'Recurring Events Count',description:'Events flagged as recurring over last 30 days',metric_type:'count',unit:'events',threshold_warn:3,threshold_crit:7,frequency:'monthly',auto_update_event_type:''}
];

  function esc(value) {
    var node = document.createElement('div');
    node.textContent = String(value == null ? '' : value);
    return node.innerHTML;
  }

  window.ormOpenKriLibrary = function () {
    var previous = document.getElementById('kriLibModal');
    if (previous) previous.remove();
    var opener = document.activeElement;
    var overlay = document.createElement('div');
    overlay.className = 'orm-modal-overlay';
    overlay.id = 'kriLibModal';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Choose a KRI from the library');
    overlay.innerHTML = '<div class="modal-box" data-s="sae5b6ed">' +
      '<button type="button" class="modal-close" data-orm-close-kri-library aria-label="Close KRI library">&#10005;</button>' +
      '<div class="modal-title"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-library></use></svg> KRI Library — Pre-built Indicators</div>' +
      '<div data-s="see36960">Click "Add" to pre-fill the KRI form with suggested settings</div>' +
      '<div data-s="s4a37ffe" data-sd="grid">' +
      KRI_LIBRARY.map(function (indicator, index) {
        return '<div data-s="sb12e81d">' +
          '<div data-s="scfbf4c9">' + esc(indicator.name) + '</div>' +
          '<div data-s="sa0f62e4">' + esc(indicator.description) + '</div>' +
          '<div data-s="s4b67c47" data-sd="flex">' +
            '<span data-s="s84f2de7"><svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-alarm-clock></use></svg> ' + esc(indicator.frequency) + '</span>' +
            (indicator.threshold_warn ? '<span data-s="sc8b6fad">Warn: ' + indicator.threshold_warn + '</span>' : '') +
            (indicator.threshold_crit ? '<span data-s="s8d1240d">Crit: ' + indicator.threshold_crit + '</span>' : '') +
            (indicator.auto_update_event_type ? '<span data-s="s58fa7f5">Auto: ' + esc(indicator.auto_update_event_type.replace(/_/g, ' ')) + '</span>' : '') +
          '</div>' +
          '<button type="button" class="btn btn-sm btn-primary" data-orm-kri-index="' + index + '">+ Add this KRI</button>' +
          '</div>';
      }).join('') +
      '</div></div>';

    function closeLibrary() {
      overlay.remove();
      if (opener && opener.isConnected && typeof opener.focus === 'function') opener.focus();
    }

    overlay.addEventListener('click', function (event) {
      if (event.target === overlay) {
        closeLibrary();
        return;
      }
      if (!(event.target instanceof Element)) return;
      var closeButton = event.target.closest('[data-orm-close-kri-library]');
      if (closeButton && overlay.contains(closeButton)) {
        closeLibrary();
        return;
      }
      var addButton = event.target.closest('[data-orm-kri-index]');
      if (!addButton || !overlay.contains(addButton)) return;
      var index = Number(addButton.dataset.ormKriIndex);
      if (!Number.isInteger(index) || !KRI_LIBRARY[index]) return;
      var indicator = KRI_LIBRARY[index];
      closeLibrary();
      window.ormOpenKriModal(indicator);
    });
    overlay.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeLibrary();
        return;
      }
      if (event.key !== 'Tab') return;
      var focusable = overlay.querySelectorAll('button');
      var first = focusable[0];
      var last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    document.body.appendChild(overlay);
    overlay.querySelector('[data-orm-close-kri-library]').focus();
  };
})();
