"""Official-source monitoring must remain scoped, reviewable, and extractive."""
import pytest

from modules.sentinel import living_law as law


HTML_A = b"<html><body><h1>Personal data breaches</h1><p>Where a personal data breach is likely to result in a risk to individuals, notify the supervisory authority without undue delay.</p></body></html>"
HTML_B = b"<html><body><h1>Personal data breaches</h1><p>Where a personal data breach is likely to result in a risk to individuals, notify the supervisory authority without undue delay and record the incident.</p></body></html>"


def test_capture_review_citations_and_tenant_masking(test_db, monkeypatch):
    monkeypatch.setattr(law, "_active", lambda: {"UK GDPR"})
    monkeypatch.setattr(law, "_fetch", lambda url: HTML_A)
    first = law.check_source(1, "uk_ico_breach")
    assert first["result"] == "baseline_pending_review"
    assert law.checked_within_hour(1, "uk_ico_breach") is True
    assert law.check_source(1, "uk_ico_breach")["result"] == "unchanged"
    capture_id = first["capture_id"]
    assert law.capture_detail(1, capture_id)["hash_verified"] is True
    assert "without undue delay" in law.capture_detail(1, capture_id)["captured_text"]
    with pytest.raises(LookupError):
        law.capture_detail(2, capture_id)
    assert law.ask(1, "When must a personal data breach notify the authority?")["verified"] is False
    law.review_capture(1, capture_id, 7, "approved", "Reviewed against the ICO page; usable for source retrieval.")
    answer = law.ask(1, "When must a personal data breach notify the authority?")
    assert answer["verified"] is True
    assert answer["tokens_used"] == 0
    assert answer["citations"][0]["capture_id"] == capture_id
    assert "ico.org.uk" in answer["citations"][0]["source_url"]
    assert law.ask(2, "When must a personal data breach notify the authority?")["verified"] is False
    with pytest.raises(ValueError):
        law.ask(1, "When must a personal data breach notify the authority?", "GDPR")

    monkeypatch.setattr(law, "_fetch", lambda url: HTML_B)
    second = law.check_source(1, "uk_ico_breach")
    assert second["result"] == "change_pending_review"
    assert law.capture_detail(1, second["capture_id"])["review_state"] == "pending"
    with pytest.raises(LookupError):
        law.review_capture(1, capture_id, 7, "approved", "Late approval of an old version")
    assert [row["id"] for row in law.list_sources(1)[0]["recent_captures"]] == [second["capture_id"], capture_id]
    # An unapproved change never replaces the previously approved corpus.
    answer = law.ask(1, "When must a personal data breach notify the authority?")
    assert answer["citations"][0]["capture_id"] == capture_id
    assert answer["citations"][0]["newer_unapproved_capture_exists"] is True


def test_schedule_validation_source_allowlist_and_failed_check(test_db, monkeypatch):
    monkeypatch.setattr(law, "_active", lambda: {"UK GDPR"})
    assert law.get_cadence(1) == "weekly"
    law.set_cadence(1, "monthly", 7)
    assert law.get_cadence(1) == "monthly"
    assert law.get_cadence(2) == "weekly"
    with pytest.raises(ValueError):
        law.set_cadence(1, "hourly", 7)
    with pytest.raises(ValueError):
        law.set_cadence(1, ["weekly"], 7)
    with pytest.raises(ValueError):
        law._fetch("https://127.0.0.1/private")
    monkeypatch.setattr(law, "_fetch", lambda url: (_ for _ in ()).throw(ValueError("HTTP 503")))
    failed = law.check_source(1, "uk_ico_breach")
    assert failed["result"] == "error"
    assert law.list_sources(1)[0]["last_result"] == "error"
    with pytest.raises(ValueError):
        law.check_source(1, "eu_gdpr")
    with pytest.raises(ValueError):
        law.check_source(1, ["uk_ico_breach"])


