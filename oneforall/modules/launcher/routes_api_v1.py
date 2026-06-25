"""
ThemisIQ public REST API v1.

Authentication: X-API-Key header (PBKDF2-SHA256, checked against api_keys table).
All endpoints are read-only and require scope 'read'.
Docs available at /docs (FastAPI OpenAPI UI).
"""
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from database import get_db, set_current_tenant

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["REST API v1"])

_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50

_KEY_SALT = os.environ.get("SECRET_KEY", "fallback-hmac-key").encode()


def _hash_key(raw: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", raw.encode(), _KEY_SALT, 100_000).hex()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_read_scope(scopes_str: str) -> bool:
    return "read" in {s.strip() for s in (scopes_str or "").split(",")}


async def _require_read_key(x_api_key: str = Header(None, alias="X-API-Key")):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")
    key_hash = _hash_key(x_api_key)
    db = get_db()
    try:
        row = db.execute(
            "SELECT ak.id, ak.scopes, ak.expires_at, ak.org_id, o.slug AS org_slug"
            " FROM api_keys ak LEFT JOIN organizations o ON o.id = ak.org_id"
            " WHERE ak.key_hash=%s AND ak.is_active=1",
            (key_hash,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid or inactive API key")
        if row["expires_at"] and row["expires_at"] < _now_iso():
            raise HTTPException(status_code=401, detail="API key expired")
        if not _has_read_scope(row["scopes"]):
            raise HTTPException(status_code=403, detail="API key does not have read scope")
        try:
            db.execute(
                "UPDATE api_keys SET last_used_at=%s WHERE id=%s",
                (_now_iso(), row["id"]),
            )
            db.commit()
        except Exception as exc:
            log.warning("[api-v1] last_used_at update failed: %s", exc)
        # Set tenant context so subsequent get_db() calls use the right schema.
        slug = row["org_slug"] or "public"
        set_current_tenant(slug)
        return dict(row)
    finally:
        db.close()


@router.get("/risks", summary="List risks")
async def list_risks(
    status: Optional[str] = Query(None, description="Filter by status (open, closed, accepted, mitigated)"),
    category: Optional[str] = Query(None, description="Filter by category (operational, strategic, financial, ...)"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description="Max records to return (default 50, max 200)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    _key=Depends(_require_read_key),
):
    """Return risks from the cross-module risk register."""
    where_parts: list[str] = []
    params: list = []
    if status:
        where_parts.append("status=%s")
        params.append(status)
    if category:
        where_parts.append("category=%s")
        params.append(category)
    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    db = get_db()
    try:
        total = db.execute(
            f"SELECT COUNT(*) FROM risk_register {where_clause}", tuple(params)
        ).fetchone()[0]
        rows = db.execute(
            f"SELECT id, title, description, source_module, category,"
            f" likelihood, impact, risk_score, risk_level,"
            f" status, treatment, review_date, created_at, updated_at"
            f" FROM risk_register {where_clause}"
            f" ORDER BY created_at DESC LIMIT %s OFFSET %s",
            tuple(params + [limit, offset]),
        ).fetchall()
    finally:
        db.close()

    return {"data": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/audits", summary="List audits")
async def list_audits(
    status: Optional[str] = Query(None, description="Filter by status (Planning, In Progress, Completed, Closed)"),
    audit_type: Optional[str] = Query(None, description="Filter by type (Internal, External)"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description="Max records to return (default 50, max 200)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    _key=Depends(_require_read_key),
):
    """Return audits from GRID."""
    where_parts: list[str] = []
    params: list = []
    if status:
        where_parts.append("status=%s")
        params.append(status)
    if audit_type:
        where_parts.append("audit_type=%s")
        params.append(audit_type)
    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    db = get_db()
    try:
        total = db.execute(
            f"SELECT COUNT(*) FROM grid_audits {where_clause}", tuple(params)
        ).fetchone()[0]
        rows = db.execute(
            f"SELECT id, name, framework_id, audit_type, auditor,"
            f" start_date, end_date, status, scope, objective, conclusion, created_at"
            f" FROM grid_audits {where_clause}"
            f" ORDER BY created_at DESC LIMIT %s OFFSET %s",
            tuple(params + [limit, offset]),
        ).fetchall()
    finally:
        db.close()

    return {"data": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/breaches", summary="List data breaches")
async def list_breaches(
    status: Optional[str] = Query(None, description="Filter by status (open, investigating, closed, reported)"),
    severity: Optional[str] = Query(None, description="Filter by severity (low, medium, high, critical)"),
    regulation: Optional[str] = Query(None, description="Filter by regulation (GDPR, HIPAA, PCI DSS, ...)"),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description="Max records to return (default 50, max 200)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    _key=Depends(_require_read_key),
):
    """Return data breach records from Sentinel."""
    where_parts: list[str] = []
    params: list = []
    if status:
        where_parts.append("status=%s")
        params.append(status)
    if severity:
        where_parts.append("severity=%s")
        params.append(severity)
    if regulation:
        where_parts.append("regulation=%s")
        params.append(regulation)
    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    db = get_db()
    try:
        total = db.execute(
            f"SELECT COUNT(*) FROM sentinel_breaches {where_clause}", tuple(params)
        ).fetchone()[0]
        rows = db.execute(
            f"SELECT id, ref_number, title, description, severity, status,"
            f" affected_count, regulation, discovered_date, reported_date,"
            f" notification_required, authority_notified, subjects_notified,"
            f" created_at, updated_at"
            f" FROM sentinel_breaches {where_clause}"
            f" ORDER BY created_at DESC LIMIT %s OFFSET %s",
            tuple(params + [limit, offset]),
        ).fetchall()
    finally:
        db.close()

    return {"data": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}
