"""
PLAN-36 P07: ERM scenario analysis, risk/control/KRI/objective/external-context
linkage, and immutable board-pack snapshots.

Discovery-gate decision (task_plan.md P07, findings.md F18/P07): a scenario's
inherent and residual numbers are produced by calling the exact same
deterministic engine real risks use -- data_service.get_active_framework_matrix/
resolve_band for inherent banding and data_service._compute_residual_tiers for
the 4-tier residual ladder -- with the scenario's stored deltas substituted for
the live inputs they override. Never a separate formula, never a number an AI
invented. The methodology itself (L x I inherent, the asymmetric 5x5 banding
matrix, the tiered residual calculation, and its editable per-framework
default_residual_factor) was grounded directly against the organization's real
risk register and rating guideline during this plan's own F18 discovery work,
per the user's explicit instruction, and is already editable in the web app via
the existing framework clone-then-edit mechanism (modules/erm/routes.py's
framework-admin endpoints) -- no separate "scenario calculation template" was
built, because one already exists and this module reuses it.

compute_scenario_impact() is a pure, read-only function: calling it again with
the same scenario id, the same stored links/deltas, and the same live baseline
data returns the same numbers (P07 acceptance: "calculations reproduce from
stored inputs"). The live baseline is allowed to drift as real risks change --
that is the point of a baseline-vs-scenario comparison. The frozen,
point-in-time artifact is a board pack (generate_board_pack), which never
changes after creation except for its narrative/status/approval/staleness
columns.
"""
import hashlib
import json
import logging
import math

from config import settings
from core.ai_client import is_configured, create_message, safe_json_parse
from core.timeutils import utcnow
from database import get_db, insert_returning_id
from modules.erm import data_service as ds
from modules.erm.data_service import (
    _dict, _dicts, get_active_framework_matrix, resolve_band,
    _formula_residual, _default_residual_factor, _compute_residual_tiers,
)
from modules.governance.data_service import bu_scope_ids

log = logging.getLogger(__name__)

LINK_TYPES = {"risk", "control", "kri", "objective", "external_context"}
SCENARIO_STATUSES = {"draft", "active", "archived"}


class ScenarioError(ValueError):
    """Scenario/board-pack input or state error (400-shaped at the route layer)."""


class ForbiddenScopeError(ScenarioError):
    """A link or scenario action crosses a business-unit boundary the caller
    isn't authorized to cross, or that the data model itself forbids."""


def _now():
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _bu_allowed(scope, bu):
    """True if a record with this business_unit_id (None = org-wide) is
    visible under a bu_scope_ids() result. scope=None: unrestricted.
    scope=[-1]: only org-wide (bu is None). Otherwise: bu is None or in scope."""
    if scope is None:
        return True
    if scope == [-1]:
        return bu is None
    return bu is None or bu in scope


# ── Scenarios ────────────────────────────────────────────────────────────────

def _check_scenario_scope(scenario, scope):
    if not _bu_allowed(scope, scenario.get("business_unit_id")):
        raise ForbiddenScopeError("scenario not found")


def _check_write_scope(record, actor, resource="scenario"):
    """Enforce ownership for mutations. Organization-wide rows remain
    readable to BU-scoped users, but only an unrestricted user (or a user
    with no assigned BU) may mutate them."""
    if actor is None:
        return
    scope = bu_scope_ids(actor)
    record_bu = record.get("business_unit_id")
    if scope is None:
        return
    if record_bu is None:
        if scope == [-1]:
            return
        raise ForbiddenScopeError(f"{resource} not found")
    if scope == [-1] or record_bu not in scope:
        raise ForbiddenScopeError(f"{resource} not found")


def _resolve_write_business_unit(db, data, actor, existing=None):
    """Resolve a create/update BU without allowing a scoped caller to create
    or move a record outside their own subtree."""
    scope = bu_scope_ids(actor) if actor is not None else None
    supplied = "business_unit_id" in data
    if supplied:
        raw_bu = data.get("business_unit_id")
        try:
            requested_bu = int(raw_bu) if raw_bu not in (None, "") else None
        except (TypeError, ValueError, OverflowError):
            raise ScenarioError("business_unit_id must be an integer or null")
    elif existing is not None:
        requested_bu = existing.get("business_unit_id")
    elif scope is None or scope == [-1]:
        requested_bu = None
    else:
        requested_bu = int(actor["business_unit_id"])

    if requested_bu is not None and not db.execute(
        "SELECT 1 FROM business_units WHERE id=%s", (requested_bu,)
    ).fetchone():
        raise ScenarioError("business unit not found")
    if scope is not None:
        if requested_bu is None and scope != [-1]:
            raise ForbiddenScopeError("cannot create or move a scenario to organization-wide scope")
        if requested_bu is not None and (scope == [-1] or requested_bu not in scope):
            raise ForbiddenScopeError("business unit is outside your scope")
    return requested_bu


def list_scenarios(status=None, bu_scope=None):
    db = get_db()
    try:
        sql = "SELECT * FROM erm_scenarios WHERE 1=1"
        params = []
        if status:
            sql += " AND status=%s"
            params.append(status)
        if bu_scope is not None:
            if bu_scope == [-1]:
                sql += " AND business_unit_id IS NULL"
            else:
                placeholders = ",".join(["%s"] * len(bu_scope))
                sql += f" AND (business_unit_id IS NULL OR business_unit_id IN ({placeholders}))"
                params.extend(bu_scope)
        sql += " ORDER BY updated_at DESC"
        return _dicts(db.execute(sql, params).fetchall())
    finally:
        db.close()


