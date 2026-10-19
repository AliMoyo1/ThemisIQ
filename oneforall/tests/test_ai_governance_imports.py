"""
Importing the responses of an external form (plans/2026-10-governance-rework/01 section 4), through the service layer.

Written by hand. A preview creates nothing; the same response twice creates nothing the second time; a correction is a new
revision with its differences and never edits an earlier request; an owner is a person the specialist confirmed or an
explicit gap; a response with an error never becomes a request; and a batch belongs to the unit it was imported into.
"""
import io
import json

import pytest

from core import rbac
from modules.ai_governance import import_rules as ir
from modules.ai_governance import imports, service
from modules.ai_governance.service import ServiceError
from tests.test_ai_governance_service import FULL, approve_new, commit, count, fail, roles, user  # noqa: F401
from tests.test_platform_ownership import PERSONAS, _insert, world  # noqa: F401

HEADERS = [g["question"] for g in ir.FIELD_GUIDE if g["target"] != "response_id"]


def response(**changes):
    base = {
        "name": "Ticket helper", "purpose": "Summarize support tickets", "requester_name": "Pat Requester",
        "requester_email": "pat@outside.example", "requester_organization": "Support", "provider_name": "Acme AI",
        "deployment": "A vendor's AI service that we call", "intended_users": "Support agents",
        "data_categories": "Internal business information; Personal data", "affects_decisions": "No",
        "target_launch": "2026-12-01", "owner": "employee_a@example.test"}
    base.update(changes)
    return base


def export(*responses, headers=HEADERS, extra=None) -> bytes:
    """A CSV of the responses. `extra` is {column header: value} appended to every row (a column the form tool added)."""
    by_question = {g["question"]: g["target"] for g in ir.FIELD_GUIDE}
    extra = extra or {}
    lines = [",".join(f'"{h}"' for h in [*headers, *extra])]
    for r in responses:
        values = [str(r.get(by_question.get(h), "")) for h in headers] + [str(v) for v in extra.values()]
        lines.append(",".join('"' + v.replace('"', '""') + '"' for v in values))
    return "\r\n".join(lines).encode("utf-8")


def preview(world, who="dpo_a", data=None, **kw):
    kw.setdefault("source_system", "google_forms")
    kw.setdefault("form_name", "AI use intake")
    kw.setdefault("filename", "responses.csv")
    done = imports.preview(world.db, user(world, who), data=data if data is not None else export(response()), **kw)
    commit(world, done, user(world, who))
    return done


def confirm(world, done, who="dpo_a", rows=None):
    result = imports.confirm(world.db, user(world, who), done["batch"]["id"], done["batch"]["version"], rows)
    commit(world, result, user(world, who))
    return result


def intake_rows(world):
    return world.db.execute("SELECT * FROM ai_use_intake_requests ORDER BY id").fetchall()


# ── Preview ─────────────────────────────────────────────────────────────────

def test_a_preview_reads_the_export_and_creates_no_request(world):
    done = preview(world)
    assert count(world, "ai_use_intake_requests") == 0
    batch = done["batch"]
    assert batch["status"] == "previewed" and batch["row_count"] == 1 and batch["counts"]["new"] == 1
    only = batch["rows"][0]
    assert only["outcome"] == "new" and only["row_number"] == 2 and only["issues"] == [] and only["missing"] == []
    assert only["answers"]["deployment"] == "vendor_service" and only["requester"]["email"] == "pat@outside.example"
    assert batch["mapping"]["What is the name of the AI tool or use?"] == "name"
    assert batch["business_unit_id"] == world.unit["A"] and batch["file_kind"] == "csv"
    assert done["audit"][0][0] == "ai_import_previewed"


def test_a_valid_preview_mapping_can_be_reused_and_archived_without_changing_its_batch(world):
    specialist = user(world, "dpo_a")
    first = preview(world)
    batch_id = first["batch"]["id"]
    saved = imports.save_mapping(world.db, specialist, batch_id, "Support intake")
    commit(world, saved, specialist)
    mapping_id = saved["id"]
    listed = imports.list_saved_mappings(world.db, specialist)["mappings"]
    assert [entry["id"] for entry in listed] == [mapping_id]
    assert listed[0]["mapping"] == first["batch"]["mapping"]

    reused = preview(world, mapping=listed[0]["mapping"])
    assert reused["batch"]["mapping"] == first["batch"]["mapping"]
    archived = imports.archive_mapping(world.db, specialist, mapping_id)
    commit(world, archived, specialist)
    assert imports.list_saved_mappings(world.db, specialist)["mappings"] == []
    assert imports.get_batch(world.db, specialist, batch_id)["batch"]["mapping"] == first["batch"]["mapping"]


