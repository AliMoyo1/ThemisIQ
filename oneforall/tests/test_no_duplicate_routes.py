"""No two routes may answer the same method and path.

Starlette serves a request with the FIRST matching route, so a second definition of the same method and
path is silently dead code. That is how a legacy POST /api/links in routes_frameworks.py, registered
before the validated, scope-checked, audited one in routes_platform.py, answered every request for
months while the good handler never ran (linking two records that do not exist returned 201).
Handler-level tests cannot see it, because they call the function directly and skip the router.

The scan is static, so it does not depend on FastAPI internals: it reads every @router.get/post/...,
@app.get/..., and @x.api_route(path, methods=[...]) decorator, prefixes the path with the prefix the
file gives its APIRouter, and fails when two different handlers end up with the same method and path.
It does not judge routes that merely overlap (/items/{id} vs /items/bulk, a single-segment {page} vs the
{path:path} catch-all registered after it, {id:int} vs {name}): that is an ordering question, not a duplicate.
"""
import ast
import collections
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
SKIPPED_TOP_LEVEL = {"tests", "seeds", "scripts", "__pycache__"}


def _call_name(node):
    return node.id if isinstance(node, ast.Name) else getattr(node, "attr", "")


def _string(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _normalize(path: str) -> str:
    """Parameter names do not matter; the converter does: {x} is one segment, {x:path} is everything."""
    return re.sub(r"\{[^}:]*(?::([^}]*))?\}",
                  lambda m: "{" + ("*" if m.group(1) == "path" else "" if m.group(1) in (None, "str") else m.group(1)) + "}",
                  path)


def routes_in(source: str, label: str):
    """Yield (METHOD, normalized full path, 'file:line function') for every route decorator."""
    tree = ast.parse(source)
    prefixes = {}  # variable -> prefix, for `router = APIRouter(prefix="/x")` and `app = FastAPI()`
    for node in tree.body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and _call_name(node.value.func) in {"APIRouter", "FastAPI"}):
            prefix = next((_string(k.value) for k in node.value.keywords if k.arg == "prefix"), None) or ""
            for target in node.targets:
                if isinstance(target, ast.Name):
                    prefixes[target.id] = prefix
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in fn.decorator_list:
            if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                    and isinstance(deco.func.value, ast.Name) and deco.func.value.id in prefixes
                    and deco.args and _string(deco.args[0]) is not None):
                continue
            kind = deco.func.attr
            if kind in HTTP_METHODS:
                methods = [kind.upper()]
            elif kind == "api_route":
                listed = next((k.value for k in deco.keywords if k.arg == "methods"), None)
                methods = [_string(e).upper() for e in getattr(listed, "elts", []) if _string(e)] or ["GET"]
            else:
                continue
            path = _normalize(prefixes[deco.func.value.id] + _string(deco.args[0]))
            for method in methods:
                yield method, path, f"{label}:{fn.lineno} {fn.name}"


def find_duplicate_routes(sources: dict) -> list:
    seen = collections.defaultdict(list)
    for label, source in sources.items():
        for method, path, where in routes_in(source, label):
            seen[(method, path)].append(where)
    return [f"{method} {path}: " + "  AND  ".join(places)
            for (method, path), places in sorted(seen.items()) if len(places) > 1]


def test_the_application_defines_each_method_and_path_once():
    sources = {}
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in SKIPPED_TOP_LEVEL or ".venv" in rel.parts:
            continue
        sources[str(rel).replace("\\", "/")] = path.read_text(encoding="utf-8-sig")
    assert sources and any(label == "main.py" for label in sources), "the scan found no application files"
    assert not find_duplicate_routes(sources), (
        "These routes are declared twice; the later declaration never runs:\n  "
        + "\n  ".join(find_duplicate_routes(sources))
    )


# ── The scanner itself, on planted sources, so a green result above cannot be vacuous ──────────

def _module(prefix, *routes):
    head = f'router = APIRouter(prefix="{prefix}")\n' if prefix is not None else "router = APIRouter()\n"
    return head + "".join(f'@router.{m}("{p}")\nasync def {n}(): pass\n' for m, p, n in routes)


def test_the_same_method_and_path_in_two_files_is_found():
    found = find_duplicate_routes({
        "frameworks.py": _module(None, ("post", "/api/links", "legacy")),
        "platform.py": _module(None, ("post", "/api/links", "scoped")),
    })
    assert len(found) == 1 and "POST /api/links" in found[0]
    assert "frameworks.py" in found[0] and "platform.py" in found[0]


def test_parameter_names_do_not_hide_a_duplicate():
    found = find_duplicate_routes({
        "a.py": _module("/x", ("get", "/items/{item_id}", "one")),
        "b.py": _module("/x", ("get", "/items/{eid}", "two")),
    })
    assert len(found) == 1


def test_overlapping_but_different_routes_are_not_duplicates():
    assert find_duplicate_routes({
        "module.py": _module("/bcm", ("get", "/{page}", "page")),
        "main.py": _module(None, ("get", "/bcm/{path:path}", "fallback"), ("get", "/n/{id:int}", "num"),
                           ("get", "/n/{name}", "text")),
    }) == []


def test_different_prefixes_or_methods_are_not_duplicates():
    assert find_duplicate_routes({
        "aria.py": _module("/aria", ("get", "/", "aria_home")),
        "grid.py": _module("/grid", ("get", "/", "grid_home")),
        "both.py": _module(None, ("get", "/thing", "read"), ("post", "/thing", "write")),
    }) == []


def test_api_route_counts_every_method_it_lists():
    source = ('app = FastAPI()\n'
              '@app.api_route("/health", methods=["GET", "HEAD"])\nasync def health(): pass\n'
              '@app.head("/health")\nasync def health_head(): pass\n')
    found = find_duplicate_routes({"main.py": source})
    assert len(found) == 1 and found[0].startswith("HEAD /health")
