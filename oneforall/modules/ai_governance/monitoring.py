"""
AI governance G5: what is measured about a use (plans/ai-governance/08-g5-build-plan.md).

The Monitoring tab reads the owning modules through the viewer's own scope and says, for each source, one of: it reports
something to look at ("attention"), it reports and all is as it should be ("ok"), it has nothing to report because nothing
is measured ("not_measured"), or the viewer may not see it ("no_access"). Silence is never presented as health.

A small set of these facts also reopens a decision (see `decisions.reopening_facts`): an evaluation that failed or did not
finish after the decision was signed, and a regulatory change confirmed for the use after it. The rest is information.
"""
import logging
from datetime import timedelta

from core.timeutils import utcnow
from modules.ai_governance import controls, decisions, evaluations, oversight, regulation, rules, service
from modules.ai_governance.service import APP, ServiceError
from modules.governance.entity_scope import describe_record, entity_scope_sql

log = logging.getLogger("oneforall.ai_governance")

PROOF_SOON_DAYS = 30
SOURCES = ("decision", "oversight", "evaluations", "controls", "proof", "incidents", "regulation")


def _source(name, title, state, items=None, note=None) -> dict:
    return {"source": name, "title": title, "state": state, "items": items or [], "note": note}


def _guarded(name, title, build) -> dict:
    try:
        return build()
    except Exception:
        log.warning("AI governance monitoring: %s could not be read", name, exc_info=True)
        return _source(name, title, "unavailable", note="This could not be read just now. That is not a clean result.")


def _decision(db, user, application_id) -> dict:
    got = decisions.get_decisions(db, user, application_id)
    state = got["state"]
    items = [{"title": state["label"], "detail": "; ".join(state["reasons"]) or None,
              "url": f"/ai-governance/systems/{application_id}#decisions"}]
    if got["open_request"]:
        items.append({"title": "A request is waiting for a decision", "detail": None,
                      "url": f"/ai-governance/systems/{application_id}#decisions"})
    attention = state["state"] in ("needs_re_review", "expired", "revoked", "rejected") or bool(got["open_request"])
    return _source("decision", "Decision", "attention" if attention else ("ok" if state["state"] != "none" else "not_measured"),
                   items, None if state["state"] != "none" else "No decision has been recorded for this use.")


def _oversight(db, user, application_id) -> dict:
    tracks = oversight.summary_for_use(db, user, application_id)["tracks"]
    if all(track["status"] == "not_recorded" for track in tracks.values()):
        return _source("oversight", "Human oversight", "not_measured",
                       note="No design or operating arrangement has been recorded for this use.")
    labels = {"design": "Design", "operation": "Operation"}
    items = []
    attention = False
    for name, track in tracks.items():
        if track["status"] == "not_recorded":
            detail = "No arrangement recorded"
        elif track["profile_changed"]:
            detail = "AI profile changed; record a new version"
        elif track["status"] == "draft":
            detail = "Draft awaiting an independent review"
        else:
            detail = "Reviewed for the current AI profile"
        attention |= detail != "Reviewed for the current AI profile"
        items.append({"title": labels[name], "detail": detail,
                      "url": f"/ai-governance/systems/{application_id}#oversight"})
    return _source("oversight", "Human oversight", "attention" if attention else "ok", items,
                   note="Internal review status; this is not a legal conformity decision.")


def _evaluations(db, user, application_id) -> dict:
    got = evaluations.list_runs(db, user, application_id)
    runs = got["runs"] if got else []
    if not runs:
        return _source("evaluations", "Evaluations", "not_measured", note="No evaluation has been recorded for this use.")
    latest = runs[0]
    detail = f"{latest['state_label']}; {latest['subject_version']}; test set {latest['test_set_name']} {latest['test_set_version']}"
    if latest["stale"]:
        detail += "; out of date"
    attention = latest["state"] in ("failed", "interrupted") or latest["stale"]
    items = [{"title": latest["name"], "detail": detail, "url": f"/ai-governance/systems/{application_id}#monitoring"}]
    if got["comparison"]:
        moved = [f"{r['dimension']} {r['change']:+g}" for r in got["comparison"]["dimensions"] if r["change"]]
        if moved:
            items.append({"title": "Since the run before it", "detail": ", ".join(moved[:6]), "url": None})
    return _source("evaluations", "Evaluations", "attention" if attention else "ok", items)


