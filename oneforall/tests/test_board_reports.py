"""
Board reports of Enterprise Risk, Operations Risk and Resilience (decision D7 of PLAN_report_exports_2026-10-21.md).

Each module's "Board Report" button used to return a model written narrative and nothing else. The button now has a document
beside it: cover, headline measures, charts and the records behind them, built from the very figures the module's dashboard
shows the same person. The expectations are written out by hand from a seeded file, and the report is also asked the question
the page is asked, so the two must agree. Each persona sees only what its business unit scope opens; each "cannot" has a
positive twin. No model is called to build a document.
"""
import io
import re
from datetime import timedelta

import pytest
from fastapi import FastAPI
from pypdf import PdfReader
from starlette.testclient import TestClient

import core.middleware as middleware
import modules.bcm.routes as bcm_routes
import modules.erm.routes as erm_routes
import modules.orm.routes as orm_routes
from core import rbac
from core.report_kit import theme
from core.report_kit.model import Callout, Kpis
from core.timeutils import utcnow
from modules.bcm import board_report as bcm_board, dashboard_metrics
from modules.erm import board_report as erm_board, data_service as erm_ds
from modules.orm import board_report as orm_board, data_service as orm_ds
from tests.test_platform_ownership import _insert, world  # noqa: F401

PERSONAS = ("super", "dpo_a", "dpo_a1", "dpo_b", "dpo_no_unit")


# ── Helpers ─────────────────────────────────────────────────────────────────

def _kpis(report):
    return {k.label: k for block in report.blocks if isinstance(block, Kpis) for k in block.items}


def _chart(report, title):
    return next(c for c in report.charts() if c.title == title)


def _table(report, title):
    return next(t for t in report.tables() if t.title == title)


def _callout(report, title):
    return next((c for c in report.blocks if isinstance(c, Callout) and c.title == title), None)


def _pages(pdf_bytes):
    return [page.extract_text() for page in PdfReader(io.BytesIO(pdf_bytes)).pages]


def _owners(world):
    """Risk owners reach Operations Risk and Resilience (a data protection officer reaches neither): one per unit, one in the child
    unit and one with no unit, so each scope has its persona."""
    for name, tag in (("owner_a1", "A1"), ("owner_none", None)):
        unit = world.unit.get(tag) if tag else None
        uid = 200 + len(world.users)
        world.users[name] = {"id": uid, "username": name, "org_id": 1, "business_unit_id": unit, "is_super_admin": 0, "roles": [rbac.RISK_OWNER]}
        _insert(world.db, "users", id=uid, username=name, email=f"{name}@example.test", full_name=name, password_hash="x", org_id=1,
                business_unit_id=unit)


@pytest.fixture
def web(world, monkeypatch):
    who = {"name": "super"}

    async def current_user(request):
        return world.users[who["name"]]

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    app = FastAPI()
    for module in (erm_routes, orm_routes, bcm_routes):
        app.include_router(module.router)
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False, follow_redirects=False)

    def call(path, name="super"):
        who["name"] = name
        return client.get(path)

    def post(path, name="super"):
        who["name"] = name
        return client.post(path)

    call.post = post
    call.world = world
    return call


# ── Enterprise Risk ─────────────────────────────────────────────────────────

def _erm(world):
    """Open risks: A (3 x 3, unit A), B (5 x 5, unit B, board visible), organization wide (2 x 2), all in one category whose
    appetite limit is 8. One regulatory obligation is overdue."""
    db, unit = world.db, world.unit
    db.execute("UPDATE erm_enterprise_risks SET category='operational', likelihood=3, impact=3 WHERE id=%s", (world.rec[("erm", "A")],))
    db.execute("DELETE FROM erm_risk_appetite")
    _insert(db, "erm_risk_appetite", category="operational", appetite_level="low", max_score=8)
    _insert(db, "erm_enterprise_risks", title="Risk B", category="operational", likelihood=5, impact=5, status="open",
            business_unit_id=unit["B"], board_visibility=1)
    _insert(db, "erm_enterprise_risks", title="Risk org", category="operational", likelihood=2, impact=2, status="open", business_unit_id=None)
    _insert(db, "erm_regulatory_obligations", regulator="R", regulation_name="Act", obligation="Report", due_date="2001-01-01",
            status="pending")


