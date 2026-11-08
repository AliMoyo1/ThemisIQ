"""DPIA control suggestions. A similarity or inherited link is never assurance."""

from modules.governance.entity_scope import describe_record, describe_records


def quarantine_legacy_guesses(db) -> int:
    """Fail closed on unreviewed system-generated DPIA mitigation edges.

    The old handler used IDs from aria_controls, not the current controls table.
    Keep its rows for audit but change their kind to an unregistered legacy kind.
    They cannot be opened or confirmed as current controls without an explicit
    crosswalk. Human-confirmed and manually created links are left intact.
    """
    cursor = db.execute(
        "UPDATE cross_module_links SET status='candidate', provenance='system_candidate', "
        "target_type='legacy_control', "
        "note=COALESCE(note, 'Historical aria_controls ID; no verified controls crosswalk') "
        "WHERE source_module='sentinel' AND source_type='dpia' "
        "AND target_module='aria' AND target_type='control' AND relationship='mitigates' "
        "AND confirmed_by IS NULL AND ((provenance='system' "
        "AND COALESCE(status, 'confirmed')='confirmed') OR "
        "(provenance='system_candidate' AND status='candidate' "
        "AND note='Historical automated match; review before reliance'))"
    )
    return max(0, cursor.rowcount)


def suggestions(db, user, dpia_id: int) -> list[dict]:
    """Visible, bounded suggestions from reviewed links first, then labelled text matches.

    Existing rejected matches stay dismissed. The returned title is resolved from the
    same owning-module scope rule used by Related Items; a raw link never grants access.
    """
    if not describe_record(db, ("sentinel", "dpia"), dpia_id, user):
        return []
    dpia = db.execute("SELECT ropa_id, data_categories FROM sentinel_dpias WHERE id=%s", (dpia_id,)).fetchone()
    if not dpia:
        return []
    rows = db.execute(
        "SELECT target_id AS control_id, status FROM cross_module_links "
        "WHERE source_module='sentinel' AND source_type='dpia' AND source_id=%s "
        "AND target_module='aria' AND target_type='control' AND relationship='mitigates'",
        (dpia_id,),
    ).fetchall()
    states = {r["control_id"]: r["status"] for r in rows}
    ranked: list[tuple[int, str]] = []
    ropa_id = dpia["ropa_id"]
    if ropa_id and describe_record(db, ("sentinel", "ropa"), ropa_id, user):
        related = db.execute(
            "SELECT target_id FROM cross_module_links WHERE source_module='sentinel' "
            "AND source_type='ropa' AND source_id=%s AND target_module='aria' "
            "AND target_type='control' AND COALESCE(status,'confirmed')='confirmed' "
            "UNION SELECT source_id FROM cross_module_links WHERE target_module='sentinel' "
            "AND target_type='ropa' AND target_id=%s AND source_module='aria' "
            "AND source_type='control' AND COALESCE(status,'confirmed')='confirmed' LIMIT 30",
            (ropa_id, ropa_id),
        ).fetchall()
        ranked.extend((r[0], "Linked to this processing activity") for r in related)
    ranked.extend((cid, "Historical match awaiting review") for cid, status in states.items() if status == "candidate")
    # Text matching is a last resort, never called an established control relationship.
    if not ranked:
        words = [c.strip().lower()[:60] for c in str(dpia["data_categories"] or "").split(",")]
        for word in words[:5]:
            if len(word) < 4:
                continue
            pattern = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            matches = db.execute(
                "SELECT id FROM controls WHERE (LOWER(name) LIKE %s ESCAPE '\\' "
                "OR LOWER(COALESCE(description,'')) LIKE %s ESCAPE '\\') LIMIT 5",
                (pattern, pattern),
            ).fetchall()
            ranked.extend((r[0], "Text match; relevance unverified") for r in matches)
    ids = list(dict.fromkeys(cid for cid, _ in ranked if states.get(cid) not in ("rejected", "confirmed")))[:30]
    described = describe_records(db, ("aria", "control"), ids, user)
    if not described:
        return []
    marks = ",".join(["%s"] * len(described))
    details = {r["id"]: r for r in db.execute(
        f"SELECT id, status, ref, evidence_ref FROM controls WHERE id IN ({marks})", list(described)
    ).fetchall()}
    output = []
    for cid, reason in ranked:
        if cid in described and cid in details and cid not in {item["control_id"] for item in output}:
            row = details[cid]
            output.append({"control_id": cid, "title": described[cid]["title"],
                           "url": described[cid]["url"], "ref": row["ref"],
                           "control_status": row["status"], "reason": reason,
                           "link_status": states.get(cid, "unlinked")})
    return output
