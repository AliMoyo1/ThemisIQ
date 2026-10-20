"""
Tracing a predictive risk number to what it was made from (plans/2026-10-governance-rework/04 section 9, scenario 5).

A prediction keeps, with its telemetry, the records each signal was made from (ids and weights, at most 25 a signal and
the count of all). This module turns that into what a reviewer reads: for each signal its rule, its period, its weight in
the formula, the figure it produced, the records behind it that the viewer may open, and the disputes recorded beside it.
A dispute is a note. It never edits the prediction, the records or the formula, and it does not change the number.
"""
import json

from core import predictive_risk as pr
from core.sanitize import sanitize_str
from database import insert_returning_id
from modules.governance.entity_scope import describe_records

MAX_BODY = 1000


def _prediction(db, prediction_id):
    if prediction_id is None:
        return db.execute(
            "SELECT * FROM ai_risk_predictions WHERE is_active = 1 ORDER BY id DESC LIMIT 1").fetchone()
    return db.execute("SELECT * FROM ai_risk_predictions WHERE id = %s", (prediction_id,)).fetchone()


def _metric(metrics: dict, name: str):
    """The figure the formula used for a signal, or None when the engine did not supply one."""
    if name == "E_norm":
        days = metrics.get("days_since_exercise")
        return None if days is None else round((float(days) - 180.0) / 180.0, 4)
    value = metrics.get(name)
    return None if value is None else float(value)


def _notes(db, prediction_id: int) -> dict:
    out: dict = {}
    for r in db.execute(
            "SELECT id, signal, body, author_name, created_at FROM ai_risk_prediction_notes "
            "WHERE prediction_id = %s ORDER BY id", (prediction_id,)).fetchall():
        out.setdefault(r["signal"], []).append(
            {"id": r["id"], "body": r["body"], "author": r["author_name"], "created_at": str(r["created_at"])})
    return out


def build(db, user, prediction_id=None) -> "dict | None":
    """The trace of one prediction (the latest when none is named), or None when there is none."""
    row = _prediction(db, prediction_id)
    if row is None:
        return None
    try:
        metrics = json.loads(row["telemetry_json"] or "{}")
        contributions = json.loads(row["contributions_json"] or "{}")
    except (TypeError, ValueError):
        metrics, contributions = {}, {}
    trace = metrics.get("trace")
    notes = _notes(db, row["id"])
    signals = []
    for key, spec in pr.SIGNALS.items():
        value = _metric(metrics, spec["metric"])
        weight = pr.WEIGHTS[spec["weight"]]
        term = None if value is None else round(weight * value, 4)
        entry = {
            "key": key, "label": spec["label"], "rule": spec["rule"], "window": spec["window"],
            "figure": value, "weight": weight, "term": term,
            # a term below zero (a recent exercise) lowers the score; its stored share is an absolute value
            "direction": "none" if not term else ("raises" if term > 0 else "lowers"),
            "share_pct": contributions.get(key), "disputes": notes.get(key, []),
            "count": None, "of": None, "records": [], "not_shown": 0, "truncated": False, "categories": [],
            "none_found": False}
        part = (trace or {}).get(key)
        if part is not None:
            entry["count"] = part.get("count")
            entry["of"] = part.get("of")
            entry["categories"] = part.get("categories") or []
            entry["none_found"] = bool(part.get("none_found"))
            kept = part.get("records") or []
            if spec["kind"] and kept:
                found = describe_records(db, spec["kind"], [r["id"] for r in kept], user)
                for rec in kept:
                    info = found.get(rec["id"])
                    if info is None:
                        entry["not_shown"] += 1
                        continue
                    entry["records"].append({"title": info["title"], "url": info["url"], "weight": rec.get("weight")})
            entry["truncated"] = bool(entry["count"]) and entry["count"] > len(kept) and bool(spec["kind"])
        signals.append(entry)
    computed = row["computed_at"]
    return {
        "prediction_id": row["id"], "computed_at": str(computed), "delta_p": row["delta_p"],
        "risk_level": row["risk_level"], "confidence": row["confidence"],
        "traceable": trace is not None,
        "freshness": {"computed_at": str(computed), "cache_minutes": pr.CACHE_TTL_MINUTES,
                      "as_of": metrics.get("collected_at")},
        "formula": "100 x tanh(max(0, alpha*B + beta*F + gamma*(E-180)/180 + delta*O + epsilon*C + zeta*A))",
        "signals": signals,
        "note": None if trace is not None else
        "This prediction was made before its source records were kept with it. Refresh it for one that can be traced.",
    }


def add_dispute(db, user, prediction_id: int, signal: str, body) -> dict:
    """Record a reviewer's dispute of one signal. Raises ValueError with a sentence that is safe to show."""
    if signal not in pr.SIGNALS:
        raise ValueError("Name one of the signals of the prediction.")
    # The request layer keeps tags in a field called "body" (it is one of the rich text keys), so strip them here: the note
    # is read as plain text everywhere.
    text = " ".join(str(sanitize_str(str(body or "")) or "").split())
    if len(text) < 3:
        raise ValueError("Say what you dispute and why.")
    if len(text) > MAX_BODY:
        raise ValueError(f"Keep it to {MAX_BODY} characters.")
    if db.execute("SELECT 1 FROM ai_risk_predictions WHERE id = %s", (prediction_id,)).fetchone() is None:
        raise LookupError("Prediction not found.")
    note_id = insert_returning_id(
        db, "INSERT INTO ai_risk_prediction_notes (prediction_id, signal, body, author_id, author_name) "
            "VALUES (%s, %s, %s, %s, %s)",
        (prediction_id, signal, text, user.get("id"), user.get("full_name") or user.get("username")))
    return {"id": note_id, "signal": signal}
