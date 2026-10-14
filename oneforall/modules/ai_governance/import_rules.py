"""
AI governance: the pure rules of the external form import (plans/2026-10-governance-rework/01 section 4).

A governance specialist exports the responses of the customer's own Google or Microsoft Form and brings them in here. This
module only reads and normalizes: it opens a CSV or XLSX export, reads the column headers, lets a saved mapping say which
column answers which question, turns every answer into the vocabulary of `rules`, and names everything it could not
understand. It never guesses: an unknown choice is left unanswered and reported, a date is read in the order the mapping
declares, a person is a hint to confirm and never an account, and an untrusted file is only ever read as text.

Nothing here touches the database. `imports.py` persists, previews and confirms.
"""
import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime

from modules.ai_governance import rules

GUIDE_VERSION = "forms-v1"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_UNZIPPED_BYTES = 20 * 1024 * 1024
MAX_ROWS = 500
MAX_COLUMNS = 80
MAX_CELL = 4000
DATE_ORDERS = ("iso", "dmy", "mdy")
EXTRA_LIMIT = 500

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SPACE = re.compile(r"\s+")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


class ImportRuleError(Exception):
    """The file could not be read as an export. `str()` is a sentence a person can act on."""


# ── The published field guide: the questions the customer's form needs ──────

def _labels(vocab) -> list:
    return list(vocab.values())


FIELD_GUIDE = (
    {"target": "name", "question": "What is the name of the AI tool or use?", "required": True, "kind": "text"},
    {"target": "purpose", "question": "What will it be used for?", "required": True, "kind": "text"},
    {"target": "requester_name", "question": "Your name", "required": True, "kind": "text"},
    {"target": "requester_email", "question": "Your email address", "required": True, "kind": "text"},
    {"target": "requester_organization", "question": "Your organization or team", "required": True, "kind": "text"},
    {"target": "provider_name", "question": "Which product or provider is it?", "required": True, "kind": "text"},
    {"target": "deployment", "question": "How is it provided?", "required": True, "kind": "choice",
     "choices": _labels(rules.DEPLOYMENT)},
    {"target": "intended_users", "question": "Who will use it?", "required": True, "kind": "text"},
    {"target": "data_categories", "question": "What kinds of data does it use?", "required": True, "kind": "multi",
     "choices": _labels(rules.DATA_CATEGORIES)},
    {"target": "affects_decisions", "question": "Does it affect decisions about people?", "required": True, "kind": "yes_no",
     "choices": ["Yes", "No", "Not sure"]},
    {"target": "target_launch", "question": "When do you plan to start using it?", "required": True, "kind": "date"},
    {"target": "owner", "question": "Who is the business owner (name or email)?", "required": True, "kind": "person"},
    {"target": "affected_people", "question": "Who is affected by it?", "required": False, "kind": "multi",
     "choices": _labels(rules.AFFECTED_PEOPLE)},
    {"target": "autonomy", "question": "How much does it decide on its own?", "required": False, "kind": "choice",
     "choices": _labels(rules.AUTONOMY)},
    {"target": "external_access", "question": "Do people outside the organization use it or see what it produces?",
     "required": False, "kind": "yes_no", "choices": ["Yes", "No", "Not sure"]},
    {"target": "jurisdictions", "question": "Which countries or regions does it concern?", "required": False, "kind": "multi",
     "choices": _labels(rules.JURISDICTIONS)},
    {"target": "human_oversight", "question": "How will a person oversee it?", "required": False, "kind": "text"},
    {"target": "known_model", "question": "Which model or version is it, if you know?", "required": False, "kind": "extra"},
    {"target": "existing_reference", "question": "Is there an earlier approval or audit reference?", "required": False,
     "kind": "extra"},
    {"target": "supporting_documents", "question": "Supporting documents (names or links)", "required": False, "kind": "extra"},
    {"target": "response_id", "question": "Response ID", "required": False, "kind": "key"},
)
TARGETS = {g["target"]: g for g in FIELD_GUIDE}
REQUIRED_TARGETS = tuple(g["target"] for g in FIELD_GUIDE if g["required"])
_EXTRA = ("known_model", "existing_reference", "supporting_documents")
_REQUESTER = ("requester_name", "requester_email", "requester_organization")


