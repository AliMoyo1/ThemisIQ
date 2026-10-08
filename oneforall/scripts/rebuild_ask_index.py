"""
Rebuild the Ask ARIA search index for every organization in one pass.

The index carries org_id and business_unit_id on every chunk. Run this once
after deploying that change: it stamps controls and risks with the tenant that
owns them, and drops any stray rows an earlier policy publication wrote into
the shared public table. It is the same work as the admin "Rebuild index"
button, for all tenants instead of one login per tenant.

Usage:
    python scripts/rebuild_ask_index.py
        Rebuild the index of every active organization.

    python scripts/rebuild_ask_index.py --slug SLUG
        Rebuild one organization only ("public" is the default organization).

Only derived data (aria_ask_index) is written; documents, controls and risks
are read. An organization's Ask ARIA results are incomplete while its own
rebuild runs, which takes seconds. Needs the application's environment (the
same DATABASE_URL the service uses). Exit status: 0 everything rebuilt, 1 a
rebuild failed, 2 --slug matched no active organization.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from database import list_active_tenants, tenant_context  # noqa: E402
from modules.aria.ask_service import rebuild_all  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild the Ask ARIA search index.")
    parser.add_argument("--slug", help='rebuild only this organization ("public" is the default one)')
    args = parser.parse_args(argv)

    if not settings.is_postgres():
        if args.slug:
            parser.error("--slug needs PostgreSQL; SQLite has a single index for the whole database")
        print(f"all: {rebuild_all()} chunks")
        return 0

    tenants = [t for t in list_active_tenants() if args.slug in (None, t[1])]
    if not tenants:
        print(f"no active organization matches {args.slug!r}", file=sys.stderr)
        return 2
    failed = 0
    for org_id, slug in tenants:
        try:
            with tenant_context(org_id, slug):
                print(f"{slug}: {rebuild_all()} chunks")
        except Exception as exc:
            failed += 1
            print(f"{slug}: FAILED: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
