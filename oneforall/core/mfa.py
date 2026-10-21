"""
Two-Factor Authentication helpers (TOTP, RFC 6238).

Wraps pyotp for code verification, qrcode for enrollment images, and the
user_mfa table for persistent state. TOTP secrets are encrypted with a
separately managed key; backup codes are stored as bcrypt hashes (single-use, hash matches mark
the row consumed).
"""
from __future__ import annotations

import base64
import io
import json
import os
import secrets
import time
from typing import Optional

import bcrypt
import pyotp
import qrcode
from cryptography.fernet import Fernet, InvalidToken

from core.timeutils import utcnow
from database import get_db, insert_returning_id
from core.best_effort import swallowed

ISSUER = "ThemisIQ"
_BACKUP_CODE_COUNT = 8
_BACKUP_CODE_LEN = 10  # length of plaintext code shown once at enrollment
_ENCRYPTED_PREFIX = "fernet:v1:"


def _fernet_keys() -> list[Fernet]:
    """Current key first; previous keys are accepted only for migration/rotation."""
    raw = [os.getenv("MFA_ENCRYPTION_KEY", "").strip()]
    raw.extend(k.strip() for k in os.getenv("MFA_ENCRYPTION_PREVIOUS_KEYS", "").split(",") if k.strip())
    keys = []
    for key in raw:
        if key:
            try:
                keys.append(Fernet(key.encode("ascii")))
            except (ValueError, TypeError, UnicodeEncodeError) as exc:
                raise RuntimeError("Invalid MFA encryption key configuration") from exc
    return keys


def _encrypt_secret(secret: str) -> str:
    keys = _fernet_keys()
    if not os.getenv("MFA_ENCRYPTION_KEY", "").strip() or not keys:
        raise RuntimeError("MFA_ENCRYPTION_KEY is required for enrollment")
    return _ENCRYPTED_PREFIX + keys[0].encrypt(secret.encode("ascii")).decode("ascii")


def encryption_ready() -> bool:
    """Whether new MFA enrollments can be stored encrypted."""
    return bool(os.getenv("MFA_ENCRYPTION_KEY", "").strip() and _fernet_keys())


def _decrypt_secret(stored: str) -> str:
    if not stored.startswith(_ENCRYPTED_PREFIX):
        return stored  # legacy row until the one-time migration runs
    token = stored[len(_ENCRYPTED_PREFIX):].encode("ascii")
    for key in _fernet_keys():
        try:
            return key.decrypt(token).decode("ascii")
        except InvalidToken:
            continue
    raise RuntimeError("MFA secret cannot be decrypted with the configured keys")


def _generate_secret() -> str:
    """Return a base32-encoded TOTP secret compatible with authenticator apps."""
    return pyotp.random_base32()


def _generate_backup_codes() -> list[str]:
    """Return a list of single-use backup codes (plaintext)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
    return [
        "".join(secrets.choice(alphabet) for _ in range(_BACKUP_CODE_LEN))
        for _ in range(_BACKUP_CODE_COUNT)
    ]


def _hash_codes(codes: list[str]) -> list[str]:
    return [
        bcrypt.hashpw(c.encode(), bcrypt.gensalt(rounds=10)).decode()
        for c in codes
    ]


def _provisioning_uri(username: str, secret: str) -> str:
    """Build an otpauth:// URI that QR-encodes into authenticator apps."""
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=username, issuer_name=ISSUER
    )


def qr_png_data_uri(username: str, secret: str) -> str:
    """Return a data: URI containing a PNG QR code for enrollment."""
    img = qrcode.make(_provisioning_uri(username, secret))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# ── DB helpers ──────────────────────────────────────────────────────────────

