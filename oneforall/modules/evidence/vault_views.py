"""Virtual Vault folders over canonical evidence and authorized source records.

Folders never move or duplicate a file. Every query retains Evidence Vault scope;
record folders additionally apply the owning module's scope and capability.
"""
from modules.evidence.scope import current_library_sql, evidence_scope_sql
from modules.governance.entity_scope import describe_records, entity_scope_sql


FOLDERS = {
    "audits": ("Audits", (("grid", "audit"),)),
    "incidents": ("Incidents", (("bcm", "incident"), ("sentinel", "breach"), ("orm", "event"))),
    "privacy": ("Privacy records", (("sentinel", "ropa"), ("sentinel", "dpia"))),
    "plans": ("Continuity plans", (("bcm", "plan"),)),
    "ai": ("AI assessments", (("sentinel", "aiia"),)),
    "reports": ("Reports", ()),
    "policies": ("Policies", ()),
    "generated": ("Generated records", ()),
}
CATEGORIES = {"policies": "policy", "generated": "generated_record"}
REPORT_TYPES = {
    "report": "Other reports",
    "audit_completion": "Audit completion",
    "control_assessment": "Control assessments",
    "risk_assessment": "Risk assessments",
    "incident_record": "Incident reports",
    "breach_record": "Breach reports",
}


def folder_sql(folder, user, db):
    """Return a scoped predicate for a folder, or a masked 404 for a bad record folder."""
    if not folder:
        return "(1 = 1)", []
    parts = str(folder).split(":")
    group = parts[0]
    if group not in FOLDERS:
        raise ValueError("Folder not found")
    if group == "reports":
        if len(parts) == 1:
            marks = ",".join(["%s"] * len(REPORT_TYPES))
            return f"e.category IN ({marks})", list(REPORT_TYPES)
        if len(parts) == 3 and parts[1] == "type" and parts[2] in REPORT_TYPES:
            return "e.category = %s", [parts[2]]
        raise ValueError("Folder not found")
    if len(parts) == 1 and group in CATEGORIES:
        return "e.category = %s", [CATEGORIES[group]]
    keys = FOLDERS[group][1]
    if not keys or len(parts) not in (1, 4) or (len(parts) == 4 and parts[0] != group):
        raise ValueError("Folder not found")
    selected = keys
    record_id = None
    if len(parts) == 4:
        key = (parts[1], parts[2])
        if key not in keys or not parts[3].isdigit() or int(parts[3]) < 1:
            raise ValueError("Folder not found")
        record_id = int(parts[3])
        if not describe_records(db, key, [record_id], user):
            raise ValueError("Folder not found")
        selected = (key,)
    clauses, params = [], []
    for module, kind in selected:
        scope, scope_params = entity_scope_sql((module, kind), user, "t")
        # The registered table comes only from the server-side kind registry.
        from modules.governance.entity_scope import _KINDS
        table = _KINDS[(module, kind)].table
        condition = (" AND t.id = %s" if record_id is not None else "")
        clauses.append(
            "EXISTS (SELECT 1 FROM evidence_links el "
            f"JOIN {table} t ON t.id = el.entity_id "
            "WHERE el.evidence_id = e.id AND el.deleted_at IS NULL "
            f"AND el.module = %s AND el.entity_type = %s AND {scope}{condition})"
        )
        params.extend((module, kind, *scope_params))
        if record_id is not None:
            params.append(record_id)
    return "(" + " OR ".join(clauses) + ")", params


def folder_counts(db, user):
    scope, scope_params = evidence_scope_sql(user)
    counts = []
    for key, (title, _) in FOLDERS.items():
        predicate, params = folder_sql(key, user, db)
        count = db.execute(
            f"SELECT COUNT(*) FROM evidence_items e WHERE {scope} AND {current_library_sql()} AND {predicate}",
            [*scope_params, *params],
        ).fetchone()[0]
        counts.append({"key": key, "title": title, "count": count, "has_records": key not in CATEGORIES})
    return counts


def record_folders(db, user, group, page=1, query="", page_size=24):
    """Page the named source records that have visible current files; no hidden titles or counts."""
    if group == "reports":
        scope, params = evidence_scope_sql(user)
        found = []
        for category, title in REPORT_TYPES.items():
            count = db.execute(
                f"SELECT COUNT(*) FROM evidence_items e WHERE {scope} AND {current_library_sql()} AND e.category=%s",
                [*params, category],
            ).fetchone()[0]
            if count:
                found.append({"key": f"reports:type:{category}", "title": title, "count": count, "module": "reports"})
        needle = str(query or "").strip().casefold()[:100]
        found = [item for item in found if needle in item["title"].casefold()]
        return {"items": found, "total": len(found), "page": 1, "pages": 1}
    if group not in FOLDERS or not FOLDERS[group][1]:
        raise ValueError("Folder not found")
    scope, scope_params = evidence_scope_sql(user)
    found = []
    for module, kind in FOLDERS[group][1]:
        rows = db.execute(
            "SELECT el.entity_id, COUNT(DISTINCT e.id) AS file_count "
            "FROM evidence_links el JOIN evidence_items e ON e.id = el.evidence_id "
            f"WHERE {scope} AND {current_library_sql()} AND el.deleted_at IS NULL "
            "AND el.module = %s AND el.entity_type = %s GROUP BY el.entity_id ORDER BY el.entity_id DESC",
            [*scope_params, module, kind],
        ).fetchall()
        numbers = [row["entity_id"] for row in rows]
        counts = {row["entity_id"]: row["file_count"] for row in rows}
        for offset in range(0, len(numbers), 300):
            named = describe_records(db, (module, kind), numbers[offset:offset + 300], user)
            for record_id, record in named.items():
                key = f"{group}:{module}:{kind}:{record_id}"
                found.append({"key": key, "title": record["title"], "count": counts[record_id], "module": module})
    needle = str(query or "").strip().casefold()[:100]
    if needle:
        found = [item for item in found if needle in item["title"].casefold()]
    found.sort(key=lambda item: (item["title"].casefold(), item["key"]))
    total = len(found)
    page = min(max(1, int(page)), max(1, -(-total // page_size)))
    return {"items": found[(page - 1) * page_size:page * page_size], "total": total,
            "page": page, "pages": max(1, -(-total // page_size))}
