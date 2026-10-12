

def test_ai_evaluations_regulation_and_monitoring_run_inside_a_tenant_on_real_postgres(pg):
    from modules.ai_governance import decisions, evaluations, guidance, monitoring, regulation, service

    run = {"name": "Citation check", "test_set_name": "aria-citations", "test_set_version": "v3", "rubric_version": "r2",
           "subject_version": "assistant 2026-09", "evaluator": "deterministic", "status": "completed",
           "started_at": "2026-10-01", "finished_at": "2026-10-01 10:30:00",
           "scores": {"citation_validity": 97.5, "no_match": 100}, "thresholds": {"citation_validity": 95}}

    pg.init_db()
    org, unit, ids, who = _ai_governance_world(pg, "aimon")
    author, reviewer, second = who["author"], who["reviewer"], who["second"]
    for index in ("idx_ai_evaluation_application", "idx_ai_regulatory_queue"):
        assert _raw_rows("SELECT count(*) FROM pg_indexes WHERE schemaname = 'tenant_aimon' AND indexname = %s", (index,)) == [(1,)], index

    with pg.tenant_context(org, "aimon", is_super_admin=False):
        db = pg.get_db()
        try:
            row = service.create_draft(db, author, _AI_GOOD)["intake"]
            db.commit()
            sent = service.submit(db, author, row["id"], row["version"])
            db.commit()
            app = service.approve(db, reviewer, row["id"], sent["intake"]["version"], new_application={"vendor_name": "Acme AI"})["application_id"]
            db.commit()
            profile = service.get_profile(db, reviewer, app)
            service.update_profile(db, reviewer, app, {"jurisdictions": ["EU"]}, profile["version"])
            guidance.set_step_not_applicable(db, reviewer, app, "vendor", "Built by us under licence.")
            db.commit()

            # evaluation records: the reading is computed, the list orders and compares, a failure raises one event
            good = evaluations.record_run(db, reviewer, app, run)
            bad = evaluations.record_run(db, reviewer, app, {**run, "name": "Worse", "scores": {"citation_validity": 70, "no_match": 100},
                                                            "finished_at": "2026-10-05 09:00:00"})
            db.commit()
            assert (good["run"]["state"], bad["run"]["state"], len(bad["events"])) == ("passed", "failed", 1)
            listed = evaluations.list_runs(db, author, app)
            assert [r["name"] for r in listed["runs"]] == ["Worse", "Citation check"] and listed["comparison"]["dimensions"][0]["change"] == -27.5
            accepted = evaluations.review_run(db, reviewer, good["run"]["id"], "accepted", None, 1)
            db.commit()
            assert accepted["run"]["review_outcome"] == "accepted"

            # regulatory impact: candidates are proposed once, confirmed into one task
            db.execute("INSERT INTO regulatory_updates (framework_name, title, status, severity, effective_date) "
                       "VALUES ('EU AI Act', 'Guidance on prohibited practices', 'open', 'high', '2026-12-01')")
            db.commit()
            assert regulation.refresh(db, reviewer)["created"] == 1
            db.commit()
            assert regulation.refresh(db, reviewer)["created"] == 0
            db.commit()
            item = regulation.list_queue(db, reviewer)["items"][0]
            done = regulation.review(db, reviewer, item["id"], "confirm", "EU customers.", item["version"])
            db.commit()
            assert done["item"]["status"] == "confirmed" and len(done["events"]) == 1
            assert db.execute("SELECT COUNT(*) FROM task_board WHERE title LIKE 'Regulatory change%'").fetchone()[0] == 1

            # monitoring reads all of it, and a decision reopens on what was recorded after it was signed
            watched = monitoring.get_monitoring(db, reviewer, app)
            assert {"evaluations", "regulation"} <= set(watched["attention"])
            asked = decisions.request_decision(db, author, app, None)
            db.commit()
            shown = decisions.get_brief(db, second, app)["hash"]
            signed = decisions.decide(db, second, asked["decision"]["id"], "approve", brief=shown, expected_version=1)
            db.commit()
            assert signed["decision"]["status"] == "approved"
            # what was recorded before the signing stands behind it; only what is recorded after reopens it
            db.execute("UPDATE ai_use_decisions SET decided_at = '2026-06-01 00:00:00' WHERE id = %s", (asked["decision"]["id"],))
            db.execute("UPDATE ai_evaluation_runs SET recorded_at = '2026-05-01 00:00:00'")
            db.execute("UPDATE ai_regulatory_impacts SET reviewed_at = '2026-05-01 00:00:00'")
            db.commit()
            assert decisions.get_decisions(db, author, app)["state"]["state"] == "approved"
            evaluations.record_run(db, reviewer, app, {**run, "name": "After signing", "scores": {"citation_validity": 60, "no_match": 100}})
            db.commit()
            reopened = decisions.get_decisions(db, author, app)["state"]
            assert reopened["state"] == "needs_re_review" and any("evaluation failed" in r for r in reopened["reasons"])
        finally:
            db.close()
