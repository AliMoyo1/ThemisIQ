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
    overlay.innerHTML = '<div class="modal-box" style="max-width:700px;max-height:80vh;overflow-y:auto">' +
      '<button type="button" class="modal-close" data-orm-close-kri-library aria-label="Close KRI library">&#10005;</button>' +
      '<div class="modal-title">&#128218; KRI Library — Pre-built Indicators</div>' +
      '<div style="font-size:12px;color:var(--muted);margin-bottom:16px">Click "Add" to pre-fill the KRI form with suggested settings</div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">' +
      KRI_LIBRARY.map(function (indicator, index) {
        return '<div style="background:var(--surface2);border-radius:var(--radius);padding:12px;border:1px solid var(--border)">' +
          '<div style="font-size:13px;font-weight:700;margin-bottom:4px">' + esc(indicator.name) + '</div>' +
          '<div style="font-size:11px;color:var(--muted);margin-bottom:8px">' + esc(indicator.description) + '</div>' +
          '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">' +
            '<span style="font-size:10px;background:var(--surface3);padding:2px 7px;border-radius:100px;color:var(--muted)">&#9200; ' + esc(indicator.frequency) + '</span>' +
            (indicator.threshold_warn ? '<span style="font-size:10px;background:rgba(217,119,6,.1);padding:2px 7px;border-radius:100px;color:var(--amber,#d97706)">Warn: ' + indicator.threshold_warn + '</span>' : '') +
            (indicator.threshold_crit ? '<span style="font-size:10px;background:rgba(220,38,38,.1);padding:2px 7px;border-radius:100px;color:var(--red)">Crit: ' + indicator.threshold_crit + '</span>' : '') +
            (indicator.auto_update_event_type ? '<span style="font-size:10px;background:var(--surface3);padding:2px 7px;border-radius:100px;color:var(--accent)">Auto: ' + esc(indicator.auto_update_event_type.replace(/_/g, ' ')) + '</span>' : '') +
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
