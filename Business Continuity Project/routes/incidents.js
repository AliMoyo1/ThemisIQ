const express = require('express');
const router = express.Router();
const db = require('../models/db');
const { requireAuth } = require('../middleware/auth');
const { sendIncidentDeclaredEmail } = require('../services/mailer');
const { ACTIONS } = require('../services/audit');
const { chat } = require('../services/ai');

router.use(requireAuth);

// ---------- List / show / CRUD ----------

router.get('/', (req, res) => {
  const rows = db.prepare(`SELECT * FROM incidents WHERE tenant_id = ? ORDER BY started_at DESC`).all(req.session.tenant.id);
  res.render('incidents/index', { title: 'Incidents', rows });
});

router.get('/new', (req, res) => {
  res.render('incidents/form', { title: 'Declare incident', incident: null });
});

router.get('/:id', (req, res) => {
  const incident = db.prepare(`SELECT * FROM incidents WHERE id = ? AND tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!incident) { req.flash('error', 'Incident not found.'); return res.redirect('/incidents'); }
  const updates = db.prepare(`SELECT * FROM incident_updates WHERE incident_id = ? ORDER BY created_at DESC`).all(incident.id);
  res.render('incidents/show', { title: incident.title, incident, updates });
});

router.get('/:id/edit', (req, res) => {
  const incident = db.prepare(`SELECT * FROM incidents WHERE id = ? AND tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!incident) { req.flash('error', 'Incident not found.'); return res.redirect('/incidents'); }
  res.render('incidents/form', { title: 'Edit incident', incident });
});

// ---------- Incident command console ----------

router.get('/:id/command', (req, res) => {
  const tenantId = req.session.tenant.id;
  const incident = db.prepare(`SELECT * FROM incidents WHERE id = ? AND tenant_id = ?`).get(req.params.id, tenantId);
  if (!incident) { req.flash('error', 'Incident not found.'); return res.redirect('/incidents'); }

  const updates = db.prepare(`SELECT * FROM incident_updates WHERE incident_id = ? ORDER BY created_at DESC`).all(incident.id);
  const actions = db.prepare(`SELECT * FROM incident_actions WHERE incident_id = ? ORDER BY
      CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END,
      CASE status WHEN 'open' THEN 1 WHEN 'in_progress' THEN 2 WHEN 'blocked' THEN 3 ELSE 4 END,
      created_at DESC`).all(incident.id);
  const decisions = db.prepare(`SELECT * FROM incident_decisions WHERE incident_id = ? ORDER BY decided_at DESC`).all(incident.id);
  const stakeholders = db.prepare(`SELECT * FROM incident_stakeholders WHERE incident_id = ? ORDER BY
      CASE WHEN ack_at IS NOT NULL THEN 2 WHEN notified_at IS NOT NULL THEN 1 ELSE 0 END,
      id ASC`).all(incident.id);

  const linkedPlans = db.prepare(`
    SELECT p.id, p.title, p.version, p.status, p.owner, p.scope, p.content
    FROM incident_plan_links l
    JOIN bcp_plans p ON p.id = l.plan_id AND p.tenant_id = l.tenant_id
    WHERE l.incident_id = ? AND l.tenant_id = ?
    ORDER BY p.updated_at DESC
  `).all(incident.id, tenantId);

  const availablePlans = db.prepare(`
    SELECT id, title, version FROM bcp_plans
    WHERE tenant_id = ? AND id NOT IN (
      SELECT plan_id FROM incident_plan_links WHERE incident_id = ? AND tenant_id = ?
    )
    ORDER BY updated_at DESC
  `).all(tenantId, incident.id, tenantId);

  res.render('incidents/command', {
    title: 'Command: ' + incident.title,
    incident,
    updates,
    actions,
    decisions,
    stakeholders,
    linkedPlans,
    availablePlans
  });
});

