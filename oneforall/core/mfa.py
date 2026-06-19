"""
Two-Factor Authentication helpers (TOTP, RFC 6238).

Wraps pyotp for code verification, qrcode for enrollment images, and the
user_mfa table for persistent state. The TOTP secret is stored verbatim;
backup codes are stored as bcrypt hashes (single-use, hash matches mark
the row consumed).
"""
from __future__ import annotations

import base64
import io
import json
import secrets
from typing import Optional

import bcrypt
import pyotp
import qrcode

from core.timeutils import utcnow
from database import get_db, insert_returning_id

ISSUER = "ThemisIQ"
_BACKUP_CODE_COUNT = 8
_BACKUP_CODE_LEN = 10  # length of plaintext code shown once at enrollment


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
            "SELECT id, totp_secret, backup_codes, is_enabled, enrolled_at "
            "FROM user_mfa WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def is_enabled(user_id: int) -> bool:
    row = get_mfa_row(user_id)
    return bool(row and row.get("is_enabled"))


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
                "is_enabled = 0, enrolled_at = NULL WHERE id = %s",
                (secret, hashed, existing["id"]),
            )
        else:
            insert_returning_id(
                db,
                "INSERT INTO user_mfa (user_id, totp_secret, backup_codes) "
                "VALUES (%s, %s, %s)",
                (user_id, secret, hashed),
            )
        db.commit()
        return secret, plaintext_codes
    finally:
        db.close()


def confirm_enrollment(user_id: int, code: str) -> bool:
    """Verify the user's first code and flip is_enabled = 1.

    Returns True on success.
    """
    row = get_mfa_row(user_id)
    if not row:
        return False
    if not pyotp.TOTP(row["totp_secret"]).verify(code, valid_window=1):
        return False
    db = get_db()
    try:
        db.execute(
            "UPDATE user_mfa SET is_enabled = 1, enrolled_at = %s WHERE id = %s",
            (utcnow().isoformat(sep=" ")[:19], row["id"]),
        )
        db.commit()
        return True
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
        if pyotp.TOTP(row["totp_secret"]).verify(code, valid_window=1):
            db = get_db()
            try:
                db.execute(
                    "UPDATE user_mfa SET last_used_at = %s WHERE id = %s",
                    (utcnow().isoformat(sep=" ")[:19], row["id"]),
                )
                db.commit()
            finally:
                db.close()
            return True
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
                    db.execute(
                        "UPDATE user_mfa SET backup_codes = %s, last_used_at = %s "
                        "WHERE id = %s",
                        (json.dumps(remaining),
                         utcnow().isoformat(sep=" ")[:19],
                         row["id"]),
                    )
                    db.commit()
                finally:
                    db.close()
                return True
        except Exception:
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