def get_scenario(scenario_id, bu_scope=None):
    db = get_db()
    try:
        scenario = _dict(db.execute("SELECT * FROM erm_scenarios WHERE id=%s", (scenario_id,)).fetchone())
        if scenario and bu_scope is not None:
            _check_scenario_scope(scenario, bu_scope)
        return scenario
    finally:
        db.close()


def create_scenario(data, actor):
    title = (data.get("title") or "").strip()
    if not title:
        raise ScenarioError("title is required")
    status = data.get("status", "draft")
    if status not in SCENARIO_STATUSES:
        raise ScenarioError(f"invalid status: {status}")
    db = get_db()
    try:
        business_unit_id = _resolve_write_business_unit(db, data, actor)
        new_id = insert_returning_id(db,
            "INSERT INTO erm_scenarios (title, description, assumptions, horizon, "
            "owner_id, status, business_unit_id, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (title, data.get("description"), data.get("assumptions"), data.get("horizon"),
             data.get("owner_id"), status, business_unit_id, actor["id"]),
        )
        db.commit()
        return new_id
    finally:
        db.close()


def update_scenario(scenario_id, data, actor):
    db = get_db()
    try:
        existing = _dict(db.execute("SELECT * FROM erm_scenarios WHERE id=%s", (scenario_id,)).fetchone())
        if not existing:
            raise ScenarioError("scenario not found")
        _check_write_scope(existing, actor)
        status = data.get("status", existing["status"])
        if status not in SCENARIO_STATUSES:
            raise ScenarioError(f"invalid status: {status}")
        title = (data.get("title") if data.get("title") is not None else existing["title"]).strip()
        if not title:
            raise ScenarioError("title is required")
        business_unit_id = _resolve_write_business_unit(db, data, actor, existing=existing)
        db.execute(
            "UPDATE erm_scenarios SET title=%s, description=%s, assumptions=%s, horizon=%s, "
            "owner_id=%s, status=%s, business_unit_id=%s, version=version+1, updated_at=%s WHERE id=%s",
            (title, data.get("description", existing["description"]),
             data.get("assumptions", existing["assumptions"]), data.get("horizon", existing["horizon"]),
             data.get("owner_id", existing["owner_id"]), status,
             business_unit_id, _now(), scenario_id),
        )
        db.commit()
        return True
    finally:
        db.close()


def delete_scenario(scenario_id, actor):
    db = get_db()
    try:
        existing = _dict(db.execute("SELECT * FROM erm_scenarios WHERE id=%s", (scenario_id,)).fetchone())
        if not existing:
            return False
        _check_write_scope(existing, actor)
        if db.execute("SELECT 1 FROM erm_board_packs WHERE scenario_id=%s LIMIT 1", (scenario_id,)).fetchone():
            raise ScenarioError("cannot delete a scenario with existing board packs -- archive it instead")
        db.execute("DELETE FROM erm_scenarios WHERE id=%s", (scenario_id,))
        db.commit()
        return True
    finally:
        db.close()


# ── Scenario links ───────────────────────────────────────────────────────────

def _link_target(db, link_type, link_id):
    """Return (exists, business_unit_id, label) for a scenario link target.
    KRIs carry no business_unit_id of their own -- resolved through the
    linked risk, if any; a freestanding KRI (no linked_risk_id) has no
    business-unit scope and cannot be scope-checked (documented v1
    limitation, findings.md P07)."""
    if link_type == "risk":
        row = db.execute("SELECT business_unit_id, title FROM erm_enterprise_risks WHERE id=%s", (link_id,)).fetchone()
    elif link_type == "control":
        row = db.execute("SELECT business_unit_id, title FROM canonical_controls WHERE id=%s", (link_id,)).fetchone()
    elif link_type == "kri":
        row = db.execute(
            "SELECT k.name AS title, r.business_unit_id AS business_unit_id FROM erm_kris k "
            "LEFT JOIN erm_enterprise_risks r ON r.id = k.linked_risk_id WHERE k.id=%s",
            (link_id,),
        ).fetchone()
    elif link_type == "objective":
        row = db.execute("SELECT business_unit_id, title FROM erm_objectives WHERE id=%s", (link_id,)).fetchone()
    elif link_type == "external_context":
        row = db.execute("SELECT business_unit_id, title FROM erm_emerging_risks WHERE id=%s", (link_id,)).fetchone()
    else:
        return False, None, None
    if row is None:
        return False, None, None
    return True, row["business_unit_id"], row["title"]


