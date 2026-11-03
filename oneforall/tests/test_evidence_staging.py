"""Durable batch staging (plan 22, C10): a staged file survives a reload, is filed through the ordinary upload checks,
a file that fails a check is quarantined without keeping its bytes, and nobody else sees another person's staged files."""
import asyncio
import io
import json

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

import modules.evidence.routes as ev
from modules.evidence import staging
from tests.test_evidence_library import lib  # noqa: F401 (fixture)
from tests.test_evidence_vault_reads import _req, auth  # noqa: F401 (fixture)


@pytest.fixture(autouse=True)
def _dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "EVIDENCE_DIR", tmp_path / "vault")
    monkeypatch.setattr(staging, "STAGING_DIR", tmp_path / "staging")
    return tmp_path


def _stage(auth, user, data, name="proof.txt", mime="text/plain", scope="organization"):
    file = UploadFile(file=io.BytesIO(data), size=len(data), filename=name, headers=Headers({"content-type": mime}))
    result = asyncio.run(ev.api_evidence_stage(_req(auth, user), file, scope))
    return json.loads(result.body)


def _file(auth, user, staged_id, title="Staged proof"):
    args = {"title": title, "description": "", "category": "general", "tags": "", "replace_id": "", "expiry_date": "",
            "owner_user_id": "", "review_due_date": "", "period_start": "", "period_end": "",
            "filing_scope": "organization", "staged_id": str(staged_id)}
    try:
        result = asyncio.run(ev.api_evidence_upload(_req(auth, user), None, **args))
    except HTTPException as error:
        return error.status_code, {"error": error.detail}
    return result.status_code, json.loads(result.body)


def _listed(auth, user):
    return json.loads(asyncio.run(ev.api_evidence_staged(_req(auth, user))).body)["items"]


def test_a_staged_file_waits_on_the_server_and_is_filed_through_the_upload_checks(lib, auth, _dirs):
    staged = _stage(auth, lib.people.uploader, b"annual access review")
    assert staged["status"] == "staged" and staged["file_size"] == 20
    assert [s["id"] for s in _listed(auth, lib.people.uploader)] == [staged["id"]], "it survives a reload"
    assert _listed(auth, lib.people.reviewer) == [] and _listed(auth, lib.people.elsewhere) == []
    stored = list((_dirs / "staging").iterdir())
    assert len(stored) == 1 and "proof" not in stored[0].name, "kept under a random name, outside the Vault"
    status, body = _file(auth, lib.people.reviewer, staged["id"])
    assert status == 404 or body.get("error"), "only the person who staged it can file it"
    status, body = _file(auth, lib.people.uploader, staged["id"])
    assert status == 201
    row = lib.db.execute("SELECT title, file_name, file_hash, org_id FROM evidence_items WHERE id=%s", (body["id"],)).fetchone()
    assert (row["title"], row["file_name"], row["org_id"]) == ("Staged proof", "proof.txt", lib.org1)
    assert row["file_hash"] == staged["file_hash"]
    assert _listed(auth, lib.people.uploader) == [] and not list((_dirs / "staging").iterdir())
    status, body = _file(auth, lib.people.uploader, staged["id"])
    assert status == 404 or "error" in body, "a staged file is filed once"


def test_a_file_that_fails_a_check_is_quarantined_without_its_bytes(lib, auth, _dirs):
    for name, mime, data, phrase in (("tool.exe", "application/octet-stream", b"MZ....", "not allowed"),
                                     ("page.txt", "text/html", b"<script>", "not permitted"),
                                     ("scan.pdf", "application/pdf", b"not a pdf at all", "does not match")):
        staged = _stage(auth, lib.people.uploader, data, name, mime)
        assert staged["status"] == "quarantined" and phrase in staged["reason"], name
        status, body = _file(auth, lib.people.uploader, staged["id"])
        assert status == 404 or "error" in body, "a quarantined file can never be filed"
    assert not (_dirs / "staging").exists() or not list((_dirs / "staging").iterdir())
    assert {s["status"] for s in _listed(auth, lib.people.uploader)} == {"quarantined"}


def test_staging_needs_an_authorized_scope_and_is_bounded(lib, auth, monkeypatch):
    with pytest.raises(HTTPException) as no_scope:
        _stage(auth, lib.people.uploader, b"x", scope="")
    assert no_scope.value.status_code == 422
    with pytest.raises(HTTPException) as foreign_unit:
        _stage(auth, lib.people.uploader, b"x", scope=f"unit:{lib.unit_b + 1000}")
    assert foreign_unit.value.status_code in (403, 404, 422)
    monkeypatch.setattr(staging, "MAX_STAGED", 2)
    _stage(auth, lib.people.uploader, b"one")
    _stage(auth, lib.people.uploader, b"two")
    with pytest.raises(HTTPException) as full:
        _stage(auth, lib.people.uploader, b"three")
    assert full.value.status_code == 409


def test_discard_and_expiry_remove_the_bytes(lib, auth, _dirs):
    first = _stage(auth, lib.people.uploader, b"discard me")
    second = _stage(auth, lib.people.uploader, b"let me expire")
    with pytest.raises(HTTPException) as foreign:
        asyncio.run(ev.api_evidence_staged_discard(_req(auth, lib.people.elsewhere), first["id"]))
    assert foreign.value.status_code == 404
    asyncio.run(ev.api_evidence_staged_discard(_req(auth, lib.people.uploader), first["id"]))
    lib.db.execute("UPDATE evidence_staging SET expires_at='2020-01-01T00:00:00' WHERE id=%s", (second["id"],))
    lib.db.commit()
    assert staging.sweep(lib.db) == 1
    lib.db.commit()
    assert _listed(auth, lib.people.uploader) == [] and not list((_dirs / "staging").iterdir())
    status, body = _file(auth, lib.people.uploader, second["id"])
    assert status == 404 or "error" in body


def test_the_upload_route_takes_a_file_or_a_staged_file_not_both_or_neither(lib, auth):
    status, body = _file(auth, lib.people.uploader, "")
    assert status == 422
    staged = _stage(auth, lib.people.uploader, b"report")
    file = UploadFile(file=io.BytesIO(b"x"), size=1, filename="x.txt", headers=Headers({"content-type": "text/plain"}))
    args = {"title": "Both", "description": "", "category": "general", "tags": "", "replace_id": "", "expiry_date": "",
            "owner_user_id": "", "review_due_date": "", "period_start": "", "period_end": "",
            "filing_scope": "organization", "staged_id": str(staged["id"])}
    result = asyncio.run(ev.api_evidence_upload(_req(auth, lib.people.uploader), file, **args))
    assert result.status_code == 422
