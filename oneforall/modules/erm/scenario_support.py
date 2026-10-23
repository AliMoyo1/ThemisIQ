"""Scenario Studio helpers that sit around the impact engine (modules/erm/scenarios.py).

Everything here is read-only against the engine or goes through another module's own service, so the checks that module
makes (business unit, capability, organization) still apply. Nothing here changes how an impact number is calculated.

candidates(...)     the searchable picker for the Affected items step, filtered to the caller's units on the server
headline(...)       one sentence and a few counts summarising an impact result
context(...)        read only past events that inform likelihood (ORM loss events the caller may open)
create_action(...)  a task on the task board that remembers the scenario it came from
rehearse_in_bcm(...) a draft tabletop exercise in BCM built from the scenario
seed_from_record(...) the starting text for a scenario modelled on an incident, event or breach
"""
import datetime
import logging

from core.best_effort import swallowed
from database import get_db
from modules.erm import scenario_templates as tpl
from modules.erm import scenarios as sv
from modules.governance import relationships
from modules.governance.data_service import bu_scope_ids
from modules.governance.entity_scope import describe_record, entity_scope_sql

log = logging.getLogger("oneforall.erm.scenario_support")

# Higher means worse. Unknown band keys rank as moderate so a custom framework never breaks the sentence.
_BAND_RANK = {"very_low": 0, "low": 1, "minor": 1, "moderate": 2, "medium": 2, "high": 3, "major": 3,
              "critical": 4, "extreme": 4, "severe": 4}


def _rank(band):
    return _BAND_RANK.get(str(band or "").lower(), 2)


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


# ── Headline ─────────────────────────────────────────────────────────────────

def headline(impact):
    """A sentence and counts that say what the scenario does, from an impact result. Never invents a number."""
    per_risk = impact.get("per_risk") or []
    if not per_risk:
        return {"sentence": "Add at least one risk to see what this scenario does.", "risks": 0, "worse": 0,
                "band_up": 0, "to_high": 0, "new_breaches": 0, "emv_multiple": None}
    worse = band_up = to_high = 0
    for row in per_risk:
        base, scen = row["baseline"], row["scenario"]
        # Compare like with like: a risk with no stored residual score is judged on its inherent score on both sides,
        # otherwise the calculated residual of the scenario would look like an improvement over the inherent baseline.
        if base["rrr"] is None:
            is_worse = scen["irr"] > base["irr"]
        else:
            is_worse = scen["irr"] > base["irr"] or (scen["rrr"] is not None and scen["rrr"] > base["rrr"])
        if is_worse:
            worse += 1
        if _rank(scen["band"]) > _rank(base["band"]):
            band_up += 1
            if _rank(scen["band"]) >= 3 > _rank(base["band"]):
                to_high += 1
    new_breaches = sum(1 for a in impact.get("appetite_impact") or []
                       if a.get("scenario_breached") and not a.get("baseline_breached"))
    base_emv = (impact.get("baseline_totals") or {}).get("emv_r_total")
    scen_emv = (impact.get("scenario_totals") or {}).get("emv_r_total")
    multiple = round(scen_emv / base_emv, 1) if base_emv and scen_emv is not None and base_emv > 0 else None

    if not worse and not band_up and not new_breaches:
        sentence = "No linked risk changes yet. Set a higher likelihood or impact on a risk to see the effect."
    else:
        parts = [f"{worse} of {_plural(len(per_risk), 'risk')} get worse"]
        if band_up:
            parts.append(f"{_plural(band_up, 'risk')} {'moves' if band_up == 1 else 'move'} to a higher band"
                         + (f" ({to_high} into High or above)" if to_high else ""))
        if new_breaches:
            parts.append(f"{_plural(new_breaches, 'category')} go over appetite" if new_breaches > 1
                         else "1 category goes over appetite")
        sentence = ", ".join(parts) + "."
        if multiple is not None and multiple != 1:
            sentence += f" Expected residual loss is {multiple} times the baseline."
    return {"sentence": sentence, "risks": len(per_risk), "worse": worse, "band_up": band_up, "to_high": to_high,
            "new_breaches": new_breaches, "emv_multiple": multiple}


# ── Candidates for the Affected items step ───────────────────────────────────