def template_csv() -> str:
    """The header row of a form that satisfies the guide, and one example row, for the customer's administrator."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([g["question"] for g in FIELD_GUIDE if g["target"] != "response_id"])
    example = {"name": "Support ticket summarizer", "purpose": "Summarize incoming support tickets for agents",
               "requester_name": "A. Requester", "requester_email": "requester@example.com",
               "requester_organization": "Customer support", "provider_name": "Example AI",
               "deployment": rules.DEPLOYMENT["vendor_service"], "intended_users": "Support agents",
               "data_categories": "; ".join([rules.DATA_CATEGORIES["internal"], rules.DATA_CATEGORIES["personal"]]),
               "affects_decisions": "No", "target_launch": "2026-12-01", "owner": "owner@example.com"}
    writer.writerow([example.get(g["target"], "") for g in FIELD_GUIDE if g["target"] != "response_id"])
    return out.getvalue()


# ── Reading a file ──────────────────────────────────────────────────────────

def _clean_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        text = value.strftime("%Y-%m-%d %H:%M:%S") if (value.hour or value.minute or value.second) else value.strftime("%Y-%m-%d")
    elif isinstance(value, bool):
        text = "Yes" if value else "No"
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = str(value)
    return _CONTROL.sub("", text).strip()


def _headers(raw_headers) -> list:
    """Trimmed, de-duplicated, never empty: a blank header becomes "(column N)" and a repeat gets a number."""
    seen, out = {}, []
    for index, raw in enumerate(raw_headers, start=1):
        text = _SPACE.sub(" ", _clean_cell(raw)) or f"(column {index})"
        seen[text] = seen.get(text, 0) + 1
        out.append(text if seen[text] == 1 else f"{text} ({seen[text]})")
    return out


def _decode(data: bytes) -> tuple:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    try:
        return data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        raise ImportRuleError("This file is not UTF-8 text. In your spreadsheet program, save or export it as CSV UTF-8.")


def _read_csv(data: bytes) -> dict:
    text, encoding = _decode(data)
    sample = text[:4096]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ","
    rows = []
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
        for number, record in enumerate(reader):
            if len(record) > MAX_COLUMNS:
                raise ImportRuleError(f"This file has more than {MAX_COLUMNS} columns.")
            rows.append(record)
            if len(rows) > MAX_ROWS + 1:
                raise ImportRuleError(f"This file has more than {MAX_ROWS} responses. Export it in smaller parts.")
    except csv.Error as exc:
        raise ImportRuleError(f"The CSV could not be read: {exc}.")
    return {"kind": "csv", "encoding": encoding, "delimiter": delimiter, "rows": rows}


def _read_xlsx(data: bytes) -> dict:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ImportRuleError("This file is not a valid Excel workbook.")
    if sum(i.file_size for i in archive.infolist()) > MAX_UNZIPPED_BYTES:
        raise ImportRuleError("This workbook is too large to read safely.")
    try:
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise ImportRuleError("This workbook could not be read. Export the responses again as .xlsx or .csv.")
    try:
        sheet = workbook.worksheets[0]
        rows = []
        for record in sheet.iter_rows(values_only=True):
            if len(record) > MAX_COLUMNS and any(v not in (None, "") for v in record[MAX_COLUMNS:]):
                raise ImportRuleError(f"This sheet has more than {MAX_COLUMNS} columns.")
            rows.append(list(record[:MAX_COLUMNS]))
            if len(rows) > MAX_ROWS + 1:
                raise ImportRuleError(f"This sheet has more than {MAX_ROWS} responses. Export it in smaller parts.")
    finally:
        workbook.close()
    return {"kind": "xlsx", "encoding": None, "delimiter": None, "rows": rows}


def read_table(data: bytes, filename: str = "") -> dict:
    """{"kind", "encoding", "headers", "rows": [[str, ...]]}. The first non-empty row is the headers; wholly blank rows are
    dropped and the row numbers of what is left are kept, so a message can say which line of the export it means."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ImportRuleError("The file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise ImportRuleError(f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    name = (filename or "").lower()
    is_zip = bytes(data[:2]) == b"PK"
    if name.endswith((".xlsx", ".xlsm")) or is_zip:
        if not is_zip:
            raise ImportRuleError("This file is not a valid Excel workbook.")
        table = _read_xlsx(bytes(data))
    elif not name or name.endswith((".csv", ".txt", ".tsv")):
        table = _read_csv(bytes(data))
    else:
        raise ImportRuleError("Upload the export as a .csv or .xlsx file.")
    raw = table.pop("rows")
    header_index = next((i for i, r in enumerate(raw) if any(_clean_cell(c) for c in r)), None)
    if header_index is None:
        raise ImportRuleError("The file has no column headers.")
    headers = _headers(raw[header_index])
    rows = []
    for offset, record in enumerate(raw[header_index + 1:], start=header_index + 2):
        cells = [_clean_cell(c) for c in record[:len(headers)]]
        cells += [""] * (len(headers) - len(cells))
        if not any(cells):
            continue
        if any(len(c) > MAX_CELL for c in cells):
            cells = [c[:MAX_CELL] if len(c) <= MAX_CELL else None for c in cells]  # None marks a cell that was too long
        rows.append({"row_number": offset, "cells": cells})
    return {**table, "headers": headers, "rows": rows}


# ── Mapping ─────────────────────────────────────────────────────────────────

def _norm_header(text: str) -> str:
    """Case, punctuation and spacing folded away; an underscore counts as a space, so a key and its words match."""
    return re.sub(r"[^a-z0-9 ]", "", _SPACE.sub(" ", str(text).lower().replace("_", " "))).strip()


# Microsoft Forms puts the respondent's own "Name" and "Email" ahead of the questions, so a bare "Name" is the requester,
# never the name of the AI use.
_ALIASES = {
    "response_id": ("id", "response id"),
    "requester_email": ("email", "email address"),
    "requester_name": ("name",),
}


def suggest_mapping(headers) -> dict:
    """{header: target or ""}. A header is matched, whole, to the guide's question text, a target key or a short alias. A
    target is offered once; whatever is not recognized is left unmapped for the specialist to place or ignore."""
    wanted = {}
    for g in FIELD_GUIDE:
        wanted[_norm_header(g["question"])] = g["target"]
        if g["target"] != "name":
            wanted[_norm_header(g["target"].replace("_", " "))] = g["target"]
    for target, aliases in _ALIASES.items():
        for alias in aliases:
            wanted.setdefault(_norm_header(alias), target)
    taken, out = set(), {}
    for header in headers:
        target = wanted.get(_norm_header(header), "")
        if target and target not in taken:
            taken.add(target)
            out[header] = target
        else:
            out[header] = ""
    return out


def validate_mapping(mapping, headers) -> list:
    """Sentences for what is wrong with a mapping; an empty list means it can be used."""
    problems = []
    if not isinstance(mapping, dict):
        return ["Send the mapping as an object."]
    unknown_columns = sorted(h for h in mapping if h not in headers)
    if unknown_columns:
        problems.append("The mapping names columns the file does not have: " + ", ".join(f"'{h[:60]}'" for h in unknown_columns[:3]) + ".")
    targets = {}
    for header, target in mapping.items():
        if target in ("", None):
            continue
        if target not in TARGETS:
            problems.append(f"'{str(target)[:40]}' is not a question the import knows.")
        elif target in targets:
            problems.append(f"Two columns are mapped to '{TARGETS[target]['question']}'.")
        targets[target] = header
    if "name" not in targets:
        problems.append("Map a column to the name of the AI use. Without it a response cannot become a request.")
    return problems


# ── Normalizing one answer ──────────────────────────────────────────────────

_YES = {"yes", "y", "true", "1"}
_NO = {"no", "n", "false", "0"}
_UNSURE = {"not sure", "unsure", "unknown", "dont know", "do not know", "maybe"}
_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}


