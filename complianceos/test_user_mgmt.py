"""End-to-end tests for ARIA user management (tasks #17-25).

Run from project root:
    python test_user_mgmt.py

Uses a fresh /tmp/aria_test.db so we don't touch the production DB.
"""
import os, sys, shutil, sqlite3, hashlib, pathlib

# ── Hard-redirect DB BEFORE importing the app ────────────────────────────────
TEST_DB = "/tmp/aria_test.db"
for p in [TEST_DB, TEST_DB + "-wal", TEST_DB + "-shm", TEST_DB + "-journal"]:
    try: os.unlink(p)
    except FileNotFoundError: pass

os.environ["DB_PATH"] = TEST_DB
# Many modules hardcode DB_PATH from database.py, so patch at import time.
import database
database.DB_PATH = TEST_DB

# Skip ask index work during init (it's noisy and we don't need it here)
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-skip")

from fastapi.testclient import TestClient
import main
main.DB_PATH = TEST_DB  # make sure main sees test DB too

# Re-init DB against the test path
database.init_db()

# ── Starlette 1.0 compat shim ────────────────────────────────────────────────
# Production pins fastapi==0.111 (legacy starlette that supports
# TemplateResponse(name, ctx)). The dev env here has starlette 1.0 which
# requires TemplateResponse(request, name, ctx). Install a shim that detects
# the legacy 2-arg form so existing route code keeps working in tests.
from starlette.templating import Jinja2Templates as _J2T
_orig_tr = _J2T.TemplateResponse
def _compat_template_response(self, *args, **kwargs):
    # Legacy form: TemplateResponse(name: str, context: dict, ...)
    if args and isinstance(args[0], str):
        name = args[0]
        ctx = args[1] if len(args) > 1 else kwargs.pop("context", {})
        request = ctx.get("request")
        return _orig_tr(self, request, name, ctx, *args[2:], **kwargs)
    return _orig_tr(self, *args, **kwargs)
_J2T.TemplateResponse = _compat_template_response
main.templates.env.cache = {}

client = TestClient(main.app, follow_redirects=False)

passed = failed = 0
def check(cond, label):
    global passed, failed
    if cond:
        print(f"  ✅  {label}")
        passed += 1
    else:
        print(f"  ❌  {label}")
        failed += 1


def hp(p): return hashlib.sha256(p.encode()).hexdigest()

def db():
    c = sqlite3.connect(TEST_DB); c.row_factory = sqlite3.Row; return c


# ── 1. Migration: default seeded users should be in user_roles ───────────────
print("\n[1] Initial DB migration")
conn = db()
seed_users = conn.execute("SELECT id, username, role FROM users").fetchall()
check(len(seed_users) >= 1, f"seeded users present ({len(seed_users)} rows)")
for u in seed_users:
    rk = [r[0] for r in conn.execute(
        "SELECT role_key FROM user_roles WHERE user_id=?", (u["id"],)
    ).fetchall()]
    check(len(rk) > 0, f"user @{u['username']} has ≥1 role in user_roles ({rk})")
conn.close()


# ── 2. Login as admin ────────────────────────────────────────────────────────
print("\n[2] Admin login")
ADMIN_USER = "admin"
ADMIN_PW = "Admin@123!"
# Force the admin user's password to a known value for the test.
conn = db()
conn.execute("UPDATE users SET password_hash=?, must_change_password=0, active=1 WHERE username=?",
             (hp(ADMIN_PW), ADMIN_USER))
conn.commit(); conn.close()

r = client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PW})
check(r.status_code == 302 and "/dashboard" in r.headers.get("location", ""),
      f"admin login redirects to dashboard ({r.status_code})")
admin_cookies = dict(r.cookies)
check("user_id" in admin_cookies, "admin gets user_id cookie")

# Confirm: the legacy SHA-256 hash we just authenticated against has been
# silently upgraded to bcrypt on successful login.
conn = db()
ph = conn.execute("SELECT password_hash FROM users WHERE username=?", (ADMIN_USER,)).fetchone()[0]
conn.close()
check(ph.startswith("$2"), f"legacy SHA-256 hash upgraded to bcrypt (now {ph[:7]}…)")
# Wrong password should still be rejected after the upgrade
r_bad = client.post("/login", data={"username": ADMIN_USER, "password": "wrong-pw"})
check(r_bad.status_code == 200 and "Invalid credentials" in r_bad.text,
      "wrong password rejected against bcrypt hash")
