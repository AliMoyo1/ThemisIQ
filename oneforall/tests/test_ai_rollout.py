"""
AI governance rollout switch: whether an organization is shown AI Governance.

A switch for what is shown, not a guard of what is allowed: an organization with no stored choice follows the platform
default (off unless the deployment sets it), a stored choice wins, a value that cannot be read falls back to the default
instead of failing the page, and a platform administrator with no organization always sees it.
"""
import pytest

from config import settings
from core import ai_rollout


@pytest.fixture
def platform_default(monkeypatch):
    def set_default(value):
        monkeypatch.setattr(settings, "AI_GOVERNANCE_DEFAULT_ENABLED", value)
        ai_rollout.clear_cache()
    return set_default


def test_an_organization_with_no_choice_follows_the_platform_default(test_db, platform_default):
    platform_default(False)
    assert ai_rollout.is_enabled(7) is False and ai_rollout.is_set(7) is False
    platform_default(True)
    assert ai_rollout.is_enabled(7) is True


def test_a_stored_choice_wins_over_the_default_in_both_directions(test_db, platform_default):
    platform_default(False)
    ai_rollout.set_enabled(7, True)
    assert ai_rollout.is_enabled(7) is True and ai_rollout.is_set(7) is True
    assert ai_rollout.is_enabled(8) is False, "another organization is not affected"
    platform_default(True)
    ai_rollout.set_enabled(7, False)
    ai_rollout.clear_cache()
    assert ai_rollout.is_enabled(7) is False, "read back from the store, not only from the cache"
    row = test_db.execute("SELECT value FROM settings WHERE key = 'ai_governance.enabled.org7'").fetchone()
    assert row["value"] == "0"


def test_a_platform_administrator_with_no_organization_always_sees_it(test_db, platform_default):
    platform_default(False)
    assert ai_rollout.is_enabled(None) is True


def test_a_choice_that_cannot_be_read_falls_back_to_the_default(test_db, platform_default, monkeypatch):
    platform_default(False)

    def broken():
        raise RuntimeError("database is down")

    monkeypatch.setattr(ai_rollout, "get_db_background", broken)
    assert ai_rollout.is_enabled(9) is False
    platform_default(True)
    assert ai_rollout.is_enabled(9) is True


def test_the_answer_is_remembered_briefly_and_a_fresh_read_goes_to_the_store(test_db, platform_default):
    platform_default(False)
    assert ai_rollout.is_enabled(5) is False
    test_db.execute("INSERT INTO settings (key, value) VALUES ('ai_governance.enabled.org5', '1')")
    test_db.commit()
    assert ai_rollout.is_enabled(5) is False, "still the remembered answer"
    assert ai_rollout.is_enabled(5, fresh=True) is True
    assert ai_rollout.is_enabled(5) is True
