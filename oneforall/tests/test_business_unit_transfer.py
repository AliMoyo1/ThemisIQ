"""Regression coverage for controlled same-organization SBU transfers."""
import json

import pytest

from modules.governance.data_service import (
    BusinessUnitTransferError,
    create_business_unit,
    preview_user_business_unit_transfer,
    transfer_user_business_unit,
)


def _create_org(db, slug="transfer-org"):
    db.execute(
        "INSERT INTO organizations (name, slug, status) VALUES (%s,%s,'active')",
        (slug.replace("-", " ").title(), slug),
    )
    db.commit()
    return db.execute(
        "SELECT id FROM organizations WHERE slug=%s", (slug,)
    ).fetchone()["id"]


def _create_user(db, org_id, username, business_unit_id=None):
    db.execute(
        "INSERT INTO users "
        "(username, email, full_name, password_hash, org_id, business_unit_id) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (
            username,
            f"{username}@example.com",
            username.replace("_", " ").title(),
            "x",
            org_id,
            business_unit_id,
        ),
    )
    db.commit()
    return db.execute(
        "SELECT id FROM users WHERE username=%s", (username,)
    ).fetchone()["id"]


def test_transfer_is_atomic_and_preserves_historical_ownership(test_db):
    org_id = _create_org(test_db)
    old_bu = create_business_unit({"name": "EcoCash"})
    new_bu = create_business_unit({"name": "Omni"})
    actor_id = _create_user(test_db, org_id, "org_admin", old_bu)
    user_id = _create_user(test_db, org_id, "moving_user", old_bu)

    test_db.execute(
        "INSERT INTO user_roles (user_id, role_key, granted_by) VALUES (%s,'employee',%s)",
        (user_id, actor_id),
    )
    test_db.execute(
        "INSERT INTO people_directory (full_name, user_id, business_unit_id) "
        "VALUES ('Moving User',%s,%s)",
        (user_id, old_bu),
    )
    test_db.execute(
        "INSERT INTO task_board (title, assigned_to, created_by) VALUES ('Handover task',%s,%s)",
        (user_id, actor_id),
    )
    test_db.execute(
        "UPDATE business_units SET head_user_id=%s WHERE id=%s",
        (user_id, old_bu),
    )
    test_db.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES ('active-session',%s,'2999-01-01')",
        (user_id,),
    )
    test_db.commit()

    preview = preview_user_business_unit_transfer(user_id, new_bu, org_id)
    assert preview["current_business_unit"]["name"] == "EcoCash"
    assert preview["destination_business_unit"]["name"] == "Omni"
    assert preview["roles"] == ["employee"]
    assert preview["responsibility_impact"]["tasks"] == 1
    assert preview["responsibility_impact"]["business units headed"] == 1

    result = transfer_user_business_unit(
        user_id,
        new_bu,
        org_id,
        actor_id,
        "Internal move from EcoCash to Omni",
        handover_confirmed=True,
        roles_reviewed=True,
    )

    assert result["transfer_id"]
    assert result["sessions_revoked"] == 1
    user = test_db.execute(
        "SELECT business_unit_id FROM users WHERE id=%s", (user_id,)
    ).fetchone()
    assert user["business_unit_id"] == new_bu
    person = test_db.execute(
        "SELECT business_unit_id FROM people_directory WHERE user_id=%s", (user_id,)
    ).fetchone()
    assert person["business_unit_id"] == new_bu
    assert test_db.execute(
        "SELECT COUNT(*) FROM sessions WHERE user_id=%s", (user_id,)
    ).fetchone()[0] == 0

    assignments = test_db.execute(
        "SELECT business_unit_id, status, valid_until "
        "FROM user_business_unit_assignments WHERE user_id=%s ORDER BY id",
        (user_id,),
    ).fetchall()
    assert [(row["business_unit_id"], row["status"]) for row in assignments] == [
        (old_bu, "ended"),
        (new_bu, "active"),
    ]
    assert assignments[0]["valid_until"]

    transfer = test_db.execute(
        "SELECT * FROM business_unit_transfers WHERE id=%s",
        (result["transfer_id"],),
    ).fetchone()
    assert transfer["from_business_unit_id"] == old_bu
    assert transfer["to_business_unit_id"] == new_bu
    assert transfer["status"] == "completed"
    assert json.loads(transfer["roles_snapshot"]) == ["employee"]
    assert json.loads(transfer["impact_snapshot"])["tasks"] == 1

    # A move changes current access scope, not historical ownership.
    assert test_db.execute(
        "SELECT assigned_to FROM task_board WHERE title='Handover task'"
    ).fetchone()["assigned_to"] == user_id
    assert test_db.execute(
        "SELECT head_user_id FROM business_units WHERE id=%s", (old_bu,)
    ).fetchone()["head_user_id"] == user_id


