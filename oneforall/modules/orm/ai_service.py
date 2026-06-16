"""
ORM AI Service - Root cause analysis, trend narrative, chat assistant.

Uses the unified core.ai_client for multi-provider support
(Anthropic, DeepSeek, Gemini, OpenAI, Ollama).
"""
import json
import logging

from core.ai_client import create_message, is_configured, provider_name, safe_json_parse

log = logging.getLogger(__name__)


def analyze_event(event: dict) -> dict:
    if not is_configured():
        return _stub_analyze(event)
    prompt = (
        f"Operational risk event analysis:\n\n"
        f"Title: {event.get('title', '')}\n"
        f"Type: {event.get('event_type', '')}\n"
        f"Severity: {event.get('severity', '')}\n"
        f"Description: {event.get('description', '')}\n"
        f"Financial Impact: ${event.get('financial_impact', 0):,.0f}\n"
        f"Customers Affected: {event.get('customers_affected', 0)}\n"
        f"Downtime: {event.get('downtime_minutes', 0)} minutes\n\n"
        "Provide root cause analysis and recommendations. Return JSON:\n"
        '{"root_cause_category": "<people|process|system|external>", '
        '"root_cause_analysis": "<2-3 sentence analysis>", '
        '"corrective_action": "<immediate action to fix this>", '
        '"preventive_action": "<action to prevent recurrence>"}'
    )
    try:
        text = create_message([{"role": "user", "content": prompt}], max_tokens=800)
        return safe_json_parse(text, _stub_analyze(event))
    except Exception as exc:
        log.error("ORM analyze failed: %s", exc)
        return _stub_analyze(event)


def _stub_analyze(event: dict) -> dict:
    return {
        "root_cause_category": "process",
        "root_cause_analysis": f"Stub analysis for '{event.get('title', '')}'. Configure {provider_name()} API key for AI analysis.",
        "corrective_action": "Investigate and document findings. Apply immediate fix.",
        "preventive_action": "Review process controls and implement preventive measures.",
    }


def generate_trend_narrative(stats: dict) -> str:
    if not is_configured():
        return _stub_trend_narrative(stats)
    prompt = (
        "You are writing the Operational Risk section of a board report. "
        f"Write a professional 2-3 paragraph narrative covering the last {stats.get('period_days', 30)} days.\n\n"
        f"Stats: {json.dumps(stats, default=str)}\n\n"
        "Cover: event volume trends, financial impact, top event types, "
        "key incidents, and operational risk outlook. Professional tone."
    )
    try:
        return create_message([{"role": "user", "content": prompt}], max_tokens=1000)
    except Exception as exc:
        log.error("ORM trend narrative failed: %s", exc)
        return _stub_trend_narrative(stats)


def _stub_trend_narrative(stats: dict) -> str:
    total = stats.get("total_events", 0)
    loss = stats.get("financial_loss", 0)
    delta = stats.get("total_events_delta", 0)
    trend = "increased" if delta > 0 else ("decreased" if delta < 0 else "remained stable")
    return (
        f"Operational risk event volume has {trend} versus the prior period, "
        f"with {total} events recorded in the last {stats.get('period_days', 30)} days "
        f"resulting in a total financial impact of ${loss:,.0f}.\n\n"
        "The Board is requested to note the operational risk profile and approve "
        "any required remediation actions.\n\n"
        f"*[Full AI narrative requires {provider_name()} API key.]*"
    )


def chat(history: list, stats: dict = None) -> str:
    if not is_configured():
        last = history[-1]["content"] if history else ""
        return f"[ORM AI stub] Received: \"{last[:80]}\". Configure {provider_name()} API key for AI assistance."
    system = (
        "You are an Operational Risk Management expert. "
        "Help the user analyse operational risk events, identify root causes, "
        "suggest corrective and preventive actions, and improve control frameworks. "
        "Reference Basel II/III operational risk categories, ISO 31000, and industry best practices."
    )
    if stats:
        system += f"\n\nCurrent ORM stats: {json.dumps(stats, default=str)}"
    try:
        return create_message(history, system=system, max_tokens=2048)
    except Exception as exc:
        log.error("ORM chat failed: %s", exc)
        return "Sorry, I encountered an error. Please try again."
