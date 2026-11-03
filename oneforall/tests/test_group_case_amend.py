"""Group cases (plan 22, C4): the position can be amended and a closed case reopened, with the history kept."""
import json

import pytest
from fastapi import HTTPException

from modules.evidence import group_cases as cases
from modules.evidence import group_requests as requests
from tests.test_group_documents import _activate, _actor, _future, group_world  # noqa: F401 (fixture)


def _closed_case(db, parent, child, users):
    relation = _activate(db, parent, child, users)
    request_id = requests.create_request(db, users["viewer"], relation, "GROUP-REQ-9", "Need proof", _future(7))
    case_id = cases.create_case(db, users["viewer"], "CASE-9", "Proof review", "The first position.")
    cases.link_request(db, users["viewer"], case_id, request_id)
    db.execute("UPDATE group_evidence_requests SET status='no_proof' WHERE id=%s", (request_id,))
    db.commit()
    closer = _actor(db, parent, "case_closer", "compliance_manager")
    assert cases.close_case(db, closer, case_id, "No proof exists for this claim yet") == "closed_with_gaps"
    db.commit()
    return case_id, closer


def test_the_position_is_amended_with_the_earlier_text_kept(group_world):
    db, parent, child, sibling, users, _ = group_world
    _activate(db, parent, child, users)
    case_id = cases.create_case(db, users["viewer"], "CASE-8", "Position review", "The first position.")
    db.commit()
    with pytest.raises(HTTPException) as no_reason:
        cases.amend_position(db, users["viewer"], case_id, "A revised position.", "")
    assert no_reason.value.status_code == 422
    with pytest.raises(HTTPException) as same:
        cases.amend_position(db, users["viewer"], case_id, "The first position.", "Nothing changed really")
    assert same.value.status_code == 409
    with pytest.raises(HTTPException) as foreign:
        cases.amend_position(db, users["sibling"], case_id, "Not theirs to change.", "Trying from outside")
    assert foreign.value.status_code == 404
    with pytest.raises(HTTPException) as child_side:
        cases.amend_position(db, users["publisher"], case_id, "Not theirs to change.", "Trying from the child")
    assert child_side.value.status_code == 404
    cases.amend_position(db, users["viewer"], case_id, "A revised position.", "New facts from the review")
    db.commit()
    detail = cases.case_detail(db, users["viewer"], case_id)
    assert detail["case"]["position"] == "A revised position."
    amended = [json.loads(e["detail"]) for e in detail["events"] if e["action"] == "position_amended"]
    assert amended == [{"previous": "The first position.", "reason": "New facts from the review"}]


def test_a_closed_case_is_reopened_by_someone_else_and_cannot_be_amended_while_closed(group_world):
    db, parent, child, sibling, users, _ = group_world
    case_id, closer = _closed_case(db, parent, child, users)
    with pytest.raises(HTTPException) as closed:
        cases.amend_position(db, users["viewer"], case_id, "Changed after closing.", "Too late for this")
    assert closed.value.status_code == 409
    with pytest.raises(HTTPException) as own:
        cases.reopen_case(db, closer, case_id, "I closed it too early")
    assert own.value.status_code == 409
    with pytest.raises(HTTPException) as manager_only:
        cases.reopen_case(db, users["viewer"], case_id, "A manager cannot reopen")
    assert manager_only.value.status_code == 403
    reopener = _actor(db, parent, "case_reopener", "audit_lead")
    assert cases.case_detail(db, reopener, case_id)["can_reopen"] is True
    assert cases.case_detail(db, closer, case_id)["can_reopen"] is False
    cases.reopen_case(db, reopener, case_id, "New proof arrived from the subsidiary")
    db.commit()
    detail = cases.case_detail(db, reopener, case_id)
    assert detail["case"]["status"] == "open" and detail["case"]["close_reason"] is None
    reopened = json.loads(next(e["detail"] for e in detail["events"] if e["action"] == "reopened"))
    assert (reopened["previous_status"], reopened["previous_conclusion"]) == (
        "closed_with_gaps", "No proof exists for this claim yet")
    with pytest.raises(HTTPException) as again:
        cases.reopen_case(db, reopener, case_id, "Reopening an open case")
    assert again.value.status_code == 409
    assert cases.close_case(db, closer, case_id, "Still no proof after the follow up") == "closed_with_gaps"
