"""
One For All — Unified Framework Service.

Single source of truth for framework and control management across all modules.
ARIA, GRID, BCM, and Sentinel all query through this service rather than
maintaining separate framework tables.
"""
import json
import logging
from datetime import datetime
from core.timeutils import utcnow
from typing import Optional

from database import get_db, insert_returning_id
from core.events import emit

log = logging.getLogger("oneforall.frameworks")


# ── Framework CRUD ──────────────────────────────────────────────────────────

def list_frameworks(module: Optional[str] = None, active_only: bool = True) -> list[dict]:
    """List all frameworks, optionally filtered by module relevance."""
    db = get_db()
    try:
        where_clauses = []
        params = []
        if active_only:
            where_clauses.append("is_active = 1")
        if module:
            where_clauses.append("(relevant_modules LIKE %s OR relevant_modules = '')")
            params.append(f"%{module}%")
        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        rows = db.execute(
            f"SELECT id, name, description, color, type, relevant_modules, "
            f"is_active, total_controls, created_at, updated_at "
            f"FROM frameworks {where} ORDER BY name",
            params,
        ).fetchall()
        return [
            {
                "id": r[0], "name": r[1], "description": r[2], "color": r[3],
                "type": r[4], "relevant_modules": r[5], "is_active": bool(r[6]),
                "total_controls": r[7], "created_at": r[8], "updated_at": r[9],
            }
            for r in rows
        ]
    finally:
        db.close()


def get_framework(framework_id: int) -> Optional[dict]:
    """Get a single framework by ID."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT id, name, description, color, type, relevant_modules, "
            "is_active, total_controls, created_at, updated_at "
            "FROM frameworks WHERE id = %s",
            (framework_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "name": row[1], "description": row[2], "color": row[3],
            "type": row[4], "relevant_modules": row[5], "is_active": bool(row[6]),
            "total_controls": row[7], "created_at": row[8], "updated_at": row[9],
        }
    finally:
        db.close()


def activate_framework(framework_id: int, user_id: int = None) -> bool:
    """Activate a framework. Emits event for cross-module sync."""
    db = get_db()
    try:
        db.execute(
            "UPDATE frameworks SET is_active = 1, updated_at = %s WHERE id = %s",
            (utcnow().isoformat(), framework_id),
        )
        db.commit()
    finally:
        db.close()

    fw = get_framework(framework_id)
    if fw:
        emit("framework.activated", source_module="platform",
             entity_type="framework", entity_id=framework_id,
             payload={"name": fw["name"], "modules": fw["relevant_modules"]},
             user_id=user_id)
    return True


def deactivate_framework(framework_id: int, user_id: int = None) -> bool:
    """Deactivate a framework."""
    db = get_db()
    try:
        db.execute(
            "UPDATE frameworks SET is_active = 0, updated_at = %s WHERE id = %s",
            (utcnow().isoformat(), framework_id),
        )
        db.commit()
    finally:
        db.close()

    fw = get_framework(framework_id)
    if fw:
        emit("framework.deactivated", source_module="platform",
             entity_type="framework", entity_id=framework_id,
             payload={"name": fw["name"]},
             user_id=user_id)
    return True


# ── Control CRUD ────────────────────────────────────────────────────────────

def list_controls(framework_id: int, status: Optional[str] = None) -> list[dict]:
    """List controls for a framework."""
    db = get_db()
    try:
        where = "WHERE framework_id = %s"
        params: list = [framework_id]
        if status:
            where += " AND status = %s"
            params.append(status)
        rows = db.execute(
            f"SELECT id, framework_id, ref, name, description, category, doc_type, "
            f"status, priority, owner, evidence_ref, target_date, review_date, "
            f"last_updated, notes FROM controls {where} ORDER BY ref",
            params,
        ).fetchall()
        return [
            {
                "id": r[0], "framework_id": r[1], "ref": r[2], "name": r[3],
                "description": r[4], "category": r[5], "doc_type": r[6],
                "status": r[7], "priority": r[8], "owner": r[9],
                "evidence_ref": r[10], "target_date": r[11], "review_date": r[12],
                "last_updated": r[13], "notes": r[14],
            }
            for r in rows
        ]
    finally:
        db.close()


def create_control(framework_id: int, ref: str, name: str, description: str = "",
                   category: str = "", doc_type: str = "Policy",
                   priority: str = "High", user_id: int = None) -> int:
    """Create a control in the unified table. Returns control ID."""
    db = get_db()
    try:
        control_id = insert_returning_id(db,
            "INSERT INTO controls (framework_id, ref, name, description, category, "
            "doc_type, priority, last_updated) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (framework_id, ref, name, description, category, doc_type, priority,
             utcnow().isoformat()),
        )
        # Update framework control count
        db.execute(
            "UPDATE frameworks SET total_controls = "
            "(SELECT COUNT(*) FROM controls WHERE framework_id = %s), "
            "updated_at = %s WHERE id = %s",
            (framework_id, utcnow().isoformat(), framework_id),
        )
        db.commit()
        return control_id
    finally:
        db.close()


def bulk_create_controls(framework_id: int, controls_data: list[dict],
                         user_id: int = None) -> int:
    """Bulk insert controls for a framework. Returns count inserted."""
    db = get_db()
    try:
        count = 0
        for ctrl in controls_data:
            try:
                db.execute(
                    "INSERT INTO controls (framework_id, ref, name, description, "
                    "category, doc_type, priority, last_updated) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (
                        framework_id,
                        ctrl.get("ref", ""),
                        ctrl.get("name", ""),
                        ctrl.get("description", ""),
                        ctrl.get("category", ""),
                        ctrl.get("doc_type", "Policy"),
                        ctrl.get("priority", "High"),
                        utcnow().isoformat(),
                    ),
                )
                count += 1
            except Exception as e:
                log.warning("Failed to insert control %s: %s", ctrl.get("ref"), e)
        # Update count
        db.execute(
            "UPDATE frameworks SET total_controls = "
            "(SELECT COUNT(*) FROM controls WHERE framework_id = %s), "
            "updated_at = %s WHERE id = %s",
            (framework_id, utcnow().isoformat(), framework_id),
        )
        db.commit()

        emit("framework.controls_populated", source_module="platform",
             entity_type="framework", entity_id=framework_id,
             payload={"count": count}, user_id=user_id)
        return count
    finally:
        db.close()


def update_control_status(control_id: int, status: str, user_id: int = None) -> bool:
    """Update a control's status."""
    db = get_db()
    try:
        db.execute(
            "UPDATE controls SET status = %s, last_updated = %s WHERE id = %s",
            (status, utcnow().isoformat(), control_id),
        )
        db.commit()

        row = db.execute(
            "SELECT framework_id, ref, name FROM controls WHERE id = %s",
            (control_id,),
        ).fetchone()
        if row:
            emit("control.status_changed", source_module="platform",
                 entity_type="control", entity_id=control_id,
                 payload={"framework_id": row[0], "ref": row[1],
                          "name": row[2], "new_status": status},
                 user_id=user_id)
        return True
    finally:
        db.close()


