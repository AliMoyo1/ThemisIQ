"""
PLAN-36 T10: read-only capability inventory generator.

Introspects the REAL, running route table (not source-code text, so it is
immune to decorator aliasing like modules/launcher/routes_admin.py's
`_require_cap = require_capability`) to answer, for every registered route:
which auth gate protects it, which capability string that gate requires (if
any), which roles hold that capability per core/rbac.py's own CAPABILITIES
table, and whether it additionally requires an active module license.

How the introspection works: `require_auth`/`require_capability` (and
`require_module`, which is just `require_capability` under another name --
see core/middleware.py) both decorate with `@functools.wraps(func)`, which
preserves the wrapper's own `__closure__`/`__code__.co_freevars`. A route
that went through `require_capability("x", "y")` has a wrapper whose closure
contains a `capabilities` cell holding exactly `("x", "y")` -- reading that
cell is exact, not a guess, and works identically regardless of what name a
module imported the decorator under. A route that only went through
`require_auth` has a closure containing just `func`, no `capabilities`. A
route with neither is genuinely public.

This generator does NOT infer pilot-only, deprecated, or planned state from
route existence. Human-reviewed, exact route annotations live in
docs/capability_annotations.json and are merged into both generated outputs;
unreviewed routes keep a blank maturity cell. Missing documented routes fail
generation. The --check mode also compares both checked-in outputs to the
current registered route table and is wired into CI.

Usage (from oneforall/):
    ..\\.venv\\Scripts\\python.exe scripts\\capability_inventory.py
    ..\\.venv\\Scripts\\python.exe scripts\\capability_inventory.py --check
Writes capability_inventory.json and capability_inventory.md in
docs/generated/. Check mode reads them without changing files.

Never imports with a real DATABASE_URL (forces "" like the test harness) --
this only ever needs to introspect route registration, never touch data.
"""
from __future__ import annotations

import html
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

os.environ["DATABASE_URL"] = ""

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "docs" / "generated"
ANNOTATION_PATH = ROOT / "docs" / "capability_annotations.json"
MATURITY_STATES = {"implemented", "gated", "configuration-required", "pilot-only", "deprecated", "planned"}


def _decorator_info(endpoint) -> dict:
    """Return {"gate": "public"|"authenticated"|"capability", "capabilities": tuple|None}."""
    closure = endpoint.__closure__
    freevars = endpoint.__code__.co_freevars
    if not closure:
        return {"gate": "public", "capabilities": None}
    bound = dict(zip(freevars, (c.cell_contents for c in closure)))
    if "capabilities" in bound:
        return {"gate": "capability", "capabilities": tuple(bound["capabilities"])}
    if "func" in bound:
        return {"gate": "authenticated", "capabilities": None}
    return {"gate": "unknown", "capabilities": None}


def _flatten_routes(routes, prefix: str = "") -> list[tuple]:
    """Return (route, effective_path), preserving parent prefixes for nested
    FastAPI _IncludedRouter wrappers. Direct APIRoute.path values already
    include their owning APIRouter.prefix; nested child routes may not."""
    flat = []
    for r in routes:
        path = getattr(r, "path", None)
        if hasattr(r, "endpoint"):
            if prefix and path and not (path == prefix or path.startswith(prefix + "/")):
                path = prefix.rstrip("/") + path
            flat.append((r, path))
            continue
        original = getattr(r, "original_router", None)
        if original is not None and hasattr(original, "routes"):
            child = getattr(original, "prefix", "") or ""
            if not child:
                effective_prefix = prefix
            elif prefix and not (child == prefix or child.startswith(prefix + "/")):
                effective_prefix = prefix.rstrip("/") + child
            else:
                effective_prefix = child
            flat.extend(_flatten_routes(original.routes, effective_prefix))
            continue
        nested = getattr(r, "routes", None)
        if nested:
            flat.extend(_flatten_routes(nested, prefix))
    return flat


def _module_for(endpoint) -> str:
    real = endpoint
    while hasattr(real, "__wrapped__"):
        real = real.__wrapped__
    return getattr(real, "__module__", "?")


def _load_annotations() -> dict[str, dict[str, str]]:
    """Load reviewed route notes separately so regeneration never erases them."""
    data = json.loads(ANNOTATION_PATH.read_text(encoding="utf-8"))
    routes = data.get("routes")
    if not isinstance(routes, dict):
        raise ValueError("capability_annotations.json must contain a routes object")
    for key, annotation in routes.items():
        if not isinstance(key, str) or not isinstance(annotation, dict):
            raise ValueError("Invalid capability annotation entry")
        if annotation.get("maturity") not in MATURITY_STATES:
            raise ValueError(f"Invalid maturity for {key}")
        if not isinstance(annotation.get("notes", ""), str):
            raise ValueError(f"Invalid notes for {key}")
    return routes


