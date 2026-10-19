"""
The response to a requester (plans/2026-10-governance-rework/01 section 6), through the service layer and HTTP.

Written by hand. It is drafted from a standing decision and says the decision's own outcome and conditions; a different
person with the right to decide approves it, which freezes it under a hash; a download is an export and never a delivery;
a response whose decision stopped standing cannot be exported; and a hidden use has no responses for the caller.
"""
import json

import pytest

from core import ai_rollout
from modules.ai_governance import decisions, imports
from modules.ai_governance import external_responses as er
from modules.ai_governance import service
from tests.test_ai_governance_decisions import ask, decide, resolve_provider_review
from tests.test_ai_governance_decisions_routes import _ask, _decide, _resolve
from tests.test_ai_governance_imports import confirm as confirm_import
from tests.test_ai_governance_imports import export as csv_export
from tests.test_ai_governance_imports import preview as preview_import
from tests.test_ai_governance_imports import response as form_response
from tests.test_ai_governance_routes import _accepted, http  # noqa: F401
from tests.test_ai_governance_service import FULL, approve_new, commit, count, fail, roles, submitted, user  # noqa: F401
from tests.test_platform_ownership import PERSONAS, _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401


@pytest.fixture
def system(world, roles):
    done = approve_new(world, submitted(world, answers=FULL))
    world.app = done["application_id"]
    return world


def approved_use(world, conditions=None, **more):
    resolve_provider_review(world)
    row = ask(world, "dpo_a")
    if conditions:
        return decide(world, row, "approve_with_conditions", rationale="Fine with conditions.", conditions=conditions, **more)
    return decide(world, row, "approve", rationale="Fine.", **more)


def drafted(world, who="dpo_a"):
    done = er.create_draft(world.db, user(world, who), world.app)
    commit(world, done, user(world, who))
    return done["response"]


def edited(world, draft, who="dpo_a", **fields):
    fields = {"summary": "The use is approved for the pilot.", "scope": "Support agents only.", "response_date": "2026-10-20", **fields}
    done = er.update_draft(world.db, user(world, who), draft["id"], fields, draft["version"])
    commit(world, done, user(world, who))
    return done["response"]


def approved(world, draft, who="owner_a"):
    done = er.approve(world.db, user(world, who), draft["id"], draft["version"])
    commit(world, done, user(world, who))
    return done["response"]


def export(world, response, fmt="json", who="dpo_a"):
    done = er.export(world.db, user(world, who), response["id"], fmt)
    commit(world, done, user(world, who))
    return done


# ── Drafting ────────────────────────────────────────────────────────────────

def test_there_is_nothing_to_respond_with_until_a_decision_stands(system):
    fail(lambda: er.create_draft(system.db, user(system, "dpo_a"), system.app), 409)
    got = er.list_for_use(system.db, user(system, "dpo_a"), system.app)
    assert got["can_draft"] is False and got["decision"] is None and got["responses"] == []


def test_a_draft_says_the_decisions_own_outcome_and_conditions_and_names_nothing_internal(system):
    approved_use(system, conditions=[{"text": "Review the output weekly", "due_date": "2026-12-01"}])
    draft = drafted(system)
    assert draft["status"] == "draft" and draft["revision"] == 1
    assert draft["outcome"] == "approved_with_conditions" and draft["outcome_label"] == "Approved with conditions"
    assert draft["conditions"] == [{"text": "Review the output weekly", "due_date": "2026-12-01"}]
    assert draft["frozen"] is False and draft["preview"]["subject"]["name"] == "Ticket summarizer"
    text = json.dumps(draft["preview"])
    for internal in ("dpo_a", "owner_a", "rationale", "Fine with conditions", "tier", "manifest"):
        assert internal not in text, internal
    assert "not a certification" in draft["preview"]["limitations"]


