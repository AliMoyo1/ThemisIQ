"""
ThemisIQ — Predictive AI Risk Analytics Engine.

Collects multi-domain telemetry from across the platform and computes a
risk probability modifier (ΔP_risk) using a weighted tanh delta model.

Formula:
    ΔP_risk = tanh(α·B + β·F + γ·(E−180)/180 + δ·O + ε·C + ζ·A) × 100%

Where:
    B = severity-weighted, recency-decayed open breaches (Sentinel, 30d)
    F = open critical/major non-conformances (GRID)
    E = days since last completed BCM exercise (baseline 180d)
    O = recurring ORM operational events (30d)
    C = ARIA compliance gap = (100 − compliance_pct) / 100
    A = ERM risk appetite breaches (active categories above threshold)

Per-domain sub-scores:
    ΔP_cyber       = tanh(α·B + β·F·0.5) × 100%
    ΔP_operational = tanh(γ·(E−180)/180 + δ·O) × 100%
    ΔP_compliance  = tanh(β·F·0.5 + ε·C + ζ·A) × 100%
"""
import json
import math
import logging
from datetime import datetime
from config import settings
from core.timeutils import utcnow
from database import sql_days_between, sql_date_offset, sql_date_ts

log = logging.getLogger("oneforall.predictive_risk")

# ── Model weights ────────────────────────────────────────────────────────────
α = 0.45   # open breaches (Sentinel)
β = 0.25   # open critical/major NCs (GRID)
γ = 0.30   # BCM exercise staleness
δ = 0.20   # recurring ORM events
ε = 0.15   # ARIA compliance gap
ζ = 0.35   # ERM appetite breaches

# Threshold above which Claude advisory is generated
ADVISORY_THRESHOLD = 15.0
# Threshold above which auto-escalation to ERM is triggered
ESCALATION_THRESHOLD = 50.0
# Cache TTL in minutes
CACHE_TTL_MINUTES = 30


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sev_weight(sev: str) -> float:
    """Map breach/NC severity string to numeric weight."""
    return {"critical": 4.0, "major": 3.0, "high": 2.0, "medium": 1.0,
            "minor": 0.75, "low": 0.5}.get((sev or "").lower(), 1.0)


def _recency_decay(days_ago: float) -> float:
    """Exponential decay: half-life ≈ 14 days (λ=0.05)."""
    if days_ago is None or days_ago < 0:
        days_ago = 0.0
    return math.exp(-0.05 * float(days_ago))


def _tanh_score(x: float) -> float:
    """Apply tanh activation and scale to 0–100."""
    return round(math.tanh(max(0.0, x)) * 100.0, 1)


def _risk_level(delta_p: float) -> str:
    if delta_p >= 60:
        return "critical"
    if delta_p >= 35:
        return "high"
    if delta_p >= 15:
        return "medium"
    return "low"


def _confidence(metrics: dict) -> float:
    """
    Estimate confidence based on data completeness.
    If key sources return zeros due to empty tables, confidence drops.
    Returns 0.0–1.0.
    """
    signals = 0
    has_data = 0
    for key in ("breach_raw_count", "nc_count", "days_since_exercise",
                "orm_recurring", "aria_total", "appetite_breaches"):
        v = metrics.get(key)
        signals += 1
        if v is not None and v != 365:   # 365 = default "never"
            has_data += 1
    return round(has_data / max(1, signals), 2)


# ── Telemetry collection ─────────────────────────────────────────────────────

