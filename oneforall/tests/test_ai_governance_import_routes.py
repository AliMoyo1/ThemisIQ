"""
The external form import through HTTP (plans/2026-10-governance-rework/01 section 4).

Written by hand. Nobody signed out and no outside auditor reaches it, staff are refused, the upload is bounded and the
answers say what is wrong in a sentence, the same file twice makes one request, and a batch is read only inside its unit.
"""
import pytest

from modules.ai_governance import import_rules as ir
from tests.test_ai_governance_imports import export, response
from tests.test_ai_governance_routes import http  # noqa: F401
from tests.test_platform_ownership import PERSONAS, _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401

API = "/ai-governance/api/import"


def upload(http, name="dpo_a", data=None, filename="responses.csv", **fields):
    form = {"source_system": "google_forms", "form_name": "AI use intake", "date_order": "iso", **fields}
    return http("post", f"{API}/preview", name=name, files={"file": (filename, data if data is not None else export(response()), "text/csv")},
                data=form)


def confirm(http, batch, name="dpo_a", rows=None):
    return http("post", f"{API}/batches/{batch['id']}/confirm", name=name, json={"version": batch["version"], "rows": rows or {}})


READS = (f"{API}/guide", f"{API}/template.csv", f"{API}/batches", f"{API}/batches/1", "/ai-governance/import")


@pytest.mark.parametrize("path", READS)
def test_nobody_signed_out_reaches_the_import(http, path):
    assert http("get", path, name=None).status_code == 303


@pytest.mark.parametrize("path", READS)
def test_an_outside_auditor_and_staff_are_refused(http, path):
    assert http("get", path, name="auditor").status_code == 403
    assert http("get", path, name="staff_a").status_code == 403


def test_signed_out_staff_and_auditors_cannot_upload_or_decide(http):
    assert upload(http, name=None).status_code == 303
    assert upload(http, name="staff_a").status_code == 403
    assert upload(http, name="auditor").status_code == 403
    for name in ("staff_a", "auditor"):
        assert http("post", f"{API}/batches/1/confirm", name=name, json={"version": 1}).status_code == 403
        assert http("post", f"{API}/batches/1/discard", name=name, json={"version": 1}).status_code == 403


def test_the_guide_and_the_template_are_published_to_reviewers(http):
    guide = http("get", f"{API}/guide", name="dpo_a").json()
    assert guide["version"] == "forms-v1" and guide["questions"][0]["target"] == "name"
    assert guide["limits"]["rows"] == ir.MAX_ROWS and "google_forms" in guide["source_systems"]
    template = http("get", f"{API}/template.csv", name="dpo_a")
    assert template.status_code == 200 and template.headers["content-type"].startswith("text/csv")
    assert "attachment" in template.headers["content-disposition"] and template.headers["x-content-type-options"] == "nosniff"
    assert template.text.splitlines()[0].startswith("What is the name of the AI tool or use?")


def test_the_page_opens_for_a_reviewer_and_is_not_cached(http):
    page = http("get", "/ai-governance/import", name="dpo_a")
    assert page.status_code == 200 and "aigImport" in page.text and page.headers["cache-control"] == "no-store"


def test_the_whole_journey_from_an_export_to_a_draft_the_importer_can_open(http):
    previewed = upload(http)
    assert previewed.status_code == 201 and previewed.headers["cache-control"] == "private, no-store"
    batch = previewed.json()["batch"]
    assert batch["counts"]["new"] == 1 and batch["rows"][0]["owner_candidates"][0]["name"] == "employee_a"
    owner = batch["rows"][0]["owner_candidates"][0]["id"]
    done = confirm(http, batch, rows={"2": {"owner_user_id": owner}})
    assert done.status_code == 200 and done.json()["summary"]["created"] == 1
    intake_id = done.json()["created"][0]["intake_id"]
    mine = http("get", f"/ai-governance/api/requests/{intake_id}", name="dpo_a").json()["intake"]
    assert mine["source_kind"] == "import" and mine["requester"]["email"] == "pat@outside.example" and mine["status"] == "draft"
    assert http("get", f"/ai-governance/api/requests/{intake_id}", name="dpo_b").status_code == 404
    again = upload(http).json()["batch"]
    assert again["rows"][0]["outcome"] == "duplicate"
    assert confirm(http, again).json()["summary"]["duplicates"] == 1
    listed = http("get", "/ai-governance/api/requests", name="dpo_a").json()["items"]
    assert len(listed) == 1


def test_a_second_confirmation_is_the_same_answer(http):
    batch = upload(http).json()["batch"]
    first = confirm(http, batch)
    second = confirm(http, batch)
    assert first.status_code == 200 and second.status_code == 200 and second.json()["already"] is True
    assert len(http("get", "/ai-governance/api/requests", name="dpo_a").json()["items"]) == 1


def test_a_file_that_cannot_be_read_comes_back_with_a_sentence(http):
    empty = upload(http, data=b"")
    assert empty.status_code == 422 and "empty" in empty.json()["errors"]["file"]
    wrong = upload(http, data=b"%PDF-1.4", filename="scan.pdf")
    assert wrong.status_code == 422 and ".csv or .xlsx" in wrong.json()["errors"]["file"]
    huge = upload(http, data=b"a\n" + b"x" * (ir.MAX_FILE_BYTES + 10))
    assert huge.status_code == 422 and "larger than" in huge.json()["errors"]["file"]


def test_bad_form_fields_and_a_bad_mapping_are_refused_before_anything_is_stored(http):
    assert upload(http, source_system="paper").status_code == 422
    assert upload(http, form_name="  ").status_code == 422
    assert upload(http, business_unit_id="abc").status_code == 400
    assert upload(http, mapping="not json").status_code == 400
    assert upload(http, mapping="[1, 2]").status_code == 400
    bad = upload(http, mapping='{"What will it be used for?": "purpose"}')
    assert bad.status_code == 422 and "name of the AI use" in bad.json()["errors"]["mapping"]
    assert http("get", f"{API}/batches", name="dpo_a").json()["batches"] == []


def test_a_batch_is_read_inside_its_unit_only(http):
    batch = upload(http).json()["batch"]
    assert http("get", f"{API}/batches/{batch['id']}", name="dpo_a").status_code == 200
    missing = http("get", f"{API}/batches/987654", name="dpo_b")
    hidden = http("get", f"{API}/batches/{batch['id']}", name="dpo_b")
    assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()
    assert confirm(http, batch, name="dpo_b").status_code == 404
    assert http("get", f"{API}/batches", name="dpo_b").json()["batches"] == []


@pytest.mark.parametrize("body", [b"{nope", b"[1]"])
def test_a_confirm_that_is_not_a_json_object_is_refused(http, body):
    batch = upload(http).json()["batch"]
    for action in ("confirm", "discard"):
        response_ = http("post", f"{API}/batches/{batch['id']}/{action}", name="dpo_a", content=body,
                         headers={"content-type": "application/json"})
        assert response_.status_code == 400
