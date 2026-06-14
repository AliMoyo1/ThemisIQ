"""
Auth primitive tests.

Password hashing is the easiest piece to silently break (wrong cost, wrong
algorithm, salt reuse) so it gets a dedicated regression test.
"""
import pytest

from core.auth import hash_password, verify_password


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