def test_the_erm_report_states_the_dashboard_figures_of_the_records_the_caller_can_open(world):
    _erm(world)
    # persona: (open enterprise risks, risks above appetite, highest residual score as a percent of the limit of 8)
    expected = {"super": (3, 2, 313), "dpo_a": (2, 1, 113), "dpo_a1": (1, 0, 50), "dpo_b": (2, 1, 313), "dpo_no_unit": (1, 0, 50)}
    for persona, (total, breaches, exposure) in expected.items():
        user = world.users[persona]
        page = erm_ds.get_dashboard_stats(None, user=user)
        report = erm_board.board_report(user)
        kpis = _kpis(report)
        assert page["total_enterprise_risks"] == total and page["appetite_breaches"] == breaches, persona
        assert kpis["Open risks"].value == str(page["total_risks"]) == str(total), persona
        assert kpis["Risks above appetite"].value == str(breaches), persona
        assert kpis["Critical enterprise risks"].value == str(page["critical"]), persona
        assert kpis["Overdue obligations"].value == str(page["overdue_obligations"]) == "1", persona
        assert kpis["Board-visible risks"].value == str(page["board_visible"]), persona
        chart = _chart(report, "Exposure against appetite, by category")
        assert chart.data == [("Operational", exposure)], persona
        assert sum(v for _, v in _chart(report, "Open risks by band, enterprise and platform registers").data) == total, persona
    assert erm_board.board_report(world.users["super"]).meta.tier == theme.BOARD


def test_the_erm_exposure_percent_rounds_half_up(world):
    """25 on a limit of 8 is 312.5 percent: 313, as a person and the page round it (round() says 312)."""
    _erm(world)
    assert _chart(erm_board.board_report(world.users["super"]), "Exposure against appetite, by category").data == [("Operational", 313)]


def test_the_erm_decisions_come_from_the_figures_and_name_a_missing_appetite(world):
    _erm(world)
    decisions = _callout(erm_board.board_report(world.users["super"]), "Decisions for the board").items
    assert any(item.startswith("2 risks are above the appetite set for their category") for item in decisions)
    assert any(item.startswith("1 regulatory obligation overdue") for item in decisions)
    world.db.execute("DELETE FROM erm_risk_appetite")
    world.db.commit()
    report = erm_board.board_report(world.users["super"])
    assert any("No risk appetite is set" in item for item in _callout(report, "Decisions for the board").items)
    assert "No risk appetite is set" in _chart(report, "Exposure against appetite, by category").empty_text
    assert _table(report, "Risk appetite by category").rows == []


def test_the_erm_narrative_stub_does_not_claim_the_risks_are_within_an_appetite_that_is_not_set():
    from modules.erm.ai_service import _stub_board_narrative
    stats = {"total_risks": 4, "critical": 1, "appetite_breaches": 0}
    none_set = _stub_board_narrative(stats, [])
    assert "No risk appetite is set" in none_set and "within" not in none_set
    within = _stub_board_narrative(stats, [{"category": "operational", "breached": False}])
    assert "within the appetite set for its category" in within
    assert "above the appetite" in _stub_board_narrative({**stats, "appetite_breaches": 2}, [{"category": "x", "breached": True}])


# ── Operations Risk ─────────────────────────────────────────────────────────

