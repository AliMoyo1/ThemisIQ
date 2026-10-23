"""AI help inside Scenario Studio.

Five proposals, none of which changes a number on its own:

draft(sentence)      a scenario drafted from one sentence, with the existing records it would touch
shocks(scenario_id)  a likelihood and impact (or control state) per linked item, each with a reason
gaps(scenario_id)    records that look related but are not linked yet
explain(scenario_id) the impact result in plain language, every point tied to a record in the result
challenge(scenario_id) questions that test the assumptions

Each returns a proposal the person accepts item by item. The impact calculation stays in modules/erm/scenarios.py and
reads only what a person saved. A model answer is checked here before it leaves: any record id must be one the caller
was offered, any score must pass the engine's own validation, every cited reference must exist in the result.
When the assistant is off or its answer cannot be read, AIUnavailable is raised and nothing is made up.
"""
import json
import re

from core.ai_client import AIUnavailable, UNREADABLE_MESSAGE, answer_json, create_message, must_answer, wrap_user_input
from modules.erm import scenario_support as sup
from modules.erm import scenario_templates as tpl
from modules.erm import scenarios as sv

# A typed sentence is business text. These patterns stop the obvious personal details before a provider sees them.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LONG_NUMBER = re.compile(r"\d[\d\s-]{8,}\d")
MAX_SENTENCE = 600
_ICE = sorted(sv.ds.ICE_ALLOWED)


def clean_sentence(text):
    text = (text or "").strip()
    if len(text) < 8:
        raise sv.ScenarioError("describe the scenario in a sentence")
    if len(text) > MAX_SENTENCE:
        raise sv.ScenarioError(f"keep it under {MAX_SENTENCE} characters")
    if _EMAIL.search(text) or _LONG_NUMBER.search(text):
        raise sv.ScenarioError("remove email addresses and long numbers: describe the situation, not the people or accounts")
    return text


def _messages(prompt):
    return [{"role": "user", "content": prompt}]


def _short(value, size):
    return (value or "").strip()[:size] if isinstance(value, str) else ""


# ── 1. Draft from a sentence ─────────────────────────────────────────────────

def draft(sentence, actor):
    sentence = clean_sentence(sentence)
    offered = {t: sup.candidates(t, actor, limit=60) for t in ("risk", "control", "kri")}
    listing = {t: [{"id": r["id"], "title": r["label"], "category": r.get("category")} for r in rows]
               for t, rows in offered.items()}
    prompt = (
        "You help a risk team set up a what-if scenario. Use ONLY the records listed. Do not invent records or numbers.\n\n"
        f"The scenario in the person's words: {wrap_user_input(sentence)}\n\n"
        f"Records the person may use (id and title): {json.dumps(listing)}\n"
        f"Allowed scenario types: {json.dumps(tpl.SCENARIO_TYPES)}\n\n"
        'Return JSON only: {"title": "<under 90 characters>", "description": "<2 to 3 sentences>", '
        '"assumptions": "<3 to 5 short assumptions in one paragraph>", "horizon": "<for example 12 months>", '
        '"scenario_type": "<one allowed type>", "links": [{"link_type": "risk|control|kri", "link_id": <id from the list>, '
        '"reason": "<one short sentence>"}]}. Link at most 10 records, only ones this scenario would really touch.'
    )
    with must_answer():
        text = create_message(_messages(prompt), max_tokens=1500, feature="erm.scenario_draft", sources=[])
    got = answer_json(text, "title", "description")
    allowed = {t: {r["id"] for r in rows} for t, rows in offered.items()}
    links = []
    for item in got.get("links") or []:
        if not isinstance(item, dict):
            continue
        ltype, lid = item.get("link_type"), item.get("link_id")
        if ltype in allowed and isinstance(lid, int) and not isinstance(lid, bool) and lid in allowed[ltype]:
            label = next(r["label"] for r in offered[ltype] if r["id"] == lid)
            links.append({"link_type": ltype, "link_id": lid, "label": label, "reason": _short(item.get("reason"), 200)})
    kind = got.get("scenario_type")
    return {"ok": True, "source": "ai", "title": _short(got.get("title"), 200),
            "description": _short(got.get("description"), 1000), "assumptions": _short(got.get("assumptions"), 1500),
            "horizon": _short(got.get("horizon"), 100),
            "scenario_type": kind if kind in tpl.SCENARIO_TYPES else "Other", "links": links[:10]}


# ── helpers for proposals about an existing scenario ─────────────────────────

def _scenario(scenario_id, actor):
    scenario = sv.get_scenario(scenario_id, bu_scope=sv.bu_scope_ids(actor))
    if not scenario:
        raise sv.ScenarioError("scenario not found")
    scenario["links"] = sv.list_scenario_links(scenario_id)
    return scenario


