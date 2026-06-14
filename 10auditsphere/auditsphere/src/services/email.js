/**
 * email.js — G.R.I.D AI Email Service
 * Sender: aliomnizim@gmail.com via Gmail SMTP
 * All emails branded G.R.I.D AI
 */
const nodemailer = require('nodemailer');

const TIMEOUT_MS = 10000;
let _transport = null;

function getTransport() {
  if (_transport) return _transport;

  // Gmail SMTP (primary)
  if (process.env.SMTP_USER && process.env.SMTP_PASS) {
    _transport = nodemailer.createTransport({
      host:   process.env.SMTP_HOST || 'smtp.gmail.com',
      port:   parseInt(process.env.SMTP_PORT || '587'),
      secure: false,
      auth: {
        user: process.env.SMTP_USER,
        pass: process.env.SMTP_PASS.replace(/\s/g, ''), // strip spaces from app password
      },
      connectionTimeout: TIMEOUT_MS,
      greetingTimeout:   TIMEOUT_MS,
      socketTimeout:     TIMEOUT_MS,
    });
    _transport._provider = 'gmail';
    return _transport;
  }

  // Ethereal fallback (test mode — preview URL shown in console)
  return null;
}

let _ethereal = null;
async function getEtherealTransport() {
  if (_ethereal) return _ethereal;
  const acct = await nodemailer.createTestAccount();
  _ethereal  = nodemailer.createTransport({
    host: 'smtp.ethereal.email', port: 587, secure: false,
    auth: { user: acct.user, pass: acct.pass },
    connectionTimeout: TIMEOUT_MS,
  });
  _ethereal._user = acct.user;
  console.log(`\n📧 Ethereal test account created: ${acct.user}`);
  console.log('   View sent emails at: https://ethereal.email/login\n');
  return _ethereal;
}

async function sendEmail({ to, subject, html }) {
  const from = process.env.SMTP_FROM
    ? `G.R.I.D AI <${process.env.SMTP_FROM}>`
    : 'G.R.I.D AI <aliomnizim@gmail.com>';

  const transport = getTransport();

  if (transport) {
    try {
      await transport.sendMail({ from, to, subject, html });
      console.log(`📧 Sent → ${to} | ${subject}`);
      return { ok: true, provider: 'gmail' };
    } catch (err) {
      console.error(`📧 Gmail failed → ${to}: ${err.message}`);
      // Fall through to Ethereal
    }
  }

  // Ethereal fallback
  try {
    const eth  = await getEtherealTransport();
    const info = await eth.sendMail({ from: 'G.R.I.D AI <gridai@ethereal.email>', to, subject, html });
    const url  = nodemailer.getTestMessageUrl(info);
    console.log(`📧 [TEST - not real] Preview: ${url}`);
    return { ok: true, provider: 'ethereal', previewUrl: url };
  } catch (err) {
    console.error(`📧 All providers failed: ${err.message}`);
    return { ok: false, error: err.message };
  }
}

// ─────────────────────────────────────────────────────────────────────
// HTML Email Templates — G.R.I.D AI branded
// ─────────────────────────────────────────────────────────────────────
const G  = '#1a6b3a';
const GL = '#e8f5ee';
const APP_URL = () => process.env.APP_URL || 'http://localhost:3000';

function emailWrap(body, preheader = '') {
  return `<!DOCTYPE html><html><head><meta charset="UTF-8"/><style>
body{margin:0;padding:0;background:#f5f6fa;font-family:'Segoe UI',Arial,sans-serif}
.wrap{max-width:580px;margin:32px auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.08)}
.hdr{background:${G};padding:28px 32px}
.logo{font-size:20px;font-weight:800;color:white;margin:0}
.sub{font-size:11px;color:rgba(255,255,255,.75);margin:3px 0 0;font-family:monospace}
.bdy{padding:28px 32px}
.ftr{background:#f8f9fc;border-top:1px solid #e5e7eb;padding:16px 32px;font-size:11px;color:#9ca3af;text-align:center}
.btn{display:inline-block;background:${G};color:white!important;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;margin:14px 0}
p{color:#374151;line-height:1.65;margin:0 0 14px}
h2{color:#111827;font-size:18px;font-weight:800;margin:0 0 16px}
hr{border:none;border-top:1px solid #e5e7eb;margin:18px 0}
</style></head><body>
<div style="display:none;max-height:0;overflow:hidden">${preheader}</div>
<div class="wrap">
  <div class="hdr">
    <p class="logo">G&middot;R&middot;I&middot;D AI</p>
    <p class="sub">Governance &middot; Risk &middot; IT &middot; Data &middot; by Ali Moyo</p>
  </div>
  <div class="bdy">${body}</div>
  <div class="ftr">G.R.I.D AI Compliance Management &middot; Powered by Claude AI<br>Sent from aliomnizim@gmail.com</div>
</div></body></html>`;
}

