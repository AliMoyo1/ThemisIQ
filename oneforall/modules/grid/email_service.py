"""
GRID module — Email service.

Provides branded HTML email templates for GRID module notifications.
Transport is handled by core.email (provider-agnostic: Gmail, Office 365, Graph API).

Security: all dynamic text is HTML-escaped before insertion into templates.
"""
from __future__ import annotations

import html
import logging

log = logging.getLogger("grid.email")

# ═════════════════════════════════════════════════════════════════════════
# Transport
# ═════════════════════════════════════════════════════════════════════════


def _esc(text: str | None) -> str:
    """HTML-escape user-supplied text for safe template insertion."""
    return html.escape(str(text)) if text else ""


def send_email(*, to: str, subject: str, body_html: str) -> dict:
    """
    Send an email via the central AegisGRC email utility.

    Delegates to core.email.send_email which supports Google SMTP,
    Microsoft SMTP, Microsoft Graph API, and console fallback.
    All existing GRID call sites remain unchanged.

    Returns {"ok": True/False, "provider": "smtp"|"microsoft_graph"|"console", ...}
    """
    from core.email import send_email as _central
    return _central(to=to, subject=subject, body_html=body_html)


# ═════════════════════════════════════════════════════════════════════════
# Branded HTML wrapper
# ═════════════════════════════════════════════════════════════════════════

G = "#1a6b3a"
GL = "#e8f5ee"
APP_URL = lambda: os.getenv("APP_URL", "http://localhost:8000/grid")


