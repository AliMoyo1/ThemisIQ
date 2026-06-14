const nodemailer = require('nodemailer');
const cron = require('node-cron');
const db = require('../models/db');

function createTransport() {
  // Uses SMTP settings from .env — configure with your email provider
  return nodemailer.createTransport({
    host: process.env.SMTP_HOST || 'smtp.gmail.com',
    port: parseInt(process.env.SMTP_PORT || '587'),
    secure: false,
    auth: {
      user: process.env.SMTP_USER,
      pass: process.env.SMTP_PASS,
    },
    // For dev/testing without real SMTP, use Ethereal (auto-created below)
  });
}

async function getTestTransport() {
  const testAccount = await nodemailer.createTestAccount();
  const transport = nodemailer.createTransport({
    host: 'smtp.ethereal.email',
    port: 587,
    auth: { user: testAccount.user, pass: testAccount.pass }
  });
  return { transport, previewUrl: `https://ethereal.email` };
}

function buildReminderEmail(controlData) {
  const daysLeft = controlData.due_date ?
    Math.ceil((new Date(controlData.due_date) - new Date()) / 86400000) : null;
  const urgency = daysLeft !== null && daysLeft < 3 ? '🚨 URGENT' : daysLeft !== null && daysLeft < 7 ? '⚠️' : '📋';

  return {
    subject: `${urgency} AuditSphere: Evidence required — ${controlData.control_id} ${controlData.name}`,
    html: `
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>
  body { font-family: -apple-system, sans-serif; color: #1a1a2e; margin: 0; padding: 0; background: #f5f5f5; }
  .container { max-width: 560px; margin: 24px auto; background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }
  .header { background: #0d0f14; padding: 24px 28px; }
  .logo { color: #4f8ef7; font-weight: 700; font-size: 18px; letter-spacing: 0.1em; }
  .body { padding: 28px; }
  .title { font-size: 20px; font-weight: 700; margin-bottom: 6px; }
  .subtitle { color: #666; font-size: 14px; margin-bottom: 24px; }
  .card { background: #f8f9ff; border: 1px solid #e0e4ff; border-radius: 8px; padding: 16px; margin-bottom: 20px; }
  .label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: #888; margin-bottom: 4px; }
  .value { font-size: 14px; font-weight: 500; }
  .risk { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; }
  .risk-critical { background: #fee; color: #c0392b; }
  .risk-high { background: #fef5e7; color: #d68910; }
  .risk-medium { background: #eaf4ff; color: #2980b9; }
  .due-box { background: ${daysLeft !== null && daysLeft < 3 ? '#fee' : daysLeft !== null && daysLeft < 7 ? '#fef5e7' : '#f0fff4'}; border-radius: 8px; padding: 14px; text-align: center; margin-bottom: 20px; }
  .due-days { font-size: 32px; font-weight: 800; color: ${daysLeft !== null && daysLeft < 3 ? '#c0392b' : daysLeft !== null && daysLeft < 7 ? '#d68910' : '#27ae60'}; }
  .cta { display: block; text-align: center; background: #4f8ef7; color: white; text-decoration: none; padding: 13px 24px; border-radius: 8px; font-weight: 600; font-size: 15px; margin-bottom: 20px; }
  .footer { padding: 16px 28px; border-top: 1px solid #f0f0f0; font-size: 12px; color: #aaa; }
</style></head>
<body>
<div class="container">
  <div class="header"><div class="logo">AUDITSPHERE</div></div>
  <div class="body">
    <div class="title">Evidence Required</div>
    <div class="subtitle">You have a pending audit control that needs your attention.</div>
    <div class="card">
      <div class="label">Control</div>
      <div class="value">${controlData.control_id} — ${controlData.name}</div>
      <div style="margin-top:10px"><div class="label">Framework</div><div class="value">${controlData.framework_name || 'N/A'}</div></div>
      <div style="margin-top:10px"><div class="label">Risk Level</div><span class="risk risk-${(controlData.risk_level||'medium').toLowerCase()}">${controlData.risk_level}</span></div>
    </div>
    ${daysLeft !== null ? `
    <div class="due-box">
      <div class="due-days">${daysLeft <= 0 ? 'OVERDUE' : daysLeft}</div>
      <div style="font-size:13px;color:#555;">${daysLeft <= 0 ? 'Past due date' : `day${daysLeft !== 1 ? 's' : ''} remaining — Due ${controlData.due_date}`}</div>
    </div>` : ''}
    <a href="${process.env.APP_URL || 'http://localhost:3000'}" class="cta">Open AuditSphere →</a>
    <p style="font-size:13px;color:#666;line-height:1.6;">Please log in to upload the required evidence for this control. If you have questions, contact your audit lead.</p>
  </div>
  <div class="footer">AuditSphere · Compliance Audit Management · <a href="${process.env.APP_URL || 'http://localhost:3000'}" style="color:#4f8ef7;">Open Portal</a></div>
</div>
</body></html>`
  };
}

async function sendReminder(reminder, controlData) {
  const email = buildReminderEmail(controlData);
  try {
    let transport, previewUrl;
    if (process.env.SMTP_USER) {
      transport = createTransport();
    } else {
      const t = await getTestTransport();
      transport = t.transport;
      previewUrl = t.previewUrl;
    }

    const info = await transport.sendMail({
      from: process.env.SMTP_FROM || '"AuditSphere" <noreply@auditsphere.local>',
      to: reminder.email,
      subject: email.subject,
      html: email.html,
    });

    // Update last_sent
    db.prepare('UPDATE reminders SET last_sent = ? WHERE id = ?')
      .run(new Date().toISOString(), reminder.id);

    // Log it
    const { v4: uuidv4 } = require('uuid');
    db.prepare('INSERT INTO audit_log (id, entity_type, entity_id, action, details) VALUES (?, ?, ?, ?, ?)')
      .run(uuidv4(), 'reminder', reminder.control_id, 'email_sent', JSON.stringify({ to: reminder.email, messageId: info.messageId, preview: previewUrl }));

    return { success: true, messageId: info.messageId, preview: previewUrl };
  } catch (err) {
    console.error('Email send error:', err.message);
    return { success: false, error: err.message };
  }
}

function startReminderCron() {
  // Runs every day at 8am
  cron.schedule('0 8 * * *', async () => {
    console.log('[Cron] Checking reminders...');
    const reminders = db.prepare(`
      SELECT r.*, c.control_id, c.name, c.risk_level, c.due_date, c.status,
             f.name as framework_name
      FROM reminders r
      JOIN controls c ON r.control_id = c.id
      JOIN audits a ON r.audit_id = a.id
      JOIN frameworks f ON a.framework_id = f.id
      WHERE r.is_active = 1
        AND c.status != 'Complete'
        AND (
          r.last_sent IS NULL
          OR (r.frequency = 'daily' AND date(r.last_sent) < date('now'))
          OR (r.frequency = 'weekly' AND date(r.last_sent) < date('now', '-7 days'))
        )
    `).all();

    for (const r of reminders) {
      await sendReminder(r, r);
    }
    console.log(`[Cron] Sent ${reminders.length} reminders`);
  });
  console.log('[Cron] Reminder scheduler started');
}

module.exports = { sendReminder, startReminderCron, buildReminderEmail };
