"""
AI governance G3: the AI controls a use is assessed against, which canonical control each one maps to, and the proof
the Evidence Vault holds for that canonical control.

An AI control (the ORM catalogue) is not a second control inventory: a reviewer maps it to a canonical control, and the
proof attached to that control in the Vault is then shown against the AI control. A mapping is never guessed: a
suggestion is only a suggestion until a reviewer confirms it. Applicable, implemented and proof are shown as separate
facts; this module does not compute a score and does not mark anything accepted.
"""
import re

from core.rbac import has_capability
from core.timeutils import utcnow
from modules.ai_governance import service
from modules.ai_governance.service import APP, ServiceError
from modules.governance.entity_scope import describe_record, entity_scope_sql, may_view_kind

_AIMS = ("orm", "aims")


def _words(text) -> set:
    return {w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(w) > 3}


# ── Mappings ────────────────────────────────────────────────────────────────

def can_view(user) -> bool:
    """True when the viewer may open AI management assessments, so an empty list can be told apart from a denied one."""
    return may_view_kind(user, _AIMS)


def _require_mapper(user):
    service._require(user, "ai_use.review")
    if not can_view(user):
        raise ServiceError(403, "Access denied.")


def map_control(db, user, ai_control_id, canonical_control_id, note=None) -> dict:
    """A reviewer confirms that an AI control corresponds to a canonical control."""
    _require_mapper(user)
    for value in (ai_control_id, canonical_control_id):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ServiceError(400, "Choose an AI control and a canonical control.")
    scope, params = entity_scope_sql(("orm", "ai_control"), user, "c")
    control = db.execute(f"SELECT c.id, c.title FROM ai_control_catalogue c WHERE c.id = %s AND {scope}", [ai_control_id, *params]).fetchone()
    canonical = db.execute("SELECT id, title FROM canonical_controls WHERE id = %s AND is_active = 1", (canonical_control_id,)).fetchone()
    if not control or not canonical:
        raise ServiceError(404, "Control not found.")
    note = (note or "").strip()[:500] if isinstance(note, str) or note is None else ""
    now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    made = db.execute(
        "INSERT INTO ai_control_mappings (ai_control_id, canonical_control_id, note, created_by, created_at) "
        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", (ai_control_id, canonical_control_id, note or None, user["id"], now)).rowcount
    return {"created": made == 1, "events": [], "audit": [] if not made else [(
        "ai_control_mapped", "ai_control", ai_control_id, f"{control['title']} -> {canonical['title']}")]}


def unmap_control(db, user, ai_control_id, canonical_control_id) -> dict:
    _require_mapper(user)
    done = db.execute("DELETE FROM ai_control_mappings WHERE ai_control_id = %s AND canonical_control_id = %s",
                      (ai_control_id, canonical_control_id)).rowcount
    if done != 1:
        raise ServiceError(404, "That mapping does not exist.")
    return {"events": [], "audit": [("ai_control_unmapped", "ai_control", ai_control_id, f"canonical control {canonical_control_id}")]}


def search_canonical(db, user, q, limit=20) -> list:
    """Active canonical controls matching a few typed letters, for a reviewer to pick from."""
    _require_mapper(user)
    q = (q or "").strip()
    if len(q) < 2:
        return []
    from core.sql_like import ci_like, like_pattern
    from modules.governance.data_service import bu_scope_ids
    sql = f"SELECT id, ref, title FROM canonical_controls WHERE is_active = 1 AND ({ci_like('title')} OR {ci_like('ref')})"
    params = [like_pattern(q), like_pattern(q)]
    scope = bu_scope_ids(user)
    if scope is not None:
        sql += f" AND (business_unit_id IS NULL OR business_unit_id IN ({','.join(['%s'] * len(scope))}))"
        params += list(scope)
    rows = db.execute(sql + " ORDER BY title LIMIT %s", [*params, max(1, min(int(limit), 50))]).fetchall()
    return [{"id": r["id"], "ref": r["ref"], "title": r["title"]} for r in rows]


def suggest_mappings(db, user, ai_control_id, limit=5) -> list:
    """Canonical controls whose title shares words with an AI control's: candidates for a reviewer to confirm, never stored."""
    _require_mapper(user)
    scope, params = entity_scope_sql(("orm", "ai_control"), user, "c")
    control = db.execute(f"SELECT c.title, c.description FROM ai_control_catalogue c WHERE c.id = %s AND {scope}", [ai_control_id, *params]).fetchone()
    if not control:
        raise ServiceError(404, "Control not found.")
    want = _words(control["title"])
    mapped = {r[0] for r in db.execute("SELECT canonical_control_id FROM ai_control_mappings WHERE ai_control_id = %s", (ai_control_id,)).fetchall()}
    found = []
    for row in db.execute("SELECT id, ref, title FROM canonical_controls WHERE is_active = 1 ORDER BY id LIMIT 2000").fetchall():
        if row["id"] in mapped:
            continue
        shared = want & _words(row["title"])
        if len(shared) >= 2 or (shared and len(want) == 1):
            found.append((len(shared) / max(len(want), 1), row["title"].lower(), {
                "id": row["id"], "ref": row["ref"], "title": row["title"], "reason": "Shares: " + ", ".join(sorted(shared))}))
    found.sort(key=lambda t: (-t[0], t[1]))
    return [t[2] for t in found[:max(1, min(int(limit), 10))]]


# ── The controls of one use, with their proof ───────────────────────────────

def _proof(db, user, canonical_ids) -> dict:
    """canonical control id -> {"current", "expired", "verified"}: the Vault items the viewer may open that are attached to it."""
    out = {cid: {"current": 0, "expired": 0, "verified": 0, "items": []} for cid in canonical_ids}
    if not canonical_ids or not may_view_kind(user, ("evidence", "item")):
        return out
    scope, params = entity_scope_sql(("evidence", "item"), user, "e")
    marks = ",".join(["%s"] * len(canonical_ids))
    today = utcnow().strftime("%Y-%m-%d")
    rows = db.execute(
        "SELECT l.entity_id AS control_id, e.id, e.title, e.status, e.expiry_date, e.version, e.verified_at "
        "FROM evidence_links l JOIN evidence_items e ON e.id = l.evidence_id "
        f"WHERE l.module = 'grid' AND l.entity_type = 'canonical_control' AND l.entity_id IN ({marks}) "
        f"AND l.deleted_at IS NULL AND {scope} ORDER BY e.updated_at DESC", [*canonical_ids, *params]).fetchall()
    for r in rows:
        expired = bool(r["expiry_date"]) and str(r["expiry_date"])[:10] < today
        entry = out[r["control_id"]]
        entry["expired" if expired else "current"] += 1
        if r["verified_at"] and not expired:
            entry["verified"] += 1
        entry["items"].append({"id": r["id"], "title": r["title"], "version": r["version"], "expired": expired,
                               "verified": bool(r["verified_at"]), "expires": str(r["expiry_date"] or "")[:10] or None,
                               "url": f"/evidence/?open=item:{r['id']}"})
    return out


def use_controls(db, user, application_id: int) -> "list | None":
    """For each AI control in the use's management assessments: whether it is in scope and implemented, which canonical
    controls it maps to, and the proof held for them. None when the viewer may not open the application."""
    service._require(user, "ai_use.view")
    if not describe_record(db, APP, application_id, user):
        return None
    if not can_view(user):
        return []
    scope, params = entity_scope_sql(_AIMS, user, "m")
    rows = db.execute(
        "SELECT r.id AS risk_id, r.in_scope, r.implemented, r.status, m.id AS assessment_id, m.ref, m.title AS assessment_title, "
        "c.id AS control_id, c.ref AS control_ref, c.title AS control_title "
        "FROM aims_assessments m JOIN aims_risks r ON r.assessment_id = m.id "
        "JOIN ai_control_catalogue c ON c.id = r.catalogue_control_id "
        f"WHERE m.application_id = %s AND {scope} ORDER BY m.id, r.id LIMIT 200", [application_id, *params]).fetchall()
    control_ids = sorted({r["control_id"] for r in rows})
    maps: dict = {}
    if control_ids:
        marks = ",".join(["%s"] * len(control_ids))
        for m in db.execute(
            f"SELECT mp.ai_control_id, k.id, k.ref, k.title FROM ai_control_mappings mp JOIN canonical_controls k ON k.id = mp.canonical_control_id "
            f"WHERE mp.ai_control_id IN ({marks}) ORDER BY k.title", control_ids).fetchall():
            maps.setdefault(m["ai_control_id"], []).append({"id": m["id"], "ref": m["ref"], "title": m["title"]})
    proof = _proof(db, user, sorted({k["id"] for ks in maps.values() for k in ks}))
    out = []
    for r in rows:
        mapped = maps.get(r["control_id"], [])
        current = sum(proof[k["id"]]["current"] for k in mapped)
        expired = sum(proof[k["id"]]["expired"] for k in mapped)
        verified = sum(proof[k["id"]]["verified"] for k in mapped)
        items = [i for k in mapped for i in proof[k["id"]]["items"]]
        out.append({
            "assessment": {"id": r["assessment_id"], "ref": r["ref"], "title": r["assessment_title"], "url": "/orm/aims"},
            "control": {"id": r["control_id"], "ref": r["control_ref"], "title": r["control_title"]},
            "applicable": bool(r["in_scope"]), "implemented": bool(r["implemented"]), "status": r["status"],
            "mapped_to": mapped, "mapped": bool(mapped),
            "proof": {"current": current, "expired": expired, "verified": verified, "items": items[:10]},
        })
    return out