def test_law_monitor_capabilities_are_privacy_scoped():
    from core.rbac import has_capability

    dpo = {"id": 7, "org_id": 1, "roles": ["dpo"]}
    employee = {"id": 8, "org_id": 1, "roles": ["employee"]}
    assert has_capability(dpo, "module.sentinel.access")
    assert has_capability(dpo, "sentinel.jurisdiction.approve")
    assert not has_capability(employee, "module.sentinel.access")
    assert not has_capability(employee, "sentinel.jurisdiction.approve")


def test_corrupt_capture_cannot_be_approved(test_db, monkeypatch):
    monkeypatch.setattr(law, "_active", lambda: {"UK GDPR"})
    monkeypatch.setattr(law, "_fetch", lambda url: HTML_A)
    capture_id = law.check_source(1, "uk_ico_breach")["capture_id"]
    test_db.execute("UPDATE sentinel_law_captures SET captured_html_gzip_b64='bad' WHERE id=%s", (capture_id,))
    test_db.commit()
    assert law.capture_detail(1, capture_id)["hash_verified"] is False
    with pytest.raises(ValueError, match="hash check"):
        law.review_capture(1, capture_id, 7, "approved", "Reviewed")


def test_ask_refuses_tampered_approved_text(test_db, monkeypatch):
    monkeypatch.setattr(law, "_active", lambda: {"UK GDPR"})
    monkeypatch.setattr(law, "_fetch", lambda url: HTML_A)
    capture_id = law.check_source(1, "uk_ico_breach")["capture_id"]
    law.review_capture(1, capture_id, 7, "approved", "Checked source and scope.")
    test_db.execute("UPDATE sentinel_law_captures SET extracted_text='Fake legal rule' WHERE id=%s", (capture_id,))
    test_db.commit()
    result = law.ask(1, "When must a personal data breach notify the authority?")
    assert result["verified"] is False and result["citations"] == []


def test_approved_capture_with_changed_source_url_is_not_cited(test_db, monkeypatch):
    monkeypatch.setattr(law, "_active", lambda: {"UK GDPR"})
    monkeypatch.setattr(law, "_fetch", lambda url: HTML_A)
    capture_id = law.check_source(1, "uk_ico_breach")["capture_id"]
    law.review_capture(1, capture_id, 7, "approved", "Checked source and scope.")
    test_db.execute("UPDATE sentinel_law_captures SET source_url='https://example.invalid' WHERE id=%s", (capture_id,))
    test_db.commit()
    assert law.capture_detail(1, capture_id)["hash_verified"] is False
    assert law.ask(1, "When must a personal data breach notify the authority?")["citations"] == []


def test_scheduled_pass_reuses_public_fetch_but_stores_each_org_separately(test_db, monkeypatch):
    monkeypatch.setattr(law, "_active", lambda: {"UK GDPR"})
    monkeypatch.setattr(law, "SOURCES", {"uk_ico_breach": law.SOURCES["uk_ico_breach"]})
    fetched = []
    monkeypatch.setattr(law, "_fetch", lambda url: fetched.append(url) or HTML_A)
    cache = {}
    assert law.check_due(1, fetched=cache)[0]["result"] == "baseline_pending_review"
    assert law.check_due(2, fetched=cache)[0]["result"] == "baseline_pending_review"
    assert len(fetched) == 1
    assert law.list_sources(1)[0]["latest_capture"]["id"] != law.list_sources(2)[0]["latest_capture"]["id"]


def test_official_pdf_extracts_only_through_bounded_worker(monkeypatch, tmp_path):
    from modules.evidence import indexer
    monkeypatch.setattr(law.tempfile, "tempdir", str(tmp_path))
    seen = []

    def worker(path):
        seen.append(path.read_bytes())
        content = "The regulator says a security compromise must be reviewed. " * 3
        return {"status": "indexed", "text": content,
                "segments": [{"label": "Page 1", "start": 0, "end": len(content)}]}

    monkeypatch.setattr(indexer, "_child", worker)
    text = law._extract_pdf(b"%PDF-test")
    assert seen == [b"%PDF-test"] and "Page 1 |" in text
    monkeypatch.setattr(indexer, "_child", lambda path: {"status": "failed", "text": "", "segments": []})
    with pytest.raises(ValueError, match="safely extracted"):
        law._extract_pdf(b"%PDF-test")


