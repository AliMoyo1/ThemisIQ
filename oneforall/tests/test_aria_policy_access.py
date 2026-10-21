"""
PLAN-35 T02: authorization tests for the ARIA policy workflow.

Covers roles, org/BU scope (unassigned users, group BU ancestors, sibling
SBUs, organization-wide records, super-admin org limits), approver
eligibility exclusions, the SBU-transfer invariant (future access changes,
record scope never does), and concurrent document-number allocation.

Business unit ids in these tests start at 100: a fresh init_db() already
seeds a default root business_unit at id=1 ("Company"/"ROOT"), confirmed
directly, so test fixtures use a disjoint id range rather than colliding
with (or depending on the exact fields of) that seeded row.
"""
import concurrent.futures

import database
from modules.aria.policy_access import (
    document_read_ok, document_scope_sql, template_scope_sql,
    resolve_create_bu, eligible_approvers, is_eligible_approver,
    can_decide, reserve_document_number,
)


def _org(db, org_id, slug=None):
    slug = slug or f"org{org_id}"
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,%s,%s)",
               (org_id, slug, slug))


def _bu(db, bu_id, name, parent_id=None):
    db.execute(
        "INSERT INTO business_units (id, name, parent_id, is_active) VALUES (%s,%s,%s,1)",
        (bu_id, name, parent_id),
    )


def _user(db, uid, org_id, bu_id=None, is_super_admin=0, is_active=1, username=None):
    username = username or f"user{uid}"
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, "
        "org_id, business_unit_id, is_super_admin, is_active) "
        "VALUES (%s,%s,%s,%s,'x',%s,%s,%s,%s)",
        (uid, username, f"{username}@example.com", username, org_id, bu_id,
         is_super_admin, is_active),
    )


def _role(db, uid, role_key):
    db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s,%s)", (uid, role_key))


def _actor(db, uid):
    row = db.execute(
        "SELECT id, org_id, business_unit_id, COALESCE(is_super_admin,0) AS is_super_admin, "
        "is_active FROM users WHERE id=%s", (uid,),
    ).fetchone()
    d = dict(row)
    d["roles"] = [r[0] for r in db.execute(
        "SELECT role_key FROM user_roles WHERE user_id=%s", (uid,)
    ).fetchall()]
    return d


# ─────────────────────────────────────────────────────────────────────────
# Org / BU read scope
# ─────────────────────────────────────────────────────────────────────────

def test_unassigned_user_sees_only_org_wide_not_a_colleagues_bu_doc(test_db):
    _org(test_db, 1)
    _bu(test_db, 110, "Finance")
    _user(test_db, 1, 1, bu_id=None)  # no BU assigned
    test_db.commit()
    actor = _actor(test_db, 1)

    org_wide_doc = {"org_id": 1, "business_unit_id": None, "policy_workflow_managed": 1}
    bu_scoped_doc = {"org_id": 1, "business_unit_id": 110, "policy_workflow_managed": 1}
    assert document_read_ok(actor, org_wide_doc) is True
    assert document_read_ok(actor, bu_scoped_doc) is False


def test_group_bu_ancestor_sees_descendant_bu_document(test_db):
    _org(test_db, 1)
    _bu(test_db, 100, "Group")
    _bu(test_db, 101, "Econet", parent_id=100)
    _bu(test_db, 102, "EcoCash", parent_id=101)
    _user(test_db, 1, 1, bu_id=100)  # sits at the group root
    test_db.commit()
    actor = _actor(test_db, 1)

    grandchild_doc = {"org_id": 1, "business_unit_id": 102, "policy_workflow_managed": 1}
    assert document_read_ok(actor, grandchild_doc) is True


