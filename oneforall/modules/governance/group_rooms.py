"""The auditor room (plan 22, C9): a named external auditor reads exactly what a room lists, for a limited time.

The auditor is an ordinary user of the parent organization with the `external_auditor` role, so sign-in, MFA, sessions
and the login audit are the platform's own. A Compliance Manager or Chief GRC Officer proposes a room: who, from when
until when (at most 90 days) and which issued packs and group-published document versions it holds. A different person
approves it; after that its contents do not change. Every item is checked again whenever the auditor opens it, through
the pack and grant rules of the specialist who added it: if that person could no longer open it, neither can the
auditor. The auditor asks questions; a specialist answers, citing only items in the room. Every open, download,
question, answer and decision is recorded.
"""
import json
from datetime import timedelta

from fastapi import HTTPException

from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.evidence import group_documents
from modules.governance import group_figures as gf
from modules.governance import group_packs as gp

MAX_DAYS = 90
MAX_ITEMS = 50
KINDS = ("pack", "publication")


def _table(name: str) -> str:
    return gf._table(name)


def _now() -> str:
    return utcnow().isoformat()


def _text(value, label: str, low: int, high: int) -> str:
    if not isinstance(value, str) or not low <= len(value.strip()) <= high:
        raise HTTPException(422, f"Write the {label} in {low} to {high} characters")
    return value.strip()


def _when(value, label: str) -> str:
    from datetime import datetime, timezone
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, f"Choose the {label}") from None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.replace(microsecond=0).isoformat()


def _person(db, user_id: int, org_id: int) -> "dict | None":
    """A user of this organization as the access rules see them now: active, with their current roles."""
    row = db.execute("SELECT id, org_id, business_unit_id, full_name FROM users WHERE id=%s AND org_id=%s "
                     "AND is_active=1 AND deleted_at IS NULL", (user_id, org_id)).fetchone()
    if not row:
        return None
    roles = [r["role_key"] for r in db.execute("SELECT role_key FROM user_roles WHERE user_id=%s", (user_id,)).fetchall()]
    return {"id": row["id"], "org_id": row["org_id"], "business_unit_id": row["business_unit_id"],
            "full_name": row["full_name"], "roles": roles, "is_super_admin": False}


def _event(db, room: dict, actor: dict, action: str, detail: str = "") -> None:
    db.execute(f"INSERT INTO {_table('group_audit_room_events')} (room_id,parent_org_id,actor_id,action,detail,created_at) "
               "VALUES (%s,%s,%s,%s,%s,%s)", (room["id"], room["parent_org_id"], actor["id"], action, detail, _now()))


def _notify(db, user_ids, title: str, message: str, link: str) -> None:
    for user_id in user_ids:
        db.execute("INSERT INTO notifications (user_id, module, title, message, link) VALUES (%s, %s, %s, %s, %s)",
                   (user_id, "governance", title, message, link))


def _room(db, actor: dict, room_id: int) -> dict:
    row = db.execute(f"SELECT * FROM {_table('group_audit_rooms')} WHERE id=%s AND parent_org_id=%s",
                     (room_id, actor.get("org_id"))).fetchone()
    if not row:
        raise HTTPException(404, "Room not found")
    return dict(row)


def _staff(actor: dict) -> bool:
    return has_capability(actor, "group.room.manage") or has_capability(actor, "group.room.approve")


def _open_for(room: dict, actor: dict) -> bool:
    """The auditor named on an approved room, inside its window."""
    now = _now()
    return (room["status"] == "open" and room["auditor_user_id"] == actor["id"]
            and has_capability(actor, "group.room.enter") and room["starts_at"] <= now < room["ends_at"])


def _visible(db, actor: dict, room_id: int) -> dict:
    """The room for its staff, or for its auditor while it is open. Anyone else, and the auditor outside the window,
    gets the same answer as for a room that does not exist."""
    room = _room(db, actor, room_id)
    if _staff(actor) or _open_for(room, actor):
        return room
    raise HTTPException(404, "Room not found")