def test_an_unpreviewed_or_hidden_mapping_cannot_be_saved(world):
    done = preview(world)
    fail(lambda: imports.save_mapping(world.db, user(world, "dpo_b"), done["batch"]["id"], "Hidden"), 404)
    fail(lambda: imports.save_mapping(world.db, user(world, "employee_a"), done["batch"]["id"], "No review role"), 403)
    fail(lambda: imports.save_mapping(world.db, user(world, "dpo_a"), 99999, "Missing"), 404)


def test_the_owner_is_offered_as_candidates_and_never_assigned(world):
    only = preview(world)["batch"]["rows"][0]
    assert [(c["name"], c["by"]) for c in only["owner_candidates"]] == [("employee_a", "email")]
    by_name = preview(world, data=export(response(owner="dpo_b")))["batch"]["rows"][0]
    assert [(c["name"], c["by"]) for c in by_name["owner_candidates"]] == [("dpo_b", "name")]
    nobody = preview(world, data=export(response(owner="Somebody Unknown")))["batch"]["rows"][0]
    assert nobody["owner_candidates"] == [] and nobody["owner_hint"] == "Somebody Unknown"
    assert "owner_user_id" not in only["answers"], "the import never sets an owner by itself"


def test_an_application_that_may_already_be_this_use_is_listed(world):
    existing = _insert(world.db, "applications", name="Ticket helper", business_unit_id=world.unit["A"], is_active=1)
    world.db.commit()
    matches = preview(world)["batch"]["rows"][0]["matches"]
    assert existing in [m["id"] for m in matches]


def test_unknown_choices_are_reported_and_left_open_not_guessed(world):
    only = preview(world, data=export(response(deployment="Somewhere in the cloud", data_categories="Personal data; Secrets",
                                               affects_decisions="Perhaps")))["batch"]["rows"][0]
    assert only["outcome"] == "new" and only["answers"]["deployment"] is None
    assert only["answers"]["data_categories"] == ["personal"] and only["answers"]["affects_decisions"] is None
    assert len(only["issues"]) == 3 and all(i["level"] == "warning" for i in only["issues"])
    assert "deployment" in only["missing"]


def test_a_response_with_no_name_is_an_error_and_a_repeat_in_the_file_counts_once(world):
    done = preview(world, data=export(response(name=""), response(), response(purpose="Summarize tickets and email")))
    outcomes = [r["outcome"] for r in done["batch"]["rows"]]
    assert outcomes == ["error", "replaced_in_file", "new"]
    assert done["batch"]["counts"] == {"new": 1, "duplicate": 0, "revision": 0, "error": 1, "replaced_in_file": 1}
    assert done["batch"]["rows"][2]["answers"]["purpose"] == "Summarize tickets and email", "the last response of a key wins"


def test_a_mapping_with_a_problem_or_a_file_that_is_not_an_export_is_refused_with_a_sentence(world):
    headers = ["A", "B"]
    bad = fail(lambda: imports.preview(world.db, user(world, "dpo_a"), data=b"A,B\r\n1,2", filename="x.csv",
                                       source_system="other", form_name="F", mapping={"A": "purpose", "B": ""}), 422)
    assert "name of the AI use" in bad.extra["errors"]["mapping"] and bad.extra["headers"] == headers
    junk = fail(lambda: imports.preview(world.db, user(world, "dpo_a"), data=b"", filename="x.csv", source_system="other",
                                        form_name="F"), 422)
    assert "empty" in junk.extra["errors"]["file"]
    for kw, field in (({"source_system": "paper"}, "source_system"), ({"form_name": " "}, "form_name"),
                      ({"date_order": "ymd"}, "date_order"), ({"export_date": "yesterday"}, "export_date")):
        args = {"data": export(response()), "filename": "x.csv", "source_system": "other", "form_name": "F", **kw}
        assert field in fail(lambda a=args: imports.preview(world.db, user(world, "dpo_a"), **a), 422).extra["errors"]
    assert count(world, "ai_import_batches", "status = 'previewed'") == 0


def test_a_workbook_is_read_like_a_csv(world):
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.append(HEADERS)
    r = response()
    by_question = {g["question"]: g["target"] for g in ir.FIELD_GUIDE}
    sheet.append([r.get(by_question[h], "") for h in HEADERS])
    buffer = io.BytesIO()
    book.save(buffer)
    done = preview(world, data=buffer.getvalue(), filename="export.xlsx", source_system="microsoft_forms")
    assert done["batch"]["file_kind"] == "xlsx" and done["batch"]["rows"][0]["answers"]["name"] == "Ticket helper"


