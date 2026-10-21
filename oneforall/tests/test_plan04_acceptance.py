"""
Acceptance scenarios of plan 04 (plans/2026-10-governance-rework/04 section 9), one test each, written against the
behaviour a specialist sees rather than against the code that produces it.

The numbers are written by hand from the rows inserted here. Scenario 5's predictive half is not covered: a predictive
risk number still cannot be traced to its source records (see the ledger).
"""
import json
import pathlib
import re

import pytest

import modules.launcher.routes_platform as plat
import modules.launcher.routes_reports as reports
from core import ai_client, metric_registry as registry
from modules.governance import entity360
from modules.launcher import command_metrics, first_screen, report_builders
from modules.launcher.my_work_service import get_my_work
from modules.sentinel import dashboard_metrics as sentinel
from tests.test_platform_ownership import ORG, _call, _insert, _request, signed_in, world  # noqa: F401

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _quick(user, report_type, **extra):
    return _call(reports.api_report_quick_run(_request(user, payload={"report_type": report_type, **extra})))


def _open(user, run_id, **query):
    return _call(reports.api_report_run_get(_request(user, query), run_id))


@pytest.fixture
def severities(world):
    """Breach A critical, A1 high, B critical, organization wide low: unit A's DPO sees critical 1 and high 1."""
    for tag, severity in (("A", "critical"), ("A1", "high"), ("B", "critical"), ("org", "low")):
        world.db.execute("UPDATE sentinel_breaches SET severity = %s WHERE id = %s",
                         (severity, world.rec[("breach", tag)]))
    world.db.commit()
    return world


# ── 1. A board card to the same frozen numbers ──────────────────────────────

def test_1_a_card_a_list_an_export_and_the_same_numbers_later(severities):
    world = severities
    dpo = world.users["dpo_a"]
    card = command_metrics.build(world.db, dpo)["metrics"]["cc.open_breaches"]
    assert card["state"] == "measured" and card["value"] == 2
    assert card["definition"] and card["as_of"] and card["drilldown"] == "/sentinel/breaches"

    # the rows behind the card are the rows the module's own list gives this person
    from modules.governance.data_service import bu_scope_ids
    from modules.sentinel import data_service as ds
    listed = [b for b in ds.list_breaches(bu_scope=bu_scope_ids(dpo))
              if b["severity"] in ("critical", "high") and b["status"] not in ("closed", "resolved")]
    assert len(listed) == card["value"]

    status, run = _quick(dpo, "preset_board")
    assert status == 200 and run["frozen"] is True
    exported = reports.api_report_run_export(_request(dpo), run["run_id"])
    import asyncio
    response = asyncio.run(exported)
    assert response.status_code == 200 and b"breaches_open" in response.body
    before = run["result"]["sections"]["executive_brief"]["breaches_open"]

    world.db.execute("UPDATE sentinel_breaches SET status = 'closed' WHERE id = %s", (world.rec[("breach", "A")],))
    world.db.commit()
    again = _open(dpo, run["run_id"])[1]
    assert again["result"]["sections"]["executive_brief"]["breaches_open"] == before, "later, the same frozen figure"
    assert command_metrics.build(world.db, dpo)["metrics"]["cc.open_breaches"]["value"] == 1, "the live card moved"


def test_1_every_drilldown_the_registry_names_is_a_page_that_exists():
    inventory = json.loads((ROOT / "docs/generated/capability_inventory.json").read_text(encoding="utf-8"))
    patterns = [re.compile("^" + re.sub(r"\\{[^/]+\\}", "[^/]+", re.escape(e["path"].rstrip("/"))) + "$")
                for e in inventory["entries"] if "GET" in e["methods"]]
    for d in registry.REGISTRY.values():
        if d.drilldown:
            base = d.drilldown.split("?")[0].rstrip("/") or "/"
            assert any(p.match(base) for p in patterns) or base == "/", (d.key, d.drilldown)


# ── 2. A failed source is unavailable, never a sample ───────────────────────