def norm_yes_no(value: str) -> tuple:
    """(True|False|None, ok). "Not sure" is a real answer (None); anything else unrecognized is not ok."""
    text = re.sub(r"[^a-z0-9 ]", "", _SPACE.sub(" ", value.lower())).strip()
    if text in _YES:
        return True, True
    if text in _NO:
        return False, True
    if text in _UNSURE or text == "":
        return None, True
    return None, False


def _vocab_lookup(vocab: dict) -> dict:
    lookup = {}
    for key, label in vocab.items():
        lookup[_norm_header(key.replace("_", " "))] = key
        lookup[_norm_header(label)] = key
    return lookup


def norm_choice(value: str, vocab: dict) -> tuple:
    """(key or None, ok). Matches a key or its label, ignoring case, punctuation and spacing."""
    if not value.strip():
        return None, True
    key = _vocab_lookup(vocab).get(_norm_header(value))
    return key, key is not None


def split_multi(value: str) -> list:
    """Google Forms joins checkbox answers with ", " and Microsoft Forms with ";". A semicolon wins when there is one."""
    if not value.strip():
        return []
    parts = value.split(";") if ";" in value else value.split(", ")
    return [p.strip() for p in parts if p.strip()]


def norm_multi(value: str, vocab: dict) -> tuple:
    """([keys], [unknown texts])."""
    lookup = _vocab_lookup(vocab)
    keys, unknown = [], []
    for part in split_multi(value):
        key = lookup.get(_norm_header(part))
        if key is None:
            unknown.append(part)
        elif key not in keys:
            keys.append(key)
    return keys, unknown