def _validate_delta(link_type, delta):
    if delta is None:
        return {}
    if not isinstance(delta, dict):
        raise ScenarioError("delta must be a JSON object")

    allowed = {
        "risk": {
            "likelihood_override", "impact_override",
            "residual_likelihood_override", "residual_impact_override",
            "emv_inherent_override",
        },
        "control": {"ice_score_override"},
        "kri": {"target_value_override"},
        "objective": set(),
        "external_context": set(),
    }[link_type]
    unknown = set(delta) - allowed
    if unknown:
        raise ScenarioError(f"unsupported delta field(s) for {link_type}: {', '.join(sorted(unknown))}")

    normalized = {}
    score_fields = {
        "likelihood_override", "impact_override",
        "residual_likelihood_override", "residual_impact_override",
    }
    for key, value in delta.items():
        if value is None:
            normalized[key] = None
            continue
        if key in score_fields:
            if isinstance(value, bool):
                raise ScenarioError(f"{key} must be an integer from 1 to 5")
            try:
                number = int(value)
            except (TypeError, ValueError, OverflowError):
                raise ScenarioError(f"{key} must be an integer from 1 to 5")
            if number < 1 or number > 5 or number != float(value):
                raise ScenarioError(f"{key} must be an integer from 1 to 5")
            normalized[key] = number
        elif key == "ice_score_override":
            if isinstance(value, bool):
                raise ScenarioError(f"ice_score_override must be one of {sorted(ds.ICE_ALLOWED)}")
            try:
                number = int(value)
            except (TypeError, ValueError, OverflowError):
                raise ScenarioError(f"ice_score_override must be one of {sorted(ds.ICE_ALLOWED)}")
            if number not in ds.ICE_ALLOWED or number != float(value):
                raise ScenarioError(f"ice_score_override must be one of {sorted(ds.ICE_ALLOWED)}")
            normalized[key] = number
        else:
            if isinstance(value, bool):
                raise ScenarioError(f"{key} must be a finite number")
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError):
                raise ScenarioError(f"{key} must be a finite number")
            if not math.isfinite(number) or (key == "emv_inherent_override" and number < 0):
                qualifier = "a non-negative finite number" if key == "emv_inherent_override" else "a finite number"
                raise ScenarioError(f"{key} must be {qualifier}")
            normalized[key] = number
    return normalized


def add_scenario_link(scenario_id, link_type, link_id, delta=None, actor=None):
    if link_type not in LINK_TYPES:
        raise ScenarioError(f"invalid link_type: {link_type}")
    db = get_db()
    try:
        scenario = _dict(db.execute("SELECT * FROM erm_scenarios WHERE id=%s", (scenario_id,)).fetchone())
        if not scenario:
            raise ScenarioError("scenario not found")
        actor_scope = bu_scope_ids(actor) if actor is not None else None
        _check_write_scope(scenario, actor)
        normalized_delta = _validate_delta(link_type, delta)

        exists, target_bu, _label = _link_target(db, link_type, link_id)
        if not exists:
            raise ScenarioError(f"{link_type} {link_id} not found")

        scenario_bu = scenario["business_unit_id"]
        if scenario_bu is not None and target_bu is not None and scenario_bu != target_bu:
            raise ForbiddenScopeError(
                f"cannot link {link_type} {link_id} (business unit {target_bu}) to a "
                f"scenario scoped to a different business unit ({scenario_bu})"
            )
        if not _bu_allowed(actor_scope, target_bu):
            raise ForbiddenScopeError(f"{link_type} {link_id} is outside your business unit scope")

        db.execute(
            "INSERT INTO erm_scenario_links (scenario_id, link_type, link_id, delta_json, created_by) "
            "VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (scenario_id, link_type, link_id) DO UPDATE SET delta_json=excluded.delta_json",
            (scenario_id, link_type, link_id, _canonical_json(normalized_delta), actor["id"] if actor else None),
        )
        row = db.execute(
            "SELECT id FROM erm_scenario_links WHERE scenario_id=%s AND link_type=%s AND link_id=%s",
            (scenario_id, link_type, link_id),
        ).fetchone()
        db.commit()
        return row["id"]
    finally:
        db.close()


def remove_scenario_link(scenario_id, link_type, link_id, actor=None):
    db = get_db()
    try:
        scenario = _dict(db.execute("SELECT * FROM erm_scenarios WHERE id=%s", (scenario_id,)).fetchone())
        if not scenario:
            return False
        _check_write_scope(scenario, actor)
        db.execute(
            "DELETE FROM erm_scenario_links WHERE scenario_id=%s AND link_type=%s AND link_id=%s",
            (scenario_id, link_type, link_id),
        )
        db.commit()
        return True
    finally:
        db.close()


def list_scenario_links(scenario_id):
    db = get_db()
    try:
        links = _dicts(db.execute(
            "SELECT * FROM erm_scenario_links WHERE scenario_id=%s ORDER BY link_type, id", (scenario_id,)
        ).fetchall())
        for link in links:
            exists, bu, label = _link_target(db, link["link_type"], link["link_id"])
            link["exists"] = exists
            link["business_unit_id"] = bu
            link["label"] = label
            link["delta"] = json.loads(link.pop("delta_json") or "{}")
        return links
    finally:
        db.close()


# ── Scenario impact calculation ─────────────────────────────────────────────

def _scenario_ice_rollup(db, risk_id, control_overrides):
    """Same shape/semantics as data_service._ice_rollup, but substitutes a
    scenario's control-ICE overrides for the real risk_controls.ice_score
    where provided -- including for a control with no real ICE score yet,
    which can legitimately flip a risk from the no-controls-scored default
    tier into the ICE tier within the scenario (a realistic "what if we
    actually assessed this control" question)."""
    rows = db.execute("SELECT control_id, ice_score FROM risk_controls WHERE risk_id=%s", (risk_id,)).fetchall()
    scores = []
    for r in rows:
        if r["control_id"] in control_overrides:
            scores.append(control_overrides[r["control_id"]])
        elif r["ice_score"] is not None:
            scores.append(r["ice_score"])
    if not scores:
        return {"scored": False, "loa_pct": None, "lor": None}
    loa_pct = round(sum(scores) / len(scores))
    return {"scored": True, "loa_pct": loa_pct, "lor": 1.0 - (loa_pct / 100.0)}