def collect_telemetry(db) -> dict:
    """
    Query all 6 signal sources and return raw metrics dict.
    All queries are wrapped in try/except so a missing table never crashes.
    """
    metrics = {}

    # ── B: Sentinel open breaches (severity-weighted + recency-decayed) ──────
    try:
        if settings.is_postgres():
            # PostgreSQL: created_at is TIMESTAMPTZ, discovery_date is TEXT.
            # Must not COALESCE(text, timestamptz) directly — type mismatch fails.
            rows = db.execute(
                "SELECT severity, "
                "  EXTRACT(EPOCH FROM (NOW() - COALESCE(discovery_date::timestamptz, created_at))) / 86400 AS days_ago "
                "FROM sentinel_breaches WHERE status != 'closed'"
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT severity, "
                "  (julianday('now') - julianday(COALESCE(discovery_date, created_at))) AS days_ago "
                "FROM sentinel_breaches WHERE status != 'closed'"
            ).fetchall()
        B = sum(_sev_weight(r["severity"]) * _recency_decay(r["days_ago"] or 0) for r in rows)
        metrics["breach_raw_count"] = len(rows)
        metrics["B"] = round(B, 3)
        metrics["breach_severities"] = [r["severity"] for r in rows]
    except Exception as exc:
        log.warning("Telemetry B (breaches) failed: %s", exc)
        B = 0.0
        metrics["B"] = 0.0
        metrics["breach_raw_count"] = 0

    # ── F: GRID open critical/major non-conformances ─────────────────────────
    try:
        nc_rows = db.execute(
            "SELECT severity FROM grid_non_conformances "
            "WHERE status = 'open' AND severity IN ('critical','major','high')"
        ).fetchall()
        # Weight by severity, not just count
        F = sum(_sev_weight(r["severity"]) for r in nc_rows)
        metrics["nc_count"] = len(nc_rows)
        metrics["F"] = round(F, 3)
    except Exception as exc:
        log.debug("Telemetry F (NCs) unavailable: %s", exc)
        F = 0.0
        metrics["F"] = 0.0
        metrics["nc_count"] = 0

    # ── E: BCM exercise staleness ─────────────────────────────────────────────
    try:
        ex_row = db.execute(
            f"""SELECT CAST({sql_days_between("'now'", "scheduled_date")} AS REAL) AS days """
            "FROM bcm_exercises WHERE status = 'completed' "
            "ORDER BY scheduled_date DESC LIMIT 1"
        ).fetchone()
        days_since = float(ex_row["days"]) if ex_row and ex_row["days"] is not None else 365.0
        metrics["days_since_exercise"] = round(days_since, 1)
        E_norm = (days_since - 180.0) / 180.0
    except Exception as exc:
        log.debug("Telemetry E (BCM) unavailable: %s", exc)
        days_since = 365.0
        metrics["days_since_exercise"] = 365.0
        E_norm = (365.0 - 180.0) / 180.0

    # ── O: Recurring ORM operational events (30d) ────────────────────────────
    try:
        orm_count = db.execute(
            "SELECT COUNT(*) FROM orm_events "
            f"WHERE is_recurring = 1 AND created_at >= {sql_date_ts('-30 days')}"
        ).fetchone()[0]
        metrics["orm_recurring"] = int(orm_count)
        O = float(orm_count)
    except Exception as exc:
        log.debug("Telemetry O (ORM) unavailable: %s", exc)
        O = 0.0
        metrics["orm_recurring"] = 0

    # ── C: ARIA compliance gap ────────────────────────────────────────────────
    try:
        row = db.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status = 'compliant' THEN 1 ELSE 0 END) AS ok "
            "FROM aria_controls"
        ).fetchone()
        total = row["total"] or 0
        ok = row["ok"] or 0
        compliance_pct = (ok / total * 100) if total else 100.0
        C_gap = (100.0 - compliance_pct) / 100.0
        metrics["aria_total"] = total
        metrics["aria_compliant"] = ok
        metrics["compliance_pct"] = round(compliance_pct, 1)
        metrics["C"] = round(C_gap, 4)
    except Exception as exc:
        log.debug("Telemetry C (ARIA) unavailable: %s", exc)
        C_gap = 0.0
        metrics["C"] = 0.0
        metrics["aria_total"] = 0

    # ── A: ERM appetite breaches ──────────────────────────────────────────────
    try:
        app_breaches = db.execute(
            "SELECT COUNT(*) FROM erm_risk_appetite a "
            "WHERE (SELECT MAX(e.likelihood * e.impact) "
            "       FROM erm_enterprise_risks e "
            "       WHERE e.category = a.category "
            "         AND e.status NOT IN ('closed', 'accepted')) > a.max_score"
        ).fetchone()[0]
        A = float(app_breaches)
        metrics["appetite_breaches"] = int(app_breaches)
    except Exception as exc:
        log.debug("Telemetry A (ERM appetite) unavailable: %s", exc)
        A = 0.0
        metrics["appetite_breaches"] = 0

    metrics["collected_at"] = utcnow().isoformat()
    return metrics


# ── Math engine ───────────────────────────────────────────────────────────────

