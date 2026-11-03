"""Respondent assignments (plan 24, CISO 03): an audit lead hands a few controls of one audit to a named person.

The person answers each control and chooses proof from the Evidence Vault; a named reviewer accepts or returns each answer.
An assignment opens only its own controls to its assignee: the rest of the audit, other assignments and other units stay
out of reach, and an assignment that was cancelled, or handed to someone else, stops opening at once.

States. Assignment: draft (editable, invisible to the assignee), in_progress, submitted, changes_requested, closed,
cancelled. Item: unreviewed, changes_requested, resubmitted, accepted. Every change bumps the assignment's `version`, and
every write names the version it was looking at, so two people never silently overwrite each other.

Accepting an answer accepts its proof links through the Vault's own rule (`proof.review_link`): the reviewer must be able
to open each file, must not be the person who attached it, and the file must still be the current, unexpired version
that was chosen. An accepted answer does not change the GRID control's status: the audit lead still decides that in GRID.
"""
import json
from datetime import date

from fastapi import HTTPException

from core.rbac import has_capability
from core.sql_like import ci_like, like_pattern
from core.timeutils import utcnow
from database import insert_returning_id
from modules.evidence import proof
from modules.evidence.scope import current_library_sql, evidence_scope_sql
from modules.governance.entity_scope import entity_scope_sql

OPEN_STATES = ("draft", "in_progress", "submitted", "changes_requested")
SEEN_BY_ASSIGNEE = ("in_progress", "submitted", "changes_requested", "closed")
EDITABLE = ("in_progress", "changes_requested")
MAX_ITEMS = 50
MAX_PROOF = 10
TEXT_LIMITS = {"title": 120, "instructions": 2000, "response": 4000, "observation": 2000, "reason": 1000}
STATE_LABELS = {"draft": "Draft", "in_progress": "With the respondent", "submitted": "Waiting for review",
                "changes_requested": "Changes requested", "closed": "Closed", "cancelled": "Cancelled"}


def _now() -> str:
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _text(value, name: str, *, minimum: int = 0) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise HTTPException(422, f"Send the {name} as text")
    value = value.strip()
    if len(value) < minimum or len(value) > TEXT_LIMITS[name]:
        raise HTTPException(422, f"The {name} must be {minimum} to {TEXT_LIMITS[name]} characters")
    return value


def _ids(raw, name: str) -> "list[int]":
    if not isinstance(raw, list) or not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in raw):
        raise HTTPException(422, f"Send the {name} as a list of whole numbers")
    if len(set(raw)) != len(raw):
        raise HTTPException(422, f"A {name[:-1]} appears twice")
    return list(raw)


def _version(raw) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise HTTPException(422, "Send the version you were looking at")
    return raw


def _event(db, assignment_id: int, actor: dict, action: str, item_id=None, detail=None) -> None:
    db.execute("INSERT INTO grid_assignment_events (assignment_id, item_id, actor_id, action, detail, created_at) "
               "VALUES (%s,%s,%s,%s,%s,%s)",
               (assignment_id, item_id, actor["id"], action, None if detail is None else json.dumps(detail), _now()))


def _notify(db, user_id: int, title: str, message: str, assignment_id: int) -> None:
    db.execute("INSERT INTO notifications (user_id, module, title, message, link) VALUES (%s,%s,%s,%s,%s)",
               (user_id, "grid", title, message, f"/grid/assignments/?open={assignment_id}"))


def _person(db, actor: dict, user_id) -> dict:
    """An active person of the actor's own organization, with their roles, as the permission checks need them."""
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        raise HTTPException(422, "Choose a person")
    row = db.execute("SELECT id, full_name, org_id, business_unit_id, is_active, deleted_at FROM users WHERE id=%s",
                     (user_id,)).fetchone()
    if not row or not row["is_active"] or row["deleted_at"] or row["org_id"] != actor.get("org_id"):
        raise HTTPException(404, "Person not found")
    roles = [r["role_key"] for r in db.execute("SELECT role_key FROM user_roles WHERE user_id=%s", (user_id,)).fetchall()]
    return {"id": row["id"], "full_name": row["full_name"], "org_id": row["org_id"],
            "business_unit_id": row["business_unit_id"], "roles": roles, "is_super_admin": False}


def _units_above(db, unit) -> "set | None":
    """The unit and every active unit above it; None for an organization-wide audit (everyone covers it). A person's
    reach is their own unit's subtree, so they cover the audit's unit when they sit in one of these."""
    if unit is None:
        return None
    parents = {r["id"]: r["parent_id"] for r in db.execute(
        "SELECT id, parent_id FROM business_units WHERE is_active=1").fetchall()}
    found, current = set(), unit
    while current is not None and current in parents and current not in found:
        found.add(current)
        current = parents[current]
    return found


