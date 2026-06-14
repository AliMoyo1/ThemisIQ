/**
 * scheduler.js — G.R.I.D AI Cron Scheduler
 * Africa/Harare timezone (CAT = UTC+2)
 * 
 * IMPORTANT: Jobs only run on schedule, never on startup.
 * All email calls have timeouts built into email.js (10s per request).
 */
const cron = require('node-cron');
const db   = require('../database');
const {
  sendEmail, reminderEmailHTML, weeklyDigestHTML,
  escalationHTML, expiryAlertHTML,
} = require('./email');
const { sendTeamsNotification } = require('./microsoft');

function now()   { return new Date().toISOString(); }
function today() { return new Date().toISOString().slice(0, 10); }

// ── Reminders — daily 08:00 CAT ──────────────────────────────────────
async function processReminders() {
  console.log('⏰ Running reminders...');
  try {
    const reminders = db.all(`
      SELECT r.*, c.control_id, c.name as control_name, c.due_date,
             c.status as control_status, a.name as audit_name,
             u.name as user_name
      FROM reminders r
      JOIN controls c ON r.control_id = c.id
      JOIN audits a   ON c.audit_id   = a.id
      LEFT JOIN users u ON u.email    = r.user_email
      WHERE r.active = 1 AND c.status != 'complete'
      AND (
        (r.frequency = 'daily') OR
        (r.frequency = 'weekly'  AND (r.last_sent IS NULL OR datetime(r.last_sent) < datetime('now','-6 days'))) OR
        (r.frequency = 'monthly' AND (r.last_sent IS NULL OR datetime(r.last_sent) < datetime('now','-28 days')))
      )
    `);
    for (const r of reminders) {
      await sendEmail({
        to: r.user_email,
        subject: `[G.R.I.D AI] Reminder: ${r.control_name}`,
        html: reminderEmailHTML({
          controlName: r.control_name, controlId: r.control_id,
          dueDate: r.due_date, auditName: r.audit_name,
          recipientName: r.user_name, frequency: r.frequency,
        }),
      });
      db.run('UPDATE reminders SET last_sent=? WHERE id=?', [now(), r.id]);
    }
    console.log(`✅ Reminders done: ${reminders.length} sent`);
  } catch (e) { console.error('Reminders error:', e.message); }
}

// ── Escalations — daily 09:00 CAT ────────────────────────────────────
async function processEscalations() {
  console.log('🚨 Running escalations...');
  try {
    const overdue = db.all(`
      SELECT c.*, a.name as audit_name,
             u.name as owner_name, u.email as owner_email,
             m.name as manager_name, m.email as manager_email
      FROM controls c
      JOIN audits a ON c.audit_id = a.id
      LEFT JOIN users u ON c.assigned_to = u.id
      LEFT JOIN users m ON m.role = 'admin'
      WHERE c.due_date < date('now','-7 days')
      AND c.status != 'complete'
      AND c.assigned_to IS NOT NULL
      AND c.risk_level IN ('Critical','High')
      LIMIT 20
    `);
    const seen = new Set();
    for (const ctrl of overdue) {
      if (!ctrl.manager_email || seen.has(ctrl.id)) continue;
      seen.add(ctrl.id);
      const daysOverdue = Math.floor((new Date() - new Date(ctrl.due_date)) / 86400000);
      await sendEmail({
        to: ctrl.manager_email,
        subject: `[G.R.I.D AI] ESCALATION: ${ctrl.name} — ${daysOverdue} days overdue`,
        html: escalationHTML({
          managerName: ctrl.manager_name, ownerName: ctrl.owner_name || 'Unassigned',
          controlName: ctrl.name, controlId: ctrl.control_id || ctrl.id.slice(0, 8),
          daysOverdue, auditName: ctrl.audit_name,
        }),
      });
    }
    console.log(`✅ Escalations done: ${seen.size} sent`);
  } catch (e) { console.error('Escalations error:', e.message); }
}

// ── Expiry Alerts — daily 08:30 CAT ──────────────────────────────────
async function processExpiryAlerts() {
  console.log('📅 Running expiry alerts...');
  try {
    const expiring = db.all(`
      SELECT e.*, c.name as control_name, a.name as audit_name,
             u.name as owner_name, u.email as owner_email
      FROM evidence e
      JOIN controls c ON e.control_id = c.id
      JOIN audits a   ON e.audit_id   = a.id
      LEFT JOIN users u ON c.assigned_to = u.id
      WHERE e.expiry_date IS NOT NULL
      AND e.expiry_date > date('now')
      AND e.expiry_date <= date('now','+30 days')
      AND e.expiry_notified = 0
      AND e.status != 'rejected'
    `);
    for (const ev of expiring) {
      if (!ev.owner_email) continue;
      const daysLeft = Math.ceil((new Date(ev.expiry_date) - new Date()) / 86400000);
      await sendEmail({
        to: ev.owner_email,
        subject: `[G.R.I.D AI] Evidence expiring in ${daysLeft} days: ${ev.name}`,
        html: expiryAlertHTML({
          recipientName: ev.owner_name, evidenceName: ev.name,
          controlName: ev.control_name, expiryDate: ev.expiry_date,
          daysUntilExpiry: daysLeft,
        }),
      });
      db.run('UPDATE evidence SET expiry_notified=1 WHERE id=?', [ev.id]);
    }
    console.log(`✅ Expiry alerts done: ${expiring.length} sent`);
  } catch (e) { console.error('Expiry alerts error:', e.message); }
}

