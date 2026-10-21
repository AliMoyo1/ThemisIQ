/* Local interactions for the Connected Signals design study. No live data is requested. */
const flowStepButtons = Array.from(document.querySelectorAll('[data-flow-step]'));
const flowNodeButtons = Array.from(document.querySelectorAll('[data-flow-node]'));
const flowNetwork = document.getElementById('flow-network');
const flowReadout = document.getElementById('flow-readout');
const flowReadouts = ['EVENT RECORDED', 'RESPONSE CONTEXT LINKED', 'EVIDENCE IN VIEW', 'COMMAND VIEW UPDATED'];
const motionReduced = window.matchMedia('(prefers-reduced-motion: reduce)');
let replayTimers = [];
let flowReplaying = false;
let flowPlayedOnView = false;

function stopFlowReplay() {
  replayTimers.forEach(timer => window.clearTimeout(timer));
  replayTimers = [];
  flowReplaying = false;
}

function showFlowNode(index) {
  if (!Number.isInteger(index) || index < 0 || index >= flowNodeButtons.length) return;
  flowNetwork.dataset.active = String(index);
  flowReadout.textContent = flowReadouts[index];
  flowNodeButtons.forEach(node => node.setAttribute('aria-pressed', String(Number(node.dataset.flowNode) === index)));
}
flowStepButtons.forEach(button => button.addEventListener('click', () => {
  if (!flowReplaying) stopFlowReplay();
  showFlowNode(Number(button.dataset.flowStep));
}));
flowNodeButtons.forEach(node => node.addEventListener('click', () => {
  stopFlowReplay();
  flowStepButtons[Number(node.dataset.flowNode)].click();
}));
function replayFlow() {
  stopFlowReplay();
  if (motionReduced.matches) {
    flowStepButtons[3].click();
    return;
  }
  flowReplaying = true;
  flowStepButtons[0].click();
  [1, 2, 3].forEach((index, position) => {
    replayTimers.push(window.setTimeout(() => {
      flowStepButtons[index].click();
      if (position === 2) flowReplaying = false;
    }, (position + 1) * 1050));
  });
}
document.getElementById('flow-replay').addEventListener('click', replayFlow);
if ('IntersectionObserver' in window && !motionReduced.matches) {
  const flowObserver = new IntersectionObserver(entries => {
    if (!entries.some(entry => entry.isIntersecting) || flowPlayedOnView) return;
    flowPlayedOnView = true;
    replayFlow();
    flowObserver.disconnect();
  }, {threshold: .45});
  flowObserver.observe(document.getElementById('flow-display'));
}

const intelTabs = Array.from(document.querySelectorAll('[data-intel-tab]'));
const intelPanels = Array.from(document.querySelectorAll('[data-intel-panel]'));
function selectIntel(key, focus) {
  if (!intelPanels.some(panel => panel.dataset.intelPanel === key)) return;
  intelTabs.forEach(tab => {
    const selected = tab.dataset.intelTab === key;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    if (selected && focus) tab.focus();
  });
  intelPanels.forEach(panel => { panel.hidden = panel.dataset.intelPanel !== key; });
}
intelTabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectIntel(tab.dataset.intelTab, false));
  tab.addEventListener('keydown', event => {
    let next = index;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % intelTabs.length;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + intelTabs.length) % intelTabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = intelTabs.length - 1;
    else return;
    event.preventDefault();
    selectIntel(intelTabs[next].dataset.intelTab, true);
  });
});

