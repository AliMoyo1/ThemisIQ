// Nodemailer-based email service for incident alerts and reminder emails.

const nodemailer = require('nodemailer');

let transporter = null;

function getTransporter() {
  if (transporter) return transporter;
  const {
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
  } = process.env;

  if (!SMTP_HOST || !SMTP_USER || !SMTP_PASS) {
    console.warn('SMTP not fully configured — emails will be skipped.');
    return null;
  }

  transporter = nodemailer.createTransport({
    host: SMTP_HOST,
    port: parseInt(SMTP_PORT || '587', 10),
    secure: parseInt(SMTP_PORT || '587', 10) === 465,
    auth: { user: SMTP_USER, pass: SMTP_PASS }
  });
  return transporter;
}

async function sendMail({ to, subject, html, text }) {
  const t = getTransporter();
  if (!t) {
    console.warn('[mailer] Skipping send — SMTP not configured.');
    return { skipped: true };
  }
  const from = process.env.SMTP_FROM || process.env.SMTP_USER;
  const appName = process.env.APP_NAME || 'Continuity OS';
  const info = await t.sendMail({
    from: `${appName} <${from}>`,
    to: Array.isArray(to) ? to.join(',') : to,
    subject,
    html,
    text: text || (html || '').replace(/<[^>]+>/g, '')
  });
  return { messageId: info.messageId, accepted: info.accepted, rejected: info.rejected };
}

function baseTemplate({ title, bodyHtml, ctaUrl, ctaText }) {
  return `
  <div style="font-family:Inter,Segoe UI,Helvetica,Arial,sans-serif; background:#b0ac8f; padding:28px;">
    <div style="max-width:600px; margin:0 auto; background:#f4f1e8; border-radius:18px; overflow:hidden;">
      <div style="background:#0f1116; color:#fff; padding:16px 22px; font-size:16px; font-weight:600;">
        ${process.env.APP_NAME || 'Continuity OS'}
      </div>
      <div style="padding:22px;">
        <h2 style="font-family:'Cormorant Garamond', Georgia, serif; font-weight:500; font-size:22px; margin:0 0 10px; color:#1c1c1c;">${title}</h2>
        <div style="color:#333; line-height:1.55; font-size:14.5px;">${bodyHtml}</div>
        ${ctaUrl ? `<div style="margin-top:18px;"><a href="${ctaUrl}" style="background:#0f1116; color:#fff; padding:10px 18px; border-radius:10px; text-decoration:none; font-weight:600;">${ctaText || 'Open'}</a></div>` : ''}
      </div>
      <div style="padding:14px 22px; color:#8a8a5b; font-size:12px; border-top:1px solid #e8e4d5;">
        You're receiving this because you are listed as a contact on your BCM workspace. Adjust notification preferences in Settings.
      </div>
    </div>
  </div>`;
}

async function sendIncidentDeclaredEmail({ to, tenantName, incident }) {
  const url = (process.env.APP_URL || 'http://localhost:3000') + '/incidents/' + incident.id;
  const body = `
    <p>A <strong>${incident.severity || 'SEV3'}</strong> incident has been declared on the <strong>${tenantName}</strong> workspace.</p>
    <p><strong>Title:</strong> ${incident.title}</p>
    ${incident.description ? `<p>${incident.description}</p>` : ''}
    <p>Please join the response channel and acknowledge.</p>
  `;
  return sendMail({
    to,
    subject: `[${incident.severity || 'SEV3'}] Incident declared: ${incident.title}`,
    html: baseTemplate({ title: 'Incident declared', bodyHtml: body, ctaUrl: url, ctaText: 'Open incident' })
  });
}

async function sendReminderEmail({ to, subject, title, body, url, ctaText }) {
  return sendMail({
    to,
    subject,
    html: baseTemplate({ title, bodyHtml: body, ctaUrl: url, ctaText: ctaText || 'Open in Continuity OS' })
  });
}

async function sendTestEmail(to) {
  return sendMail({
    to,
    subject: 'SMTP test from Continuity OS',
    html: baseTemplate({
      title: 'SMTP is working',
      bodyHtml: '<p>This is a test message. If you can read this, email reminders are wired up correctly.</p>',
      ctaUrl: process.env.APP_URL,
      ctaText: 'Open workspace'
    })
  });
}

module.exports = { sendMail, sendIncidentDeclaredEmail, sendReminderEmail, sendTestEmail };
