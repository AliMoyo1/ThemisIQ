"""
Evidence Vault: what an item proves (plans/2026-10-governance-rework/02 section 4, and 05 Phase 1 slice C).

A file in the Vault and a claim that it supports are different things, and "has evidence" can mean three different
things. They are kept apart here, each with one definition that the coverage numbers, the library state, the control
effectiveness score and the version impact list all use:

* live link   a link nobody removed, to an item that is not archived. The item may have expired or been replaced.
* current     a live link to the current version of an item (not replaced, not archived, not expired) that no reviewer
              has returned, rejected or ruled out of scope for that target.
* accepted    a current link that a reviewer of the target accepted for this version.

A hash, a link count or the metadata health score never makes a link accepted: only a person's recorded review does, and
never the person who attached the file. A new version never inherits an accepted verdict: its links are proposed from the
previous version's and wait for their own review.
"""
from datetime import datetime, timedelta

from core.rbac import has_capability
from core.timeutils import utcnow
from modules.evidence.scope import evidence_scope_sql
from modules.governance.entity_scope import canonical_key, describe_record, describe_records

OUTCOMES = ("pending", "accepted", "returned", "rejected", "out_of_scope")
NOT_PROOF = ("returned", "rejected", "out_of_scope")
NOTE_MAX = 500
NOTE_MIN = 3
OUTCOME_LABELS = {
    "pending": "Waiting for a reviewer", "accepted": "Accepted", "returned": "Returned for changes",
    "rejected": "Rejected", "out_of_scope": "Does not apply",
}
STATE_LABELS = {
    "archived": "Archived", "replaced": "Replaced by a newer version", "expired": "Expired", "draft": "Draft",
    "needs_filing": "Needs filing", "returned": "Returned for changes", "awaiting_review": "Awaiting review",
    "accepted": "Accepted",
}


class ReviewError(Exception):
    """A refused review or impact request, with the HTTP status the route should answer."""

    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


def _ident(alias: str) -> str:
    if not alias.isidentifier():
        raise ValueError("alias must be a plain SQL identifier")
    return alias


def today() -> str:
    return utcnow().strftime("%Y-%m-%d")


def review_status_sql(link: str = "el") -> str:
    """The review status of a link; a link nobody has reviewed is pending, never accepted."""
    return f"COALESCE({_ident(link)}.review_status, 'pending')"


def live_sql(link: str = "el", item: str = "e") -> str:
    """A link that was not removed, on an item that is not archived."""
    return f"({_ident(link)}.deleted_at IS NULL AND {_ident(item)}.status != 'archived')"


def current_sql(link: str = "el", item: str = "e") -> str:
    """Live, on the current version, not expired, and not turned down by a reviewer. One bound parameter: today."""
    marks = ",".join(f"'{o}'" for o in NOT_PROOF)
    return (f"({live_sql(link, item)} AND {_ident(item)}.status = 'current' "
            f"AND ({_ident(item)}.expiry_date IS NULL OR {_ident(item)}.expiry_date > %s) "
            f"AND {review_status_sql(link)} NOT IN ({marks}))")


def accepted_sql(link: str = "el", item: str = "e") -> str:
    """Current, and accepted by a reviewer. One bound parameter: today."""
    return f"({current_sql(link, item)} AND {review_status_sql(link)} = 'accepted')"


def expired(expiry_date, on: str = None) -> bool:
    """An item expires on its expiry date: that day it no longer counts. Dates are ISO text, so they compare as text."""
    return bool(expiry_date) and str(expiry_date)[:10] <= (on or today())


def due(review_due_date, on: str = None, within_days: int = 0) -> bool:
    """True when the review date is today or past, or falls within `within_days` of `on` (the work view uses 30)."""
    if not review_due_date:
        return False
    limit = datetime.strptime(on or today(), "%Y-%m-%d") + timedelta(days=within_days)
    return str(review_due_date)[:10] <= limit.strftime("%Y-%m-%d")


