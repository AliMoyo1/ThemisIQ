"""Reviewable reconciliation of historical module file references.

No historical source bytes are removed. BCM's old paths were supplied by
clients, so those rows require a human to choose an existing Vault artifact.
"""
from __future__ import annotations

import os
import hashlib
from pathlib import Path

from core.rbac import has_capability
from database import get_db, insert_returning_id
from modules.evidence import storage
from modules.evidence.scope import evidence_scope_sql
from modules.governance.entity_scope import entity_scope_sql


def _require(user: dict, capability: str) -> int:
    if not has_capability(user, capability) or not user.get("org_id"):
        raise PermissionError("You cannot reconcile these records")
    return user["org_id"]


def _link(db, evidence_id: int, entity_type: str, entity_id: int, user_id: int) -> None:
    present = db.execute(
        "SELECT id FROM evidence_links WHERE evidence_id=%s AND module='grid' "
        "AND entity_type=%s AND entity_id=%s AND deleted_at IS NULL",
        (evidence_id, entity_type, entity_id),
    ).fetchone()
    if not present:
        db.execute(
            "INSERT INTO evidence_links (evidence_id,module,entity_type,entity_id,linked_by) "
            "VALUES (%s,'grid',%s,%s,%s)", (evidence_id, entity_type, entity_id, user_id))


def _checked_grid_source(file_path: str, original_name: str, mime_type: str | None) -> tuple[bytes, dict]:
    root = Path(os.getenv("GRID_UPLOAD_DIR", "data/grid_uploads")).resolve()
    source = Path(file_path).resolve() if file_path else None
    if source is None or not source.is_relative_to(root) or not source.is_file():
        raise ValueError("Historical source requires manual review")
    if source.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("Historical source is too large")
    content = source.read_bytes()
    return content, storage.describe(content, original_name, mime_type,
                                     max_bytes=50 * 1024 * 1024)


def grid_inventory(user: dict) -> list[dict]:
    """Scoped inventory with no legacy paths returned to the caller."""
    _require(user, "module.grid.access")
    scope, params = entity_scope_sql(("grid", "control"), user, "c")
    db = get_db()
    try:
        rows = db.execute(
            "SELECT f.id, f.control_id, f.original_name, f.file_path, f.version, "
            "x.vault_evidence_id FROM grid_evidence_files f "
            "JOIN grid_controls c ON c.id=f.control_id "
            "LEFT JOIN evidence_file_crosswalk x ON x.module='grid' AND x.source_id=f.id "
            "AND x.org_id=%s "
            f"WHERE {scope} ORDER BY f.id", [user["org_id"], *params],
        ).fetchall()
        result = []
        root = Path(os.getenv("GRID_UPLOAD_DIR", "data/grid_uploads")).resolve()
        for row in rows:
            path = row["file_path"] or ""
            if path.startswith("vault://"):
                state = "vault"
            elif path.startswith("aria://"):
                state = "aria_reference"
            else:
                source = Path(path).resolve() if path else None
                state = ("safe_local_file" if source and source.is_relative_to(root) and source.is_file()
                         else "manual_review")
            result.append({"id": row["id"], "control_id": row["control_id"],
                           "name": row["original_name"], "version": row["version"],
                           "state": state, "vault_evidence_id": row["vault_evidence_id"]})
        return result
    finally:
        db.close()


def grid_version_inventory(user: dict) -> list[dict]:
    """Scoped historical version inventory. Only safe state, never source paths."""
    _require(user, "module.grid.access")
    scope, params = entity_scope_sql(("grid", "control"), user, "c")
    db = get_db()
    try:
        rows = db.execute(
            "SELECT v.id, v.evidence_id, v.original_name, v.version, v.file_path, "
            "x.vault_evidence_id FROM grid_evidence_versions v "
            "JOIN grid_evidence_files f ON f.id=v.evidence_id "
            "JOIN grid_controls c ON c.id=f.control_id "
            "LEFT JOIN evidence_file_crosswalk x ON x.module='grid_version' AND x.source_id=v.id "
            f"AND x.org_id=%s WHERE {scope} ORDER BY v.id",
            [user["org_id"], *params],
        ).fetchall()
        root = Path(os.getenv("GRID_UPLOAD_DIR", "data/grid_uploads")).resolve()
        result = []
        for row in rows:
            path = row["file_path"] or ""
            source = Path(path).resolve() if path and not path.startswith("vault://") else None
            state = ("vault" if path.startswith("vault://") else
                     "safe_local_file" if source and source.is_relative_to(root) and source.is_file() else
                     "manual_review")
            result.append({"id": row["id"], "evidence_id": row["evidence_id"],
                           "name": row["original_name"], "version": row["version"],
                           "state": state, "vault_evidence_id": row["vault_evidence_id"]})
        return result
    finally:
        db.close()


