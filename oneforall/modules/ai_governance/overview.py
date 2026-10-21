"""
AI Governance: the specialist Overview (plans/2026-10-governance-rework/01 section 3).

A governance specialist's first screen answers what needs action today. Every card says what it counts, from which window,
against which denominator, and where the records it counted can be opened, and it is one of the states of
`core/metric_state`: a measured number (a measured zero stays zero), "not measured" when nothing defines it, or
"unavailable" when its source could not be read. A use with no evaluation or oversight arrangement is "not measured" and is
never counted as passing. This dashboard is for governance specialists; historical request authors see only their own
request history.

Every number is read through the same functions as the list it opens, inside the viewer's own business-unit scope.
"""
import logging
from datetime import timedelta

from core import ai_rollout, metric_state as ms
from core.rbac import has_capability
from core.timeutils import to_dt, utcnow
from modules.ai_governance import decisions, monitoring, rules, service, workspace
from modules.governance.data_service import bu_scope_ids

log = logging.getLogger("oneforall.ai_governance")

WINDOW_DAYS = 90
AGING = (("0_2", "0 to 2 days", 0, 2), ("3_7", "3 to 7 days", 3, 7), ("8_14", "8 to 14 days", 8, 14),
         ("15_plus", "15 days or more", 15, None))
SPECIALIST_KEYS = ("new_requests", "waiting_for_information", "awaiting_decision", "approved_with_conditions", "reviews_due",
                   "material_change", "evaluation_oversight_gaps")


def _scope(db, user) -> dict:
    scope = bu_scope_ids(user)
    if scope is None:
        return {"text": "The whole organization.", "whole_organization": True}
    if scope == [-1]:
        return {"text": "Records that belong to the whole organization only, because you have no business unit.",
                "whole_organization": False}
    row = db.execute("SELECT name FROM business_units WHERE id = %s", (user.get("business_unit_id"),)).fetchone()
    name = row["name"] if row else "Your business unit"
    return {"text": f"{name} and the units below it, plus records that belong to the whole organization.",
            "whole_organization": False}


def _age_days(stamp, now) -> "int | None":
    try:
        submitted = to_dt(stamp)
        return max(0, (now - submitted).days) if submitted is not None else None
    except (TypeError, ValueError):
        return None


def _aging(stamps, now) -> list:
    buckets = {key: 0 for key, *_ in AGING}
    for stamp in stamps:
        days = _age_days(stamp, now)
        if days is None:
            continue
        for key, _label, low, high in AGING:
            if days >= low and (high is None or days <= high):
                buckets[key] += 1
                break
    return [{"key": key, "label": label, "count": buckets[key]} for key, label, *_ in AGING]