# ── proposing and deciding ─────────────────────────────────────────────────

def propose(db, actor: dict, title, auditor_user_id, starts_at, ends_at) -> int:
    if not actor.get("org_id") or not has_capability(actor, "group.room.manage"):
        raise HTTPException(403, "Auditor room management required")
    name = _text(title, "room title", 3, 120)
    if not isinstance(auditor_user_id, int):
        raise HTTPException(422, "Choose the auditor")
    auditor = _person(db, auditor_user_id, actor["org_id"])
    if not auditor or "external_auditor" not in auditor["roles"]:
        raise HTTPException(404, "Auditor not found")
    start, end = _when(starts_at, "start"), _when(ends_at, "end")
    if end <= start or end <= _now():
        raise HTTPException(422, "The room must end after it starts, in the future")
    from datetime import datetime
    if datetime.fromisoformat(end) - datetime.fromisoformat(start) > timedelta(days=MAX_DAYS):
        raise HTTPException(422, f"A room is open for at most {MAX_DAYS} days")
    room_id = insert_returning_id(
        db, f"INSERT INTO {_table('group_audit_rooms')} (parent_org_id,title,auditor_user_id,starts_at,ends_at,status,"
        "proposed_by,created_at) VALUES (%s,%s,%s,%s,%s,'proposed',%s,%s)",
        (actor["org_id"], name, auditor_user_id, start, end, actor["id"], _now()))
    _event(db, _room(db, actor, room_id), actor, "proposed", name)
    return room_id


def candidates(db, actor: dict) -> dict:
    """What this specialist may put in a room: issued packs and the released document versions they can open."""
    if not actor.get("org_id") or not has_capability(actor, "group.room.manage"):
        raise HTTPException(403, "Auditor room management required")
    packs = []
    if has_capability(actor, "group.pack.view"):
        packs = [{"id": p["id"], "title": f"{p['title']} ({p['period_text']})"}
                 for p in gp.listing(db, actor) if p["status"] == "issued"]
    documents = [{"id": d["id"], "title": f"{d['title']} v{d['version']} ({d['source_name']})"}
                 for d in group_documents.catalogue(db, actor, page_size=100)]
    auditors = [dict(r) for r in db.execute(
        "SELECT DISTINCT u.id, u.full_name FROM users u JOIN user_roles ur ON ur.user_id=u.id "
        "WHERE u.org_id=%s AND ur.role_key='external_auditor' AND u.is_active=1 AND u.deleted_at IS NULL "
        "ORDER BY u.full_name, u.id LIMIT 100", (actor["org_id"],)).fetchall()]
    return {"packs": packs, "documents": documents, "auditors": auditors}


def _check_item(db, adder: "dict | None", kind: str, ref_id: int, *, download: bool = False):
    """The item as the person who added it could open it now, or None. Never raises for an unavailable item."""
    if adder is None:
        return None
    try:
        if kind == "pack":
            if not has_capability(adder, "group.pack.view"):
                return None
            pack = gp.get(db, adder, ref_id, log=False)
            return pack if pack["status"] == "issued" else None
        row, item = group_documents.released_item(db, adder, ref_id, download=download)
        return {"row": row, "item": item}
    except HTTPException:
        return None


