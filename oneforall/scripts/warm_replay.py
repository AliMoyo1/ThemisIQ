#!/usr/bin/env python3
"""
warm_replay.py — Warm replay: compare SQLite vs shadow PG on representative queries.

Unlike verify_pg_parity.py (which checks every table for row-count parity),
warm_replay.py runs business-meaningful JOIN queries — the same patterns the
app actually uses — and confirms the shadow PG returns equivalent results.

Usage:
    python scripts/warm_replay.py \\
        --sqlite data/oneforall.db \\
        --postgres postgresql://themisiq:shadow_pass@localhost:5433/themisiq_shadow

Exit codes:
    0 — All replay checks PASS.
    1 — One or more checks FAIL.
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from typing import Any


# ── Representative queries ───────────────────────────────────────────────────
# Each entry: (label, sql, params)
# SQL must be valid on BOTH SQLite and PostgreSQL (standard SQL only).
# Use %s placeholders (translated by _SqliteConnWrapper if needed).
# Keep queries simple — no SQLite-specific functions.

_QUERIES: list[tuple[str, str, tuple]] = [
    # ── Core ─────────────────────────────────────────────────────────────────
    ("users:count",
     "SELECT COUNT(*) FROM users", ()),

    # Code-review finding (2026-09-28): users has no `role` column -- roles
    # live in the separate user_roles table (role_key values), so this
    # query has never once executed successfully on either database and
    # silently reported SKIP (see the exit-code fix below for why that
    # used to still exit 0).
    ("users:active_admins",
     "SELECT COUNT(*) FROM users u JOIN user_roles ur ON ur.user_id = u.id "
     "WHERE u.is_active = 1 AND ur.role_key = 'super_admin'", ()),

    ("audit_log:recent_count",
     "SELECT COUNT(*) FROM audit_log WHERE action IS NOT NULL", ()),

    # ── ARIA ─────────────────────────────────────────────────────────────────
    ("aria:framework_count",
     "SELECT COUNT(*) FROM aria_frameworks", ()),

    ("aria:frameworks_with_controls",
     "SELECT f.id, COUNT(c.id) AS ctrl_count "
     "FROM aria_frameworks f "
     "LEFT JOIN aria_controls c ON c.framework_id = f.id "
     "GROUP BY f.id ORDER BY f.id",
     ()),

    ("aria:controls_by_status",
     "SELECT status, COUNT(*) AS n FROM aria_controls GROUP BY status ORDER BY status",
     ()),

    ("aria:document_count",
     "SELECT COUNT(*) FROM aria_documents", ()),

    ("aria:risks_by_likelihood_impact",
     "SELECT likelihood, impact, COUNT(*) AS n FROM aria_risks "
     "GROUP BY likelihood, impact ORDER BY likelihood, impact",
     ()),

    # ── GRID ─────────────────────────────────────────────────────────────────
    ("grid:audit_count",
     "SELECT COUNT(*) FROM grid_audits", ()),

    ("grid:audits_by_status",
     "SELECT status, COUNT(*) AS n FROM grid_audits GROUP BY status ORDER BY status",
     ()),

    # Code-review finding (2026-09-28): both of these referenced table
    # names that don't exist (grid_ncs, grid_evidence) and had never once
    # run successfully; grid_evidence_files is the actual uploaded-
    # evidence-file table (grid_evidence_items is the request/placeholder
    # a file attaches to, not the evidence itself).
    ("grid:nc_count",
     "SELECT COUNT(*) FROM grid_non_conformances", ()),

    ("grid:evidence_count",
     "SELECT COUNT(*) FROM grid_evidence_files", ()),

    # ── BCM ──────────────────────────────────────────────────────────────────
    ("bcm:plan_count",
     "SELECT COUNT(*) FROM bcm_plans", ()),

    ("bcm:plans_by_status",
     "SELECT status, COUNT(*) AS n FROM bcm_plans GROUP BY status ORDER BY status",
     ()),

    ("bcm:incident_count",
     "SELECT COUNT(*) FROM bcm_incidents", ()),

    # ── Sentinel ─────────────────────────────────────────────────────────────
    ("sentinel:ropa_count",
     "SELECT COUNT(*) FROM sentinel_ropa", ()),

    ("sentinel:breaches_by_severity",
     "SELECT severity, COUNT(*) AS n FROM sentinel_breaches "
     "GROUP BY severity ORDER BY severity",
     ()),

    ("sentinel:dsr_count",
     "SELECT COUNT(*) FROM sentinel_dsr", ()),

    ("sentinel:dpia_count",
     "SELECT COUNT(*) FROM sentinel_dpias", ()),

    # ── ERM ──────────────────────────────────────────────────────────────────
    ("erm:risks_by_treatment",
     "SELECT treatment, COUNT(*) AS n FROM erm_enterprise_risks GROUP BY treatment ORDER BY treatment",
     ()),

    # Code-review finding (2026-09-28): the real table is
    # erm_regulatory_obligations -- erm_obligations doesn't exist.
    ("erm:obligation_count",
     "SELECT COUNT(*) FROM erm_regulatory_obligations", ()),

    # ── ORM ──────────────────────────────────────────────────────────────────
    ("orm:events_by_type",
     "SELECT event_type, COUNT(*) AS n FROM orm_events "
     "GROUP BY event_type ORDER BY event_type",
     ()),

    ("orm:kri_count",
     "SELECT COUNT(*) FROM orm_kris", ()),

    ("orm:kri_breach_count",
     "SELECT COUNT(*) FROM orm_kris WHERE status = 'breach'", ()),

    # ── Evidence ─────────────────────────────────────────────────────────────
    ("evidence:item_count",
     "SELECT COUNT(*) FROM evidence_items", ()),

    ("evidence:items_by_status",
     "SELECT status, COUNT(*) AS n FROM evidence_items GROUP BY status ORDER BY status",
     ()),

    # ── Cross-module ─────────────────────────────────────────────────────────
    ("xlinks:link_count",
     "SELECT COUNT(*) FROM cross_module_links", ()),

    ("canonical_vendors:count",
     "SELECT COUNT(*) FROM canonical_vendors", ()),
]


def _hash_rows(rows: list[tuple]) -> str:
    """Stable hash of a result set for comparison."""
    canonical = "\n".join(str(r) for r in sorted(rows, key=lambda r: str(r)))
    return hashlib.md5(canonical.encode()).hexdigest()


def _run_sqlite(path: str, sql: str, params: tuple) -> list[tuple] | None:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as exc:
        return None


def _run_pg(url: str, sql: str, params: tuple) -> list[tuple] | None:
    try:
        import psycopg2
        conn = psycopg2.connect(url)
        cur = conn.cursor()
        cur.execute(sql, params or None)
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as exc:
        return None


def _classify(label: str, sq_rows: "list[tuple] | None", pg_rows: "list[tuple] | None"):
    """Pure classification of one query's two results, factored out of
    main() so it can be unit tested without real database connections.

    Returns (status, sq_display, pg_display, failure_message_or_None).

    Code-review finding (2026-09-28): a query erroring on one or both
    sides used to be classified SKIP, which never contributed to
    fail_count/failures and therefore never affected the exit code --
    four queries with a typo'd table/column name (now fixed in _QUERIES)
    silently reported SKIP on every run, forever, while this script
    still exited 0. Every query in _QUERIES is meant to always be valid
    on both databases (see the module docstring); there is no legitimate
    reason for one to error, so any error here is a real failure, never
    a skip -- this function has no SKIP outcome at all."""
    if sq_rows is None and pg_rows is None:
        return ("FAIL", "ERR", "ERR", f"{label}: both SQLite and PG queries failed")
    if sq_rows is None:
        return ("FAIL", "ERR", str(len(pg_rows)), f"{label}: SQLite query failed")
    if pg_rows is None:
        sq_display = str(len(sq_rows)) if len(sq_rows) > 1 else (str(sq_rows[0][0]) if sq_rows else "0")
        return ("FAIL", sq_display, "ERR", f"{label}: PG query failed")

    sq_display = str(sq_rows[0][0]) if len(sq_rows) == 1 and len(sq_rows[0]) == 1 else f"{len(sq_rows)}r"
    pg_display = str(pg_rows[0][0]) if len(pg_rows) == 1 and len(pg_rows[0]) == 1 else f"{len(pg_rows)}r"
    if _hash_rows(sq_rows) == _hash_rows(pg_rows):
        return ("PASS", sq_display, pg_display, None)

    sq_val = sq_rows[0][0] if len(sq_rows) == 1 and len(sq_rows[0]) == 1 else f"{len(sq_rows)} rows"
    pg_val = pg_rows[0][0] if len(pg_rows) == 1 and len(pg_rows[0]) == 1 else f"{len(pg_rows)} rows"
    return ("FAIL", sq_display, pg_display, f"{label}: sqlite={sq_val!r} pg={pg_val!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Warm replay: SQLite vs shadow PG.")
    parser.add_argument("--sqlite", required=True, help="Path to SQLite .db file.")
    parser.add_argument("--postgres", required=True, help="Shadow PG connection URL.")
    args = parser.parse_args()

    print(f"[warm-replay] {len(_QUERIES)} queries against SQLite + shadow PG\n")
    print(f"  {'Check':<42} {'SQLite':>8} {'PG':>8} {'Match':>7}")
    print("  " + "-" * 70)

    pass_count = fail_count = 0
    failures: list[str] = []

    for label, sql, params in _QUERIES:
        sq_rows = _run_sqlite(args.sqlite, sql, params)
        pg_rows = _run_pg(args.postgres, sql, params)
        status, sq_display, pg_display, failure_msg = _classify(label, sq_rows, pg_rows)
        if status == "PASS":
            pass_count += 1
        else:
            fail_count += 1
            failures.append(failure_msg)

        mark = "✓" if status == "PASS" else "✗"
        print(f"  {label:<42} {sq_display:>8} {pg_display:>8} {mark:>7}")

    print()
    print(f"[warm-replay] {pass_count} PASS, {fail_count} FAIL")

    if failures:
        print("\n[warm-replay] Failures:")
        for f in failures:
            print(f"  • {f}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
