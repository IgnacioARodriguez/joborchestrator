import sqlite3

from joborchestrator.storage import persistence as db


def test_backup_database_works_while_database_connection_is_open(tmp_path, monkeypatch):
    db_path = tmp_path / "scanner.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE example (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO example (name) VALUES ('open')")
        conn.commit()

        backup_path = db.backup_database("locked_on_windows")
    finally:
        conn.close()

    assert backup_path is not None
    assert backup_path.exists()

    backup = sqlite3.connect(backup_path)
    try:
        row = backup.execute("SELECT name FROM example").fetchone()
    finally:
        backup.close()

    assert row == ("open",)
