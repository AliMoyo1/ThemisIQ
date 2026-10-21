"""PLAN-36 P09: daily aggregate capability-state frequency, without user content."""
from datetime import timedelta
import logging

from core.timeutils import utcnow
from database import get_db

log = logging.getLogger("capability.metrics")
AREAS = frozenset({"ai", "aria-authoring", "aria-ai", "aria-conversion",
                   "erm-horizon-scan", "aria-export", "email",
                   "connector-slack", "connector-teams", "connector-whatsapp"})


def record_state(user: dict, area: str, state) -> None:
    """A failed metric must not change the truthfulness of the state response."""
    org_id = user.get("org_id")
    if not org_id or area not in AREAS:
        return
    db = None
    try:
        db = get_db()
        db.execute(
            "INSERT INTO capability_state_daily(day,org_id,area,state,count) "
            "VALUES (%s,%s,%s,%s,1) "
            "ON CONFLICT(day,org_id,area,state) DO UPDATE SET count=capability_state_daily.count+1",
            (utcnow().date().isoformat(), org_id, area, state.state),
        )
        db.commit()
    except Exception:
        if db:
            db.rollback()
        log.warning("Capability state metric could not be recorded", exc_info=True)
    finally:
        if db:
            db.close()


def frequency(days: int = 30) -> list[dict]:
    """Platform aggregate only; no IDs, input, or request metadata leave here."""
    cutoff = (utcnow().date() - timedelta(days=min(max(days, 1), 90))).isoformat()
    db = get_db()
    try:
        rows = db.execute(
            "SELECT day,area,state,SUM(count) AS count FROM capability_state_daily "
            "WHERE day>=%s GROUP BY day,area,state ORDER BY day DESC,area,state",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()
