"""
Text written in Markdown (an AI drafted DPIA, the body of a continuity plan) as report blocks.

The pages show such text as typed. A document needs it as structure: each heading opens a titled block, a bullet or a numbered line
stays a line of that block, a pipe table becomes a table. Every non blank line is kept as its own line, so a person's list with one
item per line is not run together. Nothing here keeps markup: bold, italics, code and links are reduced to their text, and an image is
dropped.
"""
import re

from core.report_kit.model import Col, Paragraphs, Table

_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_SEPARATOR_CELL = re.compile(r":?-{2,}:?")


def plain(text) -> str:
    """One line of Markdown as plain text."""
    s = str(text or "")
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)                              # an image
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)                          # a link keeps its words
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)                               # bold
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", s)     # italics
    s = re.sub(r"`([^`]*)`", r"\1", s)                                      # code
    return s.replace("\\|", "|").strip()


def _table(lines, number) -> "Table | None":
    rows = [[plain(cell) for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))] for line in lines]
    rows = [r for r in rows if not all(_SEPARATOR_CELL.fullmatch(c.strip()) for c in r)]
    if len(rows) < 2:
        return None
    head, body = rows[0], rows[1:]
    columns = [Col(h, f"c{i}", weight=2.2 if i == len(head) - 1 else 1.0) for i, h in enumerate(head)]
    return Table("", columns, [{f"c{i}": r[i] if i < len(r) else "" for i in range(len(head))} for r in body], sheet_name=f"Text table {number}")


def blocks(text, first_title="Overview") -> list:
    """`Paragraphs` and `Table` blocks for Markdown text. Text before the first heading sits under `first_title`; a top level
    heading before any content is the document's own title and is dropped (the cover carries it)."""
    if not str(text or "").strip():
        return []
    out, lines, table = [], [], []
    state = {"title": first_title, "titled": False, "seen": False}

    def flush_lines():
        if lines or not state["titled"]:
            out.append(Paragraphs("" if state["titled"] else state["title"], list(lines)))
            state["titled"] = True
            lines.clear()

    def flush_table():
        block = _table(table, sum(isinstance(b, Table) for b in out) + 1)
        table.clear()
        if block is not None:
            out.append(block)

    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if line.lstrip().startswith("|"):
            if not table:
                flush_lines()
            table.append(line)
            state["seen"] = True
            continue
        if table:
            flush_table()
        heading = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if heading:
            if state["seen"]:
                flush_lines()
            level, title = len(heading.group(1)), plain(heading.group(2))
            if level == 1 and not state["seen"]:
                state["title"], state["titled"] = first_title, False
            else:
                state["title"], state["titled"] = title, False
            continue
        if not line.strip() or _RULE.match(line) or line.strip().startswith("```"):
            continue
        state["seen"] = True
        bullet = re.match(r"^\s*[-*+]\s+(.*)$", line)
        number = re.match(r"^\s*(\d+)[.)]\s+(.*)$", line)
        quote = re.match(r"^\s*>\s?(.*)$", line)
        if bullet:
            lines.append("• " + plain(bullet.group(1)))
        elif number:
            lines.append(f"{number.group(1)}. " + plain(number.group(2)))
        else:
            lines.append(plain(quote.group(1) if quote else line))
    if table:
        flush_table()
    flush_lines()
    return [b for b in out if not (isinstance(b, Paragraphs) and not b.title and not b.paragraphs)]
