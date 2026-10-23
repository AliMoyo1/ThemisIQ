"""
ThemisIQ - organization AI policy and usage records (AI governance G1c).

Every call to a model provider goes through core/ai_client.py. Before the call it asks `authorize`; afterwards it
reports with `record_usage`. Nothing else in the platform talks to a provider (tests/test_ai_call_guard.py).

The policy belongs to an organization and is stored as one JSON setting (`ai.policy.org<id>`):

    enabled               the organization's master switch for ThemisIQ's AI features
    providers             which providers may receive its data; empty means any the platform has configured
    categories            which kinds of data may be sent (CATEGORIES); missing means all of them
    blocked_features      single features switched off
    monthly_token_budget       organization cap for a calendar month; empty means none
    monthly_user_token_budget  per-person cap for a calendar month; empty means none

An organization must have a saved policy before its data may be sent to a model provider.
An unreadable policy refuses the call.

What a feature sends is declared once, in FEATURES below, and is not inferred from prompt text. The usage log keeps
metadata only: who, which feature, provider, model, token counts, outcome. A prompt or an answer is never stored.
"""
import json
import logging
from dataclasses import dataclass, replace
from datetime import timedelta

from core.best_effort import swallowed
from core.timeutils import utcnow
from database import get_current_org, get_current_user_id, get_db_background, insert_returning_id

log = logging.getLogger("oneforall.ai_policy")

PROVIDERS = ("anthropic", "openrouter", "openai", "gemini", "deepseek", "ollama")

CATEGORIES = {
    "public": "General questions and public sources: nothing from the organization's own records",
    "business": "Policies, controls, risks, audits, plans and other business records",
    "personal": "Personal data: privacy cases, people and data subjects",
    "evidence": "Evidence files and what is written in them",
}

UNLABELLED = "unlabelled"  # what a call without a registered feature declares: refused by any organization policy

# feature id -> (what the user sees, the categories of data it sends). One line per place the platform calls a model.
FEATURES = {
    "core.compose_briefing":               ("Daily governance briefing", ("business",)),
    "core.generate_controls_for_framework": ("Draft controls for a framework", ("public",)),
    "core.auto_map_controls":              ("Match controls across frameworks", ("business",)),
    "aria.generate_policy":                ("Draft a policy", ("business",)),
    "aria.generate_gap_analysis":          ("Policy gap analysis", ("business",)),
    "aria.ask":                            ("Ask ARIA", ("business",)),
    "bcm.review_plan":                     ("Review a continuity plan", ("business",)),
    "bcm.suggest_incident_actions":        ("Suggest incident actions", ("business",)),
    "bcm.rag_ask":                         ("Ask about continuity plans", ("business",)),
    "bcm.chat":                            ("Continuity assistant", ("business",)),
    "bcm.generate_plan":                   ("Draft a continuity plan", ("business",)),
    "bcm.generate_board_narrative":        ("Continuity board narrative", ("business",)),
    "erm.score_risk":                      ("Score a risk", ("business",)),
    "erm.suggest_scores":                  ("Suggest risk scores", ("business",)),
    "erm.suggest_treatment":               ("Suggest a risk treatment", ("business",)),
    "erm.suggest_ice_rationale":           ("Explain a prioritization rating", ("business",)),
    "erm.generate_board_narrative":        ("Risk board narrative", ("business",)),
    "erm.chat":                            ("Risk assistant", ("business",)),
    "erm.generate_risk_statement":         ("Write a risk statement", ("business",)),
    "erm.suggest_assessment_questions":    ("Suggest assessment questions", ("business",)),
    "erm.identify_risks_from_responses":   ("Identify risks from responses", ("business",)),
    "erm.smart_remediation_plan":          ("Plan remediation", ("business",)),
    "erm.scan_emerging_risks_grounded":    ("Horizon scan with web search", ("business",)),
    "erm.scan_emerging_risks":             ("Horizon scan from model knowledge", ("business",)),
    "erm.generate_board_pack_narrative":   ("Board pack narrative", ("business",)),
    "erm.scenario_draft":                  ("Draft a scenario from a sentence", ("business",)),
    "erm.scenario_shocks":                 ("Suggest scenario changes", ("business",)),
    "erm.scenario_gaps":                   ("Find items missing from a scenario", ("business",)),
    "erm.scenario_explain":                ("Explain a scenario result", ("business",)),
    "erm.scenario_challenge":              ("Challenge a scenario's assumptions", ("business",)),
    "evidence.api_evidence_suggest_links": ("Suggest where evidence belongs", ("business", "evidence")),
    "evidence.find_evidence":              ("Read a question into evidence filters", ("business",)),
    "governance.run_drift_check":          ("Governance drift check", ("business",)),
    "grid.batch_risk_score":               ("Score audit risks in bulk", ("business",)),
    "grid.parse_checklist_with_ai":        ("Read an audit checklist", ("business",)),
    "grid.generate_gap_analysis":          ("Audit gap analysis", ("business",)),
    "grid.suggest_control_details":        ("Suggest control details", ("business",)),
    "grid.generate_report_narrative":      ("Audit report narrative", ("business",)),
    "grid.ask_compliance_ai":              ("Audit assistant", ("business",)),
    "grid.generate_incident_checklist":    ("Draft an incident checklist", ("business",)),
    "launcher.api_predictive_risk":        ("Predictive risk advisory", ("business",)),
    "launcher.api_tasks_ai_prioritize":    ("Prioritize tasks", ("business",)),
    "launcher.api_trainer_ask":            ("Platform help assistant", ("public",)),
    "launcher.api_executive_summary":      ("Executive summary", ("business",)),
    "orm.analyze_event":                   ("Analyse an operational event", ("business",)),
    "orm.generate_trend_narrative":        ("Operational trend narrative", ("business",)),
    "orm.chat":                            ("Operational risk assistant", ("business",)),
    "sentinel.ai_research":                ("Privacy research", ("business", "personal")),
    "sentinel.ai_generate_full_dpia":      ("Draft a DPIA", ("business", "personal")),
    "sentinel.ai_suggest_risks":           ("Suggest privacy risks", ("business", "personal")),
    "sentinel.ai_score_ropa":              ("Score a processing record", ("business", "personal")),
    "sentinel.ai_suggest_legal_basis":     ("Suggest a lawful basis", ("business", "personal")),
    "sentinel.ai_assess_breach":           ("Assess a breach", ("business", "personal")),
    "sentinel.ai_draft_dsr_response":      ("Draft a data subject reply", ("business", "personal")),
    "sentinel.ai_generate_privacy_notice": ("Draft a privacy notice", ("business", "personal")),
    "sentinel.ai_vendor_check":            ("Check a vendor", ("business", "personal")),
    "sentinel.ai_chat":                    ("Privacy assistant", ("business", "personal")),
    "sentinel.ai_gap_analysis":            ("Cross-regulation gap analysis", ("business", "personal")),
    "governance.explain_ai_use":           ("Explain the status of an AI use", ("business",)),
}