def test_2_a_failed_privacy_source_blanks_privacy_only(severities, monkeypatch):
    world = severities
    dpo = world.users["dpo_a"]
    manager = {**world.users["dpo_a"], "roles": ["compliance_manager"]}

    def refuse(real):
        def reader(db, user, table, condition="", params=()):
            if table.startswith("sentinel_"):
                raise RuntimeError("privacy source down")
            return real(db, user, table, condition, params)
        return reader

    monkeypatch.setattr(command_metrics, "scoped_count", refuse(command_metrics.scoped_count))
    monkeypatch.setattr(sentinel, "scoped_count", refuse(sentinel.scoped_count))
    monkeypatch.setattr(report_builders, "scoped_count", refuse(report_builders.scoped_count))

    cc = command_metrics.build(world.db, dpo)["metrics"]
    assert cc["cc.open_breaches"]["state"] == "unavailable" and cc["cc.open_breaches"]["value"] is None
    assert cc["cc.active_frameworks"]["state"] in ("measured", "not_measured"), "another module still answers"

    privacy = sentinel.stats(dpo)["metrics"]
    assert privacy["sentinel.breaches_active"]["state"] == "unavailable"
    assert privacy["sentinel.breaches_active"]["value"] is None

    status, run = _quick(dpo, "privacy_overview")
    assert status == 200 and run["result"]["breaches_open"] is None and run["snapshot"]["complete"] is False
    assert _quick(manager, "audit_status")[0] == 200, "the audit report is unaffected"


