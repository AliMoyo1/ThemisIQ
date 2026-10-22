"""Re-encrypt shared MFA secrets after configuring MFA_ENCRYPTION_KEY.

Dry-run by default. Run --apply after a verified database backup. This never
prints a secret, ciphertext, user ID, or encryption key.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.fernet import InvalidToken

from core.mfa import _decrypt_secret, _encrypt_secret, _fernet_keys, _ENCRYPTED_PREFIX, encryption_ready
from database import get_db_background


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Encrypt stored MFA authenticator secrets")
    parser.add_argument("--apply", action="store_true", help="write encrypted secrets")
    args = parser.parse_args(argv)
    if not encryption_ready():
        print("MFA_ENCRYPTION_KEY is not configured", file=sys.stderr)
        return 2

    db = get_db_background()
    try:
        rows = db.execute("SELECT id, totp_secret FROM user_mfa").fetchall()
        legacy = sum(not row["totp_secret"].startswith(_ENCRYPTED_PREFIX) for row in rows)
        current_key = _fernet_keys()[0]
        previous_key_rows = 0
        needs_rotation = []
        # Validate all existing encrypted rows before any update. A missing
        # previous key must fail the run without a partial rotation.
        for row in rows:
            stored = row["totp_secret"]
            _decrypt_secret(stored)
            if stored.startswith(_ENCRYPTED_PREFIX):
                try:
                    current_key.decrypt(stored[len(_ENCRYPTED_PREFIX):].encode("ascii"))
                except InvalidToken:
                    previous_key_rows += 1
                    needs_rotation.append(row)
            else:
                needs_rotation.append(row)
        if args.apply:
            for row in needs_rotation:
                encrypted = _encrypt_secret(_decrypt_secret(row["totp_secret"]))
                updated = db.execute(
                    "UPDATE user_mfa SET totp_secret=%s WHERE id=%s AND totp_secret=%s",
                    (encrypted, row["id"], row["totp_secret"]),
                ).rowcount
                if updated != 1:
                    raise RuntimeError("MFA row changed during encryption; no changes committed")
            db.commit()
        print(f"mfa_rows={len(rows)} legacy_plaintext={legacy} "
              f"previous_key_rows={previous_key_rows} changed={len(needs_rotation) if args.apply else 0} "
              f"applied={str(args.apply).lower()}")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"MFA encryption failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
