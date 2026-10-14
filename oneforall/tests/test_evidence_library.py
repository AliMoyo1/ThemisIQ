"""
Evidence Vault library (plans/2026-10-governance-rework/02 section 3): a row says who owns the file, when it is next looked
at, which claims it supports (naming only those the caller may open) and one state; the work views are lists whose counts
are the stats; and the fields that decide what a file proves are checked on the way in.
"""
import asyncio
import io
import json
import types
from datetime import timedelta

import pytest
from starlette.datastructures import Headers, UploadFile

import modules.evidence.routes as ev
from core import rbac
from core.timeutils import utcnow
from modules.evidence import proof
from tests.test_evidence_vault_reads import _bu, _get, _json_req, _org, _req, auth  # noqa: F401


def _day(offset):
    return (utcnow() + timedelta(days=offset)).strftime("%Y-%m-%d")


def _person(uid, org_id, bu_id, roles, super_admin=0):
    return {"id": uid, "username": f"lib{uid}", "org_id": org_id, "business_unit_id": bu_id, "is_super_admin": super_admin,
            "roles": roles}


@pytest.fixture
def lib(test_db):
    org1, org2 = _org(test_db, "lib1"), _org(test_db, "lib2")
    unit_a, unit_b = _bu(test_db, "LA"), _bu(test_db, "LB")
    for uid, org in ((51, org1), (52, org1), (53, org1), (54, org2)):
        test_db.execute("INSERT INTO users (id, username, email, full_name, password_hash, org_id, is_active) "
                        "VALUES (%s,%s,%s,%s,'x',%s,1)",
                        (uid, f"lib{uid}", f"lib{uid}@example.test", f"Colleague {uid}", org))
    test_db.commit()

    def risk(title, unit=None):
        cur = test_db.execute("INSERT INTO erm_enterprise_risks (title, business_unit_id) VALUES (%s, %s)", (title, unit))
        test_db.commit()
        return cur.lastrowid

    def item(title, *, status="current", uploader=51, owner=None, unit=None, **more):
        fields = {"title": title, "status": status, "uploaded_by": uploader, "org_id": org1, "business_unit_id": unit,
                  "owner_user_id": owner, **more}
        cur = test_db.execute(f"INSERT INTO evidence_items ({', '.join(fields)}) VALUES ({', '.join(['%s'] * len(fields))})",
                              tuple(fields.values()))
        test_db.commit()
        return cur.lastrowid

    def link(evidence_id, target, status=None, by=51, deleted=False):
        cur = test_db.execute(
            "INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by, review_status, deleted_at) "
            "VALUES (%s,'erm','risk',%s,%s,%s,%s)",
            (evidence_id, target, by, status, "2026-01-01 00:00:00" if deleted else None))
        test_db.commit()
        return cur.lastrowid

    people = types.SimpleNamespace(
        uploader=_person(51, org1, None, [rbac.COMPLIANCE_MGR]),
        reviewer=_person(52, org1, None, [rbac.COMPLIANCE_MGR]),
        staff=_person(53, org1, None, [rbac.EMPLOYEE]),
        elsewhere=_person(54, org2, None, [rbac.COMPLIANCE_MGR]),
        unit_a=_person(52, org1, unit_a, [rbac.COMPLIANCE_MGR]),
    )
    return types.SimpleNamespace(db=test_db, org1=org1, org2=org2, unit_a=unit_a, unit_b=unit_b, risk=risk, item=item,
                                 link=link, people=people)


def _rows(auth, user, **query):
    body = _get(ev.api_evidence_list(_req(auth, user, **query)))
    return {r["title"]: r for r in body["items"]}, body


def test_a_row_carries_the_owner_the_dates_the_claims_and_one_state(lib, auth):
    claim = lib.risk("Access control risk")
    item = lib.item("Penetration test", owner=52, review_due_date=_day(10), period_start="2026-01-01", period_end="2026-06-30")
    lib.link(item, claim, status="accepted", by=51)
    rows, body = _rows(auth, lib.people.uploader)
    row = rows["Penetration test"]
    assert (row["owner_name"], row["review_due_date"], row["period_end"]) == ("Colleague 52", _day(10), "2026-06-30")
    assert row["claims"] == [{"title": "Access control risk", "url": "/erm/register?open=risk:%d" % claim, "module": "erm",
                              "entity_type": "risk"}]
    assert (row["claims_more"], row["claims_hidden"]) == (0, 0)
    assert row["state"] == {"key": "accepted", "label": "Accepted"} and row["review_due"] is True
    assert (row["links_accepted"], row["links_pending"], row["links_returned"]) == (1, 0, 0)