# ── Cross-module links ──────────────────────────────────────────────────────

def create_link(source_module: str, source_type: str, source_id: int,
                target_module: str, target_type: str, target_id: int,
                relationship: str = "related", user_id: int = None) -> int:
    """Create a cross-module link."""
    db = get_db()
    try:
        cursor = insert_returning_id(db,
            "INSERT INTO cross_module_links (source_module, source_type, source_id, "
            "target_module, target_type, target_id, relationship, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (source_module, source_type, source_id,
             target_module, target_type, target_id, relationship, user_id),
        )
        db.commit()
        return cursor
    finally:
        db.close()


def get_links(module: str, entity_type: str, entity_id: int) -> list[dict]:
    """Get all cross-module links for an entity (as source or target)."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, source_module, source_type, source_id, "
            "target_module, target_type, target_id, relationship, created_at "
            "FROM cross_module_links "
            "WHERE (source_module = %s AND source_type = %s AND source_id = %s) "
            "   OR (target_module = %s AND target_type = %s AND target_id = %s) "
            "ORDER BY created_at DESC",
            (module, entity_type, entity_id, module, entity_type, entity_id),
        ).fetchall()
        return [
            {
                "id": r[0], "source_module": r[1], "source_type": r[2],
                "source_id": r[3], "target_module": r[4], "target_type": r[5],
                "target_id": r[6], "relationship": r[7], "created_at": r[8],
            }
            for r in rows
        ]
    finally:
        db.close()


# ── Stats ───────────────────────────────────────────────────────────────────

def get_framework_stats() -> dict:
    """Get aggregate stats across all frameworks."""
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM frameworks").fetchone()[0]
        active = db.execute("SELECT COUNT(*) FROM frameworks WHERE is_active=1").fetchone()[0]
        total_controls = db.execute("SELECT COUNT(*) FROM controls").fetchone()[0]
        compliant = db.execute(
            "SELECT COUNT(*) FROM controls WHERE status IN ('Implemented','Compliant','Complete')"
        ).fetchone()[0]
        return {
            "total_frameworks": total,
            "active_frameworks": active,
            "total_controls": total_controls,
            "compliant_controls": compliant,
            "compliance_rate": round(compliant / total_controls * 100, 1) if total_controls else 0,
        }
    finally:
        db.close()
