"""
PLAN-36 T04 (findings.md F05): erm_risks was renamed to erm_enterprise_risks
long ago. Several executable call sites never got updated and silently
referenced a table that has never existed, in ways ranging from "always 404s
this one AI suggestion" to "always skips this recovery drill check" to
"prints a harmless but confusing warning on every clean startup."

This is a static guard against the name creeping back in, not a functional
test -- it scans source text, not behavior.
"""
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STALE_NAME = re.compile(r"\berm_risks\b")

# Directories under oneforall/ never worth scanning: virtualenvs, caches,
# and this test's own future self (a real occurrence would legitimately
# appear in this file's docstring/pattern above, which must not self-flag).
_SKIP_DIR_NAMES = {".venv", "__pycache__", ".pytest_cache", ".git", ".mypy_cache", ".ruff_cache", "node_modules"}
_SELF = os.path.abspath(__file__)


def _python_files():
    for dirpath, dirnames, filenames in os.walk(_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            if os.path.abspath(path) == _SELF:
                continue
            yield path


def test_no_executable_reference_to_the_removed_erm_risks_table():
    offenders = []
    for path in _python_files():
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # explanatory comments about the historical name are fine
            if _STALE_NAME.search(line):
                offenders.append(f"{os.path.relpath(path, _ROOT)}:{lineno}: {stripped}")

    assert not offenders, (
        "erm_risks was renamed to erm_enterprise_risks; these executable lines "
        "still reference the removed name:\n" + "\n".join(offenders)
    )
