"""Reuse an earlier audit (plan 25, CISO 02): carry reviewed answers and current proof into a new audit as suggestions.

The audit lead picks the audit they are working on and an earlier one. For each control of the new audit the preview
shows which earlier control speaks to it and how strongly, what was accepted there (the answer from audit questions,
its current accepted proof), what is held back and why, and what applying would do. Applying never sets a target's
status: it links the earlier proof to the target control as proof waiting for review, and for a full match adds the
earlier answer as a comment marked "Suggested, not yet assessed". The target is still reviewed as itself.

How strongly two controls relate, one hop only:
  full     the same requirement (same canonical control, or same framework and reference), or a mapping a person
           reviewed as equivalent
  partial  a mapping reviewed as partial, or one nobody reviewed (whatever its type says)
Anything else is not offered. Only records the viewer may open are read; a hidden source is left out silently.
"""
import hashlib
import json
import re

from fastapi import HTTPException

from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.evidence import proof
from modules.evidence.scope import evidence_scope_sql
from modules.governance.entity_scope import entity_scope_sql

PAGE = 50
REVIEW_KINDS = ("equivalent", "partial")
_VAULT_PATH = re.compile(r"vault://([1-9][0-9]*)")
_VAULT_NOTE = re.compile(r"^From Evidence Vault \(vault_evidence_id=([1-9][0-9]*),")


def _now() -> str:
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _marks(values) -> str:
    return ",".join(["%s"] * len(values))


def _audit(db, user, audit_id) -> dict:
    if not isinstance(audit_id, int) or isinstance(audit_id, bool):
        raise HTTPException(422, "Choose an audit")
    scope, params = entity_scope_sql(("grid", "audit"), user, "a")
    row = db.execute(f"SELECT a.id, a.name, a.audit_date, a.end_date, a.is_locked FROM grid_audits a "
                     f"WHERE a.id=%s AND {scope}", [audit_id, *params]).fetchone()
    if not row:
        raise HTTPException(404, "Audit not found")
    return dict(row)


def _pair(db, user, target_id, source_id) -> "tuple[dict, dict]":
    if not user.get("org_id") or not has_capability(user, "grid.audits.manage"):
        raise HTTPException(403, "Reusing an earlier audit needs the audit lead role")
    target, source = _audit(db, user, target_id), _audit(db, user, source_id)
    if target["id"] == source["id"]:
        raise HTTPException(422, "Choose an earlier audit, not the same one")
    return target, source


def _vault_id(grid_file) -> "int | None":
    found = _VAULT_PATH.fullmatch(grid_file["file_path"] or "") or _VAULT_NOTE.match(grid_file["notes"] or "")
    return int(found.group(1)) if found else None


def _source_facts(db, user, source_ids: list) -> dict:
    """Per earlier control: its accepted answer, the Vault proof the viewer may open (accepted and current, or not),
    and GRID files that are not in the Vault."""
    facts = {i: {"answer": None, "carry": {}, "held": [], "grid_files": 0} for i in source_ids}
    if not source_ids:
        return facts
    marks = _marks(source_ids)
    for r in db.execute(
            "SELECT i.control_id, i.response, i.reviewed_at FROM grid_assignment_items i "
            f"WHERE i.control_id IN ({marks}) AND i.review_state='accepted' ORDER BY i.reviewed_at, i.id",
            source_ids).fetchall():
        facts[r["control_id"]]["answer"] = {"text": r["response"], "accepted_at": str(r["reviewed_at"] or "")[:10]}
    scope, scope_params = evidence_scope_sql({**user, "is_super_admin": False})
    today = proof.today()
    rows = db.execute(
        "SELECT el.entity_id, e.id, e.title, e.version, e.file_hash, "
        f"CASE WHEN {proof.accepted_sql()} THEN 1 ELSE 0 END AS good FROM evidence_links el "
        "JOIN evidence_items e ON e.id = el.evidence_id "
        f"WHERE el.module='grid' AND el.entity_type='control' AND el.entity_id IN ({marks}) AND {proof.live_sql()} "
        f"AND {scope}", [today, *source_ids, *scope_params]).fetchall()
    vault_ids = set()
    for r in rows:
        bucket = facts[r["entity_id"]]
        if r["good"]:
            bucket["carry"][r["id"]] = {"evidence_id": r["id"], "title": r["title"], "version": r["version"],
                                        "hash": r["file_hash"]}
        else:
            bucket["held"].append(f"{r['title']}: expired, replaced, turned down or not yet reviewed, so not carried")
        vault_ids.add(r["id"])
    for f in db.execute(f"SELECT control_id, file_path, notes, status, expires_at FROM grid_evidence_files "
                        f"WHERE control_id IN ({marks})", source_ids).fetchall():
        if _vault_id(f) in vault_ids:
            continue
        facts[f["control_id"]]["grid_files"] += 1
    for bucket in facts.values():
        if bucket["grid_files"]:
            bucket["held"].append(f"{bucket['grid_files']} file(s) kept only in GRID, not in the Vault: attach them "
                                  "to the new audit in GRID if they still apply")
    return facts


