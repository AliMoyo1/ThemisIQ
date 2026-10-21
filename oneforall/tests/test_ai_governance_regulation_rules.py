"""
AI governance G5: the pure rules of regulatory impact. A framework name maps to jurisdictions by a fixed table and the
longest fragment wins; a name the table does not know matches nothing; a use is a candidate only when its intended
jurisdictions include one of them; and the digest of a change moves when any part of the change does.
"""
import pytest

from modules.ai_governance import explain, regulation


@pytest.mark.parametrize("name, expected", [
    ("EU AI Act", ["EU"]), ("Regulation (EU) 2024/1689, the Artificial Intelligence Act", ["EU"]), ("GDPR", ["EU"]),
    ("UK GDPR", ["UK"]), ("POPIA", ["ZA"]), ("Protection of Personal Information Act", ["ZA"]),
    ("Zimbabwe Cyber and Data Protection Act", ["ZW"]), ("NDPA 2023", ["NG"]), ("California CCPA", ["US"]),
    ("ISO/IEC 42001", []), ("NIST AI RMF", []), ("", []), (None, []),
])
def test_a_framework_name_maps_to_jurisdictions_by_the_fixed_table(name, expected):
    assert regulation.jurisdictions_for(name) == expected


def test_a_use_is_a_candidate_only_when_its_intended_jurisdictions_include_the_one_the_change_concerns():
    update = {"framework_name": "EU AI Act", "title": "Guidance on prohibited practices"}
    assert "EU" in regulation.matches(update, ["ZW", "EU"])
    assert regulation.matches(update, ["ZW", "ZA"]) is None
    assert regulation.matches(update, []) is None
    assert regulation.matches({"framework_name": "ISO/IEC 42001", "title": "x"}, ["EU"]) is None, "no jurisdiction, no match"


def test_the_digest_of_a_change_moves_when_any_part_of_it_does():
    base = {"framework_name": "EU AI Act", "title": "T", "summary": "S", "source_url": "https://x.example/a", "effective_date": "2026-12-01",
            "affected_refs": ""}
    first = regulation.fingerprint(base)
    assert regulation.fingerprint(dict(base)) == first and len(first) == 16
    for field, value in (("title", "T2"), ("summary", "S2"), ("source_url", "https://x.example/b"), ("effective_date", "2027-01-01"),
                         ("framework_name", "GDPR"), ("affected_refs", "Art. 5")):
        assert regulation.fingerprint({**base, field: value}) != first, field


# ── Explain: what a model's answer may keep ─────────────────────────────────

FACTS = [{"id": "F1", "text": "The use is at tier lower."}, {"id": "F2", "text": "Provider review is required and in progress."},
         {"id": "F3", "text": "Decision: No decision."}]


def test_only_sentences_that_cite_facts_they_were_given_are_kept():
    answer = ("The use is at a lower tier. [F1] The provider review is still open. [F2, F3] "
              "It is certainly compliant with every law. [F9] This sentence cites nothing. Nobody has decided yet [F3].")
    got = explain.validate_ai_text(answer, FACTS)
    assert [s["text"] for s in got] == ["The use is at a lower tier.", "The provider review is still open.", "Nobody has decided yet."]
    assert [s["cites"] for s in got] == [["F1"], ["F2", "F3"], ["F3"]]


def test_an_answer_that_cites_nothing_valid_leaves_nothing():
    assert explain.validate_ai_text("It is fine. [F7]\nAll good.", FACTS) == []
    assert explain.validate_ai_text("", FACTS) == []
    assert explain.validate_ai_text(None, FACTS) == []


def test_the_rule_account_is_every_fact_once_citing_itself():
    assert explain.rule_account(FACTS) == [{"text": f["text"], "cites": [f["id"]]} for f in FACTS]
