"""
Evidence Vault proof semantics (plans/2026-10-governance-rework/02 section 4): a live link, current proof and accepted
proof are different facts with one definition each; only a reviewer other than the person who attached the file can
accept a link; a new version never inherits an accepted verdict; and a hidden claim is never named.
"""
import io
import json
import types

import pytest
from starlette.datastructures import Headers, UploadFile

import modules.evidence.routes as ev
from core import rbac
from modules.evidence import proof
from tests.test_evidence_vault_reads import _bu, _get, _json_req, _org, _req, auth  # noqa: F401

TODAY = proof.today()
PAST, FUTURE = "2020-01-01", "2099-12-31"


def _user(uid, org_id, bu_id, roles, super_admin=0):
    return {"id": uid, "username": f"proof{uid}", "org_id": org_id, "business_unit_id": bu_id, "is_super_admin": super_admin,
            "roles": roles}


@pytest.fixture
def vault(test_db):
    org1, org2 = _org(test_db, "pr1"), _org(test_db, "pr2")
    bu_a, bu_b = _bu(test_db, "PRA"), _bu(test_db, "PRB")
    for uid in (41, 42, 43, 44, 45):
        test_db.execute("INSERT INTO users (id, username, email, full_name, password_hash, org_id) VALUES (%s,%s,%s,%s,'x',%s)",
                        (uid, f"proof{uid}", f"proof{uid}@example.test", f"Person {uid}", org2 if uid == 45 else org1))
    test_db.commit()

    def risk(title, unit):
        cur = test_db.execute("INSERT INTO erm_enterprise_risks (title, business_unit_id) VALUES (%s, %s)", (title, unit))
        test_db.commit()
        return cur.lastrowid

    def item(title, *, status="current", expiry=None, uploader=41, org=org1, unit=None, version=1, parent=None, **more):
        fields = {"title": title, "status": status, "expiry_date": expiry, "uploaded_by": uploader, "org_id": org,
                  "business_unit_id": unit, "version": version, "parent_id": parent, **more}
        cur = test_db.execute(f"INSERT INTO evidence_items ({', '.join(fields)}) VALUES ({', '.join(['%s'] * len(fields))})",
                              tuple(fields.values()))
        test_db.commit()
        return cur.lastrowid

    def link(evidence_id, target_id, *, status=None, deleted=False, by=41, carried_from=None):
        cur = test_db.execute(
            "INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by, review_status, deleted_at, "
            "carried_from_link_id) VALUES (%s,'erm','risk',%s,%s,%s,%s,%s)",
            (evidence_id, target_id, by, status, "2026-01-01 00:00:00" if deleted else None, carried_from))
        test_db.commit()
        return cur.lastrowid

    users = types.SimpleNamespace(
        uploader=_user(41, org1, None, [rbac.COMPLIANCE_MGR]),
        reviewer=_user(42, org1, None, [rbac.COMPLIANCE_MGR]),
        second=_user(43, org1, None, [rbac.GRC_OFFICER]),
        staff=_user(44, org1, None, [rbac.EMPLOYEE]),
        elsewhere=_user(45, org2, None, [rbac.COMPLIANCE_MGR]),
        unit_a=_user(42, org1, bu_a, [rbac.COMPLIANCE_MGR]),
    )
    return types.SimpleNamespace(db=test_db, org1=org1, org2=org2, bu_a=bu_a, bu_b=bu_b, risk=risk, item=item, link=link,
                                 users=users)


def _status(vault, link_id):
    row = vault.db.execute("SELECT review_status, reviewed_by, review_note FROM evidence_links WHERE id = %s", (link_id,)).fetchone()
    return (row["review_status"], row["reviewed_by"], row["review_note"])


def _refused(call, status):
    with pytest.raises(proof.ReviewError) as caught:
        call()
    assert caught.value.status == status, caught.value.message
    return caught.value


# ── One definition each ─────────────────────────────────────────────────────

