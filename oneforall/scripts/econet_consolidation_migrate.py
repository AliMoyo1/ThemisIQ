#!/usr/bin/env python3
"""
econet_consolidation_migrate.py -- PLAN-31 Phase 2, scope "users + structure only".

Consolidates the Omni / Ecocash / Econet Wireless organizations into the
Default org (renamed "Econet Group"), creating each as a business unit under
the existing "Econet" root BU and moving that org's users across. It does
NOT copy any domain data -- the source tenant schemas (tenant_omni,
tenant_ecocash, tenant_econet_wireless) are left completely untouched, so
their risks/evidence/documents remain intact and recoverable.

What it changes (only these, all in the shared public schema):
  - organizations: rename Default -> "Econet Group"; set the 3 source orgs
    to status='inactive' (NOT deleted -- their schema data is preserved).
  - business_units (public): add Ecocash / Econet Wireless / Omni under
    the existing "Econet" root BU (idempotent -- reuses them if already there).
  - users: move each source org's users to org 1 with the matching new
    business_unit_id.
  - sessions: clear moved users' sessions so they re-login with fresh org
    context.

DRY RUN by default -- prints exactly what it WOULD do and commits nothing.
Pass --commit to actually apply, inside a single transaction that rolls back
on any error or on a detected username/email collision.

MUST run as the postgres superuser against the real production DB on port
5434 (see PLAN-31's CRITICAL ENVIRONMENT FINDING -- the Docker DB on 5432 is
an abandoned leftover):
    sudo -u postgres python3 oneforall/scripts/econet_consolidation_migrate.py            # dry run
    sudo -u postgres python3 oneforall/scripts/econet_consolidation_migrate.py --commit    # apply

Take a fresh superuser backup immediately before the --commit run
(PLAN-31 Phase 0).
"""
import sys
import os
import glob

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("psycopg2 not installed. Run: pip3 install psycopg2-binary --break-system-packages")
    sys.exit(1)

SOCKET_DIR = "/var/run/postgresql"
DB_NAME = "themisiq"

TARGET_ORG_ID = 1               # Default -> renamed to Econet Group
TARGET_ORG_NAME = "Econet Group"
PARENT_BU_NAME = "Econet"       # SBUs attach under this existing root BU in public
# (slug of the source org, display name for its new business unit)
SOURCE_ORGS = [
    ("omni", "Omni"),
    ("ecocash", "Ecocash"),
    ("econet_wireless", "Econet Wireless"),
]


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
    """Connect as the Postgres superuser (bypasses RLS, allows writes) on the
    real production instance. Superuser is required both to see every org's
    rows and to UPDATE across them."""
    for port in _socket_ports():
        try:
            conn = psycopg2.connect(dbname=DB_NAME, user="postgres",
                                    host=SOCKET_DIR, port=port)
            # Probe in autocommit mode so the rolsuper check does not open a
            # transaction (which would make the switch to transactional mode
            # below fail with "set_session cannot be used inside a transaction").
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
                is_super = cur.fetchone()[0]
            if is_super:
                conn.autocommit = False  # transactional from here; no txn open yet
                print(f"Connected as Postgres superuser on port {port}.\n")
                return conn
            conn.close()
        except Exception as e:
            print(f"Superuser attempt on port {port} failed ({e}).")
    print("Could not connect as postgres superuser. "
          "Run with: sudo -u postgres python3 oneforall/scripts/econet_consolidation_migrate.py")
    sys.exit(1)


