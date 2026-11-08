"""Stored framework colors must stay inert in every framework view."""

import asyncio
import json
from types import SimpleNamespace

from core.framework_service import get_framework, list_frameworks, safe_framework_color
import core.middleware as middleware
import modules.aria.routes as aria


def test_framework_color_accepts_only_six_digit_hex():
    assert safe_framework_color("#a1B2c3") == "#a1B2c3"
    for value in (None, 42, "red", "#123", "#112233;url(https://example.invalid)"):
        assert safe_framework_color(value) == "#1E3A5F"


def test_legacy_framework_color_is_safe_in_service_and_aria_views(test_db, monkeypatch):
    unsafe = "#112233; background:url(https://example.invalid/track)"
    cur = test_db.execute(
        "INSERT INTO frameworks (name, color, is_active) VALUES (%s, %s, 1)",
        ("Stored color regression", unsafe),
    )
    fw_id = cur.lastrowid
    test_db.execute(
        "INSERT INTO controls (framework_id, ref, name) VALUES (%s, %s, %s)",
        (fw_id, "SC-1", "One control"),
    )
    test_db.commit()

    assert get_framework(fw_id)["color"] == "#1E3A5F"
    assert next(fw for fw in list_frameworks() if fw["id"] == fw_id)["color"] == "#1E3A5F"

    contexts = []
    monkeypatch.setattr(aria, "_aria_render", lambda request, template, ctx, **kw: contexts.append(ctx))
    user = {"id": 1, "org_id": None, "is_super_admin": True, "roles": ["super_admin"]}

    async def current_user(request):
        return user

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    request = SimpleNamespace(
        state=SimpleNamespace(user=user),
        url=SimpleNamespace(path="/aria/"),
        query_params={},
    )
    asyncio.run(aria.aria_dashboard(request))
    assert next(fw for fw in contexts[-1]["fw_stats"] if fw["id"] == fw_id)["color"] == "#1E3A5F"
    asyncio.run(aria.frameworks_list(request))
    assert next(fw for fw in contexts[-1]["fw_list"] if fw["id"] == fw_id)["color"] == "#1E3A5F"
    asyncio.run(aria.framework_detail(request, fw_id))
    assert contexts[-1]["fw"]["color"] == "#1E3A5F"

    response = asyncio.run(aria.api_frameworks_list(request))
    assert next(fw for fw in json.loads(response.body)["items"] if fw["id"] == fw_id)["color"] == "#1E3A5F"