# Correct password should work over bcrypt
r_ok = client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PW})
check(r_ok.status_code == 302, "correct password verifies against bcrypt hash")


# ── 3. /admin/users page renders ─────────────────────────────────────────────
print("\n[3] GET /admin/users")
r = client.get("/admin/users", cookies=admin_cookies)
check(r.status_code == 200, f"admin can open /admin/users (got {r.status_code})")
check("Users & Roles" in r.text, "page shows 'Users & Roles' title")
check("New User" in r.text, "has '+ New User' CTA")
check("Role reference" in r.text, "role reference section rendered")
for rk_label in ["System Administrator", "Policy Author", "Policy Approver",
                 "Control Owner", "Risk Owner", "Employee", "External Auditor"]:
    check(rk_label in r.text, f"role label present: {rk_label}")


# ── 4. Create a new user ─────────────────────────────────────────────────────
print("\n[4] Create new user")
new_user = {"username": "tatenda.c", "email": "tatenda@example.com", "full_name": "Tatenda Chikomba"}
r = client.post("/admin/users/create", data=new_user, cookies=admin_cookies)
check(r.status_code == 200, f"create returns 200 (got {r.status_code})")
check("temporary password" in r.text.lower(), "flash banner shows temp-password reveal")
check(new_user["username"] in r.text, "new user visible in list")

# Extract temp password from page: it's inside <code id="tempPwValue">...</code>
import re
m = re.search(r'id="tempPwValue"[^>]*>([A-Za-z0-9]+)<', r.text)
check(m is not None, "temp password is displayed on page")
temp_pw = m.group(1) if m else ""

conn = db()
nu = conn.execute("SELECT id, must_change_password, active FROM users WHERE username=?",
                  (new_user["username"],)).fetchone()
check(nu is not None, "new user persisted in DB")
check(nu["must_change_password"] == 1, "must_change_password=1 on new user")
check(nu["active"] == 1, "new user is active")
nu_roles = [r[0] for r in conn.execute(
    "SELECT role_key FROM user_roles WHERE user_id=?", (nu["id"],)
).fetchall()]
check(nu_roles == ["employee"], f"default role is 'employee' (got {nu_roles})")
conn.close()
new_uid = nu["id"]


# ── 5. Grant + revoke roles ──────────────────────────────────────────────────
print("\n[5] Grant and revoke roles")
r = client.post(f"/admin/users/{new_uid}/roles/grant",
                data={"role_key": "policy_author"}, cookies=admin_cookies)
check(r.status_code == 302, "grant returns redirect")
conn = db()
rk = sorted(r[0] for r in conn.execute(
    "SELECT role_key FROM user_roles WHERE user_id=?", (new_uid,)).fetchall())
conn.close()
check("policy_author" in rk, f"policy_author granted ({rk})")

r = client.post(f"/admin/users/{new_uid}/roles/grant",
                data={"role_key": "control_owner"}, cookies=admin_cookies)
check(r.status_code == 302, "grant control_owner redirect")

# Revoke employee
r = client.post(f"/admin/users/{new_uid}/roles/revoke",
                data={"role_key": "employee"}, cookies=admin_cookies)
check(r.status_code == 302, "revoke returns redirect")
conn = db()
rk = sorted(r[0] for r in conn.execute(
    "SELECT role_key FROM user_roles WHERE user_id=?", (new_uid,)).fetchall())
conn.close()
check("employee" not in rk, "employee revoked")
check(sorted(rk) == ["control_owner", "policy_author"], f"two roles remain ({rk})")

# Unknown role key rejected
r = client.post(f"/admin/users/{new_uid}/roles/grant",
                data={"role_key": "supreme_overlord"}, cookies=admin_cookies)
check(r.status_code == 200 and "Unknown role" in r.text, "unknown role rejected")


# ── 6. Last-admin guardrails ─────────────────────────────────────────────────
print("\n[6] Last-admin guardrails")
admin_uid = int(admin_cookies["user_id"])
r = client.post(f"/admin/users/{admin_uid}/roles/revoke",
                data={"role_key": "admin"}, cookies=admin_cookies)
check(r.status_code == 200 and "last admin" in r.text.lower(),
      "cannot revoke the only admin's admin role")