def build_inventory() -> dict:
    import main  # noqa: F401  -- import side effect registers every route
    from core.rbac import CAPABILITIES

    routes = _flatten_routes(main.app.routes)
    entries = []
    unknown_capabilities = set()

    for r, path in routes:
        if path is None:
            continue
        methods = sorted(getattr(r, "methods", None) or [])
        info = _decorator_info(r.endpoint)
        caps = info["capabilities"] or ()
        roles_by_cap = {}
        license_required = []
        for cap in caps:
            roles = sorted(CAPABILITIES.get(cap, set()))
            roles_by_cap[cap] = roles
            if cap not in CAPABILITIES:
                unknown_capabilities.add(cap)
            if cap.startswith("module.") and cap.endswith(".access"):
                license_required.append(cap.split(".")[1])

        entries.append({
            "path": path,
            "methods": methods,
            "module": _module_for(r.endpoint),
            "gate": info["gate"],
            "capabilities": list(caps),
            "roles_by_capability": roles_by_cap,
            "license_modules_required": license_required,
            "name": getattr(r, "name", None),
        })

    entries.sort(key=lambda e: (e["module"], e["path"], e["methods"]))
    annotations = _load_annotations()
    route_keys = set()
    for entry in entries:
        key = f"{','.join(entry['methods']) or '-'} {entry['path']}"
        route_keys.add(key)
        annotation = annotations.get(key, {})
        entry["maturity"] = annotation.get("maturity", "")
        entry["notes"] = annotation.get("notes", "")
    stale = sorted(set(annotations) - route_keys)
    if stale:
        raise ValueError(f"Documented route identifiers no longer exist: {stale}")
    return {
        "route_count": len(entries),
        "entries": entries,
        "unknown_capabilities": sorted(unknown_capabilities),
    }


def _write_json(inventory: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "capability_inventory.json"
    path.write_text(json.dumps(inventory, indent=2, sort_keys=False), encoding="utf-8")
    return path


def _render_markdown(inventory: dict) -> str:
    by_module = defaultdict(list)
    for e in inventory["entries"]:
        by_module[e["module"]].append(e)

    lines = [
        "# ThemisIQ capability inventory (generated)",
        "",
        "Generated by `scripts/capability_inventory.py` (PLAN-36 T10) from the "
        "real route table, not source text -- see that file's own docstring "
        "for how the auth-gate/capability detection works and why it is "
        "exact rather than a best-effort scan.",
        "",
        "The `Maturity / notes` column comes from the human-reviewed "
        "`docs/capability_annotations.json`. Blank cells are unclassified. "
        "Edit that source file; regeneration preserves the annotations.",
        "",
    ]

    if inventory["unknown_capabilities"]:
        lines.append("## Capability strings with no role granted anywhere (likely a bug -- always denies everyone)")
        lines.append("")
        for cap in inventory["unknown_capabilities"]:
            lines.append(f"- `{cap}`")
        lines.append("")

    for module in sorted(by_module):
        lines.append(f"## `{module}`")
        lines.append("")
        lines.append("| Method | Path | Gate | Capability | Roles | License | Maturity / notes |")
        lines.append("|---|---|---|---|---|---|---|")
        for e in by_module[module]:
            methods = ",".join(e["methods"]) or "-"
            gate = e["gate"]
            caps = "<br>".join(e["capabilities"]) or "-"
            roles = "<br>".join(
                f"{c}: {', '.join(r) or '(none)'}" for c, r in e["roles_by_capability"].items()
            ) or "-"
            lic = ", ".join(e["license_modules_required"]) or "-"
            annotation = e["maturity"]
            if e["notes"]:
                note = html.escape(e["notes"]).replace("|", "&#124;").replace("\n", "<br>")
                annotation += ": " + note
            lines.append(f"| {methods} | `{e['path']}` | {gate} | {caps} | {roles} | {lic} | {annotation} |")
        lines.append("")

    return "\n".join(lines)


def _write_markdown(inventory: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "capability_inventory.md"
    path.write_text(_render_markdown(inventory), encoding="utf-8")
    return path


def main_cli():
    if sys.argv[1:] not in ([], ["--check"]):
        raise SystemExit("Usage: capability_inventory.py [--check]")
    inventory = build_inventory()
    if sys.argv[1:] == ["--check"]:
        path = OUT_DIR / "capability_inventory.json"
        if not path.exists() or json.loads(path.read_text(encoding="utf-8")) != inventory:
            raise SystemExit("Capability inventory drift: regenerate and review docs/generated/capability_inventory.json")
        md_path = OUT_DIR / "capability_inventory.md"
        if not md_path.exists() or md_path.read_text(encoding="utf-8") != _render_markdown(inventory):
            raise SystemExit("Capability inventory drift: regenerate and review docs/generated/capability_inventory.md")
        print("Capability inventory matches registered routes and reviewed annotations.")
        return
    json_path = _write_json(inventory, OUT_DIR)
    md_path = _write_markdown(inventory, OUT_DIR)
    print(f"{inventory['route_count']} routes inventoried.")
    if inventory["unknown_capabilities"]:
        print(f"WARNING: {len(inventory['unknown_capabilities'])} capability string(s) "
              f"granted to no role at all: {inventory['unknown_capabilities']}")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main_cli()
