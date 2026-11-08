"""What composing an imported policy DOCX changed in its layout (plan 18, P3 gate).

Composition (policy_composition._render) keeps the source package and removes or adds body blocks. A removed block can
take more with it than its own text: the section break that made the next pages landscape, the bookmark a cross-reference
points to, the heading a contents entry jumps to. This compares an inventory of what the source kept with the candidate
and names each loss before the candidate exists. It reads parts python-docx has already loaded and makes no network
call; the rendered look is still compared by people on the PDF preview.

Severity:
  loss   something the retained text relied on is missing from the candidate
  check  the candidate is complete but shows something stale until a person acts in Word
  info   a change the author chose

A candidate with a loss or check finding is created only with the author's recorded reason (BLOCKING).
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter

from lxml import etree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS = {"w": W[1:-1], "r": R[1:-1], "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "v": "urn:schemas-microsoft-com:vml"}
BLOCKING = ("loss", "check")
REASON_MIN, REASON_MAX = 10, 500
VERSION = 1
_PAGE_FIELDS = {"TOC", "PAGEREF"}
_REF_FIELDS = {"REF", "PAGEREF", "NOTEREF"}
_IGNORED_BOOKMARKS = {"_GoBack"}
_FIELD_NAME = re.compile(r"[A-Z][A-Z0-9]{0,19}")
_SAFE_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False)


def _xp(element, path):
    """lxml XPath with our prefixes; python-docx elements override xpath() with their own prefix map."""
    return etree._Element.xpath(element, path, namespaces=NS)


def _sections(body):
    """(section properties in order, element -> section index). A paragraph carrying a sectPr ends its section; the
    body's own sectPr closes the last one."""
    sections, owner, pending = [], {}, []
    for child in body.iterchildren():
        if child.tag == W + "sectPr":
            continue
        pending.append(child)
        marker = child.find(f"{W}pPr/{W}sectPr") if child.tag == W + "p" else None
        if marker is not None:
            for element in pending:
                owner[element] = len(sections)
            sections.append(marker)
            pending = []
    for element in pending:
        owner[element] = len(sections)
    sections.append(body.find(W + "sectPr"))
    return sections, owner


def _layout(sect) -> tuple:
    """Orientation and page size of one section, as Word lays it out."""
    size = sect.find(W + "pgSz") if sect is not None else None
    if size is None:
        return ("portrait", None, None)
    width, height = size.get(W + "w"), size.get(W + "h")
    orient = size.get(W + "orient")
    if not orient:
        try:
            orient = "landscape" if int(width) > int(height) else "portrait"
        except (TypeError, ValueError):
            orient = "portrait"
    return (orient, width, height)


def _part_root(part):
    element = getattr(part, "_element", None)
    if element is not None:
        return element
    return etree.fromstring(part.blob, _SAFE_PARSER)


def _has_content(part) -> bool:
    root = _part_root(part)
    text = "".join(root.itertext()).strip()
    return bool(text) or bool(_xp(root, ".//w:drawing|.//w:pict"))


def _headers(doc, sections) -> set:
    """(kind, header or footer) pairs with content across the given sections."""
    found = set()
    for sect in sections:
        if sect is None:
            continue
        for tag, name in (("headerReference", "header"), ("footerReference", "footer")):
            for ref in sect.findall(W + tag):
                part = doc.part.related_parts.get(ref.get(R + "id"))
                if part is not None and _has_content(part):
                    found.add((ref.get(W + "type") or "default", name))
    return found


def _first_page_header(doc, sect) -> bool:
    if sect is None or sect.find(W + "titlePg") is None or sect.find(W + "titlePg").get(W + "val") in ("0", "false"):
        return False
    return ("first", "header") in _headers(doc, [sect])


def _note_ids(doc, name: str) -> set:
    """Ids of footnotes or endnotes that carry text (separators are not notes)."""
    for part in doc.part.package.iter_parts():
        if str(part.partname).endswith(f"/word/{name}s.xml"):
            root = _part_root(part)
            return {n.get(W + "id") for n in root.findall(W + name) if not n.get(W + "type")}
    return set()


def _fields(elements) -> list:
    """(kind, instruction) of every field in the elements."""
    found = []
    for element in elements:
        for instr in _xp(element, ".//w:fldSimple/@w:instr"):
            found.append(instr)
        for text in _xp(element, ".//w:instrText/text()"):
            found.append(text)
    result = []
    for instr in found:
        tokens = instr.replace('"', " ").split()
        if tokens:
            # The field name is stored and shown: keep only a short keyword, never document text.
            kind = tokens[0].upper()
            result.append((kind if _FIELD_NAME.fullmatch(kind) else "OTHER", tokens))
    return result


