"""
PLAN-35 T05: spool protocol tests (app side) and worker unit tests.

The unit suite does not launch LibreOffice. Every test mocks the single
convert() call site in the worker module rather than the LibreOffice
subprocess itself, so the protocol (submit, claim, timeout, failure, cleanup)
is proven independently of the image-level conversion acceptance check.
"""
import subprocess

import pytest
from pypdf import PdfWriter
from pypdf.actions import JavaScript
from pypdf.generic import (
    ArrayObject,
    NameObject,
    NullObject,
    NumberObject,
    RectangleObject,
)

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
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            with out.open("wb") as stream:
                writer.write(stream)
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
    assert pdf_bytes.startswith(b"%PDF-")


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


def test_worker_rejects_a_converter_output_that_is_not_a_parseable_pdf(tmp_path, monkeypatch):
    import json, time

    job_dir = tmp_path / "outbox" / "invalid-pdf"
    job_dir.mkdir(parents=True)
    (job_dir / "input.docx").write_bytes(b"x")
    (job_dir / "manifest.json").write_text(
        json.dumps({"deadline": time.time() + 100}), encoding="utf-8"
    )

    def fake_convert(input_docx, output_dir, executable=None, timeout_seconds=None):
        output = output_dir / "input.pdf"
        output.write_bytes(b"%PDF-this-is-not-a-real-pdf")
        return output

    monkeypatch.setattr(worker, "convert", fake_convert)
    worker.process_one_job(job_dir)

    result = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["error_code"] == "PREVIEW_UNAVAILABLE"
    assert not (job_dir / "output.pdf").exists()


def test_worker_rejects_encrypted_pdf(tmp_path):
    path = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("secret")
    with path.open("wb") as stream:
        writer.write(stream)

    with pytest.raises(worker.PdfValidationError, match="[Ee]ncrypted"):
        worker._validate_pdf(path)


def test_worker_rejects_page_count_over_limit(tmp_path, monkeypatch):
    path = tmp_path / "two-pages.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as stream:
        writer.write(stream)
    monkeypatch.setattr(worker, "MAX_PDF_PAGES", 1)

    with pytest.raises(worker.PdfValidationError, match="page"):
        worker._validate_pdf(path)


def test_worker_rejects_active_pdf_content(tmp_path):
    path = tmp_path / "javascript.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_open_action(JavaScript("app.alert('no')"))
    with path.open("wb") as stream:
        writer.write(stream)

    with pytest.raises(worker.PdfValidationError, match="active content"):
        worker._validate_pdf(path)


def test_worker_allows_static_open_page_destination(tmp_path):
    path = tmp_path / "static-open-destination.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer._root_object[NameObject("/OpenAction")] = ArrayObject([
        writer.pages[0].indirect_reference,
        NameObject("/XYZ"),
        NullObject(),
        NullObject(),
        NumberObject(0),
    ])
    with path.open("wb") as stream:
        writer.write(stream)

    worker._validate_pdf(path)


def test_worker_rejects_external_uri_action(tmp_path):
    path = tmp_path / "external-uri.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_uri(0, "https://example.invalid", RectangleObject((0, 0, 10, 10)))
    with path.open("wb") as stream:
        writer.write(stream)

    with pytest.raises(worker.PdfValidationError, match="active content"):
        worker._validate_pdf(path)


def test_app_rejects_invalid_or_oversized_worker_output(monkeypatch):
    with pytest.raises(pp.ConversionFailedError, match="valid PDF signature"):
        pp._validate_received_pdf(b"not-a-pdf")

    monkeypatch.setattr(pp, "MAX_PREVIEW_PDF_BYTES", 8)
    with pytest.raises(pp.ConversionFailedError, match="maximum size"):
        pp._validate_received_pdf(b"%PDF-1234")


def test_worker_healthcheck_accepts_manifest_spool_and_fresh_heartbeat(
    tmp_path, monkeypatch
):
    import json

    manifest_path = tmp_path / "runtime-manifest.json"
    manifest_path.write_text(json.dumps({
        "base_image_digest": "debian@sha256:" + ("a" * 64),
        "libreoffice_version": "LibreOffice test",
        "font_package_versions": {"fonts-liberation2": "test"},
        "package_versions": {"libreoffice-writer": "test", "python3": "test"},
        "worker_build_id": "test-build",
        "pypdf_version": "test",
        "built_at": "2026-09-20T00:00:00Z",
    }), encoding="utf-8")
    monkeypatch.setattr(worker, "RUNTIME_MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(worker, "HEARTBEAT_PATH", tmp_path / ".worker.heartbeat")

    worker._write_heartbeat()
    worker.healthcheck()


def test_worker_healthcheck_rejects_placeholder_manifest(tmp_path, monkeypatch):
    import json

    manifest_path = tmp_path / "runtime-manifest.json"
    manifest_path.write_text(json.dumps({
        "base_image_digest": "debian@sha256:PIN_ME",
        "libreoffice_version": "LibreOffice test",
        "font_package_versions": {"fonts-liberation2": "test"},
        "package_versions": {"libreoffice-writer": "test", "python3": "test"},
        "worker_build_id": "test-build",
        "pypdf_version": "test",
        "built_at": "2026-09-20T00:00:00Z",
    }), encoding="utf-8")
    monkeypatch.setattr(worker, "RUNTIME_MANIFEST_PATH", manifest_path)

    with pytest.raises(RuntimeError, match="incomplete"):
        worker._validate_runtime_manifest()


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
