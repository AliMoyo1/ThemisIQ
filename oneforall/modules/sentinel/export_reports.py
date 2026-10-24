"""
The Privacy (Sentinel) reports on the shared report kit: the record of processing activities and the breach register
(operational reports), and the privacy compliance score (the board report).

Every figure is counted from the same records the tables list. The lists are read once, through the caller's own business
unit scope and without the 500 row ceiling the screens use, and the score is `data_service.get_compliance_score`, the function
the Sentinel page calls, so a report and the page cannot score differently. The wording is about what is recorded: the
platform states no legal conclusion about a notification deadline or a lawful basis, and neither does a report.
"""
from collections import Counter
from datetime import date

from core.report_kit import identity, theme
from core.rbac import has_capability
from core.report_kit.helpers import ROWS_IN_DOCUMENT, by_count, empty, label, leader, severity_rows
from core.report_kit.model import Callout, Chart, Col, Heading, Kpi, Kpis, Paragraphs, Report, Table
from core.timeutils import utcnow
from modules.governance.data_service import bu_scope_ids
from modules.launcher import report_documents as documents
from modules.sentinel import data_service as ds
from modules.sentinel.record_profiles import get_profile
from modules.sentinel.record_profiles.model import flat_text

EVERYTHING = 1_000_000                       # the lists default to 500 rows; a report states every record in scope
# core.metric_registry.BREACH_ACTIVE and the data subject request rule of the dashboard, in Python: any other status is open.
BREACH_DONE = ("closed", "resolved")
DSR_DONE = ("completed", "closed")
HIGH = ("high", "critical")
WORKFLOW = ["open", "reported", "investigating", "contained", "resolved", "closed"]

INDICATIVE = ("Notification deadlines in this report are indicative: they count from the recorded discovery date by the rule "
              "configured for each regulation. A privacy specialist confirms the legal trigger and the obligation.")


