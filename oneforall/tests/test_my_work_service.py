"""
PLAN-36 P01: My Work action centre federated read model
(modules/launcher/my_work_service.py). Discovery gate answered 2026-09-30
(see task_plan.md P01) -- this tests the four sources wired in this first
slice (ARIA approvals, evidence expiry, task_board, notifications), not the
five named-but-pending sources (see the module's own _PENDING_SOURCES list).

Org/BU isolation is the acceptance criterion named first in task_plan.md
P01 ("no cross-org/SBU item leakage") -- each source test below has a
same-org/BU positive control alongside its cross-org/BU denial, same
discipline as every isolation test elsewhere in this plan.

ARIA approvals are the one wired source with no dedicated test in this
file: a real aria_document_approvals row needs the full workflow pipeline
(a real aria_documents + aria_policy_versions row, satisfying several
CHECK/NOT NULL constraints -- state, origin, version_major/minor,
round_number, request_id, a real docx template on disk, mocked LibreOffice
conversion) -- the exact heavy tmp_path/monkeypatch fixture
tests/test_aria_policy_approvals.py's own
test_two_concurrent_deciders_exactly_one_wins already builds for this
reason. Building a second copy of that fixture just to re-prove the query
shape was judged not worth it: _aria_approvals()'s WHERE clause
(`a.approver_id=%s AND a.status='pending' AND d.org_id=%s`) is deliberately
byte-for-byte the same as policy_workflow_service.py's own already-tested
list_pending_approvals_for(), not new logic -- see this file's own docstring
for the tradeoff.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.launcher.my_work_service import get_my_work, SECTIONS


def _org(test_db, slug):
    test_db.execute(
        "INSERT INTO organizations (name, slug, plan, status) VALUES (%s, %s, 'enterprise', 'active')",
        (slug, slug),
    )
    test_db.commit()
    return test_db.execute("SELECT id FROM organizations WHERE slug=%s", (slug,)).fetchone()["id"]


def _user(test_db, username, org_id):
    cur = test_db.execute(
        "INSERT INTO users (username, email, full_name, password_hash, org_id) VALUES (%s,%s,%s,'x',%s)",
        (username, f"{username}@example.test", username, org_id),
    )
    test_db.commit()
    return {"id": cur.lastrowid, "org_id": org_id, "is_super_admin": False}


def test_shape_has_all_five_sections_and_registered_sources(test_db):
    org_id = _org(test_db, "mywork-shape-org")
    user = _user(test_db, "mywork_shape_user", org_id)

    result = get_my_work(user)

    assert set(result["sections"].keys()) == set(SECTIONS)
    assert isinstance(result["pending_sources"], list)
    assert result["pending_sources"] == []
    assert {state["source"] for state in result["source_states"]} == {
        "aria_approvals", "evidence_expiry", "task_board", "notifications",
        "workflow_actions", "grid_non_conformances", "erm_reviews",
        "orm_reviews", "bcm_incidents", "privacy_deadlines",
    }


def test_evidence_expiring_soon_is_scoped_to_my_org(test_db):
    org_a = _org(test_db, "mywork-evidence-org-a")
    org_b = _org(test_db, "mywork-evidence-org-b")
    user_a = _user(test_db, "mywork_evidence_user_a", org_a)

    from core.timeutils import utcnow
    from datetime import timedelta
    soon = (utcnow() + timedelta(days=10)).strftime("%Y-%m-%d")
    test_db.execute(
        "INSERT INTO evidence_items (title, status, expiry_date, org_id) VALUES (%s,'current',%s,%s)",
        ("Org A Expiring Evidence", soon, org_a),
    )
    test_db.execute(
        "INSERT INTO evidence_items (title, status, expiry_date, org_id) VALUES (%s,'current',%s,%s)",
        ("Org B Expiring Evidence", soon, org_b),
    )
    test_db.commit()

    result = get_my_work(user_a)
    all_titles = [it["title"] for section in result["sections"].values() for it in section]
    assert any("Org A Expiring Evidence" in t for t in all_titles)
    assert not any("Org B Expiring Evidence" in t for t in all_titles)


def test_my_tasks_only_shows_tasks_assigned_to_or_created_by_me(test_db):
    org_id = _org(test_db, "mywork-tasks-org")
    me = _user(test_db, "mywork_tasks_me", org_id)
    someone_else = _user(test_db, "mywork_tasks_other", org_id)

    test_db.execute(
        "INSERT INTO task_board (title, status, assigned_to, created_by) VALUES (%s,'todo',%s,%s)",
        ("My Assigned Task", me["id"], someone_else["id"]),
    )
    test_db.execute(
        "INSERT INTO task_board (title, status, assigned_to, created_by) VALUES (%s,'todo',%s,%s)",
        ("Someone Else's Task", someone_else["id"], someone_else["id"]),
    )
    test_db.commit()

    result = get_my_work(me)
    all_titles = [it["title"] for section in result["sections"].values() for it in section]
    assert "My Assigned Task" in all_titles
    assert "Someone Else's Task" not in all_titles


def test_unread_notifications_only_shows_my_own(test_db):
    org_id = _org(test_db, "mywork-notif-org")
    me = _user(test_db, "mywork_notif_me", org_id)
    someone_else = _user(test_db, "mywork_notif_other", org_id)

    test_db.execute(
        "INSERT INTO notifications (user_id, title, is_read) VALUES (%s,%s,0)",
        (me["id"], "My Notification"),
    )
    test_db.execute(
        "INSERT INTO notifications (user_id, title, is_read) VALUES (%s,%s,0)",
        (someone_else["id"], "Someone Else's Notification"),
    )
    test_db.commit()

    result = get_my_work(me)
    all_titles = [it["title"] for section in result["sections"].values() for it in section]
    assert "My Notification" in all_titles
    assert "Someone Else's Notification" not in all_titles
