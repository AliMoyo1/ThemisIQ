"""PostgreSQL policy installation must stop startup on failure."""

import pytest

from config import settings
from core.rls import apply_rls_policies


def test_postgres_policy_installation_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "is_postgres", lambda: True)

    class FailingDB:
        rolled_back = False

        def execute(self, _statement):
            raise PermissionError("cannot install RLS policy")

        def rollback(self):
            self.rolled_back = True

    db = FailingDB()
    with pytest.raises(RuntimeError, match="RLS policy installation failed"):
        apply_rls_policies(db)
    assert db.rolled_back