r = client.post(f"/admin/users/{admin_uid}/deactivate", cookies=admin_cookies)
check(r.status_code == 200 and "own account" in r.text.lower(),
      "cannot deactivate yourself")


# ── 7. Role-auto-floor: last role revoked → demote to employee ───────────────
print("\n[7] Role auto-floor")
# strip both remaining roles from new user
for rk in ["control_owner", "policy_author"]:
    client.post(f"/admin/users/{new_uid}/roles/revoke",
                data={"role_key": rk}, cookies=admin_cookies)
conn = db()
rk = [r[0] for r in conn.execute(
    "SELECT role_key FROM user_roles WHERE user_id=?", (new_uid,)).fetchall()]
conn.close()
check("employee" in rk, f"last revocation restores employee as floor (got {rk})")


# ── 8. Reset password flow ───────────────────────────────────────────────────
print("\n[8] Reset password")
r = client.post(f"/admin/users/{new_uid}/reset-password", cookies=admin_cookies)
check(r.status_code == 200, "reset returns 200")
check("Password reset for" in r.text, "flash banner shown")
m = re.search(r'id="tempPwValue"[^>]*>([A-Za-z0-9]+)<', r.text)
check(m is not None, "new temp password displayed")
new_temp = m.group(1) if m else ""
conn = db()
mu = conn.execute("SELECT must_change_password FROM users WHERE id=?",
                   (new_uid,)).fetchone()
conn.close()
check(mu["must_change_password"] == 1, "must_change_password set after reset")


# ── 9. Forced password change gate ───────────────────────────────────────────
print("\n[9] Forced password change gate")
# Log in as the newly-reset user. They should be redirected to /change-password
client_u = TestClient(main.app, follow_redirects=False)
r = client_u.post("/login", data={"username": "tatenda.c", "password": new_temp})
check(r.status_code == 302 and "/change-password" in r.headers.get("location", ""),
      f"login redirects to /change-password (got {r.headers.get('location')})")
u_cookies = dict(r.cookies)

# Visiting dashboard should bounce back to /change-password
r = client_u.get("/dashboard", cookies=u_cookies)
check(r.status_code == 302 and "/change-password" in r.headers.get("location", ""),
      "middleware redirects protected pages to /change-password")

# API endpoint should 403
r = client_u.get("/api/stats", cookies=u_cookies)
check(r.status_code == 403, f"middleware returns 403 on /api while pw-change pending (got {r.status_code})")

# Complete password change → gate lifts
r = client_u.post("/change-password", data={
    "new_password": "NewStrongPw!2026",
    "confirm_password": "NewStrongPw!2026",
}, cookies=u_cookies)
check(r.status_code == 302 and "/dashboard" in r.headers.get("location", ""),
      "pw change redirects to /dashboard")

r = client_u.get("/dashboard", cookies=u_cookies)
check(r.status_code == 200, f"dashboard now accessible (got {r.status_code})")


# ── 10. Capability enforcement ───────────────────────────────────────────────
print("\n[10] Capability enforcement")
# tatenda.c currently has only `employee` (auto-floor from #7). Grant just
# policy_author so we can test approval separation of duties.
client.post(f"/admin/users/{new_uid}/roles/grant",
            data={"role_key": "policy_author"}, cookies=admin_cookies)

# Employee (and policy_author) should NOT be able to see /admin/users
r = client_u.get("/admin/users", cookies=u_cookies)
check(r.status_code == 403, f"non-admin blocked from /admin/users (got {r.status_code})")

# Employee should NOT be able to create a document via /documents/add
r = client_u.post("/documents/add", data={
    "title": "Shouldn't work", "framework": "ISO 27001",
    "type": "Policy", "version": "1.0", "status": "Draft",
    "owner": "Tatenda Chikomba",
}, cookies=u_cookies)
# policy_author has create_policy, so it should succeed — but status should downgrade
check(r.status_code in (302, 200), f"policy_author can create policy ({r.status_code})")

conn = db()
doc = conn.execute("SELECT id, doc_id, status, owner FROM documents WHERE title=?",
                   ("Shouldn't work",)).fetchone()
conn.close()
check(doc is not None, "document was created")
check(doc["status"] == "Draft", f"policy_author forced status=Draft (got {doc['status']})")


