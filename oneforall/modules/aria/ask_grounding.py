"""Deterministic citation contract for Ask ARIA's authorized search results.

This verifies source identity, not the semantic truth of a model's prose.
"""

from urllib.parse import urlsplit


def _local_path(value):
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
        return False
    if any(ord(char) < 32 or ord(char) == 127 or char == "\\" for char in value):
        return False
    parsed = urlsplit(value)
    return not parsed.scheme and not parsed.netloc and not parsed.fragment


def verified_citations(proposed, chunks):
    """Return exact retrieved citations, or None if any citation is invented.

    An invalid entry makes the *whole answer* ungrounded. Keeping just the
    valid entries would still leave prose influenced by a fabricated source.
    """
    if not isinstance(proposed, list) or not proposed or len(proposed) > len(chunks):
        return None
    allowed = {}
    for chunk in chunks:
        path = chunk.get("url_path")
        if not _local_path(path):
            continue
        key = (chunk.get("content_type"), chunk.get("title"),
               chunk.get("section") or "", path)
        allowed[key] = chunk
    verified = []
    seen = set()
    for citation in proposed:
        if not isinstance(citation, dict):
            return None
        if any(not isinstance(citation.get(field), str) for field in
               ("content_type", "title", "url_path")):
            return None
        if citation.get("section") is not None and not isinstance(citation["section"], str):
            return None
        key = (citation.get("content_type"), citation.get("title"),
               citation.get("section") or "", citation.get("url_path"))
        if key not in allowed or key in seen:
            return None
        seen.add(key)
        verified.append({"content_type": key[0], "title": key[1],
                         "section": key[2], "url_path": key[3]})
    return verified
