"""
The assurance inspector and Find evidence (plans/2026-10-governance-rework/02 sections 4 and 6).

The inspector is deterministic: each defect names its rule, why it matters and where to put it right, reads inside the
caller's scope and never calls a file sufficient. Find evidence turns a question into editable filters over the same scoped
list, by rules always and by a model only when the policy allows it, and what a model answers is cut to the vocabulary.
"""
import asyncio
import json
from datetime import timedelta

import pytest

import modules.evidence.routes as ev
from core import ai_client, ai_policy
from core.timeutils import utcnow
from modules.evidence import find, inspector, proof
from tests.test_evidence_library import _day, _rows, lib  # noqa: F401
from tests.test_evidence_vault_reads import _get, _json_req, _req, auth  # noqa: F401


def _ago(days):
    return (utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _by_rule(report):
    out = {}
    for f in report["findings"]:
        out.setdefault(f["rule"], []).append(f)
    return out


# ── The inspector ───────────────────────────────────────────────────────────

def test_each_rule_names_the_defect_where_it_is_and_how_to_put_it_right(lib):
    ownerless = lib.item("Ownerless file")
    lapsed = lib.item("Lapsed policy test", owner=51, expiry_date=_day(-10), review_due_date=_day(100))
    lib.link(lapsed, lib.risk("Backup restore risk"), status="accepted")
    turned = lib.item("Turned down report", owner=51, review_due_date=_day(100))
    lib.db.execute("UPDATE evidence_links SET review_note = 'Wrong year.' WHERE id = %s",
                   (lib.link(turned, lib.risk("Change control risk"), status="returned"),))
    waiting = lib.item("Slow review report", owner=51, review_due_date=_day(100))
    lib.db.execute("UPDATE evidence_links SET created_at = %s WHERE id = %s",
                   (_ago(45), lib.link(waiting, lib.risk("Vendor risk"))))
    old_period = lib.item("Old period report", owner=51, review_due_date=_day(100), period_end="2023-12-31")
    lib.link(old_period, lib.risk("Logging risk"), status="accepted")
    undated = lib.item("Undated report", owner=51)
    lib.link(undated, lib.risk("Patching risk"), status="accepted")
    old = lib.item("Report v1", owner=51, status="superseded")
    lib.link(old, lib.risk("Carried claim"), status="accepted")
    lib.link(old, lib.risk("Left behind claim"), status="accepted")
    new = lib.item("Report v2", owner=51, review_due_date=_day(100), version=2, parent_id=old)
    carried = lib.db.execute("SELECT entity_id FROM evidence_links WHERE evidence_id = %s ORDER BY id", (old,)).fetchall()
    lib.link(new, carried[0]["entity_id"])
    lib.item("Twin title", owner=51, review_due_date=_day(100))
    lib.item("Twin title", owner=51, review_due_date=_day(100))
    lib.db.commit()

    report = inspector.inspect(lib.db, lib.people.uploader)
    by = _by_rule(report)
    assert report["rule_version"] == "i1" and set(by) == {"no_owner", "expired_in_use", "returned_link", "review_waiting",
                                                           "period_ended", "no_review_date", "claims_not_carried", "similar_title"}
    assert {f["evidence_title"] for f in by["no_owner"]} >= {"Ownerless file"}
    assert by["expired_in_use"][0]["claims"] == ["Backup restore risk"] and by["expired_in_use"][0]["severity"] == "error"
    assert by["expired_in_use"][0]["fix"] == {"label": "Add a new version", "action": "version"}
    assert "Wrong year." in by["returned_link"][0]["why"] and by["returned_link"][0]["claims"] == ["Change control risk"]
    assert by["review_waiting"][0]["claims"] == ["Vendor risk"]
    assert by["period_ended"][0]["evidence_title"] == "Old period report"
    assert by["no_review_date"][0]["evidence_title"] == "Undated report"
    assert by["claims_not_carried"][0]["claims"] == ["Left behind claim"]
    assert [f["evidence_title"] for f in by["similar_title"]] == ["Twin title", "Twin title"]
    assert by["similar_title"][0]["severity"] == "suggestion"
    assert report["findings"] == sorted(report["findings"], key=lambda f: (inspector._ORDER[f["severity"]], f["evidence_title"].lower(),
                                                                         f["evidence_id"], f["rule"])), "most serious first"
    assert "not a statement that it is sufficient" in report["note"]
    assert ownerless in {f["evidence_id"] for f in by["no_owner"]}


def test_a_file_with_nothing_wrong_has_no_finding_and_is_never_called_sufficient(lib):
    good = lib.item("Well kept report", owner=51, review_due_date=_day(120))
    lib.link(good, lib.risk("A claim"), status="accepted")
    report = inspector.inspect(lib.db, lib.people.uploader, evidence_id=good)
    assert report["findings"] == [] and report["total"] == 0 and report["scanned"] == 1
    assert "sufficient" in report["note"]


def test_one_file_is_checked_on_its_own_and_a_twin_is_still_noticed(lib):
    first = lib.item("Same title", owner=51, review_due_date=_day(90))
    lib.item("Same title", owner=51, review_due_date=_day(90))
    one = inspector.inspect(lib.db, lib.people.uploader, evidence_id=first)
    assert [f["rule"] for f in one["findings"]] == ["similar_title"] and one["scanned"] == 1


def test_the_inspector_reads_only_what_the_caller_may_open_and_names_only_claims_they_may_open(lib):
    mine = lib.item("In my unit", owner=52, expiry_date=_day(-5))
    lib.link(mine, lib.risk("Visible claim"))
    lib.link(mine, lib.risk("Secret restructuring claim", lib.unit_b))
    lib.item("Other unit file", owner=None, unit=lib.unit_b)
    report = inspector.inspect(lib.db, lib.people.unit_a)
    titles = {f["evidence_title"] for f in report["findings"]}
    assert "In my unit" in titles and "Other unit file" not in titles
    assert "Secret restructuring claim" not in json.dumps(report)
    assert inspector.inspect(lib.db, lib.people.elsewhere)["findings"] == []


def test_the_inspector_routes_validate_and_hide(lib, auth):
    item = lib.item("Ownerless")
    body = _get(ev.api_evidence_inspector(_req(auth, lib.people.uploader, rule="no_owner", limit="5")))
    assert body["total"] == 1 and body["findings"][0]["rule"] == "no_owner"
    bad = asyncio.run(ev.api_evidence_inspector(_req(auth, lib.people.uploader, rule="nonsense")))
    assert bad.status_code == 400
    assert _get(ev.api_evidence_checks(_req(auth, lib.people.uploader), item))["total"] == 1
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as hidden:
        asyncio.run(ev.api_evidence_checks(_req(auth, lib.people.elsewhere), item))
    assert hidden.value.status_code == 404


def test_the_owner_of_files_that_existed_before_owners_is_their_uploader_once(lib):
    import database
    old = lib.item("Before owners", uploader=51, owner=None)
    named = lib.item("Named later", uploader=51, owner=52)
    lib.db.execute("DELETE FROM settings WHERE key = %s", (database._EVIDENCE_OWNER_KEY,))
    lib.db.commit()
    database._backfill_evidence_owner(lib.db)
    lib.db.commit()
    owner = lambda eid: lib.db.execute("SELECT owner_user_id FROM evidence_items WHERE id = %s", (eid,)).fetchone()[0]
    assert owner(old) == 51 and owner(named) == 52
    lib.db.execute("UPDATE evidence_items SET owner_user_id = NULL WHERE id = %s", (old,))
    lib.db.commit()
    database._backfill_evidence_owner(lib.db)
    assert owner(old) is None, "the backfill runs once per schema and never hands a file back"


# ── Find evidence: reading the question ─────────────────────────────────────

def test_rules_read_states_modules_owner_and_words():
    got = find.parse_rules("Show me expired penetration test reports that are mine in GRID")
    assert got == {"state": "expired", "owner": "me", "module": "grid", "words": ["penetration", "test", "reports"]}
    assert find.parse_rules("files waiting for review about vendors") == {"state": "awaiting_review", "words": ["vendors"]}
    assert find.parse_rules("anything that needs filing") == {"state": "needs_filing", "words": ["anything"]}
    assert find.parse_rules("policies of type policy") == {"category": "policy", "words": ["policies"]}
    assert find.parse_rules("") == {} and find.parse_rules("a an the of") == {}
    many = find.parse_rules("alpha bravo charlie delta echo foxtrot golf hotel")
    assert many["words"] == ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"], "at most six words"


def test_filters_are_cut_to_the_vocabulary():
    raw = {"words": ["Access", "drop table;--", "x", "ok-word", "ok-word", 7], "state": "EXPIRED", "module": "payroll",
           "category": "nonsense", "owner": "everyone", "sql": "1=1"}
    assert find.clean_filters(raw) == {"words": ["access", "ok-word"], "state": "expired"}
    assert find.clean_filters("not a dict") == {} and find.clean_filters(None) == {}
    assert find.list_params({"words": ["a1", "b2"], "state": "expired", "owner": "me"}) == {
        "words": "a1 b2", "state": "expired", "owner": "me"}


def test_a_model_answer_is_used_only_inside_the_vocabulary_and_never_sees_a_file(monkeypatch):
    seen = {}
    monkeypatch.setattr(ai_client, "is_configured", lambda: True)

    def fake(messages, **kw):
        seen.update(kw, messages=messages)
        return '```json\n{"words": ["pentest", "q3"], "state": "expired", "owner": "me", "module": "payroll", "sql": "x"}\n```'
    monkeypatch.setattr(ai_client, "create_message", fake)
    got = find.parse("expired q3 pentest reports of mine")
    assert got == {"filters": {"words": ["pentest", "q3"], "state": "expired", "owner": "me"}, "mode": "ai", "note": None}
    assert seen["feature"] == "evidence.find_evidence" and seen["sources"] == []
    assert seen["messages"][0]["content"].endswith("<user_input>expired q3 pentest reports of mine</user_input>")
    assert "evidence.find_evidence" in ai_policy.FEATURES


@pytest.mark.parametrize("failure, phrase", [
    ("unconfigured", "not configured"), ("policy", "turned off"), ("error", "did not answer"), ("garbage", "named nothing usable")])
def test_when_the_model_cannot_be_used_the_rules_read_the_question_and_say_so(monkeypatch, failure, phrase):
    monkeypatch.setattr(ai_client, "is_configured", lambda: failure != "unconfigured")

    def fake(messages, **kw):
        if failure == "policy":
            raise ai_policy.AIPolicyError("disabled", "AI is turned off for your organization.")
        if failure == "error":
            raise RuntimeError("provider down")
        return "I cannot help with that."
    monkeypatch.setattr(ai_client, "create_message", fake)
    got = find.parse("expired reports")
    assert got["mode"] == "rules" and got["filters"] == {"state": "expired", "words": ["reports"]}
    assert phrase in got["note"]
    assert find.parse("expired reports", use_ai=False) == {"filters": got["filters"], "mode": "rules", "note": None}


# ── Find evidence: the answer ───────────────────────────────────────────────

def _find(auth, user, **body):
    result = asyncio.run(ev.api_evidence_find(_json_req(auth, user, body)))
    return result.status_code, json.loads(result.body)


def test_find_returns_at_most_five_permitted_files_each_with_its_reasons(lib, auth):
    for n in range(7):
        lib.item(f"Access review report {n}", owner=51)
    lib.item("Access review in another unit", unit=lib.unit_b)
    lib.item("Unrelated invoice", owner=51)
    status, body = _find(auth, lib.people.unit_a, question="access review report", use_ai=False)
    assert status == 200 and body["mode"] == "rules" and body["total"] == 7 and len(body["results"]) == 5
    assert body["filters"] == {"words": ["access", "review", "report"]}
    assert all(r["title"].startswith("Access review report") for r in body["results"])
    first = body["results"][0]
    assert first["why"][0] == '"access" is in the title' and first["url"] == f"/evidence/?open=item:{first['id']}"
    assert first["state"]["key"] == "needs_filing" and first["version"] == 1
    assert body["vocabulary"]["states"][0] == {"id": "needs_filing", "label": "Needs filing"}


def test_find_applies_a_state_and_owner_and_can_say_that_nothing_matches(lib, auth):
    mine = lib.item("Lapsed attestation", owner=52, expiry_date=_day(-2))
    lib.item("Lapsed attestation of another", owner=51, expiry_date=_day(-2))
    status, body = _find(auth, lib.people.reviewer, question="expired attestation that is mine", use_ai=False)
    assert [r["id"] for r in body["results"]] == [mine] and body["results"][0]["state"]["key"] == "expired"
    assert body["results"][0]["why"][-2:] == ["State: expired", "You are its owner"]
    status, none = _find(auth, lib.people.reviewer, question="expired zebra crossing certificates", use_ai=False)
    assert none["results"] == [] and none["message"].startswith("No accessible match")
    status, edited = _find(auth, lib.people.reviewer, filters={"state": "expired", "owner": "me", "words": []})
    assert edited["mode"] == "edited" and [r["id"] for r in edited["results"]] == [mine]


def test_find_never_names_a_file_or_claim_the_caller_may_not_open(lib, auth):
    secret = lib.item("Restructuring plan evidence", unit=lib.unit_b, owner=51)
    lib.link(secret, lib.risk("Layoff risk", lib.unit_b))
    visible = lib.item("Restructuring evidence summary", owner=52)
    lib.link(visible, lib.risk("Layoff risk", lib.unit_b))
    status, body = _find(auth, lib.people.unit_a, question="restructuring evidence", use_ai=False)
    assert [r["title"] for r in body["results"]] == ["Restructuring evidence summary"]
    assert "Layoff risk" not in json.dumps(body) and body["results"][0]["claims_hidden"] == 1
    status, outsider = _find(auth, lib.people.elsewhere, question="restructuring evidence", use_ai=False)
    assert outsider["results"] == [] and outsider["total"] == 0


def test_find_checks_the_question_and_changes_nothing(lib, auth):
    status, body = _find(auth, lib.people.uploader, question="   ")
    assert status == 422 and "Ask a question" in body["error"]
    status, body = _find(auth, lib.people.uploader, question="x" * 301)
    assert status == 422 and "300" in body["error"]
    item = lib.item("Unlinked file", owner=51)
    before = lib.db.execute("SELECT COUNT(*) FROM evidence_links").fetchone()[0]
    _find(auth, lib.people.uploader, question="unlinked file", use_ai=False)
    assert lib.db.execute("SELECT COUNT(*) FROM evidence_links").fetchone()[0] == before
    assert lib.db.execute("SELECT status FROM evidence_items WHERE id = %s", (item,)).fetchone()["status"] == "current"


def test_the_state_filters_partition_the_files_the_way_the_state_column_says(lib, auth):
    lib.item("Nobody linked")
    lib.item("Lapsed", expiry_date=_day(-1))
    lib.link(lib.item("Waiting"), lib.risk("R1"))
    lib.link(lib.item("Turned down"), lib.risk("R2"), status="returned")
    lib.link(lib.item("Signed off"), lib.risk("R3"), status="accepted")
    lib.link(lib.item("Mixed"), lib.risk("R4"), status="accepted")
    lib.db.execute("INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, review_status) "
                   "SELECT id, 'erm', 'risk', 1, NULL FROM evidence_items WHERE title = 'Mixed'")
    lib.db.commit()
    seen = {}
    for state in find.STATES:
        rows, body = _rows(auth, lib.people.uploader, state=state)
        for title, row in rows.items():
            assert row["state"]["key"] == state, (title, state)
            seen.setdefault(title, []).append(state)
    assert all(len(v) == 1 for v in seen.values()), "no file is in two states"
    assert seen == {"Nobody linked": ["needs_filing"], "Lapsed": ["expired"], "Waiting": ["awaiting_review"],
                    "Turned down": ["returned"], "Signed off": ["accepted"], "Mixed": ["awaiting_review"]}