_CANDIDATE_SQL = {
    "risk": ("SELECT id, title, category, likelihood, impact, business_unit_id FROM erm_enterprise_risks "
             "ORDER BY title LIMIT 500"),
    "control": "SELECT id, title, business_unit_id FROM canonical_controls ORDER BY title LIMIT 500",
    "kri": ("SELECT k.id AS id, k.name AS title, r.business_unit_id AS business_unit_id FROM erm_kris k "
            "LEFT JOIN erm_enterprise_risks r ON r.id = k.linked_risk_id ORDER BY k.name LIMIT 500"),
    "objective": "SELECT id, title, business_unit_id FROM erm_objectives ORDER BY title LIMIT 500",
    "external_context": "SELECT id, title, business_unit_id FROM erm_emerging_risks ORDER BY title LIMIT 500",
}


def candidates(link_type, actor, query="", template_id=None, limit=100):
    """Records of one type the caller may link, newest names first by title. The unit rule is applied here, on the
    server, the same one add_scenario_link enforces again when the link is written."""
    if link_type not in _CANDIDATE_SQL:
        raise sv.ScenarioError(f"invalid link_type: {link_type}")
    scope = bu_scope_ids(actor)
    words = [w.lower() for w in ((tpl.template(template_id) or {}).get("match") or [])]
    needle = (query or "").strip().lower()
    db = get_db()
    try:
        rows = [dict(r) for r in db.execute(_CANDIDATE_SQL[link_type]).fetchall()]
    finally:
        db.close()
    out = []
    for row in rows:
        if not sv._bu_allowed(scope, row.get("business_unit_id")):
            continue
        text = f"{row.get('title') or ''} {row.get('category') or ''}".lower()
        if needle and needle not in text:
            continue
        row["suggested"] = bool(words) and any(w in text for w in words)
        row["label"] = row.get("title") or f"#{row['id']}"
        out.append(row)
    out.sort(key=lambda r: (not r["suggested"], str(r["label"]).lower()))
    return out[:max(1, min(int(limit), 200))]


# ── Context (read only) ──────────────────────────────────────────────────────

def context(scenario_id, actor):
    """Past loss events the caller may open in ORM, from the last twelve months. It informs a person's judgement of
    likelihood; it is never stored with the scenario and never used by the calculation."""
    db = get_db()
    try:
        scope, params = entity_scope_sql(("orm", "event"), actor, "t")
        rows = [dict(r) for r in db.execute(
            "SELECT t.id AS id, t.title AS title, t.severity AS severity, t.event_type AS event_type, "
            "t.financial_impact AS financial_impact, t.detected_at AS detected_at FROM orm_events t "
            f"WHERE {scope} ORDER BY t.detected_at DESC LIMIT 300", params).fetchall()]
    except Exception as exc:
        # A tenant without the ORM tables has no past events to show. Anything else must surface.
        from core.best_effort import is_missing_relation
        if not is_missing_relation(exc):
            raise
        rows = []
    finally:
        db.close()
    cutoff = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    recent = [r for r in rows if str(r.get("detected_at") or "9999")[:10] >= cutoff]
    by_severity = {}
    for r in recent:
        key = (r.get("severity") or "unknown").lower()
        by_severity[key] = by_severity.get(key, 0) + 1
    top = sorted(recent, key=lambda r: -(r.get("financial_impact") or 0))[:5]
    return {
        "orm_events": {"count": len(recent), "by_severity": by_severity,
                       "total_financial_impact": round(sum((r.get("financial_impact") or 0) for r in recent), 2),
                       "top": [{"id": r["id"], "title": r["title"], "severity": r["severity"],
                                "financial_impact": r["financial_impact"], "url": f"/orm/?open=event:{r['id']}"}
                               for r in top]},
    }


# ── Actions on other modules ─────────────────────────────────────────────────

def _visible_scenario(scenario_id, actor):
    scenario = sv.get_scenario(scenario_id, bu_scope=bu_scope_ids(actor))
    if not scenario:
        raise sv.ScenarioError("scenario not found")
    return scenario