def test_the_states_a_row_can_be_in(lib, auth):
    lib.item("Nobody linked this")
    lib.link(lib.item("Waiting"), lib.risk("R1"))
    lib.link(lib.item("Turned down"), lib.risk("R2"), status="returned")
    lib.link(lib.item("Ruled out only"), lib.risk("R3"), status="out_of_scope")
    lib.link(lib.item("Lapsed", expiry_date=_day(-3)), lib.risk("R4"), status="accepted")
    rows, _ = _rows(auth, lib.people.uploader)
    assert {t: r["state"]["key"] for t, r in rows.items()} == {
        "Nobody linked this": "needs_filing", "Waiting": "awaiting_review", "Turned down": "returned",
        "Ruled out only": "needs_filing", "Lapsed": "expired"}


def test_a_claim_the_caller_may_not_open_is_counted_and_never_named(lib, auth):
    seen, hidden = lib.risk("Visible risk", None), lib.risk("Secret restructuring risk", lib.unit_b)
    extra = [lib.risk(f"More {n}", None) for n in range(2)]
    item = lib.item("Report")
    for target in (seen, hidden, *extra):
        lib.link(item, target)
    rows, _ = _rows(auth, lib.people.unit_a)
    row = rows["Report"]
    assert len(row["claims"]) == 2 and (row["claims_more"], row["claims_hidden"]) == (1, 1)
    assert "Secret restructuring risk" not in json.dumps(row)


def test_work_views_and_their_counts_are_the_same_lists(lib, auth):
    lib.item("Needs filing A")
    lib.item("Needs filing B")
    lib.link(lib.item("Filed"), lib.risk("R"))
    lib.link(lib.item("Linked by the reviewer's colleague", uploader=51), lib.risk("R5"), by=53)
    lib.item("Due soon", review_due_date=_day(5))
    lib.item("Due later", review_due_date=_day(90))
    for user_name in ("uploader", "reviewer", "staff"):
        user = getattr(lib.people, user_name)
        stats = _get(ev.api_evidence_stats(_req(auth, user)))
        for view, key in (("needs_filing", "needs_filing"), ("review_due", "review_due"), ("recent", "recently_updated"),
                          ("for_review", "for_review"), ("expiring", "expiring_soon")):
            _, body = _rows(auth, user, view=view)
            assert body["total"] == stats[key], (user_name, view)
        _, everything = _rows(auth, user)
        assert everything["total"] == stats["total"], user_name
    assert _rows(auth, lib.people.uploader, view="review_due")[1]["total"] == 1
    assert _rows(auth, lib.people.uploader, view="unlinked")[1]["total"] == _rows(auth, lib.people.uploader, view="needs_filing")[1]["total"]


def test_waiting_for_review_never_offers_what_the_caller_attached_and_needs_the_right_to_review(lib, auth):
    mine = lib.item("Uploaded by the reviewer", uploader=52)
    lib.link(mine, lib.risk("R1"), by=51)
    theirs = lib.item("Uploaded by the other", uploader=51)
    lib.link(theirs, lib.risk("R2"), by=51)
    attached = lib.item("Linked by the reviewer", uploader=51)
    lib.link(attached, lib.risk("R3"), by=52)
    rows, _ = _rows(auth, lib.people.reviewer, view="for_review")
    assert set(rows) == {"Uploaded by the other"}
    assert _rows(auth, lib.people.staff, view="for_review")[1]["total"] == 0, "staff hold no right to review evidence"
    rows, _ = _rows(auth, lib.people.uploader, view="for_review")
    assert rows == {}, "the uploader attached all three files or links, so none is theirs to review"


def test_open_requests_are_counted_for_the_person_asked(lib, auth):
    lib.db.execute(
        "INSERT INTO evidence_requests (org_id, module, entity_type, entity_id, title, assignee_id, reviewer_id, due_date, status, "
        "created_at, updated_at) VALUES (%s,'erm','risk','1','Test report',52,51,'2099-01-01','requested','2026-01-01','2026-01-01')",
        (lib.org1,))
    lib.db.commit()
    assert _get(ev.api_evidence_stats(_req(auth, lib.people.reviewer)))["open_requests"] == 1
    assert _get(ev.api_evidence_stats(_req(auth, lib.people.uploader)))["open_requests"] == 1, "a reviewer is asked too"
    assert _get(ev.api_evidence_stats(_req(auth, lib.people.staff)))["open_requests"] == 0


def test_the_owner_filter_and_the_sorts(lib, auth):
    lib.item("Alpha", owner=52, updated_at="2026-01-01 00:00:00", review_due_date=_day(40))
    lib.item("Zulu", owner=51, updated_at="2026-03-01 00:00:00", review_due_date=_day(5))
    lib.item("Mike", owner=52, updated_at="2026-02-01 00:00:00")
    mine, _ = _rows(auth, lib.people.reviewer, owner="me")
    assert set(mine) == {"Alpha", "Mike"}
    assert [i["title"] for i in _get(ev.api_evidence_list(_req(auth, lib.people.reviewer, sort="title")))["items"]] == ["Alpha", "Mike", "Zulu"]
    due = _get(ev.api_evidence_list(_req(auth, lib.people.reviewer, sort="review_due")))["items"]
    assert [i["title"] for i in due] == ["Zulu", "Alpha", "Mike"], "no date sorts last"


