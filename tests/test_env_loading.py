from __future__ import annotations

import os

from joborchestrator.env import load_local_env


def test_load_local_env_reads_key_values_without_overriding(tmp_path, monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(
        """
# comment
TURSO_DATABASE_URL=libsql://example
TURSO_AUTH_TOKEN="token with spaces"
EXISTING=from-file
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("EXISTING", "from-env")

    load_local_env(env_path)

    assert os.environ["TURSO_DATABASE_URL"] == "libsql://example"
    assert os.environ["TURSO_AUTH_TOKEN"] == "token with spaces"
    assert os.environ["EXISTING"] == "from-env"
