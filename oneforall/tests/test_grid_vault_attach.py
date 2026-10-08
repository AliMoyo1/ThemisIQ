"""Attaching a Vault item to a GRID control (grid/data_service.py attach_vault_item_to_grid_control).

The function promises that once it returns, the item is attached to the control and a live
evidence link exists. Two ways it broke that promise:

* an attachment that already existed returned early, before the link check, so a link the Vault
  had removed was never restored and GRID kept showing a file the Vault no longer linked;
* the "already attached" test matched the marker `vault_evidence_id=1` as a prefix of
  `vault_evidence_id=12`, so attaching item 1 to a control that already carried item 12 silently
  did nothing.
"""
import modules.grid.data_service as grid_ds


def _insert(db, table, **cols):
    cur = db.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        tuple(cols.values()),
    )
    db.commit()
    return cur.lastrowid


def _control(db):
    audit = _insert(db, "grid_audits", name="Attach audit")
    return _insert(db, "grid_controls", audit_id=audit, name="Attach control")


def _item(db, title):
    return _insert(db, "evidence_items", title=title, status="current")


def _links(db, item, control):
    """(live, total) evidence links from the item to the GRID control."""
    where = "evidence_id=%s AND module='grid' AND entity_type='control' AND entity_id=%s"
    live = db.execute(f"SELECT COUNT(*) FROM evidence_links WHERE {where} AND deleted_at IS NULL",
                      (item, control)).fetchone()[0]
    total = db.execute(f"SELECT COUNT(*) FROM evidence_links WHERE {where}", (item, control)).fetchone()[0]
    return live, total


def _files(db, control):
    return db.execute("SELECT COUNT(*) FROM grid_evidence_files WHERE control_id=%s", (control,)).fetchone()[0]


def test_reattaching_restores_a_link_the_vault_removed(test_db):
    control, item = _control(test_db), _item(test_db, "Policy pack")
    first = grid_ds.attach_vault_item_to_grid_control(control, item, None)
    assert first is not None and _links(test_db, item, control) == (1, 1)

    # The Vault unlinks it (a soft delete); the GRID record stays.
    test_db.execute("UPDATE evidence_links SET deleted_at = CURRENT_TIMESTAMP WHERE evidence_id = %s", (item,))
    test_db.commit()
    assert _links(test_db, item, control) == (0, 1)

    again = grid_ds.attach_vault_item_to_grid_control(control, item, None)
    assert again == first, "the existing GRID record is reused, not duplicated"
    assert _files(test_db, control) == 1
    assert _links(test_db, item, control) == (1, 2), "one live link again; the removed row stays as the audit trail"


def test_reattaching_with_a_live_link_changes_nothing(test_db):
    control, item = _control(test_db), _item(test_db, "Policy pack")
    first = grid_ds.attach_vault_item_to_grid_control(control, item, None)
    assert grid_ds.attach_vault_item_to_grid_control(control, item, None) == first
    assert _files(test_db, control) == 1 and _links(test_db, item, control) == (1, 1)


def test_item_1_is_not_mistaken_for_item_12(test_db):
    control = _control(test_db)
    items = [_item(test_db, f"Item {n}") for n in range(1, 13)]
    one, twelve = items[0], items[11]
    assert (one, twelve) == (1, 12)

    on_twelve = grid_ds.attach_vault_item_to_grid_control(control, twelve, None)
    on_one = grid_ds.attach_vault_item_to_grid_control(control, one, None)

    assert on_one is not None and on_one != on_twelve
    assert _files(test_db, control) == 2
    assert _links(test_db, one, control) == (1, 1) and _links(test_db, twelve, control) == (1, 1)
