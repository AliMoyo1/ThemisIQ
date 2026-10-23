"""
The Governance (ARIA) controls register as a workbook on the shared report kit.

One sheet per active framework with every control and its document, owner, status and dates; a summary sheet with the status
chart and the implemented share of each framework, built from the same counts as the sheets (the same part that builds the
Compliance Summary report, so the two cannot count differently); a cover sheet; and print settings. Text is stored as text:
a control named like a formula is shown as it is written and never evaluated.
"""
from core.report_kit import theme
from core.report_kit.model import Actor, Col, Heading, Kpis, Meta, Report, Table
from core.timeutils import utcnow

COLUMNS = [Col("Ref", "ref", weight=1), Col("Control", "name", weight=3), Col("Category", "category", weight=2),
           Col("Document type", "doc_type", weight=1.2), Col("Document title", "document_title", weight=3),
           Col("Owner", "owner", weight=1.5), Col("Status", "status", weight=1.3), Col("Priority", "priority", weight=1),
           Col("Target date", "target_date", weight=1.2, kind="date"), Col("Review date", "review_date", weight=1.2, kind="date"),
           Col("Version", "version", weight=0.8), Col("Notes", "notes", weight=3)]


def controls_report(db, user, org_name="") -> Report:
    from modules.launcher.report_documents import _part_compliance      # the same figures and charts as the Compliance Summary

    frameworks = db.execute("SELECT id, name FROM frameworks WHERE is_active = 1 ORDER BY name").fetchall()
    tables, by_framework, by_status = [], [], {}
    for framework in frameworks:
        rows = [dict(r) for r in db.execute("SELECT * FROM controls WHERE framework_id = %s ORDER BY ref", (framework["id"],)).fetchall()]
        done = sum(1 for r in rows if r.get("status") == "Implemented")
        by_framework.append({"name": framework["name"], "total": len(rows), "ok": done or None})
        for row in rows:
            key = row.get("status") or "none"
            by_status[key] = by_status.get(key, 0) + 1
        tables.append(Table(f"{framework['name']}: {len(rows)} controls", COLUMNS, rows, sheet_name=framework["name"],
                            empty_text="This framework has no controls."))
    total = sum(by_status.values())
    implemented = by_status.get("Implemented", 0)
    result = {"total_controls": total, "compliant": implemented,
              "non_compliant": sum(v for k, v in by_status.items() if k in ("Not Started", "Not Implemented")),
              "partial": sum(v for k, v in by_status.items() if k in ("In Progress", "Partially Implemented")),
              "by_status": by_status, "by_framework": by_framework}
    part = _part_compliance(result, compact=False)
    now = utcnow()
    meta = Meta(title="Controls register", module="aria", tier=theme.OPERATIONAL, org_name=org_name,
                subtitle="Every control of every active framework, with its document, owner and status",
                scope="Whole organization (controls are not tied to a business unit)",
                period=f"As of {now.day} {now.strftime('%b %Y')}", generated_at=now, generated_by=Actor.of_user(user))
    report = Report(meta)
    report.add(Heading("Headline measures"), Kpis(part.kpis), Heading("At a glance"), *part.charts)
    report.add(*part.tables)
    report.add(*tables)
    return report
