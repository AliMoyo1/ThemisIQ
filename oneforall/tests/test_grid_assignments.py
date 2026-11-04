"""Respondent assignments (plan 24, CISO 03): who may see and do what, and how answers and proof are reviewed."""
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from modules.grid import assignments as ga
from modules.launcher.my_work_service import _grid_assignments


def _id(db, table, **fields):
    keys = list(fields)
    db.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))})",
               [fields[k] for k in keys])
    db.commit()
    return db.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]


def _person(db, org, name, role, unit):
    uid = _id(db, "users", username=name, email=name + "@example.invalid", full_name=name.replace("_", " ").title(),
              password_hash="x", org_id=org, business_unit_id=unit, is_active=1)
    db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s,%s)", (uid, role))
    db.commit()
    return {"id": uid, "org_id": org, "business_unit_id": unit, "roles": [role], "is_super_admin": False}


def _due(days=14):
    return (date.today() + timedelta(days=days)).isoformat()


def _expect(code, work):
    with pytest.raises(HTTPException) as refused:
        work()
    assert refused.value.status_code == code, refused.value.detail
    return refused.value.detail


@pytest.fixture
def world(test_db):
    db = test_db
    org = _id(db, "organizations", name="Assign Co", slug="assign_co", status="active")
    unit = _id(db, "business_units", name="Operations", is_active=1)
    other_unit = _id(db, "business_units", name="Retail", is_active=1)
    people = {
        "lead": _person(db, org, "lead_ann", "audit_lead", unit),
        "lead2": _person(db, org, "lead_ben", "audit_lead", unit),
        "owner": _person(db, org, "owner_cara", "control_owner", unit),
        "owner2": _person(db, org, "owner_dan", "employee", unit),
        "far": _person(db, org, "far_eve", "employee", other_unit),
        "outsider": _person(db, org, "outside_fay", "external_auditor", unit),
        "uploader": _person(db, org, "upload_gus", "compliance_manager", unit),
    }
    audit = _id(db, "grid_audits", name="ISO 27001 surveillance", business_unit_id=unit)
    other_audit = _id(db, "grid_audits", name="Retail audit", business_unit_id=other_unit)
    controls = [_id(db, "grid_controls", audit_id=audit, control_id=f"A.5.{n}", name=f"Control {n}",
                    description=f"What control {n} requires") for n in (1, 2, 3)]
    _id(db, "grid_evidence_items", control_id=controls[0], name="Access review record", required=1)
    foreign = _id(db, "grid_controls", audit_id=other_audit, control_id="R.1", name="Retail control")
    files = {
        "ours": _id(db, "evidence_items", title="Q3 access review", status="current", version=1, file_hash="h-ours",
                    org_id=org, business_unit_id=unit, uploaded_by=people["uploader"]["id"]),
        "second": _id(db, "evidence_items", title="Joiner and leaver log", status="current", version=1,
                      file_hash="h-second", org_id=org, business_unit_id=unit, uploaded_by=people["uploader"]["id"]),
        "hidden": _id(db, "evidence_items", title="Retail till audit", status="current", version=1, file_hash="h-far",
                      org_id=org, business_unit_id=other_unit, uploaded_by=people["uploader"]["id"]),
    }
    return db, people, audit, controls, foreign, files


def _draft(db, people, audit, controls, **kw):
    new_id = ga.create(db, people["lead"], audit, kw.get("controls", controls), people["owner"]["id"],
                       kw.get("reviewer", people["lead"]["id"]), _due(), "Access controls for Q4",
                       "Answer each control and attach the review records.")
    db.commit()
    return new_id


def _version(db, assignment_id):
    return db.execute("SELECT version FROM grid_assignments WHERE id=%s", (assignment_id,)).fetchone()[0]