// Post update (from command console or classic view)
router.post('/:id/updates', (req, res) => {
  const { note, redirect } = req.body;
  if (!note || !note.trim()) { req.flash('error', 'Update note required.'); return res.redirect(redirect || ('/incidents/' + req.params.id)); }
  const incident = db.prepare(`SELECT id FROM incidents WHERE id = ? AND tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!incident) { req.flash('error', 'Incident not found.'); return res.redirect('/incidents'); }
  db.prepare(`INSERT INTO incident_updates (tenant_id, incident_id, author, note) VALUES (?, ?, ?, ?)`)
    .run(req.session.tenant.id, incident.id, req.session.user.name, note.trim());
  req.audit({ action: ACTIONS.CREATE, entity: 'incident_updates', entityId: incident.id, summary: 'Timeline update added' });
  req.flash('success', 'Update logged.');
  res.redirect(redirect || ('/incidents/' + req.params.id));
});

// ---------- Action items ----------

router.post('/:id/actions', (req, res) => {
  const b = req.body;
  const incident = db.prepare(`SELECT id FROM incidents WHERE id = ? AND tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!incident) { req.flash('error', 'Incident not found.'); return res.redirect('/incidents'); }
  if (!b.title || !b.title.trim()) { req.flash('error', 'Action title required.'); return res.redirect('/incidents/' + req.params.id + '/command'); }
  db.prepare(`INSERT INTO incident_actions (tenant_id, incident_id, title, owner, priority, due_at, notes, created_by)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)`).run(
    req.session.tenant.id, incident.id, b.title.trim(), b.owner || null,
    b.priority || 'normal', b.due_at || null, b.notes || null, req.session.user.name
  );
  req.audit({ action: ACTIONS.CREATE, entity: 'incident_actions', entityId: incident.id, summary: `Action "${b.title}" added` });
  req.flash('success', 'Action added.');
  res.redirect('/incidents/' + req.params.id + '/command');
});

router.post('/:id/actions/:actionId', (req, res) => {
  const { status } = req.body;
  const incident = db.prepare(`SELECT id FROM incidents WHERE id = ? AND tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!incident) return res.redirect('/incidents');
  const completedAt = (status === 'done') ? 'CURRENT_TIMESTAMP' : 'NULL';
  db.prepare(`UPDATE incident_actions SET status = ?, completed_at = CASE WHEN ? = 'done' THEN CURRENT_TIMESTAMP ELSE NULL END,
    updated_at = CURRENT_TIMESTAMP WHERE id = ? AND incident_id = ? AND tenant_id = ?`)
    .run(status || 'open', status || '', req.params.actionId, incident.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.UPDATE, entity: 'incident_actions', entityId: +req.params.actionId, summary: `Action set to ${status}` });
  res.redirect('/incidents/' + req.params.id + '/command');
});

router.post('/:id/actions/:actionId/delete', (req, res) => {
  db.prepare(`DELETE FROM incident_actions WHERE id = ? AND incident_id = ? AND tenant_id = ?`)
    .run(req.params.actionId, req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'incident_actions', entityId: +req.params.actionId, summary: 'Action removed' });
  res.redirect('/incidents/' + req.params.id + '/command');
});

// ---------- Decisions ----------

router.post('/:id/decisions', (req, res) => {
  const b = req.body;
  const incident = db.prepare(`SELECT id FROM incidents WHERE id = ? AND tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!incident) { req.flash('error', 'Incident not found.'); return res.redirect('/incidents'); }
  if (!b.decision || !b.decision.trim()) { req.flash('error', 'Decision is required.'); return res.redirect('/incidents/' + req.params.id + '/command'); }
  db.prepare(`INSERT INTO incident_decisions (tenant_id, incident_id, decision, rationale, decided_by)
    VALUES (?, ?, ?, ?, ?)`).run(
    req.session.tenant.id, incident.id, b.decision.trim(), b.rationale || null, req.session.user.name
  );
  req.audit({ action: ACTIONS.CREATE, entity: 'incident_decisions', entityId: incident.id, summary: 'Decision logged' });
  req.flash('success', 'Decision logged.');
  res.redirect('/incidents/' + req.params.id + '/command');
});

router.post('/:id/decisions/:decisionId/delete', (req, res) => {
  db.prepare(`DELETE FROM incident_decisions WHERE id = ? AND incident_id = ? AND tenant_id = ?`)
    .run(req.params.decisionId, req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'incident_decisions', entityId: +req.params.decisionId, summary: 'Decision removed' });
  res.redirect('/incidents/' + req.params.id + '/command');
});

// ---------- Stakeholders ----------