def _relations(db, target_rows, source_rows) -> dict:
    """target id -> (source row, relation, basis, mapping id) for the strongest one-hop relation, if any."""
    by_canonical, by_ref = {}, {}
    for s in source_rows:
        if s["canonical_control_id"]:
            by_canonical.setdefault(s["canonical_control_id"], s)
        if s["control_id"]:
            by_ref.setdefault((s["framework_id"], s["control_id"].strip().lower()), s)
    sources = {s["id"]: s for s in source_rows}
    targets = [t["id"] for t in target_rows]
    mapped = {}
    if targets and sources:
        for m in db.execute(
                "SELECT id, source_control_id, target_control_id, mapping_type, review_kind, reviewed_by "
                f"FROM grid_control_mappings WHERE (source_control_id IN ({_marks(targets)}) AND target_control_id "
                f"IN ({_marks(sources)})) OR (target_control_id IN ({_marks(targets)}) AND source_control_id IN "
                f"({_marks(sources)})) ORDER BY id", [*targets, *sources, *targets, *sources]).fetchall():
            t, s = ((m["source_control_id"], m["target_control_id"]) if m["source_control_id"] in targets
                    else (m["target_control_id"], m["source_control_id"]))
            if m["reviewed_by"] and m["review_kind"] == "equivalent":
                strength, basis = 2, "A mapping a person reviewed as equivalent"
            elif m["reviewed_by"]:
                strength, basis = 1, "A mapping a person reviewed as partial"
            else:
                strength, basis = 1, (f"A mapping marked '{m['mapping_type'] or 'equivalent'}' that nobody has "
                                      "reviewed, so it counts as partial")
            if strength > mapped.get(t, (0,))[0]:
                mapped[t] = (strength, sources[s], basis, m["id"])
    out = {}
    for t in target_rows:
        same = (t["canonical_control_id"] and by_canonical.get(t["canonical_control_id"])) or \
               (t["control_id"] and by_ref.get((t["framework_id"], t["control_id"].strip().lower())))
        if same:
            out[t["id"]] = (same, "full", "The same requirement in both audits", None)
        elif t["id"] in mapped:
            strength, s, basis, mapping_id = mapped[t["id"]]
            out[t["id"]] = (s, "full" if strength == 2 else "partial", basis, mapping_id)
    return out


def _controls(db, audit_id) -> list:
    return [dict(r) for r in db.execute(
        "SELECT id, control_id, name, status, notes, framework_id, canonical_control_id FROM grid_controls "
        "WHERE audit_id=%s ORDER BY control_id, id LIMIT 2000", (audit_id,)).fetchall()]


