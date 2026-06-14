#!/usr/bin/env python3
"""
Phase B migration: replace .lastrowid patterns with insert_returning_id().

Transformation:
    BEFORE:
        cur = db.execute("INSERT ...", params)
        ...optional lines...
        return cur.lastrowid       # OR: some_var = cur.lastrowid

    AFTER (return case):
        cur = insert_returning_id(db, "INSERT ...", params)
        ...optional lines...
        return cur

    AFTER (assignment case, some_var != cur):
        some_var = insert_returning_id(db, "INSERT ...", params)
        ...optional lines...
        [line removed]

The strategy:
    1. Find `cur_var = db_var.execute(` lines where INSERT follows within 10 lines.
    2. In the window [current_line, current_line+20], find `cur_var.lastrowid`.
    3. Replace the execute-start line: `cur_var = db_var.execute(` -> appropriate call.
    4. Replace / remove the lastrowid line.

This intentionally makes MINIMAL changes — only the first line of the execute
call and the lastrowid line are touched. All SQL string lines stay unchanged.

Usage:
    python scripts/phase_b_lastrowid.py --dry-run
    python scripts/phase_b_lastrowid.py --apply
"""
import re
import sys
import json
import argparse
import difflib
from pathlib import Path

ROOT = Path(__file__).parent.parent

# (relative-path, 1-based-line) pairs to skip
SKIP_LINES = {
    ("modules/grid/data_service.py", 221),  # cur2.lastrowid inside dict in loop
    ("modules/grid/data_service.py", 991),  # conditional: cur.lastrowid if cur.rowcount
    ("core/links.py", 76),                  # rowcount check needed — handle in Phase C ON CONFLICT refactor
    ("database.py", 68),                    # docstring
    ("database.py", 75),                    # insert_returning_id implementation itself
    ("database.py", 2462),                  # migration loop
}

WINDOW = 25  # max lines between execute() and .lastrowid


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def transform_file(path: Path, apply: bool) -> tuple[int, str, str]:
    """Return (changes, original_text, new_text)."""
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    n = len(lines)
    rel = _rel(path)
    skip_1based = {ln for (f, ln) in SKIP_LINES if f == rel}

    # Pattern: <indent><cursor_var> = <db_var>.execute(
    exec_re = re.compile(r'^(\s*)(\w+)\s*=\s*(\w+)\.(execute)\s*\(')

    result = list(lines)
    changes = 0
    already_has_import = "insert_returning_id" in original

    # Collect rewrites: {exec_line_idx: info_dict}
    # We scan forward; when we apply, we go in reverse order.
    rewrites = {}  # exec_line_idx -> info

    processed_lr_lines = set()  # avoid double-processing

    for i, line in enumerate(lines):
        lineno = i + 1
        if lineno in skip_1based:
            continue

        m = exec_re.match(line)
        if not m:
            continue

        indent, cur_var, db_var, _ = m.groups()

        # Quick check: is INSERT somewhere in the next WINDOW lines?
        snippet = "".join(lines[i : min(i + WINDOW, n)])
        if "INSERT" not in snippet.upper():
            continue

        # Search forward for cur_var.lastrowid within WINDOW lines
        lr_re = re.compile(r'(?<!\w)' + re.escape(cur_var) + r'\.lastrowid(?!\w)')
        found_lr_idx = -1
        for j in range(i + 1, min(i + WINDOW, n)):
            jlineno = j + 1
            if jlineno in skip_1based:
                continue
            if j in processed_lr_lines:
                continue
            if lr_re.search(lines[j]):
                found_lr_idx = j
                break

        if found_lr_idx < 0:
            continue

        # Also skip if the lastrowid line itself is in the skip set
        if (found_lr_idx + 1) in skip_1based:
            continue

        rewrites[i] = {
            "indent": indent,
            "cur_var": cur_var,
            "db_var": db_var,
            "exec_line": line,
            "lr_idx": found_lr_idx,
            "lr_line": lines[found_lr_idx],
        }
        processed_lr_lines.add(found_lr_idx)

    if not rewrites:
        return 0, original, original

    # Apply in reverse line order so indices stay valid
    for exec_idx in sorted(rewrites.keys(), reverse=True):
        info = rewrites[exec_idx]
        cur_var = info["cur_var"]
        db_var = info["db_var"]
        indent = info["indent"]
        lr_idx = info["lr_idx"]
        exec_line = info["exec_line"]
        lr_line = info["lr_line"]
        lr_re = re.compile(r'(?<!\w)' + re.escape(cur_var) + r'\.lastrowid(?!\w)')

        # ── Build the new execute-start line ────────────────────────────────
        # Replace: `cur_var = db_var.execute(`
        # With:    `cur_var = insert_returning_id(db_var,`
        # (We'll handle the lhs variable name based on the lr-line pattern.)

        # Determine what the lastrowid line does
        lr_stripped = lr_line.rstrip()

        # Pattern A: return cur_var.lastrowid
        pat_return = re.compile(
            r'^(\s*)return\s+' + re.escape(cur_var) + r'\.lastrowid(\s*(?:#.*)?)$'
        )
        # Pattern B: some_var = cur_var.lastrowid (some_var can == cur_var)
        pat_assign = re.compile(
            r'^(\s*)(\w+)\s*=\s*' + re.escape(cur_var) + r'\.lastrowid(\s*(?:#.*)?)$'
        )

        ra = pat_return.match(lr_stripped)
        ba = pat_assign.match(lr_stripped)

        if ra:
            # Change execute-start line to use cur_var = insert_returning_id(db_var,
            new_exec_line = exec_line.replace(
                f"{cur_var} = {db_var}.execute(",
                f"{cur_var} = insert_returning_id({db_var},",
                1,
            )
            # Change lastrowid line: return cur_var.lastrowid -> return cur_var
            new_lr_line = ra.group(1) + "return " + cur_var + ra.group(2) + "\n"

        elif ba:
            lhs_indent, lhs_var, comment = ba.groups()
            if lhs_var == cur_var:
                # same var: cur = cur.lastrowid (rare but possible)
                new_exec_line = exec_line.replace(
                    f"{cur_var} = {db_var}.execute(",
                    f"{cur_var} = insert_returning_id({db_var},",
                    1,
                )
                new_lr_line = None  # remove the redundant cur = cur.lastrowid line
            else:
                # different var: lhs_var = cur_var.lastrowid
                # → lhs_var = insert_returning_id(db_var, ...) AND remove cur_var assignment
                new_exec_line = exec_line.replace(
                    f"{cur_var} = {db_var}.execute(",
                    f"{lhs_var} = insert_returning_id({db_var},",
                    1,
                )
                new_lr_line = None  # remove lhs_var = cur_var.lastrowid line
        else:
            # Inline / complex — do a simple substitution on the lr line
            new_exec_line = exec_line.replace(
                f"{cur_var} = {db_var}.execute(",
                f"{cur_var} = insert_returning_id({db_var},",
                1,
            )
            new_lr_line = lr_re.sub(cur_var, lr_line)

        if new_exec_line == exec_line and (new_lr_line is None or new_lr_line == lr_line):
            continue  # no change (safety guard)

        # Apply
        result[exec_idx] = new_exec_line
        if new_lr_line is None:
            result[lr_idx] = ""   # blank the line (will be cleaned up below)
        else:
            result[lr_idx] = new_lr_line
        changes += 1

    if changes == 0:
        return 0, original, original

    # Remove blank lines we inserted (those we set to "")
    result = [l for l in result if l != ""]

    new_text = "".join(result)

    # Add import if needed
    if not already_has_import and "insert_returning_id" in new_text:
        new_text = _add_import(new_text)

    if apply and new_text != original:
        path.write_text(new_text, encoding="utf-8")

    return changes, original, new_text


