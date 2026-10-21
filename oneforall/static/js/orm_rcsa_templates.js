/* ORM RCSA template catalogue and picker. */
(function () {
  'use strict';

var RCSA_TEMPLATES=[
  {id:'it_cyber',title:'IT Operations & Cybersecurity',scope:'Information Technology',icon:'💻',description:'Covers data security, system availability, access control, patch management, and incident response.',
   risks:[
    {title:'Unauthorized Access / Data Breach',inherent_likelihood:3,inherent_impact:5,control_effectiveness:3,controls:['Access control reviews (quarterly)','MFA on all critical systems','Privileged Access Management (PAM)']},
    {title:'Ransomware / Malware Infection',inherent_likelihood:3,inherent_impact:5,control_effectiveness:3,controls:['Endpoint detection & response (EDR)','Offline backup testing (monthly)','Security patch management (<30d critical)']},
    {title:'Unplanned System Outage',inherent_likelihood:3,inherent_impact:4,control_effectiveness:3,controls:['Change management process (CAB)','High-availability / failover configuration','Incident response runbooks']},
    {title:'Vendor / Third-Party Access Risk',inherent_likelihood:3,inherent_impact:4,control_effectiveness:2,controls:['Third-party access register','Vendor access reviews (quarterly)','Contractual security obligations (ISO/SOC)']},
    {title:'Insider Threat / Data Exfiltration',inherent_likelihood:2,inherent_impact:5,control_effectiveness:3,controls:['DLP tools on email and endpoints','User activity monitoring (UAM)','Offboarding access revocation checklist']}
  ]},
  {id:'privacy_gdpr',title:'Privacy & Data Protection (GDPR)',scope:'Data Protection / Privacy',icon:'🔒',description:'Covers consent management, data subject rights, breach notification, cross-border transfers, and data minimization.',
   risks:[
    {title:'Unlawful Data Processing / Consent Failure',inherent_likelihood:3,inherent_impact:4,control_effectiveness:3,controls:['ROPA maintained and reviewed','Consent management platform active','Legal basis documented per process']},
    {title:'Data Subject Rights Failure (DSR)',inherent_likelihood:3,inherent_impact:3,control_effectiveness:3,controls:['DSR intake and tracking process','Response within 30 days (GDPR Art.12)','DSR register maintained']},
    {title:'Cross-Border Transfer Risk',inherent_likelihood:2,inherent_impact:4,control_effectiveness:3,controls:['Transfer impact assessments (TIA)','SCCs / adequacy decision reviewed','Transfer registry maintained']},
    {title:'Breach Notification Failure',inherent_likelihood:2,inherent_impact:5,control_effectiveness:3,controls:['Breach detection tools (SIEM/DLP)','72-hour notification procedure','Incident severity classification guide']},
    {title:'Privacy by Design not embedded',inherent_likelihood:3,inherent_impact:3,control_effectiveness:2,controls:['DPIA process for new processing','Privacy review in project approval gate','Data minimization standards']}
  ]},
  {id:'financial',title:'Financial Controls',scope:'Finance & Accounting',icon:'💰',description:'Covers fraud prevention, payment controls, financial reporting accuracy, and budget governance.',
   risks:[
    {title:'Internal Fraud / Misappropriation',inherent_likelihood:2,inherent_impact:5,control_effectiveness:3,controls:['Segregation of duties (SoD)','Dual authorization on payments >$10k','Monthly reconciliations reviewed by management']},
    {title:'Payment Processing Error',inherent_likelihood:3,inherent_impact:3,control_effectiveness:3,controls:['Automated reconciliation tool','Exception reporting dashboard','Daily bank reconciliation']},
    {title:'Financial Reporting Inaccuracy',inherent_likelihood:2,inherent_impact:4,control_effectiveness:3,controls:['Monthly close checklist','CFO review and sign-off','ERP access control reviews']},
    {title:'Budget Overrun / Variance',inherent_likelihood:3,inherent_impact:3,control_effectiveness:3,controls:['Budget vs actuals review (monthly)','Procurement approval limits enforced','Variance explanation required >5%']}
  ]},
  {id:'hr_people',title:'Human Resources & People',scope:'Human Resources',icon:'👥',description:'Covers key person risk, conduct, training compliance, recruitment, and workforce management.',
   risks:[
    {title:'Key Person Dependency',inherent_likelihood:3,inherent_impact:4,control_effectiveness:2,controls:['Cross-training / knowledge transfer plans','Succession plans for critical roles','Process documentation maintained']},
    {title:'Workforce Misconduct / Policy Breach',inherent_likelihood:2,inherent_impact:3,control_effectiveness:3,controls:['Code of conduct training (annual)','Whistleblower / speak-up channel','Disciplinary policy enforced consistently']},
    {title:'Training Compliance Failure',inherent_likelihood:3,inherent_impact:3,control_effectiveness:3,controls:['Mandatory training tracking system','Completion deadlines enforced','Manager accountability for team completion']},
    {title:'Poor Recruitment / Onboarding Controls',inherent_likelihood:2,inherent_impact:3,control_effectiveness:3,controls:['Background screening for all new hires','Structured onboarding checklist','Role-based access provisioned on day 1']}
  ]},
  {id:'vendor_supply',title:'Vendor & Supply Chain',scope:'Procurement / Vendor Management',icon:'📦',description:'Covers critical vendor dependency, vendor security, contract management, and third-party compliance.',
   risks:[
    {title:'Critical Vendor Failure / Dependency',inherent_likelihood:2,inherent_impact:4,control_effectiveness:2,controls:['Single-source vendor risk register','Alternative vendor pre-qualified','Vendor SLA monitoring dashboard']},
    {title:'Vendor Data Security Breach',inherent_likelihood:2,inherent_impact:4,control_effectiveness:2,controls:['Annual vendor security assessment','Data processing agreements (DPA)','Minimum security standards contractual requirement']},
    {title:'Contract Expiry / Non-Renewal Risk',inherent_likelihood:3,inherent_impact:3,control_effectiveness:2,controls:['Contract expiry calendar/alerts','90-day renewal review process','Legal review of key contracts']},
    {title:'Third-Party Compliance Failure',inherent_likelihood:2,inherent_impact:3,control_effectiveness:2,controls:['Annual compliance questionnaire','Right-to-audit clause in contracts','Vendor compliance certificate on file']}
  ]},
  {id:'bcm_resilience',title:'Business Continuity & Resilience',scope:'Business Continuity',icon:'🔄',description:'Covers disaster recovery, crisis communication, regulatory resilience requirements, and BCP testing.',
   risks:[
    {title:'Disaster Recovery / BCP Failure',inherent_likelihood:2,inherent_impact:5,control_effectiveness:3,controls:['Annual BCP / DR test (documented)','Recovery objectives (RTO/RPO) defined and tested','Offsite backup verified monthly']},
    {title:'Crisis Communication Breakdown',inherent_likelihood:2,inherent_impact:4,control_effectiveness:2,controls:['Crisis communication plan documented','Contact tree tested annually','Spokesperson trained and designated']},
    {title:'Regulatory Resilience Non-Compliance',inherent_likelihood:2,inherent_impact:4,control_effectiveness:3,controls:['Regulatory resilience calendar maintained','Senior manager accountability (SMCR/DORA)','Annual resilience self-assessment']},
    {title:'Critical Process Outage',inherent_likelihood:2,inherent_impact:4,control_effectiveness:3,controls:['BIA reviewed annually','Critical process workarounds documented','Backup IT site / cloud failover tested']}
  ]}
];

  function esc(value) {
    var node = document.createElement('div');
    node.textContent = String(value == null ? '' : value);
    return node.innerHTML;
  }

  window.ormOpenTemplatePickerModal = function () {
    var previous = document.getElementById('tmplPickerModal');
    if (previous) previous.remove();
    var opener = document.activeElement;
    var overlay = document.createElement('div');
    overlay.className = 'orm-modal-overlay';
    overlay.id = 'tmplPickerModal';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Choose an RCSA template');
    overlay.innerHTML = '<div class="modal-box" style="max-width:800px;max-height:85vh;overflow-y:auto">' +
      '<button type="button" class="modal-close" data-orm-close-template-picker aria-label="Close template picker">&#10005;</button>' +
      '<div class="modal-title">&#128203; Start from a Template</div>' +
      '<div style="font-size:12px;color:var(--muted);margin-bottom:20px">Select a template to pre-populate your assessment with common risks and suggested controls</div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">' +
      RCSA_TEMPLATES.map(function (template, index) {
        return '<div style="background:var(--surface2);border-radius:var(--radius-lg);padding:16px;border:1px solid var(--border)">' +
          '<div style="font-size:20px;margin-bottom:6px">' + template.icon + '</div>' +
          '<div style="font-size:14px;font-weight:700;margin-bottom:4px">' + esc(template.title) + '</div>' +
          '<div style="font-size:11px;color:var(--accent);font-weight:600;margin-bottom:8px">' + esc(template.scope) + '</div>' +
          '<div style="font-size:12px;color:var(--muted);margin-bottom:10px;line-height:1.4">' + esc(template.description) + '</div>' +
          '<div style="font-size:11px;color:var(--muted);margin-bottom:10px">' + template.risks.length + ' risks included</div>' +
          '<details style="margin-bottom:10px"><summary style="font-size:11px;color:var(--accent);cursor:pointer">Preview risks &#9660;</summary>' +
          '<ul style="margin:6px 0 0 0;padding-left:16px">' + template.risks.map(function (risk) {
            return '<li style="font-size:11px;color:var(--muted);margin-bottom:2px">' + esc(risk.title) + '</li>';
          }).join('') + '</ul></details>' +
          '<button type="button" class="btn btn-primary" style="width:100%" data-orm-template-index="' + index + '">Use this template &#8594;</button>' +
          '</div>';
      }).join('') +
      '</div></div>';

    function closePicker() {
      overlay.remove();
      if (opener && opener.isConnected && typeof opener.focus === 'function') opener.focus();
    }

    overlay.addEventListener('click', function (event) {
      if (event.target === overlay) {
        closePicker();
        return;
      }
      if (!(event.target instanceof Element)) return;
      var closeButton = event.target.closest('[data-orm-close-template-picker]');
      if (closeButton && overlay.contains(closeButton)) {
        closePicker();
        return;
      }
      var useButton = event.target.closest('[data-orm-template-index]');
      if (!useButton || !overlay.contains(useButton)) return;
      var index = Number(useButton.dataset.ormTemplateIndex);
      if (!Number.isInteger(index) || !RCSA_TEMPLATES[index]) return;
      var template = RCSA_TEMPLATES[index];
      window._selectedRcsaTemplate = template;
      closePicker();
      window.ormOpenRcsaModal({ title: template.title + '- RCSA', scope: template.scope });
    });
    overlay.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        event.preventDefault();
        closePicker();
        return;
      }
      if (event.key !== 'Tab') return;
      var focusable = overlay.querySelectorAll('button, summary');
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
    overlay.querySelector('[data-orm-close-template-picker]').focus();
  };
})();
