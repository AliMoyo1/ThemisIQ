"""Needs attention (plan 24, CISO 01): fixed, explainable checks over records the viewer may already open.

Each check names a concrete gap in a record that a specialist module owns, the facts that raised it, and where to put it
right. It changes nothing. It reads every module through that module's own scope (`entity_scope_sql`), so a record the
viewer cannot open is never counted or named. A source that cannot be read is reported as not checked, never as clean,
and a record with no issue has no known gap, which is not a statement that it is sufficient.

Rules (version `a1`):

  proof_missing                 a control claimed done (GRID Complete, ARIA Implemented) has no current accepted proof
  proof_stale                   the same, and every piece of its proof has expired, was replaced or was turned down
  risk_basis_unexplained        an open ERM risk plans a lower score with no treatment plan and no treatment recorded
  risk_residual_above_current   an open ERM risk plans a higher score after treatment than it has now
  owner_or_review_missing       an overdue audit, exercise, plan review or risk review that nobody answers for
  risk_acceptance_expired       the approved acceptance of an open risk has expired
  risk_acceptance_basis_changed the risk changed after its acceptance was approved

Issues are computed on request, with no stored copy (the X-rays pattern). An issue's key is its rule and record; its
fingerprint is a hash of the facts that raised it. A reviewer may record a false positive or an accepted exception
against a fingerprint, with a reason and an optional expiry: the issue stays listed, marked reviewed, and opens again
when the facts change or the expiry passes.
"""
import hashlib
import json
from datetime import date

from fastapi import HTTPException

from core.best_effort import swallowed
from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.evidence import proof
from modules.governance.entity_scope import _KINDS, entity_scope_sql, may_view_kind

RULE_VERSION = "a1"
LIMIT_SCANNED = 2000
PAGE = 50
RULES = {
    "proof_stale": ("Claimed done, but its proof has lapsed", "error"),
    "risk_residual_above_current": ("Treatment would make the risk worse", "error"),
    "risk_acceptance_expired": ("Risk acceptance has expired", "error"),
    "proof_missing": ("Claimed done with no accepted proof", "warning"),
    "risk_basis_unexplained": ("Lower planned score with no treatment", "warning"),
    "owner_or_review_missing": ("Overdue and nobody answers for it", "warning"),
    "risk_acceptance_basis_changed": ("Risk changed after it was accepted", "warning"),
}
_ORDER = {"error": 0, "warning": 1, "info": 2}
DECISIONS = {"false_positive": "Not a real issue", "accepted_exception": "Accepted exception"}
OPEN_AUDIT = "COALESCE(a.status,'') NOT IN ('Completed','Archived','Closed','Cancelled')"
OPEN_RISK = "COALESCE(r.status,'') NOT IN ('closed','archived')"
DONE_EXERCISE = ("completed", "completed_awaiting_review", "closed", "cancelled")


def _fingerprint(*facts) -> str:
    return hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _link(key: tuple, record_id: int) -> str:
    return _KINDS[key].url.format(id=record_id, doc_id=record_id)


def _issue(rule, key, record_id, title, why, fix, facts) -> dict:
    label, severity = RULES[rule]
    return {"rule": rule, "rule_version": RULE_VERSION, "severity": severity, "label": label,
            "source_type": ".".join(key), "source_id": record_id, "title": title, "why": why, "fix": fix,
            "link": _link(key, record_id), "fingerprint": _fingerprint(rule, ".".join(key), record_id, facts)}


def _ids_in(ids) -> "tuple[str, list]":
    ids = sorted(set(ids))
    return ",".join(["%s"] * len(ids)), ids


# ── Proof behind controls claimed done ──────────────────────────────────────

