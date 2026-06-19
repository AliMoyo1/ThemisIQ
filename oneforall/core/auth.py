"""
One For All — authentication & session management.

- bcrypt for password hashing (cost 12)
- Cryptographically random session tokens stored as SHA-256 hashes in DB
- httponly, samesite=strict cookies
"""
import hashlib
import secrets
from datetime import datetime, timedelta
from core.timeutils import utcnow, to_dt
from typing import Optional

import bcrypt

from database import get_db
from config import settings


# ── Password hashing ─────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── Session token hashing ───────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    """SHA-256 hash of a session token for DB storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── Session management ───────────────────────────────────────────────────────

def create_session(user_id: int, ip: str = "", user_agent: str = "",
                    mfa_pending: bool = False) -> str:
    """Create a session and return the raw token (only the hash is stored).

    When mfa_pending=True the session can only reach /mfa/verify and /logout;
    require_auth/require_capability redirect it elsewhere.
    """
    token = secrets.token_urlsafe(48)
    token_hash = _hash_token(token)
    # MFA-pending sessions have a 10-minute TTL so they can't linger after a
    # half-finished login. Promoted sessions get the full TTL on confirmation.
    ttl = 600 if mfa_pending else settings.SESSION_MAX_AGE
    expires = (utcnow() + timedelta(seconds=ttl)).isoformat()
    db = get_db()
    try:
        db.execute(
            "INSERT INTO sessions (token, user_id, ip_address, user_agent, "
            "expires_at, mfa_pending) VALUES (%s, %s, %s, %s, %s, %s)",
            (token_hash, user_id, ip, user_agent[:500] if user_agent else "",
             expires, 1 if mfa_pending else 0),
        )
        if not mfa_pending:
            db.execute(
                "UPDATE users SET last_login = %s WHERE id = %s",
                (utcnow().isoformat(), user_id),
            )
        db.commit()
    finally:
        db.close()
    return token


def promote_mfa_session(token: str) -> bool:
    """Mark an mfa_pending session as fully authenticated and extend its TTL."""
    token_hash = _hash_token(token)
    expires = (utcnow() + timedelta(seconds=settings.SESSION_MAX_AGE)).isoformat()
    db = get_db()
    try:
        row = db.execute(
            "SELECT id, user_id FROM sessions WHERE token = %s",
            (token_hash,),
        ).fetchone()
        if not row:
            return False
        db.execute(
            "UPDATE sessions SET mfa_pending = 0, expires_at = %s WHERE id = %s",
            (expires, row["id"]),
        )
        db.execute(
            "UPDATE users SET last_login = %s WHERE id = %s",
            (utcnow().isoformat(), row["user_id"]),
        )
        db.commit()
        return True
    finally:
        db.close()


def get_session_user(token: str) -> Optional[dict]:
    """Look up a session token and return the user dict (with roles), or None."""
    if not token:
        return None
    token_hash = _hash_token(token)
    db = get_db()
    try:
        row = db.execute(
            "SELECT s.user_id, s.expires_at, "
            "COALESCE(s.mfa_pending, 0) AS mfa_pending "
            "FROM sessions s WHERE s.token = %s",
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        if to_dt(row["expires_at"]) < utcnow():
            db.execute("DELETE FROM sessions WHERE token = %s", (token_hash,))
            db.commit()
            return None

        user = db.execute(
            "SELECT u.id, u.username, u.email, u.full_name, u.is_active, "
            "u.must_change_password, u.avatar_initials, u.org_id, "
            "COALESCE(u.is_super_admin, 0) AS is_super_admin "
            "FROM users u WHERE u.id = %s",
            (row["user_id"],),
        ).fetchone()
        if not user or not user["is_active"]:
            return None

        roles = [
            r["role_key"]
            for r in db.execute(
                "SELECT role_key FROM user_roles WHERE user_id = %s",
                (user["id"],),
            ).fetchall()
        ]

        # Resolve the org slug so middleware can set the correct search_path.
        org_slug = "public"
        org_name = "Default"
        licensed_modules = None
        if user["org_id"]:
            org_row = db.execute(
                "SELECT slug, name FROM organizations WHERE id = %s",
                (user["org_id"],),
            ).fetchone()
            if org_row:
                org_slug = org_row["slug"]
                org_name = org_row["name"]
            lic_row = db.execute(
                "SELECT module_keys, valid_until FROM licenses WHERE org_id = %s "
                "ORDER BY id DESC LIMIT 1",
                (user["org_id"],),
            ).fetchone()
            if lic_row and lic_row["module_keys"]:
                if lic_row["valid_until"] and lic_row["valid_until"] < utcnow().isoformat():
                    licensed_modules = []  # licence expired: revoke module access
                else:
                    licensed_modules = [
                        m.strip() for m in lic_row["module_keys"].split(",") if m.strip()
                    ]

        return {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "full_name": user["full_name"],
            "avatar_initials": user["avatar_initials"] or _initials(user["full_name"]),
            "must_change_password": bool(user["must_change_password"]),
            "roles": roles,
            "org_id": user["org_id"],
            "org_slug": org_slug,
            "org_name": org_name,
            "is_super_admin": bool(user["is_super_admin"]),
            "licensed_modules": licensed_modules,
            "mfa_pending": bool(row.get("mfa_pending")),
        }
    finally:
        db.close()


def destroy_session(token: str):
    """Delete a session by its raw token."""
    if not token:
        return
    token_hash = _hash_token(token)
    db = get_db()
    try:
        db.execute("DELETE FROM sessions WHERE token = %s", (token_hash,))
        db.commit()
    finally:
        db.close()


def cleanup_expired_sessions():
    """Remove expired sessions from the DB."""
    db = get_db()
    try:
        db.execute("DELETE FROM sessions WHERE expires_at < %s", (utcnow().isoformat(),))
        db.commit()
    finally:
        db.close()


# ── User lookup ──────────────────────────────────────────────────────────────

def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Verify credentials and return user dict if valid."""
    db = get_db()
    try:
        user = db.execute(
            "SELECT id, username, email, full_name, password_hash, is_active, "
            "must_change_password, avatar_initials FROM users WHERE username = %s",
            (username,),
        ).fetchone()
        if not user:
            # Constant-time comparison to prevent timing attacks
            bcrypt.checkpw(b"dummy", bcrypt.gensalt())
            return None
        if not user["is_active"]:
            return None
        if not verify_password(password, user["password_hash"]):
            return None

        roles = [
            r["role_key"]
            for r in db.execute(
                "SELECT role_key FROM user_roles WHERE user_id = %s",
                (user["id"],),
            ).fetchall()
        ]

        return {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "full_name": user["full_name"],
            "avatar_initials": user["avatar_initials"] or _initials(user["full_name"]),
            "must_change_password": bool(user["must_change_password"]),
            "roles": roles,
        }
    finally:
        db.close()


def _initials(name: str) -> str:
    parts = name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper() if name else "??"
