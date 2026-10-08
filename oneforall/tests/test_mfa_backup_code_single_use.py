"""A backup code works exactly once, even when two requests present it at the same moment.

verify_code read the stored list of hashed codes, checked the presented code against it, and wrote
the list back without that code. Two requests that read the list before either wrote both passed the
check and both logged in. The write now only succeeds if the stored list is still the one that was
read (compare and set), so the second request is refused.
"""
import pytest

import core.mfa as mfa


@pytest.fixture
def enrolled(test_db):
    test_db.execute("INSERT INTO users (id, username, email, full_name, password_hash) "
                    "VALUES (1, 'mfa_user', 'm@example.test', 'M', 'x')")
    test_db.commit()
    _secret, codes = mfa.start_enrollment(1)
    test_db.execute("UPDATE user_mfa SET is_enabled = 1 WHERE user_id = 1")
    test_db.commit()
    return codes


def _stored(db):
    import json
    return json.loads(db.execute("SELECT backup_codes FROM user_mfa WHERE user_id = 1").fetchone()[0])


def test_a_backup_code_works_once_and_other_codes_keep_working(test_db, enrolled):
    first, second = enrolled[0], enrolled[1]
    assert mfa.verify_code(1, first) is True
    assert mfa.verify_code(1, first) is False, "a used code is gone"
    assert len(_stored(test_db)) == len(enrolled) - 1
    assert mfa.verify_code(1, second) is True


def test_two_requests_with_the_same_code_cannot_both_succeed(test_db, enrolled, monkeypatch):
    """Interleave the second request between the first one's check and its write."""
    code = enrolled[0]
    real_checkpw = mfa.bcrypt.checkpw
    competing = []

    def checkpw(plain, hashed):
        ok = real_checkpw(plain, hashed)
        if ok and not competing:
            competing.append(True)  # the other request gets all the way through first
            assert mfa.verify_code(1, code) is True
        return ok

    monkeypatch.setattr(mfa.bcrypt, "checkpw", checkpw)
    assert mfa.verify_code(1, code) is False, "the code was already spent by the request that won"
    assert len(_stored(test_db)) == len(enrolled) - 1, "it was removed once, not twice"
