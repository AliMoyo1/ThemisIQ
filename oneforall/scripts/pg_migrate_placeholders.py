"""Phase G: Replace ? SQL placeholders with %s (psycopg2-style) across the codebase.

Uses Python's AST to find string literal SQL arguments.  Adjacent string
literals ("a" "b") are merged by the AST into one constant whose source
span covers both tokens, so the replacement is always correct.

f-strings are skipped and flagged as warnings — they need manual review.

Usage:
    python scripts/pg_migrate_placeholders.py [--dry-run | --apply]

Writes scripts/.placeholder_migration.json for auditability.
"""
import ast
import re
import sys
import json
import difflib
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Directories whose files should not be modified
_SKIP_DIRS = {"scripts", ".git", "__pycache__", "alembic", ".migration", "tests"}

# SQL keywords that identify a string literal as a SQL statement
_SQL_KW_RE = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|REPLACE|WITH|WHERE|VALUES)\b",
    re.IGNORECASE,
)

# Protect SQL string literals inside the SQL (e.g. WHERE name='O?Brien')
_SQL_STRLIT_RE = re.compile(r"'(?:''|[^'])*'")


def _replace_q_in_sql_raw(raw: str) -> str:
    """Replace ? → %s in a raw Python source slice, protecting SQL string literals."""
    parts, last = [], 0
    for m in _SQL_STRLIT_RE.finditer(raw):
        parts.append(raw[last:m.start()].replace("?", "%s"))
        parts.append(m.group(0))
        last = m.end()
    parts.append(raw[last:].replace("?", "%s"))
    return "".join(parts)


def _to_offset(lines: list[str], row: int, col: int) -> int:
    return sum(len(lines[i]) for i in range(row - 1)) + col


class _SQLVisitor(ast.NodeVisitor):
    def __init__(self, src: str):
        self.src = src
        self.lines = src.splitlines(keepends=True)
        self.replacements: list[tuple[int, int, str]] = []
        self.warnings: list[str] = []

    def visit_Constant(self, node: ast.Constant):
        if not isinstance(node.value, str):
            return
        sql = node.value
        if "?" not in sql or not _SQL_KW_RE.search(sql):
            return
        # Locate raw source span
        start = _to_offset(self.lines, node.lineno, node.col_offset)
        end = _to_offset(self.lines, node.end_lineno, node.end_col_offset)
        raw = self.src[start:end]
        # Skip f-strings
        if re.match(r"[rRbBuU]*[fF]", raw):
            self.warnings.append(
                f"  line {node.lineno}: f-string SQL with ? — manual review needed"
            )
            return
        new_raw = _replace_q_in_sql_raw(raw)
        if new_raw != raw:
            self.replacements.append((start, end, new_raw))

    # Also visit JoinedStr so we can warn about f-strings
    def visit_JoinedStr(self, node: ast.JoinedStr):
        # Reconstruct constant parts to check for ?
        parts = [
            n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]
        if any("?" in p for p in parts):
            self.warnings.append(
                f"  line {node.lineno}: f-string SQL with ? — manual review needed"
            )


def process_source(src: str) -> tuple[str, int, list[str]]:
    """Returns (new_src, total_replacements, warnings)."""
    try:
        tree = ast.parse(src, type_comments=False)
    except SyntaxError as e:
        return src, 0, [f"  SyntaxError: {e}"]

    visitor = _SQLVisitor(src)
    visitor.visit(tree)

    if not visitor.replacements:
        return src, 0, visitor.warnings

    # Apply in reverse offset order to preserve positions
    result = src
    for start, end, new_raw in sorted(visitor.replacements, reverse=True):
        result = result[:start] + new_raw + result[end:]

    total = sum(src[s:e].count("?") for s, e, _ in visitor.replacements)
    return result, total, visitor.warnings


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


def main():
    dry_run = "--apply" not in sys.argv
    if "--dry-run" not in sys.argv and "--apply" not in sys.argv:
        print("Usage: pg_migrate_placeholders.py [--dry-run | --apply]")
        print("Defaulting to --dry-run")

    py_files = sorted(
        p for p in ROOT.rglob("*.py")
        if not any(part in _SKIP_DIRS for part in p.relative_to(ROOT).parts)
    )

    manifest: dict[str, int] = {}
    files_changed = 0
    total_replacements = 0

    for path in py_files:
        src = path.read_text(encoding="utf-8")
        new_src, count, warns = process_source(src)
        if warns:
            print(f"[WARN] {_rel(path)}:")
            for w in warns:
                print(w)
        if count == 0:
            continue
        files_changed += 1
        total_replacements += count
        manifest[_rel(path)] = count
        if dry_run:
            diff = difflib.unified_diff(
                src.splitlines(keepends=True),
                new_src.splitlines(keepends=True),
                fromfile=f"a/{_rel(path)}",
                tofile=f"b/{_rel(path)}",
                n=2,
            )
            sys.stdout.writelines(diff)
        else:
            path.write_text(new_src, encoding="utf-8")
            print(f"  {_rel(path)}: {count} replacements")

    mode = "DRY RUN — " if dry_run else ""
    print(f"\n{mode}{files_changed} files, {total_replacements} replacements")

    if not dry_run:
        mf = Path(__file__).parent / ".placeholder_migration.json"
        mf.write_text(json.dumps(manifest, indent=2))
        print(f"Manifest → {mf}")


if __name__ == "__main__":
    main()