def test_sibling_sbus_cannot_see_each_other(test_db):
    _org(test_db, 1)
    _bu(test_db, 100, "Group")
    _bu(test_db, 101, "EcoCash", parent_id=100)
    _bu(test_db, 102, "Omni", parent_id=100)
    _user(test_db, 1, 1, bu_id=101)  # EcoCash
    test_db.commit()
    actor = _actor(test_db, 1)

    omni_doc = {"org_id": 1, "business_unit_id": 102, "policy_workflow_managed": 1}
    assert document_read_ok(actor, omni_doc) is False


def test_super_admin_sees_all_bus_in_own_org_but_not_another_org(test_db):
    _org(test_db, 1, "econet")
    _org(test_db, 2, "otherco")
    _bu(test_db, 100, "AnyBU")
    _user(test_db, 1, 1, bu_id=None, is_super_admin=1)
    test_db.commit()
    actor = _actor(test_db, 1)

    same_org_doc = {"org_id": 1, "business_unit_id": 100, "policy_workflow_managed": 1}
    other_org_doc = {"org_id": 2, "business_unit_id": None, "policy_workflow_managed": 1}
    assert document_read_ok(actor, same_org_doc) is True
    assert document_read_ok(actor, other_org_doc) is False


def test_legacy_unmanaged_document_stays_visible_regardless_of_scope(test_db):
    """A row with org_id NULL and policy_workflow_managed=0 predates
    adoption -- visibility is unchanged until it's actually adopted."""
    _org(test_db, 1)
    _user(test_db, 1, 1, bu_id=None)
    test_db.commit()
    actor = _actor(test_db, 1)
    legacy_doc = {"org_id": None, "business_unit_id": None, "policy_workflow_managed": 0}
    assert document_read_ok(actor, legacy_doc) is True


def test_document_scope_sql_matches_document_read_ok_against_real_rows(test_db):
    """The SQL-fragment version used by list/count queries must select
    exactly the same rows document_read_ok() would allow one at a time."""
    _org(test_db, 1)
    _org(test_db, 2)
    _bu(test_db, 100, "Group")
    _bu(test_db, 101, "EcoCash", parent_id=100)
    _bu(test_db, 102, "Omni", parent_id=100)
    _user(test_db, 1, 1, bu_id=101)
    test_db.commit()
    actor = _actor(test_db, 1)

    rows = [
        ("DOC-A", 1, None, 0),     # legacy unmanaged -> visible
        ("DOC-B", 1, None, 1),     # org-wide managed -> visible
        ("DOC-C", 1, 101, 1),      # own BU -> visible
        ("DOC-D", 1, 102, 1),      # sibling BU -> not visible
        ("DOC-E", 2, None, 1),     # other org -> not visible
    ]
    for doc_id, org_id, bu_id, managed in rows:
        test_db.execute(
            "INSERT INTO aria_documents (doc_id, framework, title, version, status, "
            "org_id, business_unit_id, policy_workflow_managed) "
            "VALUES (%s,'ISO 27001','t','1.0','Draft',%s,%s,%s)",
            (doc_id, org_id, bu_id, managed),
        )
    test_db.commit()

    scope_sql, params = document_scope_sql(actor)
    visible = {r[0] for r in test_db.execute(
        f"SELECT doc_id FROM aria_documents WHERE {scope_sql}", params
    ).fetchall()}
    assert visible == {"DOC-A", "DOC-B", "DOC-C"}


def test_template_scope_sql_excludes_retired_templates_by_default(test_db):
    _org(test_db, 1)
    _user(test_db, 1, 1)
    test_db.commit()
    actor = _actor(test_db, 1)

    test_db.execute(
        "INSERT INTO aria_doc_templates (name, file_path, file_name, org_id, is_active) "
        "VALUES ('Active Tpl', 'a.docx', 'a.docx', 1, 1)"
    )
    test_db.execute(
        "INSERT INTO aria_doc_templates (name, file_path, file_name, org_id, is_active) "
        "VALUES ('Retired Tpl', 'r.docx', 'r.docx', 1, 0)"
    )
    test_db.commit()

    scope_sql, params = template_scope_sql(actor)
    names = {r[0] for r in test_db.execute(
        f"SELECT name FROM aria_doc_templates t WHERE {scope_sql}", params
    ).fetchall()}
    assert names == {"Active Tpl"}

    scope_sql2, params2 = template_scope_sql(actor, include_inactive=True)
    names2 = {r[0] for r in test_db.execute(
        f"SELECT name FROM aria_doc_templates t WHERE {scope_sql2}", params2
    ).fetchall()}
    assert names2 == {"Active Tpl", "Retired Tpl"}