def test_the_three_measures_count_the_same_targets_differently(vault, auth):
    risks = {name: vault.risk(f"Risk {name}", None) for name in ("unreviewed", "accepted", "expired", "replaced", "returned",
                                                                 "ruled_out", "none", "removed", "archived")}
    vault.link(vault.item("current unreviewed"), risks["unreviewed"])
    vault.link(vault.item("current accepted"), risks["accepted"], status="accepted")
    vault.link(vault.item("expired", expiry=PAST), risks["expired"], status="accepted")
    vault.link(vault.item("replaced", status="superseded"), risks["replaced"], status="accepted")
    vault.link(vault.item("returned"), risks["returned"], status="returned")
    vault.link(vault.item("ruled out"), risks["ruled_out"], status="out_of_scope")
    vault.link(vault.item("removed"), risks["removed"], deleted=True)
    vault.link(vault.item("archived", status="archived"), risks["archived"], status="accepted")

    body = _get(ev.api_evidence_coverage(_req(auth, vault.users.uploader)))
    entity = next(e for e in body["erm"]["entities"] if e["type"] == "risk")
    assert entity["total"] == 9
    assert entity["linked"] == 6, "a live link on any item that is not archived: unreviewed, accepted, expired, replaced, returned, ruled out"
    assert entity["current"] == 2, "only the current, unexpired versions that nobody turned down"
    assert entity["accepted"] == 1
    assert (entity["with_evidence"], entity["pct"]) == (entity["linked"], round(6 / 9 * 100)), "the old keys keep meaning linked"
    assert entity["pct_current"] == round(2 / 9 * 100) and entity["pct_accepted"] == round(1 / 9 * 100)
    assert (body["erm"]["linked"], body["erm"]["current"], body["erm"]["accepted"]) == (6, 2, 1)


def test_coverage_is_scoped_to_what_the_caller_may_open(vault, auth):
    mine, theirs = vault.risk("Mine", vault.bu_a), vault.risk("Theirs", vault.bu_b)
    vault.link(vault.item("for mine", unit=None), mine, status="accepted")
    vault.link(vault.item("for theirs", unit=vault.bu_b), theirs, status="accepted")
    body = _get(ev.api_evidence_coverage(_req(auth, vault.users.unit_a)))
    entity = next(e for e in body["erm"]["entities"] if e["type"] == "risk")
    assert (entity["total"], entity["linked"], entity["accepted"]) == (1, 1, 1), "the other unit's risk and item are not counted"


def test_the_definitions_are_published_with_the_numbers(vault, auth):
    body = _get(ev.api_evidence_coverage_definitions(_req(auth, vault.users.uploader)))
    assert set(body["measures"]) == {"linked", "current", "accepted"}
    assert "expired" in body["measures"]["current"]["means"] and "reviewer" in body["measures"]["accepted"]["means"]
    assert body["as_of"] == TODAY and body["denominator"]


def test_a_state_never_says_accepted_without_every_active_link_accepted():
    state = lambda **kw: proof.item_state(**{"status": "current", "expiry_date": None, "links_active": 0, "links_pending": 0,
                                             "links_returned": 0, **kw})["key"]
    assert state() == "needs_filing"
    assert state(links_active=2, links_pending=1) == "awaiting_review"
    assert state(links_active=2, links_returned=1, links_pending=1) == "returned"
    assert state(links_active=2) == "accepted"
    assert state(status="superseded", links_active=2) == "replaced"
    assert state(status="archived") == "archived"
    assert state(expiry_date=PAST, links_active=2) == "expired"
    assert state(expiry_date=TODAY, links_active=2) == "expired", "an item expires on its expiry date"
    assert state(expiry_date=FUTURE, links_active=2) == "accepted"


# ── Who may accept ──────────────────────────────────────────────────────────

def test_a_reviewer_accepts_a_link_and_it_is_recorded_with_who_and_when(vault):
    target = vault.risk("Treatment", None)
    link = vault.link(vault.item("Test report"), target)
    done = proof.review_link(vault.db, vault.users.reviewer, link, "accepted", "Covers the period.")
    vault.db.commit()
    assert done["link"]["review_status"] == "accepted" and done["audit"][0].startswith("Reviewed an evidence link: accepted")
    assert _status(vault, link) == ("accepted", 42, "Covers the period.")