def test_only_an_audit_lead_sends_controls_of_one_audit_to_a_person_of_its_unit(world):
    db, people, audit, controls, foreign, files = world
    owner = people["owner"]
    _expect(403, lambda: ga.create(db, owner, audit, controls, owner["id"], None, _due(), "Mine"))
    _expect(404, lambda: ga.create(db, people["lead"], audit, [controls[0], foreign], owner["id"], None, _due(), "Mixed"))
    _expect(422, lambda: ga.create(db, people["lead"], audit, controls, people["far"]["id"], None, _due(), "Far"))
    _expect(422, lambda: ga.create(db, people["lead"], audit, controls, people["outsider"]["id"], None, _due(), "Ext"))
    _expect(422, lambda: ga.create(db, people["lead"], audit, controls, people["lead"]["id"], None, _due(), "Self"))
    _expect(422, lambda: ga.create(db, people["lead"], audit, controls, owner["id"], None, _due(-1), "Late"))
    first = _draft(db, people, audit, controls[:2])
    detail = _expect(409, lambda: ga.create(db, people["lead"], audit, [controls[1]], people["owner2"]["id"], None,
                                            _due(), "Again"))
    assert "A.5.2" in detail, "the control already out is named"
    assert ga.create(db, people["lead"], audit, [controls[2]], people["owner2"]["id"], None, _due(), "Third")
    choices = ga.audit_controls(db, people["lead"], audit)
    assert {p["name"] for p in choices["respondents"]} >= {"Owner Cara", "Owner Dan"}
    assert "Far Eve" not in {p["name"] for p in choices["respondents"]}, "only people of the audit's unit"
    assert "Outside Fay" not in {p["name"] for p in choices["respondents"]}
    assert {c["ref"]: c["busy"] for c in choices["controls"]}["A.5.1"] is True
    assert first


def test_the_person_sees_nothing_until_it_is_sent_and_then_only_their_own_controls(world):
    db, people, audit, controls, foreign, files = world
    assignment = _draft(db, people, audit, controls[:2])
    owner = people["owner"]
    _expect(404, lambda: ga.detail(db, owner, assignment))
    assert ga.listing(db, owner)["to_answer"] == []
    ga.launch(db, people["lead"], assignment, _version(db, assignment))
    db.commit()
    seen = ga.detail(db, owner, assignment)
    assert [i["ref"] for i in seen["items"]] == ["A.5.1", "A.5.2"], "never the audit's other controls"
    assert seen["role"] == "assignee" and "events" not in seen and "assignee" not in seen
    assert seen["items"][0]["required_evidence"] == ["Access review record"]
    assert db.execute("SELECT title FROM notifications WHERE user_id=%s", (owner["id"],)).fetchone()["title"] == \
        "You have audit questions to answer"
    for who in ("owner2", "far", "outsider"):
        _expect(404, lambda w=who: ga.detail(db, people[w], assignment))
    assert ga.listing(db, owner)["to_answer"][0]["id"] == assignment


def test_answers_keep_to_their_version_and_proof_comes_from_the_persons_own_vault(world):
    db, people, audit, controls, foreign, files = world
    assignment = _draft(db, people, audit, controls[:2])
    ga.launch(db, people["lead"], assignment, _version(db, assignment))
    db.commit()
    owner = people["owner"]
    items = ga.detail(db, owner, assignment)["items"]
    stale = _version(db, assignment)
    ga.save_item(db, owner, assignment, items[1]["id"], stale, "We review access monthly.")
    db.commit()
    _expect(409, lambda: ga.save_item(db, owner, assignment, items[1]["id"], stale, "Overwrite"))
    assert [f["title"] for f in ga.proof_choices(db, owner, assignment, "")] == ["Joiner and leaver log",
                                                                                 "Q3 access review"]
    assert ga.proof_choices(db, owner, assignment, "till") == [], "another unit's file is never offered"
    _expect(404, lambda: ga.add_proof(db, owner, assignment, items[0]["id"], _version(db, assignment), files["hidden"]))
    message = _expect(422, lambda: ga.submit(db, owner, assignment, _version(db, assignment)))
    assert "Answer A.5.1" in message and "choose proof for A.5.1" in message
    ga.add_proof(db, owner, assignment, items[0]["id"], _version(db, assignment), files["ours"])
    db.commit()
    link = db.execute("SELECT module, entity_type, entity_id, linked_by, review_status FROM evidence_links "
                      "WHERE evidence_id=%s", (files["ours"],)).fetchone()
    assert (link["module"], link["entity_type"], link["entity_id"], link["linked_by"]) == \
        ("grid", "control", controls[0], owner["id"]) and link["review_status"] is None
    ga.save_item(db, owner, assignment, items[0]["id"], _version(db, assignment), "Quarterly review, see the record.")
    assert ga.submit(db, owner, assignment, _version(db, assignment))["state"] == "submitted"
    db.commit()
    _expect(409, lambda: ga.save_item(db, owner, assignment, items[0]["id"], _version(db, assignment), "Late edit"))
    assert db.execute("SELECT title FROM notifications WHERE user_id=%s", (people["lead"]["id"],)).fetchone()["title"] \
        == "Audit answers are waiting for your review"


