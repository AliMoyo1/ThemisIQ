"""Themis quotes only exact, current indexed bytes the viewer may open."""

import json

from core import themis_retrieval, themis_work
from tests.test_relationships import APP, AIIA, _link, _ref, graph  # noqa: F401
from tests.test_platform_ownership import _insert, signed_in, world  # noqa: F401


def _file(graph, tag, text, *, review="accepted", index_hash=None, status="current"):
    db = graph.db
    evidence_id = _insert(db, "evidence_items", title=f"Policy {tag}", org_id=1,
                          business_unit_id=graph.unit[tag], status=status, version=2,
                          file_hash=f"hash-{tag}")
    db.execute("INSERT INTO evidence_text_index "
               "(evidence_id,org_id,business_unit_id,file_hash,indexer_version,status,content_text,segments_json) "
               "VALUES (%s,1,%s,%s,'test','indexed',%s,%s)",
               (evidence_id, graph.unit[tag], index_hash or f"hash-{tag}", text,
                json.dumps([{"label": "Continuity", "start": 0, "end": len(text)}])))
    record_id = graph.rec2[(APP, tag)]
    db.execute("INSERT INTO evidence_links "
               "(evidence_id,module,entity_type,entity_id,review_status) "
               "VALUES (%s,'governance','application',%s,%s)", (evidence_id, record_id, review))
    db.commit()
    return evidence_id


def test_exact_passage_and_version_are_cited_for_selected_record(graph):
    text = "Payments continuity policy requires recovery within four hours."
    evidence_id = _file(graph, "A", text)
    viewer = graph.users["dpo_a"]
    application_id = graph.rec2[(APP, "A")]
    result = themis_retrieval.search(graph.db, viewer, APP, application_id,
                                    "What does the policy say about recovery?")
    assert len(result) == 1
    cited = result[0]
    assert (cited["evidence_id"], cited["version"], cited["file_hash"]) == (evidence_id, 2, "hash-A")
    assert cited["quote"] == text[cited["start"]:cited["end"]]
    assert cited["section"] == "Continuity"
    answer = themis_work._document_answer(graph.db, viewer, APP, application_id,
                                          "What does the policy say about recovery?")
    assert "[1]" in answer["answer"] and "four hours" in answer["answer"]
    assert answer["sources"][0]["file_hash"] == "hash-A"


def test_scope_review_current_version_and_index_hash_all_fail_closed(graph):
    visible = _file(graph, "A", "Recovery requires four hours.")
    _file(graph, "B", "Recovery secret canary in unit B.")
    stale = _file(graph, "org", "Recovery stale canary.", index_hash="old-hash")
    pending = _file(graph, "A1", "Recovery pending canary.", review="pending")
    viewer = graph.users["dpo_a"]
    application_id = graph.rec2[(APP, "A")]
    for tag in ("B", "org", "A1"):
        assert _link(graph, graph.users["super"], _ref(graph, AIIA, tag),
                     _ref(graph, APP, "A"), "assesses")[1] is None
    answer = themis_work._document_answer(graph.db, viewer, APP, application_id,
                                          "What does the document say about recovery?")
    assert [source["record_id"] for source in answer["sources"]] == [visible]
    assert "canary" not in str(answer)
    assert themis_retrieval.search(graph.db, graph.users["dpo_b"], APP, application_id,
                                   "recovery") is None
    graph.db.execute("UPDATE evidence_items SET status='superseded' WHERE id=%s", (visible,))
    graph.db.commit()
    assert themis_retrieval.search(graph.db, viewer, APP, application_id, "recovery") == []
    assert stale != pending


