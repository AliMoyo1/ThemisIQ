"""Creating or editing a canonical vendor needs a vendor-manage capability.

POST /api/vendors/directory only required a sign-in, so any role (an employee included) could add a
vendor to the shared directory or overwrite the contact details, services and risk level of one that
already existed. It now needs the capability the owning module requires to manage its own vendors:
sentinel.vendor.manage, grid.vendor.manage or bcm.vendor.manage. Reading the directory is unchanged
(and limited per module by tests/test_vendor_profile_scope.py).
"""
import asyncio
import json
import types

import pytest
from fastapi import HTTPException

import core.middleware as middleware
import modules.launcher.routes_vendors as vendor_routes
from core import rbac

# Written from core/rbac.py: sentinel.vendor.manage = super admin + DPO, grid.vendor.manage = super admin +
# audit lead, bcm.vendor.manage = super admin + BCM manager.
ALLOWED = [rbac.SUPER_ADMIN, rbac.DPO, rbac.AUDIT_LEAD, rbac.BCM_MANAGER]
DENIED = [rbac.EMPLOYEE, rbac.COMPLIANCE_MGR, rbac.RISK_OWNER, rbac.PRIVACY_ANALYST, rbac.GRC_OFFICER]


def _user(role):
    return {"id": 1, "username": role, "org_id": None, "business_unit_id": None,
            "is_super_admin": 1 if role == rbac.SUPER_ADMIN else 0, "roles": [role]}


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    async def current_user(request):
        return request.state.user

    monkeypatch.setattr(middleware, "get_current_user", current_user)


def _create(role, body):
    request = types.SimpleNamespace(state=types.SimpleNamespace(user=_user(role)),
                                    url=types.SimpleNamespace(path="/api/vendors/directory"), query_params={})

    async def _json():
        return body

    request.json = _json
    response = asyncio.run(vendor_routes.api_vendor_directory_create(request))
    return response.status_code, json.loads(response.body)


def _vendor(db, name):
    return db.execute("SELECT * FROM canonical_vendors WHERE name = %s", (name,)).fetchone()


@pytest.mark.parametrize("role", ALLOWED)
def test_vendor_managers_can_add_to_the_directory(test_db, role):
    status, body = _create(role, {"name": "Acme Cloud", "contact_email": "ops@acme.example"})
    assert status == 201 and body["vendor"]["contact_email"] == "ops@acme.example"


@pytest.mark.parametrize("role", DENIED)
def test_other_roles_cannot_add_or_overwrite_a_vendor(test_db, role):
    test_db.execute("INSERT INTO canonical_vendors (name, contact_email) VALUES ('Acme Cloud', 'ops@acme.example')")
    test_db.commit()
    with pytest.raises(HTTPException) as refused:
        _create(role, {"name": "Acme Cloud", "contact_email": "attacker@evil.example", "risk_level": "low"})
    assert refused.value.status_code == 403
    assert _vendor(test_db, "Acme Cloud")["contact_email"] == "ops@acme.example"
    with pytest.raises(HTTPException):
        _create(role, {"name": "A brand new vendor"})
    assert _vendor(test_db, "A brand new vendor") is None


@pytest.mark.parametrize("role, shown", [(rbac.DPO, True), (rbac.SUPER_ADMIN, True), (rbac.EMPLOYEE, False),
                                          (rbac.COMPLIANCE_MGR, False)])
def test_the_add_button_is_only_offered_to_roles_that_can_use_it(monkeypatch, role, shown):
    seen = {}
    monkeypatch.setattr(vendor_routes, "shell_ctx", lambda request, **kw: {})
    monkeypatch.setattr(vendor_routes.shell_templates, "TemplateResponse",
                        lambda request, name, ctx: seen.update(ctx))
    request = types.SimpleNamespace(state=types.SimpleNamespace(user=_user(role)),
                                    url=types.SimpleNamespace(path="/vendors"), query_params={})
    asyncio.run(vendor_routes.vendor_directory_page(request))
    assert seen["can_add_vendor"] is shown
