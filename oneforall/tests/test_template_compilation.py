"""
PLAN-36 T09 ("Run JavaScript syntax/unit tests and Jinja compilation with
real filters"). The original 2026-09-24 audit compiled every template with
the application's registered filters (findings.md section 1, 60 templates
at that time) but that check was never saved as a repeatable test -- this
file makes it one.

Importing `main` (which imports every route module) is what actually
registers every custom filter (`format_dt`, `tojson`, etc.) -- they are
attached ad hoc, per module, onto that module's own `Jinja2Templates`
instance (e.g. `modules/aria/routes.py:50`), not through one central
registry, and different modules construct their own separate instance of
the same name (`templates`/`shell_templates`) with different search paths
and different filters registered. This walks every
`starlette.templating.Jinja2Templates` instance that importing `main`
leaves behind in `sys.modules`, and compiles every `.html` file any of them
can reach through the *union* of every search path and every registered
filter across all of them (see the test's own docstring for why a
per-instance-only check produces a false positive here).
"""
import sys
from pathlib import Path

import jinja2
from starlette.templating import Jinja2Templates

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _all_jinja_templates_instances():
    import main  # noqa: F401 -- import side effect registers every module's filters

    seen = set()
    instances = []
    for mod in list(sys.modules.values()):
        if mod is None:
            continue
        for _, value in vars(mod).items():
            if isinstance(value, Jinja2Templates) and id(value) not in seen:
                seen.add(id(value))
                instances.append(value)
    return instances


def _html_files_for(templates: Jinja2Templates):
    loader = templates.env.loader
    searchpath = getattr(loader, "searchpath", None) or []
    found = {}
    for base in searchpath:
        base_path = Path(base)
        if not base_path.is_absolute():
            base_path = ROOT / base_path
        if not base_path.is_dir():
            continue
        for html_file in base_path.rglob("*.html"):
            rel = html_file.relative_to(base_path).as_posix()
            found.setdefault(rel, html_file)
    return found


def test_every_reachable_template_compiles_with_its_registered_filters():
    """Compiles every template file with the UNION of every filter registered
    on any Jinja2Templates instance in the app, not template-by-template
    against only the one instance whose search path happens to list it
    first. Several modules construct their own separate
    `Jinja2Templates(directory=["templates", "modules/X/templates"])`
    instance that also resolves shared-directory files like
    `templates/profile.html` (the same instance-per-module pattern
    documented in modules/evidence/routes.py), without every module
    re-registering every filter used elsewhere -- e.g. profile.html uses
    `format_dt`, registered on modules/launcher's own `shell_templates`, but
    is also syntactically reachable through modules/evidence's differently
    constructed instance of the same name, which never got that filter.
    That is real but not a defect: routes_auth.py's actual profile route
    imports and renders through the launcher instance, which does have it.
    A per-instance-only check would false-positive on that; the union check
    below still catches the real defect class this exists for -- a filter
    referenced that no instance anywhere has registered, i.e. a genuine
    typo or missing registration -- without asserting a specific
    module/template pairing this file has no way to verify is the real one."""
    instances = _all_jinja_templates_instances()

    all_searchpaths = []
    for templates in instances:
        for base in getattr(templates.env.loader, "searchpath", None) or []:
            if base not in all_searchpaths:
                all_searchpaths.append(base)

    union_env = jinja2.Environment(loader=jinja2.FileSystemLoader(all_searchpaths))
    for templates in instances:
        union_env.filters.update(templates.env.filters)

    files = {}
    for templates in instances:
        files.update(_html_files_for(templates))

    failures = []
    for rel_name, path in files.items():
        try:
            union_env.get_template(rel_name)
        except Exception as exc:
            failures.append(f"{path}: {exc}")

    # A sanity floor only, not a replica of the original 2026-09-24 audit's
    # count of 60 -- that number is from a different discovery method (a
    # live crawl) and the template set has legitimately grown and shrunk
    # since. This just catches discovery silently finding nothing (e.g. an
    # import error swallowed somewhere), not a specific expected total.
    assert len(files) >= 30, (
        f"only found {len(files)} templates across every discovered Jinja2Templates "
        "instance -- suspiciously low, check that importing main above actually "
        "registered every module's templates object"
    )
    assert not failures, "Template compilation failures:\n" + "\n".join(failures)