function reminderEmailHTML({ controlName, controlId, dueDate, auditName, recipientName, frequency }) {
  const over = dueDate && dueDate < new Date().toISOString().slice(0,10);
  return emailWrap(`
    <h2>${over ? '&#9888; Overdue Control' : '&#9200; Evidence Reminder'}</h2>
    <p>Hi ${recipientName || 'there'},</p>
    <p>A control item requires your attention:</p>
    <div style="background:#f8f9fc;border-left:4px solid ${over ? '#dc2626' : G};border-radius:0 8px 8px 0;padding:16px;margin:16px 0">
      <div style="font-size:11px;color:${G};font-family:monospace;font-weight:700">${controlId || ''}</div>
      <div style="font-size:15px;font-weight:700;color:#111827;margin:6px 0">${controlName}</div>
      <div style="font-size:12px;color:${over ? '#dc2626' : '#6b7280'}">${over ? 'OVERDUE — was due' : 'Due'}: ${dueDate || 'Not set'}</div>
      <div style="font-size:12px;color:#6b7280;margin-top:4px">Audit: ${auditName}</div>
    </div>
    <a href="${APP_URL()}" class="btn">Open G.R.I.D AI</a>
    <hr/><p style="font-size:11px;color:#9ca3af">Receiving ${frequency || 'weekly'} reminders for this control.</p>
  `, `Action required: ${controlName}`);
}

function weeklyDigestHTML({ recipientName, audits }) {
  const rows = (audits || []).map(a => {
    const pct = a.completion_pct || 0;
    const col = pct >= 80 ? G : pct >= 40 ? '#d97706' : '#dc2626';
    return `<tr style="border-bottom:1px solid #e5e7eb">
      <td style="padding:12px 0">
        <div style="font-weight:700;color:#111827">${a.name}</div>
        <div style="font-size:11px;color:#6b7280;font-family:monospace">${a.framework_name} &middot; ${a.audit_type}</div>
      </td>
      <td style="text-align:center;padding:12px 8px"><span style="font-size:20px;font-weight:800;color:${col}">${pct}%</span></td>
      <td style="text-align:center;padding:12px 8px;font-family:monospace;font-size:12px">${a.complete_controls || 0}/${a.total_controls || 0}</td>
      <td style="text-align:center;padding:12px 8px">
        <span style="padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;font-family:monospace;background:${(a.overdue_controls||0)>0?'#fee2e2':GL};color:${(a.overdue_controls||0)>0?'#991b1b':G}">${a.overdue_controls || 0} overdue</span>
      </td>
    </tr>`;
  }).join('');
  return emailWrap(`
    <h2>&#128202; Weekly Compliance Digest</h2>
    <p>Hi ${recipientName || 'there'}, your compliance summary for the week:</p>
    <table style="width:100%;border-collapse:collapse;margin:16px 0">
      <thead><tr style="border-bottom:2px solid #e5e7eb">
        <th style="text-align:left;padding:8px 0;font-size:11px;color:#6b7280;font-family:monospace;text-transform:uppercase">Audit</th>
        <th style="text-align:center;padding:8px;font-size:11px;color:#6b7280;font-family:monospace;text-transform:uppercase">Progress</th>
        <th style="text-align:center;padding:8px;font-size:11px;color:#6b7280;font-family:monospace;text-transform:uppercase">Controls</th>
        <th style="text-align:center;padding:8px;font-size:11px;color:#6b7280;font-family:monospace;text-transform:uppercase">Status</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <a href="${APP_URL()}" class="btn">Open Dashboard</a>
  `, 'Your weekly compliance digest');
}

function auditShareHTML({ auditorName, auditName, shareUrl, expiresAt, createdBy }) {
  return emailWrap(`
    <h2>&#128279; Audit Access Granted</h2>
    <p>Hi ${auditorName || 'there'},</p>
    <p><strong>${createdBy || 'G.R.I.D AI'}</strong> has granted you read-only access to: <strong>${auditName}</strong></p>
    ${expiresAt ? `<p style="font-size:12px;color:#d97706;font-family:monospace">Access expires: ${expiresAt}</p>` : ''}
    <a href="${shareUrl}" class="btn">View Audit</a>
    <hr/><p style="font-size:12px;color:#6b7280">Read-only access. Contact ${createdBy} for write access.</p>
  `, `Audit access: ${auditName}`);
}

function approvalRequestHTML({ approverName, evidenceName, controlName, uploaderName, reviewUrl }) {
  return emailWrap(`
    <h2>&#128203; Evidence Awaiting Approval</h2>
    <p>Hi ${approverName || 'there'},</p>
    <p><strong>${uploaderName || 'A team member'}</strong> has uploaded evidence for your review:</p>
    <div style="background:#f8f9fc;border-radius:8px;padding:16px;margin:16px 0;border:1px solid #e5e7eb">
      <div style="font-size:15px;font-weight:700;color:#111827;margin-bottom:6px">${evidenceName}</div>
      <div style="font-size:12px;color:#6b7280">For control: <strong>${controlName}</strong></div>
    </div>
    <a href="${reviewUrl || APP_URL()}" class="btn">Review Evidence</a>
  `, `Evidence requires approval: ${evidenceName}`);
}