def test_drafting_again_for_the_same_decision_returns_the_draft_and_a_new_decision_starts_a_revision(system):
    approved_use(system)
    first = drafted(system)
    again = er.create_draft(system.db, user(system, "dpo_a"), system.app)
    assert again["created"] is False and again["response"]["id"] == first["id"]
    standing = decisions.get_decisions(system.db, user(system, "dpo_a"), system.app)["latest"]
    commit(system, decisions.revoke(system.db, user(system, "owner_a"), standing["id"], "The provider changed its terms."),
           user(system, "owner_a"))
    row = ask(system, "dpo_a")
    decide(system, row, "approve", rationale="Approved again after the change.")
    second = er.create_draft(system.db, user(system, "dpo_a"), system.app)
    assert second["created"] is True and second["response"]["revision"] == 2 and second["response"]["id"] != first["id"]


def test_a_response_says_whether_the_decision_it_rests_on_still_stands(system):
    approved_use(system)
    first = drafted(system)
    got = er.list_for_use(system.db, user(system, "dpo_a"), system.app)
    assert got["responses"][0]["stands"] is True and got["can_draft"] is True
    standing = decisions.get_decisions(system.db, user(system, "dpo_a"), system.app)["latest"]
    commit(system, decisions.revoke(system.db, user(system, "owner_a"), standing["id"], "The provider changed its terms."),
           user(system, "owner_a"))
    got = er.list_for_use(system.db, user(system, "dpo_a"), system.app)
    assert got["can_draft"] is False and got["responses"][0]["stands"] is False, "a revoked decision answers nobody"
    row = ask(system, "dpo_a")
    decide(system, row, "approve", rationale="Approved again after the change.")
    got = er.list_for_use(system.db, user(system, "dpo_a"), system.app)
    assert got["can_draft"] is True and got["responses"][0]["id"] == first["id"]
    assert got["responses"][0]["stands"] is False, "the old response rests on the replaced decision, not the new one"


def test_only_a_reviewer_in_the_unit_may_draft_and_a_hidden_use_has_none(system):
    approved_use(system)
    fail(lambda: er.create_draft(system.db, user(system, "employee_a"), system.app), 403)
    fail(lambda: er.create_draft(system.db, user(system, "dpo_b"), system.app), 404)
    assert er.list_for_use(system.db, user(system, "dpo_b"), system.app) is None


def test_the_requester_of_an_imported_request_is_named_in_the_draft_and_the_reference_says_which_request(world, roles):
    done = preview_import(world, data=csv_export(form_response(name="Imported helper")))
    confirm_import(world, done, rows={"2": {"owner_user_id": user(world, "employee_a")["id"]}})
    row = world.db.execute("SELECT * FROM ai_use_intake_requests WHERE source_kind = 'import'").fetchone()
    sent = service.submit(world.db, user(world, "dpo_a"), row["id"], row["version"])
    commit(world, sent, user(world, "dpo_a"))
    accepted = service.approve(world.db, user(world, "owner_a"), row["id"], sent["intake"]["version"], new_application={})
    commit(world, accepted, user(world, "owner_a"))
    world.app = accepted["application_id"]
    approved_use(world, override_reason="The other required reviews are booked for next month.")
    draft = drafted(world)
    assert draft["requester"] == {"name": "Pat Requester", "email": "pat@outside.example", "organization": "Support"}
    assert draft["source_reference"] == f"Request {row['id']}, from AI use intake"
    assert draft["preview"]["requester"] == {"name": "Pat Requester", "organization": "Support"}, "the email address is not in the document"


# ── Editing ─────────────────────────────────────────────────────────────────

def test_a_draft_is_edited_within_its_limits_and_a_stale_edit_is_refused(system):
    approved_use(system)
    draft = drafted(system)
    got = edited(system, draft, requester_actions=["Send us the data flow diagram.", "Name a technical contact."])
    assert got["summary"] == "The use is approved for the pilot." and got["version"] == draft["version"] + 1
    assert got["requester_actions"] == ["Send us the data flow diagram.", "Name a technical contact."]
    fail(lambda: er.update_draft(system.db, user(system, "dpo_a"), draft["id"], {"summary": "Old"}, draft["version"]), 409)
    for bad in ({"summary": "x" * 2001}, {"scope": "x" * 1001}, {"requester_actions": ["a"] * 11}, {"requester_actions": ["x" * 301]},
                {"requester_actions": "none"}, {"response_date": "tomorrow"}, {}):
        fail(lambda b=bad: er.update_draft(system.db, user(system, "dpo_a"), draft["id"], b, got["version"]), 422)
    fail(lambda: er.update_draft(system.db, user(system, "dpo_a"), draft["id"], {"summary": "x"}, True), 400)