def compute_scenario_impact(scenario_id):
    """Pure, reproducible baseline-vs-scenario comparison. Never writes to
    erm_enterprise_risks or any other live table. See module docstring for
    the reproducibility guarantee."""
    db = get_db()
    try:
        scenario = _dict(db.execute("SELECT * FROM erm_scenarios WHERE id=%s", (scenario_id,)).fetchone())
        if not scenario:
            return None
        links = _dicts(db.execute("SELECT * FROM erm_scenario_links WHERE scenario_id=%s ORDER BY link_type, id", (scenario_id,)).fetchall())

        control_overrides = {}
        for link in links:
            if link["link_type"] != "control":
                continue
            delta = json.loads(link["delta_json"] or "{}")
            if delta.get("ice_score_override") is not None:
                control_overrides[link["link_id"]] = int(delta["ice_score_override"])

        fw_matrix = get_active_framework_matrix(db)
        default_factor = _default_residual_factor(db)

        per_risk = []
        data_quality_issues = []
        baseline_irr, baseline_rrr, baseline_emv_i, baseline_emv_r = [], [], [], []
        scenario_irr, scenario_rrr, scenario_emv_i, scenario_emv_r = [], [], [], []
        category_track = {}  # category -> {"baseline_max":.., "scenario_max":..}

        for link in links:
            if link["link_type"] != "risk":
                continue
            risk = _dict(db.execute("SELECT * FROM erm_enterprise_risks WHERE id=%s", (link["link_id"],)).fetchone())
            if not risk:
                data_quality_issues.append({"link_type": "risk", "link_id": link["link_id"], "issue": "risk_not_found"})
                continue
            delta = json.loads(link["delta_json"] or "{}")

            b_L, b_I = risk["likelihood"] or 3, risk["impact"] or 3
            b_irr = risk["irr_score"] if risk["irr_score"] is not None else b_L * b_I
            b_emv_i = risk["emv_inherent"]
            baseline = {
                "irr": b_irr, "rrr": risk["rrr"], "residual_score": risk["residual_score"],
                "loa_pct": risk["loa_pct"], "emv_inherent": b_emv_i, "emv_residual": risk["emv_residual"],
                "band": resolve_band(fw_matrix, b_L, b_I), "likelihood": b_L, "impact": b_I,
            }

            s_L = int(delta["likelihood_override"]) if delta.get("likelihood_override") is not None else b_L
            s_I = int(delta["impact_override"]) if delta.get("impact_override") is not None else b_I
            s_irr = s_L * s_I
            s_emv_i = float(delta["emv_inherent_override"]) if delta.get("emv_inherent_override") is not None else b_emv_i
            s_RL = delta.get("residual_likelihood_override", risk["residual_likelihood"])
            s_RI = delta.get("residual_impact_override", risk["residual_impact"])
            s_ice = _scenario_ice_rollup(db, risk["id"], control_overrides)

            if s_ice["scored"]:
                tier = _compute_residual_tiers(irr=s_irr, emv_i=s_emv_i, ice=s_ice)
            elif s_RL is not None and s_RI is not None:
                tier = _compute_residual_tiers(irr=s_irr, emv_i=s_emv_i, residual_likelihood=s_RL, residual_impact=s_RI)
            else:
                weighted_eff = _formula_residual(db, risk["id"])
                if weighted_eff is not None:
                    tier = _compute_residual_tiers(irr=s_irr, emv_i=s_emv_i, weighted_effectiveness=weighted_eff)
                else:
                    tier = _compute_residual_tiers(irr=s_irr, emv_i=s_emv_i, default_factor=default_factor)

            scenario_calc = {
                "irr": s_irr, "rrr": tier["rrr"], "residual_score": tier["residual_score"],
                "loa_pct": tier["loa_pct"], "emv_inherent": s_emv_i, "emv_residual": tier["emv_residual"],
                "band": resolve_band(fw_matrix, s_L, s_I), "likelihood": s_L, "impact": s_I,
            }

            per_risk.append({
                "risk_id": risk["id"], "title": risk["title"], "category": risk["category"],
                "baseline": baseline, "scenario": scenario_calc, "delta_applied": delta,
            })

            if risk.get("category"):
                track = category_track.setdefault(risk["category"], {"baseline_max": None, "scenario_max": None})
                b_exposure = baseline["rrr"] if baseline["rrr"] is not None else baseline["irr"]
                if track["baseline_max"] is None or b_exposure > track["baseline_max"]:
                    track["baseline_max"] = b_exposure
                if track["scenario_max"] is None or scenario_calc["rrr"] > track["scenario_max"]:
                    track["scenario_max"] = scenario_calc["rrr"]

            baseline_irr.append(b_irr)
            baseline_rrr.append(risk["rrr"] if risk["rrr"] is not None else b_irr)
            if b_emv_i is not None:
                baseline_emv_i.append(b_emv_i)
            if risk["emv_residual"] is not None:
                baseline_emv_r.append(risk["emv_residual"])

            scenario_irr.append(s_irr)
            scenario_rrr.append(tier["rrr"])
            if s_emv_i is not None:
                scenario_emv_i.append(s_emv_i)
            if tier["emv_residual"] is not None:
                scenario_emv_r.append(tier["emv_residual"])

        for link in links:
            if link["link_type"] != "control":
                continue
            if not db.execute("SELECT 1 FROM canonical_controls WHERE id=%s", (link["link_id"],)).fetchone():
                data_quality_issues.append({"link_type": "control", "link_id": link["link_id"], "issue": "control_not_found"})

        kris = []
        for link in links:
            if link["link_type"] != "kri":
                continue
            kri = _dict(db.execute("SELECT * FROM erm_kris WHERE id=%s", (link["link_id"],)).fetchone())
            if not kri:
                data_quality_issues.append({"link_type": "kri", "link_id": link["link_id"], "issue": "kri_not_found"})
                continue
            history = db.execute(
                "SELECT value FROM erm_kri_history WHERE kri_id=%s ORDER BY recorded_at DESC, id DESC LIMIT 1",
                (kri["id"],),
            ).fetchone()
            missing = history is None
            if missing:
                data_quality_issues.append({"link_type": "kri", "link_id": kri["id"], "issue": "missing_kri_value"})
            delta = json.loads(link["delta_json"] or "{}")
            kris.append({
                "kri_id": kri["id"], "name": kri.get("name"),
                "latest_value": history["value"] if history else None,
                "missing": missing, "target_override": delta.get("target_value_override"),
            })

        objectives = []
        for link in links:
            if link["link_type"] != "objective":
                continue
            obj = _dict(db.execute("SELECT * FROM erm_objectives WHERE id=%s", (link["link_id"],)).fetchone())
            if not obj:
                data_quality_issues.append({"link_type": "objective", "link_id": link["link_id"], "issue": "objective_not_found"})
                continue
            objectives.append({"objective_id": obj["id"], "title": obj.get("title")})

        external_context = []
        for link in links:
            if link["link_type"] != "external_context":
                continue
            ctx = _dict(db.execute("SELECT * FROM erm_emerging_risks WHERE id=%s", (link["link_id"],)).fetchone())
            if not ctx:
                data_quality_issues.append({"link_type": "external_context", "link_id": link["link_id"], "issue": "external_context_not_found"})
                continue
            external_context.append({"id": ctx["id"], "title": ctx.get("title"), "source_note": ctx.get("source_note")})

        def _avg(lst):
            return round(sum(lst) / len(lst), 1) if lst else None

        def _sum(lst):
            return round(sum(lst), 2) if lst else None

        # Appetite impact is scoped to THIS scenario's own linked risks (which
        # category's exposure, among the risks actually in play here, would
        # move against its configured appetite) -- not a whole-register scan,
        # which the existing ERM dashboard already covers and this would only
        # duplicate.
        appetite_rows = _dicts(db.execute("SELECT category, max_score FROM erm_risk_appetite").fetchall())
        appetite_limits = {a["category"]: a["max_score"] for a in appetite_rows}
        appetite_impact = []
        for category, track in category_track.items():
            max_score = appetite_limits.get(category)
            if max_score is None:
                continue
            appetite_impact.append({
                "category": category, "max_score": max_score,
                "baseline_max_exposure": track["baseline_max"], "scenario_max_exposure": track["scenario_max"],
                "baseline_breached": track["baseline_max"] is not None and track["baseline_max"] > max_score,
                "scenario_breached": track["scenario_max"] is not None and track["scenario_max"] > max_score,
            })

        return {
            "scenario": scenario,
            "baseline_totals": {
                "avg_irr": _avg(baseline_irr), "avg_rrr": _avg(baseline_rrr),
                "emv_i_total": _sum(baseline_emv_i), "emv_r_total": _sum(baseline_emv_r),
            },
            "scenario_totals": {
                "avg_irr": _avg(scenario_irr), "avg_rrr": _avg(scenario_rrr),
                "emv_i_total": _sum(scenario_emv_i), "emv_r_total": _sum(scenario_emv_r),
            },
            "per_risk": per_risk,
            "kris": kris,
            "objectives": objectives,
            "external_context": external_context,
            "appetite_impact": appetite_impact,
            "data_quality_issues": data_quality_issues,
        }
    finally:
        db.close()


