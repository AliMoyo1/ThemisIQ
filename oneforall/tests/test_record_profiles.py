"""
The record definitions: one definition of a privacy record per type, resolved for a regulation, feeding the form, the service and the
registers.

What is checked: the definition is consistent with itself (every legal anchor and option list it names exists), a regulation changes terms and
anchors without changing which fields exist, values are validated and split between columns and the JSON details, and the RoPA service
keeps and returns everything the definition lists. A test of a fixed bug is written so that the old behaviour fails it: text typed into the
Recipients, Processors and Security measures boxes was stored and then read back as an empty list, and the Controller / DPO page saved
every row with the default role because the service did not list the field.
"""
import json

import pytest

from modules.sentinel import data_service as ds
from modules.sentinel.record_profiles import RecordError, get_profile, regulations
from modules.sentinel.record_profiles import regimes
from modules.sentinel.record_profiles.model import Cond, is_empty, says_transfer
from tests.test_platform_ownership import _insert, world  # noqa: F401
from tests.test_sentinel_write_scope import http  # noqa: F401

FORM = dict(
    processing_name="Payroll", department="Finance", owner="Head of HR", purpose="Pay staff", legal_basis="Contract",
    data_categories=["Name", "Salary"], special_categories=[], data_subjects="Employees", recipients="Payroll bureau; Tax office",
    retention_period="7 years", systems="HR system", processors="Payroll bureau (hosting)", security_measures="MFA, encryption at rest",
    intl_transfers="No", status="active", regulation="GDPR", risk_level="medium")


def _complete(record):
    return {k: v for k, v in record.items() if not is_empty(v)}


# ── The definition is consistent with itself ───────────────────────────────

def test_every_anchor_and_list_a_field_names_exists():
    profile = get_profile("ropa", "GDPR")
    lists = regimes.all_list_options()
    for f in profile.fields():
        if f.anchor:
            assert f.anchor in regimes._GDPR_ANCHORS, f"{f.key} names the anchor {f.anchor}, which GDPR does not define"
        if f.list_name:
            assert f.list_name in lists, f"{f.key} names the list {f.list_name}, which no regime defines"
        if f.when is not None:
            assert profile.get(f.when.field) is not None, f"{f.key} depends on {f.when.field}, which is not a field"
            assert f.when.op in ("nonempty", "empty", "contains", "in", "not_in", "transfers")
    keys = [f.key for f in profile.fields()]
    assert len(keys) == len(set(keys)), "a field key is defined twice"


def test_every_regulation_the_platform_knows_resolves_to_a_profile_with_the_same_fields():
    base = [f.key for f in get_profile("ropa", "GDPR").fields()]
    assert {item["key"] for item in regulations()} == set(regimes.JURISDICTION_RULES) - {"Canada Bill C-11"}
    assert get_profile("ropa", "Canada Bill C-11").regime["status"] == "proposal_not_enacted"
    for item in regulations():
        profile = get_profile("ropa", item["key"])
        assert [f.key for f in profile.fields()] == base, item["key"]
        assert item["status"] in ("researched_unapproved", "unverified")
        json.dumps(profile.to_json())          # the browser can be given it


def test_a_regulation_changes_the_words_and_the_citations_not_the_fields():
    gdpr, popia, kenya = (get_profile("ropa", r) for r in ("GDPR", "South Africa POPIA", "Kenya DPA"))
    assert gdpr.label(gdpr.get("acts_for")) == "Controller this activity is carried out for"
    assert popia.label(popia.get("acts_for")) == "Responsible party this activity is carried out for"
    assert popia.label(popia.get("special_categories")) == "Special personal information"
    assert gdpr.label(gdpr.get("special_categories")) == "Special category data"
    assert kenya.label(kenya.get("special_categories")) == "Sensitive personal data"
    assert gdpr.label(gdpr.get("intl_transfers")) == "Transfers outside the EEA"
    assert popia.label(popia.get("intl_transfers")) == "Transfers outside South Africa"
    assert gdpr.anchor(gdpr.get("purpose")) == "Art 30(1)(b)" and popia.anchor(popia.get("purpose")) == "s 13"
    assert gdpr.regime["status"] == popia.regime["status"] == "researched_unapproved"
    assert kenya.anchor(kenya.get("purpose")) == "" and kenya.regime["status"] == "unverified"
    assert "No statutory record of processing provision has been verified" in kenya.regime["record_basis"]
    assert [v for v, _ in popia.options(popia.get("transfer_safeguard"))] != [v for v, _ in gdpr.options(gdpr.get("transfer_safeguard"))]
    assert "Adequacy Decision" in [v for v, _ in gdpr.options(gdpr.get("transfer_safeguard"))]