def inventory(doc, removed=()) -> dict:
    """What the body of doc holds once the removed block elements are gone (they are still in doc when this runs)."""
    body = doc.element.body
    gone = set(removed)
    sections, owner = _sections(body)
    kept = [c for c in body.iterchildren() if c.tag != W + "sectPr" and c not in gone]
    used = sorted({owner[c] for c in kept})
    layouts = []
    for index in used:
        layout = _layout(sections[index])
        if not layouts or layouts[-1] != layout:
            layouts.append(layout)

    def all_of(path):
        return [v for element in kept for v in _xp(element, path)]

    fields = _fields(kept)
    targets = set(all_of(".//w:hyperlink/@w:anchor"))
    for kind, tokens in fields:
        if kind in _REF_FIELDS and len(tokens) > 1:
            targets.add(tokens[1])
        elif kind == "HYPERLINK" and "\\l" in tokens:
            at = tokens.index("\\l")
            if at + 1 < len(tokens):
                targets.add(tokens[at + 1])
    images, links = [], []
    for rid in all_of(".//a:blip/@r:embed") + all_of(".//v:imagedata/@r:id"):
        rel = doc.part.rels.get(rid)
        if rel is not None and not rel.is_external:
            images.append(hashlib.sha256(rel.target_part.blob).hexdigest())
    for rid in all_of(".//w:hyperlink/@r:id"):
        rel = doc.part.rels.get(rid)
        if rel is not None and rel.is_external:
            links.append(rel.target_ref)
    tables = sum((1 if c.tag == W + "tbl" else 0) + len(c.findall(".//" + W + "tbl")) for c in kept)
    return {
        "layouts": layouts,
        "headers": _headers(doc, [sections[i] for i in used]),
        "first_page_header": bool(used) and _first_page_header(doc, sections[used[0]]),
        "footnote_refs": all_of(".//w:footnoteReference/@w:id"),
        "endnote_refs": all_of(".//w:endnoteReference/@w:id"),
        "footnotes": _note_ids(doc, "footnote"),
        "endnotes": _note_ids(doc, "endnote"),
        "bookmarks": set(all_of(".//w:bookmarkStart/@w:name")),
        "targets": targets,
        "fields": [kind for kind, _ in fields],
        "tables": tables,
        "images": images,
        "links": links,
        "tracked": len(all_of(".//w:ins|.//w:del")),
        "comments": len(all_of(".//w:commentReference")),
    }


def _describe(layout) -> str:
    orient, width, height = layout
    if width and height:
        try:
            return f"{orient} {round(int(width) / 1440 * 25.4)} x {round(int(height) / 1440 * 25.4)} mm"
        except ValueError:
            pass
    return orient


def _is_subsequence(needle, haystack) -> bool:
    it = iter(haystack)
    return all(any(item == other for other in it) for item in needle)


