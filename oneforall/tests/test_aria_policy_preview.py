"""
PLAN-35 T05: spool protocol tests (app side) and worker unit tests.

A real LibreOffice conversion is NOT exercised here -- no converter binary
is available in this environment. Every test mocks the single convert()
call site in the worker module rather than the LibreOffice subprocess
itself, so the protocol (submit, claim, timeout, failure, cleanup) is
proven correctly independent of having a real converter installed. The
real-converter acceptance test (T05's actual pass condition: "one real
branded DOCX renders to PDF using the configured converter") remains an
explicit open item requiring a real LibreOffice install, tracked in the
plan's execution ledger, not simulated here.
"""
import subprocess

import pytest

from modules.aria import policy_preview as pp
import scripts.aria_policy_preview_worker as worker


@pytest.fixture(autouse=True)
def _isolated_spool(tmp_path, monkeypatch):
    monkeypatch.setattr(pp.settings, "ARIA_POLICY_PREVIEW_SPOOL_DIR", str(tmp_path))
    monkeypatch.setattr(worker, "SPOOL_DIR", tmp_path)
    monkeypatch.setattr(worker, "LOCK_PATH", tmp_path / ".worker.lock")
    yield tmp_path


@pytest.fixture
def mock_convert(monkeypatch):
    """Replace the worker's single LibreOffice call site with a
    controllable fake. Tests set .behavior to change what happens."""
    state = {"behavior": "success"}

    def fake_convert(input_docx, output_dir, executable=None, timeout_seconds=None):
        if state["behavior"] == "success":
            out = output_dir / (input_docx.stem + ".pdf")
            out.write_bytes(b"%PDF-FAKE")
            return out
        if state["behavior"] == "timeout":
            raise subprocess.TimeoutExpired(cmd=["soffice"], timeout=1)
        if state["behavior"] == "process_error":
            raise subprocess.CalledProcessError(1, ["soffice"], stderr=b"font missing")
        if state["behavior"] == "no_output":
            return output_dir / "nonexistent.pdf"  # convert() itself would raise for this; simulate directly
        raise RuntimeError("unexpected test behavior")

    monkeypatch.setattr(worker, "convert", fake_convert)
    return state


# ─────────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────────

def test_full_round_trip_submit_claim_convert_poll(mock_convert):
    job_id = pp.submit_conversion_job(b"FAKE DOCX BYTES", timeout_seconds=30)
    processed = worker.run_once()
    assert processed == 1

    pdf_bytes = pp.poll_conversion_result(job_id, timeout_seconds=5, poll_interval=0.05)
    assert pdf_bytes == b"%PDF-FAKE"


def test_cleanup_removes_both_inbox_and_outbox_traces(mock_convert):
    job_id = pp.submit_conversion_job(b"X", timeout_seconds=30)
    worker.run_once()
    pp.poll_conversion_result(job_id, timeout_seconds=5, poll_interval=0.05)

    pp.cleanup_job(job_id)
    assert not (pp._spool_dir() / "inbox" / job_id).exists()
    assert not (pp._spool_dir() / "outbox" / job_id).exists()


# ─────────────────────────────────────────────────────────────────────────
# Failure injection
# ─────────────────────────────────────────────────────────────────────────

def test_converter_timeout_reported_as_preview_timeout(mock_convert):
    mock_convert["behavior"] = "timeout"
    job_id = pp.submit_conversion_job(b"X", timeout_seconds=30)
    worker.run_once()
    with pytest.raises(pp.ConversionFailedError) as exc_info:
        pp.poll_conversion_result(job_id, timeout_seconds=5, poll_interval=0.05)
    assert exc_info.value.error_code == "PREVIEW_TIMEOUT"


def test_converter_process_error_reported_as_preview_unavailable(mock_convert):
    mock_convert["behavior"] = "process_error"
    job_id = pp.submit_conversion_job(b"X", timeout_seconds=30)
    worker.run_once()
    with pytest.raises(pp.ConversionFailedError) as exc_info:
        pp.poll_conversion_result(job_id, timeout_seconds=5, poll_interval=0.05)
    assert exc_info.value.error_code == "PREVIEW_UNAVAILABLE"
    assert "font missing" in exc_info.value.message


def test_app_side_timeout_when_worker_never_runs():
    """No worker.run_once() call at all -- simulates the converter being
    completely unavailable/down."""
    job_id = pp.submit_conversion_job(b"X", timeout_seconds=1)
    with pytest.raises(pp.ConversionTimeoutError):
        pp.poll_conversion_result(job_id, timeout_seconds=1, poll_interval=0.1)


def test_expired_job_is_refused_by_the_worker_not_converted(mock_convert):
    """A job whose deadline already passed before the worker got to it
    must not be converted at all -- proves the worker checks the deadline
    itself rather than trusting the app's poll timeout alone."""
    job_id = pp.submit_conversion_job(b"X", timeout_seconds=-5)  # already expired
    called = {"count": 0}
    def counting_convert(*a, **k):
        called["count"] += 1
        raise AssertionError("must not be called for an already-expired job")
    worker.convert = counting_convert

    worker.run_once()
    assert called["count"] == 0
    with pytest.raises(pp.ConversionFailedError) as exc_info:
        pp.poll_conversion_result(job_id, timeout_seconds=5, poll_interval=0.05)
    assert exc_info.value.error_code == "PREVIEW_TIMEOUT"


def test_missing_manifest_reported_not_crashed(tmp_path):
    job_dir = tmp_path / "inbox" / "badjob"
    job_dir.mkdir(parents=True)
    (job_dir / "input.docx").write_bytes(b"x")
    # No manifest.json written at all.
    worker.process_one_job(job_dir)
    import json
    result = json.loads((job_dir / "result.json").read_text())
    assert result["ok"] is False
    assert result["error_code"] == "PREVIEW_UNAVAILABLE"


def test_missing_input_file_reported_not_crashed(tmp_path):
    import json, time
    job_dir = tmp_path / "inbox" / "badjob2"
    job_dir.mkdir(parents=True)
    (job_dir / "manifest.json").write_text(json.dumps({"deadline": time.time() + 100}))
    # No input.docx written.
    worker.process_one_job(job_dir)
    result = json.loads((job_dir / "result.json").read_text())
    assert result["ok"] is False


# ─────────────────────────────────────────────────────────────────────────
# Concurrency: two workers cannot claim the same job
# ─────────────────────────────────────────────────────────────────────────

def test_two_claim_attempts_only_one_wins(mock_convert):
    job_id = pp.submit_conversion_job(b"X", timeout_seconds=30)
    inbox_job_dir = pp._spool_dir() / "inbox" / job_id
    outbox = pp._spool_dir() / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)

    first = worker._claim_job(inbox_job_dir, outbox)
    second = worker._claim_job(inbox_job_dir, outbox)  # dir no longer exists at old path
    assert first is not None
    assert second is None


def test_singleton_lock_prevents_a_second_worker_instance(tmp_path):
    worker._acquire_singleton_lock()
    try:
        with pytest.raises(worker.WorkerAlreadyRunningError):
            worker._acquire_singleton_lock()
    finally:
        worker._release_singleton_lock()
    # Lock released: acquiring again must now succeed.
    worker._acquire_singleton_lock()
    worker._release_singleton_lock()
