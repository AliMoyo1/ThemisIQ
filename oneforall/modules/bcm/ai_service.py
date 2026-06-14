"""
BCM AI Service — Stub layer for all AI-powered BCM features.

Each function wraps an Anthropic Claude API call.  During development
the stubs return canned responses so the rest of the module can be
tested without burning API credits.

Functions are fleshed out in Task #25.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

# ── Anthropic Client (lazy) ─────────────────────────────────────────────────

_client = None

def _get_client():
    """Return a cached Anthropic client (created on first call)."""
    global _client
    if _client is None:
        try:
            import anthropic
            _client = anthropic.Anthropic(
                api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            )
        except ImportError:
            log.warning("anthropic package not installed — AI stubs will be used")
    return _client

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")


# ── Plan Review ──────────────────────────────────────────────────────────────

def review_plan(plan: dict) -> dict:
    """
    AI-assisted review of a continuity plan.

    Returns dict with keys: score (int 0-100), strengths (list[str]),
    weaknesses (list[str]), recommendations (list[str]).
    """
    client = _get_client()
    if not client or not os.getenv("ANTHROPIC_API_KEY"):
        return _stub_review_plan(plan)

    prompt = (
        "You are a business continuity expert. Review this plan and provide:\n"
        "1. A quality score from 0-100\n"
        "2. Up to 5 strengths\n"
        "3. Up to 5 weaknesses\n"
        "4. Up to 5 recommendations\n\n"
        f"Plan title: {plan.get('title', 'Untitled')}\n"
        f"Plan content:\n{plan.get('content', '(empty)')}\n\n"
        "Respond in JSON: {\"score\": int, \"strengths\": [...], "
        "\"weaknesses\": [...], \"recommendations\": [...]}"
    )
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text
        return json.loads(text)
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

def suggest_incident_actions(incident: dict) -> list[dict]:
    """
    Given an incident dict, suggest next actions.

    Returns list of dicts: [{action, priority, rationale}, ...]
    """
    client = _get_client()
    if not client or not os.getenv("ANTHROPIC_API_KEY"):
        return _stub_suggest_actions(incident)

    prompt = (
        "You are an incident commander. Given this incident, suggest 3-5 "
        "immediate actions. Each action should have: action (str), "
        "priority (high/medium/low), rationale (str).\n\n"
        f"Incident: {incident.get('title', 'Unknown')}\n"
        f"Type: {incident.get('type', 'Unknown')}\n"
        f"Severity: {incident.get('severity', 'Unknown')}\n"
        f"Description: {incident.get('description', '')}\n\n"
        "Respond in JSON array: [{\"action\": ..., \"priority\": ..., \"rationale\": ...}]"
    )
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(resp.content[0].text)
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
    """
    Split document text into overlapping chunks for embedding/search.

    Returns list of dicts: [{chunk_index, text}, ...]
    """
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
    """
    Answer a question using the BCM document knowledge base.

    Uses keyword search over bcm_document_chunks to retrieve relevant context,
    then sends the top chunks to Claude to generate a grounded answer.

    Returns (answer_text, list_of_cited_chunk_ids).
    """
    client = _get_client()
    if not client or not os.getenv("ANTHROPIC_API_KEY"):
        return _stub_rag_ask(question)

    # Retrieve relevant chunks via keyword search
    from modules.bcm import data_service as ds
    # Split question into meaningful keywords (skip short stop words)
    stop = {"the","a","an","is","are","was","were","what","which","how","does","do",
            "in","of","for","on","to","and","or","with","this","that","it","be"}
    keywords = [w.lower() for w in question.split() if len(w) > 2 and w.lower() not in stop]

    chunks = []
    if keywords:
        # Try up to 3 keywords at once; fall back to individual keywords if nothing found
        chunks = ds.search_chunks(keywords[:3], limit=6)
        if not chunks and len(keywords) > 1:
            chunks = ds.search_chunks(keywords[:1], limit=6)

    if not chunks:
        # No documents — answer from general BCM knowledge
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=(
                    "You are a business continuity management expert. "
                    "The user asked a question but no uploaded documents matched. "
                    "Answer from general BCM knowledge and mention that no specific "
                    "documents were found in the knowledge base."
                ),
                messages=[{"role": "user", "content": question}],
            )
            return resp.content[0].text, []
        except Exception as exc:
            log.error("RAG fallback failed: %s", exc)
            return _stub_rag_ask(question)

    # Build context from retrieved chunks
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
        f"QUESTION: {question}"
    )
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text, cited_ids
    except Exception as exc:
        log.error("RAG ask failed: %s", exc)
        return _stub_rag_ask(question)


def _stub_rag_ask(question: str) -> tuple[str, list[int]]:
    return (
        f"This is a placeholder answer for: \"{question}\". "
        "Full RAG retrieval will be enabled once document embeddings are configured.",
        [],
    )


# ── Chat ─────────────────────────────────────────────────────────────────────

def chat(history: list[dict]) -> str:
    """
    BCM chatbot — multi-turn conversation with continuity expertise.

    history: list of {role: "user"|"assistant", content: str}
    Returns the assistant reply text.
    """
    client = _get_client()
    if not client or not os.getenv("ANTHROPIC_API_KEY"):
        return _stub_chat(history)

    system = (
        "You are a business continuity management expert embedded in an "
        "enterprise BCM tool called One For All. Help the user with "
        "continuity planning, incident management, risk assessment, "
        "and regulatory compliance. Be concise and actionable."
    )
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=system,
            messages=history,
        )
        return resp.content[0].text
    except Exception as exc:
        log.error("AI chat failed: %s", exc)
        return _stub_chat(history)


def _stub_chat(history: list[dict]) -> str:
    last = history[-1]["content"] if history else ""
    return (
        f"[AI stub] I received your message about: \"{last[:80]}...\". "
        "The full AI chatbot will be enabled when the Anthropic API key is configured."
    )


# ── Plan Generator ───────────────────────────────────────────────────────────

def generate_plan(
    scenario: str,
    scope: str,
    industry: str = "",
    extra_context: str = "",
) -> str:
    """
    Generate a continuity plan document using AI.

    Args:
        scenario:  Type/scenario of plan (e.g. "IT Disaster Recovery", "Pandemic")
        scope:     What the plan covers
        industry:  Industry/sector context (e.g. "Financial Services")
        extra_context: Any additional instructions

    Returns markdown-formatted plan content.
    """
    client = _get_client()
    if not client or not os.getenv("ANTHROPIC_API_KEY"):
        return _stub_generate_plan(scenario, scope, industry)

    industry_context = f" for a {industry} organisation" if industry else ""
    prompt = (
        f"Generate a detailed {scenario} business continuity plan{industry_context}.\n\n"
        f"Scope: {scope}\n"
    )
    if extra_context:
        prompt += f"\nAdditional context: {extra_context}\n"
    prompt += (
        "\nStructure the plan with these sections:\n"
        "1. Purpose & Scope\n2. Roles & Responsibilities\n"
        "3. Activation Criteria\n4. Recovery Procedures\n"
        "5. Communication Plan\n6. Resource Requirements\n"
        "7. Testing & Maintenance\n\n"
        "Use markdown formatting. Be specific and actionable."
    )
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except Exception as exc:
        log.error("AI plan generation failed: %s", exc)
        return _stub_generate_plan(scenario, scope, industry)


def _stub_generate_plan(scenario: str, scope: str, industry: str = "") -> str:
    label = f"{scenario}" + (f" — {industry}" if industry else "")
    return (
        f"# {label}\n\n"
        f"**Scope:** {scope}\n\n"
        "## 1. Purpose & Scope\n\n"
        "This plan provides recovery procedures for the affected functions.\n\n"
        "## 2. Roles & Responsibilities\n\n"
        "| Role | Responsibility |\n|---|---|\n"
        "| BCM Manager | Overall plan ownership |\n"
        "| Incident Commander | Activation decision |\n\n"
        "## 3. Activation Criteria\n\n"
        "The plan is activated when a disruption exceeds 4 hours.\n\n"
        "## 4. Recovery Procedures\n\n"
        "1. Assess impact\n2. Notify stakeholders\n"
        "3. Execute workarounds\n4. Restore normal operations\n\n"
        "## 5. Communication Plan\n\n"
        "Internal: via Teams/email chain. External: via press office.\n\n"
        "## 6. Resource Requirements\n\n"
        "- Backup site access\n- Emergency contact list\n\n"
        "## 7. Testing & Maintenance\n\n"
        "Plan reviewed quarterly. Tabletop exercise annually.\n\n"
        "*[This is a stub plan — full AI generation requires an API key.]*"
    )


# ── Board Report Narrative ───────────────────────────────────────────────────

def generate_board_narrative(stats: dict) -> str:
    """
    Generate executive narrative for a board-level BCM report.

    stats: dashboard statistics dict from data_service.get_dashboard_stats().
    Returns markdown narrative.
    """
    client = _get_client()
    if not client or not os.getenv("ANTHROPIC_API_KEY"):
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
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text
    except Exception as exc:
        log.error("AI board narrative failed: %s", exc)
        return _stub_board_narrative(stats)


def _stub_board_narrative(stats: dict) -> str:
    total_plans = stats.get("plans", 0)
    open_incidents = stats.get("open_incidents", 0)
    return (
        "## Executive Summary\n\n"
        f"The BCM programme currently maintains **{total_plans}** continuity "
        f"plans with **{open_incidents}** open incident(s). "
        "Overall programme maturity is progressing in line with the annual "
        "target.\n\n"
        "Key areas of focus for the coming quarter include updating plans "
        "due for review and completing scheduled exercises.\n\n"
        "*[This is a stub narrative — full AI generation requires an API key.]*"
    )