def _vault_links(db, module: str, ids: list) -> dict:
    """Per control: (accepted current, waiting current, lapsed) Vault link ids."""
    out = {i: ([], [], []) for i in ids}
    if not ids:
        return out
    marks, params = _ids_in(ids)
    today = proof.today()
    rows = db.execute(
        f"SELECT el.id, el.entity_id, CASE WHEN {proof.accepted_sql()} THEN 'accepted' "
        f"WHEN {proof.current_sql()} THEN 'waiting' ELSE 'lapsed' END AS state "
        "FROM evidence_links el JOIN evidence_items e ON e.id = el.evidence_id "
        f"WHERE el.module = %s AND el.entity_type = 'control' AND el.entity_id IN ({marks}) AND {proof.live_sql()}",
        [today, today, module, *params]).fetchall()
    for r in rows:
        out[r["entity_id"]][("accepted", "waiting", "lapsed").index(r["state"])].append(r["id"])
    return out


def _proof_issue(key, record_id, title, status, good, waiting, lapsed, fix) -> "dict | None":
    if good:
        return None
    facts = {"status": status, "waiting": sorted(waiting), "lapsed": sorted(lapsed)}
    if lapsed and not waiting:
        return _issue("proof_stale", key, record_id, title,
                      f"It is marked {status}, and all {len(lapsed)} piece(s) of its proof have expired, were replaced "
                      "or were turned down.", fix, facts)
    why = f"It is marked {status} with no accepted, current proof."
    if waiting:
        why += f" {len(waiting)} linked piece(s) wait for a reviewer."
    return _issue("proof_missing", key, record_id, title, why, fix, facts)


def _grid_proof(db, user) -> list:
    key = ("grid", "control")
    scope, params = entity_scope_sql(key, user, "c")
    rows = db.execute(f"SELECT c.id, c.control_id AS ref, c.name, c.status FROM grid_controls c "
                      f"WHERE c.status = 'Complete' AND {scope} ORDER BY c.id LIMIT %s",
                      [*params, LIMIT_SCANNED]).fetchall()
    ids = [r["id"] for r in rows]
    files = {i: ([], [], []) for i in ids}
    if ids:
        marks, id_params = _ids_in(ids)
        today = proof.today()
        for f in db.execute(f"SELECT id, control_id, status, expires_at FROM grid_evidence_files "
                            f"WHERE control_id IN ({marks})", id_params).fetchall():
            approved = (f["status"] or "").lower() == "approved"
            expired = bool(f["expires_at"]) and str(f["expires_at"])[:10] <= today
            slot = 0 if approved and not expired else 2 if approved else 1
            files[f["control_id"]][slot].append(f"file:{f['id']}")
    links = _vault_links(db, "grid", ids)
    out = []
    for r in rows:
        good, waiting, lapsed = (files[r["id"]][n] + [f"link:{i}" for i in links[r["id"]][n]] for n in range(3))
        issue = _proof_issue(key, r["id"], f"{r['ref'] or ''} {r['name']}".strip(), "Complete", good, waiting, lapsed,
                             "Approve current evidence in GRID, or ask the owner for a new version")
        if issue:
            out.append(issue)
    return out, len(rows) >= LIMIT_SCANNED


def _aria_proof(db, user) -> list:
    key = ("aria", "control")
    scope, params = entity_scope_sql(key, user, "c")
    rows = db.execute(f"SELECT c.id, c.ref, c.name FROM controls c WHERE c.status = 'Implemented' AND {scope} "
                      "ORDER BY c.id LIMIT %s", [*params, LIMIT_SCANNED]).fetchall()
    links = _vault_links(db, "aria", [r["id"] for r in rows])
    out = []
    for r in rows:
        good, waiting, lapsed = ([f"link:{i}" for i in links[r["id"]][n]] for n in range(3))
        issue = _proof_issue(key, r["id"], f"{r['ref']} {r['name']}", "Implemented", good, waiting, lapsed,
                             "Link current proof in the Evidence Vault and have it reviewed")
        if issue:
            out.append(issue)
    return out, len(rows) >= LIMIT_SCANNED


# ── Enterprise risks ────────────────────────────────────────────────────────