def test_connected_impact_counts_only_visible_unit_records(test_db, monkeypatch):
    monkeypatch.setattr(law, "_active", lambda: {"UK GDPR"})
    monkeypatch.setattr(law, "_fetch", lambda url: HTML_A)
    capture_id = law.check_source(1, "uk_ico_breach")["capture_id"]
    a = test_db.execute("INSERT INTO business_units (name,is_active) VALUES ('A',1)").lastrowid
    b = test_db.execute("INSERT INTO business_units (name,is_active) VALUES ('B',1)").lastrowid
    for ref, unit in (("LAW-A", a), ("LAW-B", b), ("LAW-GLOBAL", None)):
        test_db.execute("INSERT INTO sentinel_ropa (ref_number,processing_name,regulation,business_unit_id) "
                        "VALUES (%s,%s,'UK GDPR',%s)", (ref, ref, unit))
    test_db.commit()
    assert law.impact_summary(1, capture_id, [a])["records_in_your_scope"]["RoPA"] == 2
    assert law.impact_summary(1, capture_id, [])["records_in_your_scope"]["RoPA"] == 1
    assert law.impact_summary(1, capture_id, None)["records_in_your_scope"]["RoPA"] == 3
    with pytest.raises(LookupError):
        law.impact_summary(2, capture_id, None)


def test_optional_ai_draft_binds_only_retrieved_citation_ids(monkeypatch):
    from core import ai_client, ai_policy
    retrieved = {"citations": [{"source_url": "https://ico.org.uk/", "excerpt": "Breach reporting guidance",
                                 "jurisdiction": "UK GDPR", "capture_id": 1}], "verified": True}
    seen = {}

    def model(messages, system, max_tokens, *, feature, sources):
        seen.update(feature=feature, sources=sources, prompt=messages[0]["content"])
        return {"text": '{"answer":"A draft based on source one.","citation_ids":[1]}',
                "input_tokens": 24, "output_tokens": 10}

    monkeypatch.setattr(ai_client, "create_message_full", model)
    answer = law.draft_answer("What should we review?", retrieved)
    assert answer["verified"] is False and answer["citations"] == retrieved["citations"]
    assert answer["tokens_used"] == 34 and seen["feature"] == "sentinel.ai_law_answer"
    assert ai_policy.FEATURES["sentinel.ai_law_answer"][1] == ("public", "personal")
    monkeypatch.setattr(ai_client, "create_message_full", lambda *a, **k:
                        {"text": '{"answer":"Unsupported","citation_ids":[2]}'})
    with pytest.raises(ValueError, match="citation bindings"):
        law.draft_answer("What should we review?", retrieved)


def test_retention_review_and_legal_hold_are_org_scoped(test_db, monkeypatch):
    monkeypatch.setattr(law, "_active", lambda: {"UK GDPR"})
    monkeypatch.setattr(law, "_fetch", lambda url: HTML_A)
    capture_id = law.check_source(1, "uk_ico_breach")["capture_id"]
    assert law.get_retention_days(1) == 2555
    law.set_retention_days(1, 30, 7)
    assert law.get_retention_days(1) == 30 and law.get_retention_days(2) == 2555
    with pytest.raises(ValueError):
        law.set_retention_days(1, True, 7)
    test_db.execute("UPDATE sentinel_law_captures SET captured_at='2020-01-01' WHERE id=%s", (capture_id,))
    test_db.commit()
    assert law.capture_detail(1, capture_id)["retention_review_due"] is True
    law.set_hold(1, capture_id, 7, True, "Preserve for legal review")
    assert law.capture_detail(1, capture_id)["retention_review_due"] is False
    with pytest.raises(LookupError):
        law.set_hold(2, capture_id, 8, False, "Release")
    law.set_hold(1, capture_id, 7, False, "Review completed")
    assert law.capture_detail(1, capture_id)["retention_review_due"] is True