def test_2_no_dashboard_template_carries_sample_data():
    samples = ["HQ Business Continuity Plan", "Data centre cooling failure", "DSR-2026-041", "CloudHost Ltd",
               "Sarah Chen", "James Wilson"]
    for path in ("templates/command_centre.html", "modules/bcm/templates/index.html",
                 "modules/sentinel/templates/index.html", "modules/launcher/templates/analytics.html"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert not re.search(r"\b(?:var|const|let)\s+fallback\s*=", text), path
        for sample in samples:
            assert sample not in text, (path, sample)


# ── 3. A report button is a saved run or it is absent ───────────────────────

def test_3_no_report_button_ends_in_a_timer_and_every_type_it_asks_for_is_registered():
    aria = (ROOT / "modules/aria/templates/dashboard.html").read_text(encoding="utf-8")
    assert "Report generated successfully" not in aria
    assert re.search(r"/api/reports/quick-run", aria)

    bcm = (ROOT / "modules/bcm/templates/index.html").read_text(encoding="utf-8")
    kinds = re.search(r"var kinds=\{([^}]*)\}", bcm).group(1)
    asked = set(re.findall(r"'(bcm_[a-z_]+)'", kinds)) | set(re.findall(r"bcmQuickReport\('([a-z_]+)'", bcm))
    assert asked and asked <= set(reports.REPORT_TYPES), asked - set(reports.REPORT_TYPES)
    for report_type in asked:
        assert report_type in report_builders.BUILDERS, f"{report_type} is registered but has no builder"

    command_centre = (ROOT / "templates/command_centre.html").read_text(encoding="utf-8")
    assert "report_type: 'executive_brief'" not in command_centre, "the board button uses the board preset"
    assert "preset_board" in command_centre


# ── 4. A wrong-unit person cannot infer a hidden record ─────────────────────

def test_4_unit_b_is_invisible_to_unit_a_on_every_derived_surface(severities):
    world = severities
    db, unit = world.db, world.unit
    dpo = world.users["dpo_a"]
    secret_task = _insert(db, "task_board", title="Unit B secret task", status="todo",
                          assigned_to=world.users["dpo_b"]["id"], created_by=world.users["dpo_b"]["id"],
                          business_unit_id=unit["B"], due_date="2020-01-01")
    proc = _insert(db, "business_processes", name="Shared process", business_unit_id=unit["A"], is_active=1)
    ropa_b = _insert(db, "sentinel_ropa", ref_number="RP-SECRET", processing_name="Needle secret ropa B",
                     business_unit_id=unit["B"])
    _insert(db, "cross_module_links", source_module="sentinel", source_type="ropa", source_id=ropa_b,
            target_module="governance", target_type="process", target_id=proc, relationship="supports",
            provenance="manual", status="confirmed")
    breach_b = world.rec[("breach", "B")]
    hidden = ["Unit B secret task", "Needle secret ropa B", "needle breach B", "RP-SECRET", f"BR-B"]

    surfaces = {}
    surfaces["search"] = _call(plat.api_global_search(_request(dpo, {"q": "needle"})))[1]
    surfaces["case"] = _call(plat.api_global_search(_request(dpo, {"q": "secret", "case": f"governance:process:{proc}"})))
    surfaces["connected"] = entity360.get_connected(db, dpo, "governance", "process", proc)
    surfaces["my_work"] = get_my_work(dpo)
    surfaces["first_screen"] = first_screen.build(db, dpo)
    surfaces["metrics"] = command_metrics.build(db, dpo)
    surfaces["report"] = _quick(dpo, "privacy_overview")[1]
    surfaces["board"] = _quick(dpo, "preset_board")[1]
    for name, payload in surfaces.items():
        text = json.dumps(payload, default=str)
        for word in hidden:
            assert word not in text, (name, word)

    run = surfaces["report"]
    ids = _open(dpo, run["run_id"], records="1")[1]["snapshot"]["inputs"]["sentinel_breaches"]["ids"]
    assert breach_b not in ids and len(ids) == 3, "the read rows are unit A, A1 and the organization wide breach"
    assert run["result"]["breaches_open"] == 3, "not four: the count follows the rows"

    # its positive twin: the unit that owns the rows sees them
    dpo_b = world.users["dpo_b"]
    seen = json.dumps(_call(plat.api_global_search(_request(dpo_b, {"q": "needle"})))[1])
    assert "needle breach B" in seen and "Needle secret ropa B" in seen


# ── 5. A figure can be traced and disputed without editing it ───────────────

def test_5_a_figure_is_traced_to_its_rows_and_disputed_beside_it(severities):
    world = severities
    dpo = world.users["dpo_a"]
    status, run = _quick(dpo, "privacy_overview")
    snap = run["snapshot"]
    # traced: the definition, the rule, the period and freshness, and the identifiers of the rows
    assert snap["run"]["definition_version"] and snap["period"]["as_of"] and snap["sources"]
    assert registry.get("sentinel.breaches_active").eligibility
    assert snap["inputs"]["sentinel_breaches"]["count"] == 3

    note = _call(reports.api_report_run_note(_request(dpo, payload={
        "kind": "dispute", "figure": "breaches_open", "body": "Breach A was closed on paper last week."}), run["run_id"]))
    assert note[0] == 201 and note[1]["figure"] == "breaches_open"
    reopened = _open(dpo, run["run_id"])[1]
    assert reopened["result"]["breaches_open"] == run["result"]["breaches_open"], "the figure was not edited"
    assert reopened["hash"] == run["hash"]
    assert [(n["kind"], n["figure"]) for n in reopened["notes"]] == [("dispute", "breaches_open")]
    assert "breaches_open" in reopened["figures"]
    # the source was not touched, and a figure that is not in the run cannot be disputed
    assert world.db.execute("SELECT status FROM sentinel_breaches WHERE id = %s",
                            (world.rec[("breach", "A")],)).fetchone()[0] == "open"
    assert _call(reports.api_report_run_note(_request(dpo, payload={
        "kind": "dispute", "figure": "no_such_figure", "body": "x"}), run["run_id"]))[0] == 400
    assert _call(reports.api_report_run_note(_request(world.users["dpo_b"], payload={
        "kind": "note", "body": "x"}), run["run_id"]))[0] == 404, "only the person it was made for"


# ── 6. With AI off, the work is still possible ──────────────────────────────

def test_6_with_ai_off_a_specialist_can_find_review_and_report(severities, monkeypatch):
    world = severities
    monkeypatch.setattr(ai_client, "is_configured", lambda: False)
    dpo = world.users["dpo_a"]
    proc = _insert(world.db, "business_processes", name="Payroll", business_unit_id=world.unit["A"], is_active=1)

    assert _call(plat.api_global_search(_request(dpo, {"q": "needle breach"})))[1]["results"], "find"
    assert entity360.get_connected(world.db, dpo, "governance", "process", proc)["entity"]["title"] == "Payroll", "review"
    assert get_my_work(dpo)["counts"] is not None
    for report_type in ("compliance_summary", "risk_report", "audit_status", "privacy_overview", "executive_brief",
                        "preset_board", "preset_management", "preset_specialist"):
        status, run = _quick(dpo, report_type)
        assert status == 200 and run["frozen"] is True, report_type
    status, body = _call(reports.api_executive_summary(_request(dpo)))
    assert status == 200 and body["frozen"] is True and body["narrative"] is None
    assert body["stats"]["breaches_open"] == 3, "the figures are complete without the assistant"
