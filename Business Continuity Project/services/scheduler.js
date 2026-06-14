// Cron-based reminder scheduler.
// - Scans BCP plans for upcoming reviews and seeds reminders.
// - Scans risks for due dates and seeds reminders.
// - Every minute, sweeps the reminders table and sends any that are due.

const cron = require('node-cron');
const db = require('../models/db');
const { sendReminderEmail } = require('./mailer');

// --- Seeders -----------------------------------------------------------

function scheduleBcpReviewReminder(planId, tenantId) {
  const plan = db.prepare('SELECT * FROM bcp_plans WHERE id = ? AND tenant_id = ?').get(planId, tenantId);
  if (!plan || !plan.next_review) return;

  // Remove any pending reminders previously created for this plan
  db.prepare(`DELETE FROM reminders WHERE tenant_id = ? AND ref_table = 'bcp_plans' AND ref_id = ? AND status = 'pending'`).run(tenantId, planId);

  // Reminder: 7 days before + on due date
  const admins = db.prepare(`SELECT email FROM users WHERE tenant_id = ? AND role IN ('admin','manager')`).all(tenantId);
  if (!admins.length) return;
  const to = admins.map(a => a.email).join(',');
  const url = (process.env.APP_URL || 'http://localhost:3000') + '/bcp/' + planId;

  const sevenDays = db.prepare(`
    INSERT INTO reminders (tenant_id, kind, ref_table, ref_id, send_to_email, subject, body, send_at)
    VALUES (?, 'bcp_review', 'bcp_plans', ?, ?, ?, ?, date(?, '-7 days'))
  `);
  const onDue = db.prepare(`
    INSERT INTO reminders (tenant_id, kind, ref_table, ref_id, send_to_email, subject, body, send_at)
    VALUES (?, 'bcp_review', 'bcp_plans', ?, ?, ?, ?, ?)
  `);

  sevenDays.run(tenantId, planId, to,
    `BCP review due in 7 days: ${plan.title}`,
    `<p>The plan <strong>${plan.title}</strong> is scheduled for review on <strong>${plan.next_review}</strong>. Please review and approve.</p><p><a href="${url}">Open plan</a></p>`,
    plan.next_review);

  onDue.run(tenantId, planId, to,
    `BCP review DUE today: ${plan.title}`,
    `<p>The plan <strong>${plan.title}</strong> is due for review today.</p><p><a href="${url}">Open plan</a></p>`,
    plan.next_review);
}

function scheduleRiskDueReminder(riskId, tenantId) {
  const risk = db.prepare('SELECT * FROM risks WHERE id = ? AND tenant_id = ?').get(riskId, tenantId);
  if (!risk || !risk.due_date) return;
  db.prepare(`DELETE FROM reminders WHERE tenant_id = ? AND ref_table = 'risks' AND ref_id = ? AND status = 'pending'`).run(tenantId, riskId);

  const admins = db.prepare(`SELECT email FROM users WHERE tenant_id = ? AND role IN ('admin','manager')`).all(tenantId);
  if (!admins.length) return;
  const to = admins.map(a => a.email).join(',');
  const url = (process.env.APP_URL || 'http://localhost:3000') + '/risks/' + riskId;

  db.prepare(`
    INSERT INTO reminders (tenant_id, kind, ref_table, ref_id, send_to_email, subject, body, send_at)
    VALUES (?, 'risk_due', 'risks', ?, ?, ?, ?, ?)
  `).run(tenantId, riskId, to,
    `Risk mitigation due: ${risk.title}`,
    `<p>Risk <strong>${risk.title}</strong> has its mitigation action due on <strong>${risk.due_date}</strong>.</p><p>Owner: ${risk.owner || '—'}</p><p><a href="${url}">Open risk</a></p>`,
    risk.due_date);
}

// --- Sweeper -----------------------------------------------------------

async function sweepReminders() {
  const due = db.prepare(`
    SELECT * FROM reminders
    WHERE status = 'pending' AND date(send_at) <= date('now')
    ORDER BY send_at ASC LIMIT 50
  `).all();

  for (const r of due) {
    try {
      await sendReminderEmail({
        to: r.send_to_email.split(',').map(s => s.trim()).filter(Boolean),
        subject: r.subject,
        title: r.subject,
        body: r.body,
        url: process.env.APP_URL || 'http://localhost:3000'
      });
      db.prepare(`UPDATE reminders SET status='sent', sent_at=CURRENT_TIMESTAMP WHERE id = ?`).run(r.id);
    } catch (err) {
      console.error('[scheduler] failed to send reminder', r.id, err.message);
      db.prepare(`UPDATE reminders SET status='failed', error=? WHERE id = ?`).run(err.message, r.id);
    }
  }
}

// --- Bootstrap ---------------------------------------------------------

function startScheduler() {
  // Every minute: sweep due reminders
  cron.schedule('* * * * *', () => {
    sweepReminders().catch(err => console.error('sweepReminders error', err));
  });

  // Every night at 02:00: refresh reminders from plans/risks so new data shows up
  cron.schedule('0 2 * * *', () => {
    try {
      const plans = db.prepare(`SELECT id, tenant_id FROM bcp_plans WHERE next_review IS NOT NULL`).all();
      plans.forEach(p => scheduleBcpReviewReminder(p.id, p.tenant_id));

      const risks = db.prepare(`SELECT id, tenant_id FROM risks WHERE due_date IS NOT NULL AND status != 'closed'`).all();
      risks.forEach(r => scheduleRiskDueReminder(r.id, r.tenant_id));
    } catch (e) { console.error('nightly reminder refresh failed', e.message); }
  });

  // Kick off an immediate sweep on boot
  sweepReminders().catch(() => {});
}

module.exports = { startScheduler, scheduleBcpReviewReminder, scheduleRiskDueReminder, sweepReminders };
