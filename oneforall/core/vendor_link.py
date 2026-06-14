"""
Canonical vendor registry — shared vendor identity across Sentinel, GRID, and BCM.

Each module keeps its own vendor table with module-specific fields (DPA for Sentinel,
assessment scores for GRID, criticality/SLA for BCM).  This module provides:

  ensure_canonical(db, name, contact_email) → int
      Find or create a canonical_vendors row for this company.  Call this whenever
      a vendor is created in any module; store the returned id in canonical_id.

  get_cross_module_profile(db, canonical_id) → dict
      Full cross-module summary: all module records + smart risk flags.

  get_vendor_directory(db) → list[dict]
      All canonical vendors with module-presence summary and gap flags.
"""
from __future__ import annotations

from database import insert_returning_id, IntegrityError


def _norm(name: str) -> str:
    return (name or "").strip().lower()


def ensure_canonical(db, name: str, contact_email: str | None = None) -> int | None:
    """Return existing or newly-created canonical_vendors.id for this company name.

    Race-safe: relies on the UNIQUE index on lower(trim(name)). If a concurrent
    insert wins, we catch the IntegrityError and re-SELECT the row that the
    other writer just created.
    """
    norm = _norm(name)
    if not norm:
        return None
    row = db.execute(
        "SELECT id FROM canonical_vendors WHERE lower(trim(name))=%s", (norm,)
    ).fetchone()
    if row:
        if contact_email:
            db.execute(
                "UPDATE canonical_vendors SET contact_email=COALESCE(contact_email,%s), "
                "updated_at=CURRENT_TIMESTAMP WHERE id=%s AND contact_email IS NULL",
                (contact_email, row["id"]),
            )
        return row["id"]
    try:
        cur = insert_returning_id(db,
            "INSERT INTO canonical_vendors (name, contact_email) VALUES (%s,%s)",
            (name.strip(), contact_email),
        )
        return cur
    except IntegrityError:
        # Another writer inserted the same canonical vendor between our SELECT
        # and our INSERT. Look it up again and return that id.
        row = db.execute(
            "SELECT id FROM canonical_vendors WHERE lower(trim(name))=%s", (norm,)
        ).fetchone()
        return row["id"] if row else None


def get_cross_module_profile(db, canonical_id: int) -> dict:
    """Return all module-specific records linked to this canonical_id, plus smart flags."""
    result: dict = {"canonical_id": canonical_id, "modules": {}, "flags": []}

    # Canonical base
    base = db.execute(
        "SELECT * FROM canonical_vendors WHERE id=%s", (canonical_id,)
    ).fetchone()
    if base:
        result["canonical"] = dict(base)

    # Sentinel — privacy/DPA profile
    sen = db.execute(
        "SELECT id, name, type, dpa_status, dpa_expiry, risk_level, regulation, "
        "services, contact_name, contact_email, ai_assessment "
        "FROM sentinel_vendors WHERE canonical_id=%s",
        (canonical_id,),
    ).fetchone()
    if sen:
        result["modules"]["sentinel"] = dict(sen)

    # GRID — audit/assessment profile (LEFT JOIN folds the latest assessment in
    # one round-trip; previously this was two queries per profile view).
    grid = db.execute(
        "SELECT v.id, v.name, v.risk_level, v.status, v.frameworks, v.contract_expiry, "
        "       a.score, a.assessment_date, a.findings, a.action_required "
        "FROM grid_vendors v "
        "LEFT JOIN grid_vendor_assessments a "
        "       ON a.vendor_id = v.id "
        "      AND a.assessment_date = ("
        "          SELECT MAX(assessment_date) FROM grid_vendor_assessments "
        "          WHERE vendor_id = v.id"
        "      ) "
        "WHERE v.canonical_id=%s",
        (canonical_id,),
    ).fetchone()
    if grid:
        rec = {k: grid[k] for k in (
            "id", "name", "risk_level", "status", "frameworks", "contract_expiry"
        )}
        if grid["assessment_date"] is not None:
            rec["latest_assessment"] = {
                "score": grid["score"],
                "assessment_date": grid["assessment_date"],
                "findings": grid["findings"],
                "action_required": grid["action_required"],
            }
        else:
            rec["latest_assessment"] = None
        result["modules"]["grid"] = rec

    # BCM — resilience profile
    bcm = db.execute(
        "SELECT id, name, criticality, tier, data_sensitivity, sla, "
        "contract_renewal, status, service_provided "
        "FROM bcm_vendors WHERE canonical_id=%s",
        (canonical_id,),
    ).fetchone()
    if bcm:
        result["modules"]["bcm"] = dict(bcm)

    # ── Smart flags ──────────────────────────────────────────────────────────
    sen_d  = result["modules"].get("sentinel") or {}
    grid_d = result["modules"].get("grid")     or {}
    bcm_d  = result["modules"].get("bcm")      or {}

    tier    = bcm_d.get("tier")
    crit    = (bcm_d.get("criticality") or "").lower()
    dpa     = (sen_d.get("dpa_status") or "pending").lower()
    score   = (grid_d.get("latest_assessment") or {}).get("score")

    if tier == 1 and dpa in ("pending", "", "not_required"):
        result["flags"].append({
            "level": "critical",
            "msg": "Tier 1 critical vendor has no signed DPA in Privacy",
        })
    if crit == "critical" and not sen_d:
        result["flags"].append({
            "level": "high",
            "msg": "Critical BCM vendor not assessed for data processing in Privacy",
        })
    if crit in ("high", "critical") and not grid_d:
        result["flags"].append({
            "level": "high",
            "msg": "High-criticality vendor has no compliance audit in Audit",
        })
    if score is not None and score < 50:
        result["flags"].append({
            "level": "high",
            "msg": f"Low compliance audit score ({score}%) — action required",
        })
    if dpa == "expired":
        result["flags"].append({
            "level": "high",
            "msg": "DPA has expired — renew before sharing personal data",
        })
    if not bcm_d and not grid_d and not sen_d:
        result["flags"].append({
            "level": "info",
            "msg": "Vendor only exists in one module — consider registering in others",
        })

    return result


