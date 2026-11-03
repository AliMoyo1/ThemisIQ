"""The framework register as figures: the share of each active framework's controls that are implemented (plan 22, C7).

One figure per framework, keyed `aria.framework_implemented:<slug>`. A framework from the built-in catalogue is named by
the catalogue's own text; a tenant's own frameworks are added together under `other` and never named, because their
names were typed by a person and must not cross to another organization.
"""
import re

from core import metric_registry as registry, metric_state as ms
from core.best_effort import swallowed
from database import EXPECTED_FRAMEWORKS
from modules.launcher.scoped_metrics import table_scope

KEY = "aria.framework_implemented"
CATALOGUE = {name: re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") for name, *_ in EXPECTED_FRAMEWORKS}


def _rows(db, user):
    cscope, cparams = table_scope("controls", user, "c")
    fscope, fparams = table_scope("frameworks", user, "f")
    return db.execute(
        "SELECT f.name AS name, COUNT(c.id) AS total, "
        f"SUM(CASE WHEN c.{registry.CONTROL_IMPLEMENTED} THEN 1 ELSE 0 END) AS done "
        "FROM frameworks f JOIN controls c ON c.framework_id = f.id "
        f"WHERE f.is_active = 1 AND {fscope} AND {cscope} GROUP BY f.name",
        [*fparams, *cparams]).fetchall()


def metrics(db, user) -> dict:
    if table_scope("controls", user)[0] == "(1 = 0)" or table_scope("frameworks", user)[0] == "(1 = 0)":
        return {}
    try:
        rows = _rows(db, user)
    except Exception:
        swallowed("Framework register figures")
        return {}
    counts = {}
    for row in rows:
        slug, name = (CATALOGUE[row["name"]], row["name"]) if row["name"] in CATALOGUE else ("other", "Other frameworks")
        _, done, total = counts.get(slug, (name, 0, 0))
        counts[slug] = (name, done + int(row["done"] or 0), total + int(row["total"] or 0))
    out = {}
    for slug, (name, done, total) in sorted(counts.items()):
        key = f"{KEY}:{slug}"
        out[key] = {**registry.build(KEY, ms.measured, round(done / total * 100),
                                     detail={"unit": "percent", "name": name, "implemented": done, "total": total}),
                    "key": key}
    return out