# ── Approving ───────────────────────────────────────────────────────────────

def test_a_different_person_with_the_right_to_decide_approves_and_the_content_is_frozen_under_a_hash(system):
    approved_use(system)
    draft = edited(system, drafted(system))
    fail(lambda: er.approve(system.db, user(system, "dpo_a"), draft["id"], draft["version"]), 403)  # their own draft
    fail(lambda: er.approve(system.db, user(system, "employee_a"), draft["id"], draft["version"]), 403)
    done = approved(system, draft)
    assert done["status"] == "approved" and done["frozen"] is True and len(done["content_hash"]) == 64
    assert done["approved_by"] == "owner_a"
    assert done["preview"]["summary"] == "The use is approved for the pilot." and done["preview"]["response_date"] == "2026-10-20"
    fail(lambda: er.update_draft(system.db, user(system, "dpo_a"), draft["id"], {"summary": "Changed"}, done["version"]), 409)
    fail(lambda: er.approve(system.db, user(system, "owner_a"), draft["id"], done["version"]), 409)


def test_separation_can_be_off_for_an_organization_with_one_person_in_the_function(system):
    approved_use(system)
    draft = edited(system, drafted(system))
    org = user(system, "dpo_a")["org_id"]
    ai_rollout.set_separation(org, False)
    try:
        done = er.approve(system.db, user(system, "dpo_a"), draft["id"], draft["version"])
        system.db.commit()
        assert done["response"]["status"] == "approved"
    finally:
        ai_rollout.set_separation(org, True)


def test_an_incomplete_draft_cannot_be_approved(system):
    approved_use(system)
    draft = drafted(system)
    error = fail(lambda: er.approve(system.db, user(system, "owner_a"), draft["id"], draft["version"]), 422)
    assert "summary" in error.message and "response date" in error.message


def test_a_response_whose_decision_has_changed_cannot_be_approved_or_redrafted_until_it_is_decided_again(system):
    approved_use(system)
    draft = edited(system, drafted(system))
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    commit(system, service.update_profile(system.db, user(system, "dpo_a"), system.app, {"purpose": "A new purpose"},
                                          profile["version"]), user(system, "dpo_a"))
    fail(lambda: er.approve(system.db, user(system, "owner_a"), draft["id"], draft["version"]), 409)
    fail(lambda: er.create_draft(system.db, user(system, "dpo_a"), system.app), 409)


# ── Export and sent ─────────────────────────────────────────────────────────

def test_an_export_is_json_or_pdf_of_the_frozen_content_and_is_recorded_as_an_export_not_a_delivery(system):
    approved_use(system)
    ready = approved(system, edited(system, drafted(system)))
    done = export(system, ready, "json")
    assert done["media_type"] == "application/json" and done["filename"] == "ai-use-response-r1.json"
    doc = json.loads(done["body"])
    assert doc["hash"] == ready["content_hash"] and doc["response"]["outcome"]["label"] == "Approved"
    assert er.get_response(system.db, user(system, "dpo_a"), ready["id"])["response"]["status"] == "exported"
    pdf = export(system, ready, "pdf")
    assert pdf["body"][:5] == b"%PDF-" and pdf["media_type"] == "application/pdf"
    got = er.get_response(system.db, user(system, "dpo_a"), ready["id"])["response"]
    assert got["export_count"] == 2 and got["sent_at"] is None, "an export is never taken as delivery"
    fail(lambda: er.export(system.db, user(system, "dpo_a"), ready["id"], "docx"), 400)


