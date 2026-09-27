import sqlite3

import pytest

import database


@pytest.fixture
def test_db(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.init_db()
    return db_path


def test_init_db(test_db):
    conn = database.get_db_connection()
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    conn.close()

    assert 'categories' in tables
    assert 'expenses' in tables
    assert 'income' in tables
    assert 'budgets' in tables


def test_default_categories_inserted(test_db):
    conn = database.get_db_connection()
    count = conn.execute("SELECT count(*) FROM categories").fetchone()[0]
    conn.close()
    assert count > 0


def test_get_db_connection(test_db):
    conn = database.get_db_connection()
    assert isinstance(conn, sqlite3.Connection)
    conn.close()


def test_reset_database(test_db):
    database.reset_database()
    conn = database.get_db_connection()
    count = conn.execute("SELECT count(*) FROM categories").fetchone()[0]
    conn.close()
    assert count > 0


def test_current_schema_is_detected_as_current(test_db):
    conn = database.get_db_connection()
    assert database._schema_is_current(conn) is True
    assert conn.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
    conn.close()


def test_repeated_init_does_not_change_data(test_db):
    conn = database.get_db_connection()
    category_id = conn.execute(
        "SELECT id FROM categories WHERE type='expense' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    conn.close()

    database.load_sample_data()

    conn = database.get_db_connection()
    counts_before = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in database.TABLES
    }
    conn.close()

    database.init_db()

    conn = database.get_db_connection()
    counts_after = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in database.TABLES
    }
    assert counts_before == counts_after
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("SELECT id FROM categories WHERE id = ?", (category_id,)).fetchone()
    conn.close()


def test_deleted_default_category_stays_deleted_after_restart(test_db):
    conn = database.get_db_connection()
    row = conn.execute(
        "SELECT id FROM categories WHERE name = 'Travel' AND type = 'expense'"
    ).fetchone()
    assert row is not None
    conn.execute("DELETE FROM categories WHERE id = ?", (row[0],))
    conn.commit()
    conn.close()

    database.init_db()

    conn = database.get_db_connection()
    row = conn.execute(
        "SELECT id FROM categories WHERE name = 'Travel' AND type = 'expense'"
    ).fetchone()
    conn.close()
    assert row is None


def test_legacy_database_migrates_and_preserves_records(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))

    conn = database.get_db_connection()
    conn.execute("BEGIN")
    conn.execute(
        "CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL NOT NULL, category_id INTEGER NOT NULL, description TEXT, date TEXT, payment_method TEXT, currency TEXT)"
    )
    conn.execute(
        "CREATE TABLE income (id INTEGER PRIMARY KEY AUTOINCREMENT, amount REAL NOT NULL, category_id INTEGER NOT NULL, description TEXT, date TEXT, source TEXT, currency TEXT)"
    )
    conn.execute(
        "CREATE TABLE budgets (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER NOT NULL, amount REAL NOT NULL, month INTEGER, year INTEGER, currency TEXT, alert_percentage REAL)"
    )
    conn.execute("INSERT INTO categories VALUES (1, 'Food', 'expense')")
    conn.execute("INSERT INTO categories VALUES (2, 'Salary', 'income')")
    conn.execute("INSERT INTO expenses VALUES (1, 100.0, 1, 'Lunch', '2024-01-01', 'Cash', 'PKR')")
    conn.execute("INSERT INTO income VALUES (1, 1000.0, 2, 'Pay', '2024-01-02', 'Bank', 'PKR')")
    conn.execute("INSERT INTO budgets VALUES (1, 1, 500.0, 1, 2024, 'PKR', 80)")
    conn.commit()
    conn.close()

    database.init_db()

    conn = database.get_db_connection()
    assert database._schema_is_current(conn) is True
    assert conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM income").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM budgets").fetchone()[0] == 1
    assert conn.execute("SELECT description FROM expenses WHERE id = 1").fetchone()[0] == "Lunch"
    assert conn.execute("SELECT source FROM income WHERE id = 1").fetchone()[0] == "Bank"
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_legacy_artifact_state_is_recovered(tmp_path, monkeypatch):
    db_path = tmp_path / "artifact.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.init_db()

    conn = database.get_db_connection()
    conn.execute("INSERT INTO expenses (amount, category_id, description, date, currency) VALUES (?, ?, ?, ?, ?)",
                 (12.50, 1, "Artifact expense", "2024-01-01", "PKR"))
    conn.commit()

    for table in database.TABLES:
        conn.execute(f"CREATE TABLE {table}_old AS SELECT * FROM {table}")

    for table in database.CHILD_TABLES:
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM categories")
    conn.commit()
    conn.close()

    database.init_db()

    conn = database.get_db_connection()
    assert conn.execute("SELECT COUNT(*) FROM expenses WHERE description = 'Artifact expense'").fetchone()[0] == 1
    assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_old'").fetchall() == []
    assert database._schema_is_current(conn) is True
    conn.close()


def test_database_constraints_reject_invalid_rows(test_db):
    conn = database.get_db_connection()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO expenses (amount, category_id, date, currency) VALUES (?, ?, ?, ?)",
            (100.123, 1, "2024-01-01", "PKR"),
        )
    conn.rollback()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO expenses (amount, category_id, date, currency) VALUES (?, ?, ?, ?)",
            (100.00, 1, "2024-99-99", "PKR"),
        )
    conn.rollback()
    conn.close()