def _funnel(db, user, now, window_days) -> dict:
    since = (now - timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")
    counts = service.funnel_counts(db, user, since)
    stages = [
        {"key": "submitted", "label": "Submitted", "state": ms.MEASURED, "value": counts["submitted"], "note": None},
        {"key": "triaged", "label": "Triaged by a reviewer", "state": ms.MEASURED, "value": counts["triaged"], "note": None},
        {"key": "accepted", "label": "Accepted into the inventory", "state": ms.MEASURED, "value": counts["accepted"], "note": None},
        {"key": "assessed", "label": "Accepted and impact assessed", "state": ms.MEASURED, "value": counts["assessed"],
         "note": "An AI impact assessment is completed or approved."},
        {"key": "decided", "label": "Accepted and decided", "state": ms.MEASURED, "value": counts["decided"],
         "note": "A decision of approved, approved with conditions or rejected stands."},
        {"key": "responded", "label": "Response sent", "state": ms.MEASURED, "value": counts["responded"],
         "note": "The latest external response is marked sent, or the accepted request was closed after a sent response."},
        {"key": "closed", "label": "Closed", "state": ms.MEASURED, "value": counts["closed"],
         "note": "An accepted request was explicitly closed by a specialist."},
    ]
    return ms.measured(
        "decision_funnel", "Requests by stage", counts["submitted"],
        definition="Requests submitted in the window and how many reached each step. Response and closure counts "
                   "include accepted requests only; a rejection at intake is visible in the Requests worklist.",
        window=f"last {window_days} days", denominator={"value": counts["submitted"], "label": "requests submitted in the window"},
        drilldown="/ai-governance/review", detail={"stages": stages})


def _specialist(db, user, now, window_days, reviewer, decider) -> tuple:
    cards, aging = [], []
    today = now.strftime("%Y-%m-%d")
    portfolio = None

    def scoped_portfolio():
        nonlocal portfolio
        if portfolio is None:
            portfolio = monitoring.get_portfolio(db, user)
        return portfolio

    if reviewer:
        work_counts = None

        def scoped_work_counts():
            nonlocal work_counts
            if work_counts is None:
                work_counts = service.review_worklist(db, user, counts_only=True)["counts"]
            return work_counts

        def new():
            stamps = service.review_submitted_at(db, user, "submitted")
            ages = [d for d in (_age_days(s, now) for s in stamps) if d is not None]
            return ms.measured(
                "new_requests", "New requests", scoped_work_counts()["new"],
                definition="Imported drafts to triage and submitted requests awaiting a first review.",
                drilldown="/ai-governance/review?stage=new",
                detail={"oldest_days": max(ages) if ages else None})
        cards.append(ms.guarded("new_requests", "New requests", new, definition="Requests awaiting a first review.",
                                drilldown="/ai-governance/review?stage=new"))
        try:
            aging = _aging(service.review_submitted_at(db, user, "submitted"), now)
        except Exception:
            log.warning("AI governance overview: request ageing could not be read", exc_info=True)
            aging = []
        cards.append(ms.guarded(
            "waiting_for_information", "Waiting for information",
            lambda: ms.measured(
                "waiting_for_information", "Waiting for information", scoped_work_counts()["needs_clarification"],
                definition="Requests sent back to the requester, or carrying a question nobody has answered yet. A pending "
                           "reply is not an internal failure.",
                drilldown="/ai-governance/review?stage=needs_clarification"),
            definition="Requests waiting for the requester.", drilldown="/ai-governance/review?stage=needs_clarification"))

    queue_error = None
    queue = None
    try:
        queue = decisions.list_queue(db, user)
    except Exception:
        queue_error = True
        log.warning("AI governance overview: the decision queue could not be read", exc_info=True)

    def from_queue(key, label, definition, build):
        if queue_error:
            return ms.unavailable(key, label, definition=definition, drilldown="/ai-governance/decisions")

        def metric():
            result = build(queue)
            limited = queue.get("partial", {})
            source = "requests" if key == "awaiting_decision" else "standing"
            if limited.get(source):
                # list_queue is deliberately bounded. Never present a count from
                # the first page as the whole scoped portfolio.
                result["state"] = ms.PARTIAL
                result["note"] = f"At least this many; only the first {limited['limit']} records were assessed."
                result["sources"] = {"available": [f"first {limited['limit']} {source} records"],
                                     "missing": [f"{source} records beyond the first {limited['limit']}"]}
            return result

        return ms.guarded(key, label, metric, definition=definition, drilldown="/ai-governance/decisions")

    separation = ai_rollout.separation_required(user.get("org_id"))

    def awaiting(q):
        mine = [r for r in q["requests"] if decider and not (separation and r["yours"])]
        return ms.measured("awaiting_decision", "Awaiting an independent decision", len(q["requests"]),
                           definition="Requests for a decision that nobody has decided yet, in your scope.",
                           drilldown="/ai-governance/decisions", detail={"yours_to_decide": len(mine)})
    cards.append(from_queue("awaiting_decision", "Awaiting an independent decision",
                            "Requests for a decision that nobody has decided yet.", awaiting))

    def conditions(q):
        open_n = sum(c["open"] for c in q["conditions"])
        overdue = sum(c["overdue"] for c in q["conditions"])
        due = sorted(c["next_due"] for c in q["conditions"] if c["next_due"])
        return ms.measured("approved_with_conditions", "Approved with open conditions", len(q["conditions"]),
                           definition="Standing approvals that still have at least one open condition. The count is of uses; "
                                      "the conditions are in the detail.",
                           drilldown="/ai-governance/decisions",
                           detail={"open_conditions": open_n, "overdue_conditions": overdue, "next_due": due[0] if due else None})
    cards.append(from_queue("approved_with_conditions", "Approved with open conditions",
                            "Standing approvals with an open condition.", conditions))

    def due(_unused=None):
        soon = workspace.list_systems(db, user, state="review_soon", page_size=1)["total"]
        overdue = workspace.list_systems(db, user, state="review_due", page_size=1)["total"]
        return ms.measured("reviews_due", "Reviews due", soon,
                           definition=f"Active AI uses whose next review date has been reached or falls within "
                                      f"{workspace.REVIEW_SOON_DAYS} days.",
                           drilldown="/ai-governance/systems?state=review_soon",
                           detail={"overdue": overdue, "within_days": workspace.REVIEW_SOON_DAYS})
    cards.append(ms.guarded("reviews_due", "Reviews due", due, definition="Review dates reached or due soon.",
                            drilldown="/ai-governance/systems?state=review_soon"))

    def changed(q):
        return ms.measured("material_change", "Material change since the decision", len(q["re_reviews"]),
                           definition="Approved uses whose decision expired, or whose profile, tier or recorded evaluations "
                                      "changed after it was signed, so a new decision is needed.",
                           drilldown="/ai-governance/decisions")
    cards.append(from_queue("material_change", "Material change since the decision",
                            "Approved uses that need a new decision.", changed))

    def gaps():
        pf = scoped_portfolio()
        c = pf["counts"]
        detail = {k: c[k] for k in ("evaluation_failed", "evaluation_stale", "oversight_attention", "no_evaluation", "no_oversight")}
        note = None
        if c["no_evaluation"] or c["no_oversight"]:
            note = (f"{c['no_evaluation']} use(s) have no evaluation with a pass or fail threshold and {c['no_oversight']} have "
                    "no oversight arrangement recorded. These are not measured, so they are not counted as passing.")
        common = dict(definition="Active uses whose latest evaluation failed, did not finish or is out of date, or whose human "
                                 "oversight arrangement awaits review or changed with the profile.",
                      drilldown="/ai-governance/monitoring?focus=evaluation_oversight", note=note, detail=detail,
                      denominator={"value": pf["total_uses"], "label": "active AI uses in your scope"})
        if pf["state"] == "partial":
            return ms.partial("evaluation_oversight_gaps", "Evaluation and oversight gaps", pf["evaluation_oversight"],
                              sources_ok=[f"the first {pf['total_uses']} uses"],
                              sources_missing=pf["partial_reasons"],
                              **common)
        return ms.measured("evaluation_oversight_gaps", "Evaluation and oversight gaps", pf["evaluation_oversight"], **common)
    cards.append(ms.guarded("evaluation_oversight_gaps", "Evaluation and oversight gaps", gaps,
                            definition="Uses with failed, out of date or unreviewed evaluation and oversight records.",
                            drilldown="/ai-governance/monitoring?focus=evaluation_oversight"))

    funnel = ms.guarded("decision_funnel", "Requests by stage", lambda: _funnel(db, user, now, window_days),
                        definition="Requests submitted in the window and how far each got.", drilldown="/ai-governance/review",
                        window=f"last {window_days} days") if reviewer else None
    try:
        pf = scoped_portfolio()
        evaluation_counts = {"passed": 0, "failed": 0, "stale": 0, "not_measured": 0}
        tiers = {key: {"label": label, "total": 0, "attention": 0} for key, label in rules.TIER_LABELS.items()}
        for use in pf["uses"]:
            evaluation_counts[use["evaluation_outcome"]] += 1
            tier = tiers.get(use["tier"])
            if tier is not None:
                tier["total"] += 1
                tier["attention"] += bool(use["flags"] or use["not_measured"])
        charts = {"state": pf["state"], "as_of": pf["as_of"], "included": pf["total_uses"],
                  "limit": pf["limit"], "partial_reasons": pf["partial_reasons"],
                  "evaluations": evaluation_counts, "tiers": tiers,
                  "definition": "Latest recorded evaluation for each active AI use in your scope. "
                                "Not measured includes uses with no thresholded evaluation. "
                                "Attention includes recorded gaps and missing evaluation or oversight."}
    except Exception:
        log.warning("AI governance overview: portfolio charts could not be read", exc_info=True)
        charts = {"state": "unavailable", "as_of": None, "included": None, "limit": None,
                  "evaluations": None, "tiers": None,
                  "definition": "The active AI use portfolio could not be read just now."}
    return cards, funnel, aging, charts


def get_overview(db, user, *, window_days: int = WINDOW_DAYS, now=None) -> dict:
    service._require(user, "ai_use.view")
    now = now or utcnow()
    reviewer, decider = has_capability(user, "ai_use.review"), has_capability(user, "ai_use.decide")
    out = {"as_of": now.strftime("%Y-%m-%d %H:%M:%S"),
           "viewer": {"specialist": True, "reviewer": reviewer, "decider": decider},
           "scope": _scope(db, user), "cards": [], "funnel": None, "aging": [], "charts": None}
    out["cards"], out["funnel"], out["aging"], out["charts"] = _specialist(
        db, user, now, window_days, reviewer, decider)
    return out
