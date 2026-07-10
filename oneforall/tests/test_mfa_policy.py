"""Regression: PLAN-18 Part A — org-enforced MFA policy logic.

Run from repo root: .venv/Scripts/python -m pytest tests/test_mfa_policy.py -q
"""
import os
import sys

os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-0123456789abcdef")
os.environ["DATABASE_URL"] = ""

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.mfa import mfa_required_for

ADMIN = {"roles": ["compliance_manager"]}
SUPER = {"roles": ["super_admin"]}
NONADMIN = {"roles": ["auditor"]}
NONE = None


def test_policy_off_never_required():
    assert mfa_required_for(ADMIN, "off") is False
    assert mfa_required_for(NONADMIN, "off") is False


def test_policy_all_always_required():
    assert mfa_required_for(ADMIN, "all") is True
    assert mfa_required_for(NONADMIN, "all") is True


def test_policy_admins_only_admin_roles():
    assert mfa_required_for(ADMIN, "admins") is True
    assert mfa_required_for(SUPER, "admins") is True
    assert mfa_required_for(NONADMIN, "admins") is False


def test_policy_unknown_fails_open():
    # Never lock out login on a misconfigured / unknown policy value.
    assert mfa_required_for(ADMIN, "wat") is False
    assert mfa_required_for(ADMIN, "") is False
    assert mfa_required_for(ADMIN, None) is False


def test_no_user_never_required():
    assert mfa_required_for(NONE, "all") is False
