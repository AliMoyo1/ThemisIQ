"""
One For All - seed script.

Creates the default admin user and framework data for ARIA.
Run automatically on first startup if no users exist.
"""
import secrets
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_db, init_db, insert_returning_id
from core.auth import hash_password
from core.rbac import SUPER_ADMIN, COMPLIANCE_MGR, DPO, AUDIT_LEAD, BCM_MANAGER

# -- ARIA framework seed data (from ComplianceOS) -----------------------------
FRAMEWORKS = [
    # Original frameworks
    ("ISO 27001:2022", "Information Security Management System", "#1E3A5F", "aria,grid"),
    ("ISO 42001", "Artificial Intelligence Management System", "#6A0572", "aria"),
    ("SOC 2 Type II", "Service Organization Control 2", "#0B5345", "aria,grid"),
    ("PCI DSS v4.0", "Payment Card Industry Data Security Standard", "#7D6608", "aria,grid"),
    ("GDPR", "General Data Protection Regulation (EU) 2016/679", "#154360", "sentinel,aria"),
    ("Zimbabwe CDPA", "Cyber and Data Protection Act [Chapter 12:07]", "#145A32", "sentinel"),
    ("HIPAA", "Health Insurance Portability and Accountability Act", "#6E2F03", "sentinel,aria"),
    # New frameworks
    ("ISO 9001:2015", "Quality Management System", "#1B4F72", "aria,grid"),
    ("ISO 22301:2019", "Business Continuity Management System", "#7B241C", "bcm,aria,grid"),
    ("ISO 27701:2019", "Privacy Information Management System", "#4A235A", "sentinel,aria"),
    ("ISO 20000-1:2018", "IT Service Management System", "#0E6251", "aria,grid"),
    ("ISO 27017:2015", "Cloud Security Controls", "#1A5276", "aria,grid"),
    ("ISO 31000:2018", "Risk Management Guidelines", "#784212", "aria,bcm,grid"),
    ("ISO 14001:2015", "Environmental Management System", "#1D8348", "aria,grid"),
    ("ISO 50001:2018", "Energy Management System", "#117A65", "aria,grid"),
]


def seed_users(db):
    """Create default users if none exist."""
    count = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    if count > 0:
        return

    admin_pw = secrets.token_urlsafe(16)
    cm_pw    = secrets.token_urlsafe(16)
    dpo_pw   = secrets.token_urlsafe(16)
    bcm_pw   = secrets.token_urlsafe(16)

    # Super Admin
    admin_id = insert_returning_id(
        db,
        "INSERT INTO users (username, email, full_name, password_hash, avatar_initials, must_change_password) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        ("admin", "admin@oneforall.local", "System Administrator", hash_password(admin_pw), "SA", 1),
    )
    db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)", (admin_id, SUPER_ADMIN))

    # Compliance Manager
    cm_id = insert_returning_id(
        db,
        "INSERT INTO users (username, email, full_name, password_hash, avatar_initials, must_change_password) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        ("compliance", "compliance@oneforall.local", "Compliance Manager", hash_password(cm_pw), "CM", 1),
    )
    for role in [COMPLIANCE_MGR, AUDIT_LEAD]:
        db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)", (cm_id, role))

    # DPO
    dpo_id = insert_returning_id(
        db,
        "INSERT INTO users (username, email, full_name, password_hash, avatar_initials, must_change_password) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        ("dpo", "dpo@oneforall.local", "Data Protection Officer", hash_password(dpo_pw), "DP", 1),
    )
    db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)", (dpo_id, DPO))

    # BCM Manager
    bcm_id = insert_returning_id(
        db,
        "INSERT INTO users (username, email, full_name, password_hash, avatar_initials, must_change_password) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        ("bcm", "bcm@oneforall.local", "BCM Manager", hash_password(bcm_pw), "BM", 1),
    )
    db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)", (bcm_id, BCM_MANAGER))

    db.commit()
    print("  Seeded 4 default users")
    print("  SAVE THESE INITIAL PASSWORDS (users must change on first login):")
    print(f"    admin:      {admin_pw}")
    print(f"    compliance: {cm_pw}")
    print(f"    dpo:        {dpo_pw}")
    print(f"    bcm:        {bcm_pw}")


def seed_frameworks(db):
    """Seed frameworks into both the unified and legacy tables."""
    # -- Unified frameworks table (primary, used by framework_service) --------
    unified_count = db.execute("SELECT COUNT(*) as c FROM frameworks").fetchone()["c"]
    if unified_count == 0:
        for name, desc, color, modules in FRAMEWORKS:
            db.execute(
                "INSERT INTO frameworks "
                "(name, description, color, relevant_modules, is_active) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (name, desc, color, modules, 1),
            )
        db.commit()
        print("  Seeded %d unified frameworks" % len(FRAMEWORKS))

    # -- Legacy aria_frameworks table (used by older ARIA routes) -------------
    aria_count = db.execute("SELECT COUNT(*) as c FROM aria_frameworks").fetchone()["c"]
    if aria_count == 0:
        for name, desc, color, modules in FRAMEWORKS:
            db.execute(
                "INSERT INTO aria_frameworks "
                "(name, description, color, relevant_modules, is_active) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (name, desc, color, modules, 1),
            )
        db.commit()
        print("  Seeded %d legacy aria_frameworks" % len(FRAMEWORKS))


def seed_controls():
    """Seed controls for all frameworks (idempotent - skips already populated)."""
    from seeds.framework_controls import seed_all_controls
    count = seed_all_controls()
    if count:
        print("  Seeded %d controls across frameworks" % count)
    else:
        print("  Controls already populated - skipped")


def run_seed():
    print("One For All - Seeding database...")
    init_db()
    db = get_db()
    try:
        seed_users(db)
        seed_frameworks(db)
    finally:
        db.close()
    # Seed controls after DB connection closed (framework_service manages its own connections)
    seed_controls()
    # Seed pre-built control mappings after controls are loaded
    try:
        from seeds.control_mappings import seed_control_mappings
        count = seed_control_mappings()
        print("  Seeded %d pre-built control mappings" % count)
    except Exception as exc:
        print("  WARNING: Control mapping seed failed (non-fatal): %s" % exc)
    print("  Done!")


if __name__ == "__main__":
    run_seed()