# ── Board packs ──────────────────────────────────────────────────────────────

def _source_record_hash(db, link_type, link_id):
    """A stable hash of a linked source record's fields relevant to the
    calculation, used later to detect drift without storing the whole row."""
    if link_type == "risk":
        row = db.execute(
            "SELECT likelihood, impact, residual_likelihood, residual_impact, irr_score, "
            "rrr, residual_score, loa_pct, emv_inherent, emv_residual, status "
            "FROM erm_enterprise_risks WHERE id=%s", (link_id,),
        ).fetchone()
        fingerprint = dict(row) if row else None
    elif link_type == "control":
        rows = db.execute(
            "SELECT risk_id, ice_score FROM risk_controls WHERE control_id=%s ORDER BY risk_id", (link_id,)
        ).fetchall()
        fingerprint = {"ice_scores": [dict(r) for r in rows]} if rows else None
    elif link_type == "kri":
        row = db.execute(
            "SELECT value FROM erm_kri_history WHERE kri_id=%s ORDER BY recorded_at DESC, id DESC LIMIT 1",
            (link_id,),
        ).fetchone()
        fingerprint = dict(row) if row else {"value": None}
    elif link_type == "objective":
        row = db.execute("SELECT status FROM erm_objectives WHERE id=%s", (link_id,)).fetchone()
        fingerprint = dict(row) if row else None
    elif link_type == "external_context":
        row = db.execute("SELECT status FROM erm_emerging_risks WHERE id=%s", (link_id,)).fetchone()
        fingerprint = dict(row) if row else None
    else:
        fingerprint = None
    if fingerprint is None:
        return None
    return _sha256(_canonical_json(fingerprint))


def _baseline_snapshot(filters):
    return {
        "dashboard": ds.get_dashboard_stats(filters or None),
        "appetite_status": ds.get_appetite_status(),
    }


