"""Bounded local protocol for the separate policy extraction service.

No source path, application credentials, or database connection crosses the
socket. The worker receives the bytes of one document and returns one JSON
result. The web process treats a missing or malformed worker as unavailable.
"""
from __future__ import annotations

import json
import socket
import struct
from pathlib import Path


SOCKET_PATH = "/run/themisiq-policy-extract.sock"
MAX_SOURCE = 25 * 1024 * 1024
MAX_HEADER = 4096
MAX_RESULT = 1_500_000


class ExtractionUnavailable(Exception):
    """The bounded extraction service could not produce a valid result."""


class ExtractionRejected(Exception):
    """The isolated parser rejected the uploaded source."""


def _read_exact(stream, size: int) -> bytes:
    chunks = []
    while size:
        part = stream.read(size)
        if not part:
            raise ExtractionUnavailable("The extraction service ended early.")
        chunks.append(part)
        size -= len(part)
    return b"".join(chunks)


def _metadata(extension: str, filename: str, size: int) -> bytes:
    if extension not in (".docx", ".pdf") or not isinstance(filename, str) or not 0 < len(filename) <= 255:
        raise ExtractionUnavailable("Invalid extraction request.")
    if not 0 < size <= MAX_SOURCE:
        raise ExtractionUnavailable("Document exceeds the extraction limit.")
    header = json.dumps({"version": 1, "extension": extension, "filename": filename,
                         "size": size}, ensure_ascii=True).encode("ascii")
    if len(header) > MAX_HEADER:
        raise ExtractionUnavailable("Invalid extraction request.")
    return header


def request(path: Path, extension: str, filename: str, *, socket_path: str = SOCKET_PATH,
            timeout: float = 40) -> dict:
    """Ask the isolated worker to parse one already-staged private file."""
    size = path.stat().st_size
    header = _metadata(extension, filename, size)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(socket_path)
            with path.open("rb") as source:
                connection.sendall(struct.pack("!I", len(header)) + header)
                while chunk := source.read(64 * 1024):
                    connection.sendall(chunk)
            connection.shutdown(socket.SHUT_WR)
            with connection.makefile("rb") as response:
                result_size = struct.unpack("!I", _read_exact(response, 4))[0]
                if not 0 < result_size <= MAX_RESULT:
                    raise ExtractionUnavailable("Invalid extraction service response.")
                result = json.loads(_read_exact(response, result_size))
    except (OSError, ValueError, struct.error, json.JSONDecodeError) as exc:
        raise ExtractionUnavailable("The extraction service is unavailable.") from exc
    if isinstance(result, dict) and result.get("error") == "invalid_document":
        raise ExtractionRejected("The document failed validation.")
    if not isinstance(result, dict) or not isinstance(result.get("spans"), list):
        raise ExtractionUnavailable("Invalid extraction service response.")
    return result


def serve_once(input_stream, output_stream) -> int:
    """Handle one systemd socket-activated connection; return no details on error."""
    try:
        header_size = struct.unpack("!I", _read_exact(input_stream, 4))[0]
        if not 0 < header_size <= MAX_HEADER:
            return 2
        header = json.loads(_read_exact(input_stream, header_size))
        if not isinstance(header, dict) or header.get("version") != 1:
            return 2
        extension, filename, size = (header.get("extension"), header.get("filename"), header.get("size"))
        if isinstance(size, bool) or not isinstance(size, int):
            return 2
        _metadata(extension, filename, size)
        payload = _read_exact(input_stream, size)
        from modules.aria.policy_parser import extract
        try:
            extracted = extract(payload, extension, filename)
        except Exception:
            # Validation and parser errors never include source text in the
            # reply. A malformed source is distinct from a missing worker.
            extracted = {"error": "invalid_document"}
        result = json.dumps(extracted, ensure_ascii=True).encode("ascii")
        if not 0 < len(result) <= MAX_RESULT:
            return 3
        output_stream.write(struct.pack("!I", len(result)) + result)
        output_stream.flush()
        return 0
    except (ExtractionUnavailable, OSError, ValueError, TypeError, struct.error, json.JSONDecodeError):
        return 2
    except Exception:
        # Parser exceptions must not expose document content in the socket reply.
        return 3
