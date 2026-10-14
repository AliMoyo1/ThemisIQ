"""
AI governance: the outstanding items of one AI use (plans/2026-10-governance-rework/01 section 5).

A deterministic list of what stands between a use and a decision, in the order a specialist works through it. Each line is
one thing, owned by one module, in one state, with the sentence that explains it and the place to resolve it:

* complete            the owning module's own record shows it is done
* not_applicable      the rules rule it out, or a reviewer judged it so with a reason
* not_yet_assessed    nobody has done it, or what was done is out of date
* waiting             it is in someone else's hands (a review, a decision)
* failed              it was done and the result is not acceptable
* unavailable         the source could not be read: that is not "complete"
* no_access           the viewer may not see that source

A model never sets a line's state. Everything here is read through the viewer's own scope and nothing is stored: a line is
as current as the records it reads. The same rule version always gives the same lines for the same records.
"""
import logging

from core.timeutils import utcnow
from modules.ai_governance import controls, decisions, evaluations, guidance, oversight, regulation, rules, service
from modules.ai_governance.service import APP
from modules.governance import relationships
from modules.governance.entity_scope import describe_record

log = logging.getLogger("oneforall.ai_governance")

RULE_VERSION = "o1"
STATE_LABELS = {
    "complete": "Done", "not_applicable": "Not applicable", "not_yet_assessed": "Not done yet", "waiting": "Waiting on someone",
    "failed": "Needs attention", "unavailable": "Could not be read", "no_access": "Not open to you",
}
DONE_STATES = ("complete", "not_applicable")
_BCM_KINDS = {("bcm", "bia"), ("bcm", "plan")}
_PROCESS = ("governance", "process")


def _line(key, title, module, state, reason, *, blocks=False, resolution=None, owner=None, due=None, records=None) -> dict:
    return {"key": key, "title": title, "module": module, "state": state, "state_label": STATE_LABELS[state],
            "reason": reason, "blocks_decision": blocks, "rule_version": RULE_VERSION, "resolution": resolution,
            "owner": owner, "due": due, "records": records or []}


def _guard(key, title, module, build):
    try:
        return build()
    except Exception:
        log.warning("AI governance outstanding items: %s could not be read", key, exc_info=True)
        return _line(key, title, module, "unavailable", "This could not be read just now. That is not the same as done.")


def _step_line(step, owner) -> dict:
    base = f"/ai-governance/systems/{step['_application_id']}"
    resolution = step["action"] if step.get("action") else None
    blocks = step["effective"] == "required"
    reason = "; ".join(step["reasons"][:2]) if step.get("reasons") else ""
    if step["state"] == "no_access":
        return _line(step["key"], step["title"], step["module"], "no_access", "You do not have access to this part of the record.")
    if step["state"] == "unavailable":
        return _line(step["key"], step["title"], step["module"], "unavailable",
                     "This could not be read just now. That is not the same as done.", blocks=blocks, resolution=resolution)
    if step["effective"] == "not_applicable":
        judged = step.get("override")
        why = (f"Judged not applicable by {judged['set_by'] or 'a reviewer'}: {judged['reason']}"
               if judged and not judged["out_of_date"] else reason or "The answers rule it out.")
        return _line(step["key"], step["title"], step["module"], "not_applicable", why, resolution=resolution)
    if step["state"] == "complete" and not step["stale"]:
        return _line(step["key"], step["title"], step["module"], "complete",
                     f"{len(step['records'])} record(s) in {step['module']} show it is done.", blocks=blocks,
                     resolution={"label": "Open it", "url": step["records"][0]["url"]} if step["records"] else resolution,
                     records=[{"title": r["title"], "status": r["status"], "url": r["url"]} for r in step["records"][:5]])
    if step["state"] == "complete":
        why = "It was done before the use changed. Look at it again."
    elif step["state"] == "in_progress":
        why = "It has been started and is not finished."
    elif step["effective"] == "needs_review":
        why = reason or "An answer it depends on is missing."
    else:
        why = reason or "Nobody has started it."
    return _line(step["key"], step["title"], step["module"], "not_yet_assessed", why, blocks=blocks, resolution=resolution,
                 owner=owner, records=[{"title": r["title"], "status": r["status"], "url": r["url"]} for r in step["records"][:5]])