def test_the_pdf_says_the_same_words_as_the_json_and_nothing_is_escaped_twice(system):
    from io import BytesIO

    from pypdf import PdfReader

    approved_use(system)
    draft = edited(system, drafted(system), summary="Approved for R&D <pilot> use only.", scope="Support agents & managers.",
                   requester_actions=["Send the vendor contract <signed>"])
    ready = approved(system, draft)
    pdf = export(system, ready, "pdf")
    text = " ".join(page.extract_text() for page in PdfReader(BytesIO(pdf["body"])).pages)
    for expected in ("Outcome: Approved", "Approved for R&D <pilot> use only.", "Support agents & managers.",
                     "Send the vendor contract <signed>", "Date of the response: 2026-10-20"):
        assert expected in text, expected
    for leaked in ("&amp;", "&lt;", "&gt;", "<b>", "</b>"):
        assert leaked not in text, leaked


def test_a_draft_cannot_be_exported_and_a_tampered_content_never_leaves(system):
    approved_use(system)
    draft = edited(system, drafted(system))
    fail(lambda: er.export(system.db, user(system, "dpo_a"), draft["id"], "json"), 409)
    ready = approved(system, draft)
    system.db.execute("UPDATE ai_external_responses SET content = REPLACE(content, 'pilot', 'whole company') WHERE id = %s", (ready["id"],))
    system.db.commit()
    fail(lambda: er.export(system.db, user(system, "dpo_a"), ready["id"], "json"), 409)


def test_sent_is_recorded_by_a_person_with_the_date_the_channel_and_a_reference_and_only_after_an_export(system):
    approved_use(system)
    ready = approved(system, edited(system, drafted(system)))
    fail(lambda: er.mark_sent(system.db, user(system, "dpo_a"), ready["id"], "2026-10-21", "Email", None, ready["version"]), 409)
    export(system, ready)
    now = er.get_response(system.db, user(system, "dpo_a"), ready["id"])["response"]
    fail(lambda: er.mark_sent(system.db, user(system, "dpo_a"), ready["id"], "", "Email", None, now["version"]), 422)
    fail(lambda: er.mark_sent(system.db, user(system, "dpo_a"), ready["id"], "2026-10-21", "", None, now["version"]), 422)
    done = er.mark_sent(system.db, user(system, "dpo_a"), ready["id"], "2026-10-21", "Email to Pat", "Message 4411", now["version"])
    commit(system, done, user(system, "dpo_a"))
    got = done["response"]
    assert (got["status"], got["sent_at"], got["sent_channel"], got["sent_reference"], got["sent_by"]) == (
        "sent", "2026-10-21", "Email to Pat", "Message 4411", "dpo_a")
    assert done["audit"][0][0] == "ai_response_sent"


def test_a_response_whose_decision_was_revoked_cannot_be_exported_or_redrafted(system):
    approved_use(system)
    ready = approved(system, edited(system, drafted(system)))
    standing = decisions.get_decisions(system.db, user(system, "dpo_a"), system.app)["latest"]
    commit(system, decisions.revoke(system.db, user(system, "owner_a"), standing["id"], "The provider changed its terms."),
           user(system, "owner_a"))
    fail(lambda: er.export(system.db, user(system, "dpo_a"), ready["id"], "json"), 409)
    fail(lambda: er.create_draft(system.db, user(system, "dpo_a"), system.app), 409)


def test_a_response_can_be_withdrawn_with_a_reason_and_then_a_new_one_is_drafted(system):
    approved_use(system)
    ready = approved(system, edited(system, drafted(system)))
    fail(lambda: er.withdraw(system.db, user(system, "dpo_a"), ready["id"], "", ready["version"]), 422)
    gone = er.withdraw(system.db, user(system, "dpo_a"), ready["id"], "Sent to the wrong team.", ready["version"])
    commit(system, gone, user(system, "dpo_a"))
    assert gone["response"]["status"] == "withdrawn" and gone["response"]["withdraw_reason"] == "Sent to the wrong team."
    fail(lambda: er.export(system.db, user(system, "dpo_a"), ready["id"], "json"), 409)
    fail(lambda: er.withdraw(system.db, user(system, "dpo_a"), ready["id"], "Again", gone["response"]["version"]), 409)
    fresh = er.create_draft(system.db, user(system, "dpo_a"), system.app)
    assert fresh["created"] is True and fresh["response"]["revision"] == 2 and fresh["response"]["status"] == "draft"


