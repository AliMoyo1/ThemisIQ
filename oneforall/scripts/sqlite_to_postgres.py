#!/usr/bin/env python3
"""
sqlite_to_postgres.py — One-time data migration from SQLite to PostgreSQL.

Usage:
    # Dry-run (default — prints what would happen, touches nothing):
    python scripts/sqlite_to_postgres.py \\
        --sqlite data/oneforall.db \\
        --postgres postgresql://themisiq:pass@localhost:5432/themisiq

    # Apply the migration:
    python scripts/sqlite_to_postgres.py \\
        --sqlite data/oneforall.db \\
        --postgres $DATABASE_URL \\
        --apply

    # Migrate specific tables only:
    python scripts/sqlite_to_postgres.py ... --apply --tables aria_frameworks,aria_controls

    # Verify parity only (no data movement):
    python scripts/sqlite_to_postgres.py ... --verify-only

Safety:
    - Production SQLite is never written to (read-only connection).
    - All PG inserts use ON CONFLICT DO NOTHING — reruns are idempotent.
    - Sequences are reset after migration to avoid PK conflicts on new inserts.
    - Exits non-zero if row count parity fails.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from typing import Any

# GENERATED columns in ThemisIQ that must NOT be inserted (PG computes them)
_GENERATED_COLUMNS = {
    "aria_risks": {"risk_score"},
    "orm_risks": {"risk_score"},
    "aria_ask_index": {"body_tsv"},
}

# Batch size for execute_batch
_BATCH_SIZE = 100


def connect_sqlite(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def connect_pg(url: str):
    try:
        import psycopg2
        import psycopg2.extras
        return psycopg2.connect(url)
    except ImportError:
        print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)


def get_sqlite_tables(sqlite_conn: sqlite3.Connection) -> list[str]:
    """Return all non-FTS5, non-system tables in the SQLite database."""
    rows = sqlite_conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    # Filter out FTS5 shadow tables (suffixes: _data, _idx, _content, _docsize, _config)
    fts_shadows = re.compile(r"_(?:data|idx|content|docsize|config)$")
    tables = [r[0] for r in rows if not fts_shadows.search(r[0])]
    # Also remove FTS5 virtual tables themselves (they have no rows to migrate)
    def is_fts(name: str) -> bool:
        ddl_row = sqlite_conn.execute(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return ddl_row and ddl_row[0] and "USING fts5" in ddl_row[0].upper()
    return [t for t in tables if not is_fts(t)]


def get_sqlite_columns(sqlite_conn: sqlite3.Connection, table: str) -> list[str]:
    """Return column names, excluding GENERATED ALWAYS AS columns."""
    info = sqlite_conn.execute(f"PRAGMA table_info({table})").fetchall()
    excl = _GENERATED_COLUMNS.get(table, set())
    return [row[1] for row in info if row[1] not in excl]


def topological_sort(tables: list[str], sqlite_conn: sqlite3.Connection) -> list[str]:
    """Sort tables so FK-referenced parents come before children."""
    deps: dict[str, set[str]] = {t: set() for t in tables}
    table_set = set(tables)
    for t in tables:
        for fk in sqlite_conn.execute(f"PRAGMA foreign_key_list({t})").fetchall():
            ref = fk[2]  # referenced table
            if ref in table_set and ref != t:
                deps[t].add(ref)

    sorted_tables: list[str] = []
    visited: set[str] = set()
    in_progress: set[str] = set()

    def visit(t: str) -> None:
        if t in visited:
            return
        if t in in_progress:
            # Cycle — just add it (handles self-refs or circular FKs)
            sorted_tables.append(t)
            visited.add(t)
            return
        in_progress.add(t)
        for dep in deps[t]:
            visit(dep)
        in_progress.discard(t)
        visited.add(t)
        sorted_tables.append(t)

    for t in tables:
        visit(t)
    return sorted_tables


def coerce_value(v: Any) -> Any:
    """Coerce SQLite values for psycopg2 insertion."""
    if v == "":
        return None
    return v


def migrate_table(
    table: str,
    columns: list[str],
    sqlite_conn: sqlite3.Connection,
    pg_conn,
    apply: bool,
) -> tuple[int, int]:
    """
    Migrate one table.  Returns (sqlite_count, inserted_count).
    """
    import psycopg2.extras

    rows = sqlite_conn.execute(
        f"SELECT {', '.join(columns)} FROM {table}"
    ).fetchall()
    sqlite_count = len(rows)

    if not apply:
        return sqlite_count, 0

    if not rows:
        return 0, 0

    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT DO NOTHING"
    )
    data = [tuple(coerce_value(v) for v in row) for row in rows]

    with pg_conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, data, page_size=_BATCH_SIZE)

    return sqlite_count, sqlite_count  # ON CONFLICT DO NOTHING — use sqlite count as estimate


def reset_sequences(tables: list[str], columns_map: dict[str, list[str]], pg_conn) -> None:
    """Reset all SERIAL sequences to max(id) so new inserts don't conflict."""
    with pg_conn.cursor() as cur:
        for table in tables:
            if "id" not in columns_map.get(table, []):
                continue
            try:
                cur.execute(
                    f"SELECT setval("
                    f"  pg_get_serial_sequence('{table}', 'id'),"
                    f"  GREATEST(COALESCE(MAX(id), 1), 1),"
                    f"  MAX(id) IS NOT NULL"
                    f") FROM {table}"
                )
            except Exception:
                pass  # Table may not have a sequence (non-SERIAL PK)