_SETTING = "ai.policy.org{}"
_MAX_SOURCES = 20


class AIPolicyError(RuntimeError):
    """A model call refused by the organization's AI policy. `reason` is a stable code for logs and the usage view;
    str() is the sentence shown to the person, and it never names a setting or another organization."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Ticket:
    feature: str
    org_id: "int | None"
    user_id: "int | None"
    provider: str
    categories: tuple
    sources: tuple = ()
    reservation_id: "int | None" = None
    reserved_tokens: int = 0


def categories_for(feature: str) -> tuple:
    entry = FEATURES.get(feature)
    return entry[1] if entry else (UNLABELLED,)


def default_policy() -> dict:
    return {"enabled": False, "providers": [], "categories": list(CATEGORIES), "blocked_features": [],
            "monthly_token_budget": None, "monthly_user_token_budget": None}


def _clean_policy(raw: dict) -> dict:
    """Normalize a saved policy; reject restrictions that could silently widen access."""
    named_providers = raw.get("providers", [])
    if not isinstance(named_providers, list) or any(p not in PROVIDERS for p in named_providers):
        raise ValueError("Stored AI provider restriction is invalid")
    named_categories = raw.get("categories", list(CATEGORIES))
    if not isinstance(named_categories, list) or any(c not in CATEGORIES for c in named_categories):
        raise ValueError("Stored AI category restriction is invalid")
    blocked_features = raw.get("blocked_features", [])
    if not isinstance(blocked_features, list) or any(f not in FEATURES for f in blocked_features):
        raise ValueError("Stored AI feature restriction is invalid")
    def positive_budget(name):
        value = raw.get(name)
        try:
            value = int(value) if value not in (None, "") and not isinstance(value, bool) else None
        except (TypeError, ValueError):
            raise ValueError(f"Stored AI allowance {name} is invalid") from None
        if raw.get(name) not in (None, "") and (value is None or value <= 0):
            raise ValueError(f"Stored AI allowance {name} is invalid")
        return value if value is not None and value > 0 else None
    return {
        "enabled": raw.get("enabled") is True,
        "providers": list(dict.fromkeys(named_providers)),
        "categories": list(dict.fromkeys(named_categories)),
        "blocked_features": list(dict.fromkeys(blocked_features)),
        "monthly_token_budget": positive_budget("monthly_token_budget"),
        "monthly_user_token_budget": positive_budget("monthly_user_token_budget"),
    }


def parse_submitted_policy(body) -> dict:
    """A policy sent by an administrator, checked strictly. Unlike a stored policy it is never cleaned silently: an
    unknown provider dropped from the list would turn "only these providers" into "any provider". Raises ValueError
    with a sentence that can be shown."""
    if not isinstance(body, dict):
        raise ValueError("Send the policy as an object.")
    if not isinstance(body.get("enabled"), bool):
        raise ValueError("enabled must be explicitly true or false.")
    if body["enabled"] and body.get("approval_confirmed") is not True:
        raise ValueError("Confirm the reviewed policy before enabling AI.")
    policy = {"enabled": body["enabled"], "approval_confirmed": body.get("approval_confirmed") is True}
    for key, known, noun in (("providers", PROVIDERS, "provider"), ("categories", CATEGORIES, "data category"),
                             ("blocked_features", FEATURES, "feature")):
        values = body.get(key, [] if key != "categories" else list(CATEGORIES))
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError(f"{key} must be a list of names.")
        unknown = sorted({v for v in values if v not in known})
        if unknown:
            raise ValueError(f"Unknown {noun}: {', '.join(unknown[:5])}.")
        policy[key] = list(dict.fromkeys(values))
    for name in ("monthly_token_budget", "monthly_user_token_budget"):
        budget = body.get(name)
        if budget in (None, ""):
            policy[name] = None
        elif isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
            raise ValueError(f"{name} must be a whole number above zero, or empty for no cap.")
        else:
            policy[name] = budget
    return policy


def get_policy(org_id: int) -> "dict | None":
    """The organization's stored policy, or None if it has not been approved. Raises when the stored value is unreadable,
    which `authorize` turns into a refusal."""
    db = get_db_background()
    try:
        row = db.execute("SELECT value FROM settings WHERE key=%s", (_SETTING.format(org_id),)).fetchone()
    finally:
        db.close()
    if not row or row["value"] is None:
        return None
    stored = json.loads(row["value"])
    if not isinstance(stored, dict):
        raise ValueError("AI policy is not an object")
    return _effective_policy(stored)


def _effective_policy(raw: dict) -> dict:
    """Old enabled rows must be reviewed by a named policy manager before use."""
    clean = _clean_policy(raw)
    clean["review_required"] = bool(clean["enabled"] and not (
        isinstance(raw.get("approved_by"), int) and raw["approved_by"] > 0 and
        isinstance(raw.get("approved_at"), str) and raw["approved_at"]
    ))
    if clean["review_required"]:
        clean["enabled"] = False
    return clean


def save_policy(org_id: int, policy: dict, user_id: "int | None" = None) -> dict:
    """Store an organization's policy (replacing the previous one) and return what was stored."""
    if policy.get("enabled") and (policy.get("approval_confirmed") is not True or
                                  not isinstance(user_id, int) or user_id < 1):
        raise ValueError("An identified policy manager must confirm the review before enabling AI")
    clean = _clean_policy(policy)
    clean["approved_by"] = user_id if clean["enabled"] else None
    clean["approved_at"] = utcnow().strftime("%Y-%m-%d %H:%M:%S") if clean["enabled"] else None
    clean["updated_by"] = user_id
    clean["updated_at"] = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db = get_db_background()
    try:
        db.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (_SETTING.format(org_id), json.dumps(clean)),
        )
        db.commit()
    finally:
        db.close()
    return clean


