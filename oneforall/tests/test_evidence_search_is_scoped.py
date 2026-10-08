"""Evidence search must use the shared scope helper (design/evidence-vault/PHASE-1A.md, T7).

Before Phase 1a the org and business unit rule was copied into the Vault list, topbar search and the
GRID and BCM pickers, and the copies drifted. A function that searches evidence_items by title,
description or filename with LIKE must call evidence_scope_sql, or this test fails. Lookups by an
internal marker in tags (mirroring sync code) are not searches and are not flagged. It is a static
check on source text, not behavior.
"""
import ast
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKIP_DIRS = {".venv", "__pycache__", ".pytest_cache", ".git", "node_modules", "tests"}
_HELPER = "evidence_scope_sql"
# "path:function" entries allowed to search evidence_items without the helper, each with a reason.
_ALLOWED: dict = {}


def unscoped_evidence_searches(source: str) -> list:
    """Names of functions that LIKE-search evidence_items text columns without calling evidence_scope_sql."""
    tree = ast.parse(source)
    offenders = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        docstrings = {id(n.value) for n in ast.walk(func) if isinstance(n, ast.Expr)}
        sql = " ".join(
            n.value for n in ast.walk(func)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
        ).lower()
        called = {n.id for n in ast.walk(func) if isinstance(n, ast.Name)}
        text_search = re.search(r"\b(?:title|description|file_name)\s+like\b", sql)
        if "evidence_items" in sql and text_search and _HELPER not in called:
            offenders.append(func.name)
    return offenders


def test_scanner_flags_an_unscoped_search_and_accepts_a_scoped_one():
    bad = "def f(db, q):\n    return db.execute('SELECT id FROM evidence_items WHERE title LIKE %s', (q,))\n"
    good = (
        "def f(db, user, q):\n    s, p = evidence_scope_sql(user)\n"
        "    return db.execute('SELECT id FROM evidence_items e WHERE e.title LIKE %s AND ' + s, (q, *p))\n"
    )
    unrelated = "def f(db):\n    return db.execute('SELECT id FROM controls WHERE name LIKE %s')\n"
    docstring_only = 'def f():\n    """Searches evidence_items where title LIKE x."""\n    return 1\n'
    marker_lookup = "def f(db, m):\n    return db.execute('SELECT id FROM evidence_items WHERE tags LIKE %s', (m,))\n"
    aliased = "def f(db, q):\n    return db.execute('SELECT e.id FROM evidence_items e WHERE e.title LIKE %s', (q,))\n"
    assert unscoped_evidence_searches(bad) == ["f"]
    assert unscoped_evidence_searches(aliased) == ["f"]
    assert unscoped_evidence_searches(good) == []
    assert unscoped_evidence_searches(unrelated) == []
    assert unscoped_evidence_searches(docstring_only) == []
    assert unscoped_evidence_searches(marker_lookup) == []


def test_no_function_searches_evidence_without_the_shared_scope_helper():
    offenders = []
    for dirpath, dirnames, filenames in os.walk(_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding="utf-8") as f:
                    source = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            if "evidence_items" not in source:
                continue
            rel = os.path.relpath(path, _ROOT).replace(os.sep, "/")
            for func in unscoped_evidence_searches(source):
                if f"{rel}:{func}" not in _ALLOWED:
                    offenders.append(f"{rel}:{func}")
    assert not offenders, (
        "These functions LIKE-search evidence_items without evidence_scope_sql "
        "(modules/evidence/scope.py):\n" + "\n".join(offenders)
    )