# ── Who may ─────────────────────────────────────────────────────────────────

def test_only_reviewers_may_import_and_only_those_in_the_batchs_unit_may_open_it(world):
    fail(lambda: imports.preview(world.db, user(world, "employee_a"), data=export(response()), filename="x.csv",
                                 source_system="other", form_name="F"), 403)
    done = preview(world)
    assert imports.get_batch(world.db, user(world, "dpo_a"), done["batch"]["id"])["batch"]["row_count"] == 1
    fail(lambda: imports.get_batch(world.db, user(world, "dpo_a1"), done["batch"]["id"]), 404)  # a child unit does not see its parent's
    fail(lambda: imports.get_batch(world.db, user(world, "dpo_b"), done["batch"]["id"]), 404)
    fail(lambda: imports.confirm(world.db, user(world, "dpo_b"), done["batch"]["id"], 1), 404)
    fail(lambda: imports.discard(world.db, user(world, "dpo_b"), done["batch"]["id"], 1), 404)
    assert imports.list_batches(world.db, user(world, "dpo_b"))["batches"] == []
    assert [b["id"] for b in imports.list_batches(world.db, user(world, "dpo_a"))["batches"]] == [done["batch"]["id"]]


def test_a_batch_cannot_be_put_in_a_unit_the_importer_does_not_belong_to(world):
    fail(lambda: imports.preview(world.db, user(world, "dpo_a"), data=export(response()), filename="x.csv",
                                 source_system="other", form_name="F", business_unit_id=world.unit["B"]), 400)
    below = preview(world, business_unit_id=world.unit["A1"])
    assert below["batch"]["business_unit_id"] == world.unit["A1"]


# ── Confirm ─────────────────────────────────────────────────────────────────

def test_confirming_creates_a_draft_authored_by_the_importer_with_the_requesters_own_facts(world):
    done = preview(world)
    result = confirm(world, done, rows={"2": {"owner_user_id": user(world, "employee_a")["id"]}})
    assert result["summary"] == {"created": 1, "revised": 0, "skipped": 0, "duplicates": 0}
    [row] = intake_rows(world)
    assert (row["status"], row["submitted_by"], row["source_kind"], row["revision"]) == ("draft", user(world, "dpo_a")["id"], "import", 1)
    assert row["business_unit_id"] == world.unit["A"] and row["import_batch_id"] == done["batch"]["id"]
    shown = service.get_intake(world.db, user(world, "dpo_a"), row["id"])
    assert shown["source_kind"] == "import" and shown["requester"]["name"] == "Pat Requester"
    assert shown["requester"]["owner_named_in_form"] == "employee_a@example.test"
    assert shown["answers"]["owner_user_id"] == user(world, "employee_a")["id"] and shown["answers"]["name"] == "Ticket helper"
    actions = [a[0] for a in result["audit"]]
    assert actions == ["ai_use_draft_created", "ai_import_confirmed"]
    assert "import" in result["audit"][0][3] and "row 2" in result["audit"][0][3]


def test_the_requester_gets_no_account_and_no_access(world):
    before = count(world, "users")
    confirm(world, preview(world))
    assert count(world, "users") == before
    [row] = intake_rows(world)
    fail(lambda: service.get_intake(world.db, user(world, "dpo_b"), row["id"]), 404)
    fail(lambda: service.get_intake(world.db, user(world, "employee_a"), row["id"]), 404)


def test_an_owner_left_open_stays_a_gap_and_blocks_submission(world):
    confirm(world, preview(world))
    [row] = intake_rows(world)
    answers = json.loads(row["payload"])
    assert answers["owner_user_id"] is None
    error = fail(lambda: service.submit(world.db, user(world, "dpo_a"), row["id"], row["version"]), 422)
    assert "owner_user_id" in error.extra["missing"]


def test_an_owner_must_be_an_active_person_of_the_organization(world):
    world.db.execute("INSERT INTO organizations (id, name, slug) VALUES (2, 'other', 'other')")
    stranger = _insert(world.db, "users", id=70, username="stranger", email="s@example.test", full_name="Stranger",
                       password_hash="x", org_id=2)
    done = preview(world)
    fail(lambda: imports.confirm(world.db, user(world, "dpo_a"), done["batch"]["id"], done["batch"]["version"],
                                 {"2": {"owner_user_id": stranger}}), 400)
    world.db.rollback()  # a route rolls back a refused step, which also releases the batch it had claimed
    fail(lambda: imports.confirm(world.db, user(world, "dpo_a"), done["batch"]["id"], done["batch"]["version"],
                                 {"2": {"owner_user_id": True}}), 422)
    world.db.rollback()
    assert count(world, "ai_use_intake_requests") == 0 and imports.get_batch(world.db, user(world, "dpo_a"), done["batch"]["id"])["batch"]["status"] == "previewed"