def test_removing_assignment_proof_preserves_a_preexisting_vault_link(world):
    db, people, audit, controls, _foreign, files = world
    assignment = _draft(db, people, audit, controls[:1])
    ga.launch(db, people["lead"], assignment, _version(db, assignment))
    item_id = ga.detail(db, people["owner"], assignment)["items"][0]["id"]
    existing_link = _id(db, "evidence_links", evidence_id=files["ours"], module="grid",
                        entity_type="control", entity_id=controls[0], linked_by=people["owner"]["id"])

    choice = ga.add_proof(db, people["owner"], assignment, item_id, _version(db, assignment), files["ours"])
    ga.remove_proof(db, people["owner"], assignment, item_id, choice["version"], choice["id"])
    db.commit()
    assert db.execute("SELECT deleted_at FROM evidence_links WHERE id=%s", (existing_link,)).fetchone()[0] is None

    fresh = ga.add_proof(db, people["owner"], assignment, item_id, _version(db, assignment), files["second"])
    new_link = db.execute("SELECT link_id FROM grid_assignment_proof WHERE id=%s", (fresh["id"],)).fetchone()[0]
    ga.remove_proof(db, people["owner"], assignment, item_id, fresh["version"], fresh["id"])
    db.commit()
    assert db.execute("SELECT deleted_at FROM evidence_links WHERE id=%s", (new_link,)).fetchone()[0] is not None


def _submitted(db, people, audit, controls, files):
    assignment = _draft(db, people, audit, controls[:2])
    ga.launch(db, people["lead"], assignment, _version(db, assignment))
    owner = people["owner"]
    items = ga.detail(db, owner, assignment)["items"]
    ga.add_proof(db, owner, assignment, items[0]["id"], _version(db, assignment), files["ours"])
    for item in items:
        ga.save_item(db, owner, assignment, item["id"], _version(db, assignment), "Answer for " + item["ref"])
    ga.submit(db, owner, assignment, _version(db, assignment))
    db.commit()
    return assignment, items


def test_the_named_reviewer_accepts_each_answer_with_its_proof_or_returns_it_with_a_reason(world):
    db, people, audit, controls, foreign, files = world
    assignment, items = _submitted(db, people, audit, controls, files)
    owner, lead = people["owner"], people["lead"]
    _expect(403, lambda: ga.review_item(db, people["lead2"], assignment, items[0]["id"], _version(db, assignment),
                                        "accept"))
    _expect(422, lambda: ga.review_item(db, lead, assignment, items[1]["id"], _version(db, assignment), "changes", ""))
    _expect(409, lambda: ga.review_item(db, lead, assignment, items[0]["id"], _version(db, assignment) - 1, "accept"))
    ga.review_item(db, lead, assignment, items[0]["id"], _version(db, assignment), "accept")
    db.commit()
    assert db.execute("SELECT review_status, reviewed_by FROM evidence_links WHERE evidence_id=%s",
                      (files["ours"],)).fetchone()[:] == ("accepted", lead["id"]), "the proof is accepted with the answer"
    state = ga.review_item(db, lead, assignment, items[1]["id"], _version(db, assignment), "changes",
                           "Say how often the review runs")
    db.commit()
    assert state["state"] == "changes_requested"
    seen = ga.detail(db, owner, assignment)
    assert [(i["ref"], i["review_state"]) for i in seen["items"]] == [("A.5.1", "accepted"),
                                                                       ("A.5.2", "changes_requested")]
    assert seen["items"][1]["review_note"] == "Say how often the review runs"
    _expect(409, lambda: ga.save_item(db, owner, assignment, items[0]["id"], _version(db, assignment), "Change it"))
    ga.save_item(db, owner, assignment, items[1]["id"], _version(db, assignment), "Monthly, by the service owner.")
    ga.submit(db, owner, assignment, _version(db, assignment))
    db.commit()
    assert [i["review_state"] for i in ga.detail(db, owner, assignment)["items"]] == ["accepted", "resubmitted"]
    assert ga.review_item(db, lead, assignment, items[1]["id"], _version(db, assignment), "accept")["state"] == "closed"
    db.commit()
    staff = ga.detail(db, lead, assignment)
    actions = [e["action"] for e in staff["events"]]
    assert actions[:2] == ["created", "launched"] and actions[-2:] == ["accepted", "closed"]
    assert "changes_requested" in actions and "returned" in actions, "every turn is kept in the history"
    assert db.execute("SELECT status FROM grid_controls WHERE id=%s", (controls[0],)).fetchone()[0] == "Not Started", \
        "an accepted answer does not decide the GRID verdict"


def test_proof_that_changed_after_it_was_chosen_cannot_be_accepted(world):
    db, people, audit, controls, foreign, files = world
    assignment, items = _submitted(db, people, audit, controls, files)
    db.execute("UPDATE evidence_items SET status='superseded' WHERE id=%s", (files["ours"],))
    db.commit()
    assert ga.detail(db, people["lead"], assignment)["items"][0]["proof"][0]["changed"] is True
    message = _expect(409, lambda: ga.review_item(db, people["lead"], assignment, items[0]["id"],
                                                  _version(db, assignment), "accept"))
    assert "changed after it was chosen" in message
    assert db.execute("SELECT review_status FROM evidence_links WHERE evidence_id=%s",
                      (files["ours"],)).fetchone()[0] is None


