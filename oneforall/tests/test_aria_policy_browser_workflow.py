"""Browser-state regression coverage for the ARIA authoring workflow."""

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_aria_policy_workflow_browser_state_machine():
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "js" / "aria_policy_workflow.test.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_workflow_asset_version_is_bumped_on_every_page_that_loads_it():
    expected = '/static/js/aria_policy_workflow.js?v=4'
    for relative_path in (
        "modules/aria/templates/ai_generator.html",
        "modules/aria/templates/documents.html",
    ):
        template = (ROOT / relative_path).read_text(encoding="utf-8")
        assert expected in template
        assert '/static/js/aria_policy_workflow.js?v=3' not in template
