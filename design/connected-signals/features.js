/* Interactive additions for the standalone Connected Signals study. */
const ribbonTrack = document.getElementById('framework-track');
if (ribbonTrack) {
  const catalogue = ribbonTrack.querySelector('.ribbon-set[role="list"]');
  const duplicate = ribbonTrack.querySelector('.ribbon-set[aria-hidden="true"]');
  if (catalogue && duplicate) {
    duplicate.innerHTML = catalogue.innerHTML;
    ribbonTrack.classList.add('is-ready');
  }
}

const invite = document.getElementById('hero-invite');
document.querySelectorAll('[data-select-module]').forEach(button => {
  button.addEventListener('click', () => {
    const name = {aria:'Governance',grid:'Audit',bcm:'Resilience',sentinel:'Privacy',erm:'Enterprise risk',orm:'Operations risk'}[button.dataset.selectModule] || 'this module';
    if (invite) invite.lastChild.textContent = ' Previewing ' + name + ' in the product window';
  });
});
document.getElementById('reset-view').addEventListener('click', () => {
  if (invite) invite.lastChild.textContent = ' Select a module to preview its dashboard';
});

const featureTabs = Array.from(document.querySelectorAll('.feature-tab'));
const featureScenes = Array.from(document.querySelectorAll('.feature-scene'));
const featurePanel = document.getElementById('feature-panel');
const featureConsole = document.querySelector('.feature-console');
const featureNames = {
  privacy: {label: '01 / PRIVACY RESPONSE', accent: '#3b5bdb', soft: 'rgba(59,91,219,.12)'},
  response: {label: '02 / CONNECTED RESPONSE', accent: '#881337', soft: 'rgba(136,19,55,.11)'},
  evidence: {label: '03 / SHARED EVIDENCE', accent: '#7d6527', soft: 'rgba(125,101,39,.11)'},
  command: {label: '04 / PERSONAL COMMAND CENTRE', accent: '#326e62', soft: 'rgba(50,110,98,.11)'}
};

function selectFeature(key, focusTab) {
  const config = featureNames[key];
  if (!config) return;
  featureTabs.forEach(tab => {
    const active = tab.dataset.feature === key;
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active && focusTab) tab.focus();
  });
  featureScenes.forEach(scene => {
    scene.hidden = scene.dataset.scene !== key;
  });
  featurePanel.setAttribute('aria-labelledby', 'feature-tab-' + key);
  document.getElementById('feature-panel-index').textContent = config.label;
  featureConsole.style.setProperty('--active-accent', config.accent);
  featureConsole.style.setProperty('--active-soft', config.soft);
  if (key === 'response') replayResponse();
}

featureTabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectFeature(tab.dataset.feature, false));
  tab.addEventListener('keydown', event => {
    let next = index;
    if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = (index + 1) % featureTabs.length;
    else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = (index - 1 + featureTabs.length) % featureTabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = featureTabs.length - 1;
    else return;
    event.preventDefault();
    selectFeature(featureTabs[next].dataset.feature, true);
  });
});
selectFeature('privacy', false);

const responseDemo = document.getElementById('response-demo');
function replayResponse() {
  responseDemo.classList.remove('is-replaying');
  void responseDemo.offsetWidth;
  responseDemo.classList.add('is-replaying');
}
document.getElementById('replay-response').addEventListener('click', replayResponse);

const privacyRules = {
  gdpr: {name: 'EU GDPR', authority: 'National DPA', hours: 72, dsr: 30, window: '72 h example', caption: 'Based on a sample incident recorded 23 h 18 m ago'},
  kenya: {name: 'Kenya DPA', authority: 'ODPC', hours: 72, dsr: 21, window: '72 h example', caption: 'Based on a sample incident recorded 23 h 18 m ago'},
  zimbabwe: {name: 'Zimbabwe CDPA', authority: 'POTRAZ', hours: 24, dsr: 'Review locally', window: '24 h example', caption: 'Sample incident: 23 h 18 m since awareness. Authority notification is urgent.'},
  popia: {name: 'South Africa POPIA', authority: 'Information Regulator', hours: null, dsr: 30, window: 'Notify promptly', caption: 'Prompt action shown without a fixed hour timer'},
  ccpa: {name: 'California CCPA', authority: 'CPPA (CA)', hours: null, dsr: 45, window: 'No fixed hours', caption: 'Assess notification duties for this example'}
};
const privacyButtons = Array.from(document.querySelectorAll('[data-jurisdiction]'));
const demoStartedAt = Date.now() - ((23 * 60 + 18) * 60 * 1000);
let selectedJurisdiction = 'gdpr';