# ── 2. Suggest the shocks ────────────────────────────────────────────────────

def shocks(scenario_id, actor):
    scenario = _scenario(scenario_id, actor)
    impact = sv.compute_scenario_impact(scenario_id)
    past = sup.context(scenario_id, actor)["orm_events"]
    items = []
    base = {r["risk_id"]: r["baseline"] for r in impact["per_risk"]}
    for link in scenario["links"]:
        if link["link_type"] == "risk" and link["link_id"] in base:
            b = base[link["link_id"]]
            items.append({"link_type": "risk", "link_id": link["link_id"], "title": link["label"],
                          "baseline_likelihood": b["likelihood"], "baseline_impact": b["impact"]})
        elif link["link_type"] == "control":
            items.append({"link_type": "control", "link_id": link["link_id"], "title": link["label"]})
    if not items:
        raise sv.ScenarioError("link at least one risk or control first")
    prompt = (
        "You help a risk team choose what changes under a what-if scenario. Use ONLY the items listed.\n\n"
        f"Scenario: {wrap_user_input(scenario['title'])}. Assumptions: {wrap_user_input(scenario.get('assumptions') or 'none')}. "
        f"Horizon: {wrap_user_input(scenario.get('horizon') or 'not set')}.\n"
        f"Items: {json.dumps(items)}\n"
        f"Loss events in the last twelve months: {json.dumps({'count': past['count'], 'by_severity': past['by_severity']})}\n\n"
        "For a risk give likelihood (1 rare to 5 almost certain) and impact (1 low to 5 severe) as they would be IF the "
        f"scenario happened. For a control give ice_score as one of {_ICE} (lower means the control works less well). "
        'Return JSON only: {"shocks": [{"link_type": "risk|control", "link_id": <id>, "likelihood": 1-5, "impact": 1-5, '
        '"ice_score": <allowed value>, "reason": "<one short sentence>"}]}. Include only items that change.'
    )
    with must_answer():
        text = create_message(_messages(prompt), max_tokens=1800, feature="erm.scenario_shocks", sources=[f"erm/scenario/{scenario_id}"])
    got = answer_json(text, "shocks")
    offered = {(i["link_type"], i["link_id"]): i for i in items}
    out = []
    for item in got.get("shocks") or []:
        if not isinstance(item, dict):
            continue
        key = (item.get("link_type"), item.get("link_id"))
        if key not in offered:
            continue
        try:
            if key[0] == "risk":
                delta = {"likelihood_override": item.get("likelihood"), "impact_override": item.get("impact")}
            else:
                delta = {"ice_score_override": item.get("ice_score")}
            delta = sv._validate_delta(key[0], delta)
        except sv.ScenarioError:
            continue  # an out of range score is dropped, never rounded into something the model did not say
        if all(v is None for v in delta.values()):
            continue
        delta.update(source="ai", reason=_short(item.get("reason"), 300) or None)
        out.append({"link_type": key[0], "link_id": key[1], "title": offered[key]["title"], "delta": delta})
    return {"ok": True, "source": "ai", "shocks": out}


# ── 3. Find what is missing ──────────────────────────────────────────────────

def gaps(scenario_id, actor):
    scenario = _scenario(scenario_id, actor)
    linked = {(l["link_type"], l["link_id"]) for l in scenario["links"]}
    offered = {}
    for ltype in ("risk", "control", "kri", "objective", "external_context"):
        for row in sup.candidates(ltype, actor, limit=40):
            if (ltype, row["id"]) not in linked:
                offered[(ltype, row["id"])] = row["label"]
    if not offered:
        return {"ok": True, "source": "ai", "suggestions": []}
    listing = [{"link_type": k[0], "link_id": k[1], "title": v} for k, v in offered.items()]
    prompt = (
        "You help a risk team check a what-if scenario for missing pieces. Use ONLY the unlinked records listed.\n\n"
        f"Scenario: {wrap_user_input(scenario['title'])}. {wrap_user_input(scenario.get('description') or '')} "
        f"Assumptions: {wrap_user_input(scenario.get('assumptions') or 'none')}.\n"
        f"Already linked: {json.dumps([{'link_type': t, 'link_id': i} for t, i in sorted(linked)])}\n"
        f"Unlinked records: {json.dumps(listing)}\n\n"
        'Return JSON only: {"suggestions": [{"link_type": "<type>", "link_id": <id>, "reason": "<one short sentence>"}]}. '
        "At most 8, only records this scenario would really affect."
    )
    with must_answer():
        text = create_message(_messages(prompt), max_tokens=1200, feature="erm.scenario_gaps", sources=[f"erm/scenario/{scenario_id}"])
    got = answer_json(text, "suggestions")
    out = []
    for item in got.get("suggestions") or []:
        key = (item.get("link_type"), item.get("link_id")) if isinstance(item, dict) else None
        if key in offered:
            out.append({"link_type": key[0], "link_id": key[1], "label": offered[key],
                        "reason": _short(item.get("reason"), 200)})
    return {"ok": True, "source": "ai", "suggestions": out[:8]}