def norm_date(value: str, order: str = "iso") -> tuple:
    """(YYYY-MM-DD or None, recognized). A numeric date such as 03/04/2026 is read only in the order the mapping declares."""
    text = value.strip()
    if not text:
        return None, True
    date_part = re.split(r"[ T]", text)[0]
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_part):
            return datetime.strptime(date_part, "%Y-%m-%d").strftime("%Y-%m-%d"), True
        match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", date_part)
        if match and order in ("dmy", "mdy"):
            a, b, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
            day, month = (a, b) if order == "dmy" else (b, a)
            return datetime(year, month, day).strftime("%Y-%m-%d"), True
        match = re.fullmatch(r"(\d{1,2}) ([A-Za-z]+) (\d{4})", text)
        if match and match.group(2).lower() in _MONTHS:
            return datetime(int(match.group(3)), _MONTHS[match.group(2).lower()], int(match.group(1))).strftime("%Y-%m-%d"), True
    except ValueError:
        return None, False
    return None, False


def looks_like_email(value: str) -> bool:
    return bool(_EMAIL.match(value.strip()))


# ── One response ────────────────────────────────────────────────────────────

def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(answers: dict, requester: dict) -> str:
    return hashlib.sha256(canonical({"answers": answers, "requester": requester}).encode("utf-8")).hexdigest()


def correlation_key(org_id, form_name: str, response_id, requester_email, name) -> "str | None":
    """What makes two rows the same response. A response id wins; otherwise the same requester and the same use name. None
    when there is nothing to correlate on, so the row is always new."""
    if response_id:
        raw = "r:" + str(response_id).strip()
    elif requester_email and name:
        raw = "e:" + str(requester_email).strip().lower() + "|" + _SPACE.sub(" ", str(name).strip().lower())
    else:
        return None
    return hashlib.sha256(f"{org_id}|{(form_name or '').strip().lower()}|{raw}".encode("utf-8")).hexdigest()[:40]


