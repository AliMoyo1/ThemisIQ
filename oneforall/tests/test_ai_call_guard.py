"""
AI governance G1c guard: no model call bypasses the organization's AI policy.

The policy lives at one place, core/ai_client.py (see core/ai_policy.py). These checks read the source so a new call
site cannot be added without a registered feature, and a second path to a provider cannot appear beside the client.
"""
import ast
import pathlib
import re

import pytest

from core.ai_policy import CATEGORIES, FEATURES, PROVIDERS, UNLABELLED

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIRS = {"tests", ".venv", "__pycache__", "scripts", "seeds", "static", "templates", "node_modules"}
CLIENT = pathlib.Path("core/ai_client.py")
ENTRY_POINTS = {"create_message", "create_message_full", "create_message_web_search"}
# Thin helpers around the client that take the caller's feature and forward it; their callers are checked as well.
HELPERS = {("modules/grid/ai_service.py", "_call_ai"), ("modules/aria/ai_generator.py", "_call_ai"),
           ("modules/sentinel/ai_service.py", "call_ai")}
HELPER_NAMES = {name for _, name in HELPERS}


def _app_files():
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if set(rel.parts) & SKIP_DIRS:
            continue
        yield rel, path


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


class _Sites(ast.NodeVisitor):
    """Every call of the client or a helper, and every function that reaches one through asyncio.to_thread."""

    def __init__(self):
        self.stack, self.sites = [], []

    def _fn(self, node):
        self.stack.append(node)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _fn

    def visit_Call(self, node):
        called = _name(node.func)
        if called == "to_thread" and node.args:
            called = _name(node.args[0])
        if called in ENTRY_POINTS | HELPER_NAMES:
            self.sites.append((node, called, self.stack[-1].name if self.stack else "<module>"))
        self.generic_visit(node)


def _sites():
    found = []
    for rel, path in _app_files():
        if rel == CLIENT:
            continue
        text = path.read_text(encoding="utf-8-sig")
        if "create_message" not in text and "call_ai" not in text:
            continue
        finder = _Sites()
        finder.visit(ast.parse(text))
        found += [(rel.as_posix(), node, called, fn) for node, called, fn in finder.sites]
    return found


SITES = _sites()


def test_the_scan_finds_the_call_sites_it_is_meant_to_police():
    assert len(SITES) >= 50, "the source scan found too few model calls; the guard would pass vacuously"
    assert {rel.split("/")[1] for rel, *_ in SITES if rel.startswith("modules/")} >= {
        "aria", "bcm", "erm", "grid", "orm", "sentinel", "evidence", "governance", "launcher"}


@pytest.mark.parametrize("rel, node, called, fn", SITES, ids=[f"{r}:{n.lineno}" for r, n, *_ in SITES])
def test_every_model_call_names_a_registered_feature(rel, node, called, fn):
    given = [k.value for k in node.keywords if k.arg == "feature"]
    assert given, f"{rel}:{node.lineno} calls {called}() without feature="
    value = given[0]
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        assert value.value in FEATURES, f"{rel}:{node.lineno}: {value.value!r} is not in core.ai_policy.FEATURES"
    else:  # a helper hands on the feature it was given
        assert isinstance(value, ast.Name) and value.id == "feature" and (rel, fn) in HELPERS, (
            f"{rel}:{node.lineno}: feature must be a registered string, not an expression")


def test_every_registered_feature_is_used_and_declares_what_it_sends():
    used = {k.value.value for _, node, *_ in SITES for k in node.keywords
            if k.arg == "feature" and isinstance(k.value, ast.Constant)}
    assert set(FEATURES) == used, f"unused: {sorted(set(FEATURES) - used)}, unregistered: {sorted(used - set(FEATURES))}"
    for feature, (label, categories) in FEATURES.items():
        assert re.fullmatch(r"[a-z]+\.[a-z0-9_]+", feature), feature
        assert label and categories and set(categories) <= set(CATEGORIES), feature
    assert UNLABELLED not in CATEGORIES, "an unlabelled call must never be satisfiable by ticking a category"


def test_the_helpers_require_the_feature_so_a_new_caller_cannot_forget_it():
    for rel, name in HELPERS:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8-sig"))
        helper = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
        required = [a.arg for a, d in zip(helper.args.kwonlyargs, helper.args.kw_defaults) if d is None]
        assert "feature" in required, f"{rel}:{name} must take a required keyword-only feature"


def test_no_provider_is_reached_except_through_the_client():
    hosts = re.compile(r"api\.anthropic\.com|api\.openai\.com|openrouter\.ai|generativelanguage\.googleapis\.com|"
                       r"api\.deepseek\.com|api\.mistral\.ai|api\.cohere|api\.groq\.com|api\.together\.xyz")
    sdks = re.compile(r"^\s*(import|from)\s+(anthropic|openai|google\.generativeai|google\.genai|cohere|mistralai|groq|"
                      r"together|litellm|langchain\w*)\b", re.M)
    offenders = []
    for rel, path in _app_files():
        if rel == CLIENT:
            continue
        text = path.read_text(encoding="utf-8-sig")
        if hosts.search(text) or sdks.search(text):
            offenders.append(rel.as_posix())
    assert not offenders, f"these files talk to a model provider outside core/ai_client.py: {offenders}"


def test_the_client_reaches_a_provider_only_through_the_policy_check():
    tree = ast.parse((ROOT / CLIENT).read_text(encoding="utf-8-sig"))
    callers: dict = {}
    for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef)):
        for call in (c for c in ast.walk(fn) if isinstance(c, ast.Call)):
            callers.setdefault(_name(call.func), set()).add(fn.name)

    # The public entry points go through _guarded (directly or via _dispatch), and _guarded asks the policy first.
    assert callers["_dispatch"] == {"create_message", "create_message_full"}
    assert callers["_guarded"] == {"_dispatch", "create_message_web_search"}
    assert "_guarded" in callers and "authorize" in callers and callers["authorize"] == {"_guarded"}
    # Each function that reaches a provider has exactly the callers that sit inside the guarded paths.
    assert callers["_dispatch_to_provider"] == {"_dispatch"}
    assert callers["_web_search_to_provider"] == {"create_message_web_search"}
    assert callers["_anthropic"] == callers["_gemini"] == {"_dispatch_to_provider"}
    assert callers["_openai_compat"] == {"_dispatch_to_provider"}
    assert callers["_openrouter_web_search"] == {"_web_search_to_provider"}
    assert callers["_post_with_connect_retry"] == {"_openai_compat", "_openrouter_web_search"}


def test_every_provider_the_policy_can_name_has_a_model_in_the_client():
    import core.ai_client as client
    for provider in PROVIDERS:
        assert client._model_for_provider(provider)
