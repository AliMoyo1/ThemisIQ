"""
ERM AI Service - AI-powered risk scoring, treatment suggestions, board narrative, chat.

Uses the unified core.ai_client for multi-provider support
(Anthropic, DeepSeek, Gemini, OpenAI, Ollama).
"""
import json
import logging

from core.ai_client import create_message, is_configured, provider_name, safe_json_parse, wrap_user_input as _u

log = logging.getLogger(__name__)


def score_risk(title: str, description: str, category: str = "") -> dict:
    if not is_configured():
        return _stub_score(title)
    prompt = (
        f"You are an enterprise risk manager. Score this risk:\n\n"
        f"Title: {_u(title)}\n"
        f"Description: {_u(description)}\n"
        f"Category hint: {_u(category) if category else 'unknown'}\n\n"
        "Return JSON only:\n"
        '{"likelihood": <1-5>, "impact": <1-5>, "category": "<strategic|operational|compliance|financial|reputational|technology|third_party|environmental>", '
        '"treatment": "<mitigate|accept|avoid|transfer>", "rationale": "<1 sentence>"}'
    )
    try:
        text = create_message([{"role": "user", "content": prompt}], max_tokens=512)
        return safe_json_parse(text, _stub_score(title))
    except Exception as exc:
        log.error("ERM AI score failed: %s", exc)
        return _stub_score(title)


def _stub_score(title: str) -> dict:
    return {
        "likelihood": 3, "impact": 3,
        "category": "operational",
        "treatment": "mitigate",
        "rationale": f"Stub scoring for '{title}'. Configure {provider_name()} API key for real AI scoring.",
    }


def suggest_treatment(title: str, description: str, category: str, likelihood: int, impact: int) -> dict:
    if not is_configured():
        return _stub_treatment(title)
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
    try:
        text = create_message([{"role": "user", "content": prompt}], max_tokens=800)
        return safe_json_parse(text, _stub_treatment(title))
    except Exception as exc:
        log.error("ERM treatment suggestion failed: %s", exc)
        return _stub_treatment(title)


def _stub_treatment(title: str) -> dict:
    return {
        "treatment": "mitigate",
        "treatment_plan": f"Implement controls to reduce the likelihood and impact of '{title}'. Monitor quarterly.",
        "suggested_controls": "Risk assessment, management oversight, staff training",
        "recommended_owner": "Risk Manager",
    }


def generate_board_narrative(stats: dict, appetite_status: list) -> str:
    if not is_configured():
        return _stub_board_narrative(stats)
    breached = [a["category"] for a in appetite_status if a.get("breached")]
    prompt = (
        "You are writing the Enterprise Risk section of a board-level governance report. "
        "Write a professional 3-4 paragraph executive narrative.\n\n"
        f"Risk Statistics: {json.dumps(stats, default=str)}\n"
        f"Risk Appetite Breaches: {breached or 'None'}\n\n"
        "Cover: overall risk profile, critical/high risks, appetite status, "
        "top risk categories, and recommended board actions. "
        "Use professional tone. Format as plain paragraphs (no markdown headers)."
    )
    try:
        return create_message([{"role": "user", "content": prompt}], max_tokens=1500)
    except Exception as exc:
        log.error("ERM board narrative failed: %s", exc)
        return _stub_board_narrative(stats)


