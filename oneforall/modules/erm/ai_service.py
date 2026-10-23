"""
ERM AI Service - AI-powered risk scoring, treatment suggestions, board narrative, chat.

Uses the unified core.ai_client for multi-provider support
(Anthropic, OpenRouter, DeepSeek, Gemini, OpenAI, Ollama).
"""
import json
import logging

from core.ai_client import (
    AIUnavailable, UNREADABLE_MESSAGE, answer_json, create_message, create_message_web_search,
    is_configured, must_answer, provider_name, safe_json_parse, wrap_user_input as _u,
)
from config import settings
from modules.erm.data_service import create_emerging, emerging_title_exists, build_org_context

log = logging.getLogger(__name__)


def _scale(value, low: int = 1, high: int = 5) -> int:
    """A score the assistant gave, as a whole number inside the scale, or AIUnavailable."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise AIUnavailable(UNREADABLE_MESSAGE, "unreadable") from None
    if not low <= number <= high:
        raise AIUnavailable(UNREADABLE_MESSAGE, "unreadable")
    return number


def score_risk(title: str, description: str, category: str = "") -> dict:
    """A suggested likelihood and impact for one risk. Raises AIUnavailable rather than return a default score."""
    with must_answer():
        prompt = (
            f"You are an enterprise risk manager. Score this risk:\n\n"
            f"Title: {_u(title)}\n"
            f"Description: {_u(description)}\n"
            f"Category hint: {_u(category) if category else 'unknown'}\n\n"
            "Return JSON only:\n"
            '{"likelihood": <1-5>, "impact": <1-5>, "category": "<strategic|operational|compliance|financial|reputational|technology|third_party|environmental>", '
            '"treatment": "<mitigate|accept|avoid|transfer>", "rationale": "<1 sentence>"}'
        )
        text = create_message([{"role": "user", "content": prompt}], max_tokens=512, feature="erm.score_risk")
        got = answer_json(text, "likelihood", "impact")
        got["likelihood"], got["impact"] = _scale(got["likelihood"]), _scale(got["impact"])
        return got


def suggest_scores(title: str, description: str, category: str, framework_context: dict) -> dict:
    """Suggest likelihood and per-dimension impact scores using framework context."""
    dims = framework_context.get("dimensions") or []
    likelihood_scale = framework_context.get("likelihood") or []
    dim_names = [d["name"] for d in dims]

    with must_answer():
        dim_descriptions = []
        for d in dims:
            levels_text = "; ".join(
                f"{lv['level']}={lv.get('description', '')}" for lv in sorted(d.get("levels", []), key=lambda x: x["level"])
            )
            dim_descriptions.append(f"  - {d['name']}: [{levels_text}]")

        likelihood_text = "; ".join(
            f"{lv['level']}={lv.get('label', '')} ({lv.get('description', '')})"
            for lv in sorted(likelihood_scale, key=lambda x: x["level"])
        )

        prompt = (
            "You are an enterprise risk scoring expert. Based on the risk details and the "
            "organisation's rating framework below, suggest a likelihood score and an impact "
            "score for each dimension.\n\n"
            f"Risk Title: {_u(title)}\n"
            f"Description: {_u(description)}\n"
            f"Category: {_u(category)}\n\n"
            "LIKELIHOOD SCALE:\n"
            f"  {likelihood_text}\n\n"
            "IMPACT DIMENSIONS (score each 1-5 using the level descriptions):\n"
            + "\n".join(dim_descriptions) + "\n\n"
            "Return JSON only:\n"
            '{"likelihood": <1-5>, "dimension_scores": [{"dimension_name": "<name>", "score": <1-5>}], '
            '"rationale": "<2-3 sentences explaining your scoring reasoning>"}'
        )
        text = create_message([{"role": "user", "content": prompt}], max_tokens=1024, feature="erm.suggest_scores")
        result = answer_json(text, "likelihood")
        valid = []
        for ds in result.get("dimension_scores") or []:
            if isinstance(ds, dict) and ds.get("dimension_name") in dim_names and isinstance(ds.get("score"), (int, float)):
                ds["score"] = max(1, min(5, int(ds["score"])))
                valid.append(ds)
        result["dimension_scores"] = valid
        result["likelihood"] = _scale(result["likelihood"])
        return result


def suggest_treatment(title: str, description: str, category: str, likelihood: int, impact: int) -> dict:
    with must_answer():
        score = likelihood * impact
        prompt = (
            f"Enterprise risk treatment request:\n\n"
            f"Risk: {_u(title)}\nDescription: {_u(description)}\n"
            f"Category: {_u(category)}\nScore: {score} (Likelihood {likelihood}/5, Impact {impact}/5)\n\n"
            "Suggest a treatment plan. Return JSON:\n"
            '{"treatment": "<mitigate|accept|avoid|transfer>", '
            '"treatment_plan": "<detailed 2-3 sentence plan>", '
            '"suggested_controls": "<comma-separated control measures>", '
            '"recommended_owner": "<job title best suited to own this risk>"}'
        )
        text = create_message([{"role": "user", "content": prompt}], max_tokens=800, feature="erm.suggest_treatment")
        return answer_json(text, "treatment")


def suggest_ice_rationale(control_title: str, control_description: str, ice_suggested: int, factors: dict) -> str:
    """One-sentence rationale for a deterministically suggested ICE score,
    based on the T1.3 factor breakdown. Returns "" on any failure or when
    AI is unconfigured -- callers must treat this as optional narrative
    layered on top of the deterministic suggestion, never required."""
    if not is_configured():
        return ""
    passing = [k.replace("_", " ") for k, v in (factors or {}).items() if v]
    prompt = (
        f"A control effectiveness scoring system suggests an ICE (control "
        f"effectiveness) score of {ice_suggested}% for this control, based on "
        f"automated factors.\n\n"
        f"Control: {_u(control_title)}\nDescription: {_u(control_description)}\n"
        f"Passing factors: {', '.join(passing) or 'none'}\n\n"
        "Write ONE short sentence (under 25 words) explaining why this score "
        "is reasonable. Plain text only, no JSON, no markdown."
    )
    try:
        text = create_message([{"role": "user", "content": prompt}], max_tokens=100, feature="erm.suggest_ice_rationale")
        return (text or "").strip()
    except Exception as exc:
        log.error("ERM ICE rationale failed: %s", exc)
        return ""


def generate_board_narrative(stats: dict, appetite_status: list) -> str:
    if not is_configured():
        return _stub_board_narrative(stats, appetite_status)
    breached = [a["category"] for a in appetite_status if a.get("breached")]
    prompt = (
        "You are writing the Enterprise Risk section of a board-level governance report. "
        "Write a professional 3-4 paragraph executive narrative.\n\n"
        f"Risk Statistics: {json.dumps(stats, default=str)}\n"
        f"Risk appetite: {len(appetite_status)} categories have a limit; above the limit: {breached or 'none'}."
        f"{'' if appetite_status else ' No limit is set, so do not say that risk is within appetite.'}\n\n"
        "Cover: overall risk profile, critical/high risks, appetite status, "
        "top risk categories, and recommended board actions. "
        "Use professional tone. Format as plain paragraphs (no markdown headers)."
    )
    try:
        return create_message([{"role": "user", "content": prompt}], max_tokens=1500, feature="erm.generate_board_narrative")
    except Exception as exc:
        log.error("ERM board narrative failed: %s", exc)
        return _stub_board_narrative(stats, appetite_status)


def _stub_board_narrative(stats: dict, appetite_status: list = None) -> str:
    total = stats.get("total_risks", 0)
    crit = stats.get("critical", 0)
    breaches = stats.get("appetite_breaches", 0)
    limits = appetite_status or []
    if not limits:
        appetite_line = "No risk appetite is set, so exposure cannot be compared with appetite."
    elif breaches:
        appetite_line = f"{breaches} risk(s) are above the appetite set for their category, requiring board attention."
    else:
        appetite_line = "Every risk is within the appetite set for its category."
    return (
        f"The enterprise risk register currently contains {total} open risk items, "
        f"of which {crit} are rated critical. {appetite_line}\n\n"
        "The Board is requested to note the current risk profile and approve the proposed treatment plans "
        "for any above-appetite exposures.\n\n"
        f"*[Full AI narrative requires {provider_name()} API key to be configured.]*"
    )


def chat(history: list, stats: dict = None) -> str:
    if not is_configured():
        return _stub_chat(history)
    system = (
        "You are an Enterprise Risk Management expert embedded in ThemisIQ. "
        "Help the user with risk identification, scoring, treatment planning, "
        "regulatory compliance, and risk appetite management. "
        "Be concise, actionable, and professional. "
        "Reference ISO 31000, COSO ERM, and relevant industry standards where appropriate."
    )
    if stats:
        system += f"\n\nCurrent platform risk stats: {json.dumps(stats, default=str)}"
    try:
        return create_message(history, system=system, max_tokens=2048, feature="erm.chat")
    except Exception as exc:
        log.error("ERM chat failed: %s", exc)
        return _stub_chat(history)


def _stub_chat(history: list) -> str:
    last = history[-1]["content"] if history else ""
    return (
        f"[ERM AI stub] I received: \"{last[:80]}...\". "
        f"Configure {provider_name()} API key for full AI assistance."
    )


def generate_risk_statement(category: str, description: str) -> dict:
    with must_answer():
        prompt = (
            f"You are an enterprise risk manager writing a structured risk statement.\n\n"
            f"Category: {_u(category)}\n"
            f"Description: {_u(description)}\n\n"
            "Write a structured risk statement in three parts. Return JSON only:\n"
            '{"cause":"Due to [root cause / failure]","event":"there is a risk that [risk event]","consequence":"resulting in [impact/consequence]","full_statement":"[complete sentence combining all three]"}'
        )
        text = create_message([{"role": "user", "content": prompt}], max_tokens=300, feature="erm.generate_risk_statement")
        return answer_json(text, "full_statement")


def suggest_assessment_questions(assessment_type: str, linked_risk_titles: list, existing_questions: list) -> list:
    with must_answer():
        existing_q_text = "\n".join(f"- {q}" for q in existing_questions) if existing_questions else "None yet"
        risk_context = ", ".join(linked_risk_titles[:5]) if linked_risk_titles else "general enterprise risks"
        prompt = (
            f"You are an enterprise risk management expert designing a self-assessment questionnaire.\n\n"
            f"Assessment type: {_u(assessment_type)}\n"
            f"Linked risks: {_u(risk_context)}\n"
            f"Existing questions (do not repeat):\n{_u(existing_q_text)}\n\n"
            "Suggest up to 8 new assessment questions. For each, specify the most appropriate response type.\n"
            "Return JSON array only:\n"
            '[{"question":"...","question_type":"scale|yes_no|text|multiple_choice","weight":1.0}]'
        )
        text = create_message([{"role": "user", "content": prompt}], max_tokens=600, feature="erm.suggest_assessment_questions")
        return answer_json(text, kind=list)


def identify_risks_from_responses(responses_text: str, assessment_title: str) -> list:
    with must_answer():
        prompt = (
            f"You are an enterprise risk manager reviewing assessment responses for '{_u(assessment_title)}'.\n\n"
            f"Assessment responses:\n{_u(responses_text[:3000])}\n\n"
            "Identify up to 5 specific risks indicated by these responses. "
            "For each, provide a risk title, description, category, likelihood (1-5), impact (1-5), and suggested treatment.\n"
            "Return JSON array only:\n"
            '[{"title":"...","description":"...","category":"strategic|operational|compliance|financial|reputational|technology|third_party|environmental","likelihood":3,"impact":3,"treatment":"mitigate|accept|avoid|transfer"}]'
        )
        text = create_message([{"role": "user", "content": prompt}], max_tokens=800, feature="erm.identify_risks_from_responses")
        return answer_json(text, kind=list)


def smart_remediation_plan(title: str, description: str, category: str, score: int) -> dict:
    with must_answer():
        prompt = (
            f"You are a GRC expert creating a remediation plan.\n\n"
            f"Risk: {_u(title)}\nDescription: {_u(description)}\nCategory: {_u(category)}\nScore: {score}/25\n\n"
            "Create a practical step-by-step remediation plan. Return JSON only:\n"
            '{"summary":"...","steps":[{"step":1,"action":"...","timeline":"...","responsible":"..."}],"cost_tier":"low|medium|high","success_criteria":"..."}'
        )
        text = create_message([{"role": "user", "content": prompt}], max_tokens=800, feature="erm.smart_remediation_plan")
        return answer_json(text, "summary", "steps")


# ── PLAN-28: External context horizon scan ────────────────────────────────────

def _emerging_context_lines(org_context: dict) -> str:
    pillars = ", ".join(org_context.get("pillars") or []) or "none listed"
    frameworks = ", ".join(org_context.get("frameworks") or []) or "none listed"
    categories = ", ".join(c["category"] for c in (org_context.get("top_categories") or [])) or "none listed"
    return (
        f"Pillars: {_u(pillars)}\n"
        f"Frameworks in use: {_u(frameworks)}\n"
        f"Top risk categories today: {_u(categories)}\n"
    )


def _emerging_scan_token_budget() -> int:
    """Return a bounded budget large enough for reasoning plus visible JSON."""
    configured = int(getattr(settings, "ERM_SCAN_MAX_TOKENS", 3000))
    return max(2000, min(configured, 8000))


def scan_emerging_risks_grounded(org_context: dict) -> list:
    """Grounded horizon scan using the configured provider's web search. Stores
    survivors directly via create_emerging and returns their new ids.

    Any item whose source_url does not exactly match one of the citations
    the API actually returned is DISCARDED as a web-sourced item and
    re-stored with source_url NULL and the knowledge caveat instead -- a
    model can still write a plausible-looking URL into its JSON, and only
    the citations array proves a page was actually retrieved.

    Raises whatever create_message_web_search raises (e.g. RuntimeError
    when web search is disabled, unsupported, or returns no verifiable
    citations) so the caller can fall back to scan_emerging_risks(); does
    not swallow that exception itself."""
    prompt = (
        "Search the allowed sources for enterprise risks that are NEW or RISING "
        "in the last 12 months, relevant to an organisation with this profile:\n"
        + _emerging_context_lines(org_context) +
        '\nReturn a JSON array of at most 5 objects, each shaped exactly as: '
        '{"title": "<risk title>", "summary": "<1-2 sentence summary>", '
        '"pillar": "<one of the organisation pillars, or empty>", '
        '"standard_ref": "<related standard/framework, or empty>", '
        '"source_url": "<the exact URL of the source you found this from>", '
        '"rationale": "<why this is relevant now>"}. '
        'Respond with JSON only, no prose before or after. '
        'If uncertain about a candidate, omit it rather than guess -- return fewer items.'
    )
    result = create_message_web_search(
        [{"role": "user", "content": prompt}],
        max_tokens=_emerging_scan_token_budget(),
        max_searches=getattr(settings, "ERM_SCAN_MAX_SEARCHES", 8),
        allowed_domains=getattr(settings, "ERM_SCAN_ALLOWED_DOMAINS", None),
        feature="erm.scan_emerging_risks_grounded",
    )
    items = safe_json_parse(result.get("text", ""), []) or []
    if not isinstance(items, list):
        return []
    citations = result.get("citations") or []
    citation_urls = {c["url"] for c in citations if c.get("url")}
    citation_titles = {c["url"]: c.get("title", "") for c in citations if c.get("url")}

    created = []
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        if emerging_title_exists(title):
            continue
        rationale = str(item.get("rationale") or "").strip()
        raw_url = str(item.get("source_url") or "").strip()
        base = {
            "title": title,
            "summary": item.get("summary"),
            "pillar": item.get("pillar") or None,
            "standard_ref": item.get("standard_ref") or None,
        }
        if raw_url and raw_url in citation_urls:
            cited_title = citation_titles.get(raw_url) or raw_url
            eid = create_emerging(
                {**base, "source_url": raw_url,
                 "source_note": f"Live web scan ({cited_title}). {rationale}".strip()},
                origin="ai_scan_web",
            )
        else:
            eid = create_emerging(
                {**base, "source_url": None,
                 "source_note": f"AI-generated (model knowledge, verify before acting). {rationale}".strip()},
                origin="ai_scan",
            )
        created.append(eid)
    return created


def scan_emerging_risks(org_context: dict, *, raise_on_error: bool = False) -> list:
    """Knowledge-only horizon scan: the fallback for non-anthropic
    providers, web search disabled for the org, or a failed grounded call.
    Prompt forbids fabricating citations or URLs; every stored item
    carries the knowledge caveat and a NULL source_url. Returns [] on any
    failure or when AI isn't configured. ``raise_on_error=True`` is reserved
    for the durable job orchestrator, which needs to distinguish a valid empty
    result from a provider failure and persist a terminal failed state."""
    if not is_configured():
        if raise_on_error:
            raise RuntimeError("AI provider is not configured")
        return []
    prompt = (
        "Based on your training knowledge (NOT a live search), suggest enterprise "
        "risks that may be NEW or RISING for an organisation with this profile:\n"
        + _emerging_context_lines(org_context) +
        '\nReturn a JSON array of at most 5 objects, each shaped exactly as: '
        '{"title": "<risk title>", "summary": "<1-2 sentence summary>", '
        '"pillar": "<one of the organisation pillars, or empty>", '
        '"standard_ref": "<related standard/framework, or empty>", '
        '"rationale": "<why this is relevant now>"}. '
        'Respond with JSON only, no prose before or after. '
        'Do NOT invent or include any source_url or citation field -- you have no '
        'live source for this response.'
    )
    try:
        text = create_message(
            [{"role": "user", "content": prompt}],
            max_tokens=_emerging_scan_token_budget(),
            feature="erm.scan_emerging_risks",
        )
    except Exception as exc:
        log.warning("ERM knowledge-only scan failed: %s", exc)
        if raise_on_error:
            raise RuntimeError("ERM knowledge-only AI call failed") from exc
        return []
    items = safe_json_parse(text, []) or []
    if not isinstance(items, list):
        return []
    created = []
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        if emerging_title_exists(title):
            continue
        rationale = str(item.get("rationale") or "").strip()
        eid = create_emerging(
            {
                "title": title,
                "summary": item.get("summary"),
                "pillar": item.get("pillar") or None,
                "standard_ref": item.get("standard_ref") or None,
                "source_url": None,
                "source_note": f"AI-generated (model knowledge, verify before acting). {rationale}".strip(),
            },
            origin="ai_scan",
        )
        created.append(eid)
    return created


def run_emerging_scan() -> dict:
    """Shared orchestration for the on-demand scan endpoint and the weekly
    scheduled job: build org context, try the grounded (live web search)
    path first, fall back to knowledge-only on any failure -- unsupported
    provider, no key, web search disabled, missing citations, or a parse
    error -- or an empty grounded result. Opens and closes its own db
    connection and returns a sanitized error code rather than allowing a
    provider/parser/database exception to escape into a route or scheduler."""
    from database import get_db as _get_db
    try:
        db = _get_db()
        try:
            org_context = build_org_context(db)
        finally:
            db.close()
    except Exception as exc:
        log.warning("ERM emerging-risk context build failed (%s)", type(exc).__name__)
        return {"created": 0, "grounded": False, "error": "context_unavailable"}

    grounded = False
    created_ids = []
    try:
        created_ids = scan_emerging_risks_grounded(org_context)
        grounded = bool(created_ids)
    except Exception as exc:
        log.warning("Grounded emerging-risk scan unavailable, falling back to knowledge-only: %s", exc)
    if not created_ids:
        try:
            created_ids = scan_emerging_risks(org_context, raise_on_error=True)
        except Exception as exc:
            log.warning("ERM emerging-risk fallback unavailable (%s)", type(exc).__name__)
            return {"created": 0, "grounded": False, "error": "ai_unavailable"}
        grounded = False

    return {"created": len(created_ids), "grounded": grounded}
