"""
One For All — Cross-module link utilities.

Provides helper functions for creating and querying links between
entities across modules (ARIA, GRID, BCM, Sentinel).
"""
import logging
from database import get_db

log = logging.getLogger("oneforall.links")

_VALID_MODULES = frozenset({
    "aria", "grid", "bcm", "sentinel", "platform", "evidence", "erm", "orm", "governance",
})

# Each edge is stored once, in one direction, with an active verb: verb -> (label read from the source
# side, label read from the target side). The target side of an edge shows the inverse label, so
# "AIIA assesses application" reads "assessed by AIIA" on the application. The first nine verbs predate the AI
# governance work; the rest are its typed edges.
RELATIONSHIP_LABELS = {
    "related":      ("related to", "related to"),
    "triggers":     ("triggers", "triggered by"),
    "evidence_for": ("is evidence for", "has evidence"),
    "implements":   ("implements", "implemented by"),
    "mitigates":    ("mitigates", "mitigated by"),
    "escalated_to": ("escalated to", "escalated from"),
    "derived_from": ("derived from", "source of"),
    "audits":       ("audits", "audited by"),
    "elevated_to":  ("elevated to", "elevated from"),
    "uses_data":    ("uses data", "data used by"),
    "provided_by":  ("provided by", "provides"),
    "supports":     ("supports", "supported by"),
    "assesses":     ("assesses", "assessed by"),
    "covers":       ("covers", "covered by"),
    "affects":      ("affects", "affected by"),
    "impacts":      ("impacts", "impacted by"),
    "depends_on":   ("depends on", "needed by"),
}
_VALID_RELATIONSHIPS = frozenset(RELATIONSHIP_LABELS)


def create_cross_module_link(
    source_module: str,
    source_type: str,
    source_id: int,
    target_module: str,
    target_type: str,
    target_id: int,
    relationship: str = "related",
    user_id: int = None,
    db=None,
    provenance: str = "system",
) -> int | None:
    """
    Insert a row into cross_module_links with validation. This is the entry for links the platform makes
    itself (an event handler, a workflow); people's links go through modules/governance/relationships.py, which
    also checks who may see both ends. `provenance` says which: "system" for this path.

    If `db` is provided, use that connection (caller is responsible for commit/close).
    Otherwise, open a fresh connection, commit, and close it internally.

    Returns the new link ID, or None if a duplicate already exists.
    """
    if source_module not in _VALID_MODULES or target_module not in _VALID_MODULES:
        log.warning(
            "Invalid module in link: %s -> %s", source_module, target_module
        )
        return None
    if relationship not in _VALID_RELATIONSHIPS:
        relationship = "related"

    _own_db = db is None
    if _own_db:
        db = get_db()
    try:
        # Atomic dedup: rely on UNIQUE index idx_xlinks_dedup_uq.
        # ON CONFLICT DO NOTHING collapses the check-then-insert race into one statement.
        dedup_key = (
            source_module, source_type, source_id,
            target_module, target_type, target_id, relationship,
        )
        cur = db.execute(
            "INSERT INTO cross_module_links "
            "(source_module, source_type, source_id, "
            " target_module, target_type, target_id, "
            " relationship, created_by, provenance) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
            (*dedup_key, user_id, provenance),
        )
        row = cur.fetchone()
        if row is None:
            # ON CONFLICT — row already existed; fetch its id.
            existing = db.execute(
                "SELECT id FROM cross_module_links "
                "WHERE source_module=%s AND source_type=%s AND source_id=%s "
                "AND target_module=%s AND target_type=%s AND target_id=%s "
                "AND relationship=%s",
                dedup_key,
            ).fetchone()
            return existing["id"] if existing else None
        link_id = row["id"]
        if _own_db:
            db.commit()
        log.info(
            "Created cross-module link #%d: %s/%s/%d -[%s]-> %s/%s/%d",
            link_id, source_module, source_type, source_id,
            relationship, target_module, target_type, target_id,
        )
        return link_id
    except Exception as exc:
        log.exception("Failed to create cross-module link: %s", exc)
        return None
    finally:
        if _own_db:
            db.close()


def get_links_for_entity(
    module: str, entity_type: str, entity_id: int,
    direction: str = "both",
) -> list[dict]:
    """
    Return all cross-module links involving a specific entity.

    direction: "outgoing" (entity is source), "incoming" (entity is target),
               "both" (default).
    """
    db = get_db()
    try:
        results = []
        if direction in ("outgoing", "both"):
            rows = db.execute(
                "SELECT * FROM cross_module_links "
                "WHERE source_module=%s AND source_type=%s AND source_id=%s",
                (module, entity_type, entity_id),
            ).fetchall()
            results.extend(dict(r) for r in rows)

        if direction in ("incoming", "both"):
            rows = db.execute(
                "SELECT * FROM cross_module_links "
                "WHERE target_module=%s AND target_type=%s AND target_id=%s",
                (module, entity_type, entity_id),
            ).fetchall()
            results.extend(dict(r) for r in rows)

        return results
    finally:
        db.close()


def get_linked_entity_ids(
    module: str, entity_type: str, entity_id: int,
    target_module: str = None, target_type: str = None,
) -> list[int]:
    """
    Return IDs of entities linked to a given source entity.

    Optionally filter by target module/type.
    """
    db = get_db()
    try:
        sql = (
            "SELECT target_id FROM cross_module_links "
            "WHERE source_module=%s AND source_type=%s AND source_id=%s"
        )
        params: list = [module, entity_type, entity_id]
        if target_module:
            sql += " AND target_module=%s"
            params.append(target_module)
        if target_type:
            sql += " AND target_type=%s"
            params.append(target_type)
        rows = db.execute(sql, params).fetchall()
        return [r[0] for r in rows]
    finally:
        db.close()
