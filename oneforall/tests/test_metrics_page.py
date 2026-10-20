"""
The metric definitions page lists only the figures of modules the person may open, with their full definition
(plans/2026-10-governance-rework/04 section 2: every number has a stable key and a plain-language definition).
"""
from core import metric_registry as registry
from modules.launcher import routes_dashboard as dash
from tests.test_platform_ownership import _call, _request, signed_in, world  # noqa: F401


def _keys(user):
    status, body = _call(dash.api_metric_definitions(_request(user)))
    assert status == 200
    return {d["key"]: d for d in body["definitions"]}


def test_every_definition_carries_what_a_reader_needs(world):
    got = _keys(world.users["super"])
    assert got, "the registry is not empty"
    for key, d in got.items():
        for field in ("label", "definition", "eligibility", "window", "scope", "refresh", "exclusions", "owner"):
            assert d[field], (key, field)
        assert d["key"] == key
    assert got["sentinel.ropa_coverage"]["denominator"]
    assert got["cc.sla_on_time"]["exclusions"].startswith("Active clocks")


def test_a_module_the_person_may_not_open_is_not_announced(world):
    employee = _keys(world.users["employee_a"])
    dpo = _keys(world.users["dpo_a"])
    assert not any(k.startswith("sentinel.") for k in employee), "an employee may not open Privacy"
    assert any(k.startswith("bcm.") for k in employee), "its positive twin: an employee may open Business continuity"
    assert any(k.startswith("sentinel.") for k in dpo) and not any(k.startswith("bcm.") for k in dpo)
    assert any(k.startswith("cc.") for k in employee), "the platform's own figures are for everyone"
    assert set(employee) < set(registry.REGISTRY)


def test_the_page_renders(world):
    from modules.launcher import routes_dashboard
    assert routes_dashboard.metrics_page is not None