def _covers(db, person: dict, unit) -> bool:
    """The person works in the audit's unit (or above it), or the audit is organization wide."""
    covering = _units_above(db, unit)
    return covering is None or person["business_unit_id"] in covering


def _audit(db, actor: dict, audit_id) -> dict:
    if not isinstance(audit_id, int) or isinstance(audit_id, bool):
        raise HTTPException(422, "Choose an audit")
    scope, params = entity_scope_sql(("grid", "audit"), actor, "a")
    row = db.execute(f"SELECT a.id, a.name, a.business_unit_id, a.is_locked FROM grid_audits a WHERE a.id=%s AND {scope}",
                     [audit_id, *params]).fetchone()
    if not row:
        raise HTTPException(404, "Audit not found")
    return dict(row)


def _due(raw) -> str:
    try:
        value = date.fromisoformat(str(raw))
    except ValueError:
        raise HTTPException(422, "Choose a due date") from None
    if value < utcnow().date():
        raise HTTPException(422, "Choose a due date that has not passed")
    return value.isoformat()


def _check_people(db, actor: dict, audit: dict, assignee_id, reviewer_id) -> "tuple[dict, dict]":
    assignee = _person(db, actor, assignee_id)
    if not has_capability(assignee, "grid.assignment.respond") or not _covers(db, assignee, audit["business_unit_id"]):
        raise HTTPException(422, "Choose someone who works in this audit's business unit")
    reviewer = _person(db, actor, reviewer_id)
    if (not has_capability(reviewer, "grid.assignment.review") or not has_capability(reviewer, "evidence.link.review")
            or not _covers(db, reviewer, audit["business_unit_id"])):
        raise HTTPException(422, "Choose a reviewer who may review answers and proof for this audit")
    if reviewer["id"] == assignee["id"]:
        raise HTTPException(422, "The reviewer cannot be the person who answers")
    return assignee, reviewer


def _controls(db, audit_id: int, control_ids: "list[int]") -> list:
    marks = ",".join(["%s"] * len(control_ids))
    rows = db.execute(f"SELECT id, control_id, name FROM grid_controls WHERE audit_id=%s AND id IN ({marks})",
                      [audit_id, *control_ids]).fetchall()
    if len(rows) != len(control_ids):
        raise HTTPException(404, "A control is not part of this audit")
    return rows


def _busy(db, control_ids: "list[int]", except_assignment=None) -> list:
    """Controls already in another open assignment: one control, one open round."""
    if not control_ids:
        return []
    marks = ",".join(["%s"] * len(control_ids))
    states = ",".join(f"'{s}'" for s in OPEN_STATES)
    rows = db.execute(
        "SELECT c.control_id AS ref, c.name FROM grid_assignment_items i JOIN grid_assignments a ON a.id=i.assignment_id "
        f"JOIN grid_controls c ON c.id=i.control_id WHERE i.control_id IN ({marks}) AND a.state IN ({states}) "
        "AND a.id != %s", [*control_ids, except_assignment or 0]).fetchall()
    return [r["ref"] or r["name"] for r in rows]


