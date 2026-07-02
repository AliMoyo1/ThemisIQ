"""
BCM AI Service - AI-powered BCM features.

Uses the unified core.ai_client for multi-provider support
(Anthropic, DeepSeek, Gemini, OpenAI, Ollama).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from core.ai_client import create_message, is_configured, provider_name, safe_json_parse, wrap_user_input as _u

log = logging.getLogger(__name__)


# ── Plan Review ──────────────────────────────────────────────────────────────

def review_plan(plan: dict) -> dict:
    if not is_configured():
        return _stub_review_plan(plan)
    prompt = (
        "You are a business continuity expert. Review this plan and provide:\n"
        "1. A quality score from 0-100\n"
        "2. Up to 5 strengths\n"
        "3. Up to 5 weaknesses\n"
        "4. Up to 5 recommendations\n\n"
        f"Plan title: {_u(plan.get('title', 'Untitled'))}\n"
        f"Plan content:\n{_u(plan.get('content', '(empty)'))}\n\n"
        "Respond in JSON: {\"score\": int, \"strengths\": [...], "
        "\"weaknesses\": [...], \"recommendations\": [...]}"
    )
    try:
        text = create_message([{"role": "user", "content": prompt}], max_tokens=1024)
        return safe_json_parse(text, _stub_review_plan(plan))
    except Exception as exc:
        log.error("AI plan review failed: %s", exc)
        return _stub_review_plan(plan)


def _stub_review_plan(plan: dict) -> dict:
    return {
        "score": 72,
        "strengths": [
            "Plan covers key recovery procedures",
            "Clear roles and responsibilities defined",
        ],
        "weaknesses": [
            "No communication plan for external stakeholders",
            "Recovery time objectives not quantified",
        ],
        "recommendations": [
            "Add external communication templates",
            "Define measurable RTOs for each critical process",
            "Schedule a tabletop exercise to validate the plan",
        ],
    }


# ── Incident Action Suggestions ─────────────────────────────────────────────

def suggest_incident_actions(incident: dict, active_regulations: list[str] | None = None) -> list[dict]:
    if not is_configured():
        return _stub_suggest_actions(incident)
    reg_line = ""
    if active_regulations:
        reg_line = (
            f"\nActive regulatory frameworks for this organisation: {', '.join(active_regulations)}. "
            "Reference only these frameworks in your rationale — do not cite GDPR or other frameworks not in this list unless directly relevant."
        )
    prompt = (
        "You are an incident commander. Given this incident, suggest 3-5 "
        "immediate actions. Each action should have: action (str), "
        "priority (high/medium/low), rationale (str).\n\n"
        f"Incident: {_u(incident.get('title', 'Unknown'))}\n"
        f"Type: {_u(incident.get('type', 'Unknown'))}\n"
        f"Severity: {_u(incident.get('severity', 'Unknown'))}\n"
        f"Description: {_u(incident.get('description', ''))}\n"
        f"{reg_line}\n"
        "Respond in JSON array: [{\"action\": ..., \"priority\": ..., \"rationale\": ...}]"
    )
    try:
        text = create_message([{"role": "user", "content": prompt}], max_tokens=1024)
        return safe_json_parse(text, _stub_suggest_actions(incident))
    except Exception as exc:
        log.error("AI suggest actions failed: %s", exc)
        return _stub_suggest_actions(incident)


def _stub_suggest_actions(incident: dict) -> list[dict]:
    return [
        {"action": "Activate the crisis management team",
         "priority": "high",
         "rationale": "Ensures coordinated response from the outset"},
        {"action": "Notify affected stakeholders",
         "priority": "high",
         "rationale": "Regulatory and contractual notification requirements"},
        {"action": "Begin impact assessment",
         "priority": "medium",
         "rationale": "Quantify the scope before committing recovery resources"},
    ]


# ── Document Chunking (for RAG) ─────────────────────────────────────────────

def chunk_text(content: str, max_chars: int = 1500) -> list[dict]:
    if not content:
        return []
    overlap = 200
    chunks = []
    start = 0
    idx = 0
    while start < len(content):
        end = min(start + max_chars, len(content))
        chunks.append({"chunk_index": idx, "text": content[start:end]})
        idx += 1
        start = end - overlap if end < len(content) else end
    return chunks


# ── RAG Question Answering ───────────────────────────────────────────────────

def rag_ask(question: str) -> tuple[str, list[int]]:
    if not is_configured():
        return _stub_rag_ask(question)

    from modules.bcm import data_service as ds
    stop = {"the","a","an","is","are","was","were","what","which","how","does","do",
            "in","of","for","on","to","and","or","with","this","that","it","be"}
    keywords = [w.lower() for w in question.split() if len(w) > 2 and w.lower() not in stop]

    chunks = []
    if keywords:
        chunks = ds.search_chunks(keywords[:3], limit=6)
        if not chunks and len(keywords) > 1:
            chunks = ds.search_chunks(keywords[:1], limit=6)

    if not chunks:
        try:
            text = create_message(
                [{"role": "user", "content": _u(question)}],
                system=(
                    "You are a business continuity management expert. "
                    "The user asked a question but no uploaded documents matched. "
                    "Answer from general BCM knowledge and mention that no specific "
                    "documents were found in the knowledge base."
                ),
                max_tokens=1024,
            )
            return text, []
        except Exception as exc:
            log.error("RAG fallback failed: %s", exc)
            return _stub_rag_ask(question)

    context_parts = []
    cited_ids = []
    for c in chunks:
        context_parts.append(f"[Chunk {c['id']}]\n{c['content']}")
        cited_ids.append(c["id"])
    context = "\n\n---\n\n".join(context_parts)

    prompt = (
        f"Using the following excerpts from the organisation's BCM documents, "
        f"answer the question below. Cite chunk numbers where relevant.\n\n"
        f"DOCUMENTS:\n{context}\n\n"
        f"QUESTION: {_u(question)}"
    )
    try:
        text = create_message([{"role": "user", "content": prompt}], max_tokens=1500)
        return text, cited_ids
    except Exception as exc:
        log.error("RAG ask failed: %s", exc)
        return _stub_rag_ask(question)


def _stub_rag_ask(question: str) -> tuple[str, list[int]]:
    return (
        f"This is a placeholder answer for: \"{question}\". "
        f"Full RAG retrieval will be enabled once {provider_name()} API key is configured.",
        [],
    )


# ── Chat ─────────────────────────────────────────────────────────────────────

def chat(history: list[dict]) -> str:
    if not is_configured():
        return _stub_chat(history)
    try:
        return create_message(
            history,
            system=(
                "You are a business continuity management expert embedded in an "
                "enterprise BCM tool called ThemisIQ. Help the user with "
                "continuity planning, incident management, risk assessment, "
                "and regulatory compliance. Be concise and actionable."
            ),
            max_tokens=2048,
        )
    except Exception as exc:
        log.error("AI chat failed: %s", exc)
        return _stub_chat(history)


def _stub_chat(history: list[dict]) -> str:
    last = history[-1]["content"] if history else ""
    return (
        f"[AI stub] I received your message about: \"{last[:80]}...\". "
        f"Configure {provider_name()} API key to enable the AI chatbot."
    )


# ── Plan Generator ───────────────────────────────────────────────────────────

def generate_plan(scenario: str, scope: str, industry: str = "", extra_context: str = "") -> str:
    if not is_configured():
        return _stub_generate_plan(scenario, scope, industry)
    industry_context = f" for a {_u(industry)} organisation" if industry else ""
    prompt = (
        f"Generate a detailed {_u(scenario)} business continuity plan{industry_context}.\n\n"
        f"Scope: {_u(scope)}\n"
    )
    if extra_context:
        prompt += f"\nAdditional context: {_u(extra_context)}\n"
    prompt += (
        "\nStructure the plan with these sections:\n"
        "1. Purpose & Scope\n2. Roles & Responsibilities\n"
        "3. Activation Criteria\n4. Recovery Procedures\n"
        "5. Communication Plan\n6. Resource Requirements\n"
        "7. Testing & Maintenance\n\n"
        "Use markdown formatting. Be specific and actionable."
    )
    try:
        return create_message([{"role": "user", "content": prompt}], max_tokens=4096)
    except Exception as exc:
        log.error("AI plan generation failed: %s", exc)
        return _stub_generate_plan(scenario, scope, industry)


def _stub_generate_plan(scenario: str, scope: str, industry: str = "") -> str:
    label = f"{scenario}" + (f" - {industry}" if industry else "")
    return (
        f"# {label}\n\n"
        f"**Scope:** {scope}\n\n"
        "## 1. Purpose & Scope\n\nThis plan provides recovery procedures.\n\n"
        "## 2. Roles & Responsibilities\n\n"
        "| Role | Responsibility |\n|---|---|\n"
        "| BCM Manager | Overall plan ownership |\n"
        "| Incident Commander | Activation decision |\n\n"
        "## 3. Activation Criteria\n\nActivated when disruption exceeds 4 hours.\n\n"
        "## 4. Recovery Procedures\n\n1. Assess impact\n2. Notify stakeholders\n"
        "3. Execute workarounds\n4. Restore normal operations\n\n"
        "## 5. Communication Plan\n\nInternal: via Teams/email. External: via press office.\n\n"
        "## 6. Resource Requirements\n\n- Backup site access\n- Emergency contact list\n\n"
        "## 7. Testing & Maintenance\n\nReviewed quarterly. Tabletop exercise annually.\n\n"
        f"*[Stub plan. Configure {provider_name()} API key for full AI generation.]*"
    )


# ── Board Report Narrative ───────────────────────────────────────────────────

def generate_board_narrative(stats: dict) -> str:
    if not is_configured():
        return _stub_board_narrative(stats)
    prompt = (
        "You are writing the executive narrative section of a board-level "
        "business continuity report. Given the following statistics, write "
        "a concise 3-4 paragraph narrative suitable for senior leadership.\n\n"
        f"Statistics: {json.dumps(stats, default=str)}\n\n"
        "Cover: overall programme health, key risks, incident trends, "
        "and recommended actions. Use professional tone."
    )
    try:
        return create_message([{"role": "user", "content": prompt}], max_tokens=1024)
    except Exception as exc:
        log.error("AI board narrative failed: %s", exc)
        return _stub_board_narrative(stats)


def _stub_board_narrative(stats: dict) -> str:
    total_plans = stats.get("plans", 0)
    open_incidents = stats.get("open_incidents", 0)
    return (
        "## Executive Summary\n\n"
        f"The BCM programme currently maintains **{total_plans}** continuity "
        f"plans with **{open_incidents}** open incident(s).\n\n"
        "Key areas of focus: updating plans due for review and completing scheduled exercises.\n\n"
        f"*[Stub narrative. Configure {provider_name()} API key for full AI generation.]*"
    )