# ── 4. Explain the result ────────────────────────────────────────────────────

def explain(scenario_id, actor):
    scenario = _scenario(scenario_id, actor)
    impact = sv.compute_scenario_impact(scenario_id)
    if not impact["per_risk"]:
        raise sv.ScenarioError("link at least one risk before asking for an explanation")
    refs = {f"risk:{r['risk_id']}": r["title"] for r in impact["per_risk"]}
    refs.update({f"appetite:{a['category']}": a["category"] for a in impact["appetite_impact"]})
    facts = {
        "headline": sup.headline(impact)["sentence"],
        "risks": [{"ref": f"risk:{r['risk_id']}", "title": r["title"],
                   "baseline": {"irr": r["baseline"]["irr"], "rrr": r["baseline"]["rrr"], "band": r["baseline"]["band"]},
                   "scenario": {"irr": r["scenario"]["irr"], "rrr": r["scenario"]["rrr"], "band": r["scenario"]["band"]}}
                  for r in impact["per_risk"]],
        "appetite": [{"ref": f"appetite:{a['category']}", **a} for a in impact["appetite_impact"]],
        "totals": {"baseline": impact["baseline_totals"], "scenario": impact["scenario_totals"]},
    }
    prompt = (
        "Explain a what-if scenario result to a busy executive in plain language. Use ONLY the facts below; do not add "
        "numbers or causes that are not in them.\n\n"
        f"Scenario: {wrap_user_input(scenario['title'])}.\nFacts: {json.dumps(facts, default=str)}\n\n"
        'Return JSON only: {"summary": "<2 to 3 sentences>", "points": [{"text": "<one finding>", "ref": "<a ref from the facts>"}]}. '
        "Three to five points: the biggest movers, what drives them, and any appetite breach. Every point needs a ref."
    )
    with must_answer():
        text = create_message(_messages(prompt), max_tokens=1200, feature="erm.scenario_explain", sources=[f"erm/scenario/{scenario_id}"])
    got = answer_json(text, "summary", "points")
    points = []
    for item in got.get("points") or []:
        if isinstance(item, dict) and item.get("ref") in refs and _short(item.get("text"), 400):
            points.append({"text": _short(item["text"], 400), "ref": item["ref"], "ref_label": refs[item["ref"]]})
    if not points:
        raise AIUnavailable(UNREADABLE_MESSAGE, "unreadable")
    return {"ok": True, "source": "ai", "summary": _short(got.get("summary"), 700), "points": points}


# ── 5. Challenge the assumptions ─────────────────────────────────────────────

_FIELDS = {"assumptions", "horizon", "links", "owner", "review", "other"}


def challenge(scenario_id, actor):
    scenario = _scenario(scenario_id, actor)
    impact = sv.compute_scenario_impact(scenario_id)
    facts = {
        "title": scenario["title"], "type": scenario.get("scenario_type"), "assumptions": scenario.get("assumptions"),
        "horizon": scenario.get("horizon"), "has_owner": bool(scenario.get("owner_id")),
        "review_date": scenario.get("review_date"),
        "linked": {t: sum(1 for l in scenario["links"] if l["link_type"] == t)
                   for t in sv.LINK_TYPES},
        "data_quality_issues": impact["data_quality_issues"],
    }
    prompt = (
        "Act as a sceptical reviewer of a risk what-if scenario. Ask questions that test it; do not state conclusions "
        f"and do not invent facts.\n\nScenario facts: {wrap_user_input(json.dumps(facts, default=str))}\n\n"
        'Return JSON only: {"questions": [{"field": "assumptions|horizon|links|owner|review|other", "text": "<one question>"}]}. '
        "At most 6."
    )
    with must_answer():
        text = create_message(_messages(prompt), max_tokens=900, feature="erm.scenario_challenge", sources=[f"erm/scenario/{scenario_id}"])
    got = answer_json(text, "questions")
    out = []
    for item in got.get("questions") or []:
        if isinstance(item, dict) and _short(item.get("text"), 300):
            out.append({"field": item.get("field") if item.get("field") in _FIELDS else "other",
                        "text": _short(item["text"], 300)})
    return {"ok": True, "source": "ai", "questions": out[:6]}