def test_an_unknown_regulation_is_an_unverified_regime_under_its_own_name_and_the_default_is_gdpr():
    assert regimes.resolve("")["key"] == regimes.resolve(None)["key"] == "GDPR"
    unknown = regimes.resolve("Atlantis Privacy Law")
    assert unknown["key"] == "Atlantis Privacy Law" and unknown["status"] == "unverified" and unknown["anchors"] == {}


def test_no_text_of_the_definition_or_the_regimes_uses_a_dash_as_punctuation():
    dash = chr(0x2014)
    profile = get_profile("ropa", "GDPR")
    texts = [profile.label(f) + f.help for f in profile.fields()] + [profile.regime["record_basis"], regimes.SPECIALIST_NOTE]
    assert not [t for t in texts if dash in t]


# ── Conditions and completeness ─────────────────────────────────────────────

def test_a_conditions_words_mean_what_the_browser_reads_them_to_mean():
    assert Cond("a", "nonempty").holds({"a": "x"}) and not Cond("a", "nonempty").holds({"a": "  "})
    assert Cond("a", "empty").holds({}) and Cond("a", "contains", "child").holds({"a": ["Children's data"]})
    assert Cond("a", "in", ("processor",)).holds({"a": "Processor"}) and not Cond("a", "in", ("processor",)).holds({})
    assert Cond("a", "not_in", ("processor",)).holds({}) and not Cond("a", "not_in", ("processor",)).holds({"a": "processor"})
    for no in ("", "No", "none", "N/A", "No transfers outside the EEA", None):
        assert not says_transfer(no), no
    for yes in ("Yes", "USA", "Yes: South Africa", "South Africa (Cape Town)"):
        assert says_transfer(yes), yes


def test_a_controller_entry_is_complete_when_the_article_30_elements_are_entered():
    profile = get_profile("ropa", "GDPR")
    assert profile.gaps(_complete(FORM)) == []
    made, needed = profile.completeness(_complete(FORM))
    assert made == needed > 8
    for key in ("purpose", "recipients", "retention_period", "security_measures", "owner", "legal_basis", "data_subjects", "data_categories"):
        broken = _complete(FORM)
        broken.pop(key)
        assert [g.key for g in profile.gaps(broken)] == [key], key


def test_a_blank_answer_about_transfers_is_a_gap_and_is_not_read_as_no():
    profile = get_profile("ropa", "GDPR")
    record = _complete(FORM)
    record.pop("intl_transfers")
    assert [g.key for g in profile.gaps(record)] == ["intl_transfers"]


def test_what_a_condition_adds_is_required_only_when_it_holds():
    profile = get_profile("ropa", "GDPR")
    abroad = _complete(FORM)
    abroad["intl_transfers"] = "Yes: United States"
    assert {g.key for g in profile.gaps(abroad)} == {"transfer_dest", "transfer_safeguard"}
    abroad.update(transfer_dest="United States", transfer_safeguard="Derogation (Art 49)")
    assert [g.key for g in profile.gaps(abroad)] == ["transfer_safeguards_ref"]
    special = _complete(FORM)
    special["special_categories"] = ["Health / medical data", "Criminal convictions and offences", "Children's personal data"]
    assert {g.key for g in profile.gaps(special)} == {"special_condition", "criminal_basis", "children_basis"}