def _month_start() -> str:
    return utcnow().strftime("%Y-%m-01 00:00:00")


def tokens_used_this_month(org_id: int) -> int:
    db = get_db_background()
    try:
        used = _capacity_used(db, org_id)
    finally:
        db.close()
    return used


def _capacity_used(db, org_id: int, user_id: "int | None" = None) -> int:
    """Completed and in-flight allowance, including conservatively charged failures."""
    where_user = " AND user_id = %s" if user_id is not None else ""
    params = [org_id, _month_start()]
    if user_id is not None:
        params.append(user_id)
    row = db.execute(
        "SELECT COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0) AS used "
        "FROM ai_usage_log WHERE org_id = %s AND created_at >= %s "
        f"AND status IN ('ok', 'error', 'reserved'){where_user}", params,
    ).fetchone()
    return int(row["used"] or 0)


def _refusal(policy: dict, org_id: int, ticket_provider: str, feature: str, categories: tuple):
    """(reason, message) when the policy forbids this provider, feature or data category."""
    if not policy["enabled"]:
        return "disabled", "AI features are turned off for your organization."
    if policy["providers"] and ticket_provider not in policy["providers"]:
        return "provider_not_allowed", "Your organization's AI policy does not allow the AI provider this platform uses."
    if feature in policy["blocked_features"]:
        return "feature_blocked", "This AI feature is turned off for your organization."
    if not set(categories) <= set(policy["categories"]):
        return "category_not_allowed", "Your organization's AI policy does not allow this kind of data to be sent."
    return None


