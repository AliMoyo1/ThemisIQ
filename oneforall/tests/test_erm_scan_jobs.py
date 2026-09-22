"""Regression coverage for durable, non-blocking ERM horizon scans."""
import asyncio
import json
import os
import sys
from contextlib import contextmanager
from types import SimpleNamespace


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _create_org(db, slug: str) -> int:
    from database import insert_returning_id

    org_id = insert_returning_id(
        db,
        "INSERT INTO organizations (name, slug, status) VALUES (%s,%s,'active')",
        (slug.title(), slug),
    )
    db.commit()
    return org_id


def test_active_job_is_deduplicated_and_terminal_job_releases_slot(test_db, monkeypatch):
    from modules.erm import ai_service, scan_jobs

    org_id = _create_org(test_db, "queue-org")
    first, created = scan_jobs.enqueue_scan(org_id, requested_by=None)
    duplicate, duplicate_created = scan_jobs.enqueue_scan(org_id, requested_by=None)

    assert created is True
    assert duplicate_created is False
    assert duplicate["id"] == first["id"]

    monkeypatch.setattr(
        ai_service,
        "run_emerging_scan",
        lambda: {"created": 3, "grounded": True},
    )
    result = scan_jobs.process_next_job(org_id)
    assert result == {
        "job_id": first["id"],
        "state": "completed",
        "created": 3,
        "grounded": True,
    }

    completed = scan_jobs.get_job(first["id"], org_id)
    assert completed["state"] == "completed"
    assert completed["active_slot"] is None
    assert scan_jobs.public_job(completed)["grounded"] is True

    second, second_created = scan_jobs.enqueue_scan(org_id, requested_by=None)
    assert second_created is True
    assert second["id"] != first["id"]


def test_failed_job_is_sanitized_and_releases_slot(test_db, monkeypatch):
    from modules.erm import ai_service, scan_jobs

    org_id = _create_org(test_db, "failure-org")
    job, _ = scan_jobs.enqueue_scan(org_id, requested_by=None)
    monkeypatch.setattr(
        ai_service,
        "run_emerging_scan",
        lambda: {"created": 0, "grounded": False, "error": "provider_internal_detail"},
    )

    result = scan_jobs.process_next_job(org_id)
    assert result == {"job_id": job["id"], "state": "failed"}

    failed = scan_jobs.get_job(job["id"], org_id)
    public = scan_jobs.public_job(failed)
    assert failed["active_slot"] is None
    assert public["error_code"] == "scan_failed"
    assert "provider_internal_detail" not in public["error"]

    _, created = scan_jobs.enqueue_scan(org_id, requested_by=None)
    assert created is True


def test_public_failed_job_never_exposes_persisted_error_details():
    from modules.erm import scan_jobs

    public = scan_jobs.public_job({
        "id": 99,
        "state": "failed",
        "error_code": "raw_provider_failure",
        "error_message": "secret upstream response body",
    })

    assert public["error_code"] == "scan_failed"
    assert public["error"] == (
        "The emerging-risk scan could not be completed. Please retry later."
    )
    assert "secret" not in public["error"]


def test_job_lookup_is_scoped_by_organization(test_db):
    from modules.erm import scan_jobs

    first_org = _create_org(test_db, "first-org")
    second_org = _create_org(test_db, "second-org")
    job, _ = scan_jobs.enqueue_scan(first_org, requested_by=None)

    assert scan_jobs.get_job(job["id"], first_org) is not None
    assert scan_jobs.get_job(job["id"], second_org) is None


def test_expired_lease_is_reclaimed_then_terminalised_after_retry_limit(test_db):
    from modules.erm import scan_jobs

    org_id = _create_org(test_db, "recovery-org")
    queued, _ = scan_jobs.enqueue_scan(org_id, requested_by=None)
    first_claim = scan_jobs.claim_next_job(org_id)
    assert first_claim["id"] == queued["id"]
    assert first_claim["attempts"] == 1

    test_db.execute(
        "UPDATE erm_emerging_scan_jobs SET lease_until=%s WHERE id=%s",
        ("2000-01-01T00:00:00+00:00", queued["id"]),
    )
    test_db.commit()
    second_claim = scan_jobs.claim_next_job(org_id)
    assert second_claim["id"] == queued["id"]
    assert second_claim["attempts"] == 2
    assert second_claim["lease_token"] != first_claim["lease_token"]

    test_db.execute(
        "UPDATE erm_emerging_scan_jobs SET lease_until=%s WHERE id=%s",
        ("2000-01-01T00:00:00+00:00", queued["id"]),
    )
    test_db.commit()
    assert scan_jobs.claim_next_job(org_id) is None
    failed = scan_jobs.get_job(queued["id"], org_id)
    assert failed["state"] == "failed"
    assert failed["active_slot"] is None
    assert failed["error_code"] == "worker_abandoned"