def _stub_board_narrative(stats: dict) -> str:
    total = stats.get("total_risks", 0)
    crit = stats.get("critical", 0)
    breaches = stats.get("appetite_breaches", 0)
    return (
        f"The enterprise risk register currently contains {total} open risk items, "
        f"of which {crit} are rated critical. "
        f"{'Risk appetite is being breached in ' + str(breaches) + ' category/categories, requiring immediate board attention.' if breaches else 'All risks are currently within approved appetite thresholds.'}\n\n"
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
        return create_message(history, system=system, max_tokens=2048)
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
    if not is_configured():
        return {
            "cause": "inadequate controls",
            "event": "an adverse risk event materialises",
            "consequence": "financial or reputational harm to the organisation",
            "full_statement": f"Due to inadequate controls, there is a risk that an adverse {category} event materialises, resulting in financial or reputational harm to the organisation."
        }
    prompt = (
        f"You are an enterprise risk manager writing a structured risk statement.\n\n"
        f"Category: {_u(category)}\n"
        f"Description: {_u(description)}\n\n"
        "Write a structured risk statement in three parts. Return JSON only:\n"
        '{"cause":"Due to [root cause / failure]","event":"there is a risk that [risk event]","consequence":"resulting in [impact/consequence]","full_statement":"[complete sentence combining all three]"}'
    )
    try:
        text = create_message([{"role": "user", "content": prompt}], max_tokens=300)
        return safe_json_parse(text, {"full_statement": description})
    except Exception as exc:
        log.error("ERM generate_risk_statement failed: %s", exc)
        return {"full_statement": description}


def suggest_assessment_questions(assessment_type: str, linked_risk_titles: list, existing_questions: list) -> list:
    if not is_configured():
        return [
            {"question": "How effectively are current controls mitigating identified risks?", "question_type": "scale", "weight": 1.0},
            {"question": "Are risk owners clearly assigned and accountable?", "question_type": "yes_no", "weight": 1.0},
            {"question": "What gaps exist in the current risk treatment plan?", "question_type": "text", "weight": 0.5},
        ]
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
    try:
        text = create_message([{"role": "user", "content": prompt}], max_tokens=600)
        return safe_json_parse(text, [])
    except Exception as exc:
        log.error("ERM suggest_assessment_questions failed: %s", exc)
        return []


def identify_risks_from_responses(responses_text: str, assessment_title: str) -> list:
    if not is_configured():
        return [{"title": "Risk identified from assessment", "description": "Review assessment responses for details.",
                 "category": "operational", "likelihood": 3, "impact": 3, "treatment": "mitigate"}]
    prompt = (
        f"You are an enterprise risk manager reviewing assessment responses for '{_u(assessment_title)}'.\n\n"
        f"Assessment responses:\n{_u(responses_text[:3000])}\n\n"
        "Identify up to 5 specific risks indicated by these responses. "
        "For each, provide a risk title, description, category, likelihood (1-5), impact (1-5), and suggested treatment.\n"
        "Return JSON array only:\n"
        '[{"title":"...","description":"...","category":"strategic|operational|compliance|financial|reputational|technology|third_party|environmental","likelihood":3,"impact":3,"treatment":"mitigate|accept|avoid|transfer"}]'
    )
    try:
        text = create_message([{"role": "user", "content": prompt}], max_tokens=800)
        return safe_json_parse(text, [])
    except Exception as exc:
        log.error("ERM identify_risks_from_responses failed: %s", exc)
        return []


def smart_remediation_plan(title: str, description: str, category: str, score: int) -> dict:
    if not is_configured():
        return {
            "summary": "Implement standard risk controls for this category.",
            "steps": [
                {"step": 1, "action": "Assign risk owner and define accountability", "timeline": "Week 1", "responsible": "Risk Manager"},
                {"step": 2, "action": "Conduct detailed risk assessment", "timeline": "Week 2", "responsible": "Risk Owner"},
                {"step": 3, "action": "Implement primary controls", "timeline": "Month 1", "responsible": "Risk Owner"},
                {"step": 4, "action": "Monitor and report on effectiveness", "timeline": "Ongoing", "responsible": "Risk Manager"},
            ],
            "cost_tier": "medium",
            "success_criteria": "Risk score reduced below appetite threshold"
        }
    prompt = (
        f"You are a GRC expert creating a remediation plan.\n\n"
        f"Risk: {_u(title)}\nDescription: {_u(description)}\nCategory: {_u(category)}\nScore: {score}/25\n\n"
        "Create a practical step-by-step remediation plan. Return JSON only:\n"
        '{"summary":"...","steps":[{"step":1,"action":"...","timeline":"...","responsible":"..."}],"cost_tier":"low|medium|high","success_criteria":"..."}'
    )
    try:
        text = create_message([{"role": "user", "content": prompt}], max_tokens=800)
        return safe_json_parse(text, {"summary": "Unable to generate plan."})
    except Exception as exc:
        log.error("ERM smart_remediation_plan failed: %s", exc)
        return {"summary": "Unable to generate plan. Please configure AI provider."}
