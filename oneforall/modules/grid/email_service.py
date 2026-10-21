"""
GRID module: the audit share invitation email.

Reminders, escalations, finding assignments and the weekly summary are asked for from the email outbox
(core/email_outbox.py) with the catalogue in core/email_templates.py. This one message is sent at once by the person who
creates a share, because it carries a link that works only for the signed-in recipient, and its result is reported back
to that person.

Security: all dynamic text is HTML-escaped before insertion.
"""
from __future__ import annotations

import html


def _esc(text) -> str:
    """HTML-escape user-supplied text for safe template insertion."""
    return html.escape(str(text)) if text else ""


def send_email(*, to: str, subject: str, body_html: str, body_text: str | None = None) -> dict:
    """
    Send an email via the central ThemisIQ email utility (core.email.send_email).

    Returns {"status": provider_accepted | logged_only | suppressed | failed, "ok": bool, "provider": ...}. A message
    whose HTML has no text part gets one made from it.
    """
    from core.email import send_email as _central
    return _central(to=to, subject=subject, body_html=body_html, body_text=body_text)


def audit_share_html(
    *, auditor_name: str = "", audit_name: str = "", share_url: str = "",
    expires_at: str = "", created_by: str = "",
) -> str:
    """Audit read-only access link. Every value is escaped; the link is the one the caller built from APP_URL."""
    expiry_line = (f'<p style="font-size:12px;color:#92400e">Access expires: {_esc(expires_at)}</p>'
                   if expires_at else "")
    return f"""<div style="font-family:'Segoe UI',Arial,sans-serif;max-width:560px;margin:0 auto;padding:20px;color:#1e293b">
  <div style="font-size:12px;font-weight:700;letter-spacing:.06em;color:#64748b">THEMISIQ</div>
  <h2 style="font-size:18px;margin:12px 0">Audit access granted</h2>
  <p>Hello {_esc(auditor_name) or 'there'},</p>
  <p>{_esc(created_by) or 'A colleague'} has granted you read-only access to the audit {_esc(audit_name)}.</p>
  <p>Sign in to ThemisIQ with this email address, then open the link below. The link only works for your account.</p>
  {expiry_line}
  <p><a href="{_esc(share_url)}" style="display:inline-block;background:#1e3a8a;color:#ffffff;padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:600">View the audit</a></p>
  <p style="font-size:12px;color:#475569">{_esc(share_url)}</p>
  <p style="font-size:12px;color:#64748b;border-top:1px solid #e2e8f0;padding-top:10px">Read-only access. Contact {_esc(created_by) or 'the sender'} for write access. This is an operational message from ThemisIQ. Do not reply to it.</p>
</div>"""
