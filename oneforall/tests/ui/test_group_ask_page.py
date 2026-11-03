"""Asking the released group documents from the Vault (plan 22, C11), in a real browser with the assistant off."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import database
import pytest
from playwright.sync_api import expect


def _stamp(days=0):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(tzinfo=None, microsecond=0).isoformat()


@pytest.fixture
def released_document(live_app, synthetic_tenant):
    db = database.get_db()
    tag = uuid.uuid4().hex[:8]
    try:
        me = db.execute("SELECT id, org_id FROM users WHERE username=%s",
                        (synthetic_tenant["users"]["compliance_manager"]["username"],)).fetchone()
        db.execute("INSERT INTO organizations (name, slug, status, plan) VALUES ('Ask Child Co',%s,'active','enterprise')",
                   ("ga_child_" + tag,))
        child = db.execute("SELECT id FROM organizations WHERE slug=%s", ("ga_child_" + tag,)).fetchone()["id"]
        terms = {"data_classes": ["document_metadata"], "classifications": ["internal"],
                 "audiences": ["compliance_manager"], "fields": ["title", "category", "version", "source_name",
                                                                  "classification", "expires_at"]}
        db.execute("INSERT INTO org_relationships (parent_org_id,child_org_id,status,purpose,child_ack_by,"
                   "privacy_review_by,legal_review_by,terms_json,review_due_at) VALUES (%s,%s,'active','Group',1,2,3,%s,%s)",
                   (me["org_id"], child, json.dumps(terms), _stamp(90)))
        relation = db.execute("SELECT MAX(id) AS i FROM org_relationships").fetchone()["i"]
        db.execute("INSERT INTO evidence_items (title,category,org_id,status,version,file_hash) "
                   "VALUES ('Continuity plan','report',%s,'current',1,%s)", (child, "ga-" + tag))
        evidence = db.execute("SELECT MAX(id) AS i FROM evidence_items").fetchone()["i"]
        db.execute("INSERT INTO evidence_text_index (evidence_id,org_id,file_hash,indexer_version,status,content_text,"
                   "segments_json) VALUES (%s,%s,%s,'t','indexed',%s,'[]')",
                   (evidence, child, "ga-" + tag, "The recovery time objective for payments is four hours."))
        db.execute("INSERT INTO group_document_rights (source_org_id,evidence_id,file_hash,rights_state,permit_group_view,"
                   "permit_group_download,basis,reviewed_by) VALUES (%s,%s,%s,'owned',1,0,'Owned',1)",
                   (child, evidence, "ga-" + tag))
        rights = db.execute("SELECT MAX(id) AS i FROM group_document_rights").fetchone()["i"]
        db.execute("INSERT INTO group_document_publications (relationship_id,source_org_id,viewer_org_id,evidence_id,"
                   "version,file_hash,title,category,classification,purpose,rights_id,expires_at,approved_by) "
                   "VALUES (%s,%s,%s,%s,1,%s,'Continuity plan','report','internal','Group',%s,%s,2)",
                   (relation, child, me["org_id"], evidence, "ga-" + tag, rights, _stamp(30)))
        db.execute("INSERT INTO group_view_grants (relationship_id,source_org_id,viewer_org_id,user_id,capability,"
                   "expires_at,review_due_at,granted_by) VALUES (%s,%s,%s,%s,'document.view',%s,%s,999)",
                   (relation, child, me["org_id"], me["id"], _stamp(30), _stamp(7)))
        db.commit()
    finally:
        db.close()
    yield child
    db = database.get_db()
    try:
        for sql in ("DELETE FROM group_access_events WHERE source_org_id=%s",
                    "DELETE FROM group_view_grants WHERE source_org_id=%s",
                    "DELETE FROM group_document_publications WHERE source_org_id=%s",
                    "DELETE FROM group_document_rights WHERE source_org_id=%s",
                    "DELETE FROM evidence_text_index WHERE org_id=%s",
                    "DELETE FROM evidence_items WHERE org_id=%s",
                    "DELETE FROM org_relationships WHERE child_org_id=%s",
                    "DELETE FROM organizations WHERE id=%s"):
            db.execute(sql, (child,))
        db.commit()
    finally:
        db.close()


def test_a_question_returns_cited_passages_from_released_documents(login_as, live_app, released_document):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/evidence/")
    expect(page.locator("#evGroupSection")).to_be_visible()
    page.locator("#evGroupQuestion").fill("What is the recovery time objective for payments?")
    page.locator("#evGroupAsk").get_by_role("button", name="Ask").click()
    answer = page.locator("#evGroupAnswer")
    expect(answer).to_contain_text("[1] Continuity plan v1 · Ask Child Co")
    expect(answer).to_contain_text("four hours")
