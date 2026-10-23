"""
Is every figure in a piece of written narrative a figure of the data?

A narrative that a model wrote is a draft. Before it goes into a board document, each number in it is looked up among the
figures of the report it is meant to describe: the figures themselves, the numbers inside names and titles ("ISO 27001"),
and the shares and differences that follow from two of them (64 of 412 is 16 percent). A number that is none of these is
reported as unverified, and the document leaves the narrative out and says why. It is better to withhold a sentence than to
print a figure the data does not hold.
"""
import re
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

_TOKEN = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?")
MAX_PAIRS = 70   # how many figures take part in the derived shares and differences


def _norm(whole: str, fraction: str = "") -> str:
    whole = whole.replace(",", "")
    fraction = (fraction or "").rstrip("0").rstrip(".")
    return whole + (fraction if fraction not in ("", ".") else "")


def tokens_in(text) -> list:
    """The numbers written in a text, normalised (no thousands commas, no trailing zeros)."""
    return [_norm(m.group(1), m.group(2) or "") for m in _TOKEN.finditer(str(text or ""))]


def _is_year(token: str) -> bool:
    return len(token) == 4 and token.isdigit() and 1990 <= int(token) <= 2100


@dataclass
class Grounding:
    ok: bool
    unmatched: list = field(default_factory=list)
    checked: int = 0

    def sentence(self) -> str:
        if self.ok:
            return f"Every figure in this draft was found in the data of this report ({self.checked} checked)."
        shown = ", ".join(self.unmatched[:8]) + (" and more" if len(self.unmatched) > 8 else "")
        return f"This draft states figures that are not in the data of this report: {shown}."


def allowed_numbers(figures, extra=()) -> set:
    """Every number a faithful narrative may state about `figures` (a nested structure of numbers, names and lists)."""
    values, allowed = [], set()

    def walk(node):
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, (int, float)):
            number = Decimal(str(node))
            values.append(number)
            allowed.add(_plain(number))
            allowed.add(_plain(number.quantize(Decimal(1), rounding=ROUND_HALF_UP)))
        elif isinstance(node, str):
            allowed.update(tokens_in(node))
        elif isinstance(node, dict):
            for key, value in node.items():
                allowed.update(tokens_in(key))
                walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(figures)
    pool = [v for v in values if abs(v) < Decimal(10) ** 9][:MAX_PAIRS]
    for part in pool:
        for whole in pool:
            if whole > 0 and part >= 0:
                share = part * 100 / whole
                for mode in (ROUND_HALF_UP, ROUND_FLOOR):
                    rounded = share.quantize(Decimal(1), rounding=mode)
                    allowed.add(_plain(rounded))
                    allowed.add(_plain(Decimal(100) - rounded))
                allowed.add(_plain(share.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)))
                if whole >= part:
                    allowed.add(_plain(whole - part))
    for item in extra:
        allowed.update(tokens_in(str(item)))
    return allowed


def _plain(number: Decimal) -> str:
    text = format(number.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def check(text, figures, extra=()) -> Grounding:
    """Compare every number in `text` with the figures. `extra` adds numbers that are known to be fine (the day and year the
    report was generated)."""
    allowed = allowed_numbers(figures, extra)
    tokens = tokens_in(text)
    unmatched = []
    for token in tokens:
        if token in allowed or _is_year(token) or token in unmatched:
            continue
        unmatched.append(token)
    return Grounding(ok=not unmatched, unmatched=unmatched, checked=len(tokens))