def _scenario_dependency_hash(db, scenario_id):
    """Hash every stored input family that can affect a scenario calculation,
    including inputs whose edit happens to leave the current numeric output
    unchanged."""
    scenario = _dict(db.execute(
        "SELECT * FROM erm_scenarios WHERE id=%s", (scenario_id,)
    ).fetchone())
    if not scenario:
        return None
    links = _dicts(db.execute(
        "SELECT * FROM erm_scenario_links WHERE scenario_id=%s "
        "ORDER BY link_type, link_id, id",
        (scenario_id,),
    ).fetchall())
    frameworks = _dicts(db.execute(
        "SELECT * FROM erm_risk_frameworks WHERE is_active=1 ORDER BY id"
    ).fetchall())
    framework_ids = [row["id"] for row in frameworks]
    bands = []
    matrix = []
    if framework_ids:
        placeholders = ",".join(["%s"] * len(framework_ids))
        bands = _dicts(db.execute(
            f"SELECT * FROM erm_framework_bands WHERE framework_id IN ({placeholders}) "
            "ORDER BY framework_id, id",
            framework_ids,
        ).fetchall())
        matrix = _dicts(db.execute(
            f"SELECT * FROM erm_framework_matrix_bands WHERE framework_id IN ({placeholders}) "
            "ORDER BY framework_id, likelihood, impact, id",
            framework_ids,
        ).fetchall())

    risk_ids = sorted({
        int(link["link_id"]) for link in links if link["link_type"] == "risk"
    })
    risk_controls = []
    effectiveness = []
    if risk_ids:
        placeholders = ",".join(["%s"] * len(risk_ids))
        risk_controls = _dicts(db.execute(
            f"SELECT * FROM risk_controls WHERE risk_id IN ({placeholders}) "
            "ORDER BY risk_id, control_id, id",
            risk_ids,
        ).fetchall())
        effectiveness = _dicts(db.execute(
            "SELECT rc.risk_id, ces.* FROM control_effectiveness_scores ces "
            "JOIN risk_controls rc ON rc.control_id=ces.control_id "
            f"WHERE rc.risk_id IN ({placeholders}) "
            "ORDER BY rc.risk_id, ces.control_id, ces.id",
            risk_ids,
        ).fetchall())

    appetite = _dicts(db.execute(
        "SELECT * FROM erm_risk_appetite ORDER BY id"
    ).fetchall())
    return _sha256(_canonical_json({
        "scenario": scenario,
        "links": links,
        "frameworks": frameworks,
        "bands": bands,
        "matrix": matrix,
        "appetite": appetite,
        "risk_controls": risk_controls,
        "effectiveness": effectiveness,
    }))

def _current_source_hash(db, key, filters):
    if key == "baseline_snapshot":
        return _sha256(_canonical_json(_baseline_snapshot(filters)))
    if key.startswith("scenario_snapshot:"):
        try:
            scenario_id = int(key.split(":", 1)[1])
        except (TypeError, ValueError, OverflowError):
            return None
        snapshot = compute_scenario_impact(scenario_id)
        return _sha256(_canonical_json(snapshot)) if snapshot is not None else None
    if key.startswith("scenario_dependencies:"):
        try:
            scenario_id = int(key.split(":", 1)[1])
        except (TypeError, ValueError, OverflowError):
            return None
        return _scenario_dependency_hash(db, scenario_id)
    try:
        link_type, link_id = key.split(":", 1)
        return _source_record_hash(db, link_type, int(link_id))
    except (TypeError, ValueError, OverflowError):
        return None


def _lock_board_pack_chain(db):
    """Serialize selection of the previous chain head and insertion of the
    next row across processes, on both production PostgreSQL and SQLite."""
    if settings.is_postgres():
        db.execute("LOCK TABLE erm_board_packs IN SHARE ROW EXCLUSIVE MODE")
    else:
        db.execute("BEGIN IMMEDIATE")


def generate_board_pack(scenario_id=None, filters=None, actor=None):
    """Create an immutable, BU-scoped board-pack snapshot and append it to
    the tenant's serialized tamper-evident hash chain."""
    if filters is not None and not isinstance(filters, dict):
        raise ScenarioError("filters must be a JSON object")
    filters = filters or {}
    db = get_db()
    try:
        as_of = _now()

        if scenario_id is not None:
            scenario = _dict(db.execute("SELECT * FROM erm_scenarios WHERE id=%s", (scenario_id,)).fetchone())
            if not scenario:
                raise ScenarioError("scenario not found")
            if actor is not None:
                _check_write_scope(scenario, actor)
            business_unit_id = scenario.get("business_unit_id")
            source_snapshot = compute_scenario_impact(scenario_id)
            link_refs = [
                (l["link_type"], l["link_id"]) for l in _dicts(
                    db.execute(
                        "SELECT link_type, link_id FROM erm_scenario_links WHERE scenario_id=%s",
                        (scenario_id,),
                    ).fetchall()
                )
            ]
            source_hashes = {
                f"{lt}:{lid}": _source_record_hash(db, lt, lid)
                for lt, lid in link_refs
            }
            # This aggregate hash covers scenario fields, link membership and
            # deltas, framework/appetite settings, and indirect control state
            # because all of those feed compute_scenario_impact().
            source_hashes[f"scenario_snapshot:{scenario_id}"] = _sha256(
                _canonical_json(source_snapshot)
            )
            source_hashes[f"scenario_dependencies:{scenario_id}"] = (
                _scenario_dependency_hash(db, scenario_id)
            )
        else:
            if actor is not None and bu_scope_ids(actor) is not None:
                raise ForbiddenScopeError(
                    "baseline-only board packs require organization-wide scope"
                )
            business_unit_id = None
            source_snapshot = _baseline_snapshot(filters)
            source_hashes = {
                "baseline_snapshot": _sha256(_canonical_json(source_snapshot))
            }

        filters_json = _canonical_json(filters)
        source_snapshot_json = _canonical_json(source_snapshot)
        source_hashes_json = _canonical_json(source_hashes)

        _lock_board_pack_chain(db)
        prev = db.execute(
            "SELECT content_hash FROM erm_board_packs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_hash = prev["content_hash"] if prev else None

        content_hash = _sha256(_canonical_json({
            "scenario_id": scenario_id,
            "filters": filters_json,
            "as_of": as_of,
            "source_snapshot": source_snapshot_json,
            "source_hashes": source_hashes_json,
            "prev_hash": prev_hash,
        }))

        new_id = insert_returning_id(
            db,
            "INSERT INTO erm_board_packs (scenario_id, business_unit_id, filters_json, as_of, "
            "source_snapshot_json, source_hashes_json, content_hash, prev_hash, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                scenario_id, business_unit_id, filters_json, as_of,
                source_snapshot_json, source_hashes_json, content_hash,
                prev_hash, actor["id"] if actor else None,
            ),
        )
        db.commit()
        return new_id
    finally:
        db.close()