def org_state(provider: str) -> "tuple | None":
    """(reason, message) when the current organization's policy switches AI off as a whole (master switch or the
    provider), for the capability state shown beside AI buttons; None when AI is usable."""
    org_id = get_current_org()
    if org_id is None:
        return "org_unbound", "AI features require an organization context."
    try:
        policy = get_policy(org_id)
    except Exception:
        swallowed("ai_policy.org_state")
        return "policy_unreadable", "AI features are unavailable for your organization."
    if policy is None:
        return "policy_missing", "An administrator must approve your organization's AI policy before AI can be used."
    if not policy["enabled"]:
        return "disabled", "AI features are turned off for your organization."
    if policy["providers"] and provider not in policy["providers"]:
        return "provider_not_allowed", "Your organization's AI policy does not allow the AI provider this platform uses."
    return None


def authorize(feature: str, *, provider: str, sources=None, reserve_tokens: int = 1) -> Ticket:
    """Decide whether this call may leave the platform. Raises AIPolicyError (and records the refusal) or returns the
    Ticket to report the outcome with. The organization and the person come from the request or job context."""
    org_id, user_id = get_current_org(), get_current_user_id()
    ticket = Ticket(
        feature=feature or UNLABELLED, org_id=org_id, user_id=user_id, provider=provider,
        categories=categories_for(feature), sources=tuple(str(s)[:120] for s in (sources or ())[:_MAX_SOURCES]),
    )
    if org_id is None:
        refusal = ("org_unbound", "AI features require an organization context.")
        record_usage(ticket, "refused", reason=refusal[0])
        raise AIPolicyError(*refusal)
    if not isinstance(reserve_tokens, int) or not 1 <= reserve_tokens <= 10_000_000:
        refusal = ("request_too_large", "This AI request is too large to process.")
        record_usage(ticket, "refused", reason=refusal[0])
        raise AIPolicyError(*refusal)

    # The setting row is the serialization point for every call in this
    # tenant. A second worker cannot approve against the same spare budget
    # until this transaction commits its reservation.
    refusal = None
    db = None
    try:
        db = get_db_background()
        locked = db.execute(
            "UPDATE settings SET value=value WHERE key=%s", (_SETTING.format(org_id),)
        ).rowcount
        if not locked:
            refusal = ("policy_missing", "An administrator must approve your organization's AI policy before AI can be used.")
        else:
            row = db.execute("SELECT value FROM settings WHERE key=%s", (_SETTING.format(org_id),)).fetchone()
            raw = json.loads(row["value"])
            if not isinstance(raw, dict):
                raise ValueError("AI policy is not an object")
            policy = _effective_policy(raw)
            refusal = _refusal(policy, org_id, provider, ticket.feature, ticket.categories)
            if not refusal:
                # A worker that died after reserving still consumes its
                # conservative allowance. Mark it as an error after two
                # hours so the usage view does not show a call in progress.
                stale_before = (utcnow() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
                db.execute(
                    "UPDATE ai_usage_log SET status='error', reason='reservation_expired' "
                    "WHERE org_id=%s AND status='reserved' AND created_at < %s",
                    (org_id, stale_before),
                )
                org_cap = policy["monthly_token_budget"]
                user_cap = policy["monthly_user_token_budget"] if user_id is not None else None
                if org_cap is not None and _capacity_used(db, org_id) + reserve_tokens > org_cap:
                    refusal = ("budget_exhausted", "Your organization has used its AI allowance for this month.")
                elif user_cap is not None and _capacity_used(db, org_id, user_id) + reserve_tokens > user_cap:
                    refusal = ("user_budget_exhausted", "Your AI allowance for this month has been used.")
            if not refusal and _RECORDING:
                reservation_id = insert_returning_id(
                    db,
                    "INSERT INTO ai_usage_log (org_id, user_id, feature, provider, status, categories, sources, input_tokens) "
                    "VALUES (%s,%s,%s,%s,'reserved',%s,%s,%s)",
                    (org_id, user_id, ticket.feature, provider, ",".join(ticket.categories),
                     json.dumps(list(ticket.sources)) if ticket.sources else None, reserve_tokens),
                )
                if reservation_id is None:
                    raise RuntimeError("AI budget reservation was not saved")
                ticket = replace(ticket, reservation_id=reservation_id, reserved_tokens=reserve_tokens)
        db.commit()
    except Exception:
        swallowed("ai_policy.authorize")
        if db is not None:
            db.rollback()
        refusal = ("policy_unreadable", "AI features are unavailable for your organization right now.")
    finally:
        if db is not None:
            db.close()
    if refusal:
        record_usage(ticket, "refused", reason=refusal[0])
        raise AIPolicyError(*refusal)
    return ticket


# Tests that call the real client must not write into whichever database happens to be configured; they turn this off.
_RECORDING = True


def record_usage(ticket: Ticket, status: str, *, reason: str = "", model: str = "", input_tokens: int = 0,
                 output_tokens: int = 0, duration_ms: int = 0) -> None:
    """Append one usage row. Best effort: a failure to record is logged and never reaches the caller."""
    if not _RECORDING:
        return
    db = None
    try:
        db = get_db_background()
        if ticket.reservation_id is not None:
            # Finalization and admission use the same row lock. A concurrent
            # admission then sees either the full reservation or final usage.
            db.execute("UPDATE settings SET value=value WHERE key=%s",
                       (_SETTING.format(ticket.org_id),))
            actual_input = max(0, int(input_tokens or 0))
            actual_output = max(0, int(output_tokens or 0))
            # Some providers do not report usage. A failed or unmetered call
            # retains the reservation so missing telemetry cannot bypass a cap.
            if status != "ok" or not actual_input + actual_output:
                actual_input, actual_output = ticket.reserved_tokens, 0
            changed = db.execute(
                "UPDATE ai_usage_log SET model=%s, status=%s, reason=%s, input_tokens=%s, "
                "output_tokens=%s, duration_ms=%s WHERE id=%s AND org_id=%s AND status='reserved'",
                ((model or "")[:120] or None, status, (reason or "")[:120] or None,
                 actual_input, actual_output, int(duration_ms or 0), ticket.reservation_id, ticket.org_id),
            ).rowcount
            if changed != 1:
                raise RuntimeError("AI reservation could not be finalized")
        else:
            db.execute(
                "INSERT INTO ai_usage_log (org_id, user_id, feature, provider, model, status, reason, categories, "
                "sources, input_tokens, output_tokens, duration_ms) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (ticket.org_id, ticket.user_id, ticket.feature, ticket.provider, (model or "")[:120] or None, status,
                 (reason or "")[:120] or None, ",".join(ticket.categories),
                 json.dumps(list(ticket.sources)) if ticket.sources else None,
                 int(input_tokens or 0), int(output_tokens or 0), int(duration_ms or 0)),
            )
        db.commit()
    except Exception:
        swallowed("ai_policy.record_usage")
    finally:
        if db is not None:
            db.close()


