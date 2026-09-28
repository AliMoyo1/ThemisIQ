"""
Schema/quality gate for tests/ui/action_registry.json (PLAN-36 T00).

Pure static checks -- no app, no browser, no database. Runs in the default
`pytest tests -q` gate so a badly-formed registry entry fails fast, long
before anyone tries to write a browser test against it.
"""
import json
import os

import pytest

_REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ui", "action_registry.json"
)

_VALID_CLASSIFICATIONS = {"mutation", "read_only"}
_VALID_DESTRUCTIVE_POLICIES = {
    "safe_idempotent_read",
    "safe_isolated_crud",
    "no_auto_destructive",
    "manual_only",
}
_REQUIRED_STRING_FIELDS = ["id", "module", "route", "selector", "label"]


def _load_registry() -> dict:
    with open(_REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)


def _actions() -> list:
    return _load_registry()["actions"]


def test_registry_file_is_valid_json_with_actions():
    data = _load_registry()
    assert isinstance(data.get("actions"), list)
    assert len(data["actions"]) > 0


def test_action_ids_are_unique():
    ids = [a.get("id") for a in _actions()]
    duplicates = {i for i in ids if ids.count(i) > 1}
    assert not duplicates, f"duplicate action id(s) in action_registry.json: {sorted(duplicates)}"


@pytest.mark.parametrize("action", _actions(), ids=lambda a: a.get("id", "<no-id>"))
def test_action_has_required_string_fields(action):
    missing = [f for f in _REQUIRED_STRING_FIELDS if not (action.get(f) or "").strip()]
    assert not missing, f"{action.get('id', '<no-id>')} is missing/blank: {missing}"


@pytest.mark.parametrize("action", _actions(), ids=lambda a: a.get("id", "<no-id>"))
def test_action_has_backend_method_and_path(action):
    backend = action.get("backend")
    assert isinstance(backend, dict), f"{action['id']}: 'backend' must be an object"
    assert (backend.get("method") or "").strip(), f"{action['id']}: backend.method is required"
    assert (backend.get("path") or "").strip(), f"{action['id']}: backend.path is required"


@pytest.mark.parametrize("action", _actions(), ids=lambda a: a.get("id", "<no-id>"))
def test_action_classification_is_valid(action):
    assert action.get("classification") in _VALID_CLASSIFICATIONS, (
        f"{action['id']}: classification must be one of {sorted(_VALID_CLASSIFICATIONS)}, "
        f"got {action.get('classification')!r}"
    )


@pytest.mark.parametrize("action", _actions(), ids=lambda a: a.get("id", "<no-id>"))
def test_action_destructive_test_policy_is_valid(action):
    assert action.get("destructive_test_policy") in _VALID_DESTRUCTIVE_POLICIES, (
        f"{action['id']}: destructive_test_policy must be one of "
        f"{sorted(_VALID_DESTRUCTIVE_POLICIES)}, got {action.get('destructive_test_policy')!r}"
    )


@pytest.mark.parametrize(
    "action",
    [a for a in _actions() if a.get("classification") == "mutation"],
    ids=lambda a: a.get("id", "<no-id>"),
)
def test_mutation_actions_declare_a_failure_expectation(action):
    """A mutation with no documented failure UI is exactly how F08-style
    silent failures reach production undetected -- refuse to register one."""
    assert (action.get("expected_failure_ui") or "").strip(), (
        f"{action['id']} is a mutation action but declares no expected_failure_ui"
    )


@pytest.mark.parametrize("action", _actions(), ids=lambda a: a.get("id", "<no-id>"))
def test_action_declares_personas(action):
    personas = action.get("personas")
    assert isinstance(personas, list) and len(personas) > 0, (
        f"{action['id']}: 'personas' must be a non-empty list"
    )
