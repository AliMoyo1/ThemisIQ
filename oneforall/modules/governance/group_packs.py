"""Group packs: a frozen, signed-off set of group figures that can be reopened and exported unchanged (plan 21, slice 6).

A pack does not hold numbers. It holds a manifest of snapshot ids, the rows the figures page showed its author at that
moment, and a hash over those rows. Reading a pack reloads exactly those rows (never "the latest"), recomputes every
snapshot's own hash and the manifest hash, and says whether they still agree. One person proposes a pack and a
different person signs it off; after that the database refuses to change it. A subsidiary that restates a figure later
does not alter the pack: the correction is shown beside it as a notice.

A pack is not a way round the grants. Each reader sees only the subsidiaries they currently hold a figure grant for, only
the measures the relationship still approves, and only the module families their role allows; the rest of the manifest
is left out for them without a trace.
"""
import hashlib
import json
from datetime import datetime

from fastapi import HTTPException

from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.governance import group_figures as gf

MAX_TITLE = 120
MAX_PERIOD = 80


def _table(name: str) -> str:
    return gf._table(name)


def _manifest_hash(parent_org_id: int, title: str, period: str, entities: "list[dict]") -> str:
    payload = json.dumps({"parent": parent_org_id, "title": title, "period": period,
                          "snapshots": sorted([e["org_id"], s["id"], s["hash"]] for e in entities for s in e["snapshots"])},
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def create(db, actor: dict, title, period) -> int:
    """Freeze what the author can see now (own organization plus the subsidiaries they hold grants for)."""
    if not actor.get("org_id") or not has_capability(actor, "group.pack.create"):
        raise HTTPException(403, "Group pack access required")
    if not isinstance(title, str) or not 3 <= len(title.strip()) <= MAX_TITLE:
        raise HTTPException(422, "Give the pack a title of 3 to 120 characters")
    if not isinstance(period, str) or not 1 <= len(period.strip()) <= MAX_PERIOD:
        raise HTTPException(422, "Describe the period the pack covers")
    title, period = title.strip(), period.strip()
    shown = gf.view(db, actor, "group") if gf._children(db, actor) else gf.view(db, actor, "own")
    entities = []
    for entity in shown["entities"]:
        ids = [f["snapshot_id"] for f in entity["figures"]]
        rows = db.execute(
            f"SELECT id, content_hash FROM {_table('group_figure_snapshots')} WHERE source_org_id=%s "
            f"AND id IN ({','.join(['%s'] * len(ids))})", (entity["org_id"], *ids)).fetchall() if ids else []
        entities.append({"org_id": entity["org_id"], "name": entity["name"], "state": entity["state"],
                         "last_reported": entity["last_reported"],
                         "snapshots": [{"id": r["id"], "hash": r["content_hash"]} for r in rows]})
    if not any(e["snapshots"] for e in entities):
        raise HTTPException(409, "There are no published figures to freeze")
    return insert_returning_id(
        db, f"INSERT INTO {_table('group_packs')} (parent_org_id,title,period_text,manifest_json,content_hash,"
        "created_by,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (actor["org_id"], title, period, json.dumps(entities, sort_keys=True),
         _manifest_hash(actor["org_id"], title, period, entities), actor["id"], utcnow().isoformat()))


def review(db, actor: dict, pack_id: int, decision, note) -> dict:
    """A different person signs the pack off (issued) or turns it down (rejected). Either is final."""
    if not actor.get("org_id") or not has_capability(actor, "group.pack.approve"):
        raise HTTPException(403, "Group pack sign-off required")
    if decision not in ("issued", "rejected") or not isinstance(note, str) or not 10 <= len(note.strip()) <= 500:
        raise HTTPException(422, "Choose a decision and record the reason")
    row = db.execute(f"SELECT created_by, status FROM {_table('group_packs')} WHERE id=%s AND parent_org_id=%s",
                     (pack_id, actor["org_id"])).fetchone()
    if not row or row["status"] != "proposed":
        raise HTTPException(404, "Pack not found")
    if row["created_by"] == actor["id"]:
        raise HTTPException(409, "A different person must sign this pack off")
    changed = db.execute(
        f"UPDATE {_table('group_packs')} SET status=%s, reviewed_by=%s, reviewed_at=%s, review_note=%s "
        "WHERE id=%s AND parent_org_id=%s AND status='proposed'",
        (decision, actor["id"], utcnow().isoformat(), note.strip(), pack_id, actor["org_id"])).rowcount
    if not changed:
        raise HTTPException(409, "This pack was already decided")
    return {"id": pack_id, "status": decision}


