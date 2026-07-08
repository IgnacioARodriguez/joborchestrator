from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_storage_env(monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