def _load(db, assignment_id) -> dict:
    if not isinstance(assignment_id, int) or isinstance(assignment_id, bool):
        raise HTTPException(404, "Assignment not found")
    row = db.execute("SELECT * FROM grid_assignments WHERE id=%s", (assignment_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Assignment not found")
    return dict(row)


def _as_staff(db, actor: dict, assignment_id) -> dict:
    """An assignment the actor manages or reviews, in an audit they may open."""
    row = _load(db, assignment_id)
    if row["org_id"] != actor.get("org_id") or not (has_capability(actor, "grid.assignment.manage")
                                                    or has_capability(actor, "grid.assignment.review")):
        raise HTTPException(404, "Assignment not found")
    _audit(db, actor, row["audit_id"])
    return row


def _as_assignee(db, actor: dict, assignment_id) -> dict:
    row = _load(db, assignment_id)
    if (row["assignee_id"] != actor["id"] or row["org_id"] != actor.get("org_id")
            or row["state"] not in SEEN_BY_ASSIGNEE or not has_capability(actor, "grid.assignment.respond")):
        raise HTTPException(404, "Assignment not found")
    return row


def _bump(db, row: dict, version: int, **changes) -> None:
    """Compare and set on the version the caller was looking at."""
    sets = ", ".join(f"{k}=%s" for k in changes)
    moved = db.execute(f"UPDATE grid_assignments SET {sets}{', ' if sets else ''}version=version+1, updated_at=%s "
                       "WHERE id=%s AND version=%s", [*changes.values(), _now(), row["id"], version]).rowcount
    if moved != 1:
        raise HTTPException(409, "Someone changed this assignment while you were looking at it. Reload it.")


# ── The audit lead ──────────────────────────────────────────────────────────

def create(db, actor: dict, audit_id, control_ids, assignee_id, reviewer_id, due_date, title, instructions="") -> int:
    if not actor.get("org_id") or not has_capability(actor, "grid.assignment.manage"):
        raise HTTPException(403, "Assigning audit questions needs the audit lead role")
    audit = _audit(db, actor, audit_id)
    if audit["is_locked"]:
        raise HTTPException(409, "This audit is locked")
    control_ids = _ids(control_ids, "controls")
    if not 1 <= len(control_ids) <= MAX_ITEMS:
        raise HTTPException(422, f"Choose 1 to {MAX_ITEMS} controls")
    _controls(db, audit["id"], control_ids)
    assignee, reviewer = _check_people(db, actor, audit, assignee_id,
                                       actor["id"] if reviewer_id in (None, "") else reviewer_id)
    busy = _busy(db, control_ids)
    if busy:
        raise HTTPException(409, "Already in an open assignment: " + ", ".join(busy[:10]))
    now = _now()
    new_id = insert_returning_id(
        db, "INSERT INTO grid_assignments (org_id, audit_id, business_unit_id, title, instructions, assignee_id, "
            "reviewer_id, due_date, created_by, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (actor["org_id"], audit["id"], audit["business_unit_id"], _text(title, "title", minimum=3),
         _text(instructions, "instructions"), assignee["id"], reviewer["id"], _due(due_date), actor["id"], now, now))
    for cid in control_ids:
        db.execute("INSERT INTO grid_assignment_items (assignment_id, control_id, updated_at) VALUES (%s,%s,%s)",
                   (new_id, cid, now))
    _event(db, new_id, actor, "created", detail={"controls": len(control_ids)})
    return new_id


def revise(db, actor: dict, assignment_id, version, reason=None, add=None, remove=None, assignee_id=None,
           reviewer_id=None, due_date=None) -> dict:
    """Change an assignment. A draft changes freely; once launched every change needs a reason and is logged, an
    accepted answer cannot be taken out, and a new assignee loses nothing but the old one loses access at once."""
    if not has_capability(actor, "grid.assignment.manage"):
        raise HTTPException(403, "Changing an assignment needs the audit lead role")
    row = _as_staff(db, actor, assignment_id)
    version = _version(version)
    if row["state"] not in OPEN_STATES:
        raise HTTPException(409, "A closed or cancelled assignment cannot change")
    launched = row["state"] != "draft"
    why = _text(reason, "reason", minimum=3 if launched else 0)
    audit = _audit(db, actor, row["audit_id"])
    add, remove = _ids(add or [], "controls"), _ids(remove or [], "controls")
    current = {r["control_id"]: r for r in db.execute(
        "SELECT id, control_id, review_state FROM grid_assignment_items WHERE assignment_id=%s", (row["id"],)).fetchall()}
    if set(add) & set(current) or not set(remove) <= set(current):
        raise HTTPException(422, "Add controls that are not in it and remove controls that are")
    if any(current[c]["review_state"] == "accepted" for c in remove):
        raise HTTPException(409, "An accepted answer cannot be taken out")
    if not 1 <= len(current) + len(add) - len(remove) <= MAX_ITEMS:
        raise HTTPException(422, f"An assignment holds 1 to {MAX_ITEMS} controls")
    if add:
        _controls(db, row["audit_id"], add)
        busy = _busy(db, add, row["id"])
        if busy:
            raise HTTPException(409, "Already in an open assignment: " + ", ".join(busy[:10]))
    changes = {}
    if assignee_id is not None or reviewer_id is not None:
        assignee, reviewer = _check_people(db, actor, audit, row["assignee_id"] if assignee_id is None else assignee_id,
                                           row["reviewer_id"] if reviewer_id is None else reviewer_id)
        changes.update(assignee_id=assignee["id"], reviewer_id=reviewer["id"])
    if due_date is not None:
        changes["due_date"] = _due(due_date)
    if not (add or remove or changes):
        raise HTTPException(422, "Nothing to change")
    _bump(db, row, version, **changes)
    now = _now()
    for cid in add:
        db.execute("INSERT INTO grid_assignment_items (assignment_id, control_id, updated_at) VALUES (%s,%s,%s)",
                   (row["id"], cid, now))
    for cid in remove:
        db.execute("DELETE FROM grid_assignment_items WHERE id=%s", (current[cid]["id"],))
    _event(db, row["id"], actor, "revised", detail={"reason": why, "added": len(add), "removed": len(remove),
                                                   **{k: v for k, v in changes.items()}})
    if launched and changes.get("assignee_id") not in (None, row["assignee_id"]):
        _notify(db, changes["assignee_id"], "Audit questions are now yours", row["title"], row["id"])
    elif launched:
        _notify(db, row["assignee_id"], "Your audit questions changed", f"{row['title']}: {why}", row["id"])
    return {"state": row["state"], "version": version + 1}


def launch(db, actor: dict, assignment_id, version) -> dict:
    if not has_capability(actor, "grid.assignment.manage"):
        raise HTTPException(403, "Sending an assignment needs the audit lead role")
    row = _as_staff(db, actor, assignment_id)
    if row["state"] != "draft":
        raise HTTPException(409, "Only a draft is sent")
    _bump(db, row, _version(version), state="in_progress", launched_at=_now())
    _event(db, row["id"], actor, "launched")
    _notify(db, row["assignee_id"], "You have audit questions to answer", f"{row['title']}, due {row['due_date']}",
            row["id"])
    return {"state": "in_progress", "version": version + 1}


def cancel(db, actor: dict, assignment_id, version, reason) -> dict:
    if not has_capability(actor, "grid.assignment.manage"):
        raise HTTPException(403, "Cancelling an assignment needs the audit lead role")
    row = _as_staff(db, actor, assignment_id)
    if row["state"] not in OPEN_STATES:
        raise HTTPException(409, "It is already closed or cancelled")
    why = _text(reason, "reason", minimum=3)
    _bump(db, row, _version(version), state="cancelled", closed_at=_now())
    _event(db, row["id"], actor, "cancelled", detail={"reason": why})
    if row["state"] != "draft":
        _notify(db, row["assignee_id"], "Audit questions were withdrawn", f"{row['title']}: {why}", row["id"])
    return {"state": "cancelled", "version": version + 1}


# ── The respondent ──────────────────────────────────────────────────────────

def _editable_item(db, actor, assignment_id, item_id) -> "tuple[dict, dict]":
    row = _as_assignee(db, actor, assignment_id)
    if row["state"] not in EDITABLE:
        raise HTTPException(409, "This assignment is not open for answers now")
    if not isinstance(item_id, int) or isinstance(item_id, bool):
        raise HTTPException(404, "Question not found")
    item = db.execute("SELECT * FROM grid_assignment_items WHERE id=%s AND assignment_id=%s",
                      (item_id, row["id"])).fetchone()
    if not item:
        raise HTTPException(404, "Question not found")
    if item["review_state"] == "accepted":
        raise HTTPException(409, "This answer was accepted and cannot change")
    return row, dict(item)


def save_item(db, actor: dict, assignment_id, item_id, version, response, observation="") -> dict:
    row, item = _editable_item(db, actor, assignment_id, item_id)
    version = _version(version)
    _bump(db, row, version)
    db.execute("UPDATE grid_assignment_items SET response=%s, observation=%s, updated_at=%s WHERE id=%s",
               (_text(response, "response"), _text(observation, "observation"), _now(), item["id"]))
    _event(db, row["id"], actor, "answered", item_id=item["id"])
    return {"version": version + 1}


def proof_choices(db, actor: dict, assignment_id, query) -> list:
    """Vault files the respondent may open, to choose as proof: current versions only, never another unit's."""
    _as_assignee(db, actor, assignment_id)
    term = query.strip() if isinstance(query, str) else ""
    if len(term) > 100:
        raise HTTPException(422, "Search with up to 100 characters")
    scope, params = evidence_scope_sql({**actor, "is_super_admin": False})
    where = [scope, current_library_sql(), "e.status = 'current'", "(e.expiry_date IS NULL OR e.expiry_date > %s)"]
    params = [*params, proof.today()]
    if term:
        where.append(f"({ci_like('e.title')} OR {ci_like('e.file_name')})")
        params += [like_pattern(term)] * 2
    rows = db.execute("SELECT e.id, e.title, e.version, e.expiry_date FROM evidence_items e "
                      f"WHERE {' AND '.join(where)} ORDER BY e.updated_at DESC, e.id DESC LIMIT 20", params).fetchall()
    return [dict(r) for r in rows]


def add_proof(db, actor: dict, assignment_id, item_id, version, evidence_id) -> dict:
    row, item = _editable_item(db, actor, assignment_id, item_id)
    version = _version(version)
    if not isinstance(evidence_id, int) or isinstance(evidence_id, bool):
        raise HTTPException(422, "Choose a file")
    scope, params = evidence_scope_sql({**actor, "is_super_admin": False})
    found = db.execute(f"SELECT e.id, e.title, e.version, e.file_hash, e.status, e.expiry_date FROM evidence_items e "
                       f"WHERE e.id=%s AND {scope}", [evidence_id, *params]).fetchone()
    if not found:
        raise HTTPException(404, "File not found")
    if found["status"] != "current" or proof.expired(found["expiry_date"]):
        raise HTTPException(409, "Choose the current version of a file that has not expired")
    active = db.execute("SELECT id, evidence_id FROM grid_assignment_proof WHERE item_id=%s AND removed_at IS NULL",
                        (item["id"],)).fetchall()
    if any(p["evidence_id"] == evidence_id for p in active):
        raise HTTPException(409, "This file is already chosen")
    if len(active) >= MAX_PROOF:
        raise HTTPException(422, f"Choose up to {MAX_PROOF} files for one question")
    _bump(db, row, version)
    link = db.execute("SELECT id FROM evidence_links WHERE evidence_id=%s AND module='grid' AND entity_type='control' "
                      "AND entity_id=%s AND deleted_at IS NULL", (evidence_id, item["control_id"])).fetchone()
    link_id = link["id"] if link else insert_returning_id(
        db, "INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by) VALUES (%s,%s,%s,%s,%s)",
        (evidence_id, "grid", "control", item["control_id"], actor["id"]))
    proof_id = insert_returning_id(
        db, "INSERT INTO grid_assignment_proof (item_id, evidence_id, evidence_version, file_hash, link_id, added_by, "
            "added_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (item["id"], evidence_id, found["version"], found["file_hash"], link_id, actor["id"], _now()))
    _event(db, row["id"], actor, "proof_added", item_id=item["id"], detail={"evidence_id": evidence_id})
    return {"id": proof_id, "version": version + 1}


def remove_proof(db, actor: dict, assignment_id, item_id, version, proof_id) -> dict:
    row, item = _editable_item(db, actor, assignment_id, item_id)
    version = _version(version)
    chosen = db.execute("SELECT * FROM grid_assignment_proof WHERE id=%s AND item_id=%s AND removed_at IS NULL",
                        (proof_id, item["id"])).fetchone()
    if not chosen:
        raise HTTPException(404, "File not found")
    _bump(db, row, version)
    now = _now()
    db.execute("UPDATE grid_assignment_proof SET removed_at=%s WHERE id=%s", (now, chosen["id"]))
    # The Vault link goes too when this person made it and nobody has reviewed it; a link someone else relies on stays.
    db.execute("UPDATE evidence_links SET deleted_at=%s, deleted_by=%s WHERE id=%s AND linked_by=%s "
               "AND COALESCE(review_status,'pending')='pending' AND deleted_at IS NULL",
               (now, actor["id"], chosen["link_id"], actor["id"]))
    _event(db, row["id"], actor, "proof_removed", item_id=item["id"], detail={"evidence_id": chosen["evidence_id"]})
    return {"version": version + 1}


def submit(db, actor: dict, assignment_id, version) -> dict:
    row = _as_assignee(db, actor, assignment_id)
    if row["state"] not in EDITABLE:
        raise HTTPException(409, "This assignment is not open for answers now")
    version = _version(version)
    items = db.execute(
        "SELECT i.id, i.response, i.review_state, c.control_id AS ref, c.name, "
        "(SELECT COUNT(*) FROM grid_evidence_items r WHERE r.control_id=c.id AND r.required=1) AS required, "
        "(SELECT COUNT(*) FROM grid_assignment_proof p WHERE p.item_id=i.id AND p.removed_at IS NULL) AS chosen "
        "FROM grid_assignment_items i JOIN grid_controls c ON c.id=i.control_id WHERE i.assignment_id=%s ORDER BY i.id",
        (row["id"],)).fetchall()
    open_items = [i for i in items if i["review_state"] != "accepted"]
    unanswered = [i["ref"] or i["name"] for i in open_items if not (i["response"] or "").strip()]
    unproved = [i["ref"] or i["name"] for i in open_items if i["required"] and not i["chosen"]]
    if unanswered or unproved:
        parts = []
        if unanswered:
            parts.append("Answer " + ", ".join(unanswered[:10]))
        if unproved:
            parts.append("choose proof for " + ", ".join(unproved[:10]) + " (it requires evidence)")
        raise HTTPException(422, "; ".join(parts) + ".")
    _bump(db, row, version, state="submitted", submitted_at=_now())
    db.execute("UPDATE grid_assignment_items SET review_state='resubmitted' WHERE assignment_id=%s "
               "AND review_state='changes_requested'", (row["id"],))
    _event(db, row["id"], actor, "submitted")
    _notify(db, row["reviewer_id"], "Audit answers are waiting for your review", row["title"], row["id"])
    return {"state": "submitted", "version": version + 1}


# ── The reviewer ────────────────────────────────────────────────────────────

def review_item(db, actor: dict, assignment_id, item_id, version, decision, note=None) -> dict:
    if not has_capability(actor, "grid.assignment.review"):
        raise HTTPException(403, "Reviewing answers needs the audit lead role")
    row = _as_staff(db, actor, assignment_id)
    if row["reviewer_id"] != actor["id"]:
        raise HTTPException(403, "Only the named reviewer reviews these answers")
    if row["state"] != "submitted":
        raise HTTPException(409, "These answers are not waiting for review")
    version = _version(version)
    if version != row["version"]:
        raise HTTPException(409, "Someone changed this assignment while you were looking at it. Reload it.")
    item = db.execute("SELECT * FROM grid_assignment_items WHERE id=%s AND assignment_id=%s",
                      (item_id, row["id"])).fetchone() if isinstance(item_id, int) else None
    if not item:
        raise HTTPException(404, "Question not found")
    if item["review_state"] not in ("unreviewed", "resubmitted"):
        raise HTTPException(409, "This answer is not waiting for review")
    if decision not in ("accept", "changes"):
        raise HTTPException(422, "Choose accept or request changes")
    remark = _text(note, "reason", minimum=3 if decision == "changes" else 0)
    if decision == "accept":
        _accept_proof(db, actor, item["id"])
    _bump(db, row, version)
    db.execute("UPDATE grid_assignment_items SET review_state=%s, review_note=%s, reviewed_by=%s, reviewed_at=%s "
               "WHERE id=%s", ("accepted" if decision == "accept" else "changes_requested", remark or None,
                              actor["id"], _now(), item["id"]))
    _event(db, row["id"], actor, "accepted" if decision == "accept" else "changes_requested", item_id=item["id"],
           detail={"note": remark} if remark else None)
    states = [r["review_state"] for r in db.execute(
        "SELECT review_state FROM grid_assignment_items WHERE assignment_id=%s", (row["id"],)).fetchall()]
    state, version = row["state"], version + 1
    if all(s == "accepted" for s in states):
        _bump(db, {**row, "version": version}, version, state="closed", closed_at=_now())
        state, version = "closed", version + 1
        _event(db, row["id"], actor, "closed")
        _notify(db, row["assignee_id"], "Your audit answers were accepted", row["title"], row["id"])
    elif not any(s in ("unreviewed", "resubmitted") for s in states):
        _bump(db, {**row, "version": version}, version, state="changes_requested")
        state, version = "changes_requested", version + 1
        _event(db, row["id"], actor, "returned")
        returned = sum(1 for s in states if s == "changes_requested")
        _notify(db, row["assignee_id"], "Some audit answers need changes",
                f"{row['title']}: {returned} to change", row["id"])
    return {"state": state, "version": version}


def _accept_proof(db, actor: dict, item_id: int) -> None:
    """Accepting an answer accepts the proof chosen for it, under the Vault's own rule, or refuses and says why."""
    for chosen in db.execute("SELECT p.*, e.title, e.file_hash AS hash_now, e.status FROM grid_assignment_proof p "
                             "LEFT JOIN evidence_items e ON e.id=p.evidence_id "
                             "WHERE p.item_id=%s AND p.removed_at IS NULL", (item_id,)).fetchall():
        title = chosen["title"] or "A chosen file"
        if chosen["hash_now"] != chosen["file_hash"] or chosen["status"] != "current":
            raise HTTPException(409, f"{title} changed after it was chosen. Request changes so the current "
                                     "version is chosen.")
        link = db.execute("SELECT review_status FROM evidence_links WHERE id=%s AND deleted_at IS NULL",
                          (chosen["link_id"],)).fetchone()
        if link and (link["review_status"] or "pending") == "accepted":
            continue
        try:
            proof.review_link(db, actor, chosen["link_id"], "accepted")
        except proof.ReviewError as refused:
            raise HTTPException(409, f"{title}: {refused.message}") from None


# ── Reading ─────────────────────────────────────────────────────────────────

def _summary(row) -> dict:
    return {"id": row["id"], "title": row["title"], "audit": row["audit_name"], "state": row["state"],
            "state_label": STATE_LABELS[row["state"]], "due_date": row["due_date"], "items": row["items"],
            "accepted": row["accepted"], "version": row["version"]}


_LIST = ("SELECT a.*, g.name AS audit_name, "
         "(SELECT COUNT(*) FROM grid_assignment_items i WHERE i.assignment_id=a.id) AS items, "
         "(SELECT COUNT(*) FROM grid_assignment_items i WHERE i.assignment_id=a.id AND i.review_state='accepted') "
         "AS accepted FROM grid_assignments a JOIN grid_audits g ON g.id=a.audit_id ")


def listing(db, actor: dict) -> dict:
    out = {"to_answer": [], "to_review": [], "managed": [],
           "can_create": has_capability(actor, "grid.assignment.manage")}
    if not actor.get("org_id"):
        return out
    if has_capability(actor, "grid.assignment.respond"):
        states = ",".join(f"'{s}'" for s in SEEN_BY_ASSIGNEE)
        out["to_answer"] = [_summary(r) for r in db.execute(
            _LIST + f"WHERE a.assignee_id=%s AND a.org_id=%s AND a.state IN ({states}) ORDER BY a.due_date, a.id "
            "LIMIT 200", (actor["id"], actor["org_id"])).fetchall()]
    if has_capability(actor, "grid.assignment.manage") or has_capability(actor, "grid.assignment.review"):
        scope, params = entity_scope_sql(("grid", "audit"), actor, "g")
        rows = db.execute(_LIST + f"WHERE a.org_id=%s AND {scope} ORDER BY a.id DESC LIMIT 200",
                          [actor["org_id"], *params]).fetchall()
        out["to_review"] = [_summary(r) for r in rows if r["reviewer_id"] == actor["id"] and r["state"] == "submitted"]
        out["managed"] = [{**_summary(r), "assignee": None} for r in rows]
        names = _names(db, {r["assignee_id"] for r in rows})
        for entry, r in zip(out["managed"], rows):
            entry["assignee"] = names.get(r["assignee_id"])
    return out


def _names(db, ids) -> dict:
    ids = sorted(i for i in ids if i)
    if not ids:
        return {}
    marks = ",".join(["%s"] * len(ids))
    return {r["id"]: r["full_name"] for r in db.execute(f"SELECT id, full_name FROM users WHERE id IN ({marks})",
                                                        ids).fetchall()}


def detail(db, actor: dict, assignment_id) -> dict:
    """The assignee sees their questions and their own answers; the audit lead and reviewer also see who, when and
    the history. Neither sees anything of the audit beyond the assigned controls."""
    row = _load(db, assignment_id)
    staff = False
    if row["assignee_id"] == actor["id"] and row["state"] in SEEN_BY_ASSIGNEE:
        row = _as_assignee(db, actor, assignment_id)
    else:
        row = _as_staff(db, actor, assignment_id)
        staff = True
    audit = db.execute("SELECT name FROM grid_audits WHERE id=%s", (row["audit_id"],)).fetchone()
    items = [dict(r) for r in db.execute(
        "SELECT i.id, i.control_id, i.response, i.observation, i.review_state, i.review_note, i.reviewed_at, "
        "c.control_id AS ref, c.name, c.description FROM grid_assignment_items i "
        "JOIN grid_controls c ON c.id=i.control_id WHERE i.assignment_id=%s ORDER BY c.control_id, i.id",
        (row["id"],)).fetchall()]
    required = {}
    if items:
        marks = ",".join(["%s"] * len(items))
        for r in db.execute(f"SELECT control_id, name FROM grid_evidence_items WHERE required=1 AND control_id IN ({marks}) "
                            "ORDER BY id", [i["control_id"] for i in items]).fetchall():
            required.setdefault(r["control_id"], []).append(r["name"])
        chosen = db.execute(
            "SELECT p.id, p.item_id, p.evidence_id, p.evidence_version, p.file_hash, e.title, e.version, "
            "e.file_hash AS hash_now, e.status, e.expiry_date, l.review_status FROM grid_assignment_proof p "
            "LEFT JOIN evidence_items e ON e.id=p.evidence_id LEFT JOIN evidence_links l ON l.id=p.link_id "
            f"WHERE p.removed_at IS NULL AND p.item_id IN ({marks}) ORDER BY p.id", [i["id"] for i in items]).fetchall()
    else:
        chosen = []
    by_item = {}
    for p in chosen:
        changed = p["hash_now"] != p["file_hash"] or p["status"] != "current" or proof.expired(p["expiry_date"])
        by_item.setdefault(p["item_id"], []).append({
            "id": p["id"], "evidence_id": p["evidence_id"], "title": p["title"] or "A file you can no longer open",
            "version": p["evidence_version"], "changed": changed,
            "review": proof.OUTCOME_LABELS.get(p["review_status"] or "pending", "Waiting for a reviewer")})
    for item in items:
        control_id = item.pop("control_id")
        item["required_evidence"] = required.get(control_id, [])
        item["proof"] = by_item.get(item["id"], [])
    out = {"id": row["id"], "title": row["title"], "instructions": row["instructions"], "audit": audit["name"],
           "due_date": row["due_date"], "state": row["state"], "state_label": STATE_LABELS[row["state"]],
           "version": row["version"], "items": items, "role": "staff" if staff else "assignee",
           "can_answer": not staff and row["state"] in EDITABLE,
           "can_review": staff and row["state"] == "submitted" and row["reviewer_id"] == actor["id"]
           and has_capability(actor, "grid.assignment.review"),
           "can_manage": staff and has_capability(actor, "grid.assignment.manage") and row["state"] in OPEN_STATES}
    if staff:
        names = _names(db, {row["assignee_id"], row["reviewer_id"], row["created_by"]})
        out.update(assignee=names.get(row["assignee_id"]), reviewer=names.get(row["reviewer_id"]),
                   audit_id=row["audit_id"], launched=row["state"] != "draft")
        events = db.execute("SELECT e.action, e.item_id, e.detail, e.created_at, u.full_name AS actor "
                            "FROM grid_assignment_events e LEFT JOIN users u ON u.id=e.actor_id "
                            "WHERE e.assignment_id=%s ORDER BY e.id", (row["id"],)).fetchall()
        out["events"] = [{**dict(e), "detail": json.loads(e["detail"]) if e["detail"] else None} for e in events]
    return out


def audit_choices(db, actor: dict) -> list:
    """Audits the audit lead may hand questions from, with their controls and which ones are already out."""
    if not has_capability(actor, "grid.assignment.manage"):
        raise HTTPException(403, "Assigning audit questions needs the audit lead role")
    scope, params = entity_scope_sql(("grid", "audit"), actor, "a")
    audits = db.execute(f"SELECT a.id, a.name, a.business_unit_id FROM grid_audits a WHERE {scope} "
                        "AND COALESCE(a.is_locked,0)=0 ORDER BY a.id DESC LIMIT 100", params).fetchall()
    return [{"id": a["id"], "name": a["name"]} for a in audits]


def audit_controls(db, actor: dict, audit_id) -> dict:
    if not has_capability(actor, "grid.assignment.manage"):
        raise HTTPException(403, "Assigning audit questions needs the audit lead role")
    audit = _audit(db, actor, audit_id)
    states = ",".join(f"'{s}'" for s in OPEN_STATES)
    controls = db.execute(
        "SELECT c.id, c.control_id AS ref, c.name, c.status, EXISTS (SELECT 1 FROM grid_assignment_items i "
        f"JOIN grid_assignments a ON a.id=i.assignment_id WHERE i.control_id=c.id AND a.state IN ({states})) AS busy "
        "FROM grid_controls c WHERE c.audit_id=%s ORDER BY c.control_id, c.id LIMIT 1000", (audit["id"],)).fetchall()
    people = db.execute("SELECT id, full_name, business_unit_id FROM users WHERE org_id=%s AND is_active=1 "
                        "AND deleted_at IS NULL ORDER BY full_name LIMIT 1000", (actor["org_id"],)).fetchall()
    roles = {}
    for r in db.execute("SELECT r.user_id, r.role_key FROM user_roles r JOIN users u ON u.id=r.user_id "
                        "WHERE u.org_id=%s", (actor["org_id"],)).fetchall():
        roles.setdefault(r["user_id"], []).append(r["role_key"])
    # A person covers the audit's unit when they sit in it or above it (their scope is their own subtree).
    covering = _units_above(db, audit["business_unit_id"])
    respondents, reviewers = [], []
    for p in people:
        if covering is not None and p["business_unit_id"] not in covering:
            continue
        person = {"id": p["id"], "roles": roles.get(p["id"], []), "is_super_admin": False}
        if has_capability(person, "grid.assignment.respond"):
            respondents.append({"id": p["id"], "name": p["full_name"]})
        if has_capability(person, "grid.assignment.review") and has_capability(person, "evidence.link.review"):
            reviewers.append({"id": p["id"], "name": p["full_name"]})
    return {"audit": {"id": audit["id"], "name": audit["name"]},
            "controls": [{**dict(c), "busy": bool(c["busy"])} for c in controls],
            "respondents": respondents, "reviewers": reviewers}
