"""
Tests for PLAN-27: ERM Objectives Registry + Pillars Admin.

Covers the objective hierarchy rules (strategic parents only, strategic
roots only), standard_ref requirement, archive/deactivate guards while
still referenced, risk linkage validation (objective_id + risk_context),
and the joined objective/strategic-objective titles on get_enterprise_risk.

Uses the standard conftest test_db fixture (fresh SQLite per test).
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_objective_hierarchy_rules(test_db):
    """A standard objective may point at a strategic parent; it may not
    point at another standard objective. A strategic objective may never
    have a parent at all."""
    from modules.erm.data_service import create_objective

    strategic_id = create_objective({"title": "Grow ARR", "obj_type": "strategic"})
    assert strategic_id > 0

    standard_id = create_objective({
        "title": "ISMS: protect customer data", "obj_type": "standard",
        "standard_ref": "ISO 27001", "parent_id": strategic_id,
    })
    assert standard_id > 0

    with pytest.raises(ValueError):
        create_objective({
            "title": "Bad standard parent", "obj_type": "standard",
            "standard_ref": "ISO 9001", "parent_id": standard_id,
        })

    with pytest.raises(ValueError):
        create_objective({
            "title": "Bad strategic parent", "obj_type": "strategic", "parent_id": strategic_id,
        })


def test_standard_requires_standard_ref(test_db):
    """obj_type='standard' without a standard_ref raises ValueError."""
    from modules.erm.data_service import create_objective

    with pytest.raises(ValueError):
        create_objective({"title": "No ref", "obj_type": "standard"})


def test_archive_blocked_while_linked(test_db):
    """Archiving an objective still referenced by a risk's objective_id
    raises ValueError; archiving succeeds once the risk is unlinked."""
    from modules.erm.data_service import (
        create_objective, archive_objective, create_enterprise_risk, update_enterprise_risk,
    )

    oid = create_objective({"title": "Grow ARR", "obj_type": "strategic"})
    rid = create_enterprise_risk({
        "title": "Linked Risk", "likelihood": 3, "impact": 3, "objective_id": oid,
    })

    with pytest.raises(ValueError):
        archive_objective(oid)

    update_enterprise_risk(rid, {"objective_id": None})
    archive_objective(oid)


def test_risk_objective_and_context_validation(test_db):
    """A risk create with a valid objective_id + risk_context persists
    both; a bogus objective_id or an unknown risk_context raises."""
    from modules.erm.data_service import create_objective, create_enterprise_risk, get_enterprise_risk

    oid = create_objective({"title": "Grow ARR", "obj_type": "strategic"})
    rid = create_enterprise_risk({
        "title": "Contextual Risk", "likelihood": 3, "impact": 3,
        "objective_id": oid, "risk_context": "strategic",
    })
    risk = get_enterprise_risk(rid)
    assert risk["objective_id"] == oid
    assert risk["risk_context"] == "strategic"

    with pytest.raises(ValueError):
        create_enterprise_risk({"title": "Bogus obj", "likelihood": 3, "impact": 3, "objective_id": 999999})

    with pytest.raises(ValueError):
        create_enterprise_risk({"title": "Bogus context", "likelihood": 3, "impact": 3, "risk_context": "nonsense"})


def test_get_enterprise_risk_objective_titles(test_db):
    """get_enterprise_risk returns objective_title and, when the linked
    objective itself supports a strategic one, strategic_objective_title.
    A risk linked directly to a strategic objective has no support chain."""
    from modules.erm.data_service import create_objective, create_enterprise_risk, get_enterprise_risk

    strategic_id = create_objective({"title": "Grow ARR", "obj_type": "strategic"})
    standard_id = create_objective({
        "title": "ISMS: protect customer data", "obj_type": "standard",
        "standard_ref": "ISO 27001", "parent_id": strategic_id,
    })
    rid = create_enterprise_risk({
        "title": "Chain Risk", "likelihood": 3, "impact": 3, "objective_id": standard_id,
    })
    risk = get_enterprise_risk(rid)
    assert risk["objective_title"] == "ISMS: protect customer data"
    assert risk["strategic_objective_title"] == "Grow ARR"

    rid2 = create_enterprise_risk({
        "title": "Direct Strategic Risk", "likelihood": 3, "impact": 3, "objective_id": strategic_id,
    })
    risk2 = get_enterprise_risk(rid2)
    assert risk2["objective_title"] == "Grow ARR"
    assert risk2["strategic_objective_title"] is None


def test_pillar_deactivate_blocked_while_referenced(test_db):
    """Deactivating a pillar still referenced by a risk's impacted_pillar
    (a TEXT snapshot, not an FK) raises ValueError; deactivation succeeds
    once no risk carries that pillar name."""
    from modules.erm.data_service import (
        create_pillar, deactivate_pillar, create_enterprise_risk, update_enterprise_risk,
    )

    pid = create_pillar({"name": "PLAN27 Test Pillar"})
    rid = create_enterprise_risk({
        "title": "Pillar Risk", "likelihood": 3, "impact": 3,
        "impacted_pillar": "PLAN27 Test Pillar",
    })

    with pytest.raises(ValueError):
        deactivate_pillar(pid)

    update_enterprise_risk(rid, {"impacted_pillar": None})
    deactivate_pillar(pid)
