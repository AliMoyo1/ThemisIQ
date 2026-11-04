"""The audit room page in a real browser: the named auditor reads an open room and asks; staff see the question."""
import json
from datetime import datetime, timedelta, timezone

import database
import pytest
from modules.governance import group_figures as gf
from modules.governance import group_packs as gp
from playwright.sync_api import expect


@pytest.fixture(autouse=True)
def _synthetic_group_on_sqlite(monkeypatch):
    """Use synthetic group fixtures for UI behavior; keep the production SQLite guard unchanged."""
    monkeypatch.setattr(gf, "require_isolated_figures", lambda db=None: None)


def _stamp(days=0):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(tzinfo=None, microsecond=0).isoformat()


@pytest.fixture
def open_room(live_app, synthetic_tenant):
    db = database.get_db()
    try:
        def uid(persona):
            name = synthetic_tenant["users"][persona]["username"]
            return db.execute("SELECT id, org_id FROM users WHERE username=%s", (name,)).fetchone()
        manager, auditor = uid("compliance_manager"), uid("viewer")
        org = manager["org_id"]
        as_of = _stamp()
        row = {"measure_key": "cc.open_breaches", "state": "measured", "value": 3.0, "window": "", "detail": {}}
        db.execute("INSERT INTO group_figure_snapshots (source_org_id,measure_key,module,state,value,window_text,"
                   "detail_json,method_version,as_of,publication_version,content_hash) "
                   "VALUES (%s,'cc.open_breaches','sentinel','measured',3,'','{}','t',%s,1,%s)",
                   (org, as_of, gf._hash(org, row, as_of, 1)))
        snap = db.execute("SELECT MAX(id) AS i FROM group_figure_snapshots WHERE source_org_id=%s", (org,)).fetchone()["i"]
        entities = [{"org_id": org, "name": "Room org", "state": "reporting", "last_reported": as_of,
                     "snapshots": [{"id": snap, "hash": gf._hash(org, row, as_of, 1)}]}]
        db.execute("INSERT INTO group_packs (parent_org_id,title,period_text,manifest_json,content_hash,created_by,"
                   "created_at,status,reviewed_by,reviewed_at,review_note) VALUES (%s,'Room pack','FY2026',%s,%s,%s,%s,"
                   "'issued',%s,%s,'Checked against the sources')",
                   (org, json.dumps(entities), gp._manifest_hash(org, "Room pack", "FY2026", entities), manager["id"],
                    as_of, auditor["id"], as_of))
        pack = db.execute("SELECT MAX(id) AS i FROM group_packs").fetchone()["i"]
        db.execute("INSERT INTO group_audit_rooms (parent_org_id,title,auditor_user_id,starts_at,ends_at,status,"
                   "proposed_by,approved_by,approved_at,decision_reason,created_at) VALUES (%s,'Browser audit room',%s,"
                   "%s,%s,'open',%s,%s,%s,'Scope agreed',%s)",
                   (org, auditor["id"], _stamp(-1), _stamp(10), manager["id"], manager["id"], as_of, as_of))
        room = db.execute("SELECT MAX(id) AS i FROM group_audit_rooms").fetchone()["i"]
        db.execute("INSERT INTO group_audit_room_items (room_id,parent_org_id,kind,ref_id,allow_download,added_by,"
                   "added_at) VALUES (%s,%s,'pack',%s,1,%s,%s)", (room, org, pack, manager["id"], as_of))
        db.commit()
    finally:
        db.close()
    yield room
    db = database.get_db()
    try:
        for table in ("group_audit_room_events", "group_audit_room_messages", "group_audit_room_items"):
            db.execute(f"DELETE FROM {table} WHERE room_id=%s", (room,))
        db.execute("DELETE FROM group_audit_rooms WHERE id=%s", (room,))
        db.execute("DELETE FROM group_packs WHERE id=%s", (pack,))
        db.execute("DELETE FROM group_figure_snapshots WHERE id=%s", (snap,))
        db.commit()
    finally:
        db.close()


def test_the_named_auditor_opens_the_room_reads_the_pack_and_asks(login_as, live_app, open_room):
    page = login_as("viewer")
    page.goto(f"{live_app}/governance/group/rooms/")
    expect(page.get_by_role("heading", name="Audit rooms")).to_be_visible()
    expect(page.locator("#arList")).to_contain_text("Browser audit room")
    expect(page.locator("#arCreate")).to_be_hidden()
    page.get_by_role("button", name="Open room").first.click()
    expect(page.locator("#arItems")).to_contain_text("Room pack (FY2026)")
    page.locator("#arItems").get_by_role("button", name="Open").click()
    expect(page.locator("#arOpened")).to_contain_text("Integrity check passed")
    expect(page.locator("#arOpened")).to_contain_text("Open breaches: 3")
    expect(page.locator("#arOpened").get_by_role("link", name="Download PDF")).to_be_visible()
    page.locator("#arAsk textarea").fill("How were breaches counted for FY2026?")
    page.locator("#arAsk").get_by_role("button", name="Ask").click()
    expect(page.locator("#arStatus")).to_contain_text("Question sent")
    expect(page.locator("#arMessages")).to_contain_text("How were breaches counted")
    expect(page.locator("#arEvents")).to_be_empty()


def test_staff_see_the_question_and_answer_it_citing_a_room_item(login_as, live_app, open_room):
    db = database.get_db()
    try:
        room = db.execute("SELECT parent_org_id, auditor_user_id FROM group_audit_rooms WHERE id=%s",
                          (open_room,)).fetchone()
        db.execute("INSERT INTO group_audit_room_messages (room_id,parent_org_id,author_id,kind,body,cites_json,"
                   "created_at) VALUES (%s,%s,%s,'question','Please explain the method.','[]',%s)",
                   (open_room, room["parent_org_id"], room["auditor_user_id"], _stamp()))
        item = db.execute("SELECT id FROM group_audit_room_items WHERE room_id=%s", (open_room,)).fetchone()["id"]
        db.commit()
    finally:
        db.close()
    staff = login_as("compliance_manager")
    staff.goto(f"{live_app}/governance/group/rooms/?room={open_room}")
    expect(staff.locator("#arMessages")).to_contain_text("Please explain the method.")
    staff.locator("#arMessages textarea").fill("Two independent builds must agree before a figure is published.")
    staff.locator("#arMessages input").fill(str(item))
    staff.locator("#arMessages").get_by_role("button", name="Answer").click()
    expect(staff.locator("#arStatus")).to_contain_text("Answer sent")
    expect(staff.locator("#arMessages")).to_contain_text(f"Cites room items {item}")
    expect(staff.locator("#arEvents")).to_contain_text("answer")


def test_someone_without_a_room_role_is_kept_out(login_as, live_app, open_room):
    outsider = login_as("employee")
    response = outsider.goto(f"{live_app}/governance/group/rooms/")
    assert response.status == 404
    status = outsider.evaluate(f"async () => (await fetch('/governance/api/group/rooms/{open_room}')).status")
    assert status in (403, 404)