def _rows(db, user, target, source) -> list:
    target_rows, source_rows = _controls(db, target["id"]), _controls(db, source["id"])
    relations = _relations(db, target_rows, source_rows)
    facts = _source_facts(db, user, sorted({r[0]["id"] for r in relations.values()}))
    linked = {}
    targets = [t["id"] for t in target_rows]
    if targets:
        for r in db.execute("SELECT entity_id, evidence_id FROM evidence_links WHERE module='grid' "
                            f"AND entity_type='control' AND deleted_at IS NULL AND entity_id IN ({_marks(targets)})",
                            targets).fetchall():
            linked.setdefault(r["entity_id"], set()).add(r["evidence_id"])
    noted = {(r["target_control_id"], r["source_control_id"]) for r in db.execute(
        "SELECT r.target_control_id, r.source_control_id FROM grid_reuse_rows r JOIN grid_reuse_decisions d "
        "ON d.id=r.decision_id WHERE d.target_audit_id=%s AND d.undone_at IS NULL AND r.comment_id IS NOT NULL",
        (target["id"],)).fetchall()}
    rows = []
    for t in target_rows:
        row = {"target": {"id": t["id"], "ref": t["control_id"], "name": t["name"], "status": t["status"]},
               "source": None, "relation": "none", "basis": "Nothing in the earlier audit speaks to this control",
               "proof": [], "held_back": [], "answer": None, "note": False, "carry": [], "would_change": False}
        if t["id"] in relations:
            s, relation, basis, mapping_id = relations[t["id"]]
            f = facts[s["id"]]
            carry = [p for i, p in sorted(f["carry"].items()) if i not in linked.get(t["id"], set())]
            note = relation == "full" and bool(f["answer"]) and (t["id"], s["id"]) not in noted
            held = list(f["held"])
            if relation == "partial" and f["answer"]:
                held.append("The earlier answer is not carried: the controls only partly match")
            if s["status"] != "Complete":
                held.append(f"The earlier control was {s['status'] or 'not assessed'}, not Complete")
            row.update(source={"id": s["id"], "ref": s["control_id"], "name": s["name"], "status": s["status"]},
                       relation=relation, basis=basis, mapping_id=mapping_id, answer=f["answer"],
                       proof=list(f["carry"].values()), held_back=held, note=note,
                       carry=[p["evidence_id"] for p in carry], would_change=bool(carry or note))
        row["fingerprint"] = hashlib.sha256(json.dumps(
            [t["status"], sorted(linked.get(t["id"], ())), row["relation"], row["source"], row["answer"],
             [(p["evidence_id"], p["hash"]) for p in row["proof"]], row["carry"], row["note"]],
            sort_keys=True, default=str).encode()).hexdigest()[:24]
        rows.append(row)
    return rows