def add_item(db, actor: dict, room_id: int, kind, ref_id, allow_download=False) -> int:
    if not has_capability(actor, "group.room.manage"):
        raise HTTPException(403, "Auditor room management required")
    room = _room(db, actor, room_id)
    if room["status"] != "proposed":
        raise HTTPException(409, "A room's contents are fixed once it is approved")
    if kind not in KINDS or not isinstance(ref_id, int) or ref_id <= 0 or not isinstance(allow_download, bool):
        raise HTTPException(422, "Choose an issued pack or a released document")
    if _check_item(db, actor, kind, ref_id) is None:
        raise HTTPException(404, "Item not found")
    count = db.execute(f"SELECT COUNT(*) FROM {_table('group_audit_room_items')} WHERE room_id=%s",
                       (room_id,)).fetchone()[0]
    if count >= MAX_ITEMS:
        raise HTTPException(409, f"A room holds at most {MAX_ITEMS} items")
    if db.execute(f"SELECT id FROM {_table('group_audit_room_items')} WHERE room_id=%s AND kind=%s AND ref_id=%s",
                  (room_id, kind, ref_id)).fetchone():
        raise HTTPException(409, "This item is already in the room")
    item_id = insert_returning_id(
        db, f"INSERT INTO {_table('group_audit_room_items')} (room_id,parent_org_id,kind,ref_id,allow_download,added_by,"
        "added_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (room_id, room["parent_org_id"], kind, ref_id, 1 if allow_download else 0, actor["id"], _now()))
    _event(db, room, actor, "item_added", f"{kind}:{ref_id}")
    return item_id


def decide(db, actor: dict, room_id: int, decision, reason) -> str:
    if not has_capability(actor, "group.room.approve"):
        raise HTTPException(403, "Auditor room approval required")
    room = _room(db, actor, room_id)
    if room["status"] != "proposed":
        raise HTTPException(409, "This room was already decided")
    if room["proposed_by"] == actor["id"]:
        raise HTTPException(409, "A different person must approve the room")
    if decision not in ("open", "rejected"):
        raise HTTPException(422, "Approve or reject the room")
    why = _text(reason, "reason", 10, 500)
    if decision == "open" and not db.execute(f"SELECT id FROM {_table('group_audit_room_items')} WHERE room_id=%s "
                                             "LIMIT 1", (room_id,)).fetchone():
        raise HTTPException(409, "Add at least one item before approving the room")
    changed = db.execute(f"UPDATE {_table('group_audit_rooms')} SET status=%s,approved_by=%s,approved_at=%s,"
                         "decision_reason=%s WHERE id=%s AND parent_org_id=%s AND status='proposed'",
                         (decision, actor["id"], _now(), why, room_id, room["parent_org_id"])).rowcount
    if not changed:
        raise HTTPException(409, "This room was already decided")
    _event(db, room, actor, "approved" if decision == "open" else "rejected", why)
    if decision == "open":
        _notify(db, [room["auditor_user_id"]], "An audit room is open for you",
                f"{room['title']} is open from {room['starts_at'][:10]} until {room['ends_at'][:10]}.",
                f"/governance/group/rooms/?room={room_id}")
    return decision


def close(db, actor: dict, room_id: int, reason) -> None:
    if not _staff(actor):
        raise HTTPException(403, "Auditor room management required")
    room = _room(db, actor, room_id)
    if room["status"] not in ("proposed", "open"):
        raise HTTPException(409, "This room is already closed")
    why = _text(reason, "reason", 10, 500)
    db.execute(f"UPDATE {_table('group_audit_rooms')} SET status='closed',closed_by=%s,closed_at=%s,close_reason=%s "
               "WHERE id=%s AND parent_org_id=%s AND status IN ('proposed','open')",
               (actor["id"], _now(), why, room_id, room["parent_org_id"]))
    _event(db, room, actor, "closed", why)


# ── reading ────────────────────────────────────────────────────────────────

def _items(db, room: dict) -> "list[dict]":
    return [dict(r) for r in db.execute(
        f"SELECT * FROM {_table('group_audit_room_items')} WHERE room_id=%s AND parent_org_id=%s ORDER BY id",
        (room["id"], room["parent_org_id"])).fetchall()]


def _describe(db, room: dict, item: dict) -> dict:
    checked = _check_item(db, _person(db, item["added_by"], room["parent_org_id"]), item["kind"], item["ref_id"])
    if checked is None:
        return {"id": item["id"], "kind": item["kind"], "available": False, "title": None, "can_download": False}
    if item["kind"] == "pack":
        title = f"{checked['title']} ({checked['period']})"
    else:
        title = f"{checked['row']['title']} v{checked['row']['version']} ({checked['row']['source_name']})"
    return {"id": item["id"], "kind": item["kind"], "available": True, "title": title,
            "can_download": bool(item["allow_download"])}


def listing(db, actor: dict) -> dict:
    if not actor.get("org_id"):
        raise HTTPException(403, "Organization required")
    if _staff(actor):
        rows = db.execute(f"SELECT r.*, u.full_name AS auditor_name FROM {_table('group_audit_rooms')} r "
                          "LEFT JOIN users u ON u.id=r.auditor_user_id WHERE r.parent_org_id=%s "
                          "ORDER BY r.id DESC LIMIT 100", (actor["org_id"],)).fetchall()
    elif has_capability(actor, "group.room.enter"):
        rows = [r for r in db.execute(
            f"SELECT r.*, u.full_name AS auditor_name FROM {_table('group_audit_rooms')} r "
            "LEFT JOIN users u ON u.id=r.auditor_user_id WHERE r.parent_org_id=%s AND r.auditor_user_id=%s "
            "AND r.status='open' ORDER BY r.id DESC LIMIT 100", (actor["org_id"], actor["id"])).fetchall()
            if _open_for(dict(r), actor)]
    else:
        raise HTTPException(403, "Auditor room access required")
    return {"items": [{"id": r["id"], "title": r["title"], "status": r["status"], "auditor": r["auditor_name"] or "",
                       "starts_at": r["starts_at"], "ends_at": r["ends_at"]} for r in rows],
            "can_manage": has_capability(actor, "group.room.manage"),
            "can_approve": has_capability(actor, "group.room.approve")}


def detail(db, actor: dict, room_id: int) -> dict:
    room = _visible(db, actor, room_id)
    staff = _staff(actor)
    if not staff:
        _event(db, room, actor, "entered")
    items = [_describe(db, room, i) for i in _items(db, room)]
    if not staff:  # the auditor is not told what used to be in the room
        items = [i for i in items if i["available"]]
    messages = [dict(m) for m in db.execute(
        f"SELECT m.id, m.kind, m.body, m.cites_json, m.reply_to, m.created_at, u.full_name AS author "
        f"FROM {_table('group_audit_room_messages')} m LEFT JOIN users u ON u.id=m.author_id "
        "WHERE m.room_id=%s AND m.parent_org_id=%s ORDER BY m.id", (room_id, room["parent_org_id"])).fetchall()]
    for message in messages:
        message["cites"] = json.loads(message.pop("cites_json") or "[]")
    out = {"id": room["id"], "title": room["title"], "status": room["status"], "starts_at": room["starts_at"],
           "ends_at": room["ends_at"], "items": items, "messages": messages,
           "can_ask": _open_for(room, actor),
           "can_answer": room["status"] == "open" and has_capability(actor, "group.room.manage"),
           "can_add": room["status"] == "proposed" and has_capability(actor, "group.room.manage"),
           "can_decide": (room["status"] == "proposed" and has_capability(actor, "group.room.approve")
                          and room["proposed_by"] != actor["id"]),
           "can_close": room["status"] in ("proposed", "open") and staff}
    if staff:
        out["events"] = [dict(e) for e in db.execute(
            f"SELECT e.action, e.detail, e.created_at, u.full_name AS actor FROM {_table('group_audit_room_events')} e "
            "LEFT JOIN users u ON u.id=e.actor_id WHERE e.room_id=%s AND e.parent_org_id=%s ORDER BY e.id DESC LIMIT 200",
            (room_id, room["parent_org_id"])).fetchall()]
    return out


def _item(db, actor: dict, room_id: int, item_id: int, *, download: bool = False):
    room = _visible(db, actor, room_id)
    row = db.execute(f"SELECT * FROM {_table('group_audit_room_items')} WHERE id=%s AND room_id=%s AND parent_org_id=%s",
                     (item_id, room_id, room["parent_org_id"])).fetchone()
    if not row or (download and not row["allow_download"]):
        raise HTTPException(404, "Item not found")
    adder = _person(db, row["added_by"], room["parent_org_id"])
    checked = _check_item(db, adder, row["kind"], row["ref_id"], download=download)
    if checked is None:
        raise HTTPException(404, "Item not found")
    return room, dict(row), adder, checked


def _log_source(db, room: dict, actor: dict, adder: dict, item: dict, checked, action: str) -> None:
    """Each subsidiary whose data the auditor read is told, in its own access log, as for any other reader."""
    if item["kind"] == "pack":
        shown = {e["org_id"] for e in checked["entities"]}
        for child in gf._children(db, adder):
            if child["org_id"] in shown:
                gf._log(db, actor, child["relationship_id"], child["org_id"], f"room_{action}")
    else:
        group_documents.access_event(db, checked["row"], actor, f"room_{action}")
    _event(db, room, actor, action, f"{item['kind']}:{item['ref_id']}")


def open_item(db, actor: dict, room_id: int, item_id: int) -> dict:
    room, item, adder, checked = _item(db, actor, room_id, item_id)
    _log_source(db, room, actor, adder, item, checked, "open")
    if item["kind"] == "pack":
        return {"kind": "pack", "pack": checked, "can_download": bool(item["allow_download"])}
    row = checked["row"]
    return {"kind": "publication", "can_download": bool(item["allow_download"]),
            "document": {"title": row["title"], "version": row["version"], "category": row["category"],
                         "source_name": row["source_name"], "classification": row["classification"]}}


def download_item(db, actor: dict, room_id: int, item_id: int):
    """(kind, payload): the pack as seen by the person who added it, or the released document's stored file."""
    room, item, adder, checked = _item(db, actor, room_id, item_id, download=True)
    _log_source(db, room, actor, adder, item, checked, "download")
    return item["kind"], (checked if item["kind"] == "pack" else checked["item"]), adder


# ── questions and answers ──────────────────────────────────────────────────

def post_message(db, actor: dict, room_id: int, body, reply_to=None, cites=None) -> int:
    room = _visible(db, actor, room_id)
    text = _text(body, "message", 3, 2000)
    if _open_for(room, actor):
        kind, reply_to, cites = "question", None, []
        people = [r["id"] for r in db.execute(
            "SELECT id FROM users WHERE id IN (%s) AND is_active=1", (room["proposed_by"],)).fetchall()]
    elif room["status"] == "open" and has_capability(actor, "group.room.manage"):
        kind = "answer"
        if not isinstance(reply_to, int) or not db.execute(
                f"SELECT id FROM {_table('group_audit_room_messages')} WHERE id=%s AND room_id=%s AND kind='question'",
                (reply_to, room_id)).fetchone():
            raise HTTPException(422, "Answer one of the auditor's questions")
        allowed = {i["id"] for i in _items(db, room)}
        if (not isinstance(cites, list) or not 1 <= len(cites) <= 10 or len(set(cites)) != len(cites)
                or not all(isinstance(c, int) and c in allowed for c in cites)):
            raise HTTPException(422, "Cite at least one item in this room")
        people = [room["auditor_user_id"]]
    else:
        raise HTTPException(403, "Only the room's auditor asks, and its specialists answer, while it is open")
    message_id = insert_returning_id(
        db, f"INSERT INTO {_table('group_audit_room_messages')} (room_id,parent_org_id,author_id,kind,body,cites_json,"
        "reply_to,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (room_id, room["parent_org_id"], actor["id"], kind, text, json.dumps(sorted(cites)), reply_to, _now()))
    _event(db, room, actor, kind, str(message_id))
    _notify(db, people, "New question in an audit room" if kind == "question" else "Your question was answered",
            room["title"], f"/governance/group/rooms/?room={room_id}")
    return message_id