def _erm(db, user) -> list:
    key = ("erm", "risk")
    scope, params = entity_scope_sql(key, user, "r")
    today = proof.today()
    rows = db.execute(
        "SELECT r.id, r.title, r.likelihood, r.impact, r.residual_likelihood, r.residual_impact, r.treatment_plan, "
        "r.owner_id, r.review_date, r.status, "
        "(SELECT COUNT(*) FROM erm_cf_treatments t WHERE t.risk_id = r.id) AS treatments "
        f"FROM erm_enterprise_risks r WHERE {OPEN_RISK} AND {scope} ORDER BY r.id LIMIT %s",
        [*params, LIMIT_SCANNED]).fetchall()
    out = []
    for r in rows:
        current = (r["likelihood"] or 0) * (r["impact"] or 0)
        planned = (r["residual_likelihood"] * r["residual_impact"]
                   if r["residual_likelihood"] is not None and r["residual_impact"] is not None else None)
        if planned is not None and planned > current:
            out.append(_issue("risk_residual_above_current", key, r["id"], r["title"],
                              f"Its planned score after treatment ({planned}) is higher than its score now ({current}).",
                              "Check the residual likelihood and impact", {"current": current, "planned": planned}))
        elif (planned is not None and planned < current and not (r["treatment_plan"] or "").strip()
              and not r["treatments"]):
            out.append(_issue("risk_basis_unexplained", key, r["id"], r["title"],
                              f"It plans to fall from {current} to {planned}, with no treatment plan and no treatment "
                              "recorded.", "Record the treatment that brings the score down",
                              {"current": current, "planned": planned}))
        if r["review_date"] and str(r["review_date"])[:10] < today and not r["owner_id"]:
            out.append(_issue("owner_or_review_missing", key, r["id"], r["title"],
                              f"Its review was due on {str(r['review_date'])[:10]} and it has no owner.",
                              "Name an owner and review it", {"due": str(r["review_date"])[:10]}))
    out += _acceptances(db, user, [r["id"] for r in rows])
    return out, len(rows) >= LIMIT_SCANNED


def _acceptances(db, user, risk_ids) -> list:
    if not risk_ids or not user.get("org_id"):
        return []
    from modules.erm import acceptance
    marks, params = _ids_in(risk_ids)
    rows = db.execute(
        "SELECT a.id, a.risk_id, a.expires_on, a.source_hash FROM erm_risk_acceptances a "
        f"WHERE a.org_id = %s AND a.status = 'approved' AND a.risk_id IN ({marks}) ORDER BY a.risk_id, a.id DESC",
        [user["org_id"], *params]).fetchall()
    latest = {}
    for r in rows:
        latest.setdefault(r["risk_id"], r)
    if not latest:
        return []
    marks, params = _ids_in(latest)
    risks = {r["id"]: dict(r) for r in db.execute(f"SELECT * FROM erm_enterprise_risks WHERE id IN ({marks})",
                                                 params).fetchall()}
    today, key, out = proof.today(), ("erm", "risk"), []
    for risk_id, a in latest.items():
        risk = risks[risk_id]
        if str(a["expires_on"])[:10] < today:
            out.append(_issue("risk_acceptance_expired", key, risk_id, risk["title"],
                              f"Its acceptance expired on {str(a['expires_on'])[:10]} and the risk is still open.",
                              "Review the acceptance, or treat the risk", {"acceptance": a["id"]}))
        elif acceptance._snapshot(db, risk)[1] != a["source_hash"]:
            out.append(_issue("risk_acceptance_basis_changed", key, risk_id, risk["title"],
                              "The risk changed after its acceptance was approved, so the decision was about "
                              "something else.", "Ask for the acceptance to be reviewed again",
                              {"acceptance": a["id"], "hash": a["source_hash"]}))
    return out


# ── Overdue work nobody answers for ─────────────────────────────────────────

def _grid_audits(db, user) -> list:
    key = ("grid", "audit")
    scope, params = entity_scope_sql(key, user, "a")
    rows = db.execute(f"SELECT a.id, a.name, a.end_date FROM grid_audits a WHERE a.end_date IS NOT NULL "
                      f"AND a.end_date < %s AND a.lead_id IS NULL AND {OPEN_AUDIT} AND {scope} ORDER BY a.id LIMIT %s",
                      [proof.today(), *params, LIMIT_SCANNED]).fetchall()
    return [_issue("owner_or_review_missing", key, r["id"], r["name"],
                   f"It was due to end on {str(r['end_date'])[:10]}, is not complete, and has no lead.",
                   "Name a lead in GRID", {"due": str(r["end_date"])[:10]}) for r in rows], len(rows) >= LIMIT_SCANNED