def preview(db, user, target_id, source_id, page=1) -> dict:
    target, source = _pair(db, user, target_id, source_id)
    rows = _rows(db, user, target, source)
    counts = {"full": 0, "partial": 0, "none": 0, "would_change": 0}
    for r in rows:
        counts[r["relation"]] += 1
        counts["would_change"] += r["would_change"]
    pages = max(1, -(-len(rows) // PAGE))
    page = min(max(1, int(page)), pages)
    shown = rows[(page - 1) * PAGE: page * PAGE]
    for r in shown:
        for p in r["proof"]:
            p.pop("hash", None)
    return {"target": {"id": target["id"], "name": target["name"], "locked": bool(target["is_locked"])},
            "source": {"id": source["id"], "name": source["name"], "date": source["audit_date"] or source["end_date"]},
            "counts": counts, "page": page, "pages": pages, "rows": shown,
            "note": "Applying adds suggestions only. No control's status changes; each one is still reviewed here."}


def apply(db, user, target_id, source_id, selected) -> dict:
    """Apply the chosen rows, each with the fingerprint it was previewed with. A row whose facts changed since is
    refused as a whole so the person looks again; a row with nothing left to add is skipped."""
    target, source = _pair(db, user, target_id, source_id)
    if target["is_locked"]:
        raise HTTPException(409, "This audit is locked")
    if (not isinstance(selected, list) or not 1 <= len(selected) <= 500 or not all(
            isinstance(s, dict) and isinstance(s.get("target_control_id"), int)
            and not isinstance(s.get("target_control_id"), bool) and isinstance(s.get("fingerprint"), str)
            for s in selected)):
        raise HTTPException(422, "Choose the rows to apply")
    if len({s["target_control_id"] for s in selected}) != len(selected):
        raise HTTPException(422, "Choose each target control once")
    rows = {r["target"]["id"]: r for r in _rows(db, user, target, source)}
    chosen = []
    for s in selected:
        row = rows.get(s["target_control_id"])
        if row is None:
            raise HTTPException(404, "A chosen control is not part of this audit")
        if row["fingerprint"] != s["fingerprint"]:
            raise HTTPException(409, "Something changed since the preview. Refresh it and choose again.")
        if row["would_change"]:
            chosen.append(row)
    if not chosen:
        return {"decision_id": None, "applied": 0, "links": 0, "notes": 0}
    now = _now()
    decision = insert_returning_id(
        db, "INSERT INTO grid_reuse_decisions (org_id, target_audit_id, source_audit_id, applied_by, applied_at) "
            "VALUES (%s,%s,%s,%s,%s)", (user["org_id"], target["id"], source["id"], user["id"], now))
    links = notes = 0
    for row in chosen:
        made = []
        for evidence_id in row["carry"]:
            made.append(insert_returning_id(
                db, "INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by) "
                    "VALUES (%s,'grid','control',%s,%s)", (evidence_id, row["target"]["id"], user["id"])))
        comment = None
        if row["note"]:
            comment = insert_returning_id(
                db, "INSERT INTO grid_control_comments (control_id, user_id, content, created_at) VALUES (%s,%s,%s,%s)",
                (row["target"]["id"], user["id"],
                 f"Suggested, not yet assessed. From {source['name']}, control {row['source']['ref'] or ''} "
                 f"(answer accepted {row['answer']['accepted_at']}): {row['answer']['text']}", now))
            notes += 1
        links += len(made)
        db.execute(
            "INSERT INTO grid_reuse_rows (decision_id, target_control_id, source_control_id, relation, basis, "
            "mapping_id, fingerprint, source_snapshot, target_before, link_ids, comment_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (decision, row["target"]["id"], row["source"]["id"], row["relation"], row["basis"], row["mapping_id"],
             row["fingerprint"], json.dumps({"source": row["source"], "answer": row["answer"],
                                             "proof": [p["evidence_id"] for p in row["proof"]]}),
             json.dumps(row["target"]), json.dumps(made), comment))
    return {"decision_id": decision, "applied": len(chosen), "links": links, "notes": notes}


def history(db, user, target_id) -> list:
    if not has_capability(user, "grid.audits.manage"):
        raise HTTPException(403, "Reusing an earlier audit needs the audit lead role")
    target = _audit(db, user, target_id)
    rows = db.execute(
        "SELECT d.*, a.name AS source_name, u.full_name AS applied_by_name, "
        "(SELECT COUNT(*) FROM grid_reuse_rows r WHERE r.decision_id=d.id) AS rows_applied "
        "FROM grid_reuse_decisions d LEFT JOIN grid_audits a ON a.id=d.source_audit_id "
        "LEFT JOIN users u ON u.id=d.applied_by WHERE d.target_audit_id=%s ORDER BY d.id DESC LIMIT 100",
        (target["id"],)).fetchall()
    return [{"id": r["id"], "source": r["source_name"], "applied_by": r["applied_by_name"],
             "applied_at": r["applied_at"], "rows": r["rows_applied"], "undone_at": r["undone_at"],
             "undo_reason": r["undo_reason"]} for r in rows]


def undo(db, user, decision_id, reason) -> dict:
    """Take back what one application added, while none of its suggested proof has been reviewed. Otherwise the
    target's reviewer decides on that proof as usual."""
    if not has_capability(user, "grid.audits.manage"):
        raise HTTPException(403, "Reusing an earlier audit needs the audit lead role")
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 1000:
        raise HTTPException(422, "Give the reason in 3 to 1000 characters")
    found = db.execute("SELECT * FROM grid_reuse_decisions WHERE id=%s", (decision_id,)).fetchone() \
        if isinstance(decision_id, int) else None
    if not found:
        raise HTTPException(404, "Not found")
    _audit(db, user, found["target_audit_id"])
    if found["undone_at"]:
        raise HTTPException(409, "It was already undone")
    rows = db.execute("SELECT link_ids, comment_id FROM grid_reuse_rows WHERE decision_id=%s", (found["id"],)).fetchall()
    link_ids = [i for r in rows for i in json.loads(r["link_ids"])]
    if link_ids:
        reviewed = db.execute(f"SELECT COUNT(*) FROM evidence_links WHERE id IN ({_marks(link_ids)}) AND "
                              "deleted_at IS NULL AND COALESCE(review_status,'pending') <> 'pending'",
                              link_ids).fetchone()[0]
        if reviewed:
            raise HTTPException(409, f"{reviewed} suggested proof link(s) were reviewed since. Decide on them in "
                                     "the Vault instead of undoing.")
        db.execute(f"UPDATE evidence_links SET deleted_at=%s, deleted_by=%s WHERE id IN ({_marks(link_ids)}) "
                   "AND deleted_at IS NULL", [_now(), user["id"], *link_ids])
    comments = [r["comment_id"] for r in rows if r["comment_id"]]
    if comments:
        db.execute(f"DELETE FROM grid_control_comments WHERE id IN ({_marks(comments)})", comments)
    db.execute("UPDATE grid_reuse_decisions SET undone_by=%s, undone_at=%s, undo_reason=%s WHERE id=%s",
               (user["id"], _now(), reason.strip(), found["id"]))
    return {"links_removed": len(link_ids), "notes_removed": len(comments)}


def review_mapping(db, user, mapping_id, kind) -> dict:
    """A person states what a mapping is worth: equivalent (full reuse) or partial (proof only)."""
    if not has_capability(user, "grid.cross_mapping.manage"):
        raise HTTPException(403, "Reviewing mappings needs the audit lead or auditor role")
    if kind not in REVIEW_KINDS:
        raise HTTPException(422, "Choose equivalent or partial")
    m = db.execute("SELECT m.id, s.audit_id AS sa, t.audit_id AS ta FROM grid_control_mappings m "
                   "JOIN grid_controls s ON s.id=m.source_control_id JOIN grid_controls t ON t.id=m.target_control_id "
                   "WHERE m.id=%s", (mapping_id,)).fetchone() if isinstance(mapping_id, int) else None
    if not m:
        raise HTTPException(404, "Mapping not found")
    _audit(db, user, m["sa"])
    _audit(db, user, m["ta"])
    db.execute("UPDATE grid_control_mappings SET review_kind=%s, reviewed_by=%s, reviewed_at=%s WHERE id=%s",
               (kind, user["id"], _now(), m["id"]))
    return {"id": m["id"], "review_kind": kind}


def audit_choices(db, user) -> list:
    if not has_capability(user, "grid.audits.manage"):
        raise HTTPException(403, "Reusing an earlier audit needs the audit lead role")
    scope, params = entity_scope_sql(("grid", "audit"), user, "a")
    return [{"id": r["id"], "name": r["name"], "date": r["audit_date"] or r["end_date"], "locked": bool(r["is_locked"])}
            for r in db.execute(f"SELECT a.id, a.name, a.audit_date, a.end_date, a.is_locked FROM grid_audits a "
                                f"WHERE {scope} ORDER BY a.id DESC LIMIT 200", params).fetchall()]