const draftTypes = {
  dpia: {module:'SENTINEL / PRIVACY',title:'Data protection impact assessment',summary:'An assisted starting point for processing scope, data flows, risks, safeguards, and reviewer decisions.',sections:['Processing overview','Risk and impact','Mitigations'],source:'Uses assessment context and existing records',badge:'REVIEWABLE DRAFT',note:'Illustrative document outline. Generated material requires verification and approval.'},
  aiia: {module:'SENTINEL / AI IMPACT',title:'AI impact assessment',summary:'A proposed assisted outline for system purpose, affected people, potential harm, controls, and review.',sections:['Use case and purpose','Impact on people','Safeguards'],source:'Structured AIIA workflow exists in the platform',badge:'DESIGN CONCEPT',note:'Design concept: AI drafting for AIIAs is not a current platform capability. Structured AIIA assessment is available.'},
  bcp: {module:'BCM / RESILIENCE',title:'Business continuity plan',summary:'A reviewable starting point for recovery priorities, critical dependencies, contacts, and response actions.',sections:['Critical services','Recovery steps','Exercise plan'],source:'Uses continuity and impact context',badge:'REVIEWABLE DRAFT',note:'Illustrative document outline. A plan owner must verify assumptions and approve the result.'},
  policy: {module:'ARIA / GOVERNANCE',title:'Tailored AI policy',summary:'A draft shaped by the organisation context, framework requirements, controls, and intended use.',sections:['Purpose and scope','Required controls','Ownership'],source:'Policy generator supports tailored drafts',badge:'REVIEWABLE DRAFT',note:'Illustrative document outline. Generated policy text requires verification and approval.'},
  procedure: {module:'ARIA / GOVERNANCE',title:'Operating procedure',summary:'A practical draft of roles, triggers, steps, escalation, and evidence to keep.',sections:['Trigger','Action steps','Records'],source:'ARIA generator supports procedures',badge:'REVIEWABLE DRAFT',note:'Illustrative document outline. Generated procedure text requires verification and approval.'},
  record: {module:'ARIA / GOVERNANCE',title:'Governance record',summary:'A structured draft for decisions, evidence, owner, date, and follow-up actions.',sections:['Decision context','Evidence','Approval trail'],source:'ARIA generator supports records',badge:'REVIEWABLE DRAFT',note:'Illustrative document outline. Generated record text requires verification and approval.'}
};
const draftButtons = Array.from(document.querySelectorAll('[data-draft]'));
function selectDraft(key) {
  const item = draftTypes[key];
  if (!item) return;
  draftButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.draft === key)));
  document.getElementById('draft-counter').textContent = String(Object.keys(draftTypes).indexOf(key) + 1).padStart(2, '0') + ' / 06';
  document.getElementById('draft-module').textContent = item.module;
  document.getElementById('draft-title').textContent = item.title;
  document.getElementById('draft-summary').textContent = item.summary;
  document.getElementById('draft-source').textContent = item.source;
  document.getElementById('draft-disclosure').textContent = item.note;
  const badge = document.getElementById('draft-badge');
  badge.textContent = item.badge;
  badge.classList.toggle('is-concept', key === 'aiia');
  const sections = document.getElementById('draft-sections');
  sections.replaceChildren(...item.sections.map(label => {
    const chip = document.createElement('span');
    chip.textContent = label;
    return chip;
  }));
  const sheet = document.querySelector('.draft-document');
  sheet.style.animation = 'none';
  void sheet.offsetWidth;
  sheet.style.animation = '';
}
draftButtons.forEach(button => button.addEventListener('click', () => selectDraft(button.dataset.draft)));