def _hydrate_board_pack(row):
    d = dict(row)
    d["filters"] = json.loads(d.pop("filters_json") or "{}")
    d["source_snapshot"] = json.loads(d.pop("source_snapshot_json") or "{}")
    d["source_hashes"] = json.loads(d.pop("source_hashes_json") or "{}")
    citations_raw = d.pop("narrative_citations_json", None)
    d["narrative_citations"] = json.loads(citations_raw) if citations_raw else []
    d["is_stale"] = bool(d["is_stale"])
    return d


def get_board_pack(board_pack_id, bu_scope=None):
    db = get_db()
    try:
        row = _dict(db.execute(
            "SELECT * FROM erm_board_packs WHERE id=%s", (board_pack_id,)
        ).fetchone())
        if row and bu_scope is not None and not _bu_allowed(
            bu_scope, row.get("business_unit_id")
        ):
            raise ForbiddenScopeError("board pack not found")
        return _hydrate_board_pack(row) if row else None
    finally:
        db.close()


def list_board_packs(scenario_id=None, status=None, bu_scope=None):
    db = get_db()
    try:
        sql = "SELECT * FROM erm_board_packs WHERE 1=1"
        params = []
        if scenario_id is not None:
            sql += " AND scenario_id=%s"
            params.append(scenario_id)
        if status:
            sql += " AND status=%s"
            params.append(status)
        if bu_scope is not None:
            if bu_scope == [-1]:
                sql += " AND business_unit_id IS NULL"
            else:
                placeholders = ",".join(["%s"] * len(bu_scope))
                sql += f" AND (business_unit_id IS NULL OR business_unit_id IN ({placeholders}))"
                params.extend(bu_scope)
        sql += " ORDER BY id DESC"
        return [_hydrate_board_pack(r) for r in db.execute(sql, params).fetchall()]
    finally:
        db.close()