def _orm(world):
    """Events recorded now: A (unit A, 100 USD, 5 customers, 1 hour), B (unit B, 1000 USD, 50 customers, 2 hours), one
    organization wide (10 USD). One organization wide event of 500 USD was recorded 40 days ago: the period before."""
    db, unit = world.db, world.unit
    db.execute("UPDATE orm_events SET financial_impact=100, customers_affected=5, downtime_minutes=60, event_type='outage' WHERE id=%s",
               (world.rec[("event", "A")],))
    _insert(db, "orm_events", title="Event B", event_type="fraud", severity="high", financial_impact=1000, customers_affected=50,
            downtime_minutes=120, business_unit_id=unit["B"])
    _insert(db, "orm_events", title="Event org", event_type="outage", financial_impact=10, business_unit_id=None)
    _insert(db, "orm_events", title="Earlier event", event_type="outage", financial_impact=500, business_unit_id=None,
            created_at=(utcnow() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S"))


def test_the_orm_report_states_the_dashboard_figures_of_the_events_the_caller_can_open(world):
    _orm(world)
    _owners(world)
    # persona: (events, financial loss, loss against the 500 of the period before)
    expected = {"super": (3, 1110, 610), "owner_a": (2, 110, -390), "owner_a1": (1, 10, -490), "owner_b": (2, 1010, 510),
                "owner_none": (1, 10, -490)}
    for persona, (events, loss, delta) in expected.items():
        user = world.users[persona]
        page = orm_ds.get_dashboard_stats(days=30, user=user)
        report = orm_board.board_report(user)
        kpis = _kpis(report)
        assert (page["total_events"], page["financial_loss"], page["financial_loss_delta"]) == (events, loss, delta), persona
        assert kpis["Events recorded"].value == str(events), persona
        assert kpis["Financial loss, USD"].value == f"{loss:,}", persona
        word = "up" if delta > 0 else "down"
        assert kpis["Financial loss, USD"].note == f"{word} USD {abs(delta):,} on the previous 30 days", persona
        periods = dict(_chart(report, "Financial loss, this period against the one before").data)
        assert periods == {"Previous 30 days": 500, "Last 30 days": loss}, persona
        assert report.meta.tier == theme.BOARD


def test_the_orm_report_charts_the_largest_losses_of_the_events_in_scope(world):
    _orm(world)
    assert _chart(orm_board.board_report(world.users["super"]), "Largest losses, last 30 days").data == [
        ("Event B", 1000), ("Event A", 100), ("Event org", 10)]
    assert _chart(orm_board.board_report(world.users["owner_a"]), "Largest losses, last 30 days").data == [("Event A", 100), ("Event org", 10)]
    # a tie is not reported as one type leading
    by_type = _chart(orm_board.board_report(world.users["super"]), "Events by type, last 30 days")
    assert by_type.data == [("Outage", 2), ("Fraud", 1)]
    assert "Outage is the largest type: 2 of 3 events (67%)." == by_type.takeaway


def test_a_tie_for_the_largest_group_is_not_reported_as_a_leader():
    from core.report_kit.helpers import leader
    assert leader([("A", 2), ("B", 2), ("C", 1)], 5, "type", "event") == "2 types are tied for the largest share: 2 events each."
    assert leader([("A", 3), ("B", 1)], 4, "category", "open risk", group_plural="categories") == "A is the largest category: 3 of 4 open risks (75%)."
    assert leader([], 0, "type", "event") == ""


# ── Resilience ──────────────────────────────────────────────────────────────

def _bcm(world):
    """Incident B (unit B) is open. One approved plan in unit A. No analysis and no exercise is recorded."""
    db, unit = world.db, world.unit
    db.execute("UPDATE bcm_incidents SET status='open' WHERE id=%s", (world.rec[("incident", "B")],))
    _insert(db, "bcm_plans", title="Plan A", status="approved", version="1.0", business_unit_id=unit["A"])
    db.commit()


def test_the_bcm_report_states_the_dashboard_metrics_of_the_records_the_caller_can_open(world):
    _bcm(world)
    _owners(world)
    expected = {"super": (1, 1), "owner_a": (0, 1), "owner_b": (1, 0), "owner_none": (0, 0)}      # (open incidents, plans)
    for persona, (incidents, plans) in expected.items():
        user = world.users[persona]
        page = dashboard_metrics.stats(user)
        kpis = _kpis(bcm_board.board_report(user))
        assert page["open_incidents"] == incidents and page["plans"] == plans, persona
        assert kpis["Open incidents"].value == str(incidents), persona
        assert kpis["Continuity plans"].value == str(plans), persona


def test_a_metric_with_nothing_to_measure_is_not_measured_in_the_report_and_never_a_zero(world):
    _bcm(world)
    report = bcm_board.board_report(world.users["super"])
    kpis = _kpis(report)
    assert kpis["Exercises completed"].value == "Not measured" and kpis["Exercises completed"].note == "No exercise is recorded yet."
    assert kpis["Analyses with a continuity plan"].value == "Not measured"
    assert _chart(report, "Exercises completed").is_empty()
    assert _chart(report, "Exercises completed").empty_text == "No exercise is recorded yet."
    assert not any(k.value in ("0%", "0") for label, k in kpis.items() if label in ("Exercises completed", "Analyses with a continuity plan"))


def test_the_bcm_percentages_round_half_up_on_the_dashboard_the_report_reads(world):
    """5 of 8 exercises completed is 62.5 percent: 63. The dashboard used round(), which says 62."""
    _bcm(world)
    for n in range(8):
        _insert(world.db, "bcm_exercises", title=f"Exercise {n}", type="tabletop", status="completed" if n < 5 else "planned")
    page = dashboard_metrics.stats(world.users["super"])
    assert page["exercise_pct"] == 63
    assert _kpis(bcm_board.board_report(world.users["super"]))["Exercises completed"].value == "63%"


def test_the_command_centre_percentage_rounds_half_up():
    from modules.launcher import command_metrics
    assert command_metrics._percent(5, 8) == 63 and command_metrics._percent(1, 8) == 13 and command_metrics._percent(0, 0) is None


def test_the_bcm_narrative_stub_never_prints_a_figure_that_could_not_be_read():
    from modules.bcm.ai_service import _stub_board_narrative
    text = _stub_board_narrative({"plans": None, "open_incidents": None})
    assert "None" not in text and "No plan or incident figure could be read" in text
    assert "**3** continuity plan(s)" in _stub_board_narrative({"plans": 3, "open_incidents": None})


# ── The documents ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("path, stem, module_name, who, capable", [
    ("/erm/api/board-report/document", "ThemisIQ_enterprise_risk_board_report", "Enterprise Risk", "owner_a", "employee_a"),
    ("/orm/api/board-report/document", "ThemisIQ_operations_risk_board_report", "Operations Risk", "owner_a", "employee_a"),
    ("/bcm/api/board-report/document", "ThemisIQ_continuity_board_report", "Resilience", "super", "owner_a")])