def test_unconfirmed_relationship_does_not_expand_search(graph):
    _file(graph, "A1", "Recovery candidate canary.")
    app = _ref(graph, APP, "A")
    candidate = _ref(graph, AIIA, "A1")
    made, error = _link(graph, graph.users["super"], candidate, app, "assesses",
                        provenance="system_candidate")
    assert error is None
    graph.db.execute("UPDATE cross_module_links SET status='candidate' WHERE id=%s", (made["link_id"],))
    graph.db.commit()
    assert themis_retrieval.search(graph.db, graph.users["dpo_a"], APP, app[2], "recovery") == []


def test_relevant_file_is_found_after_many_unrelated_linked_files(graph):
    for number in range(42):
        _file(graph, "A", f"Annual policy filing note {number}.")
    last = _file(graph, "A", "Recovery requires four hours.")
    results = themis_retrieval.search(graph.db, graph.users["dpo_a"], APP,
                                      graph.rec2[(APP, "A")], "What does the policy say about recovery?")
    assert [row["evidence_id"] for row in results] == [last]


def test_retrieval_searches_beyond_the_connected_panel_and_first_id_batch(graph):
    db = graph.db
    app_id = graph.rec2[(APP, "A")]
    relevant = None
    for number in range(260):
        text = "Recovery takes four hours." if number == 259 else f"Annual filing note {number}."
        cur = db.execute("INSERT INTO evidence_items "
                         "(title,org_id,business_unit_id,status,version,file_hash) "
                         "VALUES (%s,1,%s,'current',1,%s)",
                         (f"Policy {number}", graph.unit["A"], f"batch-hash-{number}"))
        file_id = cur.lastrowid
        db.execute("INSERT INTO evidence_text_index "
                   "(evidence_id,org_id,business_unit_id,file_hash,indexer_version,status,content_text) "
                   "VALUES (%s,1,%s,%s,'test','indexed',%s)",
                   (file_id, graph.unit["A"], f"batch-hash-{number}", text))
        db.execute("INSERT INTO evidence_links "
                   "(evidence_id,module,entity_type,entity_id,review_status) "
                   "VALUES (%s,'governance','application',%s,'accepted')", (file_id, app_id))
        if number == 259:
            relevant = file_id
    db.commit()
    result = themis_retrieval.search(db, graph.users["dpo_a"], APP, app_id,
                                     "What does the policy say about recovery?")
    assert [row["evidence_id"] for row in result] == [relevant]


def test_retrieval_finds_a_cited_file_in_five_thousand_scoped_links(graph):
    """A large Vault must not turn an older relevant item into an abstention."""
    db = graph.db
    app_id = graph.rec2[(APP, "A")]
    unit_id = graph.unit["A"]
    db.executemany(
        "INSERT INTO evidence_items (title,org_id,business_unit_id,status,version,file_hash) "
        "VALUES (%s,1,%s,'current',1,%s)",
        [(f"Load policy {number:04d}", unit_id, f"load-hash-{number:04d}")
         for number in range(5000)],
    )
    files = db.execute(
        "SELECT id,file_hash FROM evidence_items WHERE title LIKE 'Load policy %' ORDER BY id"
    ).fetchall()
    assert len(files) == 5000
    db.executemany(
        "INSERT INTO evidence_text_index "
        "(evidence_id,org_id,business_unit_id,file_hash,indexer_version,status,content_text) "
        "VALUES (%s,1,%s,%s,'test','indexed',%s)",
        [(row["id"], unit_id, row["file_hash"],
          "Recovery must complete within four hours." if number == 4999 else "Annual filing note.")
         for number, row in enumerate(files)],
    )
    db.executemany(
        "INSERT INTO evidence_links (evidence_id,module,entity_type,entity_id,review_status) "
        "VALUES (%s,'governance','application',%s,'accepted')",
        [(row["id"], app_id) for row in files],
    )
    db.commit()
    result = themis_retrieval.search(db, graph.users["dpo_a"], APP, app_id,
                                    "What does the policy say about recovery?")
    assert [row["evidence_id"] for row in result] == [files[-1]["id"]]
    assert "four hours" in result[0]["quote"]