def sweep_stale_board_packs():
    """Flag snapshots whose aggregate deterministic output or cited source
    records differ from current data. Immutable snapshot fields are untouched."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, filters_json, source_hashes_json "
            "FROM erm_board_packs WHERE is_stale=0"
        ).fetchall()
        newly_stale = []
        for row in rows:
            filters = json.loads(row["filters_json"] or "{}")
            hashes = json.loads(row["source_hashes_json"] or "{}")
            stale_keys = [
                key for key, old_hash in hashes.items()
                if _current_source_hash(db, key, filters) != old_hash
            ]
            if stale_keys:
                db.execute(
                    "UPDATE erm_board_packs SET is_stale=1, stale_reason=%s WHERE id=%s",
                    (
                        "source(s) changed since this snapshot was generated: "
                        + ", ".join(stale_keys),
                        row["id"],
                    ),
                )
                newly_stale.append(row["id"])
        db.commit()
        return newly_stale
    finally:
        db.close()


def update_board_pack_narrative(board_pack_id, narrative, citations, source, actor=None):
    """Update a draft narrative atomically; publication wins any concurrent
    race and makes the write fail closed."""
    if source not in ("human", "ai_edited"):
        raise ScenarioError("source must be 'human' or 'ai_edited'")
    if not isinstance(citations, list):
        raise ScenarioError("citations must be a JSON array")
    db = get_db()
    try:
        row = _dict(db.execute(
            "SELECT * FROM erm_board_packs WHERE id=%s", (board_pack_id,)
        ).fetchone())
        if not row:
            raise ScenarioError("board pack not found")
        _check_write_scope(row, actor, "board pack")
        cursor = db.execute(
            "UPDATE erm_board_packs SET narrative=%s, narrative_citations_json=%s, "
            "narrative_source=%s WHERE id=%s AND status='draft'",
            (narrative, _canonical_json(citations), source, board_pack_id),
        )
        if cursor.rowcount != 1:
            db.rollback()
            raise ScenarioError("cannot edit a published board pack's narrative")
        db.commit()
        return True
    finally:
        db.close()


def generate_board_pack_narrative(board_pack_id, actor=None):
    """Generate a cited AI draft and write it only if the pack is still a
    draft after the provider call returns."""
    scope = bu_scope_ids(actor) if actor is not None else None
    pack = get_board_pack(board_pack_id, bu_scope=scope)
    if not pack:
        raise ScenarioError("board pack not found")
    _check_write_scope(pack, actor, "board pack")
    if pack["status"] == "published":
        raise ScenarioError("cannot regenerate a published board pack's narrative")

    if not is_configured():
        return {"ok": False, "reason": "AI provider is not configured"}

    allowed_refs = sorted(
        key for key in pack["source_hashes"]
        if key.split(":", 1)[0] in LINK_TYPES
    )
    if not allowed_refs:
        return {"ok": False, "reason": "no source references to cite -- add scenario links or risks first"}

    prompt = (
        "You are writing the narrative for a board risk report. Use ONLY the "
        "data below; do not invent numbers or sources.\n\n"
        f"Snapshot data: {json.dumps(pack['source_snapshot'], default=str)}\n\n"
        f"Allowed citation references (cite ONLY these, exactly as spelled): {allowed_refs}\n\n"
        "Return JSON only, shaped exactly as: "
        '{"narrative": "<3-4 professional paragraphs>", '
        '"citations": [{"ref": "<one of the allowed references>", "claim": "<short claim this supports>"}]}. '
        "Include at least one citation for every material claim."
    )
    try:
        text = create_message([{"role": "user", "content": prompt}], max_tokens=1800)
    except Exception as exc:
        log.error("P07 board pack narrative generation failed: %s", exc)
        return {"ok": False, "reason": "AI request failed"}

    parsed = safe_json_parse(text, None)
    if not isinstance(parsed, dict) or not parsed.get("narrative") or not parsed.get("citations"):
        return {"ok": False, "reason": "AI response did not include a narrative with citations"}

    citations = parsed["citations"]
    if not isinstance(citations, list) or not citations:
        return {"ok": False, "reason": "AI response had no citations"}
    allowed_set = set(allowed_refs)
    for citation in citations:
        if not isinstance(citation, dict) or citation.get("ref") not in allowed_set:
            bad = citation.get("ref") if isinstance(citation, dict) else citation
            return {"ok": False, "reason": f"AI response cited an unknown source: {bad}"}

    db = get_db()
    try:
        current = _dict(db.execute(
            "SELECT * FROM erm_board_packs WHERE id=%s", (board_pack_id,)
        ).fetchone())
        if not current:
            raise ScenarioError("board pack not found")
        _check_write_scope(current, actor, "board pack")
        cursor = db.execute(
            "UPDATE erm_board_packs SET narrative=%s, narrative_citations_json=%s, "
            "narrative_source='ai' WHERE id=%s AND status='draft'",
            (parsed["narrative"], _canonical_json(citations), board_pack_id),
        )
        if cursor.rowcount != 1:
            db.rollback()
            raise ScenarioError("cannot regenerate a published board pack's narrative")
        db.commit()
    finally:
        db.close()
    return {"ok": True, "narrative": parsed["narrative"], "citations": citations}


def publish_board_pack(board_pack_id, actor):
    db = get_db()
    try:
        row = _dict(db.execute(
            "SELECT * FROM erm_board_packs WHERE id=%s", (board_pack_id,)
        ).fetchone())
        if not row:
            raise ScenarioError("board pack not found")
        _check_write_scope(row, actor, "board pack")
        if row["status"] == "published":
            return True
        if not row["narrative"]:
            raise ScenarioError(
                "cannot publish a board pack with no narrative -- write or generate one first"
            )
        now = _now()
        cursor = db.execute(
            "UPDATE erm_board_packs SET status='published', approved_by=%s, "
            "approved_at=%s, published_at=%s WHERE id=%s AND status='draft'",
            (actor["id"], now, now, board_pack_id),
        )
        if cursor.rowcount != 1:
            db.rollback()
            raise ScenarioError("board pack was already published")
        db.commit()
        return True
    finally:
        db.close()


def verify_board_pack_chain(bu_scope=None):
    """Verify the complete tenant chain, returning only problems attached to
    packs visible to the caller's BU scope."""
    db = get_db()
    try:
        rows = _dicts(db.execute(
            "SELECT id, scenario_id, business_unit_id, filters_json, as_of, "
            "source_snapshot_json, source_hashes_json, content_hash, prev_hash "
            "FROM erm_board_packs ORDER BY id"
        ).fetchall())
        problems = []
        expected_prev = None
        for row in rows:
            visible = _bu_allowed(bu_scope, row.get("business_unit_id"))
            recomputed = _sha256(_canonical_json({
                "scenario_id": row["scenario_id"],
                "filters": row["filters_json"],
                "as_of": row["as_of"],
                "source_snapshot": row["source_snapshot_json"],
                "source_hashes": row["source_hashes_json"],
                "prev_hash": row["prev_hash"],
            }))
            snapshot = json.loads(row["source_snapshot_json"] or "{}")
            snapshot_scenario = snapshot.get("scenario") if isinstance(snapshot, dict) else None
            expected_bu = (
                snapshot_scenario.get("business_unit_id")
                if isinstance(snapshot_scenario, dict) else None
            )
            scope_mismatch = (
                row["scenario_id"] is not None
                and row.get("business_unit_id") != expected_bu
            )
            if visible and scope_mismatch:
                problems.append({
                    "id": row["id"],
                    "issue": "business_unit_id does not match the frozen scenario scope",
                })
            if visible and recomputed != row["content_hash"]:
                problems.append({
                    "id": row["id"],
                    "issue": "content_hash mismatch -- row was altered after creation",
                })
            if visible and row["prev_hash"] != expected_prev:
                problems.append({
                    "id": row["id"],
                    "issue": "prev_hash does not match the preceding pack -- chain broken",
                })
            expected_prev = row["content_hash"]
        return problems
    finally:
        db.close()