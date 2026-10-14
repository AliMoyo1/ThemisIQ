"""
Evidence Vault: the assurance inspector (plans/2026-10-governance-rework/02 sections 4 and 6).

A deterministic set of checks that name concrete defects in what the Vault holds, each with the rule that found it, why it
matters and where to put it right. It reads through the caller's own scope, changes nothing, and never says a file is fine:
a file with no finding has no known defect, which is not the same as being sufficient. A model plays no part in it.

Rules (version `i1`):

  no_owner              a current file nobody answers for
  expired_in_use        a file past its expiry date that still supports claims, which no longer count as current proof
  claims_not_carried    a new version that does not support claims the version it replaced supported
  returned_link         a reviewer returned or rejected the link to a claim, so that claim has no proof from this file
  review_waiting        a link has waited a long time for a reviewer
  period_ended          the file describes a period that ended more than a year ago, yet supports claims
  no_review_date        a file that supports claims with neither a review date nor an expiry
  similar_title         two current files with the same title: possibly revisions of one document (a suggestion only)
"""
import re

from modules.evidence import proof
from modules.evidence.scope import current_library_sql, evidence_scope_sql
from modules.governance.entity_scope import canonical_key, describe_records

RULE_VERSION = "i1"
LIMIT_SCANNED = 2000
WAIT_DAYS = 30
RULES = {
    "no_owner": ("No owner", "warning"),
    "expired_in_use": ("Expired but still in use", "error"),
    "claims_not_carried": ("A new version leaves claims behind", "warning"),
    "returned_link": ("A reviewer turned a link down", "error"),
    "review_waiting": ("Waiting a long time for a reviewer", "warning"),
    "period_ended": ("Covers a period that ended long ago", "warning"),
    "no_review_date": ("Nobody is asked to look at it again", "info"),
    "similar_title": ("May be two versions of one document", "suggestion"),
}
_ORDER = {"error": 0, "warning": 1, "info": 2, "suggestion": 3}


def _normal(title) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def _finding(rule, item, why, fix, **extra) -> dict:
    label, severity = RULES[rule]
    return {"rule": rule, "rule_version": RULE_VERSION, "severity": severity, "title": label, "why": why, "fix": fix,
            "evidence_id": item["id"], "evidence_title": item["title"], **extra}


def _claims(db, user, links) -> list:
    """Titles of the claims the caller may open among `links` (rows with module, entity_type, entity_id)."""
    wanted = {}
    for r in links:
        wanted.setdefault(canonical_key(r["module"], r["entity_type"]), set()).add(r["entity_id"])
    named = []
    for key, ids in wanted.items():
        named += [v["title"] for v in describe_records(db, key, sorted(ids), user).values()]
    return sorted(set(named))


