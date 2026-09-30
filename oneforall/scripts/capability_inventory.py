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

This generator does NOT attempt to classify a capability as pilot-only,
deprecated, or planned -- those are product judgments a static scan cannot
make honestly. It produces the generated evidence (route, gate, capability,
role membership, license requirement) that a human curator then layers a
one-line maturity note over; see the `notes` column left blank in the
Markdown output.

Usage (from oneforall/):
    ..\\.venv\\Scripts\\python.exe scripts\\capability_inventory.py
Writes capability_inventory.json and capability_inventory.md next to this
script's own output directory (docs/generated/ by default).

Never imports with a real DATABASE_URL (forces "" like the test harness) --
this only ever needs to introspect route registration, never touch data.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "docs" / "generated"


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


def _flatten_routes(routes) -> list:
    """Recurse through FastAPI's _IncludedRouter wrappers (and any nested
    APIRouter.routes, in case of multiple include_router levels) down to
    real route objects that carry an .endpoint."""
    flat = []
    for r in routes:
        if hasattr(r, "endpoint"):
            flat.append(r)
            continue
        original = getattr(r, "original_router", None)
        if original is not None and hasattr(original, "routes"):
            flat.extend(_flatten_routes(original.routes))
            continue
        nested = getattr(r, "routes", None)
        if nested:
            flat.extend(_flatten_routes(nested))
    return flat


def _module_for(endpoint) -> str:
    real = endpoint
    while hasattr(real, "__wrapped__"):
        real = real.__wrapped__
    return getattr(real, "__module__", "?")


def build_inventory() -> dict:
    import main  # noqa: F401  -- import side effect registers every route
    from core.rbac import CAPABILITIES

    routes = _flatten_routes(main.app.routes)
    entries = []
    unknown_capabilities = set()

    for r in routes:
        path = getattr(r, "path", None)
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


def _write_markdown(inventory: dict, out_dir: Path) -> Path:
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
        "The `notes` column is intentionally blank: whether a capability is "
        "implemented, gated, configuration-required, pilot-only, deprecated, "
        "or planned is a product judgment this generator does not make. Add "
        "that note by hand once, next to the generated facts it can't fake.",
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
        lines.append("| Method | Path | Gate | Capability | Roles | License |")
        lines.append("|---|---|---|---|---|---|")
        for e in by_module[module]:
            methods = ",".join(e["methods"]) or "-"
            gate = e["gate"]
            caps = "<br>".join(e["capabilities"]) or "-"
            roles = "<br>".join(
                f"{c}: {', '.join(r) or '(none)'}" for c, r in e["roles_by_capability"].items()
            ) or "-"
            lic = ", ".join(e["license_modules_required"]) or "-"
            lines.append(f"| {methods} | `{e['path']}` | {gate} | {caps} | {roles} | {lic} |")
        lines.append("")

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "capability_inventory.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main_cli():
    inventory = build_inventory()
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
