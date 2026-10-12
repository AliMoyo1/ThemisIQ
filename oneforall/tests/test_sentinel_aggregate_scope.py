"""
Sentinel aggregates: what the numbers, the score and the cross-module breach banner say is about the records the caller
can open, not about the whole organization.

The record routes were scoped by business unit but the dashboard counts, the compliance score, the per jurisdiction
counts and the "active breach" banner that BCM and GRID show were not: a unit's officer was told how many critical
breaches the other units have, and was shown the title of the worst open one. Each persona's numbers must now agree
with the lists the same persona can open, and the worst open breach is the worst one in reach.
"""
import pytest

from core import rbac
from tests.test_platform_ownership import _insert, world  # noqa: F401
from tests.test_sentinel_write_scope import http  # noqa: F401

PAST, FUTURE = "2001-01-01", "2999-01-01"
BANNER_OFF = {"active": False, "id": None, "title": None, "severity": None}
SEEN = ("super", "dpo_a", "dpo_a1", "dpo_b", "dpo_no_unit")


def _file(world):
    """RoPA entries: A 1, A1 1, B 2, organization wide 1. DPIAs: A, B, org. DSRs: A (overdue), A1 (closed), B.
    Consent: A active, A1 withdrawn, B active, org active.
    Breaches: the fixture's four (A, A1, B, org); B's is critical and A1's is resolved."""
    db, unit = world.db, world.unit

    def ropa(tag, n, **cols):
        return _insert(db, "sentinel_ropa", ref_number=f"R-{tag}-{n}", processing_name=f"{tag} {n}",
                       business_unit_id=unit[tag], **cols)

    complete = {"purpose": "To pay staff", "legal_basis": "Contract", "data_categories": '["Payroll"]'}
    ropa("A", 1, regulation="GDPR", risk_level="high", dpia_required=1, **complete)
    ropa("A1", 1, regulation="GDPR", risk_level="low")
    ropa("B", 1, regulation="South Africa POPIA", risk_level="critical", dpia_required=1)
    ropa("B", 2, regulation="South Africa POPIA", risk_level="low", **complete)
    ropa("org", 1, regulation="GDPR", risk_level="medium")
    for tag, status in (("A", "draft"), ("B", "approved"), ("org", "draft")):
        _insert(db, "sentinel_dpias", ref_number=f"D-{tag}", title=f"DPIA {tag}", status=status,
                regulation="South Africa POPIA" if tag == "B" else "GDPR", business_unit_id=unit[tag])
    for tag, status, deadline in (("A", "open", PAST), ("A1", "closed", PAST), ("B", "open", FUTURE)):
        _insert(db, "sentinel_dsr", ref_number=f"S-{tag}", requester_name=f"Requester {tag}", status=status,
                deadline_date=deadline, business_unit_id=unit[tag])
    for tag, status in (("A", "active"), ("A1", "withdrawn"), ("B", "active"), ("org", "active")):
        _insert(db, "sentinel_consent", purpose=f"Newsletter {tag}", status=status, business_unit_id=unit[tag])
    db.execute("UPDATE sentinel_breaches SET severity = 'critical' WHERE id = %s", (world.rec[("breach", "B")],))
    db.execute("UPDATE sentinel_breaches SET status = 'resolved' WHERE id = %s", (world.rec[("breach", "A1")],))
    db.commit()


@pytest.mark.parametrize("persona, ropa_total, consent_active", [
    ("super", 5, 3), ("dpo_a", 3, 2), ("dpo_a1", 2, 1), ("dpo_b", 3, 2), ("dpo_no_unit", 1, 1)])
def test_the_dashboard_numbers_are_those_of_the_records_the_caller_can_open(http, persona, ropa_total, consent_active):
    _file(http.world)

    def get(path):
        answer = http("get", path, name=persona)
        assert answer.status_code == 200, path
        return answer.json()

    ropa, dpias = get("/sentinel/api/ropa"), get("/sentinel/api/dpias")
    breaches, dsrs = get("/sentinel/api/breaches"), get("/sentinel/api/dsrs")
    assert len(ropa) == ropa_total, "the lists themselves are what they were"

    stats = get("/sentinel/api/stats")
    assert stats["ropa_total"] == len(ropa)
    assert stats["dpia_total"] == len(dpias)
    assert stats["dpia_draft"] == sum(d["status"] == "draft" for d in dpias)
    assert stats["dpia_approved"] == sum(d["status"] == "approved" for d in dpias)
    assert stats["breach_open"] == sum(b["status"] == "open" for b in breaches)
    assert stats["breach_critical"] == sum(b["severity"] == "critical" for b in breaches)
    assert stats["dsr_open"] == sum(d["status"] == "open" for d in dsrs)
    assert stats["dsr_overdue"] == sum(d["status"] == "open" and d["deadline_date"] < "2026-01-01" for d in dsrs)
    assert stats["high_risk_ropa"] == sum(r["risk_level"] in ("high", "critical") for r in ropa)
    assert stats["dpia_required"] == sum(bool(r["dpia_required"]) for r in ropa)
    assert sum(stats["by_regulation"].values()) == len(ropa)
    assert sum(stats["risk_distribution"].values()) == len(ropa)
    consent = get("/sentinel/api/consent")
    assert stats["consent_active"] == consent_active == sum(c["status"] == "active" for c in consent)

    score = get("/sentinel/api/compliance-score")["breakdown"]
    assert score["ropa_completeness"]["total"] == len(ropa)
    assert score["ropa_completeness"]["done"] == sum(bool(r["purpose"] and r["legal_basis"] and r["data_categories"])
                                                     for r in ropa)
    assert score["dpia_coverage"]["total"] == sum(
        r["risk_level"] in ("high", "critical") or bool(r["dpia_required"]) for r in ropa)
    assert score["breach_response"]["total"] == len(breaches)
    assert score["dsr_closure"]["total"] == len(dsrs)

    per_regulation = get("/sentinel/api/jurisdiction-stats")["items"]
    assert sum(i["ropa"] for i in per_regulation) == len(ropa)
    assert sum(i["dpias"] for i in per_regulation) == len(dpias)
    assert sum(i["breaches"] for i in per_regulation) == len(breaches)
    assert sum(i["dsrs"] for i in per_regulation) == len(dsrs)


