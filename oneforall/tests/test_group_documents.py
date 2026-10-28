"""Synthetic parent, child and sibling disclosure boundaries."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from modules.evidence import group_documents as group


def _id(db, table, **fields):
    keys = list(fields)
    db.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))})",
               [fields[k] for k in keys])
    db.commit()
    return db.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]


def _actor(db, org, key, role, unit=None):
    uid = _id(db, "users", username=key, email=key + "@example.invalid", full_name=key,
              password_hash="test", org_id=org, is_active=1)
    return {"id": uid, "org_id": org, "business_unit_id": unit, "roles": [role]}


def _future(days=30):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _terms(*classes):
    return {"data_classes": ["document_metadata", *classes], "classifications": ["internal"],
            "audiences": ["grc_officer"],
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
