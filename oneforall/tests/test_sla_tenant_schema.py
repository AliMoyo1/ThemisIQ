"""SLA instances need durable tenant ownership before per-tenant routes can be safe."""


def test_sla_instance_schema_has_org_id(test_db):
    columns = {
        row["name"]
        for row in test_db.execute("PRAGMA table_info(sla_instances)").fetchall()
    }
    assert "org_id" in columns