def _add_import(text: str) -> str:
    """Add insert_returning_id to the database imports in the file."""
    # Case 1: there's a simple `from database import a, b` (no alias, no comment after names)
    # Find ALL `from database import` lines; pick the one we can safely extend.
    for m in re.finditer(r'^from database import ([^#\n]+)', text, re.MULTILINE):
        names_str = m.group(1).rstrip()
        # Skip if it contains `as` (aliased import — can't extend inline)
        if " as " in names_str:
            continue
        if "insert_returning_id" in names_str:
            return text  # already present
        new_line = f"from database import {names_str}, insert_returning_id"
        return text[:m.start()] + new_line + text[m.end():]

    # Case 2: `import database` — symbol reachable as database.insert_returning_id
    if re.search(r'^import database\b', text, re.MULTILINE):
        return text

    # Case 3: only aliased imports exist, or no database import at all.
    # Find the last `from database import` line and insert a new line after it.
    last_db_end = None
    for mm in re.finditer(r'^from database import [^\n]*\n', text, re.MULTILINE):
        last_db_end = mm.end()
    if last_db_end is not None:
        return text[:last_db_end] + "from database import insert_returning_id\n" + text[last_db_end:]

    # Fallback: inject after the last import line
    last_end = 0
    for mm in re.finditer(r'^(?:import |from )\S[^\n]*\n', text, re.MULTILINE):
        last_end = mm.end()
    if last_end:
        return text[:last_end] + "from database import insert_returning_id\n" + text[last_end:]
    return "from database import insert_returning_id\n" + text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--files", nargs="*")
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        print("Specify --dry-run or --apply")
        sys.exit(1)

    targets = [ROOT / f for f in args.files] if args.files else sorted(ROOT.rglob("*.py"))
    total_changes = 0
    manifest = []

    for path in targets:
        rel = _rel(path).replace("\\", "/")
        if rel.startswith("scripts/"):
            continue
        try:
            changes, original, new_text = transform_file(path, apply=args.apply)
        except Exception as e:
            print(f"  ERROR {rel}: {e}")
            import traceback; traceback.print_exc()
            continue

        if changes == 0:
            continue

        total_changes += changes
        manifest.append({"file": rel, "changes": changes})
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
            sys.stdout.buffer.write("".join(diff[:80]).encode("utf-8", errors="replace"))
            if len(diff) > 80:
                print(f"  ... ({len(diff) - 80} more diff lines)")

    print(f"\n{'-'*60}")
    print(f"Total: {total_changes} replacements across {len(manifest)} file(s)")

    if args.apply:
        mp = Path(__file__).parent / ".phase_b_manifest.json"
        mp.write_text(json.dumps(manifest, indent=2))
        print(f"Manifest: {mp}")


if __name__ == "__main__":
    main()
