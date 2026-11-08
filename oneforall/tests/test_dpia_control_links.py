"""Guessed DPIA mitigations must not masquerade as reviewed controls."""

from core import event_handlers
from modules.governance import relationships
from tests.test_relationships import graph, _insert, _ref, DPIA  # noqa: F401
from tests.test_platform_ownership import world  # noqa: F401
from tests.test_platform_ownership import _request, signed_in  # noqa: F401
from tests.test_report_assurance_signoff import _response
from fastapi import HTTPException
import pytest


def test_completion_event_never_confirms_keyword_control_matches(monkeypatch):
    class FakeDB:
        def execute(self, sql, params=()):
            class Result:
                def fetchall(self):
                    return [(42,)]
            return Result()

        def commit(self):
            pass

        def close(self):
            pass

    calls = []
    monkeypatch.setattr(event_handlers, "get_db", lambda: FakeDB())
    monkeypatch.setattr(event_handlers, "create_cross_module_link", lambda *a, **k: calls.append((a, k)))
    event_handlers.dpia_links_to_aria_controls(
        "sentinel.dpia.completed", "sentinel", "dpia", 1,
        {"data_categories": "personal"}, 2,
    )
    assert calls == []


def test_unreviewed_legacy_guesses_are_candidates_but_human_links_remain(graph):
    from modules.governance.dpia_controls import quarantine_legacy_guesses

    db = graph.db
    dpia = _ref(graph, DPIA, "A")
    control_id = _insert(db, "controls", framework_id=_insert(db, "frameworks", name="Test framework"),
                         ref="T1", name="Personal data")
    guess = _insert(db, "cross_module_links", source_module="sentinel", source_type="dpia", source_id=dpia[2],
                    target_module="aria", target_type="control", target_id=control_id,
                    relationship="mitigates", provenance="system", status="confirmed")
    human = _insert(db, "cross_module_links", source_module="sentinel", source_type="dpia", source_id=dpia[2],
                    target_module="aria", target_type="control", target_id=control_id + 1,
                    relationship="mitigates", provenance="manual", status="confirmed",
                    confirmed_by=graph.users["super"]["id"])
    assert quarantine_legacy_guesses(db) == 1
    assert quarantine_legacy_guesses(db) == 0
    quarantined = db.execute("SELECT status,target_type FROM cross_module_links WHERE id=%s", (guess,)).fetchone()
    assert (quarantined["status"], quarantined["target_type"]) == ("candidate", "legacy_control")
    assert db.execute("SELECT status FROM cross_module_links WHERE id=%s", (human,)).fetchone()[0] == "confirmed"
    from modules.governance.dpia_controls import suggestions
    assert suggestions(db, graph.users["dpo_a"], dpia[2]) == [], "matching numeric IDs cannot identify a current control"


def test_dpia_control_suggestions_respect_ownership_and_visible_links(graph):
    from modules.governance.dpia_controls import suggestions

    db = graph.db
    a = _ref(graph, DPIA, "A")
    b = _ref(graph, DPIA, "B")
    framework = _insert(db, "frameworks", name="Test framework")
    control = _insert(db, "controls", framework_id=framework, ref="T1", name="Control A")
    _insert(db, "cross_module_links", source_module="sentinel", source_type="dpia", source_id=a[2],
            target_module="aria", target_type="control", target_id=control,
            relationship="mitigates", provenance="system_candidate", status="candidate")
    dpo_a = graph.users["dpo_a"]
    assert [item["control_id"] for item in suggestions(db, dpo_a, a[2])] == [control]
    assert suggestions(db, dpo_a, b[2]) == []
    assert relationships.list_links(db, dpo_a, DPIA, a[2]) == []


def test_specialist_accepts_or_dismisses_visible_suggestions_only(graph, monkeypatch):
    from modules.sentinel import routes
    db = graph.db
    a = _ref(graph, DPIA, "A")
    b = _ref(graph, DPIA, "B")
    framework = _insert(db, "frameworks", name="Test framework")
    c1 = _insert(db, "controls", framework_id=framework, ref="T1", name="First control")
    c2 = _insert(db, "controls", framework_id=framework, ref="T2", name="Second control")
    for control in (c1, c2):
        _insert(db, "cross_module_links", source_module="sentinel", source_type="dpia", source_id=a[2],
                target_module="aria", target_type="control", target_id=control,
                relationship="mitigates", provenance="system_candidate", status="candidate")
    db.commit()

    class SharedDB:
        def __getattr__(self, name):
            return getattr(db, name)

        def close(self):
            pass

    monkeypatch.setattr(routes, "get_db", lambda: SharedDB())
    monkeypatch.setattr(relationships, "audit", lambda *args: None)
    dpo = graph.users["dpo_a"]
    assert _response(routes.api_dpia_control_decision(_request(dpo, payload={"action": "accept"}), a[2], c1)).status_code == 200
    assert _response(routes.api_dpia_control_decision(_request(dpo, payload={"action": "dismiss"}), a[2], c2)).status_code == 200
    assert [l["entity_id"] for l in relationships.list_links(db, dpo, DPIA, a[2])] == [c1]
    assert __import__("modules.governance.dpia_controls", fromlist=["suggestions"]).suggestions(db, dpo, a[2]) == []
    with pytest.raises(HTTPException) as hidden:
        _response(routes.api_dpia_control_suggestions(_request(graph.users["dpo_b"]), a[2]))
    assert hidden.value.status_code == 404
    with pytest.raises(HTTPException) as hidden:
        _response(routes.api_dpia_control_decision(_request(dpo, payload={"action": "accept"}), b[2], c1))
    assert hidden.value.status_code == 404