def _email_wrap(body: str, preheader: str = "") -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/><style>
body{{margin:0;padding:0;background:#f5f6fa;font-family:'Segoe UI',Arial,sans-serif}}
.wrap{{max-width:580px;margin:32px auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.08)}}
.hdr{{background:{G};padding:28px 32px}}
.logo{{font-size:20px;font-weight:800;color:white;margin:0}}
.sub{{font-size:11px;color:rgba(255,255,255,.75);margin:3px 0 0;font-family:monospace}}
.bdy{{padding:28px 32px}}
.ftr{{background:#f8f9fc;border-top:1px solid #e5e7eb;padding:16px 32px;font-size:11px;color:#9ca3af;text-align:center}}
.btn{{display:inline-block;background:{G};color:white!important;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;margin:14px 0}}
p{{color:#374151;line-height:1.65;margin:0 0 14px}}
h2{{color:#111827;font-size:18px;font-weight:800;margin:0 0 16px}}
hr{{border:none;border-top:1px solid #e5e7eb;margin:18px 0}}
</style></head><body>
<div style="display:none;max-height:0;overflow:hidden">{_esc(preheader)}</div>
<div class="wrap">
  <div class="hdr">
    <p class="logo">G&middot;R&middot;I&middot;D AI</p>
    <p class="sub">Governance &middot; Risk &middot; IT &middot; Data &middot; by Ali Moyo</p>
  </div>
  <div class="bdy">{body}</div>
  <div class="ftr">G.R.I.D AI Compliance Management &middot; Powered by Claude AI</div>
</div></body></html>"""


# ═════════════════════════════════════════════════════════════════════════
# Email templates
# ═════════════════════════════════════════════════════════════════════════

def reminder_email_html(
    *, control_name: str, control_id: str = "", due_date: str = "",
    audit_name: str = "", recipient_name: str = "", frequency: str = "weekly",
) -> str:
    """Evidence reminder — daily/weekly/monthly."""
    from datetime import date
    overdue = bool(due_date and due_date < date.today().isoformat())
    border_col = "#dc2626" if overdue else G
    status_text = f"OVERDUE — was due: {_esc(due_date)}" if overdue else f"Due: {_esc(due_date or 'Not set')}"
    status_col = "#dc2626" if overdue else "#6b7280"

    return _email_wrap(f"""
    <h2>{'&#9888; Overdue Control' if overdue else '&#9200; Evidence Reminder'}</h2>
    <p>Hi {_esc(recipient_name) or 'there'},</p>
    <p>A control item requires your attention:</p>
    <div style="background:#f8f9fc;border-left:4px solid {border_col};border-radius:0 8px 8px 0;padding:16px;margin:16px 0">
      <div style="font-size:11px;color:{G};font-family:monospace;font-weight:700">{_esc(control_id)}</div>
      <div style="font-size:15px;font-weight:700;color:#111827;margin:6px 0">{_esc(control_name)}</div>
      <div style="font-size:12px;color:{status_col}">{status_text}</div>
      <div style="font-size:12px;color:#6b7280;margin-top:4px">Audit: {_esc(audit_name)}</div>
    </div>
    <a href="{APP_URL()}" class="btn">Open G.R.I.D AI</a>
    <hr/><p style="font-size:11px;color:#9ca3af">Receiving {_esc(frequency)} reminders for this control.</p>
    """, f"Action required: {control_name}")


def weekly_digest_html(*, recipient_name: str = "", audits: list[dict] | None = None) -> str:
    """Weekly compliance digest with audit progress table."""
    rows = ""
    for a in (audits or []):
        pct = a.get("completion_pct", 0)
        col = G if pct >= 80 else ("#d97706" if pct >= 40 else "#dc2626")
        overdue = a.get("overdue_controls", 0)
        ov_bg = "#fee2e2" if overdue > 0 else GL
        ov_col = "#991b1b" if overdue > 0 else G
        rows += f"""<tr style="border-bottom:1px solid #e5e7eb">
          <td style="padding:12px 0">
            <div style="font-weight:700;color:#111827">{_esc(a.get('name',''))}</div>
            <div style="font-size:11px;color:#6b7280;font-family:monospace">{_esc(a.get('framework_name',''))} &middot; {_esc(a.get('audit_type',''))}</div>
          </td>
          <td style="text-align:center;padding:12px 8px"><span style="font-size:20px;font-weight:800;color:{col}">{pct}%</span></td>
          <td style="text-align:center;padding:12px 8px;font-family:monospace;font-size:12px">{a.get('complete_controls',0)}/{a.get('total_controls',0)}</td>
          <td style="text-align:center;padding:12px 8px">
            <span style="padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;font-family:monospace;background:{ov_bg};color:{ov_col}">{overdue} overdue</span>
          </td>
        </tr>"""

    from datetime import date
    today_str = date.today().strftime("%d/%m/%Y")

    return _email_wrap(f"""
    <h2>&#128202; Weekly Compliance Digest</h2>
    <p>Hi {_esc(recipient_name) or 'there'}, your compliance summary for the week:</p>
    <table style="width:100%;border-collapse:collapse;margin:16px 0">
      <thead><tr style="border-bottom:2px solid #e5e7eb">
        <th style="text-align:left;padding:8px 0;font-size:11px;color:#6b7280;font-family:monospace;text-transform:uppercase">Audit</th>
        <th style="text-align:center;padding:8px;font-size:11px;color:#6b7280;font-family:monospace;text-transform:uppercase">Progress</th>
        <th style="text-align:center;padding:8px;font-size:11px;color:#6b7280;font-family:monospace;text-transform:uppercase">Controls</th>
        <th style="text-align:center;padding:8px;font-size:11px;color:#6b7280;font-family:monospace;text-transform:uppercase">Status</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <a href="{APP_URL()}" class="btn">Open Dashboard</a>
    """, f"Weekly compliance digest — {today_str}")


def audit_share_html(
    *, auditor_name: str = "", audit_name: str = "", share_url: str = "",
    expires_at: str = "", created_by: str = "",
) -> str:
    """Audit read-only access link."""
    expiry_line = f'<p style="font-size:12px;color:#d97706;font-family:monospace">Access expires: {_esc(expires_at)}</p>' if expires_at else ""
    return _email_wrap(f"""
    <h2>&#128279; Audit Access Granted</h2>
    <p>Hi {_esc(auditor_name) or 'there'},</p>
    <p><strong>{_esc(created_by) or 'G.R.I.D AI'}</strong> has granted you read-only access to: <strong>{_esc(audit_name)}</strong></p>
    {expiry_line}
    <a href="{_esc(share_url)}" class="btn">View Audit</a>
    <hr/><p style="font-size:12px;color:#6b7280">Read-only access. Contact {_esc(created_by)} for write access.</p>
    """, f"Audit access: {audit_name}")


def approval_request_html(
    *, approver_name: str = "", evidence_name: str = "", control_name: str = "",
    uploader_name: str = "", review_url: str = "",
) -> str:
    """Evidence awaiting approval."""
    return _email_wrap(f"""
    <h2>&#128203; Evidence Awaiting Approval</h2>
    <p>Hi {_esc(approver_name) or 'there'},</p>
    <p><strong>{_esc(uploader_name) or 'A team member'}</strong> has uploaded evidence for your review:</p>
    <div style="background:#f8f9fc;border-radius:8px;padding:16px;margin:16px 0;border:1px solid #e5e7eb">
      <div style="font-size:15px;font-weight:700;color:#111827;margin-bottom:6px">{_esc(evidence_name)}</div>
      <div style="font-size:12px;color:#6b7280">For control: <strong>{_esc(control_name)}</strong></div>
    </div>
    <a href="{_esc(review_url) or APP_URL()}" class="btn">Review Evidence</a>
    """, f"Evidence requires approval: {evidence_name}")


def approval_decision_html(
    *, uploader_name: str = "", evidence_name: str = "", decision: str = "",
    comment: str = "", reviewer_name: str = "",
) -> str:
    """Evidence approved / rejected notification."""
    ok = decision == "approved"
    icon = "&#9989; Evidence Approved" if ok else "&#10060; Evidence Rejected"
    col = G if ok else "#dc2626"
    bg = GL if ok else "#fee2e2"
    comment_line = f'<div style="font-size:13px;color:#374151">Comment: {_esc(comment)}</div>' if comment else ""

    return _email_wrap(f"""
    <h2>{icon}</h2>
    <p>Hi {_esc(uploader_name) or 'there'}, your evidence was <strong style="color:{col}">{_esc(decision)}</strong> by {_esc(reviewer_name)}.</p>
    <div style="background:{bg};border-radius:8px;padding:14px;margin:16px 0">
      <div style="font-size:14px;font-weight:700;color:#111827;margin-bottom:6px">{_esc(evidence_name)}</div>
      {comment_line}
    </div>
    <a href="{APP_URL()}" class="btn">Open G.R.I.D AI</a>
    """, f"Evidence {decision}: {evidence_name}")


def escalation_html(
    *, manager_name: str = "", owner_name: str = "", control_name: str = "",
    control_id: str = "", days_overdue: int = 0, audit_name: str = "",
) -> str:
    """Overdue control escalation to manager."""
    return _email_wrap(f"""
    <h2>&#128680; Escalation: Overdue Control</h2>
    <p>Hi {_esc(manager_name) or 'there'}, a control has been overdue for <strong>{days_overdue} days</strong> with no activity:</p>
    <div style="background:#fee2e2;border-left:4px solid #dc2626;border-radius:0 8px 8px 0;padding:16px;margin:16px 0">
      <div style="font-size:11px;color:#dc2626;font-family:monospace;font-weight:700">{_esc(control_id)}</div>
      <div style="font-size:15px;font-weight:700;color:#111827;margin:4px 0">{_esc(control_name)}</div>
      <div style="font-size:12px;color:#6b7280">Assigned to: {_esc(owner_name)} &middot; Audit: {_esc(audit_name)}</div>
    </div>
    <a href="{APP_URL()}" class="btn">View in G.R.I.D AI</a>
    """, f"ESCALATION: {control_name} is {days_overdue} days overdue")


def expiry_alert_html(
    *, recipient_name: str = "", evidence_name: str = "", control_name: str = "",
    expiry_date: str = "", days_until_expiry: int = 0,
) -> str:
    """Evidence expiring soon warning."""
    return _email_wrap(f"""
    <h2>&#9200; Evidence Expiring Soon</h2>
    <p>Hi {_esc(recipient_name) or 'there'}, the following evidence expires in <strong>{days_until_expiry} days</strong>:</p>
    <div style="background:#fef3c7;border-left:4px solid #d97706;border-radius:0 8px 8px 0;padding:16px;margin:16px 0">
      <div style="font-size:15px;font-weight:700;color:#111827;margin-bottom:6px">{_esc(evidence_name)}</div>
      <div style="font-size:12px;color:#6b7280">Control: {_esc(control_name)}</div>
      <div style="font-size:12px;color:#d97706;margin-top:6px;font-family:monospace">Expires: {_esc(expiry_date)}</div>
    </div>
    <a href="{APP_URL()}" class="btn">Update Evidence</a>
    """, f"Evidence expiring in {days_until_expiry} days")


def nc_alert_html(
    *, owner_name: str = "", nc_title: str = "", severity: str = "",
    due_date: str = "", raised_by: str = "", audit_name: str = "",
) -> str:
    """Non-conformance assigned notification."""
    col_map = {"Critical": "#dc2626", "Major": "#d97706"}
    c = col_map.get(severity, "#2563eb")
    due_line = f'<div style="font-size:12px;color:#dc2626;margin-top:4px;font-family:monospace">Due: {_esc(due_date)}</div>' if due_date else ""

    return _email_wrap(f"""
    <h2>&#9888; Non-Conformance Assigned</h2>
    <p>Hi {_esc(owner_name) or 'there'}, a non-conformance has been assigned to you for corrective action:</p>
    <div style="background:#f8f9fc;border-radius:8px;padding:16px;margin:16px 0;border:1px solid #e5e7eb">
      <div style="font-size:15px;font-weight:700;color:#111827;margin-bottom:8px">{_esc(nc_title)}</div>
      <span style="background:{c}22;color:{c};font-size:11px;font-weight:700;padding:3px 9px;border-radius:6px;font-family:monospace">{_esc(severity)}</span>
      <div style="font-size:12px;color:#6b7280;margin-top:10px">Raised by: {_esc(raised_by)} &middot; Audit: {_esc(audit_name)}</div>
      {due_line}
    </div>
    <a href="{APP_URL()}" class="btn">View Non-Conformance</a>
    """, f"NC assigned: {nc_title}")


def nc_deadline_reminder_html(
    *, owner_name: str = "", nc_title: str = "", severity: str = "",
    response_deadline: str = "", days_remaining: int = 0,
    cap_status: str = "", audit_name: str = "",
) -> str:
    """Response deadline approaching for a non-conformance."""
    overdue = days_remaining < 0
    days_abs = abs(days_remaining)
    border = "#dc2626" if overdue else "#d97706"
    status_text = f"OVERDUE by {days_abs} day{'s' if days_abs != 1 else ''}" if overdue else f"{days_abs} day{'s' if days_abs != 1 else ''} remaining"
    status_col = "#dc2626" if overdue else "#d97706"
    heading = "&#128680; NC Response Overdue" if overdue else "&#9200; NC Response Deadline Approaching"

    return _email_wrap(f"""
    <h2>{heading}</h2>
    <p>Hi {_esc(owner_name) or 'there'}, a non-conformance response deadline requires your attention:</p>
    <div style="background:#f8f9fc;border-left:4px solid {border};border-radius:0 8px 8px 0;padding:16px;margin:16px 0">
      <div style="font-size:15px;font-weight:700;color:#111827;margin-bottom:6px">{_esc(nc_title)}</div>
      <div style="font-size:12px;color:{status_col};font-weight:700;margin-bottom:4px">{status_text}</div>
      <div style="font-size:12px;color:#6b7280">Deadline: {_esc(response_deadline)} &middot; CAP Stage: {_esc(cap_status)}</div>
      <div style="font-size:12px;color:#6b7280;margin-top:2px">Audit: {_esc(audit_name)}</div>
    </div>
    <a href="{APP_URL()}" class="btn">Open G.R.I.D AI</a>
    """, f"{'OVERDUE' if overdue else 'Deadline'}: {nc_title}")


def nc_cap_escalation_html(
    *, manager_name: str = "", owner_name: str = "", nc_title: str = "",
    severity: str = "", cap_status: str = "", days_overdue: int = 0,
    audit_name: str = "", due_date: str = "",
) -> str:
    """Overdue CAP escalation to management."""
    return _email_wrap(f"""
    <h2>&#128680; CAP Escalation: Overdue Non-Conformance</h2>
    <p>Hi {_esc(manager_name) or 'there'}, a corrective action plan has been overdue for
    <strong>{days_overdue} day{'s' if days_overdue != 1 else ''}</strong> without resolution:</p>
    <div style="background:#fee2e2;border-left:4px solid #dc2626;border-radius:0 8px 8px 0;padding:16px;margin:16px 0">
      <div style="font-size:15px;font-weight:700;color:#111827;margin-bottom:6px">{_esc(nc_title)}</div>
      <div style="font-size:12px;color:#dc2626;font-weight:700">Severity: {_esc(severity)} &middot; Due: {_esc(due_date)}</div>
      <div style="font-size:12px;color:#6b7280;margin-top:4px">Assigned to: {_esc(owner_name)} &middot; CAP Stage: {_esc(cap_status)}</div>
      <div style="font-size:12px;color:#6b7280;margin-top:2px">Audit: {_esc(audit_name)}</div>
    </div>
    <a href="{APP_URL()}" class="btn">View in G.R.I.D AI</a>
    """, f"ESCALATION: {nc_title} — {days_overdue} days overdue")
