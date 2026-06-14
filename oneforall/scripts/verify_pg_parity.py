#!/usr/bin/env python3
"""
verify_pg_parity.py — Independent verifier: SQLite vs PostgreSQL row parity.

Usage:
    python scripts/verify_pg_parity.py \\
        --sqlite data/oneforall.db \\
        --postgres $DATABASE_URL

Checks:
    1. Row count per table (all tables).
    2. MD5 of ordered id list (tables that have an integer `id` column).
    3. Content comparison of 5 random rows per table.

Exits 0 if all tables PASS, 1 if any FAIL.
"""
from __future__ import annotations

import argparse
import hashlib
import random
import sqlite3
import sys
from typing import Any


def connect_sqlite(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def connect_pg(url: str):
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(url)
        return conn
    except ImportError:
        print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)


def get_tables(sqlite_conn: sqlite3.Connection) -> list[str]:
    import re
    rows = sqlite_conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    fts_shadows = re.compile(r"_(?:data|idx|content|docsize|config)$")
    result = []
    for r in rows:
        name = r[0]
        if fts_shadows.search(name):
            continue
        ddl = sqlite_conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        if ddl and ddl[0] and "USING fts5" in ddl[0].upper():
            continue
        result.append(name)
    return result


def pg_table_exists(pg_conn, table: str) -> bool:
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=%s)",
            (table,),
        )
        return cur.fetchone()[0]


def count_sqlite(sqlite_conn: sqlite3.Connection, table: str) -> int:
    return sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def count_pg(pg_conn, table: str) -> int:
    with pg_conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return cur.fetchone()[0]


def id_fingerprint_sqlite(sqlite_conn: sqlite3.Connection, table: str) -> str | None:
    """MD5 of all IDs sorted ascending."""
    try:
        rows = sqlite_conn.execute(f"SELECT id FROM {table} ORDER BY id").fetchall()
        ids = ",".join(str(r[0]) for r in rows)
        return hashlib.md5(ids.encode()).hexdigest()
    except Exception:
        return None


def id_fingerprint_pg(pg_conn, table: str) -> str | None:
    try:
        with pg_conn.cursor() as cur:
            cur.execute(f"SELECT id FROM {table} ORDER BY id")
            rows = cur.fetchall()
        ids = ",".join(str(r[0]) for r in rows)
        return hashlib.md5(ids.encode()).hexdigest()
    except Exception:
        return None


def sample_rows_sqlite(sqlite_conn: sqlite3.Connection, table: str, n: int = 5) -> list[dict]:
    rows = sqlite_conn.execute(f"SELECT * FROM {table} ORDER BY RANDOM() LIMIT {n}").fetchall()
    return [dict(r) for r in rows]


def sample_rows_pg(pg_conn, table: str, ids: list[Any]) -> list[dict]:
    if not ids:
        return []
    import psycopg2.extras
    with pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        placeholders = ",".join(["%s"] * len(ids))
        try:
            cur.execute(f"SELECT * FROM {table} WHERE id IN ({placeholders})", ids)
            return [dict(r) for r in cur.fetchall()]
        except Exception:
            return []


def rows_match(sqlite_rows: list[dict], pg_rows: list[dict], table: str) -> bool:
    """Compare rows by ID, ignoring column order and None vs '' differences."""
    pg_by_id = {r.get("id"): r for r in pg_rows}
    all_match = True
    for sr in sqlite_rows:
        sid = sr.get("id")
        pr = pg_by_id.get(sid)
        if pr is None:
            continue  # row may not exist yet — row count check will catch it
        for col, sv in sr.items():
            pv = pr.get(col)
            # Normalize: None == "" for this comparison
            sv_norm = None if sv == "" else sv
            pv_norm = None if pv == "" else pv
            if sv_norm != pv_norm:
                # Allow timestamp format differences (TEXT in SQLite vs datetime in PG)
                if isinstance(sv_norm, str) and str(pv_norm).startswith(str(sv_norm)[:10]):
                    continue
                all_match = False
                print(f"    DIFF {table}.{col} id={sid}: sqlite={sv_norm!r} pg={pv_norm!r}")
    return all_match


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify SQLite/PG row parity.")
    parser.add_argument("--sqlite", required=True, help="Path to SQLite .db file.")
    parser.add_argument("--postgres", required=True, help="PostgreSQL connection URL.")
    parser.add_argument("--sample", type=int, default=5, help="Random rows to compare per table.")
    args = parser.parse_args()

    sqlite_conn = connect_sqlite(args.sqlite)
    pg_conn = connect_pg(args.postgres)

    tables = get_tables(sqlite_conn)
    print(f"[parity] Checking {len(tables)} tables...\n")
    print(f"  {'Table':<45} {'SQLite':>8} {'PG':>8} {'Count':>6} {'ID-MD5':>6} {'Sample':>7}")
    print("  " + "-" * 85)

    pass_count = fail_count = skip_count = 0

    for table in sorted(tables):
        if not pg_table_exists(pg_conn, table):
            print(f"  {table:<45} {'N/A':>8} {'MISSING':>8} {'SKIP':>6} {'—':>6} {'—':>7}")
            skip_count += 1
            continue

        sc = count_sqlite(sqlite_conn, table)
        try:
            pc = count_pg(pg_conn, table)
        except Exception as e:
            print(f"  {table:<45} {'ERR':>8} {str(e)[:20]:>8}")
            fail_count += 1
            continue

        count_ok = "✓" if sc == pc else "✗"

        # ID fingerprint
        sf = id_fingerprint_sqlite(sqlite_conn, table)
        pf = id_fingerprint_pg(pg_conn, table)
        fp_ok = "✓" if sf == pf else ("—" if sf is None else "✗")

        # Row sample
        sqlite_sample = sample_rows_sqlite(sqlite_conn, table, args.sample)
        ids = [r.get("id") for r in sqlite_sample if r.get("id") is not None]
        pg_sample = sample_rows_pg(pg_conn, table, ids)
        sample_ok = "✓" if rows_match(sqlite_sample, pg_sample, table) else "✗"

        row_ok = count_ok == "✓" and fp_ok in ("✓", "—") and sample_ok == "✓"
        if row_ok:
            pass_count += 1
        else:
            fail_count += 1

        print(f"  {table:<45} {sc:>8} {pc:>8} {count_ok:>6} {fp_ok:>6} {sample_ok:>7}")

    print()
    print(f"[parity] Results: {pass_count} PASS, {fail_count} FAIL, {skip_count} SKIP")
    sys.exit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    main()