def test_a_processor_entry_needs_the_controller_it_acts_for_and_not_the_controller_only_fields():
    profile = get_profile("ropa", "GDPR")
    processor = {"processing_name": "Hosting for Acme", "owner": "Platform lead", "controller_role": "processor", "intl_transfers": "No",
                 "security_measures": "ISO 27001 ISMS"}
    assert {g.key for g in profile.gaps(processor)} == {"acts_for", "processing_categories"}
    assert "purpose" not in {f.key for f in profile.needed(processor)}
    processor.update(acts_for="Acme GmbH", processing_categories="Hosting and backup")
    assert profile.gaps(processor) == []


def test_the_readiness_follows_the_regulation_of_the_entry_not_the_organisation_default():
    popia = get_profile("ropa", "South Africa POPIA")
    record = _complete(FORM)
    record["special_categories"] = ["Health / medical data"]
    gap = next(g for g in popia.gaps(record) if g.key == "special_condition")
    assert gap.label == "Condition for processing special personal information" and gap.anchor == "s 26 to 33"
    assert get_profile("ropa", "Kenya DPA").gaps(record)[0].anchor == ""


# ── Validation and storage ─────────────────────────────────────────────────

def test_values_are_checked_by_kind_and_what_is_not_a_field_is_ignored():
    profile = get_profile("ropa", "GDPR")
    columns, details, errors = profile.prepare({
        "processing_name": "  Payroll\x00 ", "owner": "HR", "necessity": "Needed", "controller_role": "processor", "last_reviewed": "2026-10-01",
        "regular_disclosure": "yes", "data_volume": "high", "special_categories": "Health; Race, Health", "ref_number": "X", "business_unit_id": 7,
        "details": {"smuggled": 1}})
    assert errors == {}
    assert columns == {"processing_name": "Payroll", "owner": "HR", "special_categories": ["Health", "Race"]}
    assert details == {"necessity": "Needed", "controller_role": "processor", "last_reviewed": "2026-10-01", "regular_disclosure": 1,
                       "data_volume": "high"}


@pytest.mark.parametrize("data, key", [
    ({"last_reviewed": "2026-13-45"}, "last_reviewed"), ({"data_volume": "huge"}, "data_volume"), ({"controller_role": "boss"}, "controller_role"),
    ({"necessity": "x" * 4001}, "necessity"), ({"processing_name": "x" * 501}, "processing_name"), ({"review_date": "tomorrow"}, "review_date"),
    ({"necessity": {"a": 1}}, "necessity"), ({"data_categories": ["x" * 201]}, "data_categories")])
def test_a_value_that_cannot_be_stored_is_refused_with_the_field_named(data, key):
    assert key in get_profile("ropa", "GDPR").prepare(data)[2]


def test_a_value_saved_under_one_regulation_is_not_refused_after_the_entry_moves_to_another():
    popia_only = next(v for v, _ in get_profile("ropa", "South Africa POPIA").options(get_profile("ropa", "GDPR").get("special_condition")))
    assert get_profile("ropa", "GDPR").prepare({"special_condition": popia_only})[2] == {}


def test_what_is_not_sent_is_kept_and_what_is_sent_empty_is_cleared():
    profile = get_profile("ropa", "GDPR")
    _, details, _ = profile.prepare({"necessity": "", "data_owner": "COO"}, {"necessity": "Needed", "technical_owner": "IT", "legacy_key": "kept"})
    assert details == {"data_owner": "COO", "technical_owner": "IT", "legacy_key": "kept"}


# ── The RoPA service ───────────────────────────────────────────────────────

def test_text_typed_in_the_form_reads_back(test_db):
    """The drawer saves recipients, processors and security measures as text. They were stored, and read back as an empty list."""
    row = ds.get_ropa(ds.create_ropa(dict(FORM)))
    assert row["recipients"] == "Payroll bureau; Tax office"
    assert row["processors"] == "Payroll bureau (hosting)"
    assert row["security_measures"] == "MFA, encryption at rest"
    assert row["data_categories"] == ["Name", "Salary"] and row["retention_period"] == "7 years"
    listed = next(r for r in ds.list_ropa() if r["id"] == row["id"])
    assert listed["recipients"] == "Payroll bureau; Tax office"


