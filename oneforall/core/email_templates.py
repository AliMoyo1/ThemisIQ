"""
The catalogue of messages ThemisIQ sends by email (plans/2026-10-governance-rework/06 section 5).

A message is a template key plus structured fields. It is never HTML that a caller wrote. Each template declares its
version, who receives it, its priority, the fields it needs, the routes it may link to and the most sensitive thing it may
say. The renderer escapes every field, produces a plain text part that carries the same information as the HTML part, and
builds its one link from the configured HTTPS origin plus a relative route that the template allows.

What a message never carries: a token, a password, a document, the text of a narrative, a data subject's name, or the
title of a record. It carries a reference, the kind of action, a due date and a link to the record in ThemisIQ, where the
person's own access decides what they see.
"""
import html
import re
from dataclasses import dataclass
from datetime import datetime

SUBJECT_PREFIX = "ThemisIQ: "

# Priority decides how a message is sent and what may postpone it (06 section 3).
CRITICAL, ACTION, INFO, OPERATOR = "critical", "action", "info", "operator"

# What a person is told an action is, in words a template may use. A kind outside this list is refused, so a free text
# title cannot reach a message through it.
ACTION_KINDS = {
    "ai_use_review": "An AI use review",
    "ai_decision": "An AI use decision",
    "corrective_action": "A corrective action",
    "evidence_review": "A piece of evidence",
    "task": "A task",
    "control_review": "A control review",
}

# A reference is a code (AU-27, BRE-2026-001): no spaces, so a title or a sentence is not one.
_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#\-]{0,39}$")

# Numbers a template may state: a count of things, hours left, items overdue.
_NUMBERS = ("count", "hours", "audits", "overdue", "minutes")
_FIELDS_IN_LEADS = ("kind", "reference", "due", "due_sentence", "hours", "hours_sentence", "minutes_sentence", *_NUMBERS)


class TemplateError(ValueError):
    """The fields given do not satisfy the template. The message is safe to log."""


@dataclass(frozen=True)
class Template:
    key: str
    version: int
    priority: str
    recipient: str            # who it goes to, in words, for the catalogue page
    subject: str              # fixed text: a subject never carries a field
    lead: str                 # first paragraph, with {field} placeholders
    fields: tuple             # required fields
    optional: tuple           # optional fields
    routes: tuple             # allowed route prefixes
    cta: str                  # the one call to action
    why: str                  # why the person received it
    sensitivity: str = "reference only"


