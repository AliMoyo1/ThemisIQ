"""Synthetic parent, child and sibling disclosure boundaries."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from modules.evidence import group_documents as group
from modules.evidence import group_requests as requests
from modules.evidence import group_adoption as adoption
from modules.launcher.my_work_service import _collect, _group_proof_requests


def _id(db, table, **fields):
    keys = list(fields)
    db.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))})",
               [fields[k] for k in keys])
    db.commit()
    return db.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]


def _actor(db, org, key, role, unit=None):
    uid = _id(db, "users", username=key, email=key + "@example.invalid", full_name=key,
              password_hash="test", org_id=org, is_active=1)
    db.execute("INSERT INTO user_roles (user_id,role_key) VALUES (%s,%s)", (uid, role))
    db.commit()
    return {"id": uid, "org_id": org, "business_unit_id": unit, "roles": [role]}


def _future(days=30):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _terms(*classes):
    return {"data_classes": ["document_metadata", *classes], "classifications": ["internal"],
            "audiences": ["grc_officer", "compliance_manager"],
            "fields": ["title", "category", "version", "source_name", "classification", "expires_at"],
            "jurisdictions": ["Zimbabwe"], "legal_basis": "Synthetic pilot agreement",
            "agreement_ref": "TEST-ONLY-001"}


@pytest.fixture
def group_world(test_db):
    db = test_db
    parent = _id(db, "organizations", name="Parent Co", slug="group_parent", status="active")
    child = _id(db, "organizations", name="Child Co", slug="group_child", status="active")
    sibling = _id(db, "organizations", name="Unrelated Co", slug="group_unrelated", status="active")
    users = {
        "platform": _actor(db, parent, "platform_group", "super_admin"),
        "ack": _actor(db, child, "child_ack", "org_admin"),
        "privacy": _actor(db, child, "child_privacy", "dpo"),
        "legal": _actor(db, child, "child_legal", "compliance_manager"),
        "publisher": _actor(db, child, "child_publisher", "grc_officer"),
        "parent_admin": _actor(db, parent, "parent_admin", "org_admin"),
        "viewer": _actor(db, parent, "parent_viewer", "grc_officer"),
        "ungranted": _actor(db, parent, "parent_other", "grc_officer"),
        "sibling": _actor(db, sibling, "sibling_viewer", "grc_officer"),
    }
    evidence = _id(db, "evidence_items", title="Reviewed continuity report", category="report",
                   org_id=child, status="current", version=1, file_hash="hash-v1")
    return db, parent, child, sibling, users, evidence


def _activate(db, parent, child, users):
    relation = group.propose_relationship(db, users["platform"], parent, child,
        "Group governance", _terms("document_bytes"), _future(90))
    db.commit()
    for who, kind in (("ack", "ack"), ("privacy", "privacy"), ("legal", "legal")):
        group.record_relationship_decision(db, users[who], relation, kind)
        db.commit()
    return relation


def test_grant_review_queue_pages_old_grants_and_stays_in_viewer_tenant(group_world):
    db, parent, child, _, users, _ = group_world
    relation = _activate(db, parent, child, users)
    for _ in range(52):
        db.execute("INSERT INTO group_view_grants "
                   "(relationship_id,source_org_id,viewer_org_id,user_id,capability,expires_at,review_due_at,granted_by) "
                   "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                   (relation, child, parent, users["viewer"]["id"], "document.view",
                    _future(30), _future(7), users["parent_admin"]["id"]))
    db.execute("INSERT INTO group_access_events "
               "(relationship_id,source_org_id,viewer_org_id,actor_id,action) "
               "VALUES (%s,%s,%s,%s,%s)",
               (relation, child, parent, users["viewer"]["id"], "open"))
    db.commit()
    reviewer = _actor(db, parent, "queue_reviewer", "org_admin")
    first = group.grant_review_queue(db, reviewer)
    second = group.grant_review_queue(db, reviewer, page=2)
    assert len(first["items"]) == 50 and first["has_more"]
    assert len(second["items"]) == 2 and not second["has_more"]
    assert set(row["id"] for row in first["items"]).isdisjoint(
        row["id"] for row in second["items"])
    assert all(row["source_name"] == "Child Co" and row["recipient_name"] == "parent_viewer"
               and row["can_review"] for row in second["items"])
    assert second["items"][0]["last_matching_access_at"]
    assert group.grant_review_queue(db, {**users["sibling"], "roles": ["org_admin"]})["items"] == []
    with pytest.raises(HTTPException) as denied:
        group.grant_review_queue(db, {**users["viewer"], "roles": ["employee"]})
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as invalid:
        group.grant_review_queue(db, reviewer, page=0)
    assert invalid.value.status_code == 422


def test_group_proof_requests_flow_to_my_work_without_sibling_titles(group_world):
    db, parent, child, _, users, _ = group_world
    relation = _activate(db, parent, child, users)
    request_id = requests.create_request(db, users["viewer"], relation,
        "PARENT-REQ-42", "Proof for group review", _future(3))
    db.commit()
    source_items = _group_proof_requests(db, users["privacy"])
    assert [(item["entity_id"], item["action"]) for item in source_items] == [
        (request_id, "review_group_request")]
    assert _group_proof_requests(db, users["parent_admin"])[0]["section"] == "waiting_on_others"
    assert _group_proof_requests(db, users["sibling"]) == []
    feed, states = _collect(db, users["privacy"], None, only={"group_proof_requests"})
    assert feed[0]["entity_id"] == request_id
    assert states == [{"source": "group_proof_requests", "state": "available", "count": 1,
                       "truncated": False}]
    requests.review_request(db, users["privacy"], request_id, "no_proof", "No suitable proof exists")
    db.commit()
    assert _group_proof_requests(db, users["privacy"]) == []
    assert _group_proof_requests(db, users["parent_admin"]) == []


def test_grant_recertification_is_independent_audited_and_cannot_widen(group_world):
    db, parent, child, _, users, evidence = group_world
    relation = _activate(db, parent, child, users)
    second_admin = _actor(db, parent, "parent_second_admin", "org_admin")
    group.grant_view(db, users["parent_admin"], relation, users["viewer"]["id"],
                     "document.view", _future(), _future(7))
    download = group.grant_view(db, users["parent_admin"], relation, users["viewer"]["id"],
                                "document.download", _future(), _future(7))
    group.reviewed_rights(db, users["privacy"], evidence, "owned", True, True,
                          "Synthetic group circulation permission")
    publication = group.publish(db, users["publisher"], relation, evidence,
                                "internal", "Group governance", _future())
    db.commit()
    assert group.released_item(db, users["viewer"], publication, download=True)[1]["id"] == evidence

    with pytest.raises(HTTPException) as same_reviewer:
        group.review_grant(db, users["parent_admin"], download, "keep", "Still needed for audit",
                           _future(), _future(7))
    assert same_reviewer.value.status_code == 403
    with pytest.raises(HTTPException) as wrong_org:
        group.review_grant(db, users["sibling"], download, "revoke", "No longer needed")
    assert wrong_org.value.status_code == 404
    narrowed = group.review_grant(db, second_admin, download, "narrow",
                                  "Only catalogue view is still required", _future(), _future(7))
    db.commit()
    assert narrowed["replacement_id"] != download
    assert db.execute("SELECT capability FROM group_view_grants WHERE id=%s",
                      (narrowed["replacement_id"],)).fetchone()[0] == "document.view"
    with pytest.raises(HTTPException) as denied:
        group.released_item(db, users["viewer"], publication, download=True)
    assert denied.value.status_code == 404
    assert group.catalogue(db, users["viewer"])
    with pytest.raises(HTTPException) as broaden:
        group.review_grant(db, users["parent_admin"], narrowed["replacement_id"], "narrow",
                           "Cannot widen view back to download", _future(), _future(7))
    assert broaden.value.status_code == 422
    event = db.execute("SELECT action,detail FROM group_access_events WHERE action='review_grant' "
                       "ORDER BY id DESC LIMIT 1").fetchone()
    assert event["action"] == "review_grant"
    assert '"outcome": "narrow"' in event["detail"]


def test_version_bound_publication_requires_all_gates_and_revokes_immediately(group_world):
    db, parent, child, _, users, evidence = group_world
    relation = group.propose_relationship(db, users["platform"], parent, child,
        "Group governance", _terms("document_bytes"), _future(90))
    db.commit()
    with pytest.raises(HTTPException):
        group.publish(db, users["publisher"], relation, evidence, "internal", "Group governance", _future())
    for who, kind in (("ack", "ack"), ("privacy", "privacy"), ("legal", "legal")):
        group.record_relationship_decision(db, users[who], relation, kind)
        db.commit()
    group.grant_view(db, users["parent_admin"], relation, users["viewer"]["id"],
                     "document.view", _future(), _future(7))
    db.commit()
    assert group.catalogue(db, users["viewer"]) == []


    rights = group.reviewed_rights(db, users["privacy"], evidence, "owned", True, True,
                                    "Original policy, approved for group circulation")
    db.commit()
    pub = group.publish(db, users["publisher"], relation, evidence, "internal", "Group governance", _future())
    db.commit()
    assert [r["id"] for r in group.catalogue(db, users["viewer"])] == [pub]
    outside_audience = {**users["viewer"], "roles": ["audit_lead"]}
    assert group.catalogue(db, outside_audience) == []
    with pytest.raises(HTTPException) as audience_denied:
        group.released_item(db, outside_audience, pub)
    assert audience_denied.value.status_code == 404
    assert group.catalogue(db, users["ungranted"]) == []
    assert group.catalogue(db, users["sibling"]) == []
    with pytest.raises(HTTPException) as hidden:
        group.released_item(db, users["ungranted"], pub)
    assert hidden.value.status_code == 404
    with pytest.raises(HTTPException) as download:
        group.released_item(db, users["viewer"], pub, download=True)
    assert download.value.status_code == 404
    group.grant_view(db, users["parent_admin"], relation, users["viewer"]["id"],
                     "document.download", _future(), _future(7))
    db.commit()
    assert group.released_item(db, users["viewer"], pub, download=True)[1]["id"] == evidence
    db.execute("UPDATE evidence_items SET status='superseded' WHERE id=%s", (evidence,))
    db.commit()
    assert group.catalogue(db, users["viewer"]) == []
    db.execute("UPDATE evidence_items SET status='current' WHERE id=%s", (evidence,))
    db.execute("UPDATE group_document_rights SET rights_state='unknown',permit_group_view=0 WHERE id=%s", (rights,))
    db.commit()
    assert group.catalogue(db, users["viewer"]) == []


def test_company_browse_cursor_skips_invalidated_releases_without_leaking_sources(group_world):
    db, parent, child, sibling, users, evidence = group_world
    relation = _activate(db, parent, child, users)
    group.grant_view(db, users["parent_admin"], relation, users["viewer"]["id"],
                     "document.view", _future(), _future(7))
    db.commit()
    publications = []
    evidence_ids = [evidence]
    for index in (2, 3):
        evidence_ids.append(_id(db, "evidence_items", title=f"Report {index}", category="report",
                                org_id=child, status="current", version=1, file_hash=f"hash-{index}"))
    for item in evidence_ids:
        group.reviewed_rights(db, users["privacy"], item, "owned", True, False,
                              "Approved for named group access")
        db.commit()
        publications.append(group.publish(db, users["publisher"], relation, item,
                                          "internal", "Group governance", _future()))
        db.commit()
    db.execute("UPDATE evidence_items SET status='superseded' WHERE id=%s", (evidence_ids[1],))
    db.commit()
    assert group.source_companies(db, users["viewer"]) == [{"id": child, "name": "Child Co"}]
    assert group.source_companies(db, users["ungranted"]) == []
    first = group.catalogue_cursor(db, users["viewer"], source_org_id=child, page_size=1)
    assert [item["id"] for item in first["items"]] == [publications[2]]
    assert first["next_cursor"] == publications[2]
    second = group.catalogue_cursor(db, users["viewer"], source_org_id=child,
                                    before_id=first["next_cursor"], page_size=1)
    assert [item["id"] for item in second["items"]] == [publications[0]]
    assert second["next_cursor"] is None
    for actor, source in ((users["ungranted"], child), (users["viewer"], sibling)):
        with pytest.raises(HTTPException) as hidden:
            group.catalogue_cursor(db, actor, source_org_id=source)
        assert hidden.value.status_code == 404


def test_relationship_is_not_derived_from_name_or_role(group_world):
    db, parent, child, sibling, users, evidence = group_world
    relation = _activate(db, parent, child, users)
    with pytest.raises(HTTPException):
        group.grant_view(db, users["sibling"], relation, users["viewer"]["id"],
                         "document.view", _future(), _future(7))
    with pytest.raises(HTTPException):
        group.propose_relationship(db, users["platform"], sibling, child,
                                   "Second parent", _terms(), _future())
    with pytest.raises(HTTPException):
        group.propose_relationship(db, users["platform"], child, parent,
                                   "Cycle", _terms(), _future())
    with pytest.raises(HTTPException):
        group.reviewed_rights(db, users["viewer"], evidence, "owned", True, True, "Not owner")


def test_management_workspace_never_lists_sibling_people_or_files(group_world):
    db, parent, child, sibling, users, evidence = group_world
    relation = _activate(db, parent, child, users)
    child_space = group.management_workspace(db, users["publisher"])
    assert [row["id"] for row in child_space["relationships"]] == [relation]
    assert [row["id"] for row in child_space["evidence"]] == [evidence]
    assert all(row["id"] != users["viewer"]["id"] for row in child_space["recipients"])
    parent_space = group.management_workspace(db, users["parent_admin"])
    assert [row["id"] for row in parent_space["relationships"]] == [relation]
    assert all(row["id"] != evidence for row in parent_space["evidence"])
    assert all(row["id"] != users["publisher"]["id"] for row in parent_space["recipients"])
    unrelated = group.management_workspace(db, {**users["sibling"], "roles": ["org_admin"]})
    assert unrelated["relationships"] == []
    assert unrelated["evidence"] == []
    assert unrelated["organizations"] == []


def test_relationship_acknowledgement_and_reviews_need_distinct_people(group_world):
    db, parent, child, _, users, _ = group_world
    relation = group.propose_relationship(db, users["platform"], parent, child,
        "Group governance", _terms(), _future())
    group.record_relationship_decision(db, users["ack"], relation, "ack")
    with pytest.raises(HTTPException) as duplicate:
        group.record_relationship_decision(db, {**users["ack"], "roles": ["dpo"]}, relation, "privacy")
    assert duplicate.value.status_code == 409


def test_source_document_search_is_exactly_scoped_and_literal(group_world):
    db, parent, child, _, users, evidence = group_world
    _id(db, "evidence_items", title="Parent % secret", category="report", org_id=parent,
        status="current", version=1, file_hash="parent-hash")
    matches = group.source_candidates(db, users["publisher"], "Reviewed")
    assert [row["id"] for row in matches["items"]] == [evidence]
    assert group.source_candidates(db, users["publisher"], "%")["items"] == []
    assert group.source_candidates(db, users["publisher"], "secret")["items"] == []
    with pytest.raises(HTTPException) as denied:
        group.source_candidates(db, users["ack"], "Reviewed")
    assert denied.value.status_code == 403


def test_requirement_request_never_names_source_record_to_parent(group_world):
    db, parent, child, sibling, users, evidence = group_world
    relation = _activate(db, parent, child, users)
    request_id = requests.create_request(db, users["viewer"], relation,
        "Parent control 7.2", "Need proof of current oversight", _future(14))
    db.commit()
    parent_list = requests.list_requests(db, users["viewer"])["items"]
    assert [row["id"] for row in parent_list] == [request_id]
    assert "source_mapping" not in parent_list[0]
    assert requests.list_requests(db, users["sibling"])["items"] == []
    with pytest.raises(HTTPException):
        requests.review_request(db, users["viewer"], request_id, "approved", "Looks good")
    with pytest.raises(HTTPException) as unmapped:
        requests.review_request(db, users["legal"], request_id, "approved", "Reviewed source")
    assert unmapped.value.status_code == 409
    source_doc = _id(db, "aria_documents", doc_id="SOURCE-DOC-1", framework="ISO 27001",
                     title="Child internal claim", org_id=child)
    requests.map_request(db, users["legal"], request_id, "aria", "document", source_doc)
    db.commit()
    child_list = requests.list_requests(db, users["legal"])["items"]
    assert child_list[0]["source_mapping"]["entity_id"] == source_doc
    assert "source_mapping" not in requests.list_requests(db, users["viewer"])["items"][0]
    requests.review_request(db, users["legal"], request_id, "approved", "Reviewed for group release")
    db.commit()
    with pytest.raises(HTTPException):
        requests.fulfill_request(db, users["legal"], request_id, 1)
    group.reviewed_rights(db, users["privacy"], evidence, "owned", True, False, "Owned group report")
    publication = group.publish(db, users["publisher"], relation, evidence,
                                "internal", "Group governance", _future(20))
    with pytest.raises(HTTPException) as ungranted:
        requests.fulfill_request(db, users["publisher"], request_id, publication)
    assert ungranted.value.status_code == 409
    group.grant_view(db, users["parent_admin"], relation, users["viewer"]["id"],
                     "document.view", _future(25), _future(7))
    db.commit()
    requests.fulfill_request(db, users["publisher"], request_id, publication)
    db.commit()
    fulfilled = requests.list_requests(db, users["viewer"])["items"][0]
    assert fulfilled["status"] == "fulfilled"
    assert fulfilled["released_publication_id"] == publication
    assert "source_mapping" not in fulfilled
    events = db.execute("SELECT action,detail FROM group_access_events "
                        "WHERE detail=%s ORDER BY id", (str(request_id),)).fetchall()
    assert [event["action"] for event in events] == [
        "request_created", "request_mapped", "request_approved", "request_fulfilled"]
    assert all("SOURCE-DOC-1" not in event["detail"] for event in events)


def test_parent_verdict_is_independent_version_bound_and_return_allows_new_release(group_world):
    db, parent, child, _, users, evidence = group_world
    relation = _activate(db, parent, child, users)
    request_id = requests.create_request(db, users["viewer"], relation,
        "Parent requirement 4", "Need an independently reviewed report", _future(14))
    source_doc = _id(db, "aria_documents", doc_id="SOURCE-ONLY-2", framework="ISO 27001",
                     title="Source mapping", org_id=child)
    requests.map_request(db, users["legal"], request_id, "aria", "document", source_doc)
    requests.review_request(db, users["legal"], request_id, "approved", "Source record checked")
    group.reviewed_rights(db, users["privacy"], evidence, "owned", True, False, "Owned report")
    first = group.publish(db, users["publisher"], relation, evidence,
                          "internal", "Group governance", _future(20))
    group.grant_view(db, users["parent_admin"], relation, users["viewer"]["id"],
                     "document.view", _future(25), _future(7))
    db.commit()
    requests.fulfill_request(db, users["publisher"], request_id, first)
    db.commit()

    with pytest.raises(HTTPException) as self_review:
        requests.review_release(db, users["viewer"], request_id, "accepted", "Looks sufficient")
    assert self_review.value.status_code == 409
    with pytest.raises(HTTPException) as hidden:
        requests.review_release(db, users["sibling"], request_id, "returned", "Wrong period")
    assert hidden.value.status_code == 404
    requests.review_release(db, users["ungranted"], request_id, "returned", "The period is missing")
    db.commit()
    assert requests.list_requests(db, users["publisher"])["items"][0]["verdict"] == "returned"
    assert requests.list_requests(db, users["publisher"])["items"][0]["verdict_reason"] == "The period is missing"
    assert requests.list_requests(db, users["publisher"])["items"][0]["can_refulfill"]
    with pytest.raises(HTTPException) as same_version:
        requests.fulfill_request(db, users["publisher"], request_id, first)
    assert same_version.value.status_code == 409

    replacement = _id(db, "evidence_items", title="Corrected period report", category="report",
                      org_id=child, status="current", version=2, file_hash="different-hash")
    group.reviewed_rights(db, users["privacy"], replacement, "owned", True, False,
                          "Corrected owned report")
    second = group.publish(db, users["publisher"], relation, replacement,
                           "internal", "Group governance", _future(20))
    db.commit()
    assert {row["id"] for row in requests.release_candidates(db, users["publisher"], request_id)} == {second}
    requests.fulfill_request(db, users["publisher"], request_id, second)
    db.commit()
    with pytest.raises(HTTPException) as no_grant:
        requests.review_release(db, users["ungranted"], request_id, "accepted", "Now sufficient")
    assert no_grant.value.status_code == 404
    group.grant_view(db, users["parent_admin"], relation, users["ungranted"]["id"],
                     "document.view", _future(25), _future(7))
    db.commit()
    requests.review_release(db, users["ungranted"], request_id, "accepted", "Now sufficient")
    db.commit()
    parent_row = requests.list_requests(db, users["viewer"])["items"][0]
    assert parent_row["verdict"] == "accepted" and parent_row["released_publication_id"] == second
    assert not parent_row["can_review_verdict"]
    history = db.execute("SELECT publication_id,outcome FROM group_request_verdicts "
                         "WHERE request_id=%s ORDER BY id", (request_id,)).fetchall()
    assert [(r["publication_id"], r["outcome"]) for r in history] == [
        (first, "returned"), (second, "accepted")]
    visible_history = requests.verdict_history(db, users["viewer"], request_id)["items"]
    assert [item["outcome"] for item in visible_history] == ["accepted", "returned"]
    assert visible_history[0]["released_publication_id"] == second
    assert visible_history[1]["released_publication_id"] == first
    source_history = requests.verdict_history(db, users["publisher"], request_id)["items"]
    assert source_history[0]["reason"] is None
    assert source_history[1]["reason"] == "The period is missing"
    with pytest.raises(HTTPException) as sibling_history:
        requests.verdict_history(db, users["sibling"], request_id)
    assert sibling_history.value.status_code == 404
    group.revoke_publication(db, users["publisher"], first)
    db.commit()
    after_revoke = requests.verdict_history(db, users["viewer"], request_id)["items"]
    assert after_revoke[0]["released_publication_id"] == second
    assert after_revoke[1]["released_publication_id"] is None
    assert after_revoke[1]["title"] is None


def test_requirement_clarification_resends_without_source_mapping(group_world):
    db, parent, child, sibling, users, _ = group_world
    relation = _activate(db, parent, child, users)
    request_id = requests.create_request(db, users["viewer"], relation,
        "Parent control 1", "Need current proof", _future(14))
    requests.review_request(db, users["legal"], request_id, "clarification", "Specify the reporting period")
    db.commit()
    visible = requests.list_requests(db, users["viewer"])["items"][0]
    assert visible["status"] == "clarification" and visible["can_revise"]
    assert "requested_by" not in visible and "source_mapping" not in visible
    with pytest.raises(HTTPException) as wrong_person:
        requests.revise_request(db, users["ungranted"], request_id,
            "Parent control 1", "Clarified", _future(14), "2026-01-01", "2026-12-31")
    assert wrong_person.value.status_code == 404
    with pytest.raises(HTTPException) as wrong_org:
        requests.revise_request(db, users["sibling"], request_id,
            "Parent control 1", "Clarified", _future(14), "2026-01-01", "2026-12-31")
    assert wrong_org.value.status_code == 404
    requests.revise_request(db, users["viewer"], request_id,
        "Parent control 1", "Clarified", _future(14), "2026-01-01", "2026-12-31")
    db.commit()
    row = requests.list_requests(db, users["legal"])["items"][0]
    assert row["status"] == "requested" and row["period_start"] == "2026-01-01"
    assert row["decision_reason"] is None


def test_request_list_has_more_only_if_another_authorized_page_exists(group_world):
    db, parent, child, _, users, _ = group_world
    relation = _activate(db, parent, child, users)
    for index in range(51):
        requests.create_request(db, users["viewer"], relation,
            f"Parent requirement {index}", "Need assurance", _future(14))
    db.commit()
    first = requests.list_requests(db, users["viewer"], page=1)
    second = requests.list_requests(db, users["viewer"], page=2)
    assert len(first["items"]) == 50 and first["has_more"]
    assert len(second["items"]) == 1 and not second["has_more"]
    assert requests.list_requests(db, users["sibling"])["items"] == []


def test_grant_publication_and_relationship_revocation_hide_known_ids(group_world):
    db, parent, child, _, users, evidence = group_world
    relation = _activate(db, parent, child, users)
    view_grant = group.grant_view(db, users["parent_admin"], relation, users["viewer"]["id"],
                                  "document.view", _future(), _future(7))
    download_grant = group.grant_view(db, users["parent_admin"], relation, users["viewer"]["id"],
                                      "document.download", _future(), _future(7))
    group.reviewed_rights(db, users["privacy"], evidence, "owned", True, True, "Owned report")
    publication = group.publish(db, users["publisher"], relation, evidence,
                                "internal", "Group governance", _future())
    db.commit()
    assert group.released_item(db, users["viewer"], publication, download=True)[1]["id"] == evidence
    group.revoke_grant(db, users["parent_admin"], download_grant)
    db.commit()
    with pytest.raises(HTTPException) as blocked:
        group.released_item(db, users["viewer"], publication, download=True)
    assert blocked.value.status_code == 404
    group.revoke_grant(db, users["parent_admin"], view_grant)
    db.commit()
    assert group.catalogue(db, users["viewer"]) == []
    with pytest.raises(HTTPException):
        group.released_item(db, users["viewer"], publication)
    group.grant_view(db, users["parent_admin"], relation, users["viewer"]["id"],
                     "document.view", _future(), _future(7))
    db.commit()
    group.revoke_publication(db, users["publisher"], publication)
    db.commit()
    assert group.catalogue(db, users["viewer"]) == []
    impact = group.exit_impact(db, users["platform"], relation)
    assert impact["active_publications"] == 0
    assert impact["active_grants"] >= 1
    group.end_relationship(db, users["platform"], relation, "Group agreement concluded")
    db.commit()
    with pytest.raises(HTTPException):
        group.grant_view(db, users["parent_admin"], relation, users["viewer"]["id"],
                         "document.view", _future(), _future(7))


def test_metadata_only_terms_never_release_bytes(group_world):
    db, parent, child, _, users, evidence = group_world
    relation = group.propose_relationship(db, users["platform"], parent, child,
        "Group governance", _terms(), _future(90))
    db.commit()
    for who, kind in (("ack", "ack"), ("privacy", "privacy"), ("legal", "legal")):
        group.record_relationship_decision(db, users[who], relation, kind)
        db.commit()
    for capability in ("document.view", "document.download"):
        group.grant_view(db, users["parent_admin"], relation, users["viewer"]["id"],
                         capability, _future(), _future(7))
    group.reviewed_rights(db, users["privacy"], evidence, "owned", True, True, "Owned report")
    publication = group.publish(db, users["publisher"], relation, evidence,
                                "internal", "Group governance", _future())
    db.commit()
    assert group.released_item(db, users["viewer"], publication)[0]["id"] == publication
    with pytest.raises(HTTPException) as blocked:
        group.released_item(db, users["viewer"], publication, download=True)
    assert blocked.value.status_code == 404


def test_unapproved_policy_cannot_be_published(group_world):
    db, parent, child, _, users, _ = group_world
    relation = _activate(db, parent, child, users)
    policy = _id(db, "evidence_items", title="Unapproved policy", category="policy",
                 org_id=child, status="current", version=1, file_hash="policy-hash")
    group.reviewed_rights(db, users["privacy"], policy, "owned", True, False, "Owned")
    db.commit()
    with pytest.raises(HTTPException) as blocked:
        group.publish(db, users["publisher"], relation, policy,
                      "internal", "Group governance", _future())
    assert blocked.value.status_code == 409


def test_child_policy_adoption_is_independent_and_exact_version_bound(group_world):
    db, parent, child, _, users, _ = group_world
    relation = _activate(db, parent, child, users)
    parent_privacy = _actor(db, parent, "policy_privacy", "dpo")
    parent_publisher = _actor(db, parent, "policy_publisher", "grc_officer")
    parent_document = _id(db, "aria_documents", doc_id="PARENT-POLICY-1",
                          framework="ISO 27001", title="Group access policy", org_id=parent)
    for reviewer in (users["publisher"], users["legal"]):
        group.grant_view(db, users["ack"], relation, reviewer["id"],
                         "document.view", _future(25), _future(7))
    db.commit()

    def release(version, hash_value):
        version_id = _id(db, "aria_policy_versions", org_id=parent,
                         document_id=parent_document, version_major=version,
                         version_minor=0, version=f"{version}.0", state="approved", origin="authored")
        evidence_id = _id(db, "evidence_items", title="Group access policy",
                          org_id=parent, category="policy", status="current", version=version,
                          file_hash=hash_value, aria_policy_version_id=version_id)
        group.reviewed_rights(db, parent_privacy, evidence_id, "owned", True, False,
                              "Owned group policy")
        pub = group.publish(db, parent_publisher, relation, evidence_id,
                            "internal", "Group governance", _future(20))
        db.commit()
        return pub

    first = release(1, "group-policy-v1")
    assert [p["id"] for p in adoption.list_policies(db, users["publisher"])["items"]] == [first]
    parent_version = db.execute("SELECT aria_policy_version_id FROM evidence_items WHERE file_hash=%s",
                                ("group-policy-v1",)).fetchone()[0]
    with pytest.raises(HTTPException) as foreign_local_version:
        adoption.propose(db, users["publisher"], first, "adapted", "Local changes reviewed",
                         "2099-01-01", "2026-10-28", parent_version)
    assert foreign_local_version.value.status_code == 404
    with pytest.raises(HTTPException) as hidden:
        adoption.propose(db, users["sibling"], first, "adopted", "Accepted locally",
                         "2099-01-01", "2026-10-28")
    assert hidden.value.status_code in (403, 404)
    proposal = adoption.propose(db, users["publisher"], first, "adopted",
                                "Local owner checked group terms", "2099-01-01", "2026-10-28")
    db.commit()
    assert adoption.list_policies(db, users["publisher"])["items"][0]["adoption"]["state"] == "pending_review"
    with pytest.raises(HTTPException) as same_person:
        adoption.review(db, {**users["publisher"], "roles": ["grc_officer", "compliance_manager"]},
                        proposal, "approve", "Reviewed")
    assert same_person.value.status_code == 409
    assert adoption.review(db, users["legal"], proposal, "approve", "Independently checked") == "adopted"
    db.commit()
    assert adoption.list_policies(db, users["legal"])["items"][0]["adoption"]["state"] == "adopted"
    second = release(2, "group-policy-v2")
    current = adoption.list_policies(db, users["publisher"])["items"]
    assert current[0]["id"] == second and current[0]["adoption"] is None
    assert current[1]["id"] == first and current[1]["adoption"]["state"] == "adopted"
    group.revoke_publication(db, parent_publisher, first)
    db.commit()
    assert [p["id"] for p in adoption.list_policies(db, users["publisher"])["items"]] == [second]