# ─────────────────────────────────────────────────────────────────────────
# The SBU-transfer invariant: future access changes, record scope does not
# ─────────────────────────────────────────────────────────────────────────

def test_sbu_transfer_changes_future_access_without_touching_record_scope(test_db):
    """Simulates the end-state effect of a real SBU transfer (the user's
    business_unit_id changing) directly against bu_scope_ids/document_read_ok,
    rather than driving governance.transfer_user_business_unit's full
    workflow, which has unrelated prerequisites (handover confirmation,
    People Directory, assignment ledger) outside this module's concern.
    The property under test belongs to policy_access, not to that workflow."""
    _org(test_db, 1)
    _bu(test_db, 100, "EcoCash")
    _bu(test_db, 101, "Omni")
    _user(test_db, 1, 1, bu_id=100)
    test_db.commit()

    doc = {"org_id": 1, "business_unit_id": 100, "policy_workflow_managed": 1}
    before = _actor(test_db, 1)
    assert document_read_ok(before, doc) is True

    # The transfer itself: only the user's business_unit_id changes.
    test_db.execute("UPDATE users SET business_unit_id=101 WHERE id=1")
    test_db.commit()

    after = _actor(test_db, 1)
    assert document_read_ok(after, doc) is False  # future access: revoked
    # The document's own recorded scope is untouched by the user's transfer:
    # this dict is the same object passed to document_read_ok() both times.
    assert doc["business_unit_id"] == 100


# ─────────────────────────────────────────────────────────────────────────
# Create-time BU resolution
# ─────────────────────────────────────────────────────────────────────────

def test_resolve_create_bu_defaults_to_actors_own_bu(test_db):
    _org(test_db, 1)
    _bu(test_db, 105, "Finance")
    _user(test_db, 1, 1, bu_id=105)
    test_db.commit()
    actor = _actor(test_db, 1)
    bu_id, err = resolve_create_bu(actor, None, org_wide=False)
    assert err is None and bu_id == 105


def test_resolve_create_bu_rejects_bu_outside_subtree(test_db):
    _org(test_db, 1)
    _bu(test_db, 100, "Group")
    _bu(test_db, 101, "EcoCash", parent_id=100)
    _bu(test_db, 102, "Omni", parent_id=100)
    _user(test_db, 1, 1, bu_id=101)
    test_db.commit()
    actor = _actor(test_db, 1)
    bu_id, err = resolve_create_bu(actor, 102, org_wide=False)
    assert bu_id is None and err is not None


def test_resolve_create_bu_org_wide_requires_edit_any(test_db):
    _org(test_db, 1)
    _user(test_db, 1, 1, bu_id=None)
    test_db.commit()
    actor = _actor(test_db, 1)  # no roles -> no edit_any
    bu_id, err = resolve_create_bu(actor, None, org_wide=True)
    assert bu_id is None and err is not None

    _role(test_db, 1, "super_admin")
    test_db.commit()
    actor2 = _actor(test_db, 1)
    bu_id2, err2 = resolve_create_bu(actor2, None, org_wide=True)
    assert err2 is None and bu_id2 is None  # None = organization-wide, not "no BU resolved"


# ─────────────────────────────────────────────────────────────────────────
# Approver eligibility
# ─────────────────────────────────────────────────────────────────────────

