"""Policy adoption (plan 22, C5): the parent sees each subsidiary's reviewed outcome, never its reasons or controls."""
import pytest
from fastapi import HTTPException

from modules.evidence import group_adoption as adoption
from modules.evidence import group_documents as group
from tests.test_group_documents import _activate, _actor, _future, _id, group_world  # noqa: F401 (fixture)


@pytest.fixture
def released(group_world):
    db, parent, child, sibling, users, _ = group_world
    relation = _activate(db, parent, child, users)
    parent_privacy = _actor(db, parent, "rollup_privacy", "dpo")
    parent_publisher = _actor(db, parent, "rollup_publisher", "grc_officer")
    document = _id(db, "aria_documents", doc_id="ROLLUP-POLICY", framework="ISO 27001",
                   title="Group access policy", org_id=parent)
    for reviewer in (users["publisher"], users["legal"]):
        group.grant_view(db, users["ack"], relation, reviewer["id"], "document.view", _future(25), _future(7))
    version = _id(db, "aria_policy_versions", org_id=parent, document_id=document, version_major=1,
                  version_minor=0, version="1.0", state="approved", origin="authored")
    evidence = _id(db, "evidence_items", title="Group access policy", org_id=parent, category="policy",
                   status="current", version=1, file_hash="rollup-v1", aria_policy_version_id=version)
    group.reviewed_rights(db, parent_privacy, evidence, "owned", True, False, "Owned group policy")
    publication = group.publish(db, parent_publisher, relation, evidence, "internal", "Group governance", _future(20))
    db.commit()
    return db, parent, child, users, parent_publisher, publication


def _state(db, publisher):
    return [(i["organization"], i["state"]) for i in adoption.rollup(db, publisher)["items"]]


def test_the_parent_sees_each_reviewed_outcome_and_nothing_of_the_reasoning(released):
    db, parent, child, users, publisher, publication = released
    assert _state(db, publisher) == [("Child Co", "no_decision")]
    proposal = adoption.propose(db, users["publisher"], publication, "exception_requested",
                                "Local regulator requires a stricter rule", "2099-01-01")
    db.commit()
    assert _state(db, publisher) == [("Child Co", "in_review")], "a proposal is not shown as the outcome"
    adoption.review(db, users["legal"], proposal, "approve", "Exception independently checked")
    db.commit()
    item = adoption.rollup(db, publisher)["items"][0]
    assert item["state"] == "exception_requested" and item["review_due_at"] == "2099-01-01" and item["decided_at"]
    flat = repr(item)
    assert "stricter rule" not in flat and "independently checked" not in flat
    assert set(item) == {"publication_id", "title", "version", "organization", "published_at", "state",
                         "decided_at", "effective_at", "review_due_at"}


def test_only_the_publishing_organization_sees_the_rollup(released):
    db, parent, child, users, publisher, publication = released
    assert adoption.rollup(db, users["publisher"])["items"] == [], "the child published nothing itself"
    with pytest.raises(HTTPException) as employee:
        adoption.rollup(db, _actor(db, parent, "rollup_employee", "employee"))
    assert employee.value.status_code == 403
    group.revoke_publication(db, publisher, publication)
    db.commit()
    assert adoption.rollup(db, publisher)["items"] == [], "a revoked version leaves the rollup"


def test_the_child_links_its_own_controls_to_an_adopted_policy(released):
    db, parent, child, users, publisher, publication = released
    framework = _id(db, "frameworks", name="Rollup framework")
    control = _id(db, "controls", framework_id=framework, ref="AC-1", name="Access reviews")
    proposal = adoption.propose(db, users["publisher"], publication, "adopted", "Adopted as written",
                                "2099-01-01", "2026-11-03")
    db.commit()
    with pytest.raises(HTTPException) as undecided:
        adoption.link_control(db, users["publisher"], proposal, "aria", "control", control)
    assert undecided.value.status_code == 404, "only an approved adoption is carried out by controls"
    adoption.review(db, users["legal"], proposal, "approve", "Independently checked")
    db.commit()
    for module, kind, ident, code in (("aria", "document", control, 422), ("aria", "control", 0, 422),
                                      ("aria", "control", control + 999, 404)):
        with pytest.raises(HTTPException) as bad:
            adoption.link_control(db, users["publisher"], proposal, module, kind, ident)
        assert bad.value.status_code == code
    with pytest.raises(HTTPException) as reviewer_only:
        adoption.link_control(db, users["privacy"], proposal, "aria", "control", control)
    assert reviewer_only.value.status_code == 403
    link = adoption.link_control(db, users["publisher"], proposal, "aria", "control", control)
    db.commit()
    with pytest.raises(HTTPException) as twice:
        adoption.link_control(db, users["publisher"], proposal, "aria", "control", control)
    assert twice.value.status_code == 409
    listed = adoption.list_policies(db, users["publisher"])["items"][0]["adoption"]
    assert [c["title"] for c in listed["controls"]] == ["Access reviews"] and listed["can_link"] is True
    assert "Access reviews" not in repr(adoption.rollup(db, publisher)), "controls never reach the parent"
    with pytest.raises(HTTPException) as foreign:
        adoption.unlink_control(db, publisher, link)
    assert foreign.value.status_code == 404
    adoption.unlink_control(db, users["publisher"], link)
    db.commit()
    assert adoption.list_policies(db, users["publisher"])["items"][0]["adoption"]["controls"] == []
    assert adoption.link_control(db, users["publisher"], proposal, "aria", "control", control) == link
