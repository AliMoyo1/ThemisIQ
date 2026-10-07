const modules = {
  aria: {
    index: '01', name: 'Governance', code: 'ARIA', path: '/aria',
    title: 'Give every control its context.',
    description: 'Bring frameworks, policies, documents, and control work into one clear governance view.',
    image: '../../landing_page/screenshot-aria.webp', alt: 'ARIA governance dashboard',
    tags: ['Frameworks', 'Policies & documents', 'Control mapping'],
    light: '#7d6527', dusk: '#e5cb82'
  },
  grid: {
    index: '02', name: 'Audit', code: 'GRID', path: '/grid',
    title: 'See the audit work in motion.',
    description: 'Keep audits, findings, and supporting evidence together from planning through closure.',
    image: '../../landing_page/screenshot-grid.webp', alt: 'GRID audit dashboard',
    tags: ['Audit planning', 'Findings', 'Evidence collection'],
    light: '#047857', dusk: '#6ee7b7'
  },
  bcm: {
    index: '03', name: 'Resilience', code: 'BCM', path: '/bcm',
    title: 'Be ready to respond.',
    description: 'Connect continuity planning with incidents, exercises, dependencies, and recovery work.',
    image: '../../landing_page/screenshot-bcm.webp', alt: 'BCM resilience dashboard',
    tags: ['Continuity plans', 'Exercises', 'Dependencies'],
    light: '#3d4660', dusk: '#aab6d1'
  },
  sentinel: {
    index: '04', name: 'Privacy', code: 'SENTINEL', path: '/sentinel',
    title: 'Keep privacy work visible.',
    description: 'Bring processing records, assessments, requests, and incidents into a single view.',
    image: '../../landing_page/screenshot-sentinel.webp', alt: 'Sentinel privacy dashboard',
    tags: ['RoPA records', 'DPIAs', 'Subject requests'],
    light: '#3b5bdb', dusk: '#a1b6ff'
  },
  erm: {
    index: '05', name: 'Enterprise risk', code: 'ERM', path: '/erm',
    title: 'Understand the wider exposure.',
    description: 'Explore risk posture, appetite, obligations, and the signals that need attention.',
    image: '../../landing_page/screenshot-erm.webp', alt: 'ERM enterprise risk dashboard',
    tags: ['Risk register', 'Risk appetite', 'Obligations'],
    light: '#881337', dusk: '#f19ab4'
  },
  orm: {
    index: '06', name: 'Operations risk', code: 'ORM', path: '/orm',
    title: 'Spot what happens on the ground.',
    description: 'Keep events, key risk indicators, and control assessments close to the teams that own them.',
    image: '../../landing_page/screenshot-orm.webp', alt: 'ORM operations risk dashboard',
    tags: ['Events', 'KRIs', 'Control assessments'],
    light: '#7c3a0a', dusk: '#efb17c'
  }
};

const flowSteps = [
  {
    module: 'OPERATIONS RISK / ORM', core: 'EVENT',
    title: 'Start with a clear record.',
    description: 'Capture the event, its owner, and its impact while the details are fresh.',
    color: '#84b69b'
  },
  {
    module: 'RESILIENCE / BCM', core: 'CONTEXT',
    title: 'Bring response into view.',
    description: 'See the plans, dependencies, and people relevant to the response.',
    color: '#aab6d1'
  },
  {
    module: 'SHARED EVIDENCE', core: 'PROOF',
    title: 'Keep the proof close.',
    description: 'Link supporting records to the work they explain and the decisions they inform.',
    color: '#c5d5c4'
  },
  {
    module: 'COMMAND CENTRE', core: 'VIEW',
    title: 'See the wider picture.',
    description: 'Bring connected signals into a view that helps the right people decide what comes next.',
    color: '#9bc5fc'
  }
];

const root = document.documentElement;
const moduleButtons = Array.from(document.querySelectorAll('[data-select-module]'));
const moduleTabs = Array.from(document.querySelectorAll('[role="tab"][data-select-module]'));
const heroButtons = Array.from(document.querySelectorAll('.signal-token'));
const heroImage = document.getElementById('hero-image');
const heroPreview = document.getElementById('hero-preview');
const moduleImage = document.getElementById('module-image');
const moduleFrame = document.querySelector('.module-image-frame');
const themeToggle = document.getElementById('theme-toggle');
let selectedModule = 'aria';

function rgba(hex, alpha) {
  const value = hex.replace('#', '');
  return `rgba(${parseInt(value.slice(0, 2), 16)}, ${parseInt(value.slice(2, 4), 16)}, ${parseInt(value.slice(4, 6), 16)}, ${alpha})`;
}

function applyModuleAccent() {
  const module = modules[selectedModule];
  const accent = root.dataset.theme === 'dusk' ? module.dusk : module.light;
  root.style.setProperty('--active-accent', accent);
  root.style.setProperty('--active-soft', rgba(accent, 0.13));
}

function animateFrame(frame) {
  frame.classList.remove('is-switching');
  void frame.offsetWidth;
  frame.classList.add('is-switching');
}

