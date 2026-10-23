"""
The definition of a privacy record, written once.

A RoPA entry, a DPIA and an AI impact assessment each have many fields, and the regulations they answer to ask for similar
things under different names. A definition lists every field once (key, label, kind, section, legal anchor, options,
whether it is required and when). A regime (see `regimes.py`) changes terms, anchors, option lists and required fields without
touching the definition. The same definition feeds the form, the server side validation, the completeness check and the
exports, so a form cannot offer a field the service drops, and a report cannot ask for one the form never collected.

Values that already had a column keep it (`store="column"`); every other field lives in one JSON `details` column per table.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

DETAILS_MAX_BYTES = 200_000
TEXT_MAX = 500
LONG_MAX = 4000
LIST_ITEMS_MAX = 100
LIST_ITEM_MAX = 200

KINDS = ("text", "longtext", "select", "multiselect", "bool", "date", "number", "rows")
OPS = ("nonempty", "empty", "contains", "in", "not_in", "transfers")

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_NO_TRANSFER = ("", "no", "none", "n/a", "na", "not applicable", "nil", "false", "0")


class RecordError(ValueError):
    """The values sent cannot be stored. `errors` maps a field key to a sentence a person can act on."""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__("Some details need fixing: " + "; ".join(f"{key}: {text}" for key, text in errors.items()))


# ── Values ───────────────────────────────────────────────────────────────────

def is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def flat_text(value) -> str:
    """A stored value as one line of text (a list is joined), for comparing and for conditions."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(flat_text(v) for v in value if not is_empty(v))
    if isinstance(value, dict):
        return "; ".join(f"{k}: {flat_text(v)}" for k, v in value.items() if not is_empty(v))
    return str(value).strip()


def says_transfer(value) -> bool:
    """True when a free text answer about transfers outside the territory means that there is one ("Yes", "USA", "South Africa")."""
    text = flat_text(value).lower()
    if text in _NO_TRANSFER:
        return False
    return not (text.startswith("no ") or text.startswith("no,") or text.startswith("none"))


@dataclass(frozen=True)
class Cond:
    """A field matters only when another field of the record says so. Ops: nonempty, empty, contains (text), in (one of the values),
    not_in (none of the values, an empty answer included), transfers (a transfer outside the territory is stated). The browser
    evaluates the same words."""
    field: str
    op: str = "nonempty"
    value: object = None

    def holds(self, record: dict) -> bool:
        raw = record.get(self.field)
        if self.op == "nonempty":
            return not is_empty(raw)
        if self.op == "empty":
            return is_empty(raw)
        if self.op == "transfers":
            return says_transfer(raw)
        text = flat_text(raw).lower()
        if self.op == "contains":
            return str(self.value).lower() in text
        if self.op == "in":
            return text in {str(v).lower() for v in (self.value or ())}
        if self.op == "not_in":
            return text not in {str(v).lower() for v in (self.value or ())}
        raise ValueError(f"Unknown condition {self.op}")

    def to_json(self) -> dict:
        return {"field": self.field, "op": self.op, "value": list(self.value) if isinstance(self.value, tuple) else self.value}


# ── Definition ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Field:
    key: str
    label: str                       # may hold {controller}, {processor}, {dpo}, {special}, {territory}, {regulator}, {subject}
    kind: str = "text"
    store: str = "details"           # "column" when the record table already has a column with this key
    anchor: str = ""                 # a role key the regime turns into a citation ("purposes" becomes "Art 30(1)(b)" under GDPR)
    help: str = ""
    options: tuple = ()              # closed list as (value, label) pairs; or name a regime list with `list_name`
    list_name: str = ""
    required: bool = False
    when: Cond | None = None         # the field applies only when this holds
    cols: tuple = ()                 # kind "rows": the fields of one row
    max_len: int = 0                 # 0: TEXT_MAX for text, LONG_MAX for longtext
    max_rows: int = 40
    json_list: bool = False          # a column that holds a JSON list of strings (data categories)
    wide: bool = False               # the form and the register give it the whole row

    def limit(self) -> int:
        return self.max_len or (LONG_MAX if self.kind == "longtext" else TEXT_MAX)


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    fields: tuple
    help: str = ""


@dataclass(frozen=True)
class Gap:
    key: str
    label: str
    anchor: str
    section: str


def _label(text: str, terms: dict) -> str:
    out = _PLACEHOLDER.sub(lambda m: str(terms.get(m.group(1), m.group(0))), text)
    return out[:1].upper() + out[1:]


