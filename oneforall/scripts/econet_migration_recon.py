#!/usr/bin/env python3
"""
econet_migration_recon.py -- READ-ONLY reconnaissance for PLAN-31 (the
Ecocash / Econet Wireless / Omni -> "Econet Group" org consolidation).

Makes no changes whatsoever -- every query is a SELECT or COUNT. Reports:
  - every organization row (id, name, slug, status)
  - every tenant schema present in the database
  - user counts per organization
  - row counts for every non-empty table in every tenant schema
  - the full business_units tree in every schema, to reveal whether
    Ecocash/Econet Wireless/Omni already have internal sub-structure
    beyond their seeded root

This database uses row-level security keyed on a per-request session GUC
(app.current_org_id, set by database.py's set_rls_context() on every real
app request). A plain connection as the app's own themisiq role never sets
that GUC, so RLS silently hides every row of every org-scoped table --
confirmed live: COUNT(*) FROM organizations returned 0 as themisiq but 4
as the postgres superuser. Superusers bypass RLS entirely, which is
exactly what a true, complete recon needs here.

Run as the postgres OS user so the peer-auth connection below lands on
the Postgres superuser role (matching how `sudo -u postgres psql` already
proved works), from /project on the VPS:
    sudo -u postgres python3 oneforall/scripts/econet_migration_recon.py

Falls back to the app's own themisiq-role DATABASE_URL (deploy.py's exact
construction) only if the superuser connection isn't available -- that
fallback will under-report real data due to RLS, same as the first recon
pass did, so prefer the sudo -u postgres invocation above.
"""
import sys
import os
import glob

try:
    import psycopg2
except ImportError:
    print("psycopg2 not installed. Run: pip3 install psycopg2-binary --break-system-packages")
    sys.exit(1)

SECRETS_FILE = "/project/secrets/pg_password.txt"
DB_NAME = "themisiq"

# The real production database is the system PostgreSQL on this VPS, whose
# socket lives in SOCKET_DIR. Confirmed live: the running app holds idle
# connections here (pg_stat_activity showed 4 themisiq connections from ::1)
# and it has the full 12 users / 4 orgs matching the UI. Its port is NOT the
# libpq default 5432 -- the actual socket file is .s.PGSQL.5434, and there
# are unrelated leftover Docker postgres containers on 5432/5433 the app no
# longer uses. psycopg2-binary bundles its own libpq defaulting to 5432, so
# the port must be passed explicitly; we derive it from the socket file(s)
# actually present, with 5434 then 5432 as fallbacks.
SOCKET_DIR = "/var/run/postgresql"


def _socket_ports():
    ports = []
    for f in glob.glob(os.path.join(SOCKET_DIR, ".s.PGSQL.*")):
        if f.endswith(".lock"):
            continue
        tail = f.rsplit(".", 1)[-1]
        if tail.isdigit():
            ports.append(int(tail))
    for fallback in (5434, 5432):
        if fallback not in ports:
            ports.append(fallback)
    return ports


def _connect():
    """Prefer the Postgres superuser via local peer auth (bypasses RLS
    entirely). Falls back to the app's own restricted role over TCP,
    which is subject to RLS and will under-report row counts."""
    for port in _socket_ports():
        try:
            conn = psycopg2.connect(dbname=DB_NAME, user="postgres",
                                    host=SOCKET_DIR, port=port)
            conn.set_session(readonly=True, autocommit=True)
            with conn.cursor() as cur:
                cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
                is_super = cur.fetchone()[0]
            if is_super:
                print(f"Connected as Postgres superuser on port {port} "
                      "(RLS bypassed) -- this is the complete picture.\n")
                return conn
            conn.close()
        except Exception as e:
            print(f"Superuser attempt on port {port} failed ({e}).")
    print("Falling back to the app role.\n")

    pw = None
    if os.path.exists(SECRETS_FILE):
        try:
            pw = open(SECRETS_FILE).read().strip()
        except PermissionError:
            pw = None
    if not pw:
        print(f"Could not connect as postgres superuser, and could not read {SECRETS_FILE} "
              "(likely a permission error if this script is running as the postgres OS user).")
        print("Re-run as root instead: python3 oneforall/scripts/econet_migration_recon.py")
        print("(without sudo -u postgres) to use the themisiq-role fallback, "
              "or fix socket/auth access for the postgres superuser path above.")
        sys.exit(1)
    print("WARNING: connected as the restricted 'themisiq' app role -- row-level "
          "security will silently hide rows belonging to other organizations. "
          "Counts below are NOT the complete picture. Re-run with "
          "'sudo -u postgres python3 ...' for accurate results.\n")
    conn = psycopg2.connect(f"postgresql://themisiq:{pw}@localhost:5432/{DB_NAME}")
    conn.set_session(readonly=True, autocommit=True)
    return conn