def _bcm(db, user) -> list:
    today, out = proof.today(), []
    key = ("bcm", "exercise")
    scope, params = entity_scope_sql(key, user, "x")
    done = ",".join(f"'{s}'" for s in DONE_EXERCISE)
    rows = db.execute(f"SELECT x.id, x.title, x.scheduled_date FROM bcm_exercises x WHERE x.scheduled_date IS NOT NULL "
                      f"AND x.scheduled_date < %s AND x.owner_id IS NULL AND COALESCE(x.status,'') NOT IN ({done}) "
                      f"AND {scope} ORDER BY x.id LIMIT %s", [today, *params, LIMIT_SCANNED]).fetchall()
    out += [_issue("owner_or_review_missing", key, r["id"], r["title"],
                   f"It was due on {str(r['scheduled_date'])[:10]}, has not been completed, and has no owner.",
                   "Name an owner and run or reschedule it", {"due": str(r["scheduled_date"])[:10]}) for r in rows]
    hit = len(rows) >= LIMIT_SCANNED
    key = ("bcm", "plan")
    scope, params = entity_scope_sql(key, user, "p")
    rows = db.execute(f"SELECT p.id, p.title, p.next_review FROM bcm_plans p WHERE p.next_review IS NOT NULL "
                      f"AND p.next_review < %s AND COALESCE(TRIM(p.owner),'') = '' "
                      f"AND COALESCE(p.status,'') NOT IN ('archived','retired') AND {scope} ORDER BY p.id LIMIT %s",
                      [today, *params, LIMIT_SCANNED]).fetchall()
    out += [_issue("owner_or_review_missing", key, r["id"], r["title"],
                   f"Its review was due on {str(r['next_review'])[:10]} and it has no owner.",
                   "Name an owner and review the plan", {"due": str(r["next_review"])[:10]}) for r in rows]
    return out, hit or len(rows) >= LIMIT_SCANNED


# (name, the kinds it reads, the check)
SOURCES = (
    ("grid_controls", (("grid", "control"),), _grid_proof),
    ("aria_controls", (("aria", "control"),), _aria_proof),
    ("erm_risks", (("erm", "risk"),), _erm),
    ("grid_audits", (("grid", "audit"),), _grid_audits),
    ("bcm", (("bcm", "exercise"), ("bcm", "plan")), _bcm),
)


def evaluate(db, user: dict) -> "tuple[list, list]":
    """(issues, sources): every issue the viewer may see, and for each source whether it was checked."""
    issues, sources = [], []
    for name, kinds, check in SOURCES:
        if not any(may_view_kind(user, k) for k in kinds):
            continue  # not the viewer's module: nothing is said about it at all
        try:
            found, limited = check(db, user)
        except Exception:
            db.rollback()
            swallowed(f"Needs attention source {name}")
            sources.append({"source": name, "state": "unavailable"})
            continue
        issues += found
        sources.append({"source": name, "state": "partial" if limited else "checked"})
    return issues, sources


def _reviews(db, user: dict, issues: list) -> None:
    """Mark each issue with its latest review, when that review is about the same facts and has not expired."""
    if not issues:
        return
    rows = db.execute("SELECT r.*, u.full_name AS reviewer FROM assurance_issue_reviews r "
                      "LEFT JOIN users u ON u.id = r.reviewed_by WHERE r.org_id = %s ORDER BY r.id",
                      (user.get("org_id"),)).fetchall()
    latest = {(r["rule"], r["source_type"], r["source_id"]): r for r in rows}
    today = proof.today()
    for issue in issues:
        r = latest.get((issue["rule"], issue["source_type"], issue["source_id"]))
        issue["review"], issue["state"] = None, "open"
        if not r:
            continue
        if r["fingerprint"] != issue["fingerprint"]:
            issue["reopened"] = "The facts changed after it was reviewed."
        elif r["expires_on"] and str(r["expires_on"])[:10] < today:
            issue["reopened"] = f"The review expired on {str(r['expires_on'])[:10]}."
        else:
            issue["state"] = "reviewed"
            issue["review"] = {"decision": r["decision"], "label": DECISIONS[r["decision"]], "reason": r["reason"],
                               "by": r["reviewer"], "at": str(r["reviewed_at"])[:16], "expires_on": r["expires_on"]}