def usage_summary(org_id: int) -> dict:
    """This month's calls, tokens and refusals for one organization, by feature, plus the latest refusals."""
    db = get_db_background()
    try:
        rows = db.execute(
            "SELECT feature, status, COUNT(*) AS calls, COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0) AS tokens "
            "FROM ai_usage_log WHERE org_id = %s AND created_at >= %s AND status <> 'reserved' "
            "GROUP BY feature, status ORDER BY feature",
            (org_id, _month_start()),
        ).fetchall()
        recent = db.execute(
            "SELECT feature, reason, created_at FROM ai_usage_log WHERE org_id = %s AND status = 'refused' "
            "ORDER BY id DESC LIMIT 10", (org_id,),
        ).fetchall()
    finally:
        db.close()
    by_feature: dict = {}
    for r in rows:
        entry = by_feature.setdefault(r["feature"], {"feature": r["feature"], "ok": 0, "error": 0, "refused": 0, "tokens": 0})
        entry[r["status"]] = int(r["calls"])
        if r["status"] == "ok":
            entry["tokens"] += int(r["tokens"])
    return {
        "month": utcnow().strftime("%Y-%m"),
        "calls": sum(e["ok"] for e in by_feature.values()),
        "refused": sum(e["refused"] for e in by_feature.values()),
        "errors": sum(e["error"] for e in by_feature.values()),
        "tokens": sum(e["tokens"] for e in by_feature.values()),
        "by_feature": [{**e, "label": FEATURES.get(e["feature"], (e["feature"],))[0]} for e in by_feature.values()],
        "recent_refusals": [{"feature": r["feature"], "reason": r["reason"], "at": str(r["created_at"])} for r in recent],
    }
