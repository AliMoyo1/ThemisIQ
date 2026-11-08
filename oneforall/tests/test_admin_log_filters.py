"""The on-screen audit log and its CSV use the same scoped filter."""

from modules.launcher.routes_admin import _audit_log_filters


def test_audit_log_filter_keeps_organization_and_screen_filters(test_db):
    test_db.execute("INSERT INTO organizations (id,name,slug) VALUES (1,'First','first')")
    test_db.execute("INSERT INTO organizations (id,name,slug) VALUES (2,'Second','second')")
    test_db.execute("INSERT INTO audit_log (username,module,action,details,org_id) "
                    "VALUES ('Reviewer A','aria','policy_approved','in scope',1)")
    test_db.execute("INSERT INTO audit_log (username,module,action,details,org_id) "
                    "VALUES ('Reviewer B','aria','policy_approved','wrong organization',2)")
    test_db.execute("INSERT INTO audit_log (username,module,action,details,org_id) "
                    "VALUES ('Reviewer A','aria','policy_rejected','wrong action',1)")
    query = {"module": "aria", "action": "approved", "user": "Reviewer A"}
    where, params = _audit_log_filters({"id": 11, "org_id": 1, "is_super_admin": False}, query)
    result = test_db.execute(
        "SELECT al.details FROM audit_log al LEFT JOIN users u ON al.user_id=u.id WHERE " + where, params,
    ).fetchall()
    assert [row["details"] for row in result] == ["in scope"]

    where, params = _audit_log_filters({"id": 1, "is_super_admin": True}, {})
    result = test_db.execute(
        "SELECT al.details FROM audit_log al LEFT JOIN users u ON al.user_id=u.id WHERE " + where, params,
    ).fetchall()
    assert {row["details"] for row in result} >= {"in scope", "wrong organization", "wrong action"}