def listing(db, actor: dict) -> "list[dict]":
    if not actor.get("org_id") or not has_capability(actor, "group.pack.view"):
        raise HTTPException(403, "Group pack access required")
    rows = db.execute(
        f"SELECT p.id,p.title,p.period_text,p.status,p.created_at,p.reviewed_at,p.created_by,"
        "u.full_name AS created_name FROM " + _table("group_packs") + " p LEFT JOIN users u ON u.id=p.created_by "
        "WHERE p.parent_org_id=%s ORDER BY p.id DESC LIMIT 100", (actor["org_id"],)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["can_review"] = (item["status"] == "proposed" and item["created_by"] != actor["id"]
                              and has_capability(actor, "group.pack.approve"))
        out.append(item)
    return out


def _verify(db, pack: dict, entities: "list[dict]") -> bool:
    """True when every snapshot still hashes to what the manifest recorded and the manifest hash still matches."""
    if _manifest_hash(pack["parent_org_id"], pack["title"], pack["period_text"], entities) != pack["content_hash"]:
        return False
    for entity in entities:
        ids = [s["id"] for s in entity["snapshots"]]
        if not ids:
            continue
        rows = db.execute(
            f"SELECT * FROM {_table('group_figure_snapshots')} WHERE source_org_id=%s "
            f"AND id IN ({','.join(['%s'] * len(ids))})", (entity["org_id"], *ids)).fetchall()
        by_id = {r["id"]: r for r in rows}
        for snap in entity["snapshots"]:
            row = by_id.get(snap["id"])
            if row is None or row["content_hash"] != snap["hash"]:
                return False
            expected = gf._hash(entity["org_id"], {"measure_key": row["measure_key"], "state": row["state"],
                                                   "value": row["value"], "window": row["window_text"] or "",
                                                   "detail": json.loads(row["detail_json"] or "{}")},
                                row["as_of"], row["publication_version"])
            if expected != row["content_hash"]:
                return False
    return True


def _log(db, actor: dict, shown_orgs: "set[int]", action: str) -> None:
    """Each subsidiary whose figures a person opened through a pack is recorded in its own access log."""
    for child in gf._children(db, actor):
        if child["org_id"] in shown_orgs:
            gf._log(db, actor, child["relationship_id"], child["org_id"], action)


def log_export(db, actor: dict, pack_id: int, fmt: str) -> None:
    shown = {e["org_id"] for e in get(db, actor, pack_id, log=False)["entities"]}
    _log(db, actor, shown, f"pack_export_{fmt}")


def get(db, actor: dict, pack_id: int, log: bool = True) -> dict:
    if not actor.get("org_id") or not has_capability(actor, "group.pack.view"):
        raise HTTPException(403, "Group pack access required")
    row = db.execute(
        f"SELECT p.*, c.full_name AS created_name, r.full_name AS reviewed_name FROM {_table('group_packs')} p "
        "LEFT JOIN users c ON c.id=p.created_by LEFT JOIN users r ON r.id=p.reviewed_by "
        "WHERE p.id=%s AND p.parent_org_id=%s", (pack_id, actor["org_id"])).fetchone()
    if not row:
        raise HTTPException(404, "Pack not found")
    pack = dict(row)
    manifest = json.loads(pack["manifest_json"])
    verified = _verify(db, pack, manifest)
    families = gf._allowed_families(actor)
    permitted = {c["org_id"]: gf._approved(c["terms_json"]) for c in gf._children(db, actor)}
    entities, corrections = [], []
    for entity in manifest:
        org_id = entity["org_id"]
        own = org_id == actor["org_id"]
        if not own and org_id not in permitted:
            continue
        ids = [s["id"] for s in entity["snapshots"]]
        rows = db.execute(
            f"SELECT * FROM {_table('group_figure_snapshots')} WHERE source_org_id=%s "
            f"AND id IN ({','.join(['%s'] * len(ids))}) ORDER BY measure_key", (org_id, *ids)).fetchall() if ids else []
        rows = [dict(r) for r in rows
                if (families is None or r["module"] in families) and (own or gf._base(r["measure_key"]) in permitted[org_id])]
        figures = [gf._figure({"row": r, "previous": None}) for r in rows]
        entities.append({"org_id": org_id, "name": entity["name"], "state": entity["state"],
                         "last_reported": entity["last_reported"], "figures": figures})
        if rows:
            later = db.execute(
                f"SELECT restates_snapshot_id, measure_key, value, as_of, restatement_reason FROM "
                f"{_table('group_figure_snapshots')} WHERE source_org_id=%s AND restates_snapshot_id IN "
                f"({','.join(['%s'] * len(rows))}) ORDER BY id", (org_id, *[r["id"] for r in rows])).fetchall()
            old = {r["id"]: r for r in rows}
            for fix in later:
                original = old[fix["restates_snapshot_id"]]
                definition = gf.registry.REGISTRY.get(gf._base(fix["measure_key"]))
                corrections.append({"org_id": org_id, "name": entity["name"], "key": fix["measure_key"],
                                    "label": definition.label if definition else fix["measure_key"],
                                    "pack_value": original["value"], "corrected_value": fix["value"],
                                    "corrected_at": fix["as_of"], "reason": fix["restatement_reason"]})
    if log:
        _log(db, actor, {e["org_id"] for e in entities}, "pack_view")
    return {"id": pack["id"], "title": pack["title"], "period": pack["period_text"], "status": pack["status"],
            "created_at": pack["created_at"], "created_by": pack["created_name"] or "",
            "reviewed_at": pack["reviewed_at"], "reviewed_by": pack["reviewed_name"] or "",
            "review_note": pack["review_note"], "content_hash": pack["content_hash"], "verified": verified,
            "entities": entities, "corrections": corrections}


def build_report(actor: dict, org_name: str, pack: dict):
    """The pack as a board report on the shared kit. The same data as the page, so the formats cannot drift."""
    from core.report_kit import theme
    from core.report_kit.model import Actor, Callout, Col, Heading, Meta, Report, Table
    created = datetime.fromisoformat(pack["created_at"])
    final = pack["status"] == "issued"
    meta = Meta(title=pack["title"], module="aria", section="Group pack", tier=theme.BOARD, org_name=org_name,
                subtitle="" if final else "Draft: not signed off",
                scope="Whole group, as far as the reader holds access", period=pack["period"],
                generated_at=created, generated_by=Actor(name=pack["created_by"] or "Unknown user"),
                exported_by=Actor.of_user(actor), exported_at=utcnow(), reference=f"Pack {pack['id']}")
    report = Report(meta)
    sign = (f"Signed off by {pack['reviewed_by']} on {pack['reviewed_at'][:10]}: {pack['review_note']}" if final
            else f"Not signed off ({pack['status']})")
    report.add(Callout("Status", [sign, "Integrity check passed: every figure matches the frozen record."
                                  if pack["verified"] else "Integrity check FAILED: do not rely on this pack.",
                                  f"Fingerprint {pack['content_hash'][:16]}"],
                       kind="note" if pack["verified"] else "limit"))
    columns = [Col("Figure", "label", weight=3), Col("Value", "value", align="right", kind="number", weight=1),
               Col("State", "state", weight=1.5), Col("Window", "window", weight=2), Col("As of", "as_of", kind="date", weight=1.2)]
    for entity in pack["entities"]:
        report.add(Heading(entity["name"]))
        if entity["state"] != "reporting":
            report.add(Callout("Not reporting", [f"Last figures {entity['last_reported'] or 'never published'}."]))
            continue
        rows = [{**f, "state": f["state"].replace("_", " ") + (" (restated)" if f["restated"] else "")}
                for f in entity["figures"]]
        report.add(Table(entity["name"], columns, rows, sheet_name=entity["name"][:28],
                         empty_text="No figures are visible to your role."))
    if pack["corrections"]:
        report.add(Callout("Corrections since this pack was frozen",
                           [f"{c['name']}: {c['label']} was {c['pack_value']:g} in this pack and has been corrected to "
                            f"{c['corrected_value']:g} ({c['reason']})" for c in pack["corrections"]], kind="decision"))
    return report