def get_mfa_row(user_id: int) -> Optional[dict]:
    db = get_db()
    try:
        row = db.execute(
            "SELECT id, totp_secret, backup_codes, is_enabled, enrolled_at, last_accepted_step "
            "FROM user_mfa WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["_stored_secret"] = result["totp_secret"]
        result["totp_secret"] = _decrypt_secret(result["totp_secret"])
        return result
    finally:
        db.close()


def is_enabled(user_id: int) -> bool:
    row = get_mfa_row(user_id)
    return bool(row and row.get("is_enabled"))


# Admin-role keys that org MFA policy "admins" applies to. Mirrors the
# privileged tiers a GRC buyer's auditors expect to be MFA-gated.
_ADMIN_ROLE_KEYS = (
    "super_admin", "compliance_manager", "audit_lead", "dpo",
    "security_manager", "bcm_manager", "erm_manager", "aria_manager",
)


def mfa_required_for(user: dict, policy: str) -> bool:
    """Pure policy check: does the org MFA policy require this user to have MFA?

    policy values (from settings.security.require_mfa):
      "off"    -> never required
      "admins" -> required only for admin/manager-tier roles
      "all"    -> required for every user
    Any unknown/empty value fails open to "off" (never lock out login).
    """
    if not user:
        return False
    policy = (policy or "off").strip().lower()
    if policy == "all":
        return True
    if policy == "admins":
        from core.rbac import has_role
        return has_role(user, *_ADMIN_ROLE_KEYS)
    # "off" or anything unexpected -> fail open, never block login
    return False


def start_enrollment(user_id: int) -> tuple[str, list[str]]:
    """Create or replace a pending (not-yet-enabled) MFA row.

    Returns (totp_secret, backup_codes_plaintext). Backup codes are hashed
    before storage; the plaintext is shown once and never re-derivable.
    """
    secret = _generate_secret()
    plaintext_codes = _generate_backup_codes()
    hashed = json.dumps(_hash_codes(plaintext_codes))
    db = get_db()
    try:
        existing = db.execute(
            "SELECT id FROM user_mfa WHERE user_id = %s", (user_id,)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE user_mfa SET totp_secret = %s, backup_codes = %s, "
                "is_enabled = 0, enrolled_at = NULL, last_accepted_step = NULL WHERE id = %s",
                (_encrypt_secret(secret), hashed, existing["id"]),
            )
        else:
            insert_returning_id(
                db,
                "INSERT INTO user_mfa (user_id, totp_secret, backup_codes) "
                "VALUES (%s, %s, %s)",
                (user_id, _encrypt_secret(secret), hashed),
            )
        db.commit()
        return secret, plaintext_codes
    finally:
        db.close()


def _matching_step(secret: str, code: str) -> int | None:
    """Return the exact accepted TOTP step within the one-step clock window."""
    code = (code or "").strip().replace(" ", "")
    if not (code.isascii() and code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret)
    current = int(time.time() // totp.interval)
    for step in (current - 1, current, current + 1):
        if step >= 0 and secrets.compare_digest(totp.at(step * totp.interval), code):
            return step
    return None


def confirm_enrollment(user_id: int, code: str) -> bool:
    """Verify the user's first code and flip is_enabled = 1.

    Returns True on success.
    """
    row = get_mfa_row(user_id)
    if not row:
        return False
    step = _matching_step(row["totp_secret"], code)
    if step is None:
        return False
    db = get_db()
    try:
        updated = db.execute(
            "UPDATE user_mfa SET is_enabled = 1, enrolled_at = %s, last_accepted_step = %s "
            "WHERE id = %s AND is_enabled = 0 AND totp_secret = %s",
            (utcnow().isoformat(sep=" ")[:19], step, row["id"], row["_stored_secret"]),
        ).rowcount
        db.commit()
        return updated == 1
    finally:
        db.close()


def verify_code(user_id: int, code: str) -> bool:
    """Verify a TOTP code or a single-use backup code.

    Backup code matches are consumed (hash removed from the list).
    """
    row = get_mfa_row(user_id)
    if not row or not row.get("is_enabled"):
        return False
    code = (code or "").strip().replace(" ", "")

    # TOTP first (fast path)
    if code.isdigit() and len(code) == 6:
        step = _matching_step(row["totp_secret"], code)
        if step is not None:
            db = get_db()
            try:
                accepted = db.execute(
                    "UPDATE user_mfa SET last_used_at = %s, last_accepted_step = %s "
                    "WHERE id = %s AND is_enabled = 1 "
                    "AND (last_accepted_step IS NULL OR last_accepted_step < %s)",
                    (utcnow().isoformat(sep=" ")[:19], step, row["id"], step),
                ).rowcount
                db.commit()
            finally:
                db.close()
            return accepted == 1
        return False

    # Backup code path
    try:
        hashed_list = json.loads(row["backup_codes"]) or []
    except Exception:
        hashed_list = []
    for h in hashed_list:
        try:
            if bcrypt.checkpw(code.upper().encode(), h.encode()):
                remaining = [x for x in hashed_list if x != h]
                db = get_db()
                try:
                    # Compare and set: the write only counts if the list is still the one we read.
                    # Otherwise another request changed it meanwhile, most likely by spending this
                    # very code, and this one must not succeed as well.
                    spent = db.execute(
                        "UPDATE user_mfa SET backup_codes = %s, last_used_at = %s "
                        "WHERE id = %s AND backup_codes = %s",
                        (json.dumps(remaining),
                         utcnow().isoformat(sep=" ")[:19],
                         row["id"], row["backup_codes"]),
                    ).rowcount
                    db.commit()
                finally:
                    db.close()
                return spent == 1
        except Exception:
            swallowed("verify_code (user_mfa)")
            continue
    return False


def disable(user_id: int) -> None:
    """Disable MFA for a user (drops the row entirely)."""
    db = get_db()
    try:
        db.execute("DELETE FROM user_mfa WHERE user_id = %s", (user_id,))
        db.commit()
    finally:
        db.close()


def regenerate_backup_codes(user_id: int) -> list[str]:
    """Issue a fresh batch of backup codes (invalidates the old set)."""
    plaintext = _generate_backup_codes()
    hashed = json.dumps(_hash_codes(plaintext))
    db = get_db()
    try:
        db.execute(
            "UPDATE user_mfa SET backup_codes = %s WHERE user_id = %s",
            (hashed, user_id),
        )
        db.commit()
    finally:
        db.close()
    return plaintext