def _controls_and_proof(db, user, application_id):
    items = controls.use_controls(db, user, application_id)
    if not controls.can_view(user):
        return (_source("controls", "AI controls", "no_access", note="You do not have access to AI management assessments."),
                _source("proof", "Proof", "no_access", note="You do not have access to AI management assessments."))
    if not items:
        return (_source("controls", "AI controls", "not_measured", note="No AI controls are recorded for this use."),
                _source("proof", "Proof", "not_measured", note="No AI controls are recorded for this use."))
    weak = [i for i in items if i["applicable"] and i["implemented"] and (not i["mapped"] or i["proof"]["current"] == 0)]
    control_items = [{"title": (f"{i['control']['ref']} " if i["control"]["ref"] else "") + i["control"]["title"],
                      "detail": "Implemented, not mapped to a canonical control" if not i["mapped"] else
                      ("All of its proof has expired" if i["proof"]["expired"] else "Implemented, no proof attached"),
                      "url": f"/ai-governance/systems/{application_id}#risks_controls"} for i in weak]
    controls_source = _source("controls", "AI controls", "attention" if weak else "ok", control_items,
                              None if weak else "Every implemented control has current proof.")
    soon = (utcnow() + timedelta(days=PROOF_SOON_DAYS)).strftime("%Y-%m-%d")
    today = utcnow().strftime("%Y-%m-%d")
    proof_items = []
    for item in items:
        for p in item["proof"]["items"]:
            if p.get("expires") and p["expires"] <= soon and not p["expired"]:
                proof_items.append({"title": p["title"], "detail": f"Expires {p['expires']}", "url": p["url"]})
            elif p["expired"] and p.get("expires") and p["expires"] < today:
                proof_items.append({"title": p["title"], "detail": f"Expired {p['expires']}", "url": p["url"]})
    return (controls_source, _source("proof", "Proof", "attention" if proof_items else "ok", proof_items,
                                     None if proof_items else "Nothing the controls rely on expires within 30 days."))


def _incidents(db, user, application_id) -> dict:
    from modules.ai_governance import workspace
    found = workspace._linked(db, user, application_id, workspace._INCIDENTS)
    if not found:
        return _source("incidents", "Incidents", "not_measured",
                       note="No incident is linked to this use. Link one from the incident to show it here.")
    return _source("incidents", "Incidents", "attention",
                   [{"title": l["title"], "detail": l["label"], "url": l["url"]} for l in found])


def _regulation(db, user, application_id) -> dict:
    rows = regulation.confirmed_for(db, user, application_id)
    if not rows:
        return _source("regulation", "Regulatory change", "not_measured", note="No regulatory change is confirmed for this use.")
    return _source("regulation", "Regulatory change", "attention",
                   [{"title": r["title"], "detail": f"{r['framework_name']}" + (f", effective {r['effective_date']}" if r["effective_date"] else ""),
                     "url": r["source_url"]} for r in rows])


def get_monitoring(db, user, application_id: int) -> "dict | None":
    service._require(user, "ai_use.view")
    if not describe_record(db, APP, application_id, user):
        return None
    sections = [
        _guarded("decision", "Decision", lambda: _decision(db, user, application_id)),
        _guarded("oversight", "Human oversight", lambda: _oversight(db, user, application_id)),
        _guarded("evaluations", "Evaluations", lambda: _evaluations(db, user, application_id)),
    ]
    try:
        controls_source, proof_source = _controls_and_proof(db, user, application_id)
    except Exception:
        log.warning("AI governance monitoring: controls could not be read", exc_info=True)
        controls_source = _source("controls", "AI controls", "unavailable", note="This could not be read just now. That is not a clean result.")
        proof_source = _source("proof", "Proof", "unavailable", note="This could not be read just now. That is not a clean result.")
    sections += [controls_source, proof_source,
                 _guarded("incidents", "Incidents", lambda: _incidents(db, user, application_id)),
                 _guarded("regulation", "Regulatory change", lambda: _regulation(db, user, application_id))]
    return {"sources": sections, "attention": [s["source"] for s in sections if s["state"] == "attention"],
            "unavailable": [s["source"] for s in sections if s["state"] == "unavailable"]}


# ── The portfolio: every use with what needs looking at ─────────────────────

PORTFOLIO_LIMIT = 500
GAP_LABELS = {
    "evaluation_failed": "The latest evaluation failed or did not finish",
    "evaluation_stale": "The latest evaluation is out of date",
    "oversight_attention": "A human oversight arrangement awaits review or changed with the profile",
    "review_overdue": "The review date has been reached",
    "material_change": "The standing decision needs a new review",
    "condition_overdue": "A condition of the approval is overdue",
}
NOT_MEASURED_LABELS = {
    "no_evaluation": "No evaluation with a pass or fail threshold has been recorded",
    "no_oversight": "No human oversight arrangement has been recorded",
}
FOCUS = {"evaluation_oversight": ("evaluation_failed", "evaluation_stale", "oversight_attention"),
         "gaps": tuple(GAP_LABELS), "evaluation_current": ()}


