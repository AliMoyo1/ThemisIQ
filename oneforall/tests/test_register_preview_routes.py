"""Preview reads only the same scoped builder used by a frozen register run."""
import asyncio
import json

from modules.launcher import routes_reports as reports
from tests.test_platform_ownership import _request, signed_in, world  # noqa: F401


def _preview(user, **query):
    response = asyncio.run(reports.api_register_preview(_request(user, query)))
    return response.status_code, json.loads(response.body)


def test_register_preview_requires_a_valid_selection_and_masks_denied_records(world):
    admin = world.users["super"]
    assert _preview(admin, report_type="framework_auditor_register", framework_id="none")[0] == 400
    assert _preview(admin, report_type="unknown")[0] == 400
    missing = _preview(admin, report_type="framework_auditor_register", framework_id="999999")
    assert missing[0] == 404 and missing[1]["error"] == "Not found"
    good = _preview(admin, report_type="ai_systems_register")
    assert good[0] == 200 and good[1]["counts"]["systems"] == 0
    assert "sections" not in good[1], "Preview returns counts and gaps, not an unbounded raw record dump"