def test_a_completed_imported_draft_goes_through_the_same_review_as_any_request(world):
    answers = {"owner_user_id": user(world, "employee_a")["id"]}
    confirm(world, preview(world), rows={"2": answers})
    [row] = intake_rows(world)
    sent = service.submit(world.db, user(world, "dpo_a"), row["id"], row["version"])
    commit(world, sent, user(world, "dpo_a"))
    assert sent["intake"]["status"] == "submitted"
    approved = service.approve(world.db, user(world, "owner_a"), row["id"], sent["intake"]["version"], new_application={})
    commit(world, approved, user(world, "owner_a"))
    assert approved["intake"]["status"] == "approved" and approved["created_application"] is True


def test_a_response_can_be_left_out_at_confirmation(world):
    done = preview(world, data=export(response(name="One"), response(name="Two", requester_email="two@outside.example")))
    result = confirm(world, done, rows={"2": {"include": False}})
    assert result["summary"] == {"created": 1, "revised": 0, "skipped": 1, "duplicates": 0}
    assert [json.loads(r["payload"])["name"] for r in intake_rows(world)] == ["Two"]


# ── The same response, again and corrected ──────────────────────────────────

def test_the_same_export_twice_creates_nothing_the_second_time(world):
    confirm(world, preview(world))
    again = preview(world)
    assert again["batch"]["rows"][0]["outcome"] == "duplicate" and again["batch"]["counts"]["duplicate"] == 1
    result = confirm(world, again)
    assert result["summary"] == {"created": 0, "revised": 0, "skipped": 0, "duplicates": 1} and result["created"] == []
    assert count(world, "ai_use_intake_requests") == 1


def test_confirming_twice_is_one_confirmation(world):
    done = preview(world)
    first = confirm(world, done)
    second = imports.confirm(world.db, user(world, "dpo_a"), done["batch"]["id"], done["batch"]["version"] + 1)
    assert first["summary"]["created"] == 1 and second["already"] is True and second["created"] == []
    assert count(world, "ai_use_intake_requests") == 1
    fail(lambda: imports.discard(world.db, user(world, "dpo_a"), done["batch"]["id"], 3), 409)


def test_a_corrected_response_is_a_new_revision_with_its_differences_and_the_old_draft_is_superseded(world):
    confirm(world, preview(world))
    corrected = preview(world, data=export(response(purpose="Summarize and route support tickets")))
    row = corrected["batch"]["rows"][0]
    assert row["outcome"] == "revision" and row["prior_status"] == "draft"
    assert [(d["field"], d["after"]) for d in row["diff"]] == [("purpose", "Summarize and route support tickets")]
    result = confirm(world, corrected)
    assert result["summary"] == {"created": 0, "revised": 1, "skipped": 0, "duplicates": 0}
    old, new = intake_rows(world)
    assert old["status"] == "superseded" and "revision 2" in old["review_note"]
    assert (new["status"], new["revision"], new["supersedes_id"]) == ("draft", 2, old["id"])
    assert json.loads(old["payload"])["purpose"] == "Summarize support tickets", "the earlier request is never edited"
    assert [a[0] for a in result["audit"]] == ["ai_use_draft_created", "ai_use_superseded", "ai_import_confirmed"]


def test_a_correction_of_an_accepted_request_leaves_the_decided_request_and_its_use_alone(world):
    confirm(world, preview(world), rows={"2": {"owner_user_id": user(world, "employee_a")["id"]}})
    [row] = intake_rows(world)
    sent = service.submit(world.db, user(world, "dpo_a"), row["id"], row["version"])
    commit(world, sent, user(world, "dpo_a"))
    done = service.approve(world.db, user(world, "dpo_a"), row["id"], sent["intake"]["version"], new_application={})
    commit(world, done, user(world, "dpo_a"))
    profile_before = service.get_profile(world.db, user(world, "dpo_a"), done["application_id"])

    corrected = preview(world, data=export(response(purpose="A different purpose")))
    assert corrected["batch"]["rows"][0]["prior_status"] == "approved"
    confirm(world, corrected)
    original, revision = intake_rows(world)
    assert original["status"] == "approved" and revision["status"] == "draft" and revision["supersedes_id"] == original["id"]
    profile_after = service.get_profile(world.db, user(world, "dpo_a"), done["application_id"])
    assert profile_after["purpose"] == profile_before["purpose"] == "Summarize support tickets"


