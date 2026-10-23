"""
Record definitions for the privacy records (RoPA, DPIA, AI impact assessment), resolved per regulation.

    from modules.sentinel.record_profiles import get_profile
    profile = get_profile("ropa", "South Africa POPIA")
    profile.gaps(record)            # the required entries that are missing, with their legal anchors
    profile.prepare(data)           # validates what a form sent and splits it into columns and the JSON details

See `model.py` for what a profile can do and `regimes.py` for how a regulation changes it.
"""
from __future__ import annotations

from functools import lru_cache
from importlib import import_module

from modules.sentinel.record_profiles import regimes
from modules.sentinel.record_profiles.model import Cond, Field, Gap, Profile, RecordError, Section, flat_text, is_empty  # noqa: F401

RECORDS = {"ropa": "ropa", "dpia": "dpia", "aiia": "aiia"}


@lru_cache(maxsize=1)
def _all_options() -> dict:
    return regimes.all_list_options()


@lru_cache(maxsize=None)
def _sections(record: str) -> tuple:
    if record not in RECORDS:
        raise KeyError(f"No record definition called {record}")
    try:
        module = import_module(f"modules.sentinel.record_profiles.{RECORDS[record]}")
    except ModuleNotFoundError:
        raise KeyError(f"No record definition called {record}") from None
    return module.sections()


@lru_cache(maxsize=256)
def get_profile(record: str, regulation: str | None = None) -> Profile:
    """The definition of `record` as it reads under `regulation` (GDPR when none is given). Do not change what it returns: it is shared."""
    regime = dict(regimes.resolve(regulation))
    if record == "ropa" and regime["key"] == "South Africa POPIA":
        # POPIA section 17 refers to PAIA documentation. It does not prescribe
        # the GDPR Article 30 field inventory; keep that distinction visible.
        regime["record_basis"] = (
            "POPIA section 17 requires documentation of processing operations by reference to PAIA. "
            "The fields in this form are an operational register template, not a claim that POPIA prescribes "
            "every GDPR Article 30 field. A privacy specialist must approve the filed record."
        )
    if record == "dpia":
        regime["record_basis"] = regime["dpia_basis"]
    elif record == "aiia":
        regime["status"] = "internal_template"
        regime["record_basis"] = (
            "This is an internal AI impact assessment. The applicable legal duties and filing requirements "
            "need a separate specialist determination for the use and jurisdiction."
        )
    return Profile(record, regime, _sections(record), _all_options())


def regulations() -> list:
    return regimes.regulations()