def migrate_grid_file(source_id: int, user: dict) -> int:
    """Idempotently copy a trusted GRID file and change its reference to Vault."""
    org_id = _require(user, "grid.evidence.upload")
    scope, params = entity_scope_sql(("grid", "control"), user, "c")
    db = get_db()
    stored_path = None
    try:
        row = db.execute(
            "SELECT f.*, c.audit_id, a.business_unit_id FROM grid_evidence_files f "
            "JOIN grid_controls c ON c.id=f.control_id "
            "JOIN grid_audits a ON a.id=c.audit_id "
            f"WHERE f.id=%s AND {scope}", [source_id, *params],
        ).fetchone()
        if row is None:
            raise LookupError("GRID file not found")
        prior = db.execute(
            "SELECT vault_evidence_id FROM evidence_file_crosswalk "
            "WHERE org_id=%s AND module='grid' AND source_id=%s", (org_id, source_id),
        ).fetchone()
        if prior:
            prior_scope, prior_params = evidence_scope_sql(user)
            if db.execute(
                f"SELECT 1 FROM evidence_items e WHERE e.id=%s AND e.org_id=%s AND {prior_scope}",
                [prior["vault_evidence_id"], org_id, *prior_params],
            ).fetchone() is None:
                raise LookupError("GRID file not found")
            return prior["vault_evidence_id"]
        path = row["file_path"] or ""
        if path.startswith("vault://"):
            raise ValueError("This file already points to the Vault")
        content, info = _checked_grid_source(path, row["original_name"], row["mime_type"])
        # Previous best-effort GRID syncs may have made the Vault copy already.
        marker = f"grid_evidence_id={source_id},"
        candidate_scope, candidate_params = evidence_scope_sql(user)
        candidates = db.execute(
            "SELECT e.id, e.file_hash, e.file_path FROM evidence_items e "
            f"WHERE e.org_id=%s AND e.tags LIKE %s AND {candidate_scope} "
            "AND COALESCE(e.business_unit_id,-1)=COALESCE(%s,-1) "
            "AND e.status NOT IN ('archived','superseded') ORDER BY e.id DESC",
            [org_id, f"%{marker}%", *candidate_params, row["business_unit_id"]],
        ).fetchall()
        vault_root = Path(os.getenv("EVIDENCE_DIR", "data/evidence")).resolve()
        existing = None
        for candidate in candidates:
            candidate_path = (vault_root / candidate["file_path"]).resolve() if candidate["file_path"] else None
            if (candidate["file_hash"] == info["file_hash"] and candidate_path
                    and candidate_path.is_relative_to(vault_root) and candidate_path.is_file()
                    and candidate_path.stat().st_size == len(content)
                    and hashlib.sha256(candidate_path.read_bytes()).hexdigest() == info["file_hash"]):
                existing = candidate
                break
        if existing:
            vault_id = existing["id"]
        else:
            name, stored_path = storage.write(content, info["extension"])
            vault_id = insert_returning_id(db,
                "INSERT INTO evidence_items "
                "(title,description,file_path,file_name,file_size,file_hash,mime_type,"
                "category,tags,status,uploaded_by,org_id,business_unit_id,owner_user_id,version) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (info["original_name"], "Historical GRID control evidence", name,
                 info["original_name"], info["file_size"], info["file_hash"],
                 info["mime_type"], "general", f"grid,legacy,{marker}", "current",
                 user["id"], org_id, row["business_unit_id"], user["id"], row["version"] or 1))
        _link(db, vault_id, "control", row["control_id"], user["id"])
        _link(db, vault_id, "audit", row["audit_id"], user["id"])
        insert_returning_id(db,
            "INSERT INTO evidence_file_crosswalk "
            "(org_id,module,source_id,legacy_path,source_hash,vault_evidence_id,migrated_by) "
            "VALUES (%s,'grid',%s,%s,%s,%s,%s)",
            (org_id, source_id, path, info["file_hash"], vault_id, user["id"]),
        )
        changed = db.execute("UPDATE grid_evidence_files SET file_path=%s WHERE id=%s AND file_path=%s",
                             (f"vault://{vault_id}", source_id, path)).rowcount
        if changed != 1:
            raise ValueError("The GRID file changed during reconciliation; refresh and review again")
        db.commit()
        return vault_id
    except Exception:
        db.rollback()
        if stored_path is not None:
            stored_path.unlink(missing_ok=True)
        raise
    finally:
        db.close()


