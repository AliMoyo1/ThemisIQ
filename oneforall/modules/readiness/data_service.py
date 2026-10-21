"""
PLAN-36 P04: data-readiness and integrity centre -- rule engine, findings
storage, and acknowledge/suppress/export operations.

Design (task_plan.md P04's own "Selected design"):
  - Rules are deterministic, versioned (rule_code), and read-only by default.
  - Every issue carries code, severity, module, scoped record reference,
    explanation, detected time, and a remediation link.
  - No generic Auto Fix performs broad mutation; acknowledge/suppress only
    ever changes a finding's own row, never the record it points at.

Rules are plain read-only functions -- no new workflow engine, no new
draft/version/queue table (P04's own discovery-gate line). Each takes
(db, org_id) and returns a list of RawFinding; run_rules_for_org() persists
them into readiness_findings, reconciling (never duplicating) against
whatever is already open for that org, and auto-resolving findings that no
longer reproduce.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from core.timeutils import utcnow
from core.best_effort import swallowed


@dataclass(frozen=True)
class RawFinding:
    """What a rule function returns -- everything except org_id/timestamps,
    which run_rules_for_org() fills in (a rule only ever sees one org's
    data, via the tenant_context binding its caller already set up)."""
    rule_code: str
    severity: str          # 'critical' | 'high' | 'medium' | 'low'
    module: str
    entity_type: str
    entity_id: str
    message: str
    business_unit_id: int | None = None
    remediation_route: str | None = None


_RULES: dict[str, "callable"] = {}
_RULE_MODULES: dict[str, str | None] = {}


def register_rule(rule_code: str, module: str | None = None):
    """Decorator: adds a rule function to the registry under rule_code.
    modules/readiness/rules.py uses this on import; run_rules_for_org()
    iterates the registry rather than a hardcoded list, so adding a rule
    there is the only change needed to wire it in."""
    def _wrap(fn):
        _RULES[rule_code] = fn
        _RULE_MODULES[rule_code] = module
        return fn
    return _wrap


def _ensure_rules_imported():
    import modules.readiness.rules  # noqa: F401  (populates _RULES on import)


def _licensed_modules(db, org_id: int) -> set[str] | None:
    row = db.execute(
        "SELECT module_keys,valid_until FROM licenses WHERE org_id=%s "
        "ORDER BY id DESC LIMIT 1", (org_id,),
    ).fetchone()
    if not row or not row["module_keys"]:
        return None
    if row["valid_until"] and str(row["valid_until"]) < utcnow().isoformat():
        return set()
    return {part.strip() for part in row["module_keys"].split(",") if part.strip()}


def get_rule_coverage(db, org_id: int) -> list[dict]:
    """Show why a licensed module was not inspected, even with zero findings."""
    _ensure_rules_imported()
    licensed = _licensed_modules(db, org_id)
    return [
        {"rule_code": code, "module": module,
         "state": ("skipped_unlicensed"
                   if module in {"aria", "grid", "bcm", "sentinel", "erm", "orm"}
                   and licensed is not None and module not in licensed
                   else "eligible")}
        for code, module in _RULE_MODULES.items()
    ]


def run_rules_for_org(db, org_id: int) -> dict:
    """Runs every registered rule against this org's own data (caller is
    responsible for tenant_context already being bound, same as every other
    per-tenant scheduler job in this codebase), reconciles the results into
    readiness_findings, and returns {"new": n, "updated": n, "resolved": n}.

    Reconciliation: a finding not reproduced this run, that was still
    'open', is marked 'resolved' -- the record it was about presumably got
    fixed. An 'acknowledged' or 'suppressed' finding that stops reproducing
    is left alone (a human decision about a since-fixed issue is still a
    real decision worth keeping in history, not silently erased); one that
    is STILL reproducing after its suppression expires (suppressed_until in
    the past) reverts to 'open' so it surfaces again."""
    _ensure_rules_imported()
    now = utcnow().isoformat()
    seen_keys: set[tuple[str, str, str]] = set()
    counts = {"new": 0, "updated": 0, "resolved": 0, "skipped": 0, "failed_rules": []}
    licensed = _licensed_modules(db, org_id)
    checked_rules: set[str] = set()

    for rule_code, rule_fn in _RULES.items():
        module = _RULE_MODULES.get(rule_code)
        if (module in {"aria", "grid", "bcm", "sentinel", "erm", "orm"}
                and licensed is not None and module not in licensed):
            counts["skipped"] += 1
            continue
        db.execute("SAVEPOINT readiness_rule")
        try:
            raw_findings = rule_fn(db, org_id)
            db.execute("RELEASE SAVEPOINT readiness_rule")
            checked_rules.add(rule_code)
        except Exception:
            swallowed(f"readiness rule {rule_code}")
            db.execute("ROLLBACK TO SAVEPOINT readiness_rule")
            db.execute("RELEASE SAVEPOINT readiness_rule")
            counts["skipped"] += 1
            counts["failed_rules"].append(rule_code)
            continue  # never auto-resolve a finding for a rule we could not run
        for f in raw_findings:
            seen_keys.add((f.rule_code, f.entity_type, f.entity_id))
            existing = db.execute(
                "SELECT id, status, suppressed_until FROM readiness_findings "
                "WHERE org_id=%s AND rule_code=%s AND entity_type=%s AND entity_id=%s",
                (org_id, f.rule_code, f.entity_type, f.entity_id),
            ).fetchone()
            if existing is None:
                db.execute(
                    "INSERT INTO readiness_findings "
                    "(org_id, business_unit_id, rule_code, severity, module, entity_type, "
                    "entity_id, message, remediation_route, status, detected_at, last_seen_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',%s,%s)",
                    (org_id, f.business_unit_id, f.rule_code, f.severity, f.module,
                     f.entity_type, f.entity_id, f.message, f.remediation_route, now, now),
                )
                counts["new"] += 1
            else:
                existing = dict(existing)
                new_status = existing["status"]
                if existing["status"] == "resolved":
                    new_status = "open"  # reproduced again after being fixed once
                elif (existing["status"] == "suppressed" and existing["suppressed_until"]
                      and existing["suppressed_until"] < now):
                    new_status = "open"
                db.execute(
                    "UPDATE readiness_findings SET severity=%s, message=%s, "
                    "business_unit_id=%s, remediation_route=%s, status=%s, "
                    "last_seen_at=%s, resolved_at=NULL WHERE id=%s",
                    (f.severity, f.message, f.business_unit_id, f.remediation_route,
                     new_status, now, existing["id"]),
                )
                counts["updated"] += 1

    open_rows = db.execute(
        "SELECT id, rule_code, entity_type, entity_id FROM readiness_findings "
        "WHERE org_id=%s AND status='open'", (org_id,),
    ).fetchall()
    for row in open_rows:
        key = (row["rule_code"], row["entity_type"], row["entity_id"])
        if row["rule_code"] in checked_rules and key not in seen_keys:
            db.execute(
                "UPDATE readiness_findings SET status='resolved', resolved_at=%s WHERE id=%s",
                (now, row["id"]),
            )
            counts["resolved"] += 1

    db.commit()
    return counts


def list_findings(db, org_id: int, *, module: str | None = None,
                   severity: str | None = None, status: str | None = None) -> list[dict]:
    q = "SELECT * FROM readiness_findings WHERE org_id=%s"
    params: list = [org_id]
    if module:
        q += " AND module=%s"
        params.append(module)
    if severity:
        q += " AND severity=%s"
        params.append(severity)
    if status:
        q += " AND status=%s"
        params.append(status)
    else:
        q += " AND status != 'resolved'"
    q += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 " \
         "WHEN 'medium' THEN 2 ELSE 3 END, detected_at DESC"
    return [dict(r) for r in db.execute(q, params).fetchall()]


def _get_org_scoped_finding(db, org_id: int, finding_id: int) -> dict | None:
    """Fail-closed scoped lookup (same convention as every other module's
    _scoped_* helper): returns None for both 'does not exist' and 'exists
    but belongs to another org', so a 404 never confirms another tenant's
    finding id is real."""
    row = db.execute(
        "SELECT * FROM readiness_findings WHERE id=%s AND org_id=%s", (finding_id, org_id),
    ).fetchone()
    return dict(row) if row else None


def acknowledge_finding(db, org_id: int, finding_id: int, actor: dict, reason: str,
                         expires_at: str | None = None) -> dict | None:
    """status='acknowledged' (reason required, no expiry -- a human decided
    this is fine) or status='suppressed' (reason + expiry -- fine for now,
    surface again after expires_at). Never touches the entity the finding
    is about; only this finding row changes (P04's own 'no generic Auto
    Fix performs broad mutation' rule)."""
    finding = _get_org_scoped_finding(db, org_id, finding_id)
    if finding is None:
        return None
    if not (reason or "").strip():
        raise ValueError("A reason is required to acknowledge or suppress a finding.")
    now = utcnow().isoformat()
    status = "suppressed" if expires_at else "acknowledged"
    db.execute(
        "UPDATE readiness_findings SET status=%s, acknowledged_by=%s, acknowledged_reason=%s, "
        "acknowledged_at=%s, suppressed_until=%s WHERE id=%s",
        (status, actor["id"], reason.strip(), now, expires_at, finding_id),
    )
    db.commit()
    return _get_org_scoped_finding(db, org_id, finding_id)


def reopen_finding(db, org_id: int, finding_id: int) -> dict | None:
    """Undo an acknowledge/suppress -- a human can decide a finding matters
    again before its own suppression would have expired."""
    finding = _get_org_scoped_finding(db, org_id, finding_id)
    if finding is None:
        return None
    db.execute(
        "UPDATE readiness_findings SET status='open', acknowledged_by=NULL, "
        "acknowledged_reason=NULL, acknowledged_at=NULL, suppressed_until=NULL WHERE id=%s",
        (finding_id,),
    )
    db.commit()
    return _get_org_scoped_finding(db, org_id, finding_id)


def export_findings_csv(db, org_id: int, **filters) -> str:
    """CSV export -- entity references and messages only, matching P04's
    'export without sensitive content' acceptance line. A finding's
    message is generated by the rule itself from non-sensitive metadata
    (ids, dates, column names), never a record's own free-text content."""
    findings = list_findings(db, org_id, **filters)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["rule_code", "severity", "module", "entity_type", "entity_id",
                      "message", "status", "detected_at", "last_seen_at"])
    for f in findings:
        writer.writerow([f["rule_code"], f["severity"], f["module"], f["entity_type"],
                          f["entity_id"], f["message"], f["status"], f["detected_at"],
                          f["last_seen_at"]])
    return buf.getvalue()
