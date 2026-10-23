"""Scoped, source-backed summaries shared by specialist module home pages."""
from __future__ import annotations

import logging

from core.rbac import has_capability, user_modules
from database import get_db, sql_date_ts
from modules.launcher.my_work_service import get_my_work
from modules.launcher.scoped_metrics import scoped_count

log = logging.getLogger("oneforall.module_home")

# Only identifiers in this static registry enter SQL. Quality is a data hygiene
# measure, not a claim that a control or plan is compliant or effective.
MODULES = {
    "aria": ("controls", "last_updated", "owner IS NOT NULL AND owner != ''", "Controls with an owner"),
    "grid": ("grid_audits", "created_at", "lead_id IS NOT NULL", "Audits with a lead"),
    "bcm": ("bcm_plans", "created_at", "owner IS NOT NULL AND owner != ''", "Plans with an owner"),
    "sentinel": ("sentinel_breaches", "created_at", "discovery_date IS NOT NULL", "Breaches with discovery recorded"),
    "erm": ("erm_enterprise_risks", "created_at", "owner_id IS NOT NULL", "Risks with an owner"),
    "orm": ("orm_events", "created_at", "owner_id IS NOT NULL", "Events with an owner"),
}

WORK_SOURCES = {
    "aria": frozenset({"aria_approvals"}),
    "grid": frozenset({"grid_non_conformances"}),
    "bcm": frozenset({"bcm_incidents"}),
    "sentinel": frozenset({"privacy_deadlines"}),
    "erm": frozenset({"erm_reviews", "erm_acceptances", "erm_scenarios"}),
    "orm": frozenset({"orm_reviews"}),
}


def _card(key, label, *, state="unavailable", value=None, note="", denominator=None):
    return {"key": key, "label": label, "state": state, "value": value,
            "note": note, "denominator": denominator}


def build(module: str, user: dict) -> dict:
    if module not in MODULES or not has_capability(user, f"module.{module}.access") or module not in user_modules(user):
        raise LookupError("Module not found")
    table, date_column, quality_where, quality_label = MODULES[module]
    cards = {
        "act_now": _card("act_now", "Act now", note="My Work actions for this module"),
        "portfolio": _card("portfolio", "Portfolio", note=f"Visible records in {table}"),
        "trends": _card("trends", "Trends", note="Records added or updated in the last 30 days"),
        "quality": _card("quality", "Coverage / quality", note=quality_label),
    }
    try:
        work = get_my_work(user, source=module, page_size=1,
                           only_sources=WORK_SOURCES[module])
        sources = [entry for entry in work["source_states"] if entry.get("state") in ("degraded", "scope_limited")]
        counts = work["counts"]
        cards["act_now"] = _card("act_now", "Act now", state="partial" if sources else "measured",
            value=sum(counts.get(section, 0) for section in ("needs_my_action", "due_soon", "overdue")),
            note="My Work actions requiring attention. Source failures or limited scope are disclosed." if sources
                 else "My Work actions requiring attention.")
    except Exception:
        log.exception("Module home work projection unavailable for %s", module)
    db = get_db()
    try:
        try:
            total = scoped_count(db, user, table)
            cards["portfolio"] = _card("portfolio", "Portfolio", state="measured", value=total,
                note=f"Visible {table.replace('_', ' ')} records")
        except Exception:
            db.rollback()
            log.exception("Module home portfolio unavailable for %s", module)
            total = None
        try:
            recent = scoped_count(db, user, table, f"{date_column} >= {sql_date_ts('-30 days')}")
            prior = scoped_count(db, user, table,
                                 f"{date_column} >= {sql_date_ts('-60 days')} AND "
                                 f"{date_column} < {sql_date_ts('-30 days')}")
            cards["trends"] = _card("trends", "Trends", state="measured", value=recent,
                denominator=prior, note=("Updated" if module == "aria" else "Created") +
                " in last 30 days; comparison is the preceding 30 days")
        except Exception:
            db.rollback()
            log.exception("Module home trend unavailable for %s", module)
        if total is not None:
            try:
                assigned = scoped_count(db, user, table, quality_where)
                cards["quality"] = _card("quality", "Coverage / quality",
                    state="measured" if total else "not_measured", value=assigned if total else None,
                    denominator=total, note=quality_label + ". This is data completeness, not assurance.")
            except Exception:
                db.rollback()
                log.exception("Module home quality unavailable for %s", module)
    finally:
        db.close()
    return {"module": module, "cards": cards, "source": "live scoped records"}