def test_the_board_report_downloads_as_a_pdf_with_the_board_cover_and_a_footer_on_every_page(web, path, stem, module_name, who, capable):
    answer = web(path, name=who)
    assert answer.status_code == 200 and answer.headers["content-type"] == "application/pdf" and answer.content.startswith(b"%PDF")
    assert re.fullmatch(rf'attachment; filename="{stem}_\d{{8}}_\d{{4}}\.pdf"', answer.headers["content-disposition"])
    assert answer.headers["x-content-type-options"] == "nosniff" and answer.headers["cache-control"] == "no-store"
    reader = PdfReader(io.BytesIO(answer.content))
    pages = _pages(answer.content)
    assert len(reader.pages[0].images) >= 1, "the ThemisIQ logo is on the cover"
    assert "Board report" in pages[0]
    for number, text in enumerate(pages, start=1):
        assert f"Module: {module_name}" in text and f"Generated by {who}" in text and "UTC" in text and "CAT" in text, number
        assert f"Page {number} of {len(pages)}" in text and "Board report" in text, number
    assert web(path + "?format=xlsx", name=who).content.startswith(b"PK")
    assert web(path + "?format=docx", name=who).status_code == 400
    # the same permission as the AI narrative beside it: a role without it is refused
    assert web(path, name=capable).status_code == 403