def migrate_grid_version(version_id: int, user: dict) -> int:
    """Copy a historical GRID version without changing its review decision."""
    org_id = _require(user, "grid.evidence.upload")
    scope, params = entity_scope_sql(("grid", "control"), user, "c")
    db = get_db()
    stored_path = None
    try:
        row = db.execute(
            "SELECT v.*, f.control_id, c.audit_id, a.business_unit_id "
            "FROM grid_evidence_versions v "
            "JOIN grid_evidence_files f ON f.id=v.evidence_id "
            "JOIN grid_controls c ON c.id=f.control_id "
            "JOIN grid_audits a ON a.id=c.audit_id "
            f"WHERE v.id=%s AND {scope}", [version_id, *params],
        ).fetchone()
        if row is None:
            raise LookupError("GRID version not found")
        prior = db.execute(
            "SELECT vault_evidence_id FROM evidence_file_crosswalk "
            "WHERE org_id=%s AND module='grid_version' AND source_id=%s",
            (org_id, version_id),
        ).fetchone()
        if prior:
            prior_scope, prior_params = evidence_scope_sql(user)
            if db.execute(
                f"SELECT 1 FROM evidence_items e WHERE e.id=%s AND e.org_id=%s AND {prior_scope}",
                [prior["vault_evidence_id"], org_id, *prior_params],
            ).fetchone() is None:
                raise LookupError("GRID version not found")
            return prior["vault_evidence_id"]
        path = row["file_path"] or ""
        if path.startswith("vault://"):
            raise ValueError("This version already points to the Vault")
        content, info = _checked_grid_source(path, row["original_name"], row["mime_type"])
        name, stored_path = storage.write(content, info["extension"])
        vault_id = insert_returning_id(
            db, "INSERT INTO evidence_items "
            "(title,description,file_path,file_name,file_size,file_hash,mime_type,"
            "category,tags,status,uploaded_by,org_id,business_unit_id,owner_user_id,version) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (info["original_name"], "Historical GRID evidence version", name,
             info["original_name"], info["file_size"], info["file_hash"],
             info["mime_type"], "general", f"grid,legacy_version={version_id}",
             "superseded", user["id"], org_id, row["business_unit_id"],
             user["id"], row["version"] or 1),
        )
        # Version history is retained in GRID. The crosswalk is the pointer to
        # its immutable Vault bytes; historical approval remains untouched.
        insert_returning_id(
            db, "INSERT INTO evidence_file_crosswalk "
            "(org_id,module,source_id,legacy_path,source_hash,vault_evidence_id,migrated_by) "
            "VALUES (%s,'grid_version',%s,%s,%s,%s,%s)",
            (org_id, version_id, path, info["file_hash"], vault_id, user["id"]),
        )
        changed = db.execute("UPDATE grid_evidence_versions SET file_path=%s WHERE id=%s AND file_path=%s",
                             (f"vault://{vault_id}", version_id, path)).rowcount
        if changed != 1:
            raise ValueError("The GRID version changed during reconciliation; refresh and review again")
        db.commit()
        stored_path = None
        return vault_id
    except Exception:
        db.rollback()
        if stored_path is not None:
            stored_path.unlink(missing_ok=True)
        raise
    finally:
        db.close()


