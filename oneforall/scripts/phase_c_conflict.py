#!/usr/bin/env python3
"""
Phase C migration: INSERT OR IGNORE -> INSERT INTO ... ON CONFLICT DO NOTHING

Strategy:
  1. Mask triple-quoted strings to protect them from the single-string regex,
     transform them in-place, then restore.
  2. Transform adjacent double-quoted string blocks (the common multi-line SQL
     pattern) using STRBLOCK_RE.
  3. Flag INSERT OR REPLACE for manual review.

Usage:
    python scripts/phase_c_conflict.py --dry-run
    python scripts/phase_c_conflict.py --apply
"""
import re
import sys
import argparse
import difflib
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


# Matches triple-quoted strings (non-greedy, DOTALL)
_TRIPLE_RE = re.compile(r'"""[\s\S]*?"""', re.DOTALL)

# Matches one or more adjacent double-quoted string literals.
# Used AFTER masking triple-quoted strings so they don't interfere.
_STRBLOCK_RE = re.compile(r'"(?:[^"\\]|\\.)*"(?:\s*"(?:[^"\\]|\\.)*")*')


def _transform_triple(triple: str) -> tuple[str, int]:
    """Transform one triple-quoted string. Returns (new_text, n_changes)."""
    if "INSERT OR IGNORE INTO" not in triple.upper():
        return triple, 0
    # Step 1: remove OR IGNORE
    new = re.sub(
        r"INSERT\s+OR\s+IGNORE\s+INTO",
        "INSERT INTO",
        triple,
        flags=re.IGNORECASE,
    )
    # Step 2: append ON CONFLICT DO NOTHING on the last content line,
    # before the closing """
    clos = new.rfind('"""')
    if clos > 0:
        content_part = new[:clos]           # everything before closing """
        suffix = new[clos:]                 # closing """ (and nothing else)
        stripped = content_part.rstrip()    # trim trailing whitespace
        trailing_ws = content_part[len(stripped):]  # the whitespace we trimmed
        new = stripped + " ON CONFLICT DO NOTHING" + trailing_ws + suffix
    return new, 1


def _transform_strblock(block: str) -> tuple[str, int]:
    """Transform one adjacent-string block. Returns (new_block, n_changes)."""
    if "INSERT OR IGNORE INTO" not in block.upper():
        return block, 0
    # Step 1: remove OR IGNORE
    new = re.sub(
        r"INSERT\s+OR\s+IGNORE\s+INTO",
        "INSERT INTO",
        block,
        flags=re.IGNORECASE,
    )
    # Step 2: append ON CONFLICT DO NOTHING before the last closing "
    pos = new.rfind('"')
    if pos < 0:
        return new, 1
    inner = new[:pos]
    tail = new[pos + 1:]  # empty for a normal string block
    new = inner.rstrip() + " ON CONFLICT DO NOTHING" + '"' + tail
    return new, 1


def transform_file(path: Path, apply: bool):
    original = path.read_text(encoding="utf-8")
    uorig = original.upper()
    if "INSERT OR IGNORE INTO" not in uorig and "INSERT OR REPLACE INTO" not in uorig:
        return 0, original, original, []

    warnings: list[str] = []
    changes = 0
    text = original

    # ── Phase 1: mask triple-quoted strings ──────────────────────────────────
    placeholders: dict[str, str] = {}
    idx = [0]

    def mask_triple(m: re.Match) -> str:
        key = f'"__TQ{idx[0]}__"'
        idx[0] += 1
        new_triple, n = _transform_triple(m.group(0))
        nonlocal changes
        changes += n
        placeholders[key] = new_triple
        return key

    text = _TRIPLE_RE.sub(mask_triple, text)

    # ── Phase 2: transform regular string blocks ──────────────────────────────
    def repl_block(m: re.Match) -> str:
        nonlocal changes
        new, n = _transform_strblock(m.group(0))
        changes += n
        return new

    text = _STRBLOCK_RE.sub(repl_block, text)

    # ── Phase 3: restore triple-quoted strings ────────────────────────────────
    for key, triple in placeholders.items():
        text = text.replace(key, triple, 1)

    # ── Warnings: true manual-review cases only ───────────────────────────────
    # Only flag if INSERT OR IGNORE / OR REPLACE appears outside comments
    non_comment_lines = [
        ln for ln in text.splitlines()
        if not ln.lstrip().startswith("#") and "INSERT OR IGNORE INTO" in ln.upper()
    ]
    if non_comment_lines:
        warnings.append(
            f"  !! {_rel(path)}: INSERT OR IGNORE still present in non-comment line(s) "
            f"after transformation — check manually"
        )

    replace_lines = [
        ln for ln in text.splitlines()
        if not ln.lstrip().startswith("#") and "INSERT OR REPLACE" in ln.upper()
    ]
    if replace_lines:
        warnings.append(
            f"  !! {_rel(path)}: INSERT OR REPLACE — requires ON CONFLICT DO UPDATE SET, "
            f"handle manually"
        )

    if apply and text != original:
        path.write_text(text, encoding="utf-8")

    return changes, original, text, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        print("Specify --dry-run or --apply")
        sys.exit(1)

    targets = sorted(ROOT.rglob("*.py"))
    total_changes = 0
    all_warnings: list[str] = []

    for path in targets:
        rel = _rel(path)
        if rel.startswith("scripts/"):
            continue

        try:
            changes, original, new_text, warns = transform_file(path, apply=args.apply)
        except Exception as e:
            print(f"  ERROR {rel}: {e}")
            import traceback; traceback.print_exc()
            continue

        all_warnings.extend(warns)
        if changes == 0:
            continue

        total_changes += changes
        tag = "[DRY-RUN]" if args.dry_run else "[APPLIED]"
        print(f"\n{tag} {rel} -- {changes} replacement(s)")

        if args.dry_run:
            diff = list(difflib.unified_diff(
                original.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                n=2,
            ))
            sys.stdout.buffer.write(
                "".join(diff[:60]).encode("utf-8", errors="replace")
            )
            if len(diff) > 60:
                print(f"  ... ({len(diff) - 60} more diff lines)")

    print(f"\n{'-'*60}")
    print(f"Total: {total_changes} replacement(s)")

    if all_warnings:
        print("\nManual review required:")
        for w in all_warnings:
            print(w)


if __name__ == "__main__":
    main()
