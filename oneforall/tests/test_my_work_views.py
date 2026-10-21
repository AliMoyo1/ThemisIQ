"""
My Work: one obligation is shown once, a change is not an action, and every item says who acts and why it is ranked
(plans/2026-10-governance-rework/04 section 3).

Before this an unread notification was an action ("needs my action") even when the item it was about was listed too, so
one assignment counted twice and a change inflated the queue. Expectations are written by hand from the rows inserted.
"""
import pytest

from modules.launcher.my_work_service import GROUPS, SECTIONS, get_my_work
from tests.test_my_work_service import _org, _user


def _all(result):
    return [item for section in result["sections"].values() for item in section]


def _by_title(result, title):
    found = [i for i in _all(result) if i["title"] == title]
    assert len(found) == 1, (title, [i["title"] for i in _all(result)])
    return found[0]


@pytest.fixture
def me(test_db):
    org = _org(test_db, "mywork-views-org")
    user = _user(test_db, "mywork_views_me", org)
    other = _user(test_db, "mywork_views_other", org)
    return {"db": test_db, "user": user, "other": other, "org": org}


def test_a_notification_is_a_change_not_an_action(me):
    me["db"].execute("INSERT INTO notifications (user_id, title, is_read) VALUES (%s,'Policy changed',0)",
                     (me["user"]["id"],))
    me["db"].commit()
    result = get_my_work(me["user"])
    assert "recently_changed" in SECTIONS
    assert [i["title"] for i in result["sections"]["recently_changed"]] == ["Policy changed"]
    assert result["sections"]["needs_my_action"] == []
    assert result["counts"]["recently_changed"] == 1 and result["counts"]["needs_my_action"] == 0

    only = get_my_work(me["user"], section="recently_changed")
    assert [i["title"] for i in only["sections"]["recently_changed"]] == ["Policy changed"]


def test_an_item_and_the_notification_about_it_are_one_line_that_says_it_was_also_notified(me):
    db, user = me["db"], me["user"]
    task = db.execute(
        "INSERT INTO task_board (title, status, assigned_to, created_by) VALUES ('Review the DPA', 'todo', %s, %s)",
        (user["id"], me["other"]["id"])).lastrowid
    db.execute("INSERT INTO notifications (user_id, title, link, is_read) VALUES (%s,'Task assigned to you',%s,0)",
               (user["id"], f"/tasks?open={task}"))
    db.execute("INSERT INTO notifications (user_id, title, link, is_read) VALUES (%s,'Unrelated change','/aria/',0)",
               (user["id"],))
    db.commit()
    result = get_my_work(user)
    titles = [i["title"] for i in _all(result)]
    assert titles.count("Review the DPA") == 1
    assert "Task assigned to you" not in titles, "the notification adds nothing the task does not already say"
    assert "Unrelated change" in titles, "a notification about something else stays"
    assert _by_title(result, "Review the DPA")["also_notified"] == 1


def test_every_item_says_what_kind_of_action_who_acts_and_why_it_is_ranked(me):
    db, user = me["db"], me["user"]
    db.execute("INSERT INTO task_board (title, status, assigned_to, created_by, due_date, priority) "
               "VALUES ('Mine, late', 'todo', %s, %s, '2020-01-01', 'high')", (user["id"], me["other"]["id"]))
    db.execute("INSERT INTO task_board (title, status, assigned_to, created_by, priority) "
               "VALUES ('Handed to them', 'todo', %s, %s, 'low')", (me["other"]["id"], user["id"]))
    db.commit()
    result = get_my_work(user)

    mine = _by_title(result, "Mine, late")
    assert mine["section"] == "overdue" and mine["action_kind"] == "do"
    assert (mine["responsible"], mine["source_state"]) == ("you", "open")
    assert mine["priority_basis"] == "Due 2020-01-01"

    theirs = _by_title(result, "Handed to them")
    assert theirs["section"] == "waiting_on_others"
    assert (theirs["responsible"], theirs["source_state"], theirs["action_kind"]) == ("others", "waiting", "do")
    assert theirs["priority_basis"] == "Priority: low"


def test_grouping_is_presentation_only_and_names_each_group(me):
    db, user = me["db"], me["user"]
    unit = db.execute("INSERT INTO business_units (name, is_active) VALUES ('Unit North', 1)").lastrowid
    user = {**user, "business_unit_id": unit}
    db.execute("INSERT INTO task_board (title, status, assigned_to, created_by, business_unit_id) "
               "VALUES ('North task', 'todo', %s, %s, %s)", (user["id"], me["other"]["id"], unit))
    db.execute("INSERT INTO task_board (title, status, assigned_to, created_by) VALUES ('Everywhere task', 'todo', %s, %s)",
               (user["id"], me["other"]["id"]))
    db.commit()

    plain = get_my_work(user)
    grouped = get_my_work(user, group="business_unit")
    assert [i["title"] for i in _all(plain)] == [i["title"] for i in _all(grouped)], "the same items, in the same order"
    labels = {g["label"]: g["count"] for g in grouped["groups"]}
    assert labels == {"Unit North": 1, "Whole organization": 1}
    assert _by_title(grouped, "North task")["group_key"] == str(unit)

    by_source = get_my_work(user, group="source")
    assert {g["key"] for g in by_source["groups"]} == {"platform"}
    assert get_my_work(user)["groups"] == [] and get_my_work(user)["group"] == ""


def test_a_finding_is_grouped_under_its_audit(test_db):
    org = _org(test_db, "mywork-audit-org")
    lead = {**_user(test_db, "mywork_audit_lead", org), "roles": ["audit_lead"]}
    audit = test_db.execute("INSERT INTO grid_audits (name, status) VALUES ('Q3 access audit', 'Active')").lastrowid
    test_db.execute("INSERT INTO grid_non_conformances (audit_id, title, status, assigned_to, severity) "
                    "VALUES (%s, 'Shared admin account', 'open', %s, 'high')", (audit, lead["id"]))
    test_db.commit()
    result = get_my_work(lead, group="parent")
    finding = _by_title(result, "Audit finding: Shared admin account")
    assert finding["context"] == {"kind": "audit", "id": audit, "title": "Q3 access audit"}
    assert {g["label"] for g in result["groups"]} == {"Audit: Q3 access audit"}
    assert finding["group_key"] == f"audit:{audit}"


def test_only_the_named_groupings_are_accepted(me):
    assert GROUPS == ("", "source", "business_unit", "parent", "vendor", "process")
    with pytest.raises(ValueError):
        get_my_work(me["user"], group="owner")
