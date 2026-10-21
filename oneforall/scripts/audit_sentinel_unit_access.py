#!/usr/bin/env python3
"""Report aggregate Sentinel business-unit exposure in every PostgreSQL tenant.

This command has no write mode. It prints counts only, never record identifiers,
names, document contents, connection strings, or environment values.

Run from /project/oneforall as root so the production environment file can be
read: .venv/bin/python3 scripts/audit_sentinel_unit_access.py
"""

from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from deploy import DEFAULT_ENV_FILE, parse_env_file  # noqa: E402

production_env = parse_env_file(DEFAULT_ENV_FILE)
for key in ("DATABASE_URL", "PGPASSWORD_FILE", "PGPASSWORD"):
    value = production_env.get(key)
    if value:
        os.environ.setdefault(key, value)

from config import settings  # noqa: E402
from database import get_db_bypass_rls  # noqa: E402

TABLES = (
    "sentinel_ropa",
    "sentinel_dpias",
    "sentinel_breaches",
    "sentinel_dsr",
    "sentinel_consent",
    "sentinel_aiia",
)
SCHEMA_TABLES = TABLES + ("business_units",)


def _columns(db, schema: str) -> dict[str, set[str]]:
    rows = db.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name = ANY(%s)",
        (schema, list(SCHEMA_TABLES)),
    ).fetchall()
    columns: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        columns[row["table_name"]].add(row["column_name"])
    return columns


def _reachable(children: dict[int, set[int]], parent: int, descendant: int) -> bool:
    pending = [parent]
    seen = set()
    while pending:
        current = pending.pop()
        if current == descendant:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(children.get(current, ()))
    return False


def _linked_dpia_counts(db) -> dict[str, int]:
    children: dict[int, set[int]] = defaultdict(set)
    for row in db.execute("SELECT id, parent_id FROM business_units WHERE is_active=1").fetchall():
        if row["parent_id"] is not None:
            children[int(row["parent_id"])].add(int(row["id"]))

    counts = {"linked": 0, "organization_wide_to_unit": 0,
              "different_unit": 0, "wider_than_ropa": 0}
    rows = db.execute(
        "SELECT d.business_unit_id AS dpia_unit, r.business_unit_id AS ropa_unit "
        "FROM sentinel_dpias d JOIN sentinel_ropa r ON r.id=d.ropa_id"
    ).fetchall()
    for row in rows:
        counts["linked"] += 1
        dpia_unit, ropa_unit = row["dpia_unit"], row["ropa_unit"]
        if ropa_unit is None:
            continue
        if dpia_unit is None:
            counts["organization_wide_to_unit"] += 1
            counts["wider_than_ropa"] += 1
        elif dpia_unit != ropa_unit:
            counts["different_unit"] += 1
            if not _reachable(children, int(dpia_unit), int(ropa_unit)):
                counts["wider_than_ropa"] += 1
    return counts


def main() -> int:
    if not settings.is_postgres():
        print("PostgreSQL connection is required; no audit was run.", file=sys.stderr)
        return 2
    db = get_db_bypass_rls()
    try:
        db.execute("SET TRANSACTION READ ONLY")
        schemas = ["public"] + [
            row["schema_name"] for row in db.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name LIKE 'tenant_%%' ORDER BY schema_name"
            ).fetchall()
        ]
        db.rollback()
        for index, schema in enumerate(schemas, 1):
            if schema != "public" and not re.fullmatch(r"tenant_[a-z0-9_]+", schema):
                raise RuntimeError("Unexpected tenant schema name; audit stopped before querying it.")
            slug = "public" if schema == "public" else schema[len("tenant_"):]
            db.set_tenant(slug)
            db.execute("SET TRANSACTION READ ONLY")
            print(f"schema {index}/{len(schemas)}" + (" (public)" if schema == "public" else " (tenant)"))
            columns = _columns(db, schema)
            for table in TABLES:
                if "business_unit_id" not in columns.get(table, set()):
                    print(f"  {table}: unavailable (table or unit column missing)")
                    continue
                row = db.execute(
                    f"SELECT COUNT(*) AS total, "
                    f"COUNT(*) FILTER (WHERE business_unit_id IS NULL) AS organization_wide FROM {table}"
                ).fetchone()
                print(f"  {table}: total={row['total']} organization_wide={row['organization_wide']}")
            if {"ropa_id", "business_unit_id"} <= columns.get("sentinel_dpias", set()) and \
                    "business_unit_id" in columns.get("sentinel_ropa", set()) and \
                    {"id", "parent_id", "is_active"} <= columns.get("business_units", set()):
                counts = _linked_dpia_counts(db)
                print("  linked_dpias: " + " ".join(f"{key}={value}" for key, value in counts.items()))
            else:
                print("  linked_dpias: unavailable (link or unit column missing)")
            db.rollback()
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
