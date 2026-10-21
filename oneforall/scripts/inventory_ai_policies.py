"""Read-only AI policy readiness inventory across active organizations.

Prints policy state and caps, never policy JSON, prompts, secrets or records.
This inventory does not approve or enable a policy.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ai_policy import get_policy
from database import get_db_background, list_active_tenants, tenant_context


def main() -> int:
    print("org_id|state|org_monthly_cap|user_monthly_cap|saved_by")
    for org_id, slug in list_active_tenants():
        with tenant_context(org_id, slug, is_super_admin=False):
            try:
                policy = get_policy(org_id)
                db = get_db_background()
                try:
                    row = db.execute("SELECT value FROM settings WHERE key=%s",
                                     (f"ai.policy.org{org_id}",)).fetchone()
                finally:
                    db.close()
                raw = json.loads(row["value"]) if row and row["value"] else {}
            except Exception:
                print(f"{org_id}|unreadable|||")
                continue
        if policy is None:
            print(f"{org_id}|missing|||")
            continue
        state = ("enabled" if policy["enabled"] else
                 "review_required" if raw.get("enabled") is True else "disabled")
        print(f"{org_id}|{state}|{policy.get('monthly_token_budget') or ''}|"
              f"{policy.get('monthly_user_token_budget') or ''}|{raw.get('updated_by') or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