function approvalDecisionHTML({ uploaderName, evidenceName, decision, comment, reviewerName }) {
  const ok = decision === 'approved';
  return emailWrap(`
    <h2>${ok ? '&#9989; Evidence Approved' : '&#10060; Evidence Rejected'}</h2>
    <p>Hi ${uploaderName || 'there'}, your evidence was <strong style="color:${ok ? G : '#dc2626'}">${decision}</strong> by ${reviewerName}.</p>
    <div style="background:${ok ? GL : '#fee2e2'};border-radius:8px;padding:14px;margin:16px 0">
      <div style="font-size:14px;font-weight:700;color:#111827;margin-bottom:6px">${evidenceName}</div>
      ${comment ? `<div style="font-size:13px;color:#374151">Comment: ${comment}</div>` : ''}
    </div>
    <a href="${APP_URL()}" class="btn">Open G.R.I.D AI</a>
  `, `Evidence ${decision}: ${evidenceName}`);
}

function escalationHTML({ managerName, ownerName, controlName, controlId, daysOverdue, auditName }) {
  return emailWrap(`
    <h2>&#128680; Escalation: Overdue Control</h2>
    <p>Hi ${managerName || 'there'}, a control has been overdue for <strong>${daysOverdue} days</strong> with no activity:</p>
    <div style="background:#fee2e2;border-left:4px solid #dc2626;border-radius:0 8px 8px 0;padding:16px;margin:16px 0">
      <div style="font-size:11px;color:#dc2626;font-family:monospace;font-weight:700">${controlId}</div>
      <div style="font-size:15px;font-weight:700;color:#111827;margin:4px 0">${controlName}</div>
      <div style="font-size:12px;color:#6b7280">Assigned to: ${ownerName} &middot; Audit: ${auditName}</div>
    </div>
    <a href="${APP_URL()}" class="btn">View in G.R.I.D AI</a>
  `, `ESCALATION: ${controlName} is ${daysOverdue} days overdue`);
}

function expiryAlertHTML({ recipientName, evidenceName, controlName, expiryDate, daysUntilExpiry }) {
  return emailWrap(`
    <h2>&#9200; Evidence Expiring Soon</h2>
    <p>Hi ${recipientName || 'there'}, the following evidence expires in <strong>${daysUntilExpiry} days</strong>:</p>
    <div style="background:#fef3c7;border-left:4px solid #d97706;border-radius:0 8px 8px 0;padding:16px;margin:16px 0">
      <div style="font-size:15px;font-weight:700;color:#111827;margin-bottom:6px">${evidenceName}</div>
      <div style="font-size:12px;color:#6b7280">Control: ${controlName}</div>
      <div style="font-size:12px;color:#d97706;margin-top:6px;font-family:monospace">Expires: ${expiryDate}</div>
    </div>
    <a href="${APP_URL()}" class="btn">Update Evidence</a>
  `, `Evidence expiring in ${daysUntilExpiry} days`);
}

function ncAlertHTML({ ownerName, ncTitle, severity, dueDate, raisedBy, auditName }) {
  const c = severity === 'Critical' ? '#dc2626' : severity === 'Major' ? '#d97706' : '#2563eb';
  return emailWrap(`
    <h2>&#9888; Non-Conformance Assigned</h2>
    <p>Hi ${ownerName || 'there'}, a non-conformance has been assigned to you for corrective action:</p>
    <div style="background:#f8f9fc;border-radius:8px;padding:16px;margin:16px 0;border:1px solid #e5e7eb">
      <div style="font-size:15px;font-weight:700;color:#111827;margin-bottom:8px">${ncTitle}</div>
      <span style="background:${c}22;color:${c};font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px;font-family:monospace">${severity}</span>
      <div style="font-size:12px;color:#6b7280;margin-top:10px">Raised by: ${raisedBy} &middot; Audit: ${auditName}</div>
      ${dueDate ? `<div style="font-size:12px;color:#dc2626;margin-top:4px;font-family:monospace">Due: ${dueDate}</div>` : ''}
    </div>
    <a href="${APP_URL()}" class="btn">View Non-Conformance</a>
  `, `NC assigned: ${ncTitle}`);
}

module.exports = {
  sendEmail, emailWrap,
  reminderEmailHTML, weeklyDigestHTML, auditShareHTML,
  approvalRequestHTML, approvalDecisionHTML, escalationHTML,
  expiryAlertHTML, ncAlertHTML,
};
