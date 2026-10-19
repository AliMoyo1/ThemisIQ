"""Uploading to a claim is one scoped action; version history reveals only visible files."""
import asyncio
import json

import pytest
from fastapi import HTTPException

import modules.evidence.routes as ev
from tests.test_evidence_library import _upload, lib  # noqa: F401
from tests.test_evidence_vault_reads import _req, auth  # noqa: F401


def test_guided_upload_creates_a_pending_link_in_the_claims_unit(lib, auth, tmp_path, monkeypatch):
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setattr(ev, "EVIDENCE_DIR", evidence_dir)
    risk = lib.risk("Access risk", lib.unit_a)
    status, body = _upload(auth, lib.people.unit_a, b"scope proof", link_module="erm",
                           link_entity_type="risk", link_entity_id=str(risk))
    assert status == 201
    assert body["link"]["review_status"] == "pending"
    row = lib.db.execute("SELECT business_unit_id FROM evidence_items WHERE id=%s", (body["id"],)).fetchone()
    assert row["business_unit_id"] == lib.unit_a
    [link] = lib.db.execute("SELECT module,entity_type,entity_id,review_status FROM evidence_links WHERE evidence_id=%s",
                            (body["id"],)).fetchall()
    assert (link["module"], link["entity_type"], link["entity_id"], link["review_status"] or "pending") == (
        "erm", "risk", risk, "pending")
    assert len(list(evidence_dir.iterdir())) == 1


def test_hidden_or_incomplete_target_is_refused_before_bytes_are_written(lib, auth, tmp_path, monkeypatch):
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setattr(ev, "EVIDENCE_DIR", evidence_dir)
    hidden = lib.risk("Hidden risk", lib.unit_b)
    with pytest.raises(HTTPException) as error:
        _upload(auth, lib.people.unit_a, b"no file", link_module="erm",
                link_entity_type="risk", link_entity_id=str(hidden))
    assert error.value.status_code == 404 and "Hidden risk" not in str(error.value.detail)
    status, _ = _upload(auth, lib.people.unit_a, b"no file", link_module="erm")
    assert status == 422
    assert lib.db.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0] == 0
    assert not evidence_dir.exists()


def test_failed_link_write_rolls_back_file_and_item(lib, auth, tmp_path, monkeypatch):
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setattr(ev, "EVIDENCE_DIR", evidence_dir)
    risk = lib.risk("Available risk", lib.unit_a)
    original = ev.insert_returning_id

    def fail_link(db, statement, params):
        if statement.lstrip().startswith("INSERT INTO evidence_links"):
            raise RuntimeError("link write failed")
        return original(db, statement, params)

    monkeypatch.setattr(ev, "insert_returning_id", fail_link)
    with pytest.raises(RuntimeError, match="link write failed"):
        _upload(auth, lib.people.unit_a, b"failed file", link_module="erm",
                link_entity_type="risk", link_entity_id=str(risk))
    assert lib.db.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0] == 0
    assert not list(evidence_dir.iterdir())


def test_replacement_requires_a_visible_current_version(lib, auth, tmp_path, monkeypatch):
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setattr(ev, "EVIDENCE_DIR", evidence_dir)
    hidden = lib.item("Hidden old version", unit=lib.unit_b)
    superseded = lib.item("Replaced old version", status="superseded", unit=lib.unit_a)
    status, _ = _upload(auth, lib.people.unit_a, b"new file", replace_id="not-an-id")
    assert status == 422
    with pytest.raises(HTTPException) as error:
        _upload(auth, lib.people.unit_a, b"new file", replace_id=str(hidden))
    assert error.value.status_code == 404
    status, _ = _upload(auth, lib.people.unit_a, b"new file", replace_id=str(superseded))
    assert status == 409
    assert lib.db.execute("SELECT COUNT(*) FROM evidence_items").fetchone()[0] == 2
    assert not evidence_dir.exists()


def test_selected_claim_on_a_new_version_is_not_linked_twice(lib, auth, tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "EVIDENCE_DIR", tmp_path / "evidence")
    risk = lib.risk("Continuity risk", lib.unit_a)
    old = lib.item("Old report", unit=lib.unit_a)
    lib.link(old, risk, status="accepted")
    status, body = _upload(auth, lib.people.unit_a, b"revised report", replace_id=str(old),
                           link_module="erm", link_entity_type="risk", link_entity_id=str(risk))
    assert status == 201 and body["impact"]["carried"] == 1
    links = lib.db.execute("SELECT id, review_status FROM evidence_links WHERE evidence_id=%s", (body["id"],)).fetchall()
    assert len(links) == 1
    assert links[0]["id"] == body["link"]["id"]
    assert (links[0]["review_status"] or "pending") == "pending"


def test_versions_exclude_hidden_descendants_and_parent_ids(lib, auth):
    root = lib.item("Visible root", status="superseded", unit=lib.unit_a, version=1)
    lib.item("Hidden child", unit=lib.unit_b, version=2, parent_id=root)
    response = asyncio.run(ev.api_evidence_versions(_req(auth, lib.people.unit_a), root))
    body = json.loads(response.body)
    assert [row["title"] for row in body["versions"]] == ["Visible root"]
    assert "Hidden child" not in json.dumps(body)


def test_versions_do_not_walk_through_a_hidden_ancestor(lib, auth):
    hidden = lib.item("Hidden root", unit=lib.unit_b)
    child = lib.item("Visible child", unit=lib.unit_a, version=2, parent_id=hidden)
    lib.item("Hidden sibling", unit=lib.unit_b, version=2, parent_id=hidden)
    response = asyncio.run(ev.api_evidence_versions(_req(auth, lib.people.unit_a), child))
    body = json.loads(response.body)
    assert [row["title"] for row in body["versions"]] == ["Visible child"]
    assert "Hidden root" not in json.dumps(body)
    assert "parent_id" not in json.dumps(body)
