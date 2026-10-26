"""Local, source-anchored extraction with no app configuration or database import."""
from __future__ import annotations

import io
import re
from datetime import date
from pathlib import Path

MAX_PAGES = 200
MAX_TEXT = 300_000


def extract(content: bytes, ext: str, filename: str) -> dict:
    spans: list[dict] = []
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
                spans.append({"anchor": f"block {i}", "text": clipped})
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
    if props_version:
        metadata["version"] = {"value": props_version[:30], "anchor": "document properties", "kind": "stated"}
    patterns = {
        "version": r"\bversion\s*[:|]\s*(\d{1,3}\.\d{1,3})\b",
        "effective_date": r"\beffective\s+date\s*[:|]\s*(\d{4}-\d{2}-\d{2})\b",
        "review_date": r"\b(?:next\s+)?review\s+date\s*[:|]\s*(\d{4}-\d{2}-\d{2})\b",
        "owner": r"\b(?:document\s+)?owner\s*[:|]\s*([^\n|]{3,80})",
        "approver": r"\bapproved\s+by\s*[:|]\s*([^\n|]{3,80})",
    }
    for field, pattern in patterns.items():
        if field in metadata:
            continue
        for span in spans:
            hit = re.search(pattern, span["text"], re.IGNORECASE)
            if hit:
                value = hit.group(1).strip()[:180]
                if field.endswith("_date"):
                    try:
                        date.fromisoformat(value)
                    except ValueError:
                        continue
                metadata[field] = {"value": value, "anchor": span["anchor"], "kind": "stated"}
                break
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
            "parser": "local-docx-1" if ext == ".docx" else "local-pypdf-1"}
