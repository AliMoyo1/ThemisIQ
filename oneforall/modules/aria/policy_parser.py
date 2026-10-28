"""Local, source-anchored extraction with no app configuration or database import."""
from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

MAX_PAGES = 200
MAX_TEXT = 300_000
DOCX_PARSER_VERSION = "local-docx-2"


def _label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _version(value: str) -> str:
    match = re.search(r"(?<!\d)(\d{1,3}\.\d{1,3})(?![\d.])", value)
    return match.group(1) if match else ""


def _date_value(value: str) -> str:
    """Normalize only unambiguous dates; do not guess a numeric locale."""
    match = re.search(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", value)
    if match:
        year, month, day = map(int, match.groups())
    else:
        match = re.search(r"(?<!\d)(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?!\d)", value)
        if not match:
            return ""
        day, month, year = map(int, match.groups())
        if day <= 12 and month <= 12:
            return ""
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _person(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if (not 2 < len(value) <= 80 or "|" in value or ":" in value
            or _date_value(value) or re.fullmatch(r"[\d/.-]+", value)
            or _label(value) in {"owner", "document owner", "policy owner", "approver",
                                 "approved by", "author", "author s", "authors", "date",
                                 "signature", "full names", "document custodian"}):
        return ""
    return value


def _table_metadata(tables: list[tuple[str, list[list[str]]]], metadata: dict) -> None:
    labels = {
        "version": {"version", "version no", "version n", "version number"},
        "effective_date": {"effective date", "implementation date", "commencement date"},
        "approval_date": {"approval date", "date approved"},
        "review_date": {"review date", "next review date"},
        "owner": {"owner", "document owner", "policy owner", "document custodian"},
        "approver": {"approver", "approved by"},
    }
    for anchor, rows in tables:
        for row in rows:
            for index, cell in enumerate(row[:-1]):
                label = _label(cell)
                value = row[index + 1]
                for field, names in labels.items():
                    if field in metadata or label not in names:
                        continue
                    proposed = (_version(value) if field == "version" else
                                _date_value(value) if field.endswith("_date") else _person(value))
                    if proposed:
                        metadata[field] = {"value": proposed, "anchor": anchor, "kind": "stated"}

        if not rows:
            continue
        header = [_label(cell) for cell in rows[0]]
        if "authorized by" in header and "full names" in header:
            name_index = header.index("full names")
            date_index = header.index("date") if "date" in header else -1
            candidates = [row for row in rows[1:] if len(row) > name_index and _person(row[name_index])]
            if len(candidates) == 1:
                row = candidates[0]
                metadata.setdefault("approver", {"value": _person(row[name_index]),
                                                 "anchor": anchor, "kind": "stated"})
                if date_index >= 0 and len(row) > date_index:
                    approved = _date_value(row[date_index])
                    if approved:
                        metadata.setdefault("approval_date", {"value": approved,
                                                               "anchor": anchor, "kind": "stated"})

    if "owner" not in metadata:
        current_version = metadata.get("version", {}).get("value", "")
        for anchor, rows in tables:
            if not rows:
                continue
            header = [_label(cell) for cell in rows[0]]
            versions = [i for i, name in enumerate(header) if name in {"version", "version number"}]
            authors = [i for i, name in enumerate(header) if name in {"author", "author s", "authors"}]
            if not versions or not authors:
                continue
            version_index, author_index = versions[0], authors[0]
            revisions = [(row[version_index], _person(row[author_index])) for row in rows[1:]
                         if len(row) > max(version_index, author_index) and _version(row[version_index])]
            selected = next(((version, author) for version, author in revisions
                             if _version(version) == current_version and author), None)
            if selected:
                metadata["owner"] = {"value": selected[1], "anchor": anchor, "kind": "inferred",
                                     "note": "Latest revision author; confirm document ownership."}
                break


def extract(content: bytes, ext: str, filename: str) -> dict:
    spans: list[dict] = []
    paragraphs: list[dict] = []
    tables: list[tuple[str, list[list[str]]]] = []
    if ext == ".docx":
        from docx import Document
        document = Document(io.BytesIO(content))
        text_len = 0
        for i, block in enumerate(document.iter_inner_content(), 1):
            if i > 3000 or text_len >= MAX_TEXT:
                break
            text = (getattr(block, "text", "") or "").strip()
            if block.__class__.__name__ == "Table":
                text = " | ".join(" | ".join(c.text for c in row.cells) for row in block.rows)
            if text:
                clipped = text[:3000]
                span = {"anchor": f"block {i}", "text": clipped}
                spans.append(span)
                if block.__class__.__name__ == "Table" and i <= 80:
                    tables.append((span["anchor"], [[cell.text[:180] for cell in row.cells[:8]]
                                                     for row in block.rows[:30]]))
                elif block.__class__.__name__ != "Table":
                    paragraphs.append(span)
                text_len += len(clipped)
        props = document.core_properties
        props_title = (props.title or "").strip()
        props_version = (props.version or "").strip()
    elif ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content), strict=True)
        if len(reader.pages) > MAX_PAGES:
            raise ValueError(f"PDF exceeds {MAX_PAGES} pages")
        text_len = 0
        for i, page in enumerate(reader.pages, 1):
            if text_len >= MAX_TEXT:
                break
            text = (page.extract_text() or "").strip()[:6000]
            if text:
                spans.append({"anchor": f"page {i}", "text": text})
                paragraphs.append(spans[-1])
                text_len += len(text)
        info = reader.metadata
        props_title = str(info.title or "").strip() if info else ""
        props_version = ""
    else:
        raise ValueError("Unsupported parser type")
    text = "\n".join(s["text"] for s in spans)
    metadata: dict[str, dict] = {}
    stem = Path(filename).stem.replace("_", " ").replace("-", " ")[:180]
    metadata["title"] = {"value": props_title[:180] or stem, "anchor": "document properties" if props_title else "filename",
                         "kind": "stated" if props_title else "inferred"}
    if not props_title and ext == ".docx":
        for span in paragraphs[:30]:
            heading = span["text"].strip()
            if (2 <= len(heading.split()) <= 12 and len(heading) <= 120
                    and heading == heading.upper()
                    and re.search(r"\b(?:POLICY|PROCEDURE|STANDARD|GUIDELINE|TEMPLATE|PLAN)$", heading)):
                metadata["title"] = {"value": heading.title(), "anchor": span["anchor"], "kind": "stated"}
                break
    if props_version:
        metadata["version"] = {"value": props_version[:30], "anchor": "document properties", "kind": "stated"}
    _table_metadata(tables, metadata)
    patterns = {
        "version": r"^\s*version(?:\s+(?:no\.?|number))?\s*[:|]?\s*(\d{1,3}\.\d{1,3})\b",
        "effective_date": r"^\s*(?:effective|implementation|commencement)\s+date\s*[:|]\s*(.+)$",
        "approval_date": r"^\s*(?:approval\s+date|date\s+approved)\s*[:|]\s*(.+)$",
        "review_date": r"^\s*(?:next\s+)?review\s+date\s*[:|]\s*(.+)$",
        "owner": r"^\s*(?:(?:document|policy)\s+)?owner\s*[:|]\s*([^\n|]{3,80})$",
        "approver": r"^\s*approved\s+by\s*[:|]\s*([^\n|]{3,80})$",
    }
    for field, pattern in patterns.items():
        if field in metadata and metadata[field].get("kind") == "stated":
            continue
        found = False
        for span in paragraphs:
            for line in span["text"].splitlines():
                hit = re.search(pattern, line, re.IGNORECASE)
                if not hit:
                    continue
                raw = hit.group(1).strip()
                value = (_version(raw) if field == "version" else
                         _date_value(raw) if field.endswith("_date") else _person(raw))
                if value:
                    metadata[field] = {"value": value, "anchor": span["anchor"], "kind": "stated"}
                    found = True
                    break
            if found:
                break
    if "version" not in metadata:
        match = re.search(r"(?i)(?:^|[ _.-])v(?:ersion)?[ _.-]*(\d{1,3}\.\d{1,3})(?=$|[ _.-])",
                          Path(filename).stem)
        if match:
            metadata["version"] = {"value": match.group(1), "anchor": "filename", "kind": "inferred"}
    if "owner" not in metadata and "version" in metadata:
        _table_metadata(tables, metadata)
    kinds = ("Policy", "Procedure", "Standard", "Guideline", "Template", "Record", "Plan")
    for source_text, anchor in ((props_title, "document properties"),
                                (text[:1200], spans[0]["anchor"] if spans else "")):
        for kind in kinds:
            if re.search(rf"\b{re.escape(kind)}\b", source_text, re.IGNORECASE):
                metadata["doc_type"] = {"value": kind, "anchor": anchor, "kind": "inferred"}
                break
        if "doc_type" in metadata:
            break
    return {"metadata": metadata, "spans": spans, "text_status": "extracted" if spans else "no_extractable_text",
            "parser": DOCX_PARSER_VERSION if ext == ".docx" else "local-pypdf-1"}
