"""Read-only release inventory of public API key metadata.

Run with the app's private environment loaded. Never prints full keys,
password hashes, or key hashes. Works before the business-unit migration.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_db_background


def main() -> int:
    db = get_db_background()
    try:
        rows = db.execute(
            "SELECT id, org_id, scopes, is_active, expires_at, last_used_at "
            "FROM api_keys ORDER BY org_id, id"
        ).fetchall()
    finally:
        db.close()
    print("key_id|org_id|active|legacy_scope|scopes|has_expiry|last_used")
    for row in rows:
        scopes = {value.strip() for value in (row["scopes"] or "").split(",")}
        legacy = bool(scopes & {"read", "write"})
        print(f"{row['id']}|{row['org_id']}|{int(bool(row['is_active']))}|"
              f"{int(legacy)}|{','.join(sorted(scopes))}|{int(bool(row['expires_at']))}|"
              f"{str(row['last_used_at'] or '')[:10]}")
    print(f"key_count={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