def item_state(*, status, expiry_date, links_active, links_pending, links_returned, on: str = None) -> dict:
    """The one-word state a library row shows. `links_active` is live links that were not ruled out of scope. Never says
    accepted unless every active link was accepted by a reviewer."""
    if status == "archived":
        key = "archived"
    elif status == "superseded":
        key = "replaced"
    elif status == "draft":
        key = "draft"
    elif status == "expired" or expired(expiry_date, on):
        key = "expired"
    elif not links_active:
        key = "needs_filing"
    elif links_returned:
        key = "returned"
    elif links_pending:
        key = "awaiting_review"
    else:
        key = "accepted"
    return {"key": key, "label": STATE_LABELS[key]}


# ── A reviewer's verdict on one link ───────────────────────────────────────

def _note(value, required: bool) -> "str | None":
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ReviewError(422, "Say why, so the person who owns the record can see your reasoning.")
        return None
    if not isinstance(value, str):
        raise ReviewError(422, "The note must be text.")
    value = value.strip()
    if len(value) < NOTE_MIN:
        raise ReviewError(422, f"Write at least {NOTE_MIN} characters.")
    if len(value) > NOTE_MAX:
        raise ReviewError(422, f"Keep the note to {NOTE_MAX} characters or fewer.")
    return value


def review_link(db, user: dict, link_id: int, outcome, note=None, expected_status=None) -> dict:
    """Record a reviewer's verdict on one link: whether this version of the item supports this target. Needs the right to
    review evidence and the right to open the target; a hidden or removed link answers 404 like a missing one. The person
    who attached the file or the link cannot review it. Only the current, unexpired version can be accepted. The change
    is compare-and-set on the status the reviewer was looking at, so two reviewers never silently overwrite each other."""
    if not has_capability(user, "evidence.link.review"):
        raise ReviewError(403, "You do not have the right to review evidence.")
    if isinstance(link_id, bool) or not isinstance(link_id, int):
        raise ReviewError(400, "Send the link as a whole number.")
    if outcome not in OUTCOMES:
        raise ReviewError(422, "Choose accepted, returned, rejected, does not apply, or back to waiting.")
    scope_sql, scope_params = evidence_scope_sql(user)
    row = db.execute(
        "SELECT el.id, el.evidence_id, el.module, el.entity_type, el.entity_id, el.linked_by, el.review_status, "
        "e.status AS item_status, e.expiry_date, e.uploaded_by, e.title "
        "FROM evidence_links el JOIN evidence_items e ON e.id = el.evidence_id "
        f"WHERE el.id = %s AND el.deleted_at IS NULL AND {scope_sql}", [link_id, *scope_params]).fetchone()
    if row is None or not describe_record(db, canonical_key(row["module"], row["entity_type"]), row["entity_id"], user):
        raise ReviewError(404, "Link not found.")
    if user["id"] in (row["linked_by"], row["uploaded_by"]):
        raise ReviewError(403, "Someone other than the person who attached this evidence has to review it.")
    current = row["review_status"] or "pending"
    if expected_status is not None and expected_status != current:
        raise ReviewError(409, "This link was reviewed by someone else. Reload it and look again.", status_now=current)
    if outcome == "accepted":
        if row["item_status"] != "current" or expired(row["expiry_date"]):
            raise ReviewError(409, "Only the current version that has not expired can be accepted. This one has been "
                                   "replaced, has expired or is archived.", item_status=row["item_status"])
    note = _note(note, required=outcome in NOT_PROOF)
    now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    moved = db.execute(
        "UPDATE evidence_links SET review_status = %s, reviewed_by = %s, reviewed_at = %s, review_note = %s "
        "WHERE id = %s AND deleted_at IS NULL AND COALESCE(review_status, 'pending') = %s",
        (outcome, None if outcome == "pending" else user["id"], None if outcome == "pending" else now,
         None if outcome == "pending" else note, link_id, current)).rowcount
    if moved != 1:
        raise ReviewError(409, "This link was reviewed by someone else. Reload it and look again.")
    return {"link": {"id": link_id, "evidence_id": row["evidence_id"], "review_status": outcome,
                     "label": OUTCOME_LABELS[outcome], "reviewed_at": None if outcome == "pending" else now,
                     "review_note": None if outcome == "pending" else note},
            "entity_type": row["entity_type"], "entity_id": row["entity_id"],
            "audit": ("Reviewed an evidence link: " + OUTCOME_LABELS[outcome].lower(), "evidence", row["evidence_id"],
                      f"{row['module']}/{row['entity_type']} {row['entity_id']}")}