def get_outstanding(db, user, application_id: int) -> "dict | None":
    """The lines for one use, the count by state, and whether anything that blocks a decision is still open. None when the
    viewer may not open the use."""
    service._require(user, "ai_use.view")
    if not describe_record(db, APP, application_id, user):
        return None
    base = f"/ai-governance/systems/{application_id}"
    profile = service.get_profile(db, user, application_id)
    app = db.execute("SELECT a.owner_user_id, u.full_name FROM applications a LEFT JOIN users u ON u.id = a.owner_user_id "
                     "WHERE a.id = %s", (application_id,)).fetchone()
    owner = {"id": app["owner_user_id"], "name": app["full_name"]} if app and app["owner_user_id"] else None
    today = utcnow().strftime("%Y-%m-%d")
    lines = []

    if profile is None:
        lines.append(_line("profile", "AI profile", "AI Governance", "not_yet_assessed",
                           "The use has no AI profile yet, so nothing else can be read.", blocks=True,
                           resolution={"label": "Add the profile", "url": base + "#overview"}))
        return _wrap(lines)

    # Facts the use itself must supply
    def facts():
        missing = [rules.label(f) for f in profile["missing"]]
        if not missing:
            return _line("facts", "Answers the screening rules read", "AI Governance", "complete",
                         "Every question the screening rules read is answered.", resolution={"label": "Open the profile", "url": base + "#overview"})
        return _line("facts", "Answers the screening rules read", "AI Governance", "not_yet_assessed",
                     "Not answered: " + ", ".join(missing) + ". An unanswered question keeps the tier at needs review.",
                     resolution={"label": "Answer them", "url": base + "#overview"}, owner=owner)
    lines.append(_guard("facts", "Answers the screening rules read", "AI Governance", facts))

    def owner_line():
        if owner:
            return _line("owner", "A named owner", "Governance", "complete", f"{owner['name']} is named as the owner.")
        return _line("owner", "A named owner", "Governance", "not_yet_assessed",
                     "Nobody is named as answerable for this use.", blocks=True,
                     resolution={"label": "Name an owner", "url": base + "#overview"})
    lines.append(_guard("owner", "A named owner", "Governance", owner_line))

    # The assessments the requirement rules call for, from the owning modules' own records
    try:
        plan = guidance.get_checklist(db, user, application_id) or {"steps": []}
        for step in plan["steps"]:
            lines.append(_step_line({**step, "_application_id": application_id}, owner))
    except Exception:
        log.warning("AI governance outstanding items: the checklist could not be read", exc_info=True)
        lines.append(_line("checklist", "Required assessments", "AI Governance", "unavailable",
                           "This could not be read just now. That is not the same as done.", blocks=True))

    def evaluation():
        got = evaluations.list_runs(db, user, application_id)
        latest = (got or {}).get("latest")
        res = {"label": "Record an evaluation", "url": base + "#monitoring"}
        if latest is None:
            return _line("evaluation", "An evaluation with a pass or fail threshold", "AI Governance", "not_yet_assessed",
                         "No evaluation has been recorded for this use.", resolution=res, owner=owner)
        if latest["state"] == "ungated":
            return _line("evaluation", "An evaluation with a pass or fail threshold", "AI Governance", "not_yet_assessed",
                         "The latest run recorded no threshold, so it claims neither a pass nor a failure.", resolution=res, owner=owner)
        if latest["state"] in ("failed", "interrupted"):
            return _line("evaluation", "An evaluation with a pass or fail threshold", "AI Governance", "failed",
                         f"The latest evaluation, {latest['name']}, " + ("failed." if latest["state"] == "failed" else "did not finish."),
                         resolution={"label": "Review the run", "url": base + "#monitoring"})
        if latest["stale"]:
            return _line("evaluation", "An evaluation with a pass or fail threshold", "AI Governance", "not_yet_assessed",
                         f"The latest evaluation, {latest['name']}, is out of date: the use changed or it is older than 180 days.",
                         resolution=res, owner=owner)
        return _line("evaluation", "An evaluation with a pass or fail threshold", "AI Governance", "complete",
                     f"The latest evaluation, {latest['name']}, passed and is current.", resolution={"label": "Open it", "url": base + "#monitoring"})
    lines.append(_guard("evaluation", "An evaluation with a pass or fail threshold", "AI Governance", evaluation))

    def oversight_line():
        tracks = oversight.summary_for_use(db, user, application_id)["tracks"]
        res = {"label": "Open human oversight", "url": base + "#oversight"}
        recorded = {k: v for k, v in tracks.items() if v["status"] != "not_recorded"}
        if not recorded:
            return _line("oversight", "Human oversight arrangements", "AI Governance", "not_yet_assessed",
                         "No design or operating arrangement is recorded.", resolution=res, owner=owner)
        if any(t["profile_changed"] for t in recorded.values()):
            return _line("oversight", "Human oversight arrangements", "AI Governance", "not_yet_assessed",
                         "The AI profile changed after an arrangement was recorded. Record a new version.", resolution=res, owner=owner)
        if any(t["status"] == "draft" for t in recorded.values()):
            return _line("oversight", "Human oversight arrangements", "AI Governance", "waiting",
                         "An arrangement is a draft waiting for an independent review.", resolution=res)
        if len(recorded) < len(tracks):
            return _line("oversight", "Human oversight arrangements", "AI Governance", "not_yet_assessed",
                         "Only one of the design and operating arrangements is recorded.", resolution=res, owner=owner)
        return _line("oversight", "Human oversight arrangements", "AI Governance", "complete",
                     "Both arrangements are reviewed for the current profile. This is not a legal conformity decision.", resolution=res)
    lines.append(_guard("oversight", "Human oversight arrangements", "AI Governance", oversight_line))

    def proof():
        if not controls.can_view(user):
            return _line("proof", "Current proof for implemented AI controls", "Operations risk", "no_access",
                         "You do not have access to AI management assessments.")
        items = controls.use_controls(db, user, application_id) or []
        res = {"label": "Open controls and proof", "url": base + "#risks_controls"}
        if not items:
            return _line("proof", "Current proof for implemented AI controls", "Operations risk", "not_yet_assessed",
                         "No AI control is recorded for this use.", resolution=res, owner=owner)
        weak = [i for i in items if i["applicable"] and i["implemented"] and (not i["mapped"] or i["proof"]["current"] == 0)]
        if weak:
            return _line("proof", "Current proof for implemented AI controls", "Operations risk", "failed",
                         f"{len(weak)} implemented control(s) have no current proof or no mapped canonical control.", resolution=res,
                         records=[{"title": f"{i['control']['ref'] or ''} {i['control']['title']}".strip(), "status": "no current proof",
                                   "url": None} for i in weak[:5]])
        return _line("proof", "Current proof for implemented AI controls", "Operations risk", "complete",
                     "Every implemented, applicable control has current proof.", resolution=res)
    lines.append(_guard("proof", "Current proof for implemented AI controls", "Operations risk", proof))

    def continuity():
        found = [l for l in relationships.list_links(db, user, APP, application_id)
                 if (l["module"], l["entity_type"]) in _BCM_KINDS]
        processes = [l for l in relationships.list_links(db, user, APP, application_id)
                     if (l["module"], l["entity_type"]) == _PROCESS]
        res = {"label": "Open continuity", "url": "/bcm/bia"}
        if found:
            return _line("continuity", "Continuity impact", "Business continuity", "complete",
                         f"{len(found)} continuity record(s) are linked to this use.", resolution=res,
                         records=[{"title": l["title"], "status": l["label"], "url": l["url"]} for l in found[:5]])
        why = (f"The use supports {len(processes)} business process(es), and no impact analysis or plan is linked to it."
               if processes else "No business process or continuity record is linked, so its continuity impact cannot be read.")
        return _line("continuity", "Continuity impact", "Business continuity", "not_yet_assessed", why, resolution=res, owner=owner)
    lines.append(_guard("continuity", "Continuity impact", "Business continuity", continuity))

    def regulatory():
        pending = [i for i in regulation.list_queue(db, user, "candidate")["items"] if i["application_id"] == application_id]
        res = {"label": "Open regulatory changes", "url": "/ai-governance/regulatory"}
        if not profile.get("jurisdictions"):
            return _line("regulatory", "Intended jurisdictions and regulatory changes", "Governance", "not_yet_assessed",
                         "No intended jurisdiction is named, so no change can be matched to this use.", resolution=res, owner=owner)
        if pending:
            return _line("regulatory", "Intended jurisdictions and regulatory changes", "Governance", "waiting",
                         f"{len(pending)} proposed regulatory change(s) await a reviewer.", resolution=res)
        return _line("regulatory", "Intended jurisdictions and regulatory changes", "Governance", "complete",
                     "Jurisdictions are named and no proposed change awaits review. This is not a legal applicability decision.",
                     resolution=res)
    lines.append(_guard("regulatory", "Intended jurisdictions and regulatory changes", "Governance", regulatory))

    def decision():
        got = decisions.get_decisions(db, user, application_id)
        res = {"label": "Open decisions", "url": base + "#decisions"}
        state = got["state"]
        if got["open_request"]:
            return _line("decision", "An independent decision", "AI Governance", "waiting",
                         "A decision has been asked for and nobody has decided it yet.", resolution=res)
        if state["state"] in ("approved", "approved_with_conditions"):
            return _line("decision", "An independent decision", "AI Governance", "complete",
                         f"{state['label']}." + (" " + " ".join(state["reasons"]) if state["reasons"] else ""), resolution=res)
        if state["state"] in ("needs_re_review", "expired"):
            return _line("decision", "An independent decision", "AI Governance", "not_yet_assessed",
                         state["label"] + ": " + " ".join(state["reasons"]), resolution=res)
        if state["state"] in ("rejected", "revoked"):
            return _line("decision", "An independent decision", "AI Governance", "failed", state["label"] + ".", resolution=res)
        return _line("decision", "An independent decision", "AI Governance", "not_yet_assessed",
                     "No decision has been asked for.", resolution=res, owner=owner)
    lines.append(_guard("decision", "An independent decision", "AI Governance", decision))

    def conditions():
        got = decisions.list_queue(db, user)
        mine = [c for c in got["conditions"] if c["application_id"] == application_id]
        if not mine:
            return None
        c = mine[0]
        res = {"label": "Open the conditions", "url": base + "#decisions"}
        if c["overdue"]:
            return _line("conditions", "Conditions of the approval", "AI Governance", "failed",
                         f"{c['overdue']} of {c['open']} open condition(s) are past their date.", resolution=res, due=c["next_due"])
        return _line("conditions", "Conditions of the approval", "AI Governance", "waiting",
                     f"{c['open']} condition(s) are open.", resolution=res, owner=owner, due=c["next_due"])
    extra = _guard("conditions", "Conditions of the approval", "AI Governance", conditions)
    if extra is not None:
        lines.append(extra)
    return _wrap(lines)


def _wrap(lines) -> dict:
    counts = {k: 0 for k in STATE_LABELS}
    for line in lines:
        counts[line["state"]] += 1
    blocking = [l["key"] for l in lines if l["blocks_decision"] and l["state"] not in DONE_STATES]
    unread = [l["key"] for l in lines if l["state"] in ("unavailable",)]
    return {"rule_version": RULE_VERSION, "lines": lines, "counts": counts, "blocking": blocking, "unavailable": unread,
            "ready_for_decision": not blocking and not unread,
            "note": "A line is as current as the records it reads. Nothing here approves, accepts or certifies a use."}