@pytest.mark.parametrize(
    "handover_confirmed,roles_reviewed,error_text",
    [
        (False, True, "responsibilities"),
        (True, False, "roles"),
    ],
)
def test_transfer_requires_reviews_and_leaves_assignment_unchanged(
    test_db, handover_confirmed, roles_reviewed, error_text
):
    org_id = _create_org(test_db)
    old_bu = create_business_unit({"name": "EcoCash"})
    new_bu = create_business_unit({"name": "Omni"})
    actor_id = _create_user(test_db, org_id, "org_admin", old_bu)
    user_id = _create_user(test_db, org_id, "moving_user", old_bu)

    with pytest.raises(BusinessUnitTransferError, match=error_text):
        transfer_user_business_unit(
            user_id,
            new_bu,
            org_id,
            actor_id,
            "Internal move from EcoCash to Omni",
            handover_confirmed=handover_confirmed,
            roles_reviewed=roles_reviewed,
        )

    assert test_db.execute(
        "SELECT business_unit_id FROM users WHERE id=%s", (user_id,)
    ).fetchone()["business_unit_id"] == old_bu
    assert test_db.execute(
        "SELECT COUNT(*) FROM business_unit_transfers"
    ).fetchone()[0] == 0


def test_transfer_rejects_cross_organization_target(test_db):
    org_a = _create_org(test_db, "transfer-org-a")
    org_b = _create_org(test_db, "transfer-org-b")
    old_bu = create_business_unit({"name": "EcoCash"})
    new_bu = create_business_unit({"name": "Omni"})
    actor_id = _create_user(test_db, org_a, "org_admin", old_bu)
    user_id = _create_user(test_db, org_b, "other_org_user", old_bu)

    with pytest.raises(BusinessUnitTransferError, match="organization"):
        transfer_user_business_unit(
            user_id,
            new_bu,
            org_a,
            actor_id,
            "Attempted cross organization move",
            handover_confirmed=True,
            roles_reviewed=True,
        )

    assert test_db.execute(
        "SELECT business_unit_id FROM users WHERE id=%s", (user_id,)
    ).fetchone()["business_unit_id"] == old_bu


def test_transfer_rejects_inactive_or_same_destination(test_db):
    org_id = _create_org(test_db)
    old_bu = create_business_unit({"name": "EcoCash"})
    inactive_bu = create_business_unit({"name": "Dormant SBU"})
    test_db.execute(
        "UPDATE business_units SET is_active=0 WHERE id=%s", (inactive_bu,)
    )
    test_db.commit()
    actor_id = _create_user(test_db, org_id, "org_admin", old_bu)
    user_id = _create_user(test_db, org_id, "moving_user", old_bu)

    with pytest.raises(BusinessUnitTransferError, match="already assigned"):
        preview_user_business_unit_transfer(user_id, old_bu, org_id)
    with pytest.raises(BusinessUnitTransferError, match="inactive"):
        preview_user_business_unit_transfer(user_id, inactive_bu, org_id)