def test_the_person_who_attached_the_file_or_the_link_cannot_review_it(vault):
    target = vault.risk("Treatment", None)
    link = vault.link(vault.item("Test report", uploader=41), target, by=43)
    _refused(lambda: proof.review_link(vault.db, vault.users.uploader, link, "accepted"), 403)
    _refused(lambda: proof.review_link(vault.db, vault.users.second, link, "accepted"), 403)
    assert _status(vault, link)[0] is None


def test_only_those_with_the_right_review_and_only_what_they_may_open(vault):
    target = vault.risk("Treatment", None)
    hidden = vault.risk("Other unit", vault.bu_b)
    link = vault.link(vault.item("Test report"), target)
    other = vault.link(vault.item("Another report"), hidden)
    _refused(lambda: proof.review_link(vault.db, vault.users.staff, link, "accepted"), 403)
    _refused(lambda: proof.review_link(vault.db, vault.users.elsewhere, link, "accepted"), 404)
    _refused(lambda: proof.review_link(vault.db, vault.users.unit_a, other, "accepted"), 404)
    _refused(lambda: proof.review_link(vault.db, vault.users.reviewer, 987654, "accepted"), 404)
    assert _status(vault, other)[0] is None


def test_a_turned_down_link_needs_a_reason_and_acceptance_needs_none(vault):
    target = vault.risk("Treatment", None)
    link = vault.link(vault.item("Test report"), target)
    for outcome in ("returned", "rejected", "out_of_scope"):
        _refused(lambda o=outcome: proof.review_link(vault.db, vault.users.reviewer, link, o, "  "), 422)
    _refused(lambda: proof.review_link(vault.db, vault.users.reviewer, link, "accepted", "x" * 501), 422)
    _refused(lambda: proof.review_link(vault.db, vault.users.reviewer, link, "approved"), 422)
    done = proof.review_link(vault.db, vault.users.reviewer, link, "returned", "The test period is the wrong year.")
    vault.db.commit()
    assert done["link"]["review_status"] == "returned"
    again = proof.review_link(vault.db, vault.users.second, link, "accepted", expected_status="returned")
    vault.db.commit()
    assert again["link"]["review_status"] == "accepted"


def test_only_the_current_unexpired_version_can_be_accepted(vault):
    target = vault.risk("Treatment", None)
    for kwargs in ({"status": "superseded"}, {"status": "archived"}, {"expiry": PAST}):
        link = vault.link(vault.item("Test report", **kwargs), target)
        _refused(lambda lid=link: proof.review_link(vault.db, vault.users.reviewer, lid, "accepted"), 409)
    # a reviewer may still turn a link down, or rule it out, on a version that has been replaced
    old = vault.link(vault.item("Old report", status="superseded"), target)
    done = proof.review_link(vault.db, vault.users.reviewer, old, "out_of_scope", "Replaced by the signed copy.")
    assert done["link"]["review_status"] == "out_of_scope"


def test_two_reviewers_never_overwrite_each_other_silently(vault):
    target = vault.risk("Treatment", None)
    link = vault.link(vault.item("Test report"), target)
    proof.review_link(vault.db, vault.users.reviewer, link, "accepted", expected_status="pending")
    vault.db.commit()
    stale = _refused(lambda: proof.review_link(vault.db, vault.users.second, link, "returned", "No.", expected_status="pending"), 409)
    assert stale.extra["status_now"] == "accepted"
    assert _status(vault, link)[0] == "accepted"


def test_an_accepted_link_can_be_put_back_to_waiting_and_forgets_the_verdict(vault):
    target = vault.risk("Treatment", None)
    link = vault.link(vault.item("Test report"), target)
    proof.review_link(vault.db, vault.users.reviewer, link, "accepted", "Fine.")
    vault.db.commit()
    proof.review_link(vault.db, vault.users.second, link, "pending")
    vault.db.commit()
    assert _status(vault, link) == ("pending", None, None)