function updatePrivacyClock() {
  const rule = privacyRules[selectedJurisdiction];
  const clock = document.getElementById('privacy-clock');
  const orbit = document.querySelector('.timer-orbit');
  if (rule.hours === null) {
    clock.textContent = selectedJurisdiction === 'popia' ? 'ACT PROMPTLY' : 'ASSESS NOW';
    document.querySelector('.timer-orbit>span').innerHTML = selectedJurisdiction === 'popia' ? 'ASAP' : 'RULE';
    orbit.style.setProperty('--timer-progress', '100%');
    document.getElementById('privacy-progress').style.width = '100%';
    return;
  }
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - demoStartedAt) / 1000));
  const remaining = Math.max(0, rule.hours * 3600 - elapsedSeconds);
  const hours = String(Math.floor(remaining / 3600)).padStart(2, '0');
  const minutes = String(Math.floor((remaining % 3600) / 60)).padStart(2, '0');
  const seconds = String(remaining % 60).padStart(2, '0');
  clock.textContent = hours + ':' + minutes + ':' + seconds;
  document.querySelector('.timer-orbit>span').innerHTML = String(rule.hours) + '<span>H</span>';
  const progress = Math.min(100, Math.round(elapsedSeconds / (rule.hours * 3600) * 100));
  orbit.style.setProperty('--timer-progress', progress + '%');
  document.getElementById('privacy-progress').style.width = progress + '%';
}

privacyButtons.forEach(button => button.addEventListener('click', () => {
  const key = button.dataset.jurisdiction;
  const rule = privacyRules[key];
  if (!rule) return;
  selectedJurisdiction = key;
  privacyButtons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  document.getElementById('privacy-authority').textContent = rule.authority;
  document.getElementById('privacy-window').textContent = rule.window;
  document.getElementById('privacy-dsr').textContent = typeof rule.dsr === 'number' ? rule.dsr + ' days' : rule.dsr;
  document.getElementById('privacy-timer-caption').textContent = rule.caption;
  document.getElementById('privacy-status').textContent = rule.name + ' selected. Example notification rule: ' + rule.window + '.';
  updatePrivacyClock();
}));
updatePrivacyClock();
window.setInterval(updatePrivacyClock, 1000);

const evidenceLinks = {
  aria: {label: 'GOVERNANCE / ARIA', title: 'Proof beside the control', body: 'Reviewers can open the supporting file from the control they are assessing.'},
  grid: {label: 'AUDIT / GRID', title: 'Evidence in the audit trail', body: 'The same file can support the audit record without another upload.'},
  bcm: {label: 'RESILIENCE / BCM', title: 'Context for an incident', body: 'Continuity teams can link the file to the incident they are investigating.'}
};
const evidenceDetail = document.querySelector('.evidence-detail');
document.querySelectorAll('[data-evidence-link]').forEach(button => button.addEventListener('click', () => {
  const detail = evidenceLinks[button.dataset.evidenceLink];
  if (!detail) return;
  document.querySelectorAll('[data-evidence-link]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  document.getElementById('evidence-detail-label').textContent = detail.label;
  document.getElementById('evidence-detail-title').textContent = detail.title;
  document.getElementById('evidence-detail-body').textContent = detail.body;
  evidenceDetail.classList.remove('is-changing');
  void evidenceDetail.offsetWidth;
  evidenceDetail.classList.add('is-changing');
}));

const commandCards = document.getElementById('command-cards');
const moveAudit = document.getElementById('move-audit');
const toggleBriefing = document.getElementById('toggle-briefing');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

function animateCardLayout(change) {
  const cards = Array.from(commandCards.querySelectorAll('.command-card'));
  if (reducedMotion.matches || typeof cards[0].animate !== 'function') {
    change();
    return;
  }
  const before = new Map(cards.filter(card => !card.hidden && getComputedStyle(card).display !== 'none').map(card => [card, card.getBoundingClientRect()]));
  change();
  requestAnimationFrame(() => {
    cards.forEach(card => {
      const old = before.get(card);
      if (!old || getComputedStyle(card).display === 'none') return;
      const now = card.getBoundingClientRect();
      const dx = old.left - now.left;
      const dy = old.top - now.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      card.animate([{transform: 'translate(' + dx + 'px,' + dy + 'px)'}, {transform: 'translate(0,0)'}], {duration: 440, easing: 'cubic-bezier(.22,.61,.36,1)'});
    });
  });
}

moveAudit.addEventListener('click', () => {
  const active = !commandCards.classList.contains('audit-first');
  animateCardLayout(() => commandCards.classList.toggle('audit-first', active));
  moveAudit.setAttribute('aria-pressed', String(active));
  moveAudit.firstChild.textContent = active ? 'Restore card order ' : 'Move audit first ';
});
toggleBriefing.addEventListener('click', () => {
  const hidden = !commandCards.classList.contains('briefing-hidden');
  animateCardLayout(() => commandCards.classList.toggle('briefing-hidden', hidden));
  toggleBriefing.setAttribute('aria-pressed', String(hidden));
  toggleBriefing.firstChild.textContent = hidden ? 'Bring briefing back ' : 'Hide briefing ';
});

if ('IntersectionObserver' in window && !reducedMotion.matches) {
  const revealTargets = document.querySelectorAll('.intro-grid,.system-strip,.flow-header,.flow-experience,.feature-heading,.feature-console,.modules-heading,.modules-layout,.approach-heading,.approach-grid,.contact-inner');
  revealTargets.forEach(target => target.dataset.reveal = '');
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      entry.target.classList.add('is-visible');
      observer.unobserve(entry.target);
    });
  }, {rootMargin: '0px 0px -7% 0px', threshold: .08});
  document.documentElement.classList.add('motion-ready');
  revealTargets.forEach(target => observer.observe(target));
}