def get_vendor_directory(db) -> list[dict]:
    """Return all canonical vendors with per-module presence summary.

    Batched: 4 queries total (canonical + sentinel + grid + bcm) regardless
    of vendor count. Previously this fired 3*N+1 queries per call.
    """
    rows = db.execute(
        "SELECT * FROM canonical_vendors WHERE status='active' OR status IS NULL "
        "ORDER BY name"
    ).fetchall()
    if not rows:
        return []

    # Pre-fetch every module's per-canonical row in one shot each, then index by canonical_id.
    sen_by_cid = {
        r["canonical_id"]: dict(r)
        for r in db.execute(
            "SELECT canonical_id, id, dpa_status, risk_level "
            "FROM sentinel_vendors WHERE canonical_id IS NOT NULL"
        ).fetchall()
    }
    grid_by_cid = {
        r["canonical_id"]: dict(r)
        for r in db.execute(
            "SELECT canonical_id, id, risk_level, status "
            "FROM grid_vendors WHERE canonical_id IS NOT NULL"
        ).fetchall()
    }
    bcm_by_cid = {
        r["canonical_id"]: dict(r)
        for r in db.execute(
            "SELECT canonical_id, id, tier, criticality, status "
            "FROM bcm_vendors WHERE canonical_id IS NOT NULL"
        ).fetchall()
    }

    out = []
    for row in rows:
        cid = row["id"]
        rec = dict(row)
        sen  = sen_by_cid.get(cid)
        grid = grid_by_cid.get(cid)
        bcm  = bcm_by_cid.get(cid)
        rec["sentinel"] = sen  or {}
        rec["grid"]     = grid or {}
        rec["bcm"]      = bcm  or {}
        rec["coverage"] = sum(1 for m in (sen, grid, bcm) if m)
        rec["risk_flag"] = None
        if bcm and bcm.get("tier") == 1 and sen and (sen.get("dpa_status") or "pending") in ("pending", "expired"):
            rec["risk_flag"] = "critical"
        elif bcm and (bcm.get("criticality") or "").lower() in ("high", "critical") and not grid:
            rec["risk_flag"] = "high"
        elif sen and (sen.get("dpa_status") or "pending") == "expired":
            rec["risk_flag"] = "high"
        out.append(rec)
    return out