# ── 11. Separation of duties on approval ─────────────────────────────────────
print("\n[11] Separation of duties on approve")
# Grant policy_approver to tatenda — now they're author+approver.
client.post(f"/admin/users/{new_uid}/roles/grant",
            data={"role_key": "policy_approver"}, cookies=admin_cookies)

# Their OWN draft → they shouldn't be able to self-approve.
# Route path uses the *string* doc_id ("DOC-0001"), not the integer id.
doc_doc_id = doc["doc_id"]
r = client_u.post(f"/documents/update/{doc_doc_id}", data={
    "status": "Approved",
}, cookies=u_cookies)
check(r.status_code == 403, f"self-approval returns 403 (got {r.status_code})")
conn = db()
d_after = conn.execute("SELECT status FROM documents WHERE doc_id=?",
                       (doc_doc_id,)).fetchone()
conn.close()
check(d_after["status"] != "Approved",
      f"self-approval blocked — status stayed {d_after['status']}")

# Admin approval on the same doc should work
r = client.post(f"/documents/update/{doc_doc_id}", data={
    "status": "Approved",
}, cookies=admin_cookies)
conn = db()
d_admin = conn.execute("SELECT status FROM documents WHERE doc_id=?",
                       (doc_doc_id,)).fetchone()
conn.close()
check(d_admin["status"] == "Approved", f"admin can approve (got {d_admin['status']})")


# ── 12. Owner scoping on controls ────────────────────────────────────────────
print("\n[12] Owner scoping on controls")
# Give tatenda only control_owner; set them as owner of one control, not another.
# First, strip their other roles to isolate the test.
for rk in ["policy_author", "policy_approver", "employee"]:
    client.post(f"/admin/users/{new_uid}/roles/revoke",
                data={"role_key": rk}, cookies=admin_cookies)
client.post(f"/admin/users/{new_uid}/roles/grant",
            data={"role_key": "control_owner"}, cookies=admin_cookies)

conn = db()
ctrls = conn.execute("SELECT id FROM controls ORDER BY id LIMIT 2").fetchall()
owned, unowned = ctrls[0]["id"], ctrls[1]["id"]
conn.execute("UPDATE controls SET owner=? WHERE id=?", ("Tatenda Chikomba", owned))
conn.execute("UPDATE controls SET owner=? WHERE id=?", ("Someone Else", unowned))
conn.commit(); conn.close()

# Update OWN control → should succeed
r = client_u.post(f"/control/{owned}/update", data={"status": "In Progress"}, cookies=u_cookies)
j = r.json()
check(j.get("success") is True, f"control_owner can update OWN control ({j})")

# Update NOT-OWNED control → should 403
r = client_u.post(f"/control/{unowned}/update", data={"status": "In Progress"}, cookies=u_cookies)
check(r.status_code == 403, f"control_owner blocked on unowned control ({r.status_code})")


# ── 13. Deactivation blocks login ────────────────────────────────────────────
print("\n[13] Deactivation blocks login")
client.post(f"/admin/users/{new_uid}/deactivate", cookies=admin_cookies)
# fresh client with no cookies
c_dead = TestClient(main.app, follow_redirects=False)
r = c_dead.post("/login", data={"username": "tatenda.c", "password": "NewStrongPw!2026"})
check(r.status_code == 200 and "deactivated" in r.text.lower(),
      f"deactivated user blocked at /login ({r.status_code})")

# Reactivate → login works again
client.post(f"/admin/users/{new_uid}/activate", cookies=admin_cookies)
r = c_dead.post("/login", data={"username": "tatenda.c", "password": "NewStrongPw!2026"})
check(r.status_code == 302, f"reactivated user can log in ({r.status_code})")


# ── 14. Audit-log coverage ───────────────────────────────────────────────────
print("\n[14] Audit log coverage")
conn = db()
actions = [r[0] for r in conn.execute(
    "SELECT action FROM audit_log ORDER BY id DESC LIMIT 30"
).fetchall()]
conn.close()
for needle in ["Created user tatenda.c",
               "Granted role 'policy_author'",
               "Revoked role",
               "Reset password for tatenda.c",
               "Deactivated user tatenda.c",
               "Activated user tatenda.c"]:
    check(any(needle in a for a in actions), f"audit log records: {needle!r}")


# ── Summary ──────────────────────────────────────────────────────────────────
print(f"\n{'─'*60}\n  RESULTS: {passed} passed / {failed} failed\n{'─'*60}")
sys.exit(0 if failed == 0 else 1)