def compute_delta_p(metrics: dict) -> dict:
    """
    Run the weighted tanh formula on collected telemetry.
    Returns a rich result dict including domain sub-scores,
    signal contributions, risk level, and confidence.
    """
    B = metrics.get("B", 0.0)
    F = metrics.get("F", 0.0)
    O = metrics.get("orm_recurring", 0.0)
    C = metrics.get("C", 0.0)
    A = metrics.get("appetite_breaches", 0.0)
    days_since = metrics.get("days_since_exercise", 365.0)
    E_norm = (float(days_since) - 180.0) / 180.0

    # ── Global ΔP ──
    raw_global = α * B + β * F + γ * E_norm + δ * O + ε * C + ζ * A
    delta_p = _tanh_score(raw_global)

    # ── Domain sub-scores ──
    raw_cyber = α * B + β * F * 0.5
    raw_ops   = γ * E_norm + δ * O
    raw_comp  = β * F * 0.5 + ε * C + ζ * A

    delta_cyber       = _tanh_score(raw_cyber)
    delta_operational = _tanh_score(raw_ops)
    delta_compliance  = _tanh_score(raw_comp)

    # ── Per-signal contributions (% of total raw) ──
    raw_total = max(0.001, abs(raw_global))
    contributions = {
        "breaches":          round(abs(α * B) / raw_total * 100),
        "non_conformances":  round(abs(β * F) / raw_total * 100),
        "bcm_staleness":     round(abs(γ * E_norm) / raw_total * 100),
        "orm_recurring":     round(abs(δ * O) / raw_total * 100),
        "compliance_gap":    round(abs(ε * C) / raw_total * 100),
        "appetite_breaches": round(abs(ζ * A) / raw_total * 100),
    }

    risk_level = _risk_level(delta_p)
    confidence = _confidence(metrics)

    return {
        "delta_p":            delta_p,
        "delta_cyber":        delta_cyber,
        "delta_operational":  delta_operational,
        "delta_compliance":   delta_compliance,
        "risk_level":         risk_level,
        "confidence":         confidence,
        "signal_contributions": contributions,
        "raw_score":          round(raw_global, 4),
    }


# ── Advisory prompt builder ───────────────────────────────────────────────────

ADVISORY_SYSTEM_PROMPT = """You are ThemisIQ's Virtual Chief Risk Officer. You receive live telemetry \
from an enterprise GRC platform and produce a concise executive-ready risk advisory.

Output EXACTLY this format (Markdown):

### [Aegis AI Alert] <Domain> Risk Probability Elevated +{delta}%

**Finding:** <1-2 sentences explaining what the signals indicate and why this matters>
**Primary Driver:** <single biggest contributing factor, with module name>
**Recommended Actions:**
1. <Specific, actionable step referencing module/control by name>
2. <Second step>
3. <Third step if warranted>

Rules: Be specific. Reference actual ThemisIQ module names (Sentinel, GRID, BCM, ERM, ORM, ARIA). \
Keep total response under 220 words. Do not mention percentages beyond what is given. \
Do not speculate about data not provided."""


def build_advisory_prompt(metrics: dict, result: dict) -> str:
    """Build the user-facing prompt payload for Claude."""
    domain_leader = max(
        [("Cyber",       result["delta_cyber"]),
         ("Operational", result["delta_operational"]),
         ("Compliance",  result["delta_compliance"])],
        key=lambda x: x[1]
    )[0]

    contribs = result.get("signal_contributions", {})
    top_signal = max(contribs, key=contribs.get) if contribs else "unknown"
    top_signal_labels = {
        "breaches": "Active Sentinel data breaches",
        "non_conformances": "Open GRID non-conformances",
        "bcm_staleness": "Overdue BCM exercises",
        "orm_recurring": "Recurring ORM operational events",
        "compliance_gap": "ARIA compliance gap",
        "appetite_breaches": "ERM risk appetite breaches",
    }

    lines = [
        f"PLATFORM TELEMETRY SNAPSHOT — {metrics.get('collected_at', 'now')}",
        "",
        f"Global ΔP_risk: +{result['delta_p']}%  (Risk Level: {result['risk_level'].upper()})",
        f"Domain Scores:  Cyber={result['delta_cyber']}%  Operational={result['delta_operational']}%  Compliance={result['delta_compliance']}%",
        f"Top Domain: {domain_leader}",
        f"Primary Signal: {top_signal_labels.get(top_signal, top_signal)} ({contribs.get(top_signal, 0)}% of score)",
        "",
        "RAW METRICS:",
        f"  • Sentinel open breaches (30d, weighted): {metrics.get('B', 0):.2f}  (raw count: {metrics.get('breach_raw_count', 0)})",
        f"  • GRID open critical/major NCs: {metrics.get('nc_count', 0)}",
        f"  • Days since last BCM exercise: {metrics.get('days_since_exercise', 365):.0f}",
        f"  • Recurring ORM events (30d): {metrics.get('orm_recurring', 0)}",
        f"  • ARIA compliance: {metrics.get('compliance_pct', 100):.1f}% ({metrics.get('aria_compliant', 0)}/{metrics.get('aria_total', 0)} controls)",
        f"  • ERM appetite breaches: {metrics.get('appetite_breaches', 0)}",
        "",
        "SIGNAL CONTRIBUTIONS:",
    ]
    for sig, pct in sorted(contribs.items(), key=lambda x: -x[1]):
        lines.append(f"  • {top_signal_labels.get(sig, sig)}: {pct}%")

    lines += [
        "",
        f"Generate the advisory. Use 'domain' = '{domain_leader}' and 'delta' = '{result['delta_p']}'.",
    ]
    return "\n".join(lines)
