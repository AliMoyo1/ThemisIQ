"""
Auth primitive tests.

Password hashing is the easiest piece to silently break (wrong cost, wrong
algorithm, salt reuse) so it gets a dedicated regression test.
"""
import asyncio

import pytest
from fastapi import HTTPException

from core.auth import (
    authenticate_user,
    create_session,
    get_session_user,
    hash_password,
    verify_password,
)


def test_password_roundtrip():
    h = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", h) is True


def test_wrong_password_fails():
    h = hash_password("right-password")
    assert verify_password("wrong-password", h) is False


def test_hashes_are_salted_unique():
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b
    assert verify_password("same-password", a)
    assert verify_password("same-password", b)


@pytest.mark.parametrize("pw", ["", "a", "x" * 60, "пароль", "🔐emoji-key"])
def test_handles_edge_case_passwords(pw):
    # bcrypt silently truncates at 72 bytes — keep inputs under that to keep
    # the "different password fails" assertion meaningful.
    h = hash_password(pw)
    assert verify_password(pw, h) is True
    assert verify_password(pw + "x", h) is False


def test_inactive_organization_blocks_login_and_revokes_existing_session(test_db):
    password = "Correct-Horse-42"
    test_db.execute(
        "INSERT INTO organizations (name, slug, status) "
        "VALUES ('Suspension Test', 'suspension-test', 'active')"
    )
    org_id = test_db.execute(
        "SELECT id FROM organizations WHERE slug='suspension-test'"
    ).fetchone()["id"]
    test_db.execute(
        "INSERT INTO users (username, email, full_name, password_hash, org_id) "
        "VALUES ('suspended_user','suspended@example.com','Suspended User',%s,%s)",
        (hash_password(password), org_id),
    )
    test_db.commit()
    user_id = test_db.execute(
        "SELECT id FROM users WHERE username='suspended_user'"
    ).fetchone()["id"]

    assert authenticate_user("suspended_user", password) is not None
    token = create_session(user_id)
    assert get_session_user(token) is not None

    test_db.execute(
        "UPDATE organizations SET status='inactive' WHERE id=%s", (org_id,)
    )
    test_db.commit()

    assert authenticate_user("suspended_user", password) is None
    assert get_session_user(token) is None
    assert test_db.execute(
        "SELECT COUNT(*) FROM sessions WHERE user_id=%s", (user_id,)
    ).fetchone()[0] == 0


def test_inactive_organization_blocks_api_keys(test_db):
    from modules.launcher.routes_api_v1 import _authenticate_key, _hash_key

    raw_key = "ofa_test_suspended_org_key"
    test_db.execute(
        "INSERT INTO organizations (name, slug, status) "
        "VALUES ('API Suspension Test', 'api-suspension-test', 'inactive')"
    )
    org_id = test_db.execute(
        "SELECT id FROM organizations WHERE slug='api-suspension-test'"
    ).fetchone()["id"]
    test_db.execute(
        "INSERT INTO users (username, email, full_name, password_hash, org_id) "
        "VALUES ('api_key_owner','api-owner@example.com','API Owner','x',%s)",
        (org_id,),
    )
    owner_id = test_db.execute(
        "SELECT id FROM users WHERE username='api_key_owner'"
    ).fetchone()["id"]
    test_db.execute(
        "INSERT INTO api_keys "
        "(name, key_hash, key_prefix, scopes, created_by, org_id, is_active) "
        "VALUES ('Suspended key',%s,'ofa_test','read',%s,%s,1)",
        (_hash_key(raw_key), owner_id, org_id),
    )
    test_db.commit()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(_authenticate_key(raw_key, "read"))
    assert exc.value.status_code == 401