// ── Weekly Digest — Mondays 07:00 CAT ────────────────────────────────
async function sendWeeklyDigest() {
  console.log('📊 Sending weekly digest...');
  try {
    const subs = db.all('SELECT * FROM digest_subscriptions WHERE active=1');
    if (subs.length === 0) { console.log('No digest subscribers'); return; }

    const audits = db.all(`
      SELECT a.*, f.name as framework_name,
             COUNT(c.id) as total_controls,
             SUM(CASE WHEN c.status='complete' THEN 1 ELSE 0 END) as complete_controls,
             SUM(CASE WHEN c.due_date < date('now') AND c.status!='complete' THEN 1 ELSE 0 END) as overdue_controls
      FROM audits a
      JOIN frameworks f ON a.framework_id = f.id
      LEFT JOIN controls c ON c.audit_id = a.id
      GROUP BY a.id ORDER BY a.created_at DESC
    `);
    audits.forEach(a => {
      a.completion_pct = a.total_controls > 0
        ? Math.round(a.complete_controls / a.total_controls * 100) : 0;
    });

    for (const sub of subs) {
      const filtered = sub.audit_ids === 'all' ? audits
        : audits.filter(a => (sub.audit_ids || '').split(',').includes(a.id));
      await sendEmail({
        to: sub.email,
        subject: `[G.R.I.D AI] Weekly Compliance Digest — ${new Date().toLocaleDateString('en-GB')}`,
        html: weeklyDigestHTML({ recipientName: sub.name, audits: filtered }),
      });
    }

    await sendTeamsNotification({
      title: 'Weekly Compliance Digest',
      text:  `${audits.length} audit(s) tracked.`,
      facts: audits.slice(0, 5).map(a => ({ label: a.name, value: `${a.completion_pct}%` })),
      actionUrl: process.env.APP_URL,
    });

    console.log(`✅ Weekly digest sent to ${subs.length} subscriber(s)`);
  } catch (e) { console.error('Weekly digest error:', e.message); }
}

// ── Compliance Score Snapshot — midnight ─────────────────────────────
async function snapshotScores() {
  try {
    const { v4: uuid } = require('uuid');
    const audits = db.all(`
      SELECT a.id, COUNT(c.id) as total,
             SUM(CASE WHEN c.status='complete' THEN 1 ELSE 0 END) as complete
      FROM audits a LEFT JOIN controls c ON c.audit_id=a.id GROUP BY a.id
    `);
    for (const a of audits) {
      const score = a.total > 0 ? Math.round(a.complete / a.total * 100) : 0;
      db.run('INSERT INTO compliance_scores (id,audit_id,score,total_controls,complete_controls) VALUES (?,?,?,?,?)',
        [uuid(), a.id, score, a.total, a.complete]);
    }
  } catch (e) { console.error('Score snapshot error:', e.message); }
}

// ── Backup — 02:00 CAT ───────────────────────────────────────────────
async function performBackup() {
  console.log('💾 Running backup...');
  try {
    const fs      = require('fs');
    const path    = require('path');
    const archiver = require('archiver');
    const dir     = process.env.BACKUP_PATH || './data/backups';
    fs.mkdirSync(dir, { recursive: true });
    const stamp  = today();
    const zip    = path.join(dir, `gridai-backup-${stamp}.zip`);
    if (fs.existsSync(zip)) { console.log('💾 Backup already exists for today'); return; }
    const out    = fs.createWriteStream(zip);
    const arc    = archiver('zip', { zlib: { level: 6 } });
    arc.pipe(out);
    if (fs.existsSync('./data/auditsphere.db')) arc.file('./data/auditsphere.db', { name: 'auditsphere.db' });
    if (fs.existsSync('./data/uploads'))        arc.directory('./data/uploads', 'uploads');
    await arc.finalize();
    // Prune old backups
    const retain = parseInt(process.env.BACKUP_RETAIN_DAYS || '30');
    const cutoff = new Date(Date.now() - retain * 86400000);
    fs.readdirSync(dir).filter(f => f.endsWith('.zip')).forEach(f => {
      const fp = path.join(dir, f);
      if (fs.statSync(fp).mtime < cutoff) { fs.unlinkSync(fp); console.log('🗑 Pruned:', f); }
    });
    console.log(`✅ Backup done: ${zip}`);
  } catch (e) { console.error('Backup error:', e.message); }
}

// ── Start — register cron jobs only, never run on startup ────────────
function startScheduler() {
  const tz = 'Africa/Harare';

  // Each job runs on schedule only — no immediate execution
  cron.schedule('0 8 * * *',   processReminders,    { timezone: tz });
  cron.schedule('30 8 * * *',  processExpiryAlerts, { timezone: tz });
  cron.schedule('0 9 * * *',   processEscalations,  { timezone: tz });
  cron.schedule('0 7 * * 1',   sendWeeklyDigest,    { timezone: tz }); // Monday only
  cron.schedule('0 0 * * *',   snapshotScores,      { timezone: tz });
  cron.schedule('0 2 * * *',   performBackup,        { timezone: tz });

  console.log('✅ Scheduler started (Africa/Harare timezone)');
}

module.exports = { startScheduler, processReminders, sendWeeklyDigest, performBackup, snapshotScores };
