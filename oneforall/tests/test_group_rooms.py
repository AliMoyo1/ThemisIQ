"""The auditor room (plan 22, C9): named, time-boxed, approved by a second person, rechecked on every read."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from modules.governance import group_packs as gp
from modules.governance import group_rooms as rooms
from tests.test_group_packs import _make, _user, world  # noqa: F401 (fixture)


def _at(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(tzinfo=None, microsecond=0).isoformat()


@pytest.fixture
def room_world(world):
    db, parent, child, relation, users, snaps = world
    users["auditor"] = _user(db, parent, "rm_auditor", "external_auditor")
    users["other_auditor"] = _user(db, parent, "rm_other_auditor", "external_auditor")
    pack_id = _make(db, users)
    gp.review(db, users["comp"], pack_id, "issued", "Checked against the sources")
    db.commit()
    return db, parent, child, relation, users, pack_id


def _open_room(db, users, pack_id, *, start=-1, end=30, download=False):
    room = rooms.propose(db, users["grc"], "Year end audit", users["auditor"]["id"], _at(start), _at(end))
    item = rooms.add_item(db, users["grc"], room, "pack", pack_id, download)
    rooms.decide(db, users["comp"], room, "open", "Scope agreed with the auditor")
    db.commit()
    return room, item


def test_a_room_is_proposed_for_a_named_external_auditor_within_ninety_days(room_world):
    db, parent, child, relation, users, pack_id = room_world
    for who, auditor, start, end, code in (
            ("emp", users["auditor"]["id"], _at(0), _at(10), 403),
            ("audit", users["auditor"]["id"], _at(0), _at(10), 403),
            ("grc", users["comp"]["id"], _at(0), _at(10), 404),
            ("grc", users["child_grc"]["id"], _at(0), _at(10), 404),
            ("grc", users["auditor"]["id"], _at(0), _at(91), 422),
            ("grc", users["auditor"]["id"], _at(-10), _at(-1), 422),
            ("grc", users["auditor"]["id"], _at(5), _at(2), 422)):
        with pytest.raises(HTTPException) as bad:
            rooms.propose(db, users[who], "Year end audit", auditor, start, end)
        assert bad.value.status_code == code, (who, code)
    assert rooms.propose(db, users["grc"], "Year end audit", users["auditor"]["id"], _at(0), _at(90))


def test_a_second_person_approves_and_then_the_contents_are_fixed(room_world):
    db, parent, child, relation, users, pack_id = room_world
    room = rooms.propose(db, users["grc"], "Year end audit", users["auditor"]["id"], _at(-1), _at(30))
    db.commit()
    with pytest.raises(HTTPException) as empty:
        rooms.decide(db, users["comp"], room, "open", "Scope agreed with the auditor")
    assert empty.value.status_code == 409
    draft = _make(db, users, title="Draft pack")
    with pytest.raises(HTTPException) as unissued:
        rooms.add_item(db, users["grc"], room, "pack", draft)
    assert unissued.value.status_code == 404, "only an issued pack goes in a room"
    rooms.add_item(db, users["grc"], room, "pack", pack_id)
    with pytest.raises(HTTPException) as twice:
        rooms.add_item(db, users["grc"], room, "pack", pack_id)
    assert twice.value.status_code == 409
    with pytest.raises(HTTPException) as own:
        rooms.decide(db, {**users["grc"], "roles": ["grc_officer", "compliance_manager"]}, room, "open", "Approving my own")
    assert own.value.status_code == 409
    with pytest.raises(HTTPException) as auditor_cannot:
        rooms.decide(db, users["auditor"], room, "open", "Approving my own room")
    assert auditor_cannot.value.status_code == 403
    assert rooms.listing(db, users["auditor"])["items"] == [], "nothing is shown before approval"
    assert rooms.decide(db, users["dpo"], room, "open", "Scope agreed with the auditor") == "open"
    db.commit()
    with pytest.raises(HTTPException) as fixed:
        rooms.add_item(db, users["grc"], room, "pack", draft)
    assert fixed.value.status_code == 409
    note = db.execute("SELECT title FROM notifications WHERE user_id=%s", (users["auditor"]["id"],)).fetchone()
    assert note["title"] == "An audit room is open for you"


def test_the_auditor_reads_only_their_open_room_inside_its_window(room_world):
    db, parent, child, relation, users, pack_id = room_world
    room, item = _open_room(db, users, pack_id)
    assert [r["id"] for r in rooms.listing(db, users["auditor"])["items"]] == [room]
    detail = rooms.detail(db, users["auditor"], room)
    assert [i["title"] for i in detail["items"]] == ["Q4 board pack (Q4 2026)"] and "events" not in detail
    opened = rooms.open_item(db, users["auditor"], room, item)
    db.commit()
    names = [e["name"] for e in opened["pack"]["entities"]]
    assert names == ["Pack Parent", "Pack Child"], "the auditor sees what the person who added it sees"
    logged = db.execute("SELECT action, viewer_org_id FROM group_access_events WHERE source_org_id=%s "
                        "AND action='room_open'", (child,)).fetchall()
    assert len(logged) == 1, "the subsidiary's own log records the auditor's read"
    with pytest.raises(HTTPException) as no_download:
        rooms.download_item(db, users["auditor"], room, item)
    assert no_download.value.status_code == 404
    for who in ("other_auditor", "emp", "child_grc"):
        with pytest.raises(HTTPException) as hidden:
            rooms.detail(db, users[who], room)
        assert hidden.value.status_code in (403, 404), who
    assert rooms.listing(db, users["other_auditor"])["items"] == []
    db.execute("UPDATE group_audit_rooms SET ends_at=%s WHERE id=%s", (_at(-1), room))
    db.commit()
    with pytest.raises(HTTPException) as expired:
        rooms.open_item(db, users["auditor"], room, item)
    assert expired.value.status_code == 404, "the window ends access by itself"
    assert rooms.listing(db, users["auditor"])["items"] == []


def test_a_room_that_has_not_started_or_was_closed_is_shut(room_world):
    db, parent, child, relation, users, pack_id = room_world
    room, item = _open_room(db, users, pack_id, start=2, end=10)
    with pytest.raises(HTTPException) as early:
        rooms.detail(db, users["auditor"], room)
    assert early.value.status_code == 404
    db.execute("UPDATE group_audit_rooms SET starts_at=%s WHERE id=%s", (_at(-1), room))
    db.commit()
    assert rooms.detail(db, users["auditor"], room)["can_ask"] is True
    with pytest.raises(HTTPException) as auditor_close:
        rooms.close(db, users["auditor"], room, "I am done with this")
    assert auditor_close.value.status_code == 403
    rooms.close(db, users["audit"], room, "Fieldwork finished early")
    db.commit()
    with pytest.raises(HTTPException) as closed:
        rooms.detail(db, users["auditor"], room)
    assert closed.value.status_code == 404


def test_every_read_is_rechecked_through_the_person_who_added_the_item(room_world):
    db, parent, child, relation, users, pack_id = room_world
    room, item = _open_room(db, users, pack_id, download=True)
    db.execute("UPDATE group_view_grants SET revoked_at=%s WHERE user_id=%s", (_at(-1), users["grc"]["id"]))
    db.commit()
    names = [e["name"] for e in rooms.open_item(db, users["auditor"], room, item)["pack"]["entities"]]
    assert names == ["Pack Parent"], "without the adder's grant the subsidiary leaves the room too"
    db.execute("DELETE FROM user_roles WHERE user_id=%s", (users["grc"]["id"],))
    db.commit()
    assert rooms.detail(db, users["auditor"], room)["items"] == [], "nothing the adder can no longer open is shown"
    with pytest.raises(HTTPException) as gone:
        rooms.download_item(db, users["auditor"], room, item)
    assert gone.value.status_code == 404
    staff_view = rooms.detail(db, users["comp"], room)["items"]
    assert staff_view == [{"id": item, "kind": "pack", "available": False, "title": None, "can_download": False}]


def test_questions_come_from_the_auditor_and_answers_cite_room_items(room_world):
    db, parent, child, relation, users, pack_id = room_world
    room, item = _open_room(db, users, pack_id, download=True)
    question = rooms.post_message(db, users["auditor"], room, "How was the breach count reconciled?")
    with pytest.raises(HTTPException) as uncited:
        rooms.post_message(db, users["grc"], room, "Two builds must agree.", question, [])
    assert uncited.value.status_code == 422
    with pytest.raises(HTTPException) as outside:
        rooms.post_message(db, users["grc"], room, "Two builds must agree.", question, [item + 99])
    assert outside.value.status_code == 422
    with pytest.raises(HTTPException) as not_a_question:
        rooms.post_message(db, users["grc"], room, "Two builds must agree.", None, [item])
    assert not_a_question.value.status_code == 422
    with pytest.raises(HTTPException) as approver_only:
        rooms.post_message(db, users["audit"], room, "Two builds must agree.", question, [item])
    assert approver_only.value.status_code == 403
    rooms.post_message(db, users["grc"], room, "Two independent builds must agree.", question, [item])
    db.commit()
    messages = rooms.detail(db, users["auditor"], room)["messages"]
    assert [(m["kind"], m["cites"]) for m in messages] == [("question", []), ("answer", [item])]
    kind, payload, adder = rooms.download_item(db, users["auditor"], room, item)
    assert kind == "pack" and payload["status"] == "issued"
    actions = [e["action"] for e in rooms.detail(db, users["comp"], room)["events"]]
    assert {"proposed", "item_added", "approved", "question", "answer", "download", "entered"} <= set(actions)