def main():
    conn = _connect()
    cur = conn.cursor()

    print("=" * 70)
    print("ORGANIZATIONS")
    print("=" * 70)
    cur.execute("SELECT id, name, slug, plan, status FROM organizations ORDER BY id")
    for row in cur.fetchall():
        print(f"  id={row[0]:<4} name={row[1]:<25} slug={row[2]:<25} plan={row[3]:<12} status={row[4]}")

    print()
    print("=" * 70)
    print("ALL SCHEMAS (excluding Postgres/system internals)")
    print("=" * 70)
    cur.execute(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name NOT IN ('pg_catalog', 'information_schema') "
        "AND schema_name NOT LIKE 'pg_toast%' AND schema_name NOT LIKE 'pg_temp%' "
        "ORDER BY schema_name"
    )
    schemas = [r[0] for r in cur.fetchall()]
    for s in schemas:
        print(f"  {s}")

    print()
    print("=" * 70)
    print("USERS PER ORGANIZATION")
    print("=" * 70)
    cur.execute(
        "SELECT o.name, o.id, COUNT(u.id) FROM organizations o "
        "LEFT JOIN users u ON u.org_id = o.id "
        "GROUP BY o.name, o.id ORDER BY o.id"
    )
    for row in cur.fetchall():
        print(f"  {row[0]:<25} org_id={row[1]:<4} users={row[2]}")

    print()
    print("=" * 70)
    print("ORG-SCOPING COLUMN CHECK (does each domain table carry org_id or")
    print("business_unit_id -- i.e. is isolation done by column, not schema?)")
    print("=" * 70)
    _check_tables = [
        "business_units", "departments", "business_processes", "applications",
        "data_assets", "erm_enterprise_risks", "orm_events", "aria_documents",
        "grid_audits", "sentinel_ropa", "bcm_plans", "evidence_items",
        "controls", "task_board",
    ]
    for t in _check_tables:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s "
            "AND column_name IN ('org_id', 'business_unit_id') "
            "ORDER BY column_name",
            (t,),
        )
        cols = [r[0] for r in cur.fetchall()]
        print(f"  {t:<25} {', '.join(cols) if cols else '(neither column present)'}")

    print()
    print("=" * 70)
    print("ROW COUNTS PER TABLE, PER SCHEMA (empty tables omitted)")
    print("=" * 70)
    for schema in schemas:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
            "ORDER BY table_name",
            (schema,),
        )
        tables = [r[0] for r in cur.fetchall()]
        print(f"\n--- schema: {schema} ({len(tables)} tables total) ---")
        for t in tables:
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{t}"')
                count = cur.fetchone()[0]
                if count > 0:
                    print(f"  {t:<40} {count}")
            except Exception as e:
                print(f"  {t:<40} ERROR: {e}")

    print()
    print("=" * 70)
    print("BUSINESS UNIT STRUCTURE PER SCHEMA")
    print("(non-root rows here = internal sub-structure a flat migration would lose)")
    print("=" * 70)
    for schema in schemas:
        try:
            cur.execute(f'SELECT id, name, parent_id FROM "{schema}".business_units ORDER BY id')
            rows = cur.fetchall()
            print(f"\n--- schema: {schema} ---")
            for r in rows:
                print(f"  id={r[0]:<4} name={r[1]:<30} parent_id={r[2]}")
        except Exception as e:
            print(f"  (no business_units table, or error: {e})")

    cur.close()
    conn.close()
    print()
    print("Recon complete. No changes were made to the database.")


if __name__ == "__main__":
    main()