function selectModule(key) {
  const module = modules[key];
  if (!module) return;
  selectedModule = key;
  applyModuleAccent();

  heroImage.src = module.image;
  heroImage.alt = module.alt;
  document.getElementById('hero-url').textContent = `app.themisiq.net${module.path}`;
  document.getElementById('hero-caption').textContent = `${module.name} / ${module.code}`;
  document.getElementById('hero-index').textContent = `${module.index} / 06`;
  animateFrame(heroPreview);

  document.getElementById('module-eyebrow').textContent = `${module.name.toUpperCase()} / ${module.code}`;
  document.getElementById('module-counter').textContent = `${module.index} / 06`;
  document.getElementById('module-title').textContent = module.title;
  document.getElementById('module-description').textContent = module.description;
  document.getElementById('module-url').textContent = `app.themisiq.net${module.path}`;
  moduleImage.src = module.image;
  moduleImage.alt = module.alt;
  document.getElementById('module-panel').setAttribute('aria-labelledby', `module-tab-${key}`);
  const tags = document.getElementById('module-capabilities');
  tags.replaceChildren(...module.tags.map(label => {
    const chip = document.createElement('span');
    chip.textContent = label;
    return chip;
  }));
  animateFrame(moduleFrame);

  moduleTabs.forEach(button => {
    const active = button.dataset.selectModule === key;
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
  });
  heroButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.selectModule === key)));
}

moduleButtons.forEach(button => button.addEventListener('click', () => selectModule(button.dataset.selectModule)));
moduleTabs.forEach((button, index) => button.addEventListener('keydown', event => {
  let next = index;
  if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = (index + 1) % moduleTabs.length;
  else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = (index - 1 + moduleTabs.length) % moduleTabs.length;
  else if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = moduleTabs.length - 1;
  else return;
  event.preventDefault();
  const target = moduleTabs[next];
  selectModule(target.dataset.selectModule);
  target.focus();
}));

document.getElementById('reset-view').addEventListener('click', () => {
  heroImage.src = '../../landing_page/screenshot-command-centre.webp';
  heroImage.alt = 'ThemisIQ Command Centre dashboard';
  document.getElementById('hero-url').textContent = 'app.themisiq.net/command-centre';
  document.getElementById('hero-caption').textContent = 'Command Centre';
  document.getElementById('hero-index').textContent = '00 / 06';
  heroButtons.forEach(button => button.setAttribute('aria-pressed', 'false'));
  animateFrame(heroPreview);
});

function applyTheme(theme) {
  const dusk = theme === 'dusk';
  root.dataset.theme = dusk ? 'dusk' : 'sage';
  themeToggle.setAttribute('aria-pressed', String(dusk));
  themeToggle.setAttribute('aria-label', dusk ? 'Switch to sage theme' : 'Switch to dusk theme');
  document.getElementById('theme-label').textContent = dusk ? 'Sage' : 'Dusk';
  document.querySelector('.theme-icon').textContent = dusk ? '\u2600' : '\u263e';
  applyModuleAccent();
  try { localStorage.setItem('themisIQ-connected-signals-theme', root.dataset.theme); } catch (_) {}
}
try {
  const storedTheme = localStorage.getItem('themisIQ-connected-signals-theme');
  if (storedTheme === 'dusk') applyTheme('dusk');
} catch (_) {}
themeToggle.addEventListener('click', () => applyTheme(root.dataset.theme === 'sage' ? 'dusk' : 'sage'));
applyModuleAccent();
moduleTabs.forEach(button => button.tabIndex = button.dataset.selectModule === selectedModule ? 0 : -1);

const flowButtons = Array.from(document.querySelectorAll('[data-flow-step]'));
flowButtons.forEach(button => button.addEventListener('click', () => {
  const index = Number(button.dataset.flowStep);
  const step = flowSteps[index];
  if (!step) return;
  flowButtons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  document.getElementById('flow-module').textContent = step.module;
  document.getElementById('flow-number').textContent = String(index + 1).padStart(2, '0') + ' / 04';
  document.getElementById('flow-step-title').textContent = step.title;
  document.getElementById('flow-step-description').textContent = step.description;
}));

const menuToggle = document.getElementById('menu-toggle');
const navLinks = document.getElementById('nav-links');
function closeMenu() {
  navLinks.dataset.open = 'false';
  menuToggle.setAttribute('aria-expanded', 'false');
  menuToggle.setAttribute('aria-label', 'Open navigation');
}
menuToggle.addEventListener('click', () => {
  const open = navLinks.dataset.open !== 'true';
  navLinks.dataset.open = String(open);
  menuToggle.setAttribute('aria-expanded', String(open));
  menuToggle.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
});
navLinks.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMenu));
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeMenu(); });

const visual = document.getElementById('hero-visual');
if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  visual.addEventListener('pointermove', event => {
    const box = visual.getBoundingClientRect();
    visual.style.setProperty('--glow-x', `${Math.round((event.clientX - box.left) / box.width * 100)}%`);
    visual.style.setProperty('--glow-y', `${Math.round((event.clientY - box.top) / box.height * 100)}%`);
  });
}
