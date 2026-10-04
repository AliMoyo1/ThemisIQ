/* Per-user Command Centre layout; all content remains sourced from the existing live widgets. */
(() => {
  'use strict';
  const canvas = document.getElementById('ccDashboardCanvas');
  if (!canvas) return;
  const definitions = [
    ['modules', '#ccModulesSection', 'Your modules', 4],
    ['compliance', '#ccComplianceCard', 'Overall compliance', 2],
    ['projects', '#ccProjectsCard', 'Active projects', 1],
    ['overdue', '#ccOverdueCard', 'Overdue actions', 1],
    ['pending_actions', '#ccPendingActionsCard', 'My pending actions', 1],
    ['unread_alerts', '#ccUnreadAlertsCard', 'Unread alerts', 1],
    ['erm_critical', '#ccErmCritCard', 'Critical / high risks', 1, 'erm'],
    ['sentinel_breaches', '#ccSentinelCard', 'Open breaches', 1, 'sentinel'],
    ['briefing', '#briefingStrip', "Today's briefing", 4],
    ['predictive', '#prPanel', 'Predictive risk', 4],
    ['erm_appetite', '#ccErmCard', 'Appetite breaches', 1, 'erm'],
    ['orm_events', '#ccOrmCard', 'Open events', 1, 'orm'],
    ['bcm_incidents', '#ccBcmCard', 'Active incidents', 1, 'bcm'],
    ['grid_findings', '#ccGridFindCard', 'Audit findings', 1, 'grid'],
    ['reviews', '#ccReviewsCard', 'Upcoming reviews', 1],
    ['frameworks', '#ccFrameworksCard', 'Active frameworks', 1],
    ['evidence', '#ccEvidenceCard', 'Evidence collected', 1],
    ['module_health', '#ccModuleHealthCard', 'Module health', 2],
    ['sla', '#ccSlaPanel', 'SLA performance', 2],
    ['activity', '#ccActivityCard', 'Recent activity', 2],
    ['risks', '#ccRisksCard', 'Open risks', 2],
    ['workflows', '#ccWorkflowsCard', 'Active workflows', 2],
    ['overdue_table', '#ccOverduePanel', 'Overdue action items', 4]
  ];
  const modules = new Set((canvas.dataset.modules || '').split(',').filter(Boolean));
  const catalog = new Map();
  const initial = [];
  for (const [key, selector, label, span, module] of definitions) {
    const source = document.querySelector(selector);
    if (!source) continue;
    if (module && !modules.has(module)) {
      source.remove();
      continue;
    }
    const shell = document.createElement('section');
    shell.className = 'cc-widget';
    shell.dataset.key = key;
    shell.dataset.span = String(span);
    shell.setAttribute('aria-label', label);
    if (source.hasAttribute('onclick')) {
      source.tabIndex = 0;
      source.setAttribute('role', key === 'overdue' || key === 'unread_alerts' ? 'button' : 'link');
      source.addEventListener('keydown', event => {
        if (editMode || event.target !== source || !['Enter', ' '].includes(event.key)) return;
        event.preventDefault();
        source.click();
      });
    }
    const body = document.createElement('div');
    body.className = 'cc-widget-body';
    body.append(source);
    shell.append(body);
    const tools = document.createElement('div');
    tools.className = 'cc-widget-tools';
    tools.setAttribute('aria-label', `${label} layout controls`);
    const buttons = [
      ['cc-drag-handle', 'Drag to move', '⠿'],
      ['cc-move-back', 'Move earlier', '←'],
      ['cc-move-next', 'Move later', '→'],
      ['cc-remove', 'Remove card', '×']
    ];
    for (const [className, action, icon] of buttons) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = className;
      button.title = `${action}: ${label}`;
      button.setAttribute('aria-label', `${action}: ${label}`);
      button.textContent = icon;
      button.addEventListener('click', event => event.stopPropagation());
      tools.append(button);
    }
    shell.append(tools);
    canvas.append(shell);
    catalog.set(key, {shell, source, label});
    initial.push(key);
  }
  // Empty legacy grouping nodes must not leave blank grid rows behind.
  document.querySelectorAll('.dash-section-heading, .cc-primary-metrics, .cc-exposure-metrics, .cc-workflow-metrics, .three-col, .two-col, #ccPersonalSource')
    .forEach(node => node.remove());
  const defaultHidden = [
    'erm_appetite', 'orm_events', 'reviews', 'frameworks', 'evidence', 'risks', 'workflows'
  ];
  let hidden = new Set(defaultHidden.filter(key => catalog.has(key)));
  let editMode = false;
  let saving = Promise.resolve();
  let modified = false;
  const status = document.getElementById('ccLayoutStatus');
  const palette = document.getElementById('ccWidgetPalette');
  const customize = document.getElementById('ccCustomizer');
  const toggle = document.getElementById('ccCustomizeBtn');
  const motionOK = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const widgets = () => Array.from(canvas.children).filter(node => node.classList.contains('cc-widget'));
  const snapshot = () => ({order: widgets().map(node => node.dataset.key), hidden: [...hidden]});
  const animateMove = action => {
    const before = new Map(widgets().map(node => [node, node.getBoundingClientRect()]));
    action();
    if (!motionOK) return;
    widgets().forEach(node => {
      const prior = before.get(node);
      if (!prior) return;
      const next = node.getBoundingClientRect();
      const dx = prior.left - next.left, dy = prior.top - next.top;
      if (dx || dy) node.animate([
        {transform: `translate(${dx}px, ${dy}px)`}, {transform: 'translate(0, 0)'}
      ], {duration: 380, easing: 'cubic-bezier(.18,.82,.18,1)'});
    });
  };
  const renderPalette = () => {
    palette.replaceChildren();
    const missing = initial.filter(key => hidden.has(key));
    if (!missing.length) {
      const text = document.createElement('span');
      text.className = 'cc-all-added';
      text.textContent = 'All available cards are on your dashboard.';
      palette.append(text);
    }
    missing.forEach(key => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = `+ ${catalog.get(key).label}`;
      button.addEventListener('click', () => {
        hidden.delete(key);
        catalog.get(key).shell.hidden = false;
        renderPalette();
        persist();
        catalog.get(key).shell.scrollIntoView({behavior: motionOK ? 'smooth' : 'instant', block: 'nearest'});
      });
      palette.append(button);
    });
  };
  const syncVisibility = () => {
    catalog.forEach(({shell, source}, key) => {
      const unavailable = (key === 'briefing' || key === 'predictive') && source.style.display === 'none';
      shell.hidden = hidden.has(key) || unavailable;
    });
    renderPalette();
  };
  const persist = (reset = false) => {
    modified = true;
    const layout = reset ? null : snapshot();
    status.textContent = 'Saving your layout...';
    saving = saving.catch(() => {}).then(() => ApiClient.request('/api/command-centre/layout', {
      method: 'PUT', body: {layout}, actionId: 'command_centre.layout.save'
    })).then(() => { status.textContent = 'Layout saved for you'; }).catch(error => {
      status.textContent = 'Layout could not be saved';
      if (typeof showToast === 'function') showToast(error.detail || 'Dashboard layout could not be saved', 'error');
    });
  };
  const move = (item, target, after = false) => {
    if (!item || !target || item === target) return;
    animateMove(() => canvas.insertBefore(item, after ? target.nextSibling : target));
    persist();
    item.querySelector('.cc-drag-handle').focus();
  };
  catalog.forEach(({shell}, key) => {
    const handle = shell.querySelector('.cc-drag-handle');
    let pointerDrag = null;
    const clearDrag = () => {
      if (!pointerDrag) return;
      pointerDrag.ghost?.remove();
      shell.classList.remove('cc-dragging');
      widgets().forEach(node => node.classList.remove('cc-drop-before', 'cc-drop-after'));
      pointerDrag = null;
    };
    handle.addEventListener('pointerdown', event => {
      if (!editMode || !event.isPrimary) return;
      event.preventDefault();
      handle.setPointerCapture(event.pointerId);
      pointerDrag = {x: event.clientX, y: event.clientY, target: null, after: false, ghost: null};
    });
    handle.addEventListener('pointermove', event => {
      if (!pointerDrag) return;
      if (!pointerDrag.ghost && Math.hypot(event.clientX - pointerDrag.x, event.clientY - pointerDrag.y) < 5) return;
      if (!pointerDrag.ghost) {
        const ghost = document.createElement('div');
        ghost.className = 'cc-drag-ghost';
        ghost.textContent = catalog.get(key).label;
        document.body.append(ghost);
        pointerDrag.ghost = ghost;
        shell.classList.add('cc-dragging');
      }
      pointerDrag.ghost.style.left = `${event.clientX + 14}px`;
      pointerDrag.ghost.style.top = `${event.clientY + 14}px`;
      const target = document.elementFromPoint(event.clientX, event.clientY)?.closest('.cc-widget');
      widgets().forEach(node => node.classList.remove('cc-drop-before', 'cc-drop-after'));
      pointerDrag.target = target && target !== shell && !target.hidden ? target : null;
      if (pointerDrag.target) {
        const bounds = pointerDrag.target.getBoundingClientRect();
        pointerDrag.after = event.clientX > bounds.left + bounds.width / 2;
        pointerDrag.target.classList.add(pointerDrag.after ? 'cc-drop-after' : 'cc-drop-before');
      }
    });
    handle.addEventListener('pointerup', () => {
      if (!pointerDrag) return;
      const {target, after} = pointerDrag;
      clearDrag();
      if (target) move(shell, target, after);
    });
    handle.addEventListener('pointercancel', clearDrag);
    handle.addEventListener('keydown', event => {
      if (!editMode || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
      event.preventDefault();
      const list = widgets().filter(node => !node.hidden);
      const index = list.indexOf(shell);
      const earlier = event.key === 'ArrowLeft' || event.key === 'ArrowUp';
      move(shell, list[index + (earlier ? -1 : 1)], !earlier);
    });
    shell.querySelector('.cc-move-back').addEventListener('click', () => {
      const list = widgets().filter(node => !node.hidden);
      move(shell, list[list.indexOf(shell) - 1]);
    });
    shell.querySelector('.cc-move-next').addEventListener('click', () => {
      const list = widgets().filter(node => !node.hidden);
      move(shell, list[list.indexOf(shell) + 1], true);
    });
    shell.querySelector('.cc-remove').addEventListener('click', () => {
      hidden.add(key);
      syncVisibility();
      persist();
    });
  });
  toggle.addEventListener('click', () => {
    editMode = !editMode;
    canvas.classList.toggle('cc-editing', editMode);
    customize.hidden = !editMode;
    toggle.setAttribute('aria-expanded', String(editMode));
    toggle.textContent = editMode ? 'Done arranging' : 'Customise dashboard';
    if (editMode) renderPalette();
  });
  document.getElementById('ccResetLayout').addEventListener('click', () => {
    hidden = new Set(defaultHidden.filter(key => catalog.has(key)));
    animateMove(() => initial.forEach(key => canvas.append(catalog.get(key).shell)));
    syncVisibility();
    persist(true);
    if (typeof showToast === 'function') showToast('Default dashboard restored', 'success');
  });
  ['briefing', 'predictive'].forEach(key => {
    const item = catalog.get(key);
    if (item) new MutationObserver(syncVisibility).observe(item.source, {attributes: true, attributeFilter: ['style']});
  });
  syncVisibility();
  fetch('/api/command-centre/layout', {credentials: 'same-origin'})
    .then(response => { if (!response.ok) throw new Error('Unable to load dashboard layout'); return response.json(); })
    .then(({layout}) => {
      if (modified || !layout || !Array.isArray(layout.order) || !Array.isArray(layout.hidden)) return;
      layout.order.forEach(key => { if (catalog.has(key)) canvas.append(catalog.get(key).shell); });
      hidden = new Set(layout.hidden.filter(key => catalog.has(key)));
      syncVisibility();
    })
    .catch(() => { if (typeof showToast === 'function') showToast('Using the default dashboard layout', 'error'); });
  const refreshPersonal = () => fetch('/api/command-centre/personal', {credentials: 'same-origin'})
    .then(response => { if (!response.ok) throw new Error('Personal counters unavailable'); return response.json(); })
    .then(data => {
      document.getElementById('ccPendingActions').textContent = data.pending_actions;
      document.getElementById('ccUnreadAlerts').textContent = data.unread_alerts;
    })
    .catch(() => {
      document.getElementById('ccPendingActions').textContent = '—';
      document.getElementById('ccUnreadAlerts').textContent = '—';
    });
  refreshPersonal();
  setInterval(refreshPersonal, 300000);
})();