def verify_parity(tables: list[str], sqlite_conn: sqlite3.Connection, pg_conn) -> bool:
    """Compare row counts between SQLite and PG. Returns True if all match."""
    ok = True
    print("\nParity check:")
    print(f"  {'Table':<45} {'SQLite':>10} {'PG':>10} {'Match':>6}")
    print("  " + "-" * 75)
    for table in sorted(tables):
        sc = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        with pg_conn.cursor() as cur:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                pc = cur.fetchone()[0]
            except Exception as e:
                pc = f"ERR:{e}"
        match = "✓" if sc == pc else "✗"
        if sc != pc:
            ok = False
        print(f"  {table:<45} {sc:>10} {str(pc):>10} {match:>6}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate SQLite → PostgreSQL.")
    parser.add_argument("--sqlite", required=True, help="Path to SQLite .db file.")
    parser.add_argument("--postgres", required=True, help="PostgreSQL connection URL.")
    parser.add_argument("--apply", action="store_true",
                        help="Write data to PG (default is dry-run).")
    parser.add_argument("--tables", default="",
                        help="Comma-separated list of tables to migrate (default: all).")
    parser.add_argument("--verify-only", action="store_true",
                        help="Skip migration, run parity check only.")
    args = parser.parse_args()

    sqlite_conn = connect_sqlite(args.sqlite)
    pg_conn = connect_pg(args.postgres)

    all_tables = get_sqlite_tables(sqlite_conn)
    if args.tables:
        subset = set(args.tables.split(","))
        all_tables = [t for t in all_tables if t in subset]

    print(f"[migrate] Found {len(all_tables)} tables in SQLite.")

    if args.verify_only:
        parity_ok = verify_parity(all_tables, sqlite_conn, pg_conn)
        sys.exit(0 if parity_ok else 1)

    sorted_tables = topological_sort(all_tables, sqlite_conn)
    columns_map = {t: get_sqlite_columns(sqlite_conn, t) for t in sorted_tables}

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[migrate] Mode: {mode}")
    print()

    total_sqlite = 0
    total_pg = 0
    errors: list[str] = []

    for table in sorted_tables:
        cols = columns_map[table]
        t0 = time.monotonic()
        try:
            sc, ic = migrate_table(table, cols, sqlite_conn, pg_conn, apply=args.apply)
            elapsed = time.monotonic() - t0
            status = "DRY" if not args.apply else "OK"
            print(f"  [{status}] {table:<45} {sc:>7} rows  ({elapsed:.1f}s)")
            total_sqlite += sc
            if args.apply:
                total_pg += ic
        except Exception as exc:
            pg_conn.rollback()
            errors.append(f"{table}: {exc}")
            print(f"  [ERR] {table}: {exc}", file=sys.stderr)

    if args.apply:
        pg_conn.commit()
        reset_sequences(sorted_tables, columns_map, pg_conn)
        pg_conn.commit()

    print()
    print(f"[migrate] Total SQLite rows: {total_sqlite}")
    if args.apply:
        print(f"[migrate] Total PG rows inserted: {total_pg}")

    if errors:
        print(f"\n[migrate] {len(errors)} table(s) with errors:")
        for e in errors:
            print(f"  • {e}")

    if args.apply:
        parity_ok = verify_parity(sorted_tables, sqlite_conn, pg_conn)
        if not parity_ok:
            print("\n[migrate] PARITY MISMATCH — investigate before cutover.")
            sys.exit(1)
        print("\n[migrate] Parity: PASS")
    else:
        print(f"\n[migrate] Dry-run complete. Re-run with --apply to execute.")

    sqlite_conn.close()
    pg_conn.close()
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