router.post('/:id/stakeholders', (req, res) => {
  const b = req.body;
  const incident = db.prepare(`SELECT id FROM incidents WHERE id = ? AND tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!incident) return res.redirect('/incidents');
  if (!b.role || !b.role.trim()) { req.flash('error', 'Stakeholder role required.'); return res.redirect('/incidents/' + req.params.id + '/command'); }
  db.prepare(`INSERT INTO incident_stakeholders (tenant_id, incident_id, role, person, channel, notes)
    VALUES (?, ?, ?, ?, ?, ?)`).run(
    req.session.tenant.id, incident.id, b.role.trim(), b.person || null,
    b.channel || null, b.notes || null
  );
  req.audit({ action: ACTIONS.CREATE, entity: 'incident_stakeholders', entityId: incident.id, summary: `Stakeholder "${b.role}" added` });
  res.redirect('/incidents/' + req.params.id + '/command');
});

router.post('/:id/stakeholders/:stakeId', (req, res) => {
  const { mark } = req.body;
  let sql, args;
  if (mark === 'notified') {
    sql = `UPDATE incident_stakeholders SET notified_at = CURRENT_TIMESTAMP WHERE id = ? AND incident_id = ? AND tenant_id = ?`;
    args = [req.params.stakeId, req.params.id, req.session.tenant.id];
  } else if (mark === 'ack') {
    sql = `UPDATE incident_stakeholders SET ack_at = CURRENT_TIMESTAMP WHERE id = ? AND incident_id = ? AND tenant_id = ?`;
    args = [req.params.stakeId, req.params.id, req.session.tenant.id];
  } else if (mark === 'reset') {
    sql = `UPDATE incident_stakeholders SET notified_at = NULL, ack_at = NULL WHERE id = ? AND incident_id = ? AND tenant_id = ?`;
    args = [req.params.stakeId, req.params.id, req.session.tenant.id];
  } else {
    return res.redirect('/incidents/' + req.params.id + '/command');
  }
  db.prepare(sql).run(...args);
  req.audit({ action: ACTIONS.UPDATE, entity: 'incident_stakeholders', entityId: +req.params.stakeId, summary: `Stakeholder ${mark}` });
  res.redirect('/incidents/' + req.params.id + '/command');
});

router.post('/:id/stakeholders/:stakeId/delete', (req, res) => {
  db.prepare(`DELETE FROM incident_stakeholders WHERE id = ? AND incident_id = ? AND tenant_id = ?`)
    .run(req.params.stakeId, req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'incident_stakeholders', entityId: +req.params.stakeId, summary: 'Stakeholder removed' });
  res.redirect('/incidents/' + req.params.id + '/command');
});

// ---------- Plan links ----------

router.post('/:id/plan-links', (req, res) => {
  const { plan_id } = req.body;
  const incident = db.prepare(`SELECT id FROM incidents WHERE id = ? AND tenant_id = ?`).get(req.params.id, req.session.tenant.id);
  if (!incident) return res.redirect('/incidents');
  const plan = db.prepare(`SELECT id FROM bcp_plans WHERE id = ? AND tenant_id = ?`).get(plan_id, req.session.tenant.id);
  if (!plan) { req.flash('error', 'Plan not found.'); return res.redirect('/incidents/' + req.params.id + '/command'); }
  try {
    db.prepare(`INSERT INTO incident_plan_links (tenant_id, incident_id, plan_id, linked_by) VALUES (?, ?, ?, ?)`)
      .run(req.session.tenant.id, incident.id, plan.id, req.session.user.name);
    req.audit({ action: ACTIONS.CREATE, entity: 'incident_plan_links', entityId: incident.id, summary: `Linked plan ${plan.id}` });
  } catch (e) { /* unique constraint — already linked */ }
  res.redirect('/incidents/' + req.params.id + '/command');
});

router.post('/:id/plan-links/:planId/delete', (req, res) => {
  db.prepare(`DELETE FROM incident_plan_links WHERE plan_id = ? AND incident_id = ? AND tenant_id = ?`)
    .run(req.params.planId, req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'incident_plan_links', entityId: +req.params.planId, summary: 'Plan unlinked' });
  res.redirect('/incidents/' + req.params.id + '/command');
});

// ---------- AI suggest next steps ----------

router.post('/:id/ai-suggest', async (req, res) => {
  const tenantId = req.session.tenant.id;
  const incident = db.prepare(`SELECT * FROM incidents WHERE id = ? AND tenant_id = ?`).get(req.params.id, tenantId);
  if (!incident) { req.flash('error', 'Incident not found.'); return res.redirect('/incidents'); }

  const updates = db.prepare(`SELECT author, note, created_at FROM incident_updates WHERE incident_id = ? ORDER BY created_at DESC LIMIT 10`).all(incident.id);
  const actions = db.prepare(`SELECT title, owner, status, priority FROM incident_actions WHERE incident_id = ? ORDER BY created_at DESC LIMIT 20`).all(incident.id);
  const decisions = db.prepare(`SELECT decision, decided_by, decided_at FROM incident_decisions WHERE incident_id = ? ORDER BY decided_at DESC LIMIT 10`).all(incident.id);
  const plans = db.prepare(`
    SELECT p.title, p.scope, p.content FROM incident_plan_links l
    JOIN bcp_plans p ON p.id = l.plan_id AND p.tenant_id = l.tenant_id
    WHERE l.incident_id = ? AND l.tenant_id = ?
  `).all(incident.id, tenantId);

  const planDigest = plans.length
    ? plans.map(p => `### ${p.title} (${p.scope || 'no scope'})\n${(p.content || '').slice(0, 3500)}`).join('\n\n---\n\n')
    : '(no continuity plans linked yet)';
  const timelineTxt = updates.length
    ? updates.map(u => `- ${u.created_at} · ${u.author}: ${u.note}`).join('\n')
    : '(no timeline updates yet)';
  const actionsTxt = actions.length
    ? actions.map(a => `- [${a.status}/${a.priority}] ${a.title}${a.owner ? ' — ' + a.owner : ''}`).join('\n')
    : '(no action items yet)';
  const decisionsTxt = decisions.length
    ? decisions.map(d => `- ${d.decided_at} · ${d.decided_by}: ${d.decision}`).join('\n')
    : '(no decisions logged yet)';

  const prompt = `You are advising an incident commander in real time. Based on the current state of the incident and any linked continuity plans, recommend the next 5-7 concrete actions the response team should take in the next 60 minutes.

# Incident
Title: ${incident.title}
Severity: ${incident.severity || 'unknown'}
Status: ${incident.status}
Commander: ${incident.commander || 'unassigned'}
Started: ${incident.started_at}
Affected systems: ${incident.affected_systems || 'unspecified'}
Description: ${incident.description || 'none'}

# Timeline (most recent first)
${timelineTxt}

# Existing action items
${actionsTxt}

# Decisions logged
${decisionsTxt}

# Linked continuity plan(s)
${planDigest}

Produce your response as markdown with two sections:
1. **Next 60 minutes** — a numbered list of 5–7 specific, assignable actions. For each action suggest an owner role (e.g. "Incident Commander", "Comms Lead", "IT Ops") and a time-box.
2. **Watch-outs** — a short bulleted list of risks, blind-spots, or decisions leadership should be making right now.

Be direct and practical. Reference the linked plan(s) by name where they already dictate steps. Do not pad.`;

  const { reply, provider } = await chat({ tenantId, messages: [{ role: 'user', content: prompt }] });

  // Log the update into the timeline so the team sees it
  db.prepare(`INSERT INTO incident_updates (tenant_id, incident_id, author, note) VALUES (?, ?, ?, ?)`)
    .run(tenantId, incident.id, 'AI Copilot', `**Suggested next steps** (${provider})\n\n${reply}`);
  req.audit({ action: ACTIONS.AI_CALL, entity: 'incidents', entityId: incident.id, summary: `AI suggestions requested (${provider})` });

  req.flash('success', 'AI suggestions added to the timeline.');
  res.redirect('/incidents/' + req.params.id + '/command');
});

// ---------- Classic CRUD ----------

router.post('/', (req, res) => {
  const b = req.body;
  const info = db.prepare(`
    INSERT INTO incidents (tenant_id, title, description, severity, status, commander, affected_systems)
    VALUES (?, ?, ?, ?, 'open', ?, ?)
  `).run(req.session.tenant.id, b.title, b.description || null, b.severity || 'SEV3', b.commander || null, b.affected_systems || null);

  try {
    const admins = db.prepare(`SELECT email FROM users WHERE tenant_id = ? AND role IN ('admin','manager')`).all(req.session.tenant.id);
    const toList = admins.map(a => a.email);
    if (toList.length) {
      sendIncidentDeclaredEmail({
        to: toList,
        tenantName: req.session.tenant.name,
        incident: { id: info.lastInsertRowid, title: b.title, severity: b.severity, description: b.description }
      }).catch(err => console.error('Incident email failed:', err.message));
    }
  } catch (e) { console.error(e); }

  req.audit({ action: ACTIONS.CREATE, entity: 'incidents', entityId: info.lastInsertRowid, summary: `Incident "${b.title}" declared (${b.severity || 'SEV3'})` });
  req.flash('success', 'Incident declared. Responders notified by email.');
  res.redirect('/incidents/' + info.lastInsertRowid + '/command');
});

router.post('/:id', (req, res) => {
  const b = req.body;
  db.prepare(`
    UPDATE incidents SET title=?, description=?, severity=?, status=?, commander=?, affected_systems=?,
      resolved_at = CASE WHEN ? IN ('resolved','closed') AND resolved_at IS NULL THEN CURRENT_TIMESTAMP ELSE resolved_at END,
      updated_at=CURRENT_TIMESTAMP
    WHERE id = ? AND tenant_id = ?
  `).run(b.title, b.description || null, b.severity || 'SEV3', b.status || 'open', b.commander || null, b.affected_systems || null, b.status, req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.UPDATE, entity: 'incidents', entityId: +req.params.id, summary: `Incident "${b.title}" set to ${b.status}` });
  req.flash('success', 'Incident updated.');
  res.redirect('/incidents/' + req.params.id);
});

router.post('/:id/delete', (req, res) => {
  db.prepare(`DELETE FROM incidents WHERE id = ? AND tenant_id = ?`).run(req.params.id, req.session.tenant.id);
  req.audit({ action: ACTIONS.DELETE, entity: 'incidents', entityId: +req.params.id, summary: 'Incident removed' });
  req.flash('success', 'Incident removed.');
  res.redirect('/incidents');
});

module.exports = router;
