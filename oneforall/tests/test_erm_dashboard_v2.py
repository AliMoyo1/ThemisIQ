"""
Tests for PLAN-26: ERM Dashboard v2.

Covers the risk posture block (IRR/RRR/LoA/LoR averages, EMV totals,
control effectiveness, high-RRR watchlist, trajectory), the posture filter
plumbing, and the decided appetite-vs-residual-exposure semantics change.

Uses the standard conftest test_db fixture (fresh SQLite per test).
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _create_control(db, title="Test Control"):
    db.execute(
        "INSERT INTO canonical_controls (title, automation) VALUES (%s, 'manual')",
        (title,),
    )
    db.commit()
    row = db.execute(
        "SELECT id FROM canonical_controls WHERE title=%s ORDER BY id DESC LIMIT 1",
        (title,),
    ).fetchone()
    return row["id"]


def test_high_rrr_watchlist_and_averages(test_db):
    """3 risks: one at RRR >= 15 (L5xI5 with a single ICE-30 control gives
    RRR 17.5), two unassessed and below threshold. posture.high_rrr contains
    exactly the first; averages match hand-computed values."""
    from modules.erm.data_service import (
        create_enterprise_risk, link_risk_control, set_control_assessment,
        get_dashboard_stats,
    )

    rid_a = create_enterprise_risk({
        "title": "High RRR Risk", "likelihood": 5, "impact": 5, "emv_inherent": 100000,
    })
    ctrl = _create_control(test_db, "Weak Control")
    link_risk_control(rid_a, ctrl, 1)
    set_control_assessment(rid_a, ctrl, 30, None)

    create_enterprise_risk({"title": "Low Risk B", "likelihood": 2, "impact": 2, "emv_inherent": 50000})
    create_enterprise_risk({"title": "Low Risk C", "likelihood": 3, "impact": 3, "emv_inherent": 30000})

    posture = get_dashboard_stats()["posture"]

    assert len(posture["high_rrr"]) == 1
    assert posture["high_rrr"][0]["id"] == rid_a
    assert posture["high_rrr"][0]["rrr"] == 17.5

    assert posture["avg_irr"] == round((25 + 4 + 9) / 3, 1)
    assert posture["avg_rrr"] == round((17.5 + 4 + 9) / 3, 1)
    assert posture["avg_loa"] == round((30 + 0 + 0) / 3, 1)
    assert posture["avg_lor"] == round(100 - posture["avg_loa"], 1)
    assert posture["emv_i_total"] == 180000
    assert posture["emv_r_total"] == 150000
    assert posture["control_effectiveness"] == 30.0


def test_category_filter_narrows_posture(test_db):
    """A category filter narrows averages to just the matching risk(s); a
    category with no matching risks returns None averages and an empty
    high_rrr list (never a misleading 0)."""
    from modules.erm.data_service import create_enterprise_risk, get_dashboard_stats

    create_enterprise_risk({"title": "Tech Risk", "likelihood": 4, "impact": 4, "category": "Technology Risk"})
    create_enterprise_risk({"title": "Strategic Risk", "likelihood": 2, "impact": 2, "category": "Strategic Risk"})

    posture = get_dashboard_stats({"category": "Technology Risk"})["posture"]
    assert posture["avg_irr"] == 16.0

    posture2 = get_dashboard_stats({"category": "Environmental Risk"})["posture"]
    assert posture2["avg_irr"] is None
    assert posture2["avg_rrr"] is None
    assert posture2["high_rrr"] == []


def test_trajectory_buckets_by_month(test_db):
    """Score-history rows inserted across 3 synthetic months bucket
    correctly in ascending order with correct per-bucket means."""
    from modules.erm.data_service import create_enterprise_risk, get_dashboard_stats

    rid = create_enterprise_risk({"title": "Trajectory Risk", "likelihood": 3, "impact": 3})
    # Wipe the creation-time history row so only the synthetic rows count.
    test_db.execute("DELETE FROM erm_risk_score_history WHERE risk_id=%s", (rid,))
    test_db.commit()

    rows = [
        ("2026-01-15 00:00:00", 20, 25),
        ("2026-01-20 00:00:00", 22, 25),
        ("2026-02-10 00:00:00", 15, 25),
        ("2026-03-05 00:00:00", 10, 25),
    ]
    for recorded_at, rrr, irr in rows:
        test_db.execute(
            "INSERT INTO erm_risk_score_history (risk_id, irr, rrr, recorded_at) VALUES (%s,%s,%s,%s)",
            (rid, irr, rrr, recorded_at),
        )
    test_db.commit()

    traj = get_dashboard_stats()["posture"]["trajectory"]
    assert [b["month"] for b in traj] == ["2026-01", "2026-02", "2026-03"]
    assert traj[0]["avg_rrr"] == 21.0
    assert traj[1]["avg_rrr"] == 15.0
    assert traj[2]["avg_rrr"] == 10.0
    assert traj[0]["avg_irr"] == 25.0


def test_empty_db_posture_is_safe(test_db):
    """With zero risks, every posture value is None or an empty list -- no
    exception, and never a misleading 0."""
    from modules.erm.data_service import get_dashboard_stats

    posture = get_dashboard_stats()["posture"]
    for key in ("avg_irr", "avg_rrr", "avg_loa", "avg_lor", "emv_i_total",
                "emv_r_total", "emv_a_total", "control_effectiveness"):
        assert posture[key] is None
    assert posture["high_rrr"] == []
    assert posture["trajectory"] == []


def test_existing_payload_keys_unchanged(test_db):
    """The pre-PLAN-26 payload keys are all still present for a no-filter
    call (regression guard for the old dashboard cards). appetite_breaches
    VALUE semantics are tested separately in test 6; here only key
    presence and the trivially-obvious totals are asserted."""
    from modules.erm.data_service import create_enterprise_risk, get_dashboard_stats

    create_enterprise_risk({"title": "Regression Risk", "likelihood": 3, "impact": 3})
    stats = get_dashboard_stats()

    for key in ("total_enterprise_risks", "total_register_risks", "total_risks",
                "critical", "high", "appetite_breaches", "overdue_obligations",
                "open_assessments", "board_visible", "trend_total",
                "trend_critical", "top_critical_risks", "actions_required",
                "posture"):
        assert key in stats
    assert stats["total_enterprise_risks"] == 1
    assert stats["total_risks"] == 1


def test_appetite_residual_exposure_semantics(test_db):
    """Appetite compares residual exposure (COALESCE(rrr, likelihood*impact)),
    not raw inherent. An unassessed risk breaches identically to the old
    inherent-only math; scoring its controls can clear the breach; another
    unassessed risk in the same category can still breach on its own. The
    event-handler's own query is exercised directly, not just re-derived."""
    from modules.erm.data_service import (
        create_enterprise_risk, link_risk_control, set_control_assessment,
        upsert_appetite, get_dashboard_stats, get_appetite_status,
    )
    from core.event_handlers import _check_and_emit_appetite_breach
    from database import get_db

    upsert_appetite({"category": "Strategic Risk", "max_score": 12, "appetite_level": "low"})

    rid_a = create_enterprise_risk({
        "title": "Risk A", "likelihood": 5, "impact": 5, "category": "Strategic Risk",
    })
    # Unassessed: rrr defaults to irr_score (25) -> breaches exactly like the
    # old inherent-only math (25 > 12).
    stats = get_dashboard_stats()
    assert stats["appetite_breaches"] >= 1
    status = get_appetite_status()
    strategic = next(a for a in status if a["category"] == "Strategic Risk")
    assert strategic["breached"] is True
    assert strategic["current_max_score"] == 25

    # Score risk A's control at ICE 70 -> rrr 7.5 -> breach clears.
    ctrl = _create_control(test_db, "Strong Control")
    link_risk_control(rid_a, ctrl, 1)
    set_control_assessment(rid_a, ctrl, 70, None)
    status = get_appetite_status()
    strategic = next(a for a in status if a["category"] == "Strategic Risk")
    assert strategic["breached"] is False
    assert strategic["current_max_score"] == 7.5

    # Risk B, unassessed, L4xI4 -> rrr defaults to 16 -> still breaches.
    create_enterprise_risk({"title": "Risk B", "likelihood": 4, "impact": 4, "category": "Strategic Risk"})
    status = get_appetite_status()
    strategic = next(a for a in status if a["category"] == "Strategic Risk")
    assert strategic["breached"] is True
    assert strategic["current_max_score"] == 16

    # Event-handler path: call the real function (must run cleanly against
    # the new COALESCE SQL) and confirm the same residual-exposure value.
    db = get_db()
    try:
        _check_and_emit_appetite_breach(db, "Strategic Risk")
        row = db.execute(
            "SELECT MAX(COALESCE(rrr, likelihood * impact)) AS max_score FROM erm_enterprise_risks "
            "WHERE category=%s AND status NOT IN ('closed','accepted')",
            ("Strategic Risk",),
        ).fetchone()
        assert row["max_score"] == 16
    finally:
        db.close()