const askExamples = {
  retention: {question:'What is our retention approach?',answer:'Begin with the approved retention schedule, confirm the record category and owner, then check any hold before disposal. The exact period comes from your organisation’s policy.',source:'Approved policy · Retention schedule',note:'Sample citation card; no organisation document is displayed here.'},
  incident: {question:'How do we escalate an incident?',answer:'Use the organisation’s incident procedure to identify the owner, assess severity, and record the escalation path. The assistant should cite the applicable approved source.',source:'Approved procedure · Incident response',note:'Sample citation card; no organisation document is displayed here.'},
  unknown: {question:'What is our quantum policy?',answer:'Not covered by the available authorised records in this example. Ask a policy owner to confirm whether a current document exists.',source:'No supporting source found',note:'A grounded assistant should say when the record does not support an answer.'}
};
document.querySelectorAll('[data-ask]').forEach(button => button.addEventListener('click', () => {
  const example = askExamples[button.dataset.ask];
  if (!example) return;
  document.querySelectorAll('[data-ask]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  document.getElementById('ask-question').textContent = example.question;
  document.getElementById('ask-answer').textContent = example.answer;
  const card = document.getElementById('ask-source');
  card.querySelector('strong').textContent = example.source;
  card.querySelector('small').textContent = example.note;
}));

const contextExamples = {
  technology: {sector:'TECHNOLOGY',title:'Technology change',description:'Review new dependencies, supplier exposure, and control coverage against the organisation’s risk register.'},
  operations: {sector:'OPERATIONS',title:'Operational pressure',description:'Compare emerging disruption themes with continuity plans, recent events, and critical service dependencies.'},
  privacy: {sector:'PRIVACY',title:'Privacy change',description:'Surface changing privacy expectations for review against jurisdictions, data flows, and breach procedures.'}
};
document.querySelectorAll('[data-context]').forEach(button => button.addEventListener('click', () => {
  const example = contextExamples[button.dataset.context];
  if (!example) return;
  document.querySelectorAll('[data-context]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  document.getElementById('context-sector').textContent = example.sector;
  document.getElementById('context-title').textContent = example.title;
  document.getElementById('context-description').textContent = example.description;
  const result = document.querySelector('.context-result');
  if (!motionReduced.matches && result.animate) result.animate([{opacity:.5,transform:'translateY(8px)'},{opacity:1,transform:'translateY(0)'}],{duration:340,easing:'ease-out'});
}));

const riskExamples = {
  baseline: {change:'+8.4%',level:'WATCH',cyber:12,operational:18,compliance:10,driver:'Review linked signals',explanation:'An example of how continuity, control, incident, and appetite signals form one reviewable picture.',confidence:'Moderate · sample completeness',signals:['bcm','aria']},
  exercise: {change:'+28.6%',level:'ELEVATED',cyber:9,operational:54,compliance:14,driver:'Overdue continuity exercise',explanation:'An overdue exercise raises the operational contribution. The view points teams back to the BCM work that needs attention.',confidence:'Moderate · sample completeness',signals:['bcm']},
  controls: {change:'+21.3%',level:'ELEVATED',cyber:16,operational:22,compliance:47,driver:'Control assessment gap',explanation:'Unassessed controls raise the compliance contribution. Governance teams can review the underlying assessment backlog.',confidence:'Moderate · sample completeness',signals:['aria']}
};
document.querySelectorAll('[data-risk]').forEach(button => button.addEventListener('click', () => {
  const example = riskExamples[button.dataset.risk];
  if (!example) return;
  document.querySelectorAll('[data-risk]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  document.getElementById('risk-change').textContent = example.change;
  document.getElementById('risk-level').textContent = example.level;
  ['cyber','operational','compliance'].forEach(domain => {
    document.getElementById('risk-' + domain).textContent = example[domain] + '%';
    document.querySelector('[data-risk-bar="' + domain + '"]').style.width = example[domain] + '%';
  });
  document.getElementById('risk-driver').textContent = example.driver;
  document.getElementById('risk-explanation').textContent = example.explanation;
  document.getElementById('risk-confidence').textContent = example.confidence;
  document.querySelectorAll('[data-risk-signal]').forEach(signal => signal.classList.toggle('is-contributing', example.signals.includes(signal.dataset.riskSignal)));
}));
Object.keys(riskExamples.baseline).filter(key => ['cyber','operational','compliance'].includes(key)).forEach(domain => {
  document.querySelector('[data-risk-bar="' + domain + '"]').style.width = riskExamples.baseline[domain] + '%';
});

document.querySelectorAll('[data-risk-signal]').forEach(signal => signal.classList.toggle('is-contributing', riskExamples.baseline.signals.includes(signal.dataset.riskSignal)));