def _edge(actor, source, target, relationship):
    """Record where something came from. The work itself is already saved, so a failed edge is logged and skipped."""
    db = get_db()
    try:
        relationships.create_link(db, actor, source, target, relationship, provenance="system")
        db.commit()
    except Exception:
        swallowed("scenario_support: link to scenario")
    finally:
        db.close()


def create_action(scenario_id, data, actor):
    """A task on the board for something the scenario showed. The task stays an ordinary task; the scenario is its
    related record."""
    from modules.launcher.task_service import create_task_with_assignment_notification
    scenario = _visible_scenario(scenario_id, actor)
    title = (data.get("title") or "").strip()[:200]
    if not title:
        raise sv.ScenarioError("title is required")
    priority = data.get("priority") or "medium"
    if priority not in {"critical", "high", "medium", "low"}:
        raise sv.ScenarioError("invalid priority")
    due = sv._clean_review_date(data.get("due_date"))
    assignee = data.get("assigned_to")
    try:
        assignee = int(assignee) if assignee not in (None, "") else None
    except (TypeError, ValueError, OverflowError):
        raise sv.ScenarioError("assigned_to must be a user id")
    description = (data.get("description") or "").strip()[:2000] or f"From scenario: {scenario['title']}"
    try:
        task_id = create_task_with_assignment_notification(
            title=title, description=description, module="erm", entity_type="scenario", entity_id=scenario_id,
            assigned_to=assignee, priority=priority, status="todo", due_date=due, tags="scenario",
            created_by=actor["id"])
    except ValueError as exc:
        raise sv.ScenarioError(str(exc))
    _edge(actor, ("platform", "task", task_id), ("erm", "scenario", scenario_id), "derived_from")
    return task_id


def rehearse_in_bcm(scenario_id, actor):
    """A draft tabletop exercise in BCM from the scenario. BCM's own service applies its rules (organization,
    business unit, who may run exercises), so the same refusal a BCM manager would get applies here."""
    from modules.bcm import exercise_service as exs
    scenario = _visible_scenario(scenario_id, actor)
    objectives = (scenario.get("assumptions") or "").strip()
    try:
        exercise_id = exs.create_exercise(actor, {
            "title": f"Tabletop: {scenario['title']}"[:255],
            "type": "tabletop",
            "description": scenario.get("description") or "",
            "scenario": scenario.get("description") or scenario["title"],
            "objectives": ("Test the response to this scenario. Assumptions: " + objectives) if objectives else "",
        })
    except exs.ExerciseError as exc:
        raise sv.ScenarioError(str(exc))
    _edge(actor, ("bcm", "exercise", exercise_id), ("erm", "scenario", scenario_id), "derived_from")
    return exercise_id


# ── Modelling a scenario on a record from another module ─────────────────────

_SEEDS = {
    ("bcm", "incident"): ("bcm_incidents", "Technology failure"),
    ("orm", "event"): ("orm_events", "Other"),
    ("sentinel", "breach"): ("sentinel_breaches", "Data breach"),
}


def seed_from_record(module, record_type, record_id, actor):
    """Starting text for a scenario about a real incident, event or breach the caller may open. The record's own
    scope rule decides; an unreadable or missing record answers the same way."""
    key = (str(module).lower(), str(record_type).lower())
    if key not in _SEEDS:
        raise sv.ScenarioError("this kind of record cannot start a scenario")
    db = get_db()
    try:
        shown = describe_record(db, key, record_id, actor)
        if not shown:
            raise sv.ScenarioError("record not found")
        table, scenario_type = _SEEDS[key]
        row = db.execute(f"SELECT description FROM {table} WHERE id=%s", (record_id,)).fetchone()
    finally:
        db.close()
    return {"title": f"What if it were worse: {shown['title']}"[:200],
            "description": ((row["description"] if row else "") or "")[:1000],
            "scenario_type": scenario_type, "assumptions": "",
            "origin": {"module": key[0], "type": key[1], "id": int(record_id)}}


def link_origin(scenario_id, origin, actor):
    """Remember which record the scenario was modelled on."""
    if not origin:
        return
    try:
        source = (str(origin["module"]), str(origin["type"]), int(origin["id"]))
    except (KeyError, TypeError, ValueError):
        return
    _edge(actor, ("erm", "scenario", scenario_id), source, "derived_from")