# ── Resolved profile ─────────────────────────────────────────────────────────

@dataclass
class Profile:
    record: str                      # ropa | dpia | aiia
    regime: dict                     # one entry of regimes.REGIMES, resolved (see regimes.resolve)
    sections: tuple
    all_options: dict = field(default_factory=dict)       # list name -> every option of every regime (for validation)

    # lookups
    def fields(self) -> list:
        return [f for s in self.sections for f in s.fields]

    def get(self, key: str):
        return next((f for f in self.fields() if f.key == key), None)

    def column_keys(self) -> list:
        return [f.key for f in self.fields() if f.store == "column"]

    def detail_keys(self) -> list:
        return [f.key for f in self.fields() if f.store != "column"]

    # resolved text
    def label(self, f: Field) -> str:
        return _label(f.label, self.regime["terms"])

    def section_label(self, s: Section) -> str:
        return _label(s.label, self.regime["terms"])

    def anchor(self, f: Field) -> str:
        return self.regime["anchors"].get(f.anchor, "") if f.anchor else ""

    def options(self, f: Field) -> list:
        """[(value, label)] of a select, in the order the regime gives them."""
        raw = f.options or self.regime["lists"].get(f.list_name, ())
        return [(o, o) if isinstance(o, str) else (o[0], o[1]) for o in raw]

    def is_hidden(self, f: Field) -> bool:
        return f.key in self.regime["hidden"]

    def is_required(self, f: Field) -> bool:
        if f.key in self.regime["required_drop"]:
            return False
        return f.required or f.key in self.regime["required_add"]

    # reading a stored row
    def expand(self, row: dict) -> dict:
        """The row with its `details` merged in as ordinary keys. A key that is also a column keeps its column value."""
        out = dict(row)
        raw = out.pop("details", None)
        if raw:
            try:
                extra = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                extra = {}
            if isinstance(extra, dict):
                for key, value in extra.items():
                    out.setdefault(key, value)
        return out

    # writing
    def prepare(self, data: dict, existing_details: dict | None = None) -> tuple:
        """(columns, details, errors) from the values sent. Only fields of the definition are read; anything else is ignored. A field
        that is not sent keeps its stored value; a field sent empty is cleared. `details` is the whole merged object to store, or None
        when no detail field was sent."""
        columns, sent, errors = {}, {}, {}
        for f in self.fields():
            if f.key not in data:
                continue
            try:
                value = self._clean(f, data[f.key])
            except ValueError as exc:
                errors[f.key] = str(exc)
                continue
            if f.store == "column":
                columns[f.key] = value
            else:
                sent[f.key] = value
        if errors:
            return {}, None, errors
        details = None
        if sent:
            details = dict(existing_details or {})       # a key the definition no longer lists is kept, never dropped by a save
            details.update(sent)
            details = {k: v for k, v in details.items() if not is_empty(v)}
            if len(json.dumps(details).encode("utf-8")) > DETAILS_MAX_BYTES:
                return {}, None, {"details": "This record is too large to store."}
        return columns, details, {}

    def _clean(self, f: Field, value):
        kind = f.kind
        if f.json_list:
            return self._clean_list(f, value)
        if kind in ("text", "longtext"):
            if value is None:
                return ""
            if isinstance(value, dict):
                raise ValueError("Send this as text.")
            if isinstance(value, (list, tuple)):                 # a list sent where text is kept (older callers) is joined, not refused
                value = "; ".join(str(v).strip() for v in value if str(v).strip())
            text = _CONTROL.sub("", str(value)).strip()
            if len(text) > f.limit():
                raise ValueError(f"Keep this to {f.limit()} characters or fewer.")
            return text
        if kind == "select":
            text = _CONTROL.sub("", str(value if value is not None else "")).strip()
            if text and f.store != "column":
                allowed = {o[0] if not isinstance(o, str) else o for o in self.all_options.get(f.list_name, ())} \
                    | {o[0] if not isinstance(o, str) else o for o in f.options}
                if text not in allowed:
                    raise ValueError("Choose one of the listed options.")
            if len(text) > TEXT_MAX:
                raise ValueError("Choose one of the listed options.")
            return text
        if kind == "multiselect":
            return self._clean_list(f, value)
        if kind == "bool":
            if isinstance(value, str):
                text = value.strip().lower()
                if not text:
                    return ""
                if text in ("1", "true", "yes", "on"):
                    return 1
                if text in ("0", "false", "no", "off"):
                    return 0
                raise ValueError("Choose yes or no.")
            if value is None:
                return ""
            if value not in (True, False, 1, 0, None):
                raise ValueError("Choose yes or no.")
            return 1 if value else 0
        if kind == "date":
            text = str(value if value is not None else "").strip()
            if not text:
                return ""
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                    raise ValueError(text)
                return date.fromisoformat(text).isoformat()
            except ValueError:
                raise ValueError("Write the date as YYYY-MM-DD.") from None
        if kind == "number":
            if value in (None, ""):
                return ""
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError("Write a number.") from None
            if number != number or number in (float("inf"), float("-inf")):
                raise ValueError("Write a number.")
            return int(number) if number == int(number) else number
        if kind == "rows":
            return self._clean_rows(f, value)
        raise ValueError(f"Unknown kind {kind}")

    @staticmethod
    def _clean_list(f: Field, value) -> list:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            value = [part for part in re.split(r"[\n;,]", value)]
        if not isinstance(value, (list, tuple)):
            raise ValueError("Send this as a list.")
        out = []
        for item in value:
            text = _CONTROL.sub("", str(item)).strip()
            if not text:
                continue
            if len(text) > LIST_ITEM_MAX:
                raise ValueError(f"Keep each entry to {LIST_ITEM_MAX} characters or fewer.")
            if text not in out:
                out.append(text)
        if len(out) > LIST_ITEMS_MAX:
            raise ValueError(f"Give at most {LIST_ITEMS_MAX} entries.")
        return out

    def _clean_rows(self, f: Field, value) -> list:
        if value is None or value == "":
            return []
        if not isinstance(value, (list, tuple)):
            raise ValueError("Send the rows as a list.")
        rows = []
        for raw in value:
            if not isinstance(raw, dict):
                raise ValueError("Each row must be an object.")
            row = {}
            for col in f.cols:
                try:
                    cleaned = self._clean(col, raw.get(col.key))
                except ValueError as exc:
                    raise ValueError(f"{col.label}: {exc}") from None
                if not is_empty(cleaned):
                    row[col.key] = cleaned
            if row:
                rows.append(row)
        if len(rows) > f.max_rows:
            raise ValueError(f"Give at most {f.max_rows} rows.")
        return rows

    # completeness
    def applies(self, f: Field, record: dict) -> bool:
        return not self.is_hidden(f) and (f.when is None or f.when.holds(record))

    def gaps(self, record: dict) -> list:
        """The required fields that apply to this record and have no entry. `record` is an expanded row."""
        out = []
        for s in self.sections:
            for f in s.fields:
                if self.is_required(f) and self.applies(f, record) and is_empty(record.get(f.key)):
                    out.append(Gap(f.key, self.label(f), self.anchor(f), self.section_label(s)))
        return out

    def needed(self, record: dict) -> list:
        return [f for s in self.sections for f in s.fields if self.is_required(f) and self.applies(f, record)]

    def completeness(self, record: dict) -> tuple:
        """(entries made, entries needed) over the required fields that apply to this record."""
        needed = self.needed(record)
        return sum(1 for f in needed if not is_empty(record.get(f.key))), len(needed)

    # for the browser
    def to_json(self) -> dict:
        def one(f: Field) -> dict:
            return {"key": f.key, "label": self.label(f), "kind": f.kind, "store": f.store,
                    "help": f.help, "anchor": self.anchor(f),
                    "options": [[v, l] for v, l in self.options(f)], "required": self.is_required(f),
                    "when": f.when.to_json() if f.when else None, "wide": f.wide or f.kind in ("longtext", "rows"),
                    "limit": f.limit(), "list": f.json_list, "maxRows": f.max_rows,
                    "cols": [one(c) for c in f.cols]}
        regime = self.regime
        return {"record": self.record, "regulation": regime["key"], "regime": {
                    "key": regime["key"], "name": regime["name"], "terms": regime["terms"], "territory": regime["territory"],
                    "status": regime["status"], "record_basis": regime["record_basis"], "authority": regime["authority"],
                    "authority_short": regime["authority_short"], "notes": regime.get("notes", "")},
                "sections": [{"key": s.key, "label": self.section_label(s), "help": s.help,
                              "fields": [one(f) for f in s.fields if not self.is_hidden(f)]} for s in self.sections]}