def get_portfolio(db, user, *, focus=None) -> dict:
    """Every active use the viewer may open, each with the facts that need looking at and the facts nobody has measured.

    A use with no evaluation or no oversight arrangement is listed as "not measured" and is never counted as passing.
    `focus` narrows the list to `gaps`, to `evaluation_oversight` or to one gap kind; the counts are always for the whole
    scope so a card and its list agree. Uses with something to look at come first. When more uses exist than the limit,
    the state is `partial`."""
    service._require(user, "ai_use.view")
    if focus not in (None, "", "all", *FOCUS, *GAP_LABELS, *NOT_MEASURED_LABELS):
        raise ServiceError(400, "Unknown focus.")
    today = utcnow().strftime("%Y-%m-%d")
    scope, params = entity_scope_sql(APP, user, "a")
    rows = db.execute(
        "SELECT a.id, a.name, a.business_unit_id, bu.name AS bu_name, u.full_name AS owner_name, p.provisional_tier, "
        "p.adopted_tier, p.next_review_at, p.version AS profile_version, p.material_changed_at "
        "FROM applications a JOIN ai_use_profiles p ON p.application_id = a.id "
        "LEFT JOIN business_units bu ON bu.id = a.business_unit_id LEFT JOIN users u ON u.id = a.owner_user_id "
        f"WHERE a.is_active = 1 AND {scope} ORDER BY a.name, a.id LIMIT %s", [*params, PORTFOLIO_LIMIT + 1]).fetchall()
    truncated = len(rows) > PORTFOLIO_LIMIT
    rows = rows[:PORTFOLIO_LIMIT]
    ids = [r["id"] for r in rows]
    latest, tracks = {}, {}
    if ids:
        marks = ",".join(["%s"] * len(ids))
        for run in db.execute(
                "SELECT application_id, result_state, finished_at, recorded_at FROM ai_evaluation_runs "
                f"WHERE application_id IN ({marks}) ORDER BY COALESCE(finished_at, recorded_at) DESC, id DESC", ids).fetchall():
            latest.setdefault(run["application_id"], run)
        for t in db.execute(
                "SELECT h.application_id, h.track, v.status, v.profile_version FROM ai_oversight_heads h "
                "JOIN ai_oversight_versions v ON v.application_id = h.application_id AND v.track = h.track "
                f"AND v.version = h.content_version WHERE h.application_id IN ({marks})", ids).fetchall():
            tracks.setdefault(t["application_id"], []).append(t)
    queue = decisions.list_queue(db, user)
    queue_truncated = queue.get("partial", {}).get("standing", False)
    changed = {r["application_id"] for r in queue["re_reviews"]}
    overdue_conditions = {c["application_id"] for c in queue["conditions"] if c["overdue"]}

    uses = []
    counts = {key: 0 for key in (*GAP_LABELS, *NOT_MEASURED_LABELS)}
    for r in rows:
        flags, unmeasured = [], []
        run = latest.get(r["id"])
        if run is None or run["result_state"] not in ("passed", "failed", "interrupted"):
            unmeasured.append("no_evaluation")
            evaluation_outcome = "not_measured"
        elif run["result_state"] in ("failed", "interrupted"):
            flags.append("evaluation_failed")
            evaluation_outcome = "failed"
        elif evaluations.is_stale(run["finished_at"] or run["recorded_at"], r["material_changed_at"], today):
            flags.append("evaluation_stale")
            evaluation_outcome = "stale"
        else:
            evaluation_outcome = "passed"
        recorded = tracks.get(r["id"], [])
        if not recorded:
            unmeasured.append("no_oversight")
        elif any(t["status"] == "draft" or t["profile_version"] != r["profile_version"] for t in recorded):
            flags.append("oversight_attention")
        if r["next_review_at"] and str(r["next_review_at"])[:10] <= today:
            flags.append("review_overdue")
        if r["id"] in changed:
            flags.append("material_change")
        if r["id"] in overdue_conditions:
            flags.append("condition_overdue")
        for key in (*flags, *unmeasured):
            counts[key] += 1
        tier = rules.effective_tier(r["provisional_tier"], r["adopted_tier"])
        uses.append({"application_id": r["id"], "name": r["name"], "business_unit": r["bu_name"], "owner": r["owner_name"],
                     "tier": tier, "tier_label": rules.TIER_LABELS[tier],
                     "evaluation_outcome": evaluation_outcome,
                     "flags": [{"key": k, "label": GAP_LABELS[k]} for k in flags],
                     "not_measured": [{"key": k, "label": NOT_MEASURED_LABELS[k]} for k in unmeasured],
                     "url": f"/ai-governance/systems/{r['id']}#monitoring"})
    with_gaps = sum(1 for u in uses if u["flags"])
    in_focus = sum(1 for u in uses if any(f["key"] in FOCUS["evaluation_oversight"] for f in u["flags"]))
    wanted = set(FOCUS.get(focus, (focus,))) if focus not in (None, "", "all") else None
    if focus == "evaluation_current":
        shown = [u for u in uses if u["evaluation_outcome"] == "passed"]
    else:
        shown = uses if wanted is None else [u for u in uses if wanted & {f["key"] for f in (*u["flags"], *u["not_measured"])}]
    shown.sort(key=lambda u: (-len(u["flags"]), u["name"].lower(), u["application_id"]))
    partial_reasons = []
    if truncated:
        partial_reasons.append(f"AI uses beyond the first {PORTFOLIO_LIMIT}")
    if queue_truncated:
        partial_reasons.append(f"decision records beyond the first {decisions.QUEUE_LIMIT}")
    return {"as_of": utcnow().strftime("%Y-%m-%d %H:%M:%S"), "state": "partial" if partial_reasons else "measured",
            "partial_reasons": partial_reasons,
            "limit": PORTFOLIO_LIMIT, "total_uses": len(uses), "with_gaps": with_gaps, "evaluation_oversight": in_focus,
            "counts": counts, "uses": shown, "focus": focus or "all"}
