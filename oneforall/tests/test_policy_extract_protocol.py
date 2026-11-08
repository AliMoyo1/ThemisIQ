"""The policy parser's bounded, credential-free worker protocol."""
from __future__ import annotations

import io
import json
import socket
import struct
import tempfile
import threading
import uuid
from pathlib import Path

import pytest

from modules.aria import policy_extract_protocol as protocol
from modules.aria import policy_intake


def _request(document: bytes, *, extension=".pdf") -> bytes:
    header = protocol._metadata(extension, "policy.pdf", len(document))
    return struct.pack("!I", len(header)) + header + document


def test_worker_returns_framed_extraction_without_a_source_path(monkeypatch):
    from modules.aria import policy_parser
    monkeypatch.setattr(policy_parser, "extract", lambda content, ext, name: {
        "spans": [{"anchor": "page 1", "text": content.decode()}], "metadata": {"title": {"value": name}}
    })
    source, reply = io.BytesIO(_request(b"sample")), io.BytesIO()
    assert protocol.serve_once(source, reply) == 0
    answer = reply.getvalue()
    size = struct.unpack("!I", answer[:4])[0]
    assert len(answer) == size + 4
    assert json.loads(answer[4:])["spans"][0]["text"] == "sample"


@pytest.mark.parametrize("input_bytes", [b"", struct.pack("!I", protocol.MAX_HEADER + 1),
                                          struct.pack("!I", 10) + b"{}"])
def test_worker_refuses_truncated_or_oversized_headers(input_bytes):
    reply = io.BytesIO()
    assert protocol.serve_once(io.BytesIO(input_bytes), reply) != 0
    assert reply.getvalue() == b""


def test_worker_refuses_oversized_output_before_writing(monkeypatch):
    from modules.aria import policy_parser
    monkeypatch.setattr(policy_parser, "extract", lambda *_: {"spans": [{"text": "x" * protocol.MAX_RESULT}]})
    reply = io.BytesIO()
    assert protocol.serve_once(io.BytesIO(_request(b"test")), reply) == 3
    assert reply.getvalue() == b""


def test_worker_rejects_unsafe_docx_without_echoing_source():
    source = b"not a zip with private policy text"
    header = protocol._metadata(".docx", "policy.docx", len(source))
    reply = io.BytesIO()
    assert protocol.serve_once(io.BytesIO(struct.pack("!I", len(header)) + header + source), reply) == 0
    result = json.loads(reply.getvalue()[4:])
    assert result == {"error": "invalid_document"}
    assert b"private policy text" not in reply.getvalue()


def test_client_and_worker_exchange_one_document_over_unix_socket(monkeypatch, tmp_path):
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("UNIX domain sockets unavailable")
    from modules.aria import policy_parser
    monkeypatch.setattr(policy_parser, "extract", lambda content, *_: {
        "spans": [{"anchor": "page 1", "text": content.decode()}]})
    socket_path = str(Path(tempfile.gettempdir()) / f"p-{uuid.uuid4().hex[:10]}.sock")
    if len(socket_path.encode()) > 100:
        pytest.skip("UNIX socket path exceeds the platform limit")
    source = tmp_path / "source.pdf"
    source.write_bytes(b"private policy text")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    server.listen(1)
    outcomes = []

    def respond():
        with server:
            connection, _ = server.accept()
            with connection:
                with connection.makefile("rb") as reader, connection.makefile("wb") as writer:
                    outcomes.append(protocol.serve_once(reader, writer))

    thread = threading.Thread(target=respond, daemon=True)
    thread.start()
    result = protocol.request(source, ".pdf", "source.pdf", socket_path=socket_path, timeout=3)
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert outcomes == [0]
    assert result["spans"][0]["text"] == "private policy text"
    Path(socket_path).unlink(missing_ok=True)


def test_production_worker_unavailable_fails_closed(monkeypatch, tmp_path):
    source = tmp_path / "policy.pdf"
    source.write_bytes(b"%PDF-test")
    monkeypatch.setattr(policy_intake, "_requires_remote_worker", lambda: True)
    monkeypatch.setattr(protocol, "request", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        protocol.ExtractionUnavailable("socket is absent")))
    with pytest.raises(policy_intake.IntakeError) as error:
        policy_intake._extract_isolated(source, ".pdf", "policy.pdf")
    assert error.value.status == 503
    assert "socket" not in error.value.message


def test_production_worker_rejection_is_a_safe_document_error(monkeypatch, tmp_path):
    source = tmp_path / "policy.docx"
    source.write_bytes(b"not a zip")
    monkeypatch.setattr(policy_intake, "_requires_remote_worker", lambda: True)
    monkeypatch.setattr(protocol, "request", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        protocol.ExtractionRejected("private parser detail")))
    with pytest.raises(policy_intake.IntakeError) as error:
        policy_intake._extract_isolated(source, ".docx", "policy.docx")
    assert error.value.status == 422
    assert "private parser detail" not in error.value.message