def needs_attention(db, user: dict, *, severity="", rule="", state="open", source_type="", source_id=None,
                    page=1) -> dict:
    if not user.get("org_id") or not has_capability(user, "assurance.attention.view"):
        raise HTTPException(403, "Needs attention is for compliance, audit and risk specialists")
    if severity and severity not in _ORDER or rule and rule not in RULES or state not in ("open", "reviewed", "all"):
        raise HTTPException(422, "Choose a listed severity, check and state")
    issues, sources = evaluate(db, user)
    _reviews(db, user, issues)
    if source_type:
        issues = [i for i in issues if i["source_type"] == source_type and i["source_id"] == source_id]
    counts = {"open": {}, "reviewed": 0}
    for i in issues:
        if i["state"] == "open":
            counts["open"][i["severity"]] = counts["open"].get(i["severity"], 0) + 1
        else:
            counts["reviewed"] += 1
    shown = [i for i in issues if (state == "all" or i["state"] == state) and (not severity or i["severity"] == severity)
             and (not rule or i["rule"] == rule)]
    shown.sort(key=lambda i: (_ORDER[i["severity"]], i["rule"], i["title"].lower(), i["source_id"]))
    by_rule = {}
    for i in shown:
        by_rule[i["rule"]] = by_rule.get(i["rule"], 0) + 1
    pages = max(1, -(-len(shown) // PAGE))
    page = min(max(1, int(page)), pages)
    return {"rule_version": RULE_VERSION, "as_of": proof.today(), "sources": sources, "counts": counts,
            "by_rule": by_rule, "total": len(shown), "page": page, "pages": pages,
            "issues": shown[(page - 1) * PAGE: page * PAGE],
            "rules": {k: {"label": v[0], "severity": v[1]} for k, v in RULES.items()},
            "can_review": has_capability(user, "assurance.attention.review"),
            "note": "Checked only what you may open. A record with no issue has no known gap; that is not a "
                    "statement that it is sufficient."}


def review(db, user: dict, rule, source_type, source_id, fingerprint, decision, reason, expires_on=None) -> int:
    """Record that one issue is a false positive or an accepted exception, against the facts the reviewer saw."""
    if not user.get("org_id") or not has_capability(user, "assurance.attention.review"):
        raise HTTPException(403, "Reviewing issues needs a compliance, GRC or audit lead role")
    if decision not in DECISIONS:
        raise HTTPException(422, "Choose not a real issue, or accepted exception")
    if not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 1000:
        raise HTTPException(422, "Give the reason in 10 to 1000 characters")
    expiry = None
    if expires_on not in (None, ""):
        try:
            expiry = date.fromisoformat(str(expires_on))
        except ValueError:
            raise HTTPException(422, "Choose an expiry date") from None
        if expiry <= utcnow().date():
            raise HTTPException(422, "Choose an expiry date in the future")
        expiry = expiry.isoformat()
    issues, _ = evaluate(db, user)
    match = next((i for i in issues if i["rule"] == rule and i["source_type"] == source_type
                  and i["source_id"] == source_id), None)
    if match is None:
        raise HTTPException(404, "Issue not found")
    if match["fingerprint"] != fingerprint:
        raise HTTPException(409, "The facts behind this issue changed while you were looking. Reload it.")
    return insert_returning_id(
        db, "INSERT INTO assurance_issue_reviews (org_id, rule, source_type, source_id, fingerprint, decision, reason, "
            "expires_on, reviewed_by, reviewed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (user["org_id"], rule, source_type, source_id, fingerprint, decision, reason.strip(), expiry, user["id"],
         utcnow().strftime("%Y-%m-%d %H:%M:%S")))