def test_eligible_approvers_excludes_owner_and_requester_and_deactivated(test_db):
    _org(test_db, 1)
    _bu(test_db, 100, "Finance")
    _user(test_db, 1, 1, bu_id=100, username="owner")
    _user(test_db, 2, 1, bu_id=100, username="requester")
    _user(test_db, 3, 1, bu_id=100, username="eligible_approver")
    _user(test_db, 4, 1, bu_id=100, username="deactivated_approver", is_active=0)
    for uid in (1, 2, 3, 4):
        _role(test_db, uid, "compliance_manager")
    test_db.commit()

    document = {"org_id": 1, "business_unit_id": 100, "policy_workflow_managed": 1}
    eligible = eligible_approvers(test_db, document, exclude_user_ids={1, 2})
    ids = {c["id"] for c in eligible}
    assert ids == {3}, f"expected only user 3, got {ids}"


def test_eligible_approvers_excludes_users_without_the_capability(test_db):
    _org(test_db, 1)
    _bu(test_db, 100, "Finance")
    _user(test_db, 1, 1, bu_id=100)
    test_db.commit()  # no roles granted at all
    document = {"org_id": 1, "business_unit_id": 100, "policy_workflow_managed": 1}
    assert eligible_approvers(test_db, document, exclude_user_ids=set()) == []


def test_eligible_approvers_excludes_sibling_bu_users(test_db):
    _org(test_db, 1)
    _bu(test_db, 100, "Group")
    _bu(test_db, 101, "EcoCash", parent_id=100)
    _bu(test_db, 102, "Omni", parent_id=100)
    _user(test_db, 1, 1, bu_id=102, username="sibling_approver")
    _role(test_db, 1, "compliance_manager")
    test_db.commit()

    document = {"org_id": 1, "business_unit_id": 101, "policy_workflow_managed": 1}
    assert is_eligible_approver(test_db, 1, document, exclude_user_ids=set()) is False


def test_can_decide_requires_exact_assigned_approver_no_admin_override(test_db):
    _org(test_db, 1)
    _user(test_db, 1, 1, username="assigned_approver")
    _user(test_db, 2, 1, username="super_admin_bystander", is_super_admin=1)
    for uid in (1, 2):
        _role(test_db, uid, "compliance_manager")
        _role(test_db, uid, "super_admin")
    test_db.commit()

    approval = {"approver_id": 1, "status": "pending"}
    assigned = _actor(test_db, 1)
    bystander = _actor(test_db, 2)
    assert can_decide(assigned, approval) is True
    assert can_decide(bystander, approval) is False, \
        "no override, not even for a super admin, per the confirmed decision"


# ─────────────────────────────────────────────────────────────────────────
# Concurrent document-number allocation
# ─────────────────────────────────────────────────────────────────────────

def test_concurrent_reservations_never_duplicate_a_document_number(tmp_path, monkeypatch):
    """Uses a real file-based DB (not the in-memory test_db fixture) so
    separate threads get separate real connections contending for the same
    lock, the scenario the locked allocator exists to survive."""
    monkeypatch.setattr(database, "_DB_PATH", str(tmp_path / "concurrency.db"))
    database.init_db()

    def worker():
        db = database.get_db()
        try:
            num = reserve_document_number(db, is_postgres=False)
            db.commit()
            return num
        finally:
            db.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda _: worker(), range(25)))

    assert len(results) == len(set(results)) == 25


def test_number_allocator_continues_past_existing_legacy_doc_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_DB_PATH", str(tmp_path / "seq.db"))
    database.init_db()
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO aria_documents (doc_id, framework, title, version, status) "
            "VALUES ('DOC-0007', 'ISO 27001', 't', '1.0', 'Draft')"
        )
        db.commit()
        from scripts.prepare_aria_policy_workflow import ensure_document_number_sequence
        ensure_document_number_sequence(db)
        num = reserve_document_number(db, is_postgres=False)
        db.commit()
    finally:
        db.close()
    assert num == "DOC-0008"