def test_a_value_stored_as_a_json_list_still_reads_as_the_list(test_db):
    new_id = _insert(test_db, "sentinel_ropa", ref_number="R-1", processing_name="Old", recipients='["A", "B"]', security_measures='["MFA"]',
                     processors="[]")
    row = ds.get_ropa(new_id)
    assert row["recipients"] == ["A", "B"] and row["security_measures"] == ["MFA"] and row["processors"] == []


def test_the_fields_that_have_no_column_are_stored_and_returned_with_the_rest(test_db):
    sent = dict(FORM, description="Monthly payroll", data_owner="Head of Finance", technical_owner="HRIS lead", necessity="Pay people",
                further_processing="None", data_source="direct", regular_disclosure=True, retention_criteria="End of the tax year",
                profiling="None", last_reviewed="2026-09-30", dpia_status="not_required", controller_role="controller")
    row = ds.get_ropa(ds.create_ropa(sent))
    for key in ("description", "data_owner", "technical_owner", "necessity", "further_processing", "data_source", "retention_criteria",
                "profiling", "last_reviewed", "dpia_status", "controller_role"):
        assert row[key] == sent[key], key
    assert row["regular_disclosure"] == 1
    assert "details" not in row
    stored = json.loads(test_db.execute("SELECT details FROM sentinel_ropa WHERE id=%s", (row["id"],)).fetchone()["details"])
    assert stored["data_owner"] == "Head of Finance" and "processing_name" not in stored


def test_an_update_changes_only_what_was_sent(test_db):
    new_id = ds.create_ropa(dict(FORM, data_owner="Head of Finance", necessity="Pay people"))
    ds.update_ropa(new_id, {"necessity": "Statutory duty", "retention_criteria": "End of the tax year"})
    row = ds.get_ropa(new_id)
    assert row["necessity"] == "Statutory duty" and row["retention_criteria"] == "End of the tax year"
    assert row["data_owner"] == "Head of Finance" and row["purpose"] == "Pay staff"
    ds.update_ropa(new_id, {"data_owner": "", "purpose": ""})
    cleared = ds.get_ropa(new_id)
    assert "data_owner" not in cleared or not cleared["data_owner"]
    assert cleared["purpose"] == "" and cleared["necessity"] == "Statutory duty"


def test_an_update_that_sends_nothing_the_definition_knows_changes_nothing(test_db):
    new_id = ds.create_ropa(dict(FORM, data_owner="Head of Finance"))
    ref = ds.get_ropa(new_id)["ref_number"]
    ds.update_ropa(new_id, {"ref_number": "HACKED", "details": '{"data_owner": "x"}', "id": 999, "created_at": "2001-01-01"})
    row = ds.get_ropa(new_id)
    assert row["ref_number"] == ref and row["data_owner"] == "Head of Finance" and row["id"] == new_id


def test_a_value_that_cannot_be_stored_raises_with_the_field_named_and_stores_nothing(test_db):
    with pytest.raises(RecordError) as caught:
        ds.create_ropa(dict(FORM, last_reviewed="yesterday", data_volume="huge"))
    assert set(caught.value.errors) == {"last_reviewed", "data_volume"}
    assert test_db.execute("SELECT COUNT(*) FROM sentinel_ropa").fetchone()[0] == 0


def test_the_entry_keeps_its_jurisdiction_and_is_read_under_it(test_db):
    new_id = ds.create_ropa(dict(FORM, regulation="South Africa POPIA", special_categories=["Health / medical data"]))
    row = ds.get_ropa(new_id)
    profile = get_profile("ropa", row["regulation"])
    assert row["regulation"] == "South Africa POPIA"
    assert [g.key for g in profile.gaps(row)] == ["special_condition"]


# ── The routes ─────────────────────────────────────────────────────────────

