"""
The Overview, the portfolio and the systems list through HTTP (plans/2026-10-governance-rework/01 section 3).

Written by hand. Nobody signed out reaches any of them, an outside auditor is refused, staff get their own numbers and not
the specialist ones, a bad filter is a 400 that names the problem, and a unit never reads another unit's portfolio.
"""
import pytest

from tests.test_ai_governance_routes import FULL, _submit, http  # noqa: F401
from tests.test_platform_ownership import PERSONAS, _insert, world  # noqa: F401

PAGES = ("/ai-governance/", "/ai-governance/systems", "/ai-governance/monitoring")
APIS = ("/ai-governance/api/overview", "/ai-governance/api/portfolio")


def _accepted(http, name="employee_a", answers=None, reviewer="dpo_a"):
    row = _submit(http, name, {**FULL, **(answers or {})})
    done = http("post", f"/ai-governance/api/review/requests/{row['id']}/approve", name=reviewer,
                json={"version": row["version"], "new_application": {}})
    assert done.status_code == 200, done.text
    return done.json()["application_id"]


@pytest.mark.parametrize("path", PAGES + APIS)
def test_nobody_signed_out_reaches_any_of_them(http, path):
    assert http("get", path, name=None).status_code == 303


@pytest.mark.parametrize("path", PAGES + APIS)
def test_an_outside_auditor_is_refused(http, path):
    assert http("get", path, name="auditor").status_code == 403


@pytest.mark.parametrize("path", PAGES)
def test_the_pages_open_for_staff_and_specialists(http, path):
    for who in ("employee_a", "dpo_a", "super"):
        assert http("get", path, name=who).status_code == 200, (path, who)


def test_the_landing_page_is_the_overview_and_the_inventory_moved_to_systems(http):
    landing = http("get", "/ai-governance/", name="dpo_a").text
    assert "aigOverview" in landing and "aigInventory" not in landing
    assert "aigInventory" in http("get", "/ai-governance/systems", name="dpo_a").text
    assert "aigPortfolio" in http("get", "/ai-governance/monitoring", name="dpo_a").text


def test_a_specialist_gets_the_cards_and_staff_get_their_own(http):
    mine = http("get", "/ai-governance/api/overview", name="dpo_a").json()
    assert mine["ok"] is True and mine["viewer"]["specialist"] is True
    assert [c["key"] for c in mine["cards"]][:2] == ["new_requests", "waiting_for_information"]
    staff = http("get", "/ai-governance/api/overview", name="employee_a").json()
    assert staff["viewer"]["specialist"] is False and [c["key"] for c in staff["cards"]] == ["my_requests", "my_systems"]


def test_the_overview_counts_a_submitted_request_for_its_unit_only(http):
    _submit(http, "employee_a")
    assert http("get", "/ai-governance/api/overview", name="dpo_a").json()["cards"][0]["value"] == 1
    assert http("get", "/ai-governance/api/overview", name="dpo_b").json()["cards"][0]["value"] == 0
    assert http("get", "/ai-governance/api/overview", name="employee_a").json()["cards"][0]["value"] == 1, "their own request"
    assert http("get", "/ai-governance/api/overview", name="owner_b").json()["cards"][0]["value"] == 0


def test_the_portfolio_lists_the_uses_in_scope_and_never_a_hidden_one(http):
    mine = _accepted(http)
    theirs = _accepted(http, "owner_b", {"name": "Unit B use"}, reviewer="dpo_b")
    got = http("get", "/ai-governance/api/portfolio", name="dpo_a").json()
    assert [u["application_id"] for u in got["uses"]] == [mine] and got["total_uses"] == 1
    assert "Unit B use" not in http("get", "/ai-governance/api/portfolio", name="dpo_a").text
    assert [u["application_id"] for u in http("get", "/ai-governance/api/portfolio", name="dpo_b").json()["uses"]] == [theirs]
    assert {u["application_id"] for u in http("get", "/ai-governance/api/portfolio", name="super").json()["uses"]} == {mine, theirs}


def test_a_use_with_nothing_recorded_is_listed_as_not_measured(http):
    app = _accepted(http)
    use = http("get", "/ai-governance/api/portfolio", name="dpo_a").json()["uses"][0]
    assert use["application_id"] == app and use["flags"] == []
    assert {n["key"] for n in use["not_measured"]} == {"no_evaluation", "no_oversight"}


def test_the_portfolio_focus_filters_and_a_bad_one_is_a_400(http):
    _accepted(http)
    assert http("get", "/ai-governance/api/portfolio?focus=gaps", name="dpo_a").json()["uses"] == []
    assert http("get", "/ai-governance/api/portfolio?focus=all", name="dpo_a").json()["total_uses"] == 1
    bad = http("get", "/ai-governance/api/portfolio?focus=everything", name="dpo_a")
    assert bad.status_code == 400 and bad.json()["ok"] is False


def test_the_systems_list_filters_by_review_soon_and_rejects_an_unknown_state(http):
    _accepted(http)
    assert http("get", "/ai-governance/api/systems?state=review_soon", name="dpo_a").status_code == 200
    assert http("get", "/ai-governance/api/systems?state=whenever", name="dpo_a").status_code == 400


def test_the_review_queue_returns_the_requests_sent_back(http):
    row = _submit(http, "employee_a")
    sent_back = http("post", f"/ai-governance/api/review/requests/{row['id']}/return", name="dpo_a",
                     json={"note": "Which vendor is it?", "version": row["version"]})
    assert sent_back.status_code == 200
    assert http("get", "/ai-governance/api/review/queue", name="dpo_a").json()["items"] == []
    waiting = http("get", "/ai-governance/api/review/queue?status=returned", name="dpo_a").json()["items"]
    assert [r["id"] for r in waiting] == [row["id"]]