def test_handing_it_to_someone_else_or_cancelling_ends_the_old_persons_access_at_once(world):
    db, people, audit, controls, foreign, files = world
    assignment = _draft(db, people, audit, controls[:2])
    ga.launch(db, people["lead"], assignment, _version(db, assignment))
    db.commit()
    owner, owner2 = people["owner"], people["owner2"]
    _expect(422, lambda: ga.revise(db, people["lead"], assignment, _version(db, assignment), "",
                                   assignee_id=owner2["id"]))
    ga.revise(db, people["lead"], assignment, _version(db, assignment), "Cara moved to another team",
              assignee_id=owner2["id"])
    db.commit()
    _expect(404, lambda: ga.detail(db, owner, assignment))
    assert ga.detail(db, owner2, assignment)["can_answer"] is True
    ga.cancel(db, people["lead"], assignment, _version(db, assignment), "Audit scope changed")
    db.commit()
    _expect(404, lambda: ga.detail(db, owner2, assignment))
    assert ga.create(db, people["lead"], audit, controls[:2], owner["id"], None, _due(), "Second round"), \
        "a cancelled assignment frees its controls"


def test_a_proof_file_is_named_only_to_people_who_may_open_it(world):
    """The person answering sits above the audit's unit and chooses a file from a sibling unit the reviewer cannot
    open: the reviewer sees that a file was chosen, never its title, and cannot accept it."""
    db, people, audit, controls, foreign, files = world
    org = people["lead"]["org_id"]
    parent = _id(db, "business_units", name="Group", is_active=1)
    child = _id(db, "business_units", name="Plant", is_active=1, parent_id=parent)
    sibling = _id(db, "business_units", name="Depot", is_active=1, parent_id=parent)
    plant_audit = _id(db, "grid_audits", name="Plant audit", business_unit_id=child)
    control = _id(db, "grid_controls", audit_id=plant_audit, control_id="P.1", name="Plant control")
    head = _person(db, org, "head_hal", "control_owner", parent)
    plant_lead = _person(db, org, "plant_ivy", "audit_lead", child)
    depot_file = _id(db, "evidence_items", title="Depot fire drill", status="current", version=1, file_hash="h-depot",
                     org_id=org, business_unit_id=sibling, uploaded_by=people["uploader"]["id"])
    assignment = ga.create(db, plant_lead, plant_audit, [control], head["id"], None, _due(), "Plant questions")
    ga.launch(db, plant_lead, assignment, _version(db, assignment))
    item = ga.detail(db, head, assignment)["items"][0]["id"]
    ga.add_proof(db, head, assignment, item, _version(db, assignment), depot_file)
    ga.save_item(db, head, assignment, item, _version(db, assignment), "Drill records attached")
    ga.submit(db, head, assignment, _version(db, assignment))
    db.commit()
    assert ga.detail(db, head, assignment)["items"][0]["proof"][0]["title"] == "Depot fire drill"
    seen = ga.detail(db, plant_lead, assignment)["items"][0]["proof"][0]
    assert seen["title"] == "A file you cannot open"
    refused = _expect(409, lambda: ga.review_item(db, plant_lead, assignment, item, _version(db, assignment), "accept"))
    assert "Depot" not in refused and "cannot open" in refused


def test_my_work_shows_the_person_their_questions_and_the_reviewer_the_answers(world):
    db, people, audit, controls, foreign, files = world
    assignment = _draft(db, people, audit, controls[:2])
    assert _grid_assignments(db, people["owner"]) == []
    ga.launch(db, people["lead"], assignment, _version(db, assignment))
    db.commit()
    mine = _grid_assignments(db, people["owner"])
    assert [(i["action"], i["section"], i["link"]) for i in mine] == [
        ("answer_audit_questions", "due_soon", f"/grid/assignments/?open={assignment}")]
    assert _grid_assignments(db, people["lead"]) == []
    assignment2, _ = _submitted(db, people, audit, [controls[2]], files)
    reviewer = [i for i in _grid_assignments(db, people["lead"]) if i["entity_id"] == assignment2]
    assert reviewer[0]["action"] == "review_audit_answers"
    assert [i["section"] for i in _grid_assignments(db, people["owner"]) if i["entity_id"] == assignment2] == \
        ["waiting_on_others"]