def test_a_single_jurisdiction_reports_only_what_the_caller_can_open(http):
    _file(http.world)  # GDPR RoPA entries: A, A1 and one organization wide; B's two are POPIA
    for persona, expected in (("super", 3), ("dpo_a", 3), ("dpo_a1", 2), ("dpo_b", 1), ("dpo_no_unit", 1)):
        answer = http("get", "/sentinel/api/jurisdictions/GDPR", name=persona)
        assert answer.status_code == 200, persona
        assert answer.json()["stats"]["ropa"] == expected, persona


def test_the_audit_pack_score_is_the_callers_too(http):
    import io
    import json
    import zipfile
    _file(http.world)
    pack = {}
    for persona in ("super", "dpo_b"):
        answer = http("get", "/sentinel/api/audit-export?type=compliance", name=persona)
        assert answer.status_code == 200, persona
        with zipfile.ZipFile(io.BytesIO(answer.content)) as zf:
            name = next(n for n in zf.namelist() if n.startswith("Compliance_Score"))
            pack[persona] = json.loads(zf.read(name))
    assert pack["super"]["breakdown"]["ropa_completeness"]["total"] == 5
    assert pack["dpo_b"]["breakdown"]["ropa_completeness"]["total"] == 3


def test_the_active_breach_banner_names_only_a_breach_the_caller_can_open(http):
    world = http.world
    for tag, severity in (("B", "critical"), ("A1", "high"), ("A", "low"), ("org", "medium")):
        world.db.execute("UPDATE sentinel_breaches SET severity = %s WHERE id = %s",
                         (severity, world.rec[("breach", tag)]))
    world.db.commit()
    worst_in_reach = {"super": "B", "dpo_b": "B", "dpo_a": "A1", "dpo_a1": "A1", "dpo_no_unit": "org"}
    for persona, tag in worst_in_reach.items():
        banner = http("get", "/sentinel/api/active-breach", name=persona).json()
        assert banner["active"] is True and banner["id"] == world.rec[("breach", tag)], persona
        assert banner["title"] == f"needle breach {tag}", persona
    # Nothing open in reach is not the same as nothing open anywhere.
    world.db.execute("UPDATE sentinel_breaches SET status = 'closed' WHERE id = %s", (world.rec[("breach", "org")],))
    world.db.commit()
    assert http("get", "/sentinel/api/active-breach", name="dpo_no_unit").json() == BANNER_OFF
    assert http("get", "/sentinel/api/active-breach", name="dpo_b").json()["id"] == world.rec[("breach", "B")]


@pytest.mark.parametrize("role, may_open", [
    (rbac.DPO, True), (rbac.PRIVACY_ANALYST, False), (rbac.COMPLIANCE_MGR, False), (rbac.GRC_OFFICER, False)])
def test_the_banner_names_the_breach_only_to_those_who_can_open_the_breach_list(http, role, may_open):
    """BCM and GRID show the banner to anyone with the Sentinel module, which several roles hold without
    sentinel.breach.manage. They are told a breach is active and how severe it is, not which one."""
    world = http.world
    world.users["reader"] = {"id": 77, "username": "reader", "org_id": 1, "business_unit_id": world.unit["A"],
                             "is_super_admin": 0, "roles": [role]}
    banner = http("get", "/sentinel/api/active-breach", name="reader").json()
    assert banner["active"] is True and banner["severity"] == "medium"
    assert (banner["id"] is not None) is may_open, banner
    assert (banner["title"] is not None) is may_open, banner
    listed = http("get", "/sentinel/api/breaches", name="reader")
    assert (listed.status_code == 200) is may_open, "the banner never shows more than the list would"