TEMPLATES = {t.key: t for t in (
    Template(
        "action.assigned", 1, ACTION, "The named person an action is assigned to",
        "an action is assigned to you",
        "{kind} is assigned to you. Reference: {reference}.{due_sentence} Open it in ThemisIQ to see what is needed.",
        ("kind", "reference"), ("due",), ("/my-work", "/ai-governance/", "/grid/", "/tasks", "/evidence/", "/aria/"),
        "Open it in ThemisIQ", "it is assigned to you"),
    Template(
        "tasks.assigned", 1, ACTION, "The person several tasks were assigned to at once",
        "tasks are assigned to you",
        "{count} task(s) are assigned to you. Open the task board in ThemisIQ to see what is needed.",
        ("count",), (), ("/tasks",), "Open the task board", "tasks were assigned to you"),
    Template(
        "decision.ready", 1, ACTION, "The independent decider named for the case",
        "an AI use decision is ready for you",
        "The review brief for {reference} is ready.{due_sentence} Confirm the evidence and record your decision in "
        "ThemisIQ. This message is a request for a decision, not a decision.",
        ("reference",), ("due",), ("/ai-governance/",), "Open the decision", "you are the named decider"),
    Template(
        "evidence.renew", 1, ACTION, "The owner of an evidence item",
        "evidence needs review",
        "Evidence {reference} needs review by {due}. Open the current version in ThemisIQ and record your decision.",
        ("reference", "due"), (), ("/evidence/", "/grid/"), "Open the evidence", "you own this evidence"),
    Template(
        "audit.finding", 1, ACTION, "The person a corrective action is assigned to",
        "a corrective action is assigned to you",
        "A corrective action for audit {reference} is assigned to you.{due_sentence} Open the finding in ThemisIQ to "
        "see the response that is required.",
        ("reference",), ("due",), ("/grid/",), "Open the finding", "a corrective action was assigned to you"),
    Template(
        "audit.deadline", 1, ACTION, "The person a finding is assigned to",
        "a finding response is due",
        "The response to a finding on audit {reference} is due.{due_sentence} Open the finding in ThemisIQ to update "
        "the corrective action plan.",
        ("reference",), ("due",), ("/grid/",), "Open the finding", "a finding is assigned to you"),
    Template(
        "audit.escalation", 1, ACTION, "The audit lead, or an administrator of the organization when there is none",
        "an overdue audit item needs attention",
        "An item on audit {reference} that is assigned to someone you answer for is overdue.{due_sentence} Open it in "
        "ThemisIQ to see who owns it and what is outstanding.",
        ("reference",), ("due",), ("/grid/",), "Open the item", "you lead this audit or administer this organization"),
    Template(
        "control.reminder", 1, ACTION, "The person who asked to be reminded of a control",
        "a control needs your attention",
        "A control on audit {reference} needs your attention.{due_sentence} Open it in ThemisIQ to add the evidence.",
        ("reference",), ("due",), ("/grid/",), "Open the control", "you asked to be reminded of this control"),
    Template(
        "privacy.deadline", 2, CRITICAL, "The privacy officer named for the organization",
        "a privacy case needs review",
        "A privacy case needs attention. Reference: {reference}. Its recorded review target is "
        "{due}.{hours_sentence} Open the case in ThemisIQ to confirm the applicable rule, trigger and notice decision.",
        ("reference", "due"), ("hours",), ("/sentinel/",), "Open the case",
        "you are named as a privacy officer for this organization"),
    Template(
        "privacy.dsr", 2, CRITICAL, "The privacy officer named for the organization",
        "a data subject request needs review",
        "A data subject request has a recorded review target of {due}. Reference: {reference}. Open it in ThemisIQ "
        "to confirm the legal response period and see what is outstanding.",
        ("reference", "due"), (), ("/sentinel/",), "Open the request",
        "you are named as a privacy officer for this organization"),
    Template(
        "summary.weekly", 1, INFO, "A subscriber who can open the audits it counts",
        "your weekly audit summary",
        "You have {audits} audit(s) in your scope and {overdue} overdue control(s). The counts are those you can open: "
        "the audit list in ThemisIQ shows exactly which.",
        ("audits", "overdue"), (), ("/grid/",), "Open the audits", "you subscribed to the weekly audit summary"),
    Template(
        "bcm.exercise", 1, ACTION, "The person who owns the continuity exercise",
        "a continuity exercise is coming up",
        "A continuity exercise you own is scheduled for {due}. Reference: {reference}. Open it in ThemisIQ to confirm "
        "readiness and participants.",
        ("reference", "due"), (), ("/bcm/",), "Open the exercise", "you own this exercise"),
    Template(
        "bcm.incident", 2, CRITICAL, "The incident commander named on the incident",
        "you are named incident commander",
        "You are named as incident commander for incident {reference}.{minutes_sentence} Open it in ThemisIQ to see "
        "what is needed and keep the response updated.",
        ("reference",), ("minutes",), ("/bcm/",), "Open the incident", "you are the named incident commander"),
    Template(
        "bcm.escalation", 1, CRITICAL, "The BCM managers who can open the incident",
        "an incident has not been acknowledged",
        "Nobody acknowledged incident {reference} within {minutes} minutes. Open it in ThemisIQ to take it over or to "
        "name a commander.",
        ("reference", "minutes"), (), ("/bcm/",), "Open the incident", "you are a BCM manager who can open this incident"),
    Template(
        "summary.mywork", 1, INFO, "A person who asked for a daily or weekly summary of what needs them",
        "your summary of what needs you",
        "You have {count} item(s) that need you, {overdue} of them overdue. These are the counts My Work shows you: "
        "open it to see exactly which.",
        ("count", "overdue"), (), ("/my-work",), "Open My Work", "you asked for a summary of what needs you"),
    Template(
        "delivery.failure", 1, OPERATOR, "An administrator who may manage email",
        "notification delivery needs attention",
        "{count} notification(s) could not be accepted by the mail provider. Open the delivery queue in ThemisIQ and "
        "follow the contact runbook for critical items.",
        ("count",), (), ("/admin/email",), "Open the delivery queue", "you manage email for this organization"),
)}


def get(key: str) -> Template:
    try:
        return TEMPLATES[key]
    except KeyError:
        raise TemplateError(f"Unknown template {key!r}") from None


def reference_or(value, fallback: str) -> str:
    """`value` when it is a short code a message may carry, else `fallback`. A producer passes the record's own
    reference and the code it would have had (AU-27) so that a free-text reference never stops a message."""
    text = str(value or "").strip()
    return text if _REFERENCE.match(text) else fallback


def iso_or_none(value) -> "str | None":
    """The date part of a stored value when it is an ISO date, else None, so a template leaves the due date out
    rather than refusing the message."""
    text = str(value or "").strip()
    try:
        datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return text[:10]


