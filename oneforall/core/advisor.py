"""
Governance Advisory Engine — signal collection + briefing composition.

Signals are collected from existing platform data (risk predictions, evidence
expiry, overdue audits, appetite breaches, BCM staleness, open NCs). The
compose_briefing() function ranks them and inserts the top 3 into
governance_advisories.  Designed to be called by a daily scheduler and
also on-demand from the dashboard.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# ── Score mapping ────────────────────────────────────────────────────────────
_SCORE = {"high": 3, "medium": 2, "info": 1}


# ── Signal collectors ────────────────────────────────────────────────────────

def _signal_predictive_delta(db) -> dict | None:
    """Risk prediction score change ≥ 5 points → high severity."""
    try:
        rows = db.execute(
            "SELECT delta_p, computed_at FROM ai_risk_predictions "
            "ORDER BY id DESC LIMIT 2"
        ).fetchall()
        if len(rows) < 2:
            return None
        latest = float(rows[0]["delta_p"] or 0)
        previous = float(rows[1]["delta_p"] or 0)
        delta = round(abs(latest - previous), 1)
        if delta < 5:
            return None
        direction = "increased" if latest > previous else "decreased"
        return {
            "signal_key": "predictive_delta",
            "severity": "high",
            "title": f"Risk score {direction} by {delta} points",
            "detail": (
                f"AI predictive risk score changed from {previous} to {latest} "
                f"(Δ={delta}). Computed at {rows[0]['computed_at']}."
            ),
            "link": "/erm/",
            "score": _SCORE["high"],
        }
    except Exception:
        log.warning("Signal 'predictive_delta' failed silently", exc_info=True)
        return None


def _signal_evidence_expiring(db) -> dict | None:
    """Evidence items expiring within 7 days → medium severity."""
    try:
        row = db.execute(
            "SELECT COUNT(*) AS cnt FROM evidence_items "
            "WHERE expiry_date BETWEEN date('now') AND date('now', '+7 days') "
            "  AND status = 'current'"
        ).fetchone()
        count = row["cnt"] if row else 0
        if count == 0:
            return None
        return {
            "signal_key": "evidence_expiring",
            "severity": "medium",
            "title": f"{count} evidence item(s) expiring within 7 days",
            "detail": (
                f"{count} evidence item(s) have an expiry date in the next 7 days. "
                "Review and renew or archive to maintain compliance."
            ),
            "link": "/evidence/",
            "score": _SCORE["medium"],
        }
    except Exception:
        log.warning("Signal 'evidence_expiring' failed silently", exc_info=True)
        return None


def _signal_overdue_audits(db) -> dict | None:
    """Audits past their end_date and not closed → medium severity."""
    try:
        row = db.execute(
            "SELECT COUNT(*) AS cnt FROM grid_audits "
            "WHERE end_date < date('now') "
            "  AND status NOT IN ('completed', 'locked', 'cancelled')"
        ).fetchone()
        count = row["cnt"] if row else 0
        if count == 0:
            return None
        return {
            "signal_key": "overdue_audits",
            "severity": "medium",
            "title": f"{count} audit(s) past their end date",
            "detail": (
                f"{count} audit(s) are past their planned end date and still open. "
                "Review and close or extend their timeline."
            ),
            "link": "/grid/",
            "score": _SCORE["medium"],
        }
    except Exception:
        log.warning("Signal 'overdue_audits' failed silently", exc_info=True)
        return None


def _signal_appetite_breach(_db) -> dict | None:
    """Risk appetite breaches → high severity (uses ERM data service)."""
    try:
        from modules.erm.data_service import get_appetite_status

        status = get_appetite_status()
        count = sum(1 for item in status if item.get("breached"))
        if count == 0:
            return None
        return {
            "signal_key": "appetite_breach",
            "severity": "high",
            "title": f"{count} risk appetite threshold(s) breached",
            "detail": (
                f"{count} risk category(ies) have exceeded their defined "
                "appetite threshold. Review the risk register and consider "
                "mitigation."
            ),
            "link": "/erm/",
            "score": _SCORE["high"],
        }
    except ImportError:
        log.warning("Signal 'appetite_breach' skipped — ERM data service unavailable")
        return None
    except Exception:
        log.warning("Signal 'appetite_breach' failed silently", exc_info=True)
        return None


def _signal_bcm_stale(db) -> dict | None:
    """BCM exercises not tested in > 180 days → medium severity."""
    try:
        row = db.execute(
            "SELECT MAX(scheduled_date) AS max_date FROM bcm_exercises"
        ).fetchone()
        max_date = row["max_date"] if row else None
        if max_date is None:
            return {
                "signal_key": "bcm_stale",
                "severity": "medium",
                "title": "No BCM exercises recorded",
                "detail": (
                    "No business continuity exercises have been recorded. "
                    "Schedule a tabletop or drill exercise."
                ),
                "link": "/bcm/",
                "score": _SCORE["medium"],
            }
        # julianday is SQLite-specific; on PG this won't match but the scheduler
        # is a background job — if someone runs PG, this signal degrades gracefully
        # (the query returns None and we skip).
        row2 = db.execute(
            "SELECT (julianday('now') - julianday(%s)) AS days_since",
            (max_date,),
        ).fetchone()
        days = row2["days_since"] if row2 else None
        if days is None or days <= 180:
            return None
        return {
            "signal_key": "bcm_stale",
            "severity": "medium",
            "title": f"BCM exercises not tested in {int(days)} days",
            "detail": (
                f"The last BCM exercise was on {max_date} ({int(days)} days ago). "
                "Schedule a new exercise to maintain readiness."
            ),
            "link": "/bcm/",
            "score": _SCORE["medium"],
        }
    except Exception:
        log.warning("Signal 'bcm_stale' failed silently", exc_info=True)
        return None


def _signal_open_critical_ncs(db) -> dict | None:
    """Open critical/major non-conformances → high severity."""
    try:
        row = db.execute(
            "SELECT COUNT(*) AS cnt FROM grid_non_conformances "
            "WHERE severity IN ('critical', 'major') "
            "  AND status NOT IN ('closed', 'done')"
        ).fetchone()
        count = row["cnt"] if row else 0
        if count == 0:
            return None
        return {
            "signal_key": "open_critical_ncs",
            "severity": "high",
            "title": f"{count} open critical/major non-conformance(s)",
            "detail": (
                f"{count} non-conformance(s) with critical or major severity "
                "remain open. Prioritise corrective actions."
            ),
            "link": "/grid/",
            "score": _SCORE["high"],
        }
    except Exception:
        log.warning("Signal 'open_critical_ncs' failed silently", exc_info=True)
        return None


# ── Collector registry ───────────────────────────────────────────────────────

_SIGNAL_COLLECTORS = [
    _signal_predictive_delta,
    _signal_evidence_expiring,
    _signal_overdue_audits,
    _signal_appetite_breach,
    _signal_bcm_stale,
    _signal_open_critical_ncs,
]


# ── Public API ───────────────────────────────────────────────────────────────

def collect_signals(db) -> list[dict]:
    """Collect governance signals from existing data. Never raises.

    Each collector is wrapped in its own try/except so a single failing
    table or query never prevents the rest of the briefing from being
    composed.
    """
    signals: list[dict] = []
    for collector in _SIGNAL_COLLECTORS:
        try:
            result = collector(db)
            if result:
                signals.append(result)
        except Exception:
            # Already logged inside each collector; belt-and-suspenders.
            pass
    return signals


def compose_briefing(db, today: str) -> int:
    """Compose today's briefing. Returns number of advisories inserted.

    Idempotent — checks for an existing briefing before inserting.
    Returns 0 if no signals were found or the briefing was already composed.
    """
    # 1. Check if already composed
    try:
        existing = db.execute(
            "SELECT COUNT(*) FROM governance_advisories WHERE briefing_date=%s",
            (today,),
        ).fetchone()[0]
        if existing > 0:
            log.info("Briefing for %s already composed — skipping", today)
            return 0
    except Exception:
        log.exception("Failed to check existing briefing for %s", today)
        return 0

    # 2. Collect signals
    signals = collect_signals(db)
    if not signals:
        log.info("No signals for %s — skipping briefing", today)
        return 0

    # 3. Sort by score DESC, take top 3
    signals.sort(key=lambda s: s.get("score", 0), reverse=True)
    top = signals[:3]

    # 4. Optional AI narrative (attached only to first/highest-scored signal)
    ai_narrative = None
    try:
        from config import settings
        if getattr(settings, "ANTHROPIC_API_KEY", None):
            lines = "\n".join(
                f"- [{s['severity'].upper()}] {s['title']}: {s.get('detail', '')}"
                for s in top
            )
            text_for_ai = f"Today's governance briefing:\n{lines}"
            try:
                from core.ai_client import create_message
                ai_narrative = create_message(
                    messages=[{"role": "user", "content": text_for_ai}],
                    system=(
                        "Summarise these governance items in under 80 words. "
                        "Be direct and actionable."
                    ),
                    max_tokens=120,
                )
            except Exception:
                log.warning("AI narrative generation failed — continuing without it")
    except Exception:
        pass

    # 5. INSERT rows
    inserted = 0
    for idx, s in enumerate(top):
        try:
            db.execute(
                "INSERT OR IGNORE INTO governance_advisories "
                "(briefing_date, severity, signal_key, title, detail, link, ai_narrative) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    today,
                    s["severity"],
                    s["signal_key"],
                    s["title"],
                    s.get("detail"),
                    s.get("link"),
                    ai_narrative if idx == 0 else None,
                ),
            )
            inserted += 1
        except Exception:
            log.warning(
                "Failed to insert advisory for signal_key=%s", s.get("signal_key"),
                exc_info=True,
            )

    if inserted > 0:
        try:
            db.commit()
        except Exception:
            log.exception("Failed to commit briefing for %s", today)
            return 0

    log.info("Briefing for %s: %d advisory(ies) inserted", today, inserted)
    return inserted