def test_the_board_report_is_recorded_in_the_audit_trail(web):
    world = web.world
    world.db.execute("DELETE FROM audit_log")
    world.db.commit()
    assert web("/erm/api/board-report/document", name="owner_a").status_code == 200
    assert web("/orm/api/board-report/document", name="owner_a").status_code == 200
    assert web("/bcm/api/board-report/document", name="super").status_code == 200
    rows = world.db.execute("SELECT module, action, details FROM audit_log WHERE action = 'report_export' ORDER BY module").fetchall()
    assert [r["module"] for r in rows] == ["bcm", "erm", "orm"]
    assert all("tier=board" in r["details"] for r in rows)


def test_a_document_names_no_risk_of_another_unit(web):
    world = web.world
    _erm(world)
    text = " ".join(_pages(web("/erm/api/board-report/document", name="owner_b").content)).replace("\n", " ")
    assert "ERM risk A" not in text and "Risk B" in text
    text_a = " ".join(_pages(web("/erm/api/board-report/document", name="owner_a").content)).replace("\n", " ")
    assert "ERM risk A" in text_a and "Risk B" not in text_a


# ── The AI narrative beside each document is checked against the figures ──────

def test_each_ai_board_narrative_comes_back_with_a_check_of_its_figures(web, monkeypatch):
    """The panels showed a model's text as it came. Every figure in it is now looked up among the figures of the data, and the
    answer travels with it: a draft that states a number the data does not hold says so."""
    import modules.bcm.ai_service as bcm_ai
    for module in (erm_routes, orm_routes):
        monkeypatch.setattr(module, "check_ai_rate_limit", lambda uid: True, raising=False)
        monkeypatch.setattr(module, "record_ai_call", lambda uid: None, raising=False)
    monkeypatch.setattr(bcm_routes, "check_ai_rate_limit", lambda uid: True)
    monkeypatch.setattr(bcm_routes, "record_ai_call", lambda uid: None)

    honest = {"/erm/api/ai/board-report": ("owner_a", erm_routes.ai, "generate_board_narrative",
                                           lambda stats, appetite: f"There are {stats['total_risks']} open risks."),
              "/orm/api/ai/board-report": ("owner_a", orm_routes.ai, "generate_trend_narrative",
                                           lambda stats: f"{stats['total_events']} events in {stats['period_days']} days."),
              "/bcm/api/reports/board": ("super", bcm_ai, "generate_board_narrative", lambda stats: f"{stats['plans']} plans are recorded.")}
    for path, (persona, target, name, fake) in honest.items():
        monkeypatch.setattr(target, name, fake)
        answer = web.post(path, name=persona)
        assert answer.status_code == 200, path
        body = answer.json()
        assert body["narrative_grounded"] is True and "found in the data" in body["narrative_check"], path

    invented = {"/erm/api/ai/board-report": (erm_routes.ai, "generate_board_narrative", lambda stats, appetite: "Exposure is 987654 risks."),
                "/orm/api/ai/board-report": (orm_routes.ai, "generate_trend_narrative", lambda stats: "Losses reached 987654 dollars."),
                "/bcm/api/reports/board": (bcm_ai, "generate_board_narrative", lambda stats: "There are 987654 plans.")}
    for path, (target, name, fake) in invented.items():
        monkeypatch.setattr(target, name, fake)
        body = web.post(path, name="super").json()
        assert body["narrative_grounded"] is False and "987654" in body["narrative_check"], path
        assert body["narrative"] and "stats" in body, "the draft itself is still returned; the page shows the check beside it"