def inspect(db, user: dict, *, evidence_id: int = None, rule: str = None, limit: int = 200) -> dict:
    """Findings for the files the caller may open, most serious first; or for one file when `evidence_id` is given."""
    scope_sql, scope_params = evidence_scope_sql(user)
    today = proof.today()
    where = [scope_sql, current_library_sql()]
    params = list(scope_params)
    if evidence_id is not None:
        where.append("e.id = %s")
        params.append(int(evidence_id))
    rows = db.execute(
        "SELECT e.id, e.title, e.owner_user_id, e.expiry_date, e.review_due_date, e.period_end, e.parent_id, e.status "
        f"FROM evidence_items e WHERE {' AND '.join(where)} ORDER BY e.id LIMIT %s", [*params, LIMIT_SCANNED]).fetchall()
    ids = [r["id"] for r in rows]
    links = {}
    if ids:
        marks = ",".join(["%s"] * len(ids))
        for r in db.execute(
                "SELECT id, evidence_id, module, entity_type, entity_id, review_status, review_note, created_at, reviewed_at "
                f"FROM evidence_links WHERE evidence_id IN ({marks}) AND deleted_at IS NULL ORDER BY id", ids).fetchall():
            links.setdefault(r["evidence_id"], []).append(r)
    findings = []
    for item in rows:
        mine = links.get(item["id"], [])
        active = [l for l in mine if (l["review_status"] or "pending") != "out_of_scope"]
        pending = [l for l in active if (l["review_status"] or "pending") == "pending"]
        returned = [l for l in active if (l["review_status"] or "pending") in ("returned", "rejected")]
        if not item["owner_user_id"]:
            findings.append(_finding("no_owner", item, "Nobody is named as answerable for this file.",
                                     {"label": "Name an owner", "action": "owner"}))
        if proof.expired(item["expiry_date"], today) and active:
            findings.append(_finding(
                "expired_in_use", item,
                f"It expired on {str(item['expiry_date'])[:10]} and still supports {len(active)} claim(s), which no longer "
                "count as current proof.", {"label": "Add a new version", "action": "version"},
                claims=_claims(db, user, active)))
        for link in returned:
            when = str(link["reviewed_at"] or "")[:10]
            findings.append(_finding(
                "returned_link", item,
                f"A reviewer {'returned' if link['review_status'] == 'returned' else 'rejected'} the link to a claim"
                + (f" on {when}" if when else "") + (f": {link['review_note']}" if link["review_note"] else "."),
                {"label": "Open the file", "action": "open"}, claims=_claims(db, user, [link])))
        old = [l for l in pending if l["created_at"] and str(l["created_at"])[:10] <= _days_before(today, WAIT_DAYS)]
        if old:
            findings.append(_finding("review_waiting", item,
                                     f"{len(old)} link(s) have waited more than {WAIT_DAYS} days for a reviewer.",
                                     {"label": "Open the file", "action": "open"}, claims=_claims(db, user, old)))
        if item["period_end"] and active and str(item["period_end"])[:10] <= _days_before(today, 365):
            findings.append(_finding("period_ended", item,
                                     f"It describes a period that ended on {str(item['period_end'])[:10]}.",
                                     {"label": "Add a new version", "action": "version"}))
        if active and not item["review_due_date"] and not item["expiry_date"]:
            findings.append(_finding("no_review_date", item,
                                     "It supports claims, and it has neither a review date nor an expiry date.",
                                     {"label": "Set a review date", "action": "review_due_date"}))
    # A new version that does not support what the one it replaced supported.
    heads = [r for r in rows if r["parent_id"]]
    if heads:
        parents = {r["parent_id"] for r in heads}
        marks = ",".join(["%s"] * len(parents))
        earlier = {}
        for r in db.execute(
                "SELECT evidence_id, module, entity_type, entity_id FROM evidence_links "
                f"WHERE evidence_id IN ({marks}) AND deleted_at IS NULL", sorted(parents)).fetchall():
            earlier.setdefault(r["evidence_id"], []).append(r)
        for item in heads:
            have = {(l["module"], l["entity_type"], l["entity_id"]) for l in links.get(item["id"], [])}
            missing = [l for l in earlier.get(item["parent_id"], []) if (l["module"], l["entity_type"], l["entity_id"]) not in have]
            if missing:
                findings.append(_finding(
                    "claims_not_carried", item,
                    f"The version it replaced supported {len(missing)} claim(s) that this version does not.",
                    {"label": "See what changed", "action": "versions"}, claims=_claims(db, user, missing)))
    # Two current files with the same title are possibly one document in two uploads. For one file, look at the others.
    pool = rows
    if evidence_id is not None and rows:
        pool = list(rows) + db.execute(
            "SELECT e.id, e.title, e.owner_user_id, e.expiry_date, e.review_due_date, e.period_end, e.parent_id, e.status "
            f"FROM evidence_items e WHERE {scope_sql} AND {current_library_sql()} AND e.id != %s "
            "AND LOWER(e.title) = LOWER(%s) LIMIT 20", [*scope_params, int(evidence_id), rows[0]["title"]]).fetchall()
    by_title = {}
    for item in pool:
        key = _normal(item["title"])
        if key:
            by_title.setdefault(key, []).append(item)
    wanted = set(ids)
    for group in by_title.values():
        if len(group) > 1:
            for item in group:
                if item["id"] not in wanted:
                    continue
                others = [g["title"] for g in group if g["id"] != item["id"]]
                findings.append(_finding("similar_title", item,
                                         f"{len(others)} other current file(s) have the same title. They may be versions of "
                                         "one document; nothing is merged for you.",
                                         {"label": "Open the file", "action": "open"}))
    if rule:
        findings = [f for f in findings if f["rule"] == rule]
    findings.sort(key=lambda f: (_ORDER[f["severity"]], f["evidence_title"].lower(), f["evidence_id"], f["rule"]))
    counts = {}
    for f in findings:
        counts[f["rule"]] = counts.get(f["rule"], 0) + 1
    return {"rule_version": RULE_VERSION, "as_of": today, "scanned": len(rows), "limit_hit": len(rows) >= LIMIT_SCANNED,
            "counts": counts, "total": len(findings), "findings": findings[:max(1, min(int(limit), 500))],
            "rules": {k: {"label": v[0], "severity": v[1]} for k, v in RULES.items()},
            "note": "A file with no finding has no known defect. That is not a statement that it is sufficient."}


def _days_before(day: str, days: int) -> str:
    from datetime import datetime, timedelta
    return (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