def bcm_inventory(user: dict) -> list[dict]:
    _require(user, "module.bcm.access")
    db = get_db()
    try:
        rows = db.execute(
            "SELECT b.id, b.control_id, b.title, b.file_path, x.vault_evidence_id "
            "FROM bcm_compliance_evidence b LEFT JOIN evidence_file_crosswalk x "
            "ON x.module='bcm' AND x.source_id=b.id AND x.org_id=%s "
            "WHERE b.deleted_at IS NULL ORDER BY b.id", (user["org_id"],)
        ).fetchall()
        return [{"id": row["id"], "control_id": row["control_id"], "title": row["title"],
                 "state": "vault" if (row["file_path"] or "").startswith("vault://")
                 else "manual_review", "vault_evidence_id": row["vault_evidence_id"]} for row in rows]
    finally:
        db.close()


def reconcile_bcm_file(source_id: int, vault_id: int, user: dict) -> int:
    """Human-reviewed BCM crosswalk; never resolves or reads a client path."""
    org_id = _require(user, "bcm.compliance.manage")
    scope, params = evidence_scope_sql(user)
    db = get_db()
    try:
        row = db.execute(
            "SELECT id, control_id, file_path FROM bcm_compliance_evidence "
            "WHERE id=%s AND deleted_at IS NULL", (source_id,),
        ).fetchone()
        vault = db.execute(
            f"SELECT e.id, e.file_hash, e.file_path, e.file_size FROM evidence_items e "
            f"WHERE e.id=%s AND e.org_id=%s AND e.status='current' "
            f"AND e.file_path IS NOT NULL AND e.file_hash IS NOT NULL AND {scope}",
            [vault_id, org_id, *params],
        ).fetchone()
        if row is None or vault is None:
            raise LookupError("BCM reference or Vault item not found")
        vault_root = Path(os.getenv("EVIDENCE_DIR", "data/evidence")).resolve()
        vault_path = (vault_root / vault["file_path"]).resolve()
        if (not vault_path.is_relative_to(vault_root) or not vault_path.is_file()
                or vault_path.stat().st_size != vault["file_size"]
                or hashlib.sha256(vault_path.read_bytes()).hexdigest() != vault["file_hash"]):
            raise ValueError("The selected Vault file is missing or differs from its recorded hash")
        path = row["file_path"] or ""
        if path.startswith("vault://"):
            if path == f"vault://{vault_id}":
                return vault_id
            raise ValueError("This BCM reference already points to a different Vault item")
        prior = db.execute(
            "SELECT vault_evidence_id FROM evidence_file_crosswalk "
            "WHERE org_id=%s AND module='bcm' AND source_id=%s", (org_id, source_id),
        ).fetchone()
        if prior:
            if prior["vault_evidence_id"] == vault_id:
                return vault_id
            raise ValueError("This BCM reference was already reconciled")
        insert_returning_id(db,
            "INSERT INTO evidence_file_crosswalk "
            "(org_id,module,source_id,legacy_path,source_hash,vault_evidence_id,migrated_by) "
            "VALUES (%s,'bcm',%s,%s,%s,%s,%s)",
            (org_id, source_id, path, vault["file_hash"], vault_id, user["id"]),
        )
        changed = db.execute("UPDATE bcm_compliance_evidence SET file_path=%s WHERE id=%s AND file_path=%s",
                             (f"vault://{vault_id}", source_id, path)).rowcount
        if changed != 1:
            raise ValueError("The BCM reference changed during reconciliation; refresh and review again")
        linked = db.execute(
            "SELECT id FROM evidence_links WHERE evidence_id=%s AND module='bcm' "
            "AND entity_type='compliance_control' AND entity_id=%s AND deleted_at IS NULL",
            (vault_id, row["control_id"]),
        ).fetchone()
        if linked is None:
            db.execute(
                "INSERT INTO evidence_links (evidence_id,module,entity_type,entity_id,linked_by) "
                "VALUES (%s,'bcm','compliance_control',%s,%s)",
                (vault_id, row["control_id"], user["id"]),
            )
        db.commit()
        return vault_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
