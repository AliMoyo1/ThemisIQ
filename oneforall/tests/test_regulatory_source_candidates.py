"""A source change reaches Governance only after two distinct reviews."""
import pytest

from modules.sentinel import living_law as law
from modules.governance import source_candidates as candidates


FIRST = b"<html><body><p>Report a security incident when personal data is affected by the compromise and notify the competent regulator.</p></body></html>"
SECOND = b"<html><body><p>Report a security incident when personal data is affected by the compromise and notify the competent regulator. Keep an incident record.</p></body></html>"


def test_capture_requires_dpo_review_then_independent_governance_decision(test_db, monkeypatch):
    monkeypatch.setattr(law, "_active", lambda: {"UK GDPR"})
    monkeypatch.setattr(law, "_fetch", lambda url: FIRST)
    baseline = law.check_source(1, "uk_ico_breach")["capture_id"]
    law.review_capture(1, baseline, 3, "approved", "Verified source baseline.")
    with pytest.raises(ValueError, match="baseline"):
        candidates.propose(1, baseline, 7, {"framework_name": "UK GDPR", "title": "Change"})
    monkeypatch.setattr(law, "_fetch", lambda url: SECOND)
    changed = law.check_source(1, "uk_ico_breach")["capture_id"]
    with pytest.raises(ValueError, match="approved"):
        candidates.propose(1, changed, 7, {"framework_name": "UK GDPR", "title": "Change"})
    law.review_capture(1, changed, 3, "approved", "Verified source text; not a legal conclusion.")
    item = {"framework_name": "UK GDPR", "title": "Review incident record requirement",
            "summary": "Specialist interpretation pending", "affected_refs": "A.5.1"}
    cid = candidates.propose(1, changed, 7, item)
    assert candidates.propose(1, changed, 7, item) == cid
    assert candidates.list_pending(2) == []
    with pytest.raises(ValueError, match="independent"):
        candidates.decide(1, cid, 7, "approved", "Same person")
    result = candidates.decide(1, cid, 8, "approved", "Reviewed exact capture and affected references")
    assert result["update_id"]
    row = test_db.execute("SELECT source_capture_id,source_text_sha256,status,ai_summary "
                          "FROM regulatory_updates WHERE id=%s", (result["update_id"],)).fetchone()
    assert row["source_capture_id"] == changed
    assert row["source_text_sha256"] == law.capture_detail(1, changed)["text_sha256"]
    assert row["status"] == "processed" and row["ai_summary"] is None
    assert result["drift"]["updates"] == 1
    with pytest.raises(LookupError):
        candidates.decide(1, cid, 9, "approved", "Repeated review")


def test_tampered_capture_and_wrong_framework_are_rejected(test_db, monkeypatch):
    monkeypatch.setattr(law, "_active", lambda: {"UK GDPR"})
    monkeypatch.setattr(law, "_fetch", lambda url: FIRST)
    law.check_source(1, "uk_ico_breach")
    monkeypatch.setattr(law, "_fetch", lambda url: SECOND)
    changed = law.check_source(1, "uk_ico_breach")["capture_id"]
    law.review_capture(1, changed, 3, "approved", "Source reviewed")
    with pytest.raises(ValueError, match="mapped"):
        candidates.propose(1, changed, 7, {"framework_name": "ISO 27001", "title": "Wrong"})
    test_db.execute("UPDATE sentinel_law_captures SET extracted_text='altered' WHERE id=%s", (changed,))
    test_db.commit()
    with pytest.raises(ValueError, match="intact"):
        candidates.propose(1, changed, 7, {"framework_name": "UK GDPR", "title": "Tampered"})