def test_a_race_that_imported_the_response_since_the_preview_creates_no_second_request(world):
    first, second = preview(world), None
    second = imports.preview(world.db, user(world, "dpo_a1"), data=export(response()), filename="r.csv",
                             source_system="google_forms", form_name="AI use intake")
    commit(world, second, user(world, "dpo_a1"))
    confirm(world, first)
    result = imports.confirm(world.db, user(world, "dpo_a1"), second["batch"]["id"], second["batch"]["version"])
    commit(world, result, user(world, "dpo_a1"))
    assert result["summary"]["duplicates"] == 1 and count(world, "ai_use_intake_requests") == 1


def test_a_response_imported_between_the_check_and_the_insert_is_kept_once_and_reported_as_a_duplicate(world, monkeypatch):
    first = preview(world)
    second = imports.preview(world.db, user(world, "dpo_a1"), data=export(response()), filename="r.csv",
                             source_system="google_forms", form_name="AI use intake")
    commit(world, second, user(world, "dpo_a1"))
    confirm(world, first)
    real, looks = imports._existing_by_key, []

    def blind(db, who, key):  # the first look misses the request the other import committed a moment later
        looks.append(key)
        return None if len(looks) == 1 else real(db, who, key)
    monkeypatch.setattr(imports, "_existing_by_key", blind)
    result = imports.confirm(world.db, user(world, "dpo_a1"), second["batch"]["id"], second["batch"]["version"])
    commit(world, result, user(world, "dpo_a1"))
    assert result["summary"] == {"created": 0, "revised": 0, "skipped": 0, "duplicates": 1} and result["created"] == []
    [only] = intake_rows(world)
    stored = json.loads(world.db.execute("SELECT rows FROM ai_import_batches WHERE id = %s", (second["batch"]["id"],)).fetchone()[0])
    assert stored[0]["outcome"] == "duplicate" and stored[0]["existing_id"] == only["id"]


# ── What is kept ────────────────────────────────────────────────────────────

def test_columns_that_were_only_shown_are_dropped_when_the_import_is_confirmed(world):
    data = export(response(), extra={"Phone number": "+263 77 000 0000"})
    shown = preview(world, data=data)["batch"]["rows"][0]
    assert shown["unmapped"] == {"Phone number": "+263 77 000 0000"}
    done = confirm(world, preview(world, data=data))
    stored = json.loads(world.db.execute("SELECT rows FROM ai_import_batches WHERE id = %s", (done["batch"]["id"],)).fetchone()[0])
    assert stored[0]["unmapped"] == {} and "+263" not in json.dumps(stored)


def test_a_preview_that_was_replaced_cannot_be_confirmed_and_old_previews_are_purged(world):
    first = preview(world)
    second = preview(world)
    fail(lambda: imports.confirm(world.db, user(world, "dpo_a"), first["batch"]["id"], first["batch"]["version"] + 1), 409)
    world.db.execute("UPDATE ai_import_batches SET created_at = '2020-01-01 00:00:00' WHERE id = %s", (second["batch"]["id"],))
    world.db.commit()
    preview(world, data=export(response(name="Another use")))
    assert world.db.execute("SELECT COUNT(*) FROM ai_import_batches WHERE id = %s", (second["batch"]["id"],)).fetchone()[0] == 0


def test_a_batch_can_be_discarded_once(world):
    done = preview(world)
    gone = imports.discard(world.db, user(world, "dpo_a"), done["batch"]["id"], done["batch"]["version"])
    commit(world, gone, user(world, "dpo_a"))
    assert gone["batch"]["status"] == "discarded" and gone["audit"][0][0] == "ai_import_discarded"
    fail(lambda: imports.discard(world.db, user(world, "dpo_a"), done["batch"]["id"], done["batch"]["version"] + 1), 409)
    fail(lambda: imports.confirm(world.db, user(world, "dpo_a"), done["batch"]["id"], done["batch"]["version"] + 1), 409)


def test_the_overview_funnel_counts_a_response_once_when_it_was_superseded(world):
    from modules.ai_governance import overview
    confirm(world, preview(world), rows={"2": {"owner_user_id": user(world, "employee_a")["id"]}})
    [row] = intake_rows(world)
    sent = service.submit(world.db, user(world, "dpo_a"), row["id"], row["version"])
    commit(world, sent, user(world, "dpo_a"))
    confirm(world, preview(world, data=export(response(purpose="Corrected purpose"))))
    stages = {s["key"]: s["value"] for s in overview.get_overview(world.db, user(world, "dpo_a"))["funnel"]["detail"]["stages"]}
    assert stages["submitted"] == 0, "the submitted request was superseded by its correction, which is a draft"