def _flag(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes")


def _day(value) -> str:
    return str(value or "")[:10]


def _list(value) -> str:
    return ", ".join(str(v) for v in value) if isinstance(value, (list, tuple)) else (str(value) if value else "")


def _share(part, whole):
    return identity.pct(part, whole) if whole else None


def _top_share(rows, total, what) -> str:
    """The sentence under a bar chart of a free text field: the largest group and its share, in words."""
    if not rows or not total:
        return ""
    name, count = rows[0]
    share = _share(count, total)
    if name == "Not recorded":
        return f"No {what} is recorded for {identity.fmt_int(count)} of {identity.fmt_int(total)} activities ({share}%)."
    return leader(rows, total, "group", "activity", noun_plural="activities")


# ── The record of processing activities ─────────────────────────────────────

def ropa_figures(rows, today) -> dict:
    """The counts the RoPA report states, from the records it lists. The first four are the rules the compliance score and
    the RoPA page use (a record is complete with a purpose, a legal basis and a data category; it needs a DPIA when it is rated
    high or critical or marked as needing one)."""
    needs = [r for r in rows if r.get("risk_level") in HIGH or _flag(r.get("dpia_required"))]
    return {
        "total": len(rows),
        "incomplete": sum(1 for r in rows if not (r.get("purpose") and r.get("legal_basis") and r.get("data_categories"))),
        "needs_dpia": len(needs),
        "has_dpia": sum(1 for r in needs if r.get("dpia_id")),
        "high": sum(1 for r in rows if r.get("risk_level") in HIGH),
        "special": sum(1 for r in rows if r.get("special_categories")),
        "review_overdue": sum(1 for r in rows if r.get("review_date") and _day(r["review_date"]) < today),
        "by_basis": Counter(r.get("legal_basis") for r in rows),
        "by_risk": Counter(r.get("risk_level") for r in rows),
        "by_department": Counter(r.get("department") for r in rows),
    }


def _dpia_text(row) -> str:
    if row.get("risk_level") in HIGH or _flag(row.get("dpia_required")):
        return "On file" if row.get("dpia_id") else "Still to do"
    return "Not required"


def _ropa_table_row(r) -> dict:
    profile = get_profile("ropa", r.get("regulation"))
    made, needed = profile.completeness(r)
    out = {
        "ref": r.get("ref_number"), "name": r.get("processing_name"), "department": r.get("department"),
        "regulation": r.get("regulation"), "legal_basis": r.get("legal_basis"),
        "data_categories": _list(r.get("data_categories")) or None,
        "risk": label(r.get("risk_level")) if r.get("risk_level") else None, "dpia": _dpia_text(r),
        "status": label(r.get("status")) if r.get("status") else None, "review": r.get("review_date"),
        "owner": r.get("owner"), "purpose": r.get("purpose"), "data_subjects": r.get("data_subjects"),
        "subject_count": r.get("subject_count"), "special": _list(r.get("special_categories")) or None,
        "recipients": _list(r.get("recipients")) or None, "processors": _list(r.get("processors")) or None,
        "systems": r.get("systems"), "retention": r.get("retention_period"), "transfers": r.get("intl_transfers"),
        "transfer_dest": r.get("transfer_dest"), "safeguard": r.get("transfer_safeguard"),
        "security": _list(r.get("security_measures")) or None, "notes": r.get("notes"),
        "readiness": f"{made}/{needed}", "gap_count": len(profile.gaps(r)),
        "legal_status": profile.regime["status"], "controller_role": r.get("controller_role"),
    }
    for field in profile.fields():
        if field.store == "details":
            value = r.get(field.key)
            out["detail_" + field.key] = ("Yes" if value in (True, 1) else "No") if field.kind == "bool" and value is not None else flat_text(value)
    return out


# The PDF table has seven columns so that the Ref column can hold the widest reference (ROPA-YYYYMMDD-XXXXX, W for every letter, 19 characters)
# on one line: a reference split across two lines cannot be read or copied. The department is in the chart and in every workbook row.
ROPA_COLUMNS = [Col("Ref", "ref", weight=3.0), Col("Processing activity", "name", weight=2.5), Col("Legal basis", "legal_basis", weight=1.7),
                Col("Data categories", "data_categories", weight=1.9), Col("Risk", "risk", weight=1.15), Col("DPIA", "dpia", weight=1.15),
                Col("Next review", "review", weight=1.3, kind="date")]
PROCESSOR_COLUMNS = [Col("Ref", "ref", weight=2.6), Col("Processing activity", "name", weight=2.3),
                     Col("Controller served", "acts_for", weight=2.0), Col("Processing categories", "categories", weight=2.8),
                     Col("Transfers", "transfers", weight=1.5), Col("Review", "review", weight=1.3, kind="date")]
ROPA_SHEET_COLUMNS = [
    Col("Ref", "ref"), Col("Processing activity", "name"), Col("Department", "department"), Col("Owner", "owner"),
    Col("Regulation", "regulation"), Col("Purpose", "purpose"), Col("Legal basis", "legal_basis"),
    Col("Data categories", "data_categories"), Col("Special category data", "special"), Col("Data subjects", "data_subjects"),
    Col("Approximate subject count", "subject_count"), Col("Recipients", "recipients"), Col("Processors", "processors"),
    Col("Systems", "systems"), Col("Retention", "retention"), Col("International transfers", "transfers"),
    Col("Transfer destination", "transfer_dest"), Col("Transfer safeguard", "safeguard"), Col("Security measures", "security"),
    Col("Risk", "risk"), Col("DPIA", "dpia"), Col("Status", "status"), Col("Next review", "review", kind="date"), Col("Notes", "notes"),
    Col("Readiness", "readiness"), Col("Open fields", "gap_count", kind="int"), Col("Legal wording status", "legal_status"),
    *[Col(get_profile("ropa").label(field), "detail_" + field.key)
      for field in get_profile("ropa").fields() if field.store == "details"]]


def ropa_report(user) -> Report:
    now = utcnow()
    rows = sorted(ds.list_ropa(bu_scope=bu_scope_ids(user), limit=None),
                  key=lambda r: (str(r.get("processing_name") or "").lower(), str(r.get("ref_number") or "")))
    settings = ds.get_all_settings() or {}
    fig = ropa_figures(rows, now.strftime("%Y-%m-%d"))
    controller_rows = [r for r in rows if r.get("controller_role") != "processor"]
    processor_rows = [r for r in rows if r.get("controller_role") == "processor"]
    total, gap = fig["total"], fig["needs_dpia"] - fig["has_dpia"]
    report = Report(documents.module_meta(user, "sentinel", "Record of processing activities",
                          "The register of processing: legal basis, data, retention and risk", theme.OPERATIONAL, now))

    held = [f"{what}: {settings[key]}" for what, key in (("Controller", "org_name"), ("Primary regulation", "primary_regulation"))
            if settings.get(key)]
    dpo = " ".join(part for part in (f"Data protection officer: {settings['dpo_name']}." if settings.get("dpo_name") else "",
                                     f"Contact: {settings['dpo_email']}." if settings.get("dpo_email") else "") if part)
    lines = [line for line in ("; ".join(held), dpo) if line]
    report.add(Paragraphs("Controller and data protection officer",
                          lines or ["No controller or data protection officer is recorded in the Sentinel settings."]))
    if has_capability(user, "sentinel.controller.manage"):
        controllers = ds.list_controllers(limit=EVERYTHING)
        report.add(Table("Recorded controller and processor identities",
                         [Col("Organisation", "name"), Col("Role", "role"), Col("Contact", "contact"),
                          Col("Agreement", "agreement")],
                         [{"name": c.get("org_name"), "role": label(c.get("role")),
                           "contact": c.get("controller_email") or c.get("contact_email") or c.get("dpo_email"),
                           "agreement": c.get("agreement_ref")} for c in controllers],
                         empty_text="No controller or processor identity is recorded.", sheet_name="Organisations"))
    report.add(Callout("Legal wording status", [
        "The jurisdiction references and completeness prompts are researched but have not been approved for filing.",
        "Completeness is a count of answered profile fields, not an automated legal conclusion.",
        "A privacy specialist must confirm the selected regime, identity, contents and legal references before external use.",
    ], kind="limit"))
    report.add(Heading("Headline measures"), Kpis([
        Kpi("Processing activities", identity.fmt_int(total)),
        Kpi("Controller entries", identity.fmt_int(len(controller_rows))),
        Kpi("Processor entries", identity.fmt_int(len(processor_rows))),
        Kpi("High or critical risk", identity.fmt_int(fig["high"]), f"{_share(fig['high'], total)}% of activities" if total else "", "warn" if fig["high"] else "neutral"),
        Kpi("DPIA still to do", identity.fmt_int(gap), f"of {identity.fmt_int(fig['needs_dpia'])} that need one", "bad" if gap else "neutral"),
        Kpi("Incomplete records", identity.fmt_int(fig["incomplete"]), "no purpose, legal basis or data category", "warn" if fig["incomplete"] else "neutral"),
        Kpi("Special category data", identity.fmt_int(fig["special"]), "activities that process it"),
        Kpi("Review overdue", identity.fmt_int(fig["review_overdue"]), "past the next review date", "warn" if fig["review_overdue"] else "neutral"),
    ]))

    basis = by_count(fig["by_basis"], limit=8)
    risk_rows, risk_colours = severity_rows(fig["by_risk"])
    department = by_count(fig["by_department"], limit=8, other="Other departments")
    report.add(Heading("At a glance"),
               Chart("bar", "Processing activities by legal basis", basis, x_label="Number of processing activities", y_label="Legal basis",
                     unit="activities", half=True, takeaway=_top_share(basis, total, "legal basis"),
                     empty_text=empty("No processing activity is recorded.")),
               Chart("bar", "Processing activities by risk level", risk_rows, x_label="Number of processing activities", y_label="Risk level",
                     unit="activities", half=True, colours=risk_colours,
                     takeaway=(f"{identity.fmt_int(fig['high'])} of {identity.fmt_int(total)} activities ({_share(fig['high'], total)}%) are "
                               "rated high or critical." if total else ""), empty_text=empty("No processing activity is recorded.")),
               Chart("bar", "Processing activities by department", department, x_label="Number of processing activities", y_label="Department",
                     unit="activities", half=True, takeaway=_top_share(department, total, "department"),
                     empty_text=empty("No processing activity is recorded.")),
               Chart("donut", "DPIA position of the activities that need one",
                     [("DPIA on file", fig["has_dpia"]), ("DPIA still to do", gap)], unit="activities", half=True,
                     centre=f"{_share(fig['has_dpia'], fig['needs_dpia'])}%" if fig["needs_dpia"] else "",
                     takeaway=(f"{identity.fmt_int(fig['has_dpia'])} of {identity.fmt_int(fig['needs_dpia'])} activities that need a DPIA have one "
                               f"on file ({_share(fig['has_dpia'], fig['needs_dpia'])}%)." if fig["needs_dpia"] else ""),
                     empty_text=empty("No activity is rated high or critical or marked as needing a DPIA.")))

    needs = []
    if gap:
        needs.append(f"{identity.plural(gap, 'activity that needs', 'activities that need')} a DPIA and "
                     f"{'has' if gap == 1 else 'have'} none on file: agree an owner and a date for each.")
    if fig["incomplete"]:
        needs.append(f"{identity.plural(fig['incomplete'], 'record')} without a purpose, a legal basis or a data category: complete "
                     f"{'it' if fig['incomplete'] == 1 else 'them'}.")
    if fig["review_overdue"]:
        needs.append(f"{identity.plural(fig['review_overdue'], 'record')} past the next review date: schedule the review.")
    if needs:
        report.add(Callout("Needs attention", needs, kind="decision"))

    report.add(Heading("Controller register"), Table(
        f"Controller activities: {identity.fmt_int(len(controller_rows))}", ROPA_COLUMNS, [_ropa_table_row(r) for r in controller_rows],
        empty_text="No processing activity is recorded in the records open to you.",
        sheet_name="Controller register", sheet_columns=ROPA_SHEET_COLUMNS))
    report.add(Heading("Processor register"), Table(
        f"Processor activities: {identity.fmt_int(len(processor_rows))}", PROCESSOR_COLUMNS,
        [{**_ropa_table_row(r), "acts_for": r.get("acts_for"), "categories": r.get("processing_categories")}
         for r in processor_rows],
        empty_text="No processor activity is recorded in your scope.",
        sheet_name="Processor register", sheet_columns=ROPA_SHEET_COLUMNS))
    report.add(Table("Record readiness and missing answers",
                     [Col("Ref", "ref", weight=2), Col("Role", "role"), Col("Answered", "readiness"),
                      Col("Open fields", "gaps", weight=4)],
                     [{"ref": r.get("ref_number"), "role": r.get("controller_role") or "controller (not confirmed)",
                       "readiness": _ropa_table_row(r)["readiness"],
                       "gaps": "; ".join(gap.label for gap in get_profile("ropa", r.get("regulation")).gaps(r)) or "None"}
                      for r in rows],
                     empty_text="No processing activity is recorded in your scope.", sheet_name="Readiness"))
    for r in rows:
        profile = get_profile("ropa", r.get("regulation"))
        gaps = profile.gaps(r)
        def shown(key):
            return flat_text(r.get(key)) or "Not recorded"
        report.add(Paragraphs(f"{shown('ref_number')} · {shown('processing_name')}", [
            f"Role: {shown('controller_role')}. Owner: {shown('owner')}. Review due: {shown('review_date')}.",
            f"Jurisdiction: {profile.regime['name']} ({profile.regime['status']}). "
            f"Purpose: {shown('purpose')}. Lawful basis: {shown('legal_basis')}.",
            f"People: {shown('data_subjects')}. Data: {shown('data_categories')}. "
            f"Recipients: {shown('recipients')}.",
            f"Processor/controller relationship: {shown('acts_for')}. Processing categories: {shown('processing_categories')}.",
            f"Transfers: {shown('intl_transfers')}. Destination: {shown('transfer_dest')}. "
            f"Safeguard: {shown('transfer_safeguard')}.",
            f"Retention: {shown('retention_period')}. Security: {shown('security_measures')}.",
            f"Open profile fields ({len(gaps)}): {'; '.join(gap.label for gap in gaps) or 'none recorded as blank'}. "
            "The specialist must verify the content and jurisdiction before external use.",
        ]))
    return report


# ── The breach register ─────────────────────────────────────────────────────

def _months(now, count=12) -> list:
    """The last `count` calendar months ending with this one, oldest first, as (YYYY-MM, label)."""
    year, month, out = now.year, now.month, []
    for _ in range(count):
        out.append((f"{year:04d}-{month:02d}", date(year, month, 1).strftime("%b %Y")))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out[::-1]


def breach_figures(rows, now) -> dict:
    active = [b for b in rows if b.get("status") not in BREACH_DONE]
    required = [b for b in rows if _flag(b.get("notification_required"))]
    outstanding = [b for b in required if not _flag(b.get("authority_notified"))]
    counted = [b["affected_count"] for b in rows if b.get("affected_count") is not None]
    keys = [key for key, _ in _months(now)]
    monthly = Counter(_day(b.get("discovery_date"))[:7] for b in rows)
    return {
        "total": len(rows), "active": len(active),
        "active_high": sum(1 for b in active if str(b.get("severity") or "").lower() in HIGH),
        "affected": sum(counted) if counted else None, "affected_from": len(counted),
        "required": len(required), "outstanding": len(outstanding),
        "past_deadline": sum(1 for b in outstanding if b.get("notify_deadline")
                             and identity.to_utc(b["notify_deadline"]) and identity.to_utc(b["notify_deadline"]) < now),
        "no_discovery": sum(1 for b in rows if not b.get("discovery_date")),
        "notified": sum(1 for b in required if _flag(b.get("authority_notified"))),
        "not_required": len(rows) - len(required),
        "by_severity": Counter(str(b.get("severity") or "").lower() for b in rows),
        "by_status": Counter(b.get("status") for b in rows),
        "last_year": sum(monthly.get(key, 0) for key in keys), "monthly": monthly,
    }


def _authority_text(b) -> str:
    if _flag(b.get("authority_notified")):
        return "Yes" + (f", {identity.format_day(b['authority_notify_date'])}" if b.get("authority_notify_date") else "")
    return "Not yet" if _flag(b.get("notification_required")) else "Not marked as required"


def _breach_table_row(b) -> dict:
    clock = b.get("clock") or {}
    return {
        "ref": b.get("ref_number"), "title": b.get("title"), "severity": label(b.get("severity")) if b.get("severity") else None,
        "status": label(b.get("status")) if b.get("status") else None, "discovered": b.get("discovery_date"),
        "affected": b.get("affected_count"), "authority": _authority_text(b), "deadline": b.get("notify_deadline"),
        "regulation": b.get("regulation"), "incident": b.get("incident_date"), "type": b.get("breach_type"),
        "data_types": _list(b.get("data_types")) or None, "description": b.get("description"), "root_cause": b.get("root_cause"),
        "containment": b.get("containment"), "remediation": b.get("remediation"),
        "required": "Yes" if _flag(b.get("notification_required")) else "No", "authority_ref": b.get("authority_ref"),
        "subjects": "Yes" if _flag(b.get("subjects_notified")) else "No", "subjects_on": b.get("subjects_notify_date"),
        "lessons": b.get("lessons_learned"), "basis": clock.get("label"),
    }


# Seven columns for the same reason as the RoPA table (BRE-YYYYMMDD-XXXXX): the people affected are a headline measure above and a workbook column.
BREACH_COLUMNS = [Col("Ref", "ref", weight=2.8), Col("Breach", "title", weight=2.2), Col("Severity", "severity", weight=1.15),
                  Col("Status", "status", weight=1.5), Col("Discovered", "discovered", weight=1.45, kind="date"),
                  Col("Authority notified", "authority", weight=1.5), Col("Indicative deadline", "deadline", weight=1.4, kind="date")]
BREACH_SHEET_COLUMNS = [
    Col("Ref", "ref"), Col("Breach", "title"), Col("Regulation", "regulation"), Col("Severity", "severity"), Col("Status", "status"),
    Col("Type", "type"), Col("Incident date", "incident", kind="date"), Col("Discovered", "discovered", kind="date"),
    Col("Affected individuals", "affected", "right", kind="int"), Col("Data types", "data_types"), Col("Description", "description"),
    Col("Root cause", "root_cause"), Col("Containment", "containment"), Col("Remediation", "remediation"),
    Col("Notification required", "required"), Col("Authority notified", "authority"), Col("Authority reference", "authority_ref"),
    Col("Indicative deadline", "deadline", kind="date"), Col("Deadline basis", "basis"), Col("Individuals notified", "subjects"),
    Col("Individuals notified on", "subjects_on", kind="date"), Col("Lessons learned", "lessons")]


def breach_report(user) -> Report:
    now = utcnow()
    rows = sorted(ds.list_breaches(bu_scope=bu_scope_ids(user), limit=EVERYTHING),
                  key=lambda b: (_day(b.get("discovery_date")) or "0000", str(b.get("ref_number") or "")), reverse=True)
    fig = breach_figures(rows, now)
    total = fig["total"]
    report = Report(documents.module_meta(user, "sentinel", "Breach register", "Every recorded personal data breach, its severity, status and notification position",
                          theme.OPERATIONAL, now))
    affected = identity.fmt_int(fig["affected"]) if fig["affected"] is not None else "n/a"
    report.add(Heading("Headline measures"), Kpis([
        Kpi("Breaches recorded", identity.fmt_int(total)),
        Kpi("Active", identity.fmt_int(fig["active"]), "not resolved or closed", "bad" if fig["active"] else "neutral"),
        Kpi("Active, critical or high", identity.fmt_int(fig["active_high"]), "", "bad" if fig["active_high"] else "neutral"),
        Kpi("People affected", affected, f"from {identity.plural(fig['affected_from'], 'breach', 'breaches')} with a recorded count"
            if fig["affected_from"] else "no breach has a recorded count"),
        Kpi("Authority not yet notified", identity.fmt_int(fig["outstanding"]), "marked as requiring notification",
            "bad" if fig["outstanding"] else "neutral"),
    ]))

    severity_rows_, colours = severity_rows(fig["by_severity"])
    status_rows = sorted(((label(k), v) for k, v in fig["by_status"].items() if v),
                         key=lambda r: (WORKFLOW.index(r[0].lower()) if r[0].lower() in WORKFLOW else len(WORKFLOW), r[0]))
    months = _months(now)
    report.add(Heading("At a glance"),
               Chart("bar", "Breaches by severity", severity_rows_, x_label="Number of breaches", y_label="Severity", unit="breaches",
                     half=True, colours=colours, empty_text=empty("No breach is recorded."),
                     takeaway=(f"{identity.fmt_int(fig['active_high'])} of {identity.fmt_int(fig['active'])} active breaches are critical or high."
                               if fig["active"] else "No breach is active.") if total else ""),
               Chart("bar", "Breaches by status", status_rows, x_label="Number of breaches", y_label="Status", unit="breaches", half=True,
                     takeaway=(f"{identity.fmt_int(fig['active'])} of {identity.fmt_int(total)} breaches are still active." if total else ""),
                     empty_text=empty("No breach is recorded.")),
               Chart("line", "Breaches by month of discovery",
                     [(name, fig["monthly"].get(key, 0)) for key, name in months], x_label="Month of discovery, last 12 months", y_label="Number of breaches",
                     unit="breaches", half=True,
                     takeaway=(f"{identity.fmt_int(fig['last_year'])} of {identity.fmt_int(total)} breaches were discovered in the last 12 months."
                               + (f" {identity.plural(fig['no_discovery'], 'breach has', 'breaches have')} no discovery date and "
                                  f"{'is' if fig['no_discovery'] == 1 else 'are'} not in this chart." if fig["no_discovery"] else "")) if total else "",
                     empty_text=empty("No breach was discovered in the last 12 months.")),
               Chart("donut", "Notification position of breaches that require it",
                     [("Notified to the authority", fig["notified"]), ("Authority not yet notified", fig["outstanding"])],
                     unit="breaches", half=True, centre=f"{_share(fig['notified'], fig['required'])}%" if fig["required"] else "",
                     takeaway=(f"{identity.fmt_int(fig['notified'])} of {identity.fmt_int(fig['required'])} breaches marked as requiring "
                               "notification are recorded as notified to the authority."
                               + (f" {identity.plural(fig['not_required'], 'other breach is', 'other breaches are')} not marked as requiring "
                                  "notification." if fig["not_required"] else "")) if fig["required"] else "",
                     empty_text=empty("No breach is marked as requiring notification.")))

    needs = []
    if fig["active_high"]:
        needs.append(f"{identity.plural(fig['active_high'], 'active breach is', 'active breaches are')} critical or high: confirm who leads "
                     f"{'it' if fig['active_high'] == 1 else 'each'}.")
    if fig["outstanding"]:
        needs.append(f"{identity.plural(fig['outstanding'], 'breach is', 'breaches are')} marked as requiring notification with no "
                     f"notification to the authority recorded: confirm the position with the privacy specialist.")
    if fig["past_deadline"]:
        needs.append(f"{identity.plural(fig['past_deadline'], 'of these is', 'of these are')} past the indicative deadline recorded for "
                     f"{'it' if fig['past_deadline'] == 1 else 'them'}.")
    if fig["no_discovery"]:
        needs.append(f"{identity.plural(fig['no_discovery'], 'breach has', 'breaches have')} no discovery date, so no notification deadline is counted.")
    if needs:
        report.add(Callout("Needs attention", needs, kind="decision"))
    report.add(Callout("How to read the deadlines", [INDICATIVE], kind="limit"))

    report.add(Heading("Register"), Table(
        f"Breaches, most recently discovered first: {identity.fmt_int(total)}", BREACH_COLUMNS, [_breach_table_row(b) for b in rows],
        max_rows=ROWS_IN_DOCUMENT, more_in_excel=True, empty_text="No breach is recorded in the records open to you.",
        sheet_name="Breaches", sheet_columns=BREACH_SHEET_COLUMNS))
    return report


# ── The privacy compliance score (the board report) ─────────────────────────

PART_RULES = {
    "ropa_completeness": "Processing records with a purpose, a legal basis and a data category",
    "dpia_coverage": "Processing records rated high or critical, or needing a DPIA, that have one on file",
    "breach_response": "Breaches that are contained, resolved or closed",
    "dsr_closure": "Data subject requests that are completed or closed",
    "vendor_compliance": "Vendors with an active, signed, executed or compliant data processing agreement",
}
GRADE_TONE = {"A": "good", "B": "good", "C": "warn", "D": "bad", "F": "bad"}


def score_report(user) -> Report:
    now = utcnow()
    scope = bu_scope_ids(user)
    score = ds.get_compliance_score(bu_scope=scope)
    breaches = ds.list_breaches(bu_scope=scope, limit=EVERYTHING)
    dsrs = ds.list_dsrs(bu_scope=scope, limit=EVERYTHING)
    today = now.strftime("%Y-%m-%d")
    parts, overall, grade = score["breakdown"], score["overall"], score["grade"]
    measured = {k: p for k, p in parts.items() if p["score"] is not None}
    active = sum(1 for b in breaches if b.get("status") not in BREACH_DONE)
    open_dsr = [d for d in dsrs if d.get("status") not in DSR_DONE]
    overdue = sum(1 for d in open_dsr if d.get("deadline_date") and _day(d["deadline_date"]) < today)
    dpia_gap = parts["dpia_coverage"]["total"] - parts["dpia_coverage"]["done"]
    incomplete = parts["ropa_completeness"]["total"] - parts["ropa_completeness"]["done"]
    no_dpa = parts["vendor_compliance"]["total"] - parts["vendor_compliance"]["done"]

    report = Report(documents.module_meta(user, "sentinel", "Privacy compliance score", "For the board: the score, what it is made of and what needs a decision",
                          theme.BOARD, now))
    report.add(Heading("Headline measures"), Kpis([
        Kpi("Overall score", f"{overall}%" if overall is not None else "Not measured",
            (f"Grade {grade}. {len(measured)} of {len(parts)} parts measured." if overall is not None
             else "nothing is recorded to measure"), GRADE_TONE.get(grade, "neutral")),
        Kpi("Active breaches", identity.fmt_int(active), "not resolved or closed", "bad" if active else "neutral"),
        Kpi("Open data subject requests", identity.fmt_int(len(open_dsr)), f"{identity.fmt_int(overdue)} past their deadline",
            "warn" if open_dsr else "neutral"),
        Kpi("DPIAs still to do", identity.fmt_int(dpia_gap), "high risk activities with none on file", "bad" if dpia_gap else "neutral"),
    ]))

    bars = sorted(((p["label"], p["score"]) for p in measured.values()), key=lambda r: (-r[1], r[0]))
    stack = [(p["label"], [("Done", p["done"]), ("Still to do", p["total"] - p["done"])]) for p in measured.values()]
    actions = [("Active breaches", active), ("Open data subject requests", len(open_dsr)), ("Requests past their deadline", overdue),
               ("High risk activities with no DPIA", dpia_gap), ("Records missing purpose, basis or category", incomplete),
               ("Vendors without an active DPA", no_dpa)]
    biggest = max(actions, key=lambda r: r[1])
    report.add(Heading("At a glance"),
               Chart("bar", "Score by part", bars, unit="%", max_value=100, x_label="Score, percent", y_label="Part of the score", half=True,
                     takeaway=(f"Lowest: {bars[-1][0]} at {bars[-1][1]}%. Highest: {bars[0][0]} at {bars[0][1]}%." if len(bars) > 1 else
                               f"{bars[0][0]} is the only part measured, at {bars[0][1]}%." if bars else ""),
                     empty_text=empty("No part of the score has records to measure.")),
               Chart("stack", "Records behind each part: done and still to do", stack, x_label="Number of records", y_label="Part of the score",
                     half=True, colours=[theme.GRAPHITE, theme.SILVER],
                     takeaway=(f"{identity.fmt_int(sum(p['done'] for p in measured.values()))} of "
                               f"{identity.fmt_int(sum(p['total'] for p in measured.values()))} records are done." if measured else ""),
                     empty_text=empty("No part of the score has records to measure.")),
               Chart("bar", "Items that need action", actions, unit="items", x_label="Number of items", y_label="Kind of item",
                     takeaway=(f"{identity.fmt_int(sum(v for _, v in actions))} items need action; the largest group is "
                               f"{biggest[0].lower()} ({identity.fmt_int(biggest[1])})." if biggest[1] else ""),
                     empty_text="Nothing needs action: no breach, request, DPIA or record gap is open."))

    decisions = []
    if overall is None:
        decisions.append("No part of the score could be measured: record processing activities, breaches, requests and vendors first.")
    if active:
        decisions.append(f"{identity.plural(active, 'active breach', 'active breaches')}: confirm the response and the notification position.")
    if overdue:
        decisions.append(f"{identity.plural(overdue, 'data subject request')} past the deadline: agree how they are cleared.")
    if dpia_gap:
        decisions.append(f"{identity.plural(dpia_gap, 'high risk activity', 'high risk activities')} with no DPIA on file: agree an owner and a date.")
    if no_dpa:
        decisions.append(f"{identity.plural(no_dpa, 'vendor')} without an active data processing agreement: agree the remedy.")
    if decisions:
        report.add(Callout("Decisions for the board", decisions, kind="decision"))

    weight = sum(p["weight"] for p in measured.values())
    rows = [{"part": p["label"], "counts": PART_RULES.get(key, ""), "done": p["done"], "total": p["total"],
             "score": p["score"], "weight": p["weight"],
             "in": "Yes" if p["score"] is not None else "No: nothing recorded"} for key, p in parts.items()]
    report.add(Heading("How the score is made"), Table(
        "The five parts and their weights", [Col("Part", "part", weight=1.6), Col("What it counts", "counts", weight=3.4),
                                             Col("Done", "done", "right", 0.7, "int"), Col("Total", "total", "right", 0.7, "int"),
                                             Col("Score", "score", "right", 0.8, "pct"), Col("Weight", "weight", "right", 0.8, "pct"),
                                             Col("In the overall", "in", weight=1.4)], rows,
        note=("The overall score is the weighted average of the parts that were measured; the weights of the others are left out "
              f"and the rest are scaled to 100%. Weights measured: {weight} of {sum(p['weight'] for p in parts.values())}."),
        sheet_name="Score parts"))
    report.add(Callout("What this score is", [
        "It counts what is recorded in Privacy. It is not a legal finding and it does not replace the privacy specialist's judgement.",
        "A part with nothing recorded is shown as not measured. It is not counted as 100%."], kind="limit"))
    return report


# kind -> (builder, capability that opens the same records on screen, file name stem)
REPORTS = {
    "ropa": (ropa_report, "module.sentinel.access", "ThemisIQ_privacy_ropa"),
    "breach": (breach_report, "sentinel.breach.manage", "ThemisIQ_privacy_breach_register"),
    "compliance": (score_report, "module.sentinel.access", "ThemisIQ_privacy_compliance_score"),
}