def test_stale_worker_cannot_overwrite_current_lease_owner(test_db):
    from modules.erm import scan_jobs

    org_id = _create_org(test_db, "lease-owner-org")
    queued, _ = scan_jobs.enqueue_scan(org_id, requested_by=None)
    stale_claim = scan_jobs.claim_next_job(org_id)

    test_db.execute(
        "UPDATE erm_emerging_scan_jobs SET lease_until=%s WHERE id=%s",
        ("2000-01-01T00:00:00+00:00", queued["id"]),
    )
    test_db.commit()
    current_claim = scan_jobs.claim_next_job(org_id)

    assert current_claim["lease_token"] != stale_claim["lease_token"]
    assert scan_jobs._complete(stale_claim, {"created": 99, "grounded": True}) is False

    still_running = scan_jobs.get_job(queued["id"], org_id)
    assert still_running["state"] == "running"
    assert still_running["lease_token"] == current_claim["lease_token"]
    assert scan_jobs._complete(current_claim, {"created": 1, "grounded": True}) is True


def test_scan_route_returns_202_without_calling_ai(monkeypatch):
    from modules.erm import routes

    job = {
        "id": 41,
        "state": "pending",
        "created_at": "2026-09-22T19:00:00+00:00",
        "started_at": None,
        "completed_at": None,
    }
    recorded = []
    monkeypatch.setattr(routes, "check_ai_rate_limit", lambda _uid: True)
    monkeypatch.setattr(routes, "record_ai_call", lambda uid: recorded.append(uid))
    monkeypatch.setattr(routes.scan_jobs, "enqueue_scan", lambda org_id, requested_by: (job, True))
    monkeypatch.setattr(
        routes.ai,
        "run_emerging_scan",
        lambda: (_ for _ in ()).throw(AssertionError("AI work ran in request path")),
    )
    request = SimpleNamespace(state=SimpleNamespace(user={"id": 7, "org_id": 9}))

    response = asyncio.run(routes.api_emerging_scan.__wrapped__(request))
    body = json.loads(response.body)

    assert response.status_code == 202
    assert body["job_id"] == 41
    assert body["state"] == "pending"
    assert body["reused"] is False
    assert recorded == ["7"]


def test_scan_status_route_uses_current_organization_and_public_contract(monkeypatch):
    from modules.erm import routes

    lookups = []
    monkeypatch.setattr(
        routes.scan_jobs,
        "get_job",
        lambda job_id, org_id: (
            lookups.append((job_id, org_id))
            or {
                "id": job_id,
                "org_id": org_id,
                "state": "failed",
                "error_code": "provider_trace",
                "error_message": "upstream stack trace",
            }
        ),
    )
    request = SimpleNamespace(state=SimpleNamespace(user={"id": 7, "org_id": 23}))

    response = asyncio.run(routes.api_emerging_scan_status.__wrapped__(request, 41))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert lookups == [(41, 23)]
    assert body["job_id"] == 41
    assert body["state"] == "failed"
    assert body["error_code"] == "scan_failed"
    assert "trace" not in body["error"]


def test_weekly_scheduler_enqueues_every_active_tenant(monkeypatch):
    from modules.erm import scheduler

    seen_contexts = []
    queued = []

    @contextmanager
    def fake_tenant_context(org_id, slug):
        seen_contexts.append((org_id, slug))
        yield

    monkeypatch.setattr(scheduler, "list_active_tenants", lambda: [(1, "alpha"), (2, "beta")])
    monkeypatch.setattr(scheduler, "tenant_context", fake_tenant_context)
    monkeypatch.setattr(
        scheduler.scan_jobs,
        "enqueue_scan",
        lambda org_id, requested_by: (queued.append((org_id, requested_by)) or {"id": org_id}, True),
    )

    scheduler._enqueue_weekly_scans()

    assert seen_contexts == [(1, "alpha"), (2, "beta")]
    assert queued == [(1, None), (2, None)]


def test_queue_drain_rebinds_tenant_context_and_processes_one_job(monkeypatch):
    from modules.erm import scheduler

    seen_contexts = []
    processed = []

    @contextmanager
    def fake_tenant_context(org_id, slug):
        seen_contexts.append((org_id, slug))
        yield

    monkeypatch.setattr(
        scheduler,
        "list_active_tenants",
        lambda: [(1, "empty"), (2, "queued"), (3, "not-reached")],
    )
    monkeypatch.setattr(scheduler, "tenant_context", fake_tenant_context)

    def fake_process(org_id):
        processed.append(org_id)
        if org_id == 2:
            return {"job_id": 17, "state": "completed", "created": 1, "grounded": True}
        return None

    monkeypatch.setattr(scheduler.scan_jobs, "process_next_job", fake_process)

    scheduler._drain_scan_queue()

    assert seen_contexts == [(1, "empty"), (2, "queued")]
    assert processed == [1, 2]