def main():
    commit = "--commit" in sys.argv
    conn = _connect()  # already in transactional mode (autocommit=False)
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        print("=" * 68)
        print("BEFORE")
        print("=" * 68)
        cur.execute(
            "SELECT o.id, o.name, o.status, COUNT(u.id) AS n "
            "FROM organizations o LEFT JOIN users u ON u.org_id = o.id "
            "GROUP BY o.id, o.name, o.status ORDER BY o.id"
        )
        for r in cur.fetchall():
            print(f"  org id={r['id']:<3} {r['name']:<22} status={r['status']:<10} users={r['n']}")

        # ---- Preconditions ----
        cur.execute("SELECT id, name FROM organizations WHERE id = %s", (TARGET_ORG_ID,))
        target = cur.fetchone()
        if not target:
            print(f"\nABORT: target org id {TARGET_ORG_ID} not found.")
            conn.rollback()
            sys.exit(1)

        cur.execute(
            "SELECT id FROM business_units WHERE name = %s AND parent_id IS NULL",
            (PARENT_BU_NAME,),
        )
        parents = cur.fetchall()
        if len(parents) != 1:
            print(f"\nABORT: expected exactly one root business unit named "
                  f"'{PARENT_BU_NAME}' in the public schema, found {len(parents)}. "
                  "Create/disambiguate it first.")
            conn.rollback()
            sys.exit(1)
        parent_bu_id = parents[0]["id"]

        print("\n" + "=" * 68)
        print("PLANNED CHANGES")
        print("=" * 68)
        print(f"Parent BU: '{PARENT_BU_NAME}' id={parent_bu_id}")
        print(f"Rename org {TARGET_ORG_ID}: '{target['name']}' -> '{TARGET_ORG_NAME}'")
        cur.execute("UPDATE organizations SET name = %s WHERE id = %s",
                    (TARGET_ORG_NAME, TARGET_ORG_ID))

        moved_user_ids = []
        for slug, bu_name in SOURCE_ORGS:
            cur.execute("SELECT id, name FROM organizations WHERE slug = %s", (slug,))
            src = cur.fetchone()
            if not src:
                print(f"\n  WARNING: source org slug '{slug}' not found -- skipping.")
                continue
            src_id = src["id"]

            # Idempotent BU create-or-reuse.
            cur.execute(
                "SELECT id FROM business_units WHERE name = %s AND parent_id = %s",
                (bu_name, parent_bu_id),
            )
            existing = cur.fetchone()
            if existing:
                bu_id = existing["id"]
                print(f"\n  BU '{bu_name}' already exists (id={bu_id}) -- reusing.")
            else:
                cur.execute(
                    "INSERT INTO business_units (name, code, description, parent_id) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (bu_name, slug.upper()[:20],
                     f"SBU consolidated from '{slug}' org (PLAN-31)", parent_bu_id),
                )
                bu_id = cur.fetchone()["id"]
                print(f"\n  Create BU '{bu_name}' (id={bu_id}) under '{PARENT_BU_NAME}'.")

            cur.execute("SELECT id, username, email FROM users WHERE org_id = %s", (src_id,))
            users = cur.fetchall()
            print(f"  Move {len(users)} user(s) from org {src_id} ('{slug}') "
                  f"-> org {TARGET_ORG_ID}, business_unit_id={bu_id}:")
            for u in users:
                print(f"      - {u['username']} ({u['email']})")
                moved_user_ids.append(u["id"])
            cur.execute(
                "UPDATE users SET org_id = %s, business_unit_id = %s WHERE org_id = %s",
                (TARGET_ORG_ID, bu_id, src_id),
            )
            cur.execute("UPDATE organizations SET status = 'inactive' WHERE id = %s", (src_id,))
            print(f"  Deactivate org {src_id} ('{slug}') "
                  "(schema + domain data preserved, not deleted).")

        # Clear moved users' sessions so they re-login with fresh org context.
        if moved_user_ids:
            cur.execute("DELETE FROM sessions WHERE user_id = ANY(%s)", (moved_user_ids,))
            print(f"\n  Cleared sessions for {len(moved_user_ids)} moved user(s) "
                  "(they will need to log in again).")

        # ---- Collision guard: usernames/emails must stay unique in target org ----
        cur.execute(
            "SELECT username, COUNT(*) AS c FROM users WHERE org_id = %s "
            "GROUP BY username HAVING COUNT(*) > 1", (TARGET_ORG_ID,))
        dup_u = cur.fetchall()
        cur.execute(
            "SELECT email, COUNT(*) AS c FROM users WHERE org_id = %s "
            "GROUP BY email HAVING COUNT(*) > 1", (TARGET_ORG_ID,))
        dup_e = cur.fetchall()
        if dup_u or dup_e:
            print("\nABORT: duplicate username/email would exist in the target org "
                  "after the move -- rolling back, nothing changed:")
            for d in dup_u:
                print(f"    username '{d['username']}' x{d['c']}")
            for d in dup_e:
                print(f"    email '{d['email']}' x{d['c']}")
            conn.rollback()
            sys.exit(1)

        print("\n" + "=" * 68)
        print("AFTER (pending -- not yet committed)" if not commit else "AFTER (committed)")
        print("=" * 68)
        cur.execute(
            "SELECT o.id, o.name, o.status, COUNT(u.id) AS n "
            "FROM organizations o LEFT JOIN users u ON u.org_id = o.id "
            "GROUP BY o.id, o.name, o.status ORDER BY o.id"
        )
        for r in cur.fetchall():
            print(f"  org id={r['id']:<3} {r['name']:<22} status={r['status']:<10} users={r['n']}")
        cur.execute(
            "SELECT id, name, parent_id FROM business_units ORDER BY parent_id NULLS FIRST, id")
        print("\n  business_units (public):")
        for r in cur.fetchall():
            print(f"    id={r['id']:<3} {r['name']:<22} parent_id={r['parent_id']}")

        if commit:
            conn.commit()
            print("\nCOMMITTED. Consolidation applied. Source org schemas were NOT "
                  "touched -- their data is preserved.")
        else:
            conn.rollback()
            print("\nDRY RUN -- transaction rolled back, nothing changed. "
                  "Re-run with --commit to apply.")
    except Exception as e:
        conn.rollback()
        print(f"\nERROR (rolled back, nothing changed): {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
