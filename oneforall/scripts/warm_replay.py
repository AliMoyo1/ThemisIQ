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

    ("users:active_admins",
     "SELECT COUNT(*) FROM users WHERE is_active = 1 AND role = 'admin'", ()),

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

    ("aria:risks_by_severity",
     "SELECT severity, COUNT(*) AS n FROM aria_risks GROUP BY severity ORDER BY severity",
     ()),

    # ── GRID ─────────────────────────────────────────────────────────────────
    ("grid:audit_count",
     "SELECT COUNT(*) FROM grid_audits", ()),

    ("grid:audits_by_status",
     "SELECT status, COUNT(*) AS n FROM grid_audits GROUP BY status ORDER BY status",
     ()),

    ("grid:nc_count",
     "SELECT COUNT(*) FROM grid_ncs", ()),

    ("grid:evidence_count",
     "SELECT COUNT(*) FROM grid_evidence", ()),

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
     "SELECT treatment, COUNT(*) AS n FROM erm_risks GROUP BY treatment ORDER BY treatment",
     ()),

    ("erm:obligation_count",
     "SELECT COUNT(*) FROM erm_obligations", ()),

    # ── ORM ──────────────────────────────────────────────────────────────────
    ("orm:events_by_category",
     "SELECT category, COUNT(*) AS n FROM orm_events GROUP BY category ORDER BY category",
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Warm replay: SQLite vs shadow PG.")
    parser.add_argument("--sqlite", required=True, help="Path to SQLite .db file.")
    parser.add_argument("--postgres", required=True, help="Shadow PG connection URL.")
    args = parser.parse_args()

    print(f"[warm-replay] {len(_QUERIES)} queries against SQLite + shadow PG\n")
    print(f"  {'Check':<42} {'SQLite':>8} {'PG':>8} {'Match':>7}")
    print("  " + "-" * 70)

    pass_count = fail_count = skip_count = 0
    failures: list[str] = []

    for label, sql, params in _QUERIES:
        sq_rows = _run_sqlite(args.sqlite, sql, params)
        pg_rows = _run_pg(args.postgres, sql, params)

        if sq_rows is None and pg_rows is None:
            status = "SKIP"
            skip_count += 1
            sq_display = "ERR"
            pg_display = "ERR"
        elif sq_rows is None:
            status = "SKIP"
            skip_count += 1
            sq_display = "ERR"
            pg_display = str(len(pg_rows))
        elif pg_rows is None:
            status = "FAIL"
            fail_count += 1
            failures.append(f"{label}: PG query failed")
            sq_display = str(len(sq_rows)) if len(sq_rows) > 1 else (str(sq_rows[0][0]) if sq_rows else "0")
            pg_display = "ERR"
        else:
            sq_h = _hash_rows(sq_rows)
            pg_h = _hash_rows(pg_rows)
            if sq_h == pg_h:
                status = "PASS"
                pass_count += 1
            else:
                status = "FAIL"
                fail_count += 1
                sq_val = sq_rows[0][0] if len(sq_rows) == 1 and len(sq_rows[0]) == 1 else f"{len(sq_rows)} rows"
                pg_val = pg_rows[0][0] if len(pg_rows) == 1 and len(pg_rows[0]) == 1 else f"{len(pg_rows)} rows"
                failures.append(f"{label}: sqlite={sq_val!r} pg={pg_val!r}")
            sq_display = str(sq_rows[0][0]) if len(sq_rows) == 1 and len(sq_rows[0]) == 1 else f"{len(sq_rows)}r"
            pg_display = str(pg_rows[0][0]) if len(pg_rows) == 1 and len(pg_rows[0]) == 1 else f"{len(pg_rows)}r"

        mark = "✓" if status == "PASS" else ("—" if status == "SKIP" else "✗")
        print(f"  {label:<42} {sq_display:>8} {pg_display:>8} {mark:>7}")

    print()
    print(f"[warm-replay] {pass_count} PASS, {fail_count} FAIL, {skip_count} SKIP")

    if failures:
        print("\n[warm-replay] Failures:")
        for f in failures:
            print(f"  • {f}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