def test_a_collection_request_decision_is_a_link_verdict(vault):
    target = vault.risk("Treatment", None)
    item = vault.item("Signed test")
    request = {"evidence_id": item, "module": "erm", "entity_type": "risk", "entity_id": str(target), "assignee_id": 41}
    created = proof.record_request_decision(vault.db, request, vault.users.reviewer, True, "Looks right.")
    vault.db.commit()
    assert _status(vault, created) == ("accepted", 42, "Looks right.")
    assert vault.db.execute("SELECT linked_by FROM evidence_links WHERE id = %s", (created,)).fetchone()[0] == 41
    again = proof.record_request_decision(vault.db, request, vault.users.second, False, "Wrong period.")
    vault.db.commit()
    assert again == created and _status(vault, created) == ("returned", 43, "Wrong period.")
    other = {**request, "entity_id": str(vault.risk("Another", None)), "evidence_id": vault.item("Unlinked")}
    assert proof.record_request_decision(vault.db, other, vault.users.reviewer, False, "No.") is None
    assert proof.record_request_decision(vault.db, {**request, "entity_id": "not a number"}, vault.users.reviewer, True) is None
    assert proof.record_request_decision(vault.db, {**request, "evidence_id": None}, vault.users.reviewer, True) is None


# ── A new version ───────────────────────────────────────────────────────────

def test_a_new_version_proposes_its_links_and_never_inherits_the_accepted_verdict(vault):
    seen, hidden = vault.risk("Treatment", None), vault.risk("Other unit", vault.bu_b)
    old = vault.item("Report v1", status="superseded")
    accepted = vault.link(old, seen, status="accepted")
    unseen = vault.link(old, hidden, status="accepted")
    removed = vault.link(old, vault.risk("Removed", None), deleted=True)
    new = vault.item("Report v2", version=2, parent=old)

    done = proof.carry_forward(vault.db, vault.users.unit_a, old, new)
    vault.db.commit()
    assert done == {"considered": 2, "carried": 1, "not_carried": 1}
    rows = vault.db.execute("SELECT entity_id, review_status, carried_from_link_id, linked_by FROM evidence_links "
                            "WHERE evidence_id = %s", (new,)).fetchall()
    assert [(r["entity_id"], r["review_status"], r["carried_from_link_id"], r["linked_by"]) for r in rows] == [(seen, None, accepted, 42)]
    assert unseen and removed, "the old version's links stay where they were"
    assert _status(vault, accepted)[0] == "accepted", "history is not rewritten"


def test_the_impact_names_only_claims_the_viewer_may_open(vault):
    seen, hidden = vault.risk("Treatment", None), vault.risk("Other unit secret", vault.bu_b)
    old = vault.item("Report v1", status="superseded")
    a = vault.link(old, seen, status="accepted")
    vault.link(old, hidden, status="accepted")
    new = vault.item("Report v2", version=2, parent=old)
    vault.link(new, seen, carried_from=a)

    got = proof.impact(vault.db, vault.users.unit_a, new)
    assert got["previous"]["version"] == 1 and got["hidden"] == 1
    assert [(c["title"], c["was"], c["now"]) for c in got["claims"]] == [("Treatment", "accepted", "pending")]
    assert got["summary"] == {"claims": 2, "proposed": 1, "awaiting_review": 1, "accepted_again": 0, "not_carried": 1}
    assert "secret" not in json.dumps(got)
    assert proof.impact(vault.db, vault.users.elsewhere, new) is None, "an item in another organization does not exist"
    first = proof.impact(vault.db, vault.users.uploader, old)
    assert first["previous"] is None and first["claims"] == []


# ── Through the routes ──────────────────────────────────────────────────────

def _upload(auth, user, data, *, replace_id="", name="proof.txt"):
    request = _req(auth, user)
    file = UploadFile(file=io.BytesIO(data), size=len(data), filename=name, headers=Headers({"content-type": "text/plain"}))
    import asyncio
    result = asyncio.run(ev.api_evidence_upload(
        request, file, title="Proof", description="", category="general", tags="", replace_id=replace_id, expiry_date="",
        owner_user_id="", review_due_date="", period_start="", period_end=""))
    return result.status_code, json.loads(result.body)