def process_row(headers, row, mapping, *, date_order="iso") -> dict:
    """One response, normalized. `row` is {"row_number", "cells"}. Returns the answers in the vocabulary of `rules`, the
    requester's facts, an owner hint, unmapped columns that held something, and every issue with its level: `error` keeps
    the row out of the import, `warning` imports it with that answer left open."""
    issues = []

    def issue(level, field, message):
        issues.append({"level": level, "field": field, "message": message})

    by_target, unmapped = {}, {}
    for header, cell in zip(headers, row["cells"]):
        target = mapping.get(header) or ""
        if cell is None:  # a cell over the limit is never cut: the row is refused
            issue("error", target or header, f"A cell in '{header[:60]}' is longer than {MAX_CELL} characters.")
            cell = ""
        if target:
            by_target[target] = cell
        elif cell:
            unmapped[header] = cell[:EXTRA_LIMIT]

    answers, requester, extra = {}, {}, {}
    for target, value in by_target.items():
        if target not in TARGETS or target in ("response_id", "owner"):
            continue
        kind = TARGETS[target]["kind"]
        label = rules.label(target)
        if kind == "text" and target in _REQUESTER:
            requester[target.replace("requester_", "")] = value[:200] or None
        elif kind == "text":
            answers[target] = value or None
        elif kind == "extra":
            if value:
                extra[target] = value[:EXTRA_LIMIT]
        elif kind == "choice":
            vocab = {"deployment": rules.DEPLOYMENT, "autonomy": rules.AUTONOMY}[target]
            key, ok = norm_choice(value, vocab)
            answers[target] = key
            if not ok:
                issue("warning", target, f"'{value[:60]}' is not one of the choices for {label}. Left unanswered.")
        elif kind == "multi":
            vocab = {"data_categories": rules.DATA_CATEGORIES, "affected_people": rules.AFFECTED_PEOPLE,
                     "jurisdictions": rules.JURISDICTIONS}[target]
            keys, unknown = norm_multi(value, vocab)
            answers[target] = keys
            for item in unknown:
                issue("warning", target, f"'{item[:60]}' is not one of the choices for {label}. It was not added.")
        elif kind == "yes_no":
            answer, ok = norm_yes_no(value)
            answers[target] = answer
            if not ok:
                issue("warning", target, f"'{value[:60]}' is not yes, no or not sure for {label}. Left unanswered.")
        elif kind == "date":
            iso, ok = norm_date(value, date_order)
            if ok:
                answers[target] = iso
            else:
                answers[target] = value[:40] or None
                shown = {"iso": "YYYY-MM-DD", "dmy": "DD/MM/YYYY", "mdy": "MM/DD/YYYY"}.get(date_order, "YYYY-MM-DD")
                issue("warning", target, f"'{value[:60]}' is not a date written as {shown}. Kept as written.")
    if requester.get("email") and not looks_like_email(requester["email"]):
        issue("warning", "requester_email", "The requester's email address does not look like an address.")
    cleaned, errors = rules.clean(answers)
    for field, message in errors.items():
        issue("error", field, message)
    answers = {**{k: v for k, v in answers.items() if k not in errors}, **cleaned}

    owner_hint = (by_target.get("owner") or "").strip()[:200] or None
    response_id = (by_target.get("response_id") or "").strip()[:120] or None
    if extra:
        requester["extra"] = extra
    requester = {k: v for k, v in requester.items() if v}
    if not answers.get("name"):
        issue("error", "name", "The response has no name for the AI use.")
    missing = [f for f in rules.missing_for_submit({**answers, "owner_user_id": None}) if f != "owner_user_id"]
    return {
        "row_number": row["row_number"], "answers": answers, "requester": requester, "owner_hint": owner_hint,
        "response_id": response_id, "unmapped": unmapped, "issues": issues,
        "missing": missing, "fingerprint": fingerprint(answers, requester),
        "importable": not any(i["level"] == "error" for i in issues)}


def diff_answers(old: dict, new: dict) -> list:
    """What differs between two sets of answers: [{"field", "label", "before", "after"}], in the order the form asks."""
    out = []
    for field in rules.FIELDS:
        if field in ("owner_user_id", "business_unit_id", "source_ref"):
            continue
        before, after = old.get(field) or None, new.get(field) or None  # None, "" and [] all mean "not answered"
        if before != after:
            out.append({"field": field, "label": rules.label(field), "before": before, "after": after})
    return out


def diff_requester(old: dict, new: dict) -> list:
    out = []
    for field in ("name", "email", "organization"):
        if (old or {}).get(field) != (new or {}).get(field):
            out.append({"field": f"requester_{field}", "label": f"requester {field}",
                        "before": (old or {}).get(field), "after": (new or {}).get(field)})
    return out