def test_the_responses_of_another_unit_do_not_exist_for_the_caller(system):
    approved_use(system)
    ready = approved(system, edited(system, drafted(system)))
    for call in (lambda: er.get_response(system.db, user(system, "dpo_b"), ready["id"]),
                 lambda: er.export(system.db, user(system, "dpo_b"), ready["id"], "json"),
                 lambda: er.withdraw(system.db, user(system, "dpo_b"), ready["id"], "x", 1)):
        fail(call, 404)


# ── Through HTTP ────────────────────────────────────────────────────────────

API = "/ai-governance/api"


def test_nobody_signed_out_and_no_outsider_reaches_a_response(http):
    for method, tail in (("get", "/systems/1/responses"), ("post", "/systems/1/responses"), ("get", "/responses/1"),
                         ("put", "/responses/1"), ("post", "/responses/1/approve"), ("post", "/responses/1/export"),
                         ("post", "/responses/1/sent"), ("post", "/responses/1/withdraw")):
        extra = {} if method == "get" else {"json": {}}
        assert http(method, f"{API}{tail}", name=None, **extra).status_code == 303, tail
        assert http(method, f"{API}{tail}", name="auditor", **extra).status_code == 403, tail
        assert http(method, f"{API}{tail}", name="employee_a", **extra).status_code == 403, tail


def test_the_whole_journey_through_http(http):
    app = _accepted(http)
    base = f"{API}/systems/{app}/responses"
    assert http("post", base, name="dpo_a", json={}).status_code == 409, "no decision stands yet"
    assert http("get", base, name="dpo_b").status_code == 404
    _resolve(http, app)
    decision = _ask(http, app, "dpo_a", "Ready.")
    assert _decide(http, app, decision, "approve", rationale="Fine.").status_code == 200
    made = http("post", base, name="dpo_a", json={})
    assert made.status_code == 201 and made.json()["response"]["status"] == "draft"
    response = made.json()["response"]
    assert http("post", base, name="dpo_a", json={}).json()["created"] is False
    edited_ = http("put", f"{API}/responses/{response['id']}", name="dpo_a", json={
        "version": response["version"], "fields": {"summary": "Approved for the pilot.", "response_date": "2026-10-20"}})
    assert edited_.status_code == 200
    version = edited_.json()["response"]["version"]
    assert http("post", f"{API}/responses/{response['id']}/approve", name="dpo_a", json={"version": version}).status_code == 403
    approved_ = http("post", f"{API}/responses/{response['id']}/approve", name="owner_a", json={"version": version})
    assert approved_.status_code == 200 and approved_.json()["response"]["status"] == "approved"
    file = http("post", f"{API}/responses/{response['id']}/export", name="dpo_a", json={"format": "pdf"})
    assert file.status_code == 200 and file.content[:5] == b"%PDF-"
    assert "attachment" in file.headers["content-disposition"] and file.headers["cache-control"] == "private, no-store"
    again = http("get", f"{API}/responses/{response['id']}", name="dpo_a").json()["response"]
    assert again["status"] == "exported" and again["export_count"] == 1
    sent = http("post", f"{API}/responses/{response['id']}/sent", name="dpo_a", json={
        "version": again["version"], "sent_at": "2026-10-21", "channel": "Email to the requester", "reference": "Ref 1"})
    assert sent.status_code == 200 and sent.json()["response"]["status"] == "sent"
    assert http("post", f"{API}/responses/{response['id']}/export", name="dpo_b", json={"format": "json"}).status_code == 404
    assert http("post", f"{API}/responses/{response['id']}/export", name="dpo_a", content=b"[1]",
                headers={"content-type": "application/json"}).status_code == 400
