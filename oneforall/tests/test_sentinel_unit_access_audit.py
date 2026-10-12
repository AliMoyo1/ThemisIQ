"""Focused checks for the count-only Sentinel production audit."""

from scripts.audit_sentinel_unit_access import _linked_dpia_counts


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _Database:
    def execute(self, sql):
        if "FROM business_units" in sql:
            return _Rows([
                {"id": 1, "parent_id": None},
                {"id": 2, "parent_id": 1},
                {"id": 3, "parent_id": None},
            ])
        return _Rows([
            {"dpia_unit": None, "ropa_unit": 2},
            {"dpia_unit": 1, "ropa_unit": 2},
            {"dpia_unit": 2, "ropa_unit": 1},
            {"dpia_unit": 3, "ropa_unit": 2},
            {"dpia_unit": 3, "ropa_unit": None},
        ])


def test_audit_counts_wider_links_but_not_parent_to_child_or_public_ropa():
    assert _linked_dpia_counts(_Database()) == {
        "linked": 5,
        "organization_wide_to_unit": 1,
        "different_unit": 3,
        "wider_than_ropa": 3,
    }
