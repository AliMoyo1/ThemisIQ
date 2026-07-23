#!/usr/bin/env python3
"""
econet_bu_reassign.py -- PLAN-31 follow-up on the consolidated Econet Group org.

Applies (all in the shared public schema of the real production DB on 5434):
  - Rename business unit 'Omni' -> 'OmniContact'.
  - Move Florence.Chimbetete and Freedom.Muranda up to the 'Econet' parent BU
    so bu_scope_ids() gives them the rollup view of every SBU beneath Econet,
    and grant them the Chief GRC Officer (grc_officer) role so they actually
    have cross-module read access to that scope (BU placement alone is not
    enough -- it sets scope, the role sets visibility).
  - Deactivate the placeholder accounts omni@omni.com and test@test.com.
  - Clear changed users' sessions so new scope/roles resolve on next login.

DRY RUN by default -- prints what it WOULD do, commits nothing. Pass --commit
to apply, inside one transaction that rolls back on any error.

Run as the postgres superuser against the real production DB (port 5434):
    sudo -u postgres python3 oneforall/scripts/econet_bu_reassign.py            # dry run
    sudo -u postgres python3 oneforall/scripts/econet_bu_reassign.py --commit    # apply
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

ECONET_BU_NAME = "Econet"                       # the parent oversight BU (root)
OMNI_RENAME_FROM, OMNI_RENAME_TO = "Omni", "OmniContact"
PROMOTE_EMAILS = [                              # -> Econet BU + grc_officer role
    "Florence.Chimbetete@econet.co.zw",
    "Freedom.Muranda@econet.co.zw",
]
OVERSIGHT_ROLE = "grc_officer"
DEACTIVATE_EMAILS = ["omni@omni.com", "test@test.com"]


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
    for port in _socket_ports():
        try:
            conn = psycopg2.connect(dbname=DB_NAME, user="postgres",
                                    host=SOCKET_DIR, port=port)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
                is_super = cur.fetchone()[0]
            if is_super:
                conn.autocommit = False
                print(f"Connected as Postgres superuser on port {port}.\n")
                return conn
            conn.close()
        except Exception as e:
            print(f"Superuser attempt on port {port} failed ({e}).")
    print("Could not connect as postgres superuser. "
          "Run with: sudo -u postgres python3 oneforall/scripts/econet_bu_reassign.py")
    sys.exit(1)


def main():
    commit = "--commit" in sys.argv
    conn = _connect()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    changed_ids = []
    try:
        cur.execute(
            "SELECT id FROM business_units WHERE name = %s AND parent_id IS NULL",
            (ECONET_BU_NAME,))
        rows = cur.fetchall()
        if len(rows) != 1:
            print(f"ABORT: expected exactly one root BU '{ECONET_BU_NAME}', found {len(rows)}.")
            conn.rollback()
            sys.exit(1)
        econet_bu = rows[0]["id"]
        print(f"Econet parent BU id={econet_bu}\n")

        # 1. Rename Omni -> OmniContact
        cur.execute(
            "SELECT id FROM business_units WHERE name = %s AND parent_id = %s",
            (OMNI_RENAME_FROM, econet_bu))
        omni = cur.fetchone()
        if omni:
            cur.execute(
                "UPDATE business_units SET name = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (OMNI_RENAME_TO, omni["id"]))
            print(f"Rename BU id={omni['id']}: '{OMNI_RENAME_FROM}' -> '{OMNI_RENAME_TO}'")
        else:
            print(f"No BU '{OMNI_RENAME_FROM}' under Econet (already renamed?) -- skipping rename.")

        # 2. Promote Florence / Freedom to Econet oversight + grc_officer
        for email in PROMOTE_EMAILS:
            cur.execute(
                "SELECT id, username FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
            u = cur.fetchone()
            if not u:
                print(f"  WARNING: user {email} not found -- skipping.")
                continue
            cur.execute("UPDATE users SET business_unit_id = %s WHERE id = %s",
                        (econet_bu, u["id"]))
            cur.execute(
                "INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING", (u["id"], OVERSIGHT_ROLE))
            changed_ids.append(u["id"])
            print(f"Promote {u['username']} ({email}) -> BU '{ECONET_BU_NAME}' (id={econet_bu}) "
                  f"+ grant role '{OVERSIGHT_ROLE}'")

        # 3. Deactivate placeholder accounts
        for email in DEACTIVATE_EMAILS:
            cur.execute(
                "SELECT id, username FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
            u = cur.fetchone()
            if not u:
                print(f"  WARNING: account {email} not found -- skipping.")
                continue
            cur.execute("UPDATE users SET is_active = 0 WHERE id = %s", (u["id"],))
            changed_ids.append(u["id"])
            print(f"Deactivate account {u['username']} ({email})")

        # 4. Clear changed users' sessions
        if changed_ids:
            cur.execute("DELETE FROM sessions WHERE user_id = ANY(%s)", (changed_ids,))
            print(f"\nCleared sessions for {len(changed_ids)} changed user(s).")

        # ---- After-state report ----
        print("\n" + "=" * 64)
        print("AFTER (pending -- not committed)" if not commit else "AFTER (committed)")
        print("=" * 64)
        cur.execute(
            "SELECT bu.id, bu.name, bu.parent_id, "
            "COUNT(u.id) FILTER (WHERE u.is_active = 1) AS active_users "
            "FROM business_units bu LEFT JOIN users u ON u.business_unit_id = bu.id "
            "GROUP BY bu.id, bu.name, bu.parent_id "
            "ORDER BY bu.parent_id NULLS FIRST, bu.id")
        print("business_units (active user counts):")
        for r in cur.fetchall():
            print(f"  id={r['id']:<3} {r['name']:<18} parent={str(r['parent_id']):<5} active_users={r['active_users']}")

        cur.execute(
            "SELECT u.username, u.email, u.business_unit_id, u.is_active, "
            "ARRAY_REMOVE(ARRAY_AGG(ur.role_key), NULL) AS roles "
            "FROM users u LEFT JOIN user_roles ur ON ur.user_id = u.id "
            "WHERE LOWER(u.email) = ANY(%s) "
            "GROUP BY u.id, u.username, u.email, u.business_unit_id, u.is_active",
            ([e.lower() for e in PROMOTE_EMAILS + DEACTIVATE_EMAILS],))
        print("\naffected users:")
        for r in cur.fetchall():
            print(f"  {r['username']:<22} bu={str(r['business_unit_id']):<5} "
                  f"active={r['is_active']} roles={r['roles']}")

        if commit:
            conn.commit()
            print("\nCOMMITTED.")
        else:
            conn.rollback()
            print("\nDRY RUN -- rolled back, nothing changed. Re-run with --commit to apply.")
    except Exception as e:
        conn.rollback()
        print(f"\nERROR (rolled back, nothing changed): {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
