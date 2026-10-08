"""No code may catch a broad exception around a database call and carry on without a trace.

A swallowed database error looked like "no data": a dashboard widget showing zero, an integrity
alert that was never sent, an audit-log filter returning nothing. Worse, on PostgreSQL the connection
wrapper rolls the whole transaction back when a statement fails, so carrying on silently also
discards everything written before it. A handler that tolerates the failure must say so
(core.best_effort.swallowed, or any logger call), roll back, or re-raise.

database.py is exempt: its migrations deliberately run "add this column" statements that fail when
the column already exists. main.py's one startup migration is listed by name.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
BROAD = {"Exception", "BaseException"}
LOG_CALLS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "swallowed"}
DB_CALLS = {"execute", "executemany", "executescript"}
EXEMPT_FILES = {"database.py"}
# (file, enclosing function): reviewed and deliberately silent
ALLOWED = {("main.py", "startup")}


def _broad(handler):
    t = handler.type
    if t is None:
        return True
    names = {n.id if isinstance(n, ast.Name) else getattr(n, "attr", "") for n in
             (t.elts if isinstance(t, ast.Tuple) else [t])}
    return bool(names & BROAD)


def _calls(nodes):
    for n in nodes:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Call):
                f = sub.func
                yield f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def _enclosing_function(tree, target):
    best = ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= target.lineno <= (node.end_lineno or node.lineno):
                best = node.name
    return best


def _files():
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        top = rel.parts[0]
        if top in {"tests", "seeds", "scripts", "__pycache__"} or ".venv" in rel.parts:
            continue
        if rel.name in EXEMPT_FILES and len(rel.parts) == 1:
            continue
        yield path, str(rel).replace("\\", "/")


def test_every_swallowed_database_error_is_logged_rolled_back_or_re_raised():
    offenders = []
    for path, rel in _files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try) or not (set(_calls(node.body)) & DB_CALLS):
                continue
            for handler in node.handlers:
                if not _broad(handler):
                    continue
                if any(isinstance(sub, ast.Raise) for n in handler.body for sub in ast.walk(n)):
                    continue
                if set(_calls(handler.body)) & (LOG_CALLS | {"rollback"}):
                    continue
                if (rel, _enclosing_function(tree, handler)) in ALLOWED:
                    continue
                offenders.append(f"{rel}:{handler.lineno}")
    assert not offenders, (
        "These handlers swallow a database error without logging it (use core.best_effort.swallowed, "
        "log, roll back, or re-raise):\n  " + "\n  ".join(offenders)
    )