def compare(retained: dict, candidate: dict, manifest: dict) -> list:
    """Findings, losses first. `retained` is the source inventory without the removed blocks, `candidate` the
    candidate's inventory, `manifest` the composition record (mode, choices and hashes of what it added)."""
    findings = []

    def add(key, severity, title, detail, count=None):
        findings.append({"key": key, "severity": severity, "title": title, "detail": detail, "count": count})

    for name, label in (("footnote", "footnotes"), ("endnote", "endnotes")):
        refs, defined = candidate[f"{name}_refs"], candidate[f"{name}s"]
        missing = [r for r in refs if r not in defined]
        dropped = len(retained[f"{name}_refs"]) - len(refs)
        if missing or dropped > 0:
            add(f"{name}s", "loss", f"Some {label} are missing",
                f"{len(missing)} {name} reference(s) in the candidate have no {name} text, and {max(dropped, 0)} "
                f"reference(s) from the retained text are gone. Check the numbering against the original.",
                len(missing) + max(dropped, 0))

    contents = {t for t in candidate["targets"] if t.startswith("_Toc")}
    broken = sorted(t for t in candidate["targets"] - candidate["bookmarks"] - _IGNORED_BOOKMARKS
                    if not t.startswith("_Toc"))
    if broken:
        add("cross_references", "loss", "Cross-references point to removed text",
            f"{len(broken)} internal link(s) or cross-reference(s) point to text that is no longer in the candidate. "
            "Word shows them as broken references.", len(broken))
    stale_contents = sorted(contents - candidate["bookmarks"])
    if "TOC" in candidate["fields"] or stale_contents:
        add("contents", "check", "Update the contents table in Word",
            "The contents table and its page numbers were generated before composing. "
            + (f"{len(stale_contents)} entry(ies) point to headings that were removed. " if stale_contents else "")
            + "Open the candidate in Word and update the table before approval.", len(stale_contents) or None)
    elif "PAGEREF" in candidate["fields"]:
        add("page_references", "check", "Update page references in Word",
            "Page number references were calculated before composing and may now be wrong. Update fields in Word.",
            candidate["fields"].count("PAGEREF"))
    others = sorted({f for f in candidate["fields"] if f not in _PAGE_FIELDS | _REF_FIELDS | {"HYPERLINK"}})
    if others:
        add("fields", "info", "Fields update when the document opens",
            "The body has fields that Word recalculates: " + ", ".join(others) + ".", len(others))

    if retained["layouts"] and not _is_subsequence(retained["layouts"], candidate["layouts"]):
        lost = [_describe(x) for x in retained["layouts"] if x not in candidate["layouts"]]
        add("page_layout", "loss", "A page layout change was lost",
            "The retained text used " + " then ".join(_describe(x) for x in retained["layouts"])
            + " pages; the candidate uses " + " then ".join(_describe(x) for x in candidate["layouts"])
            + (". Missing: " + ", ".join(lost) if lost else "")
            + ". A removed or excluded block carried the section break.", len(lost) or 1)

    if manifest.get("clear_headers"):
        if retained["headers"]:
            add("headers", "info", "Headers and footers cleared as you chose",
                "Old headers and footers, including logos, were removed.", len(retained["headers"]))
    else:
        gone = sorted(retained["headers"] - candidate["headers"])
        if gone:
            add("headers", "loss", "A header or footer disappeared",
                "Missing: " + ", ".join(f"{kind} {name}" for kind, name in gone)
                + ". The section that defined it was removed with a block.", len(gone))
        if manifest.get("mode") in ("replace_cover", "replace_both") and candidate["first_page_header"]:
            add("first_page_header", "check", "The first-page header now sits on the new cover",
                "The original's first page has its own header, and the new cover is now that first page. "
                "Check it in the preview, or clear old headers.")

    if candidate["tables"] < retained["tables"]:
        add("tables", "loss", "Tables are missing",
            f"The retained text had {retained['tables']} table(s); the candidate has {candidate['tables']}.",
            retained["tables"] - candidate["tables"])

    added = Counter(h for h in [manifest.get("cover_logo_sha256"), (manifest.get("figure") or {}).get("image_sha256"),
                                *[d.get("image_sha256") for d in manifest.get("diagrams") or []]] if h)
    missing_images = Counter(retained["images"]) - (Counter(candidate["images"]) - added)
    if missing_images:
        count = sum(missing_images.values())
        add("images", "loss", "Images are missing",
            f"{count} image(s) from the retained text are not in the candidate.", count)

    missing_links = Counter(retained["links"]) - Counter(candidate["links"])
    if missing_links:
        count = sum(missing_links.values())
        add("links", "loss", "Web links are missing",
            f"{count} web link(s) from the retained text are not in the candidate.", count)

    if candidate["tracked"] or candidate["comments"]:
        add("revisions", "check", "Tracked changes or comments remain",
            f"{candidate['tracked']} tracked change(s) and {candidate['comments']} comment(s) are still in the text. "
            "Accept, reject or remove them in Word so approvers see the final wording.",
            candidate["tracked"] + candidate["comments"])

    excluded = len(manifest.get("excluded_blocks") or [])
    choice = {"replace_cover": "The cover and front matter were replaced.",
              "replace_body": "The body was replaced; the cover was kept.",
              "replace_both": "The cover and body were replaced."}.get(manifest.get("mode"))
    if choice:
        add("choice", "info", "What you chose", choice + (f" {excluded} block(s) were excluded." if excluded else ""))

    order = {"loss": 0, "check": 1, "info": 2}
    findings.sort(key=lambda f: order[f["severity"]])
    return findings


def blocking(findings) -> list:
    return [f for f in findings if f["severity"] in BLOCKING]


def clean_reason(value) -> "str | None":
    """The author's reason for creating a candidate with blocking findings, or None when absent or invalid."""
    if not isinstance(value, str):
        return None
    reason = value.strip()
    return reason if REASON_MIN <= len(reason) <= REASON_MAX else None