def _date_words(value) -> str:
    """"23 Oct 2026" for a date, "14 Oct 2026, 16:00 UTC" for a date with a time (the platform stores UTC)."""
    text = str(value or "").strip().replace("T", " ")
    try:
        if len(text) > 10:
            moment = datetime.strptime(text[:16], "%Y-%m-%d %H:%M")
            return moment.strftime("%d %b %Y, %H:%M UTC").lstrip("0")
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%d %b %Y").lstrip("0")
    except ValueError:
        raise TemplateError("A due date must be an ISO date") from None


def clean_fields(template: Template, fields: dict) -> dict:
    """The fields a template may use, checked and shortened. Raises TemplateError when one is missing or not allowed."""
    fields = dict(fields or {})
    unknown = sorted(set(fields) - set(template.fields) - set(template.optional))
    if unknown:
        raise TemplateError(f"{template.key} does not take {', '.join(unknown)}")
    out = {}
    for name in template.fields:
        if fields.get(name) in (None, ""):
            raise TemplateError(f"{template.key} needs {name}")
    for name in (*template.fields, *template.optional):
        value = fields.get(name)
        if value in (None, ""):
            continue
        if name == "kind":
            if value not in ACTION_KINDS:
                raise TemplateError("Unknown action kind")
            out[name] = ACTION_KINDS[value]
        elif name == "reference":
            text = str(value).strip()
            if not _REFERENCE.match(text):
                raise TemplateError("A reference must be a short code, not free text")
            out[name] = text
        elif name == "due":
            out[name] = _date_words(value)
        elif name in _NUMBERS:
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise TemplateError(f"{name} must be a whole number") from None
            if not 0 <= number <= 100000:
                raise TemplateError(f"{name} is out of range")
            out[name] = str(number)
        else:
            raise TemplateError(f"Field {name} is not allowed")
    out["due_sentence"] = f" Due: {out['due']}." if out.get("due") else ""
    hours = out.get("hours")
    out["hours_sentence"] = (f" About {hours} hour(s) remained when this message was sent."
                             if hours not in (None, "") else "")
    minutes = out.get("minutes")
    out["minutes_sentence"] = (f" Acknowledge it in ThemisIQ within {minutes} minutes."
                               if minutes not in (None, "") else "")
    return out


def route_allowed(template: Template, route: str) -> bool:
    return (isinstance(route, str) and route.startswith("/") and not route.startswith("//")
            and "\\" not in route and not any(ord(c) < 32 for c in route)
            and any(route.startswith(p) for p in template.routes))


def render(template_key: str, fields: dict, route: str, origin: str, *, preferences_route: str = "") -> dict:
    """{"subject", "text", "html", "link"} for one message.

    `origin` is the configured HTTPS origin (core.email.app_origin) or "". Without it the message carries no link and says
    where to find the item, so a missing configuration never produces a dead or a relative link."""
    template = get(template_key)
    values = clean_fields(template, fields)
    if not route_allowed(template, route):
        raise TemplateError("That route is not allowed for this template")
    link = f"{origin}{route}" if origin else ""
    lead = template.lead.format(**{k: values.get(k, "") for k in _FIELDS_IN_LEADS})
    lead = " ".join(lead.split())
    subject = SUBJECT_PREFIX + template.subject
    footer = f"You received this because {template.why}."
    lines = [lead, ""]
    if link:
        lines += [f"{template.cta}: {link}", ""]
    else:
        lines += ["Sign in to ThemisIQ and open My Work to find it.", ""]
    lines += [footer, "This is an operational message from ThemisIQ. Do not reply to it."]
    text = "\n".join(lines)

    esc = html.escape
    button = (f'<p><a href="{esc(link, quote=True)}" style="display:inline-block;background:#1e3a8a;color:#ffffff;'
              f'padding:10px 18px;border-radius:6px;text-decoration:none;font-weight:600">{esc(template.cta)}</a></p>'
              f'<p style="font-size:12px;color:#475569">{esc(link)}</p>') if link else (
        '<p>Sign in to ThemisIQ and open My Work to find it.</p>')
    body = (
        '<div style="font-family:Segoe UI,Arial,sans-serif;max-width:560px;margin:0 auto;padding:20px;color:#1e293b">'
        '<div style="font-size:12px;font-weight:700;letter-spacing:.06em;color:#64748b">THEMISIQ</div>'
        f'<p style="font-size:15px;line-height:1.6">{esc(lead)}</p>{button}'
        f'<p style="font-size:12px;color:#64748b;border-top:1px solid #e2e8f0;padding-top:10px">{esc(footer)} '
        'This is an operational message from ThemisIQ. Do not reply to it.</p></div>')
    return {"subject": subject, "text": text, "html": body, "link": link, "template": template.key,
            "version": template.version}