def test_the_profile_route_gives_a_person_with_module_access_the_definition_under_a_regulation(http):
    answer = http("get", "/sentinel/api/record-profile/ropa?regulation=South%20Africa%20POPIA", name="dpo_a")
    assert answer.status_code == 200
    body = answer.json()
    assert body["regulation"] == "South Africa POPIA" and body["regime"]["terms"]["controller"] == "responsible party"
    assert body["regime"]["status"] == "researched_unapproved"
    assert {item["key"] for item in body["regulations"]} == set(regimes.JURISDICTION_RULES) - {"Canada Bill C-11"}
    keys = [f["key"] for s in body["sections"] for f in s["fields"]]
    assert {"purpose", "owner", "data_owner", "recipients", "retention_period", "security_measures"} <= set(keys)
    assert all(f["label"] for s in body["sections"] for f in s["fields"])
    assert http("get", "/sentinel/api/record-profile/nonsense", name="dpo_a").status_code == 404
    assert http("get", "/sentinel/api/record-profile/ropa?regulation=" + "x" * 500, name="dpo_a").status_code == 200


def test_the_ropa_list_says_how_much_of_each_entry_is_entered(http):
    world = http.world
    full = _insert(world.db, "sentinel_ropa", ref_number="R-FULL", processing_name="Payroll", owner="HR", purpose="Pay staff", legal_basis="Contract",
                   data_categories='["Name"]', data_subjects="Employees", recipients="Bureau", retention_period="7 years",
                   security_measures="MFA", intl_transfers="No", business_unit_id=world.unit["A"], regulation="GDPR")
    thin = _insert(world.db, "sentinel_ropa", ref_number="R-THIN", processing_name="Visitors", business_unit_id=world.unit["A"], regulation="GDPR")
    rows = {r["id"]: r for r in http("get", "/sentinel/api/ropa", name="dpo_a").json()}
    assert rows[full]["readiness"]["made"] == rows[full]["readiness"]["needed"] > 8
    assert rows[thin]["readiness"]["made"] == 1 and rows[thin]["readiness"]["needed"] > 8


def test_the_ropa_routes_answer_422_with_the_field_named_for_a_value_that_cannot_be_stored(http):
    bad = http("post", "/sentinel/api/ropa", name="dpo_a", json=dict(FORM, last_reviewed="yesterday"))
    assert bad.status_code == 422 and "last_reviewed" in bad.json()["detail"]
    ok = http("post", "/sentinel/api/ropa", name="dpo_a", json=dict(FORM, data_owner="Head of Finance"))
    assert ok.status_code == 201 and ok.json()["data_owner"] == "Head of Finance" and ok.json()["recipients"] == "Payroll bureau; Tax office"
    rid = ok.json()["id"]
    assert http("put", f"/sentinel/api/ropa/{rid}", name="dpo_a", json={"review_date": "never"}).status_code == 422
    assert http("put", f"/sentinel/api/ropa/{rid}", name="dpo_a", json={"data_owner": "COO"}).json()["data_owner"] == "COO"


# ── The Controller / DPO register ───────────────────────────────────────────

def test_the_controller_page_saves_the_role_the_agreement_and_the_identity_block_it_sends(http):
    """The page sends `role` and `agreement_ref`; the service did not list them, so every row was saved as the default role."""
    sent = {"org_name": "Acme Holdings", "role": "processor", "agreement_ref": "DPA v3.2", "representative": "Acme EU Rep GmbH",
            "record_owner": "Privacy lead", "last_full_review": "2026-09-30", "is_primary": "0"}
    made = http("post", "/sentinel/api/controllers", name="super", json=sent)
    assert made.status_code == 201
    body = made.json()
    assert (body["role"], body["agreement_ref"], body["representative"], body["record_owner"], body["last_full_review"]) == (
        "processor", "DPA v3.2", "Acme EU Rep GmbH", "Privacy lead", "2026-09-30")
    assert http("post", "/sentinel/api/controllers", name="super", json={"org_name": "X", "role": "boss"}).status_code == 422
    primary = http("post", "/sentinel/api/controllers", name="super", json={"org_name": "Us", "is_primary": "1"}).json()
    assert primary["role"] == "controller"
    plain = http("post", "/sentinel/api/controllers", name="super", json={"org_name": "Them"}).json()
    assert plain["role"] == "joint_controller"