# ── What goes in is checked ─────────────────────────────────────────────────

def _upload(auth, user, data, **fields):
    request = _req(auth, user)
    file = UploadFile(file=io.BytesIO(data), size=len(data), filename="proof.txt", headers=Headers({"content-type": "text/plain"}))
    args = {"title": "Proof", "description": "", "category": "general", "tags": "", "replace_id": "", "expiry_date": "",
            "owner_user_id": "", "review_due_date": "", "period_start": "", "period_end": "", **fields}
    result = asyncio.run(ev.api_evidence_upload(request, file, **args))
    return result.status_code, json.loads(result.body)


def test_an_upload_keeps_owner_review_date_and_period_and_defaults_the_owner_to_the_uploader(lib, auth, tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "EVIDENCE_DIR", tmp_path)
    status, body = _upload(auth, lib.people.uploader, b"report one", owner_user_id="52", review_due_date="2026-12-01",
                           period_start="2026-01-01", period_end="2026-06-30", expiry_date="2027-01-01")
    assert status == 201
    row = lib.db.execute("SELECT * FROM evidence_items WHERE id = %s", (body["id"],)).fetchone()
    assert (row["owner_user_id"], row["review_due_date"], row["period_start"], row["period_end"], row["expiry_date"]) == (
        52, "2026-12-01", "2026-01-01", "2026-06-30", "2027-01-01")
    status, body = _upload(auth, lib.people.uploader, b"report two")
    assert status == 201
    assert lib.db.execute("SELECT owner_user_id FROM evidence_items WHERE id = %s", (body["id"],)).fetchone()[0] == 51


def test_an_upload_with_a_bad_date_period_or_owner_is_refused_and_stores_nothing(lib, auth, tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "EVIDENCE_DIR", tmp_path)
    cases = [({"review_due_date": "next week"}, "review date"), ({"expiry_date": "31/12/2026"}, "expiry date"),
             ({"period_start": "2026-06-30", "period_end": "2026-01-01"}, "cannot end before"),
             ({"owner_user_id": "54"}, "owner"), ({"owner_user_id": "abc"}, "owner"), ({"owner_user_id": "9999"}, "owner")]
    for fields, phrase in cases:
        status, body = _upload(auth, lib.people.uploader, b"never stored", **fields)
        assert status == 422 and phrase in body["error"], (fields, body)
    assert lib.db.execute("SELECT COUNT(*) FROM evidence_items WHERE title = 'Proof'").fetchone()[0] == 0


def test_a_new_version_keeps_the_owner(lib, auth, tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "EVIDENCE_DIR", tmp_path)
    old = lib.item("Policy test", owner=53, file_path="a.txt", file_name="a.txt")
    status, body = _upload(auth, lib.people.uploader, b"the signed copy", replace_id=str(old))
    assert status == 201
    assert lib.db.execute("SELECT owner_user_id FROM evidence_items WHERE id = %s", (body["id"],)).fetchone()[0] == 53


def test_an_update_checks_dates_status_and_owner(lib, auth):
    item = lib.item("Report")

    def update(**fields):
        request = _json_req(auth, lib.people.uploader, fields)
        result = asyncio.run(ev.api_evidence_update(request, item))
        return result.status_code, json.loads(result.body)

    assert update(review_due_date="2026-12-01", owner_user_id=52, period_start="2026-01-01")[0] == 200
    row = lib.db.execute("SELECT owner_user_id, review_due_date, period_start FROM evidence_items WHERE id = %s", (item,)).fetchone()
    assert (row["owner_user_id"], row["review_due_date"], row["period_start"]) == (52, "2026-12-01", "2026-01-01")
    assert update(review_due_date="")[0] == 200, "a blank date clears it"
    assert lib.db.execute("SELECT review_due_date FROM evidence_items WHERE id = %s", (item,)).fetchone()[0] is None
    for bad in ({"status": "approved"}, {"expiry_date": "soon"}, {"owner_user_id": 54}, {"period_end": "2026-13-45"}):
        status, body = update(**bad)
        assert status == 422 and body["error"], bad


def test_the_people_list_names_only_the_callers_own_colleagues(lib, auth):
    got = _get(ev.api_evidence_people(_req(auth, lib.people.uploader)))
    names = {p["name"] for p in got["items"]}
    assert "Colleague 52" in names and "Colleague 54" not in names
    found = _get(ev.api_evidence_people(_req(auth, lib.people.uploader, q="colleague 5%")))
    assert found["items"] == [], "a wildcard is just a character"
    narrowed = _get(ev.api_evidence_people(_req(auth, lib.people.uploader, q="52")))
    assert [p["name"] for p in narrowed["items"]] == ["Colleague 52"]