def test_replacing_a_file_through_the_upload_route_proposes_its_links(vault, auth, tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "EVIDENCE_DIR", tmp_path)
    target = vault.risk("Treatment", None)
    old = vault.item("Policy test", file_path="a.txt", file_name="a.txt")
    link = vault.link(old, target, status="accepted")
    status, body = _upload(auth, vault.users.uploader, b"the signed copy", replace_id=str(old))
    assert status == 201 and body["impact"] == {"considered": 1, "carried": 1, "not_carried": 0}
    new = body["id"]
    assert vault.db.execute("SELECT status FROM evidence_items WHERE id = %s", (old,)).fetchone()["status"] == "superseded"
    row = vault.db.execute("SELECT review_status, carried_from_link_id FROM evidence_links WHERE evidence_id = %s", (new,)).fetchone()
    assert (row["review_status"], row["carried_from_link_id"]) == (None, link)

    shown = _get(ev.api_evidence_impact(_req(auth, vault.users.reviewer), new))
    assert shown["summary"]["awaiting_review"] == 1 and shown["claims"][0]["title"] == "Treatment"

    # the owner of the claim is told that the file behind it was replaced, and decides whether it needs a second look
    [signal] = vault.db.execute("SELECT * FROM change_signals").fetchall()
    assert (signal["change_kind"], signal["source_module"], signal["source_type"], signal["source_id"]) == (
        "evidence_replaced", "evidence", "item", new)
    assert [tuple(t) for t in vault.db.execute(
        "SELECT target_module, target_type, target_id, status FROM change_signal_targets").fetchall()] == [
        ("erm", "risk", target, "open")]


def test_a_duplicate_in_a_unit_the_caller_cannot_open_is_refused_without_naming_it(vault, auth, tmp_path, monkeypatch):
    import hashlib
    monkeypatch.setattr(ev, "EVIDENCE_DIR", tmp_path)
    data = b"already held by unit B"
    vault.item("Unit B secret title", unit=vault.bu_b, file_hash=hashlib.sha256(data).hexdigest())
    status, body = _upload(auth, vault.users.unit_a, data)
    assert status == 409 and body["duplicate"] is True
    assert "Unit B secret title" not in json.dumps(body) and "existing_id" not in body and body["hidden"] is True
    assert vault.db.execute("SELECT COUNT(*) FROM evidence_items WHERE title = 'Proof'").fetchone()[0] == 0


def test_the_review_route_answers_with_the_status_the_service_gave(vault, auth):
    target = vault.risk("Treatment", None)
    link = vault.link(vault.item("Test report"), target)
    request = _json_req(auth, vault.users.reviewer, {"outcome": "accepted", "note": "Good.", "expected_status": "pending"})
    got = _get(ev.api_evidence_link_review(request, link))
    assert got["link"]["review_status"] == "accepted"
    bad = _json_req(auth, vault.users.staff, {"outcome": "accepted"})
    refused = __import__("asyncio").run(ev.api_evidence_link_review(bad, link))
    assert refused.status_code == 403
    mine = _json_req(auth, vault.users.uploader, {"outcome": "returned", "note": "No."})
    assert __import__("asyncio").run(ev.api_evidence_link_review(mine, link)).status_code == 403


def test_an_item_lists_its_links_with_their_reviews(vault, auth):
    target = vault.risk("Treatment", None)
    item = vault.item("Test report")
    link = vault.link(item, target)
    proof.review_link(vault.db, vault.users.reviewer, link, "accepted", "Good.")
    vault.db.commit()
    got = _get(ev.api_evidence_get(_req(auth, vault.users.second), item))
    [shown] = got["links"]
    assert (shown["review_status"], shown["review_label"], shown["reviewed_by_name"], shown["review_note"]) == (
        "accepted", "Accepted", "Person 42", "Good.")
    assert got["state"]["key"] == "accepted" and got["can_review_links"] is True
