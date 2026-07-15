"""
Control Effectiveness Engine (T1.3).

Computes a 0-100 score for each canonical control from 7 binary factors.
All DB writes are to control_effectiveness_scores (UPSERT) and
canonical_controls.last_scored_at.

Weights:
  evidence_uploaded   20
  evidence_valid      15
  audit_passed        20
  tested_recently     15
  owner_reviewed      10
  automated           10
  no_recent_incidents 10
  Total              100
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

log = logging.getLogger("governance.effectiveness")

_WEIGHTS = {
    "evidence_uploaded":    20,
    "evidence_valid":       15,
    "audit_passed":         20,
    "tested_recently":      15,
    "owner_reviewed":       10,
    "automated":            10,
    "no_recent_incidents":  10,
}


def _score_one_control(db, cid: int) -> dict:
    """
    Evaluate all 7 factors for canonical control `cid` against the open `db`.
    Returns a dict with keys matching _WEIGHTS plus "score" (0-100).
    Callers must commit; this function never commits.
    """
    factors: dict[str, int] = {k: 0 for k in _WEIGHTS}

    try:
        now = datetime.utcnow()
        today_str = now.strftime("%Y-%m-%d")
        cutoff_7d = (now + timedelta(days=7)).strftime("%Y-%m-%d")
        cutoff_90d = (now - timedelta(days=90)).strftime("%Y-%m-%d")
        cutoff_365d = (now - timedelta(days=365)).strftime("%Y-%m-%d")

        ctrl = db.execute(
            "SELECT owner_user_id, automation, test_frequency_days, last_tested_at "
            "FROM canonical_controls WHERE id=%s",
            (cid,),
        ).fetchone()
        if not ctrl:
            return {**factors, "score": 0}

        # Factor 1 — evidence_uploaded (20)
        try:
            ev_count = db.execute(
                "SELECT COUNT(*) FROM evidence_links el "
                "JOIN evidence_items ei ON ei.id = el.evidence_id "
                "WHERE el.entity_type = 'canonical_control' AND el.entity_id = %s "
                "AND ei.status = 'current' "
                "AND (ei.expiry_date IS NULL OR ei.expiry_date > %s)",
                (cid, today_str),
            ).fetchone()[0]
            factors["evidence_uploaded"] = 1 if ev_count > 0 else 0
        except Exception:
            pass

        # Factor 2 — evidence_valid (15): no linked evidence expiring within 7 days
        if factors["evidence_uploaded"]:
            try:
                expiring_soon = db.execute(
                    "SELECT COUNT(*) FROM evidence_links el "
                    "JOIN evidence_items ei ON ei.id = el.evidence_id "
                    "WHERE el.entity_type = 'canonical_control' AND el.entity_id = %s "
                    "AND ei.status = 'current' "
                    "AND ei.expiry_date IS NOT NULL AND ei.expiry_date <= %s",
                    (cid, cutoff_7d),
                ).fetchone()[0]
                factors["evidence_valid"] = 1 if expiring_soon == 0 else 0
            except Exception:
                pass

        # Factor 3 — audit_passed (20): completed grid_audit within last 365 days
        try:
            audit_count = db.execute(
                "SELECT COUNT(*) FROM grid_controls gc "
                "JOIN grid_audits ga ON ga.id = gc.audit_id "
                "WHERE gc.canonical_control_id = %s "
                "AND ga.status = 'completed' "
                "AND ga.end_date >= %s",
                (cid, cutoff_365d),
            ).fetchone()[0]
            factors["audit_passed"] = 1 if audit_count > 0 else 0
        except Exception:
            pass

        # Factor 4 — tested_recently (15): last_tested_at within test_frequency_days
        try:
            last_tested = ctrl["last_tested_at"]
            freq_days = ctrl["test_frequency_days"] or 90
            if last_tested:
                last_dt = datetime.strptime(last_tested[:10], "%Y-%m-%d")
                age = (now - last_dt).days
                factors["tested_recently"] = 1 if age <= freq_days else 0
        except Exception:
            pass

        # Factor 5 — owner_reviewed (10): owner_user_id is set
        factors["owner_reviewed"] = 1 if ctrl["owner_user_id"] else 0

        # Factor 6 — automated (10): automation is not 'manual' and not NULL
        automation = ctrl["automation"] or ""
        factors["automated"] = 1 if (automation and automation.lower() != "manual") else 0

        # Factor 7 — no_recent_incidents (10): no high/critical orm_events in last 90 days
        try:
            incident_count = db.execute(
                "SELECT COUNT(*) FROM orm_events oe "
                "JOIN risk_controls rc ON rc.risk_id = oe.erm_risk_id "
                "WHERE rc.control_id = %s "
                "AND oe.severity IN ('high', 'critical') "
                "AND oe.created_at >= %s "
                "AND oe.status NOT IN ('resolved', 'closed')",
                (cid, cutoff_90d),
            ).fetchone()[0]
            factors["no_recent_incidents"] = 1 if incident_count == 0 else 0
        except Exception:
            factors["no_recent_incidents"] = 1  # no incidents found = pass

    except Exception as exc:
        log.warning("_score_one_control(%s) outer error: %s", cid, exc)

    score = sum(_WEIGHTS[k] * v for k, v in factors.items())
    return {**factors, "score": score}


def recompute_control(db, cid: int) -> int:
    """
    Score one control and persist the result.
    Returns the computed score.
    Callers must commit.
    """
    result = _score_one_control(db, cid)
    scored_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        db.execute(
            "INSERT INTO control_effectiveness_scores "
            "(control_id, score, evidence_uploaded, evidence_valid, audit_passed, "
            "tested_recently, owner_reviewed, automated, no_recent_incidents, scored_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(control_id) DO UPDATE SET "
            "score=%s, evidence_uploaded=%s, evidence_valid=%s, audit_passed=%s, "
            "tested_recently=%s, owner_reviewed=%s, automated=%s, "
            "no_recent_incidents=%s, scored_at=%s",
            (cid, result["score"],
             result["evidence_uploaded"], result["evidence_valid"],
             result["audit_passed"], result["tested_recently"],
             result["owner_reviewed"], result["automated"],
             result["no_recent_incidents"], scored_at,
             result["score"],
             result["evidence_uploaded"], result["evidence_valid"],
             result["audit_passed"], result["tested_recently"],
             result["owner_reviewed"], result["automated"],
             result["no_recent_incidents"], scored_at),
        )
    except Exception:
        # Fallback for SQLite (no ON CONFLICT DO UPDATE without UPSERT syntax support)
        try:
            db.execute(
                "INSERT OR REPLACE INTO control_effectiveness_scores "
                "(control_id, score, evidence_uploaded, evidence_valid, audit_passed, "
                "tested_recently, owner_reviewed, automated, no_recent_incidents, scored_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (cid, result["score"],
                 result["evidence_uploaded"], result["evidence_valid"],
                 result["audit_passed"], result["tested_recently"],
                 result["owner_reviewed"], result["automated"],
                 result["no_recent_incidents"], scored_at),
            )
        except Exception as exc2:
            log.warning("recompute_control(%s) upsert failed: %s", cid, exc2)

    try:
        db.execute(
            "UPDATE canonical_controls SET last_scored_at=%s WHERE id=%s",
            (scored_at, cid),
        )
    except Exception as exc:
        log.warning("recompute_control(%s) timestamp update failed: %s", cid, exc)

    return result["score"]


def recompute_controls_by_ids(db, control_ids: list[int]) -> int:
    """Recompute a specific set of controls. Returns count of controls scored."""
    count = 0
    for cid in control_ids:
        try:
            recompute_control(db, cid)
            count += 1
        except Exception as exc:
            log.warning("recompute_controls_by_ids: failed for control %s: %s", cid, exc)
    return count


def recompute_all_controls(db) -> int:
    """Recompute scores for every active canonical control. Returns count scored."""
    try:
        rows = db.execute(
            "SELECT id FROM canonical_controls WHERE is_active=1"
        ).fetchall()
    except Exception as exc:
        log.warning("recompute_all_controls: cannot fetch controls: %s", exc)
        return 0

    control_ids = [r[0] for r in rows]
    count = recompute_controls_by_ids(db, control_ids)
    log.info("recompute_all_controls: scored %d controls", count)
    return count


def get_control_score(db, cid: int) -> dict | None:
    """Fetch the latest stored score for a control. Returns None if not yet scored."""
    try:
        row = db.execute(
            "SELECT * FROM control_effectiveness_scores WHERE control_id=%s", (cid,)
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None