def record_request_decision(db, request: dict, reviewer: dict, accepted: bool, notes: str = "") -> "int | None":
    """A collection request that was accepted or returned is a reviewer's verdict on the file submitted for it and the
    record it was asked for. Make that visible as a link verdict so the request and the claim cannot disagree: the link is
    created when the submission had none, and starts the verdict the reviewer gave. Never inherits an older verdict and
    never touches a link of another version. Returns the link id, or None when the request names nothing linkable."""
    evidence_id = request.get("evidence_id")
    module, entity_type = str(request.get("module") or "").strip().lower(), str(request.get("entity_type") or "").strip().lower()
    try:
        entity_id = int(request.get("entity_id"))
    except (TypeError, ValueError):
        return None
    if not evidence_id or not module or not entity_type or entity_id <= 0:
        return None
    link = db.execute(
        "SELECT id FROM evidence_links WHERE evidence_id = %s AND module = %s AND entity_type = %s AND entity_id = %s "
        "AND deleted_at IS NULL ORDER BY id DESC", (evidence_id, module, entity_type, entity_id)).fetchone()
    now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    outcome = "accepted" if accepted else "returned"
    note = (notes or "").strip() or f"{OUTCOME_LABELS[outcome]} as the response to a collection request."
    if link is None:
        if not accepted:
            return None  # nothing was linked, so there is nothing to turn down
        from database import insert_returning_id
        link_id = insert_returning_id(
            db, "INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by, review_status, "
                "reviewed_by, reviewed_at, review_note) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (evidence_id, module, entity_type, entity_id, request.get("assignee_id"), outcome, reviewer["id"], now, note[:NOTE_MAX]))
        return link_id
    db.execute("UPDATE evidence_links SET review_status = %s, reviewed_by = %s, reviewed_at = %s, review_note = %s WHERE id = %s",
               (outcome, reviewer["id"], now, note[:NOTE_MAX], link["id"]))
    return link["id"]


def pending_reviews(db, user: dict, limit: int = 100) -> list:
    """Links waiting for a verdict that this person may give: the current, unexpired version; a link nobody reviewed; not
    attached by this person; to a record they may open. Each is {link_id, evidence_id, title, claim}."""
    if not has_capability(user, "evidence.link.review"):
        return []
    scope_sql, scope_params = evidence_scope_sql(user)
    rows = db.execute(
        "SELECT l.id AS link_id, l.evidence_id, l.module, l.entity_type, l.entity_id, e.title "
        "FROM evidence_links l JOIN evidence_items e ON e.id = l.evidence_id "
        "WHERE l.deleted_at IS NULL AND COALESCE(l.review_status, 'pending') = 'pending' AND e.status = 'current' "
        "AND (e.expiry_date IS NULL OR e.expiry_date > %s) AND (l.linked_by IS NULL OR l.linked_by != %s) "
        f"AND (e.uploaded_by IS NULL OR e.uploaded_by != %s) AND {scope_sql} ORDER BY l.id DESC LIMIT 500",
        [today(), user["id"], user["id"], *scope_params]).fetchall()
    wanted = {}
    for r in rows:
        wanted.setdefault(canonical_key(r["module"], r["entity_type"]), set()).add(r["entity_id"])
    seen = {key: describe_records(db, key, sorted(ids), user) for key, ids in wanted.items()}
    out = []
    for r in rows:
        shown = seen.get(canonical_key(r["module"], r["entity_type"]), {}).get(r["entity_id"])
        if shown is not None:
            out.append({"link_id": r["link_id"], "evidence_id": r["evidence_id"], "title": r["title"], "claim": shown["title"]})
        if len(out) >= limit:
            break
    return out


# ── A new version and what it does to the links of the one it replaced ─────

def carry_forward(db, user: dict, previous_id: int, new_id: int) -> dict:
    """Propose, on the new version, a link for each live link of the previous one whose target the uploader may open. A
    proposed link starts waiting for review: the accepted verdict of the old version is never inherited. Links to targets
    the uploader cannot open stay on the old version and are only counted."""
    rows = db.execute(
        "SELECT id, module, entity_type, entity_id FROM evidence_links WHERE evidence_id = %s AND deleted_at IS NULL "
        "ORDER BY id", (previous_id,)).fetchall()
    carried = hidden = 0
    for r in rows:
        if not describe_record(db, canonical_key(r["module"], r["entity_type"]), r["entity_id"], user):
            hidden += 1
            continue
        db.execute(
            "INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by, carried_from_link_id) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (new_id, r["module"], r["entity_type"], r["entity_id"], user["id"], r["id"]))
        carried += 1
    return {"considered": len(rows), "carried": carried, "not_carried": hidden}


def impact(db, user: dict, evidence_id: int) -> "dict | None":
    """What replacing the previous version did to the claims it supported, for the viewer: each link of the previous
    version with its verdict then, and whether it was proposed again on this one and where that stands. None when the item
    is not visible to the viewer. A claim whose record the viewer cannot open is only counted."""
    scope_sql, scope_params = evidence_scope_sql(user)
    item = db.execute(f"SELECT e.id, e.version, e.parent_id, e.status FROM evidence_items e WHERE e.id = %s AND {scope_sql}",
                      [evidence_id, *scope_params]).fetchone()
    if item is None:
        return None
    if not item["parent_id"]:
        return {"evidence_id": evidence_id, "version": item["version"], "previous": None, "claims": [], "hidden": 0,
                "summary": {"claims": 0, "proposed": 0, "awaiting_review": 0, "accepted_again": 0, "not_carried": 0}}
    previous = db.execute("SELECT id, version, status FROM evidence_items WHERE id = %s", (item["parent_id"],)).fetchone()
    old_links = db.execute(
        "SELECT id, module, entity_type, entity_id, review_status, reviewed_at FROM evidence_links "
        "WHERE evidence_id = %s AND deleted_at IS NULL ORDER BY id", (item["parent_id"],)).fetchall()
    new_by_origin = {r["carried_from_link_id"]: r for r in db.execute(
        "SELECT id, carried_from_link_id, review_status FROM evidence_links WHERE evidence_id = %s "
        "AND carried_from_link_id IS NOT NULL AND deleted_at IS NULL", (evidence_id,)).fetchall()}
    claims, hidden = [], 0
    summary = {"claims": len(old_links), "proposed": 0, "awaiting_review": 0, "accepted_again": 0, "not_carried": 0}
    for old in old_links:
        again = new_by_origin.get(old["id"])
        if again is not None:
            summary["proposed"] += 1
            if (again["review_status"] or "pending") == "accepted":
                summary["accepted_again"] += 1
            elif (again["review_status"] or "pending") == "pending":
                summary["awaiting_review"] += 1
        else:
            summary["not_carried"] += 1
        shown = describe_record(db, canonical_key(old["module"], old["entity_type"]), old["entity_id"], user)
        if not shown:
            hidden += 1
            continue
        claims.append({
            "module": old["module"], "entity_type": old["entity_type"], "entity_id": old["entity_id"],
            "title": shown["title"], "url": shown["url"],
            "was": old["review_status"] or "pending", "was_label": OUTCOME_LABELS[old["review_status"] or "pending"],
            "now": (again["review_status"] or "pending") if again is not None else None,
            "now_label": OUTCOME_LABELS[again["review_status"] or "pending"] if again is not None else None,
            "proposed_link_id": again["id"] if again is not None else None})
    return {"evidence_id": evidence_id, "version": item["version"], "previous": {"id": previous["id"], "version": previous["version"]},
            "claims": claims, "hidden": hidden, "summary": summary}
