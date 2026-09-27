import importlib
import re
import shutil
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import pytest

import database

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_DB = PROJECT_ROOT / "database" / "expensemate.db"


@contextmanager
def open_test_db():
    conn = database.get_db_connection()
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    test_db = tmp_path / "expensemate.db"
    shutil.copy2(PROJECT_DB, test_db)
    monkeypatch.setattr(database, "DB_PATH", str(test_db))

    import sys
    sys.modules.pop("app", None)
    module = importlib.import_module("app")
    module.app.config.update(TESTING=True)
    yield module
    sys.modules.pop("app", None)


@pytest.fixture
def app_client(app_module):
    return app_module.app.test_client()


def get_csrf(client):
    response = client.get("/categories")
    assert response.status_code == 200
    with client.session_transaction() as session:
        token = session.get("csrf_token")
    assert isinstance(token, str) and len(token) >= 32
    return token


def test_core_pages_render(app_client):
    routes = [
        "/",
        "/expenses",
        "/expenses/add",
        "/income",
        "/income/add",
        "/budgets",
        "/categories",
        "/analytics",
        "/analytics?month=",
        "/analytics/data",
        "/import-export",
    ]

    for route in routes:
        response = app_client.get(route)
        assert response.status_code == 200, route


def test_edit_income_template_uses_correct_context(app_client):
    response = app_client.get("/income/edit/1")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'name="source"' in body
    assert "UndefinedError" not in body


def test_csrf_is_required_for_all_state_changes(app_client):
    paths = [
        "/categories/add",
        "/categories/edit/1",
        "/categories/delete/1",
        "/expenses/add",
        "/expenses/edit/1",
        "/expenses/delete/1",
        "/income/add",
        "/income/edit/1",
        "/income/delete/1",
        "/budgets/add",
        "/budgets/edit/1",
        "/budgets/delete/1",
        "/import/expenses",
        "/import/income",
        "/load-sample-data",
        "/reset-database",
    ]

    for path in paths:
        response = app_client.post(path, data={})
        assert response.status_code == 403, path


def test_wrong_csrf_is_rejected(app_client):
    get_csrf(app_client)
    response = app_client.post(
        "/categories/add",
        data={
            "name": "Wrong Token",
            "type": "expense",
            "csrf_token": "x" * 43,
        },
    )
    assert response.status_code == 403


def test_cross_origin_post_is_rejected_even_with_valid_token(app_client):
    token = get_csrf(app_client)
    response = app_client.post(
        "/categories/add",
        data={"name": "Origin Test", "type": "expense", "csrf_token": token},
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403


def test_same_origin_post_is_allowed_with_valid_token(app_client):
    token = get_csrf(app_client)
    response = app_client.post(
        "/categories/add",
        data={"name": "Same Origin Test", "type": "expense", "csrf_token": token},
        headers={"Origin": "http://localhost"},
    )
    assert response.status_code == 302


def test_core_crud_post_routes_work(app_client):
    token = get_csrf(app_client)

    response = app_client.post(
        "/categories/add",
        data={"name": "Integration Expense", "type": "expense", "csrf_token": token},
    )
    assert response.status_code == 302

    with open_test_db() as conn:
        expense_category_id = conn.execute(
            "SELECT id FROM categories WHERE name = 'Integration Expense' AND type = 'expense'"
        ).fetchone()[0]
        income_category_id = conn.execute(
            "SELECT id FROM categories WHERE type = 'income' ORDER BY id LIMIT 1"
        ).fetchone()[0]

    response = app_client.post(
        "/expenses/add",
        data={
            "csrf_token": token,
            "amount": "125.50",
            "category_id": str(expense_category_id),
            "description": "Integration expense",
            "date": "2024-01-10",
            "payment_method": "Cash",
            "currency": "PKR",
        },
    )
    assert response.status_code == 302

    with open_test_db() as conn:
        expense_id = conn.execute(
            "SELECT id FROM expenses WHERE description = 'Integration expense' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

    response = app_client.post(
        f"/expenses/edit/{expense_id}",
        data={
            "csrf_token": token,
            "amount": "200.00",
            "category_id": str(expense_category_id),
            "description": "Updated expense",
            "date": "2024-01-11",
            "payment_method": "Debit Card",
            "currency": "PKR",
        },
    )
    assert response.status_code == 302

    response = app_client.post(
        f"/expenses/delete/{expense_id}",
        data={"csrf_token": token},
    )
    assert response.status_code == 302

    response = app_client.post(
        "/income/add",
        data={
            "csrf_token": token,
            "amount": "1500.00",
            "category_id": str(income_category_id),
            "description": "Integration income",
            "date": "2024-01-12",
            "source": "Integration Source",
            "currency": "PKR",
        },
    )
    assert response.status_code == 302

    with open_test_db() as conn:
        income_id = conn.execute(
            "SELECT id FROM income WHERE description = 'Integration income' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

    response = app_client.post(
        f"/income/edit/{income_id}",
        data={
            "csrf_token": token,
            "amount": "1600.00",
            "category_id": str(income_category_id),
            "description": "Updated income",
            "date": "2024-01-13",
            "source": "Updated Source",
            "currency": "PKR",
        },
    )
    assert response.status_code == 302

    response = app_client.post(
        f"/income/delete/{income_id}",
        data={"csrf_token": token},
    )
    assert response.status_code == 302

    response = app_client.post(
        "/budgets/add",
        data={
            "csrf_token": token,
            "category_id": str(expense_category_id),
            "amount": "1000.00",
            "month": "1",
            "year": "2024",
            "currency": "PKR",
            "alert_percentage": "80",
        },
    )
    assert response.status_code == 302

    with open_test_db() as conn:
        budget_id = conn.execute(
            "SELECT id FROM budgets WHERE category_id = ? AND month = 1 AND year = 2024 AND currency = 'PKR'"
            " ORDER BY id DESC LIMIT 1",
            (expense_category_id,),
        ).fetchone()[0]

    response = app_client.post(
        f"/budgets/edit/{budget_id}",
        data={
            "csrf_token": token,
            "category_id": str(expense_category_id),
            "amount": "1200.00",
            "month": "1",
            "year": "2024",
            "currency": "PKR",
            "alert_percentage": "75",
        },
    )
    assert response.status_code == 302

    response = app_client.post(
        f"/budgets/delete/{budget_id}",
        data={"csrf_token": token},
    )
    assert response.status_code == 302

    response = app_client.post(
        "/categories/add",
        data={"name": "Integration To Edit", "type": "expense", "csrf_token": token},
    )
    assert response.status_code == 302

    with open_test_db() as conn:
        category_id = conn.execute(
            "SELECT id FROM categories WHERE name = 'Integration To Edit' AND type='expense'"
        ).fetchone()[0]

    response = app_client.post(
        f"/categories/edit/{category_id}",
        data={"name": "Integration Edited", "type": "expense", "csrf_token": token},
    )
    assert response.status_code == 302

    response = app_client.post(
        f"/categories/delete/{category_id}",
        data={"csrf_token": token},
    )
    assert response.status_code == 302


def test_database_admin_routes_work_with_csrf(app_client):
    token = get_csrf(app_client)

    response = app_client.post(
        "/load-sample-data",
        data={"csrf_token": token},
    )
    assert response.status_code == 302

    response = app_client.post(
        "/reset-database",
        data={"csrf_token": token},
    )
    assert response.status_code == 302

    with open_test_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM income").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM budgets").fetchone()[0] == 0


def test_exports_work(app_client):
    assert app_client.get("/export/expenses").status_code == 200
    assert app_client.get("/export/income").status_code == 200
    assert app_client.get("/export/budgets").status_code == 200


def test_csv_import_routes_require_csrf_and_accept_valid_csv(app_client):
    no_token = app_client.post(
        "/import/expenses",
        data={"file": (BytesIO(b"amount,category,date\n100,Food,2024-01-01\n"), "x.csv")},
        content_type="multipart/form-data",
    )
    assert no_token.status_code == 403

    token = get_csrf(app_client)
    csv_bytes = b"amount,category,description,date,payment_method,currency\n100,Food,Test,2024-01-01,Cash,PKR\n"
    response = app_client.post(
        "/import/expenses",
        data={
            "csrf_token": token,
            "file": (BytesIO(csv_bytes), "expenses.csv"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302


def test_invalid_analytics_filter_is_rejected(app_client):
    response = app_client.get("/analytics/data?month=abc")
    assert response.status_code == 400
    assert response.is_json


def test_analytics_all_year_and_budgets_all_filters_are_selected(app_client):
    response = app_client.get("/analytics?month=")
    body = response.get_data(as_text=True)
    assert re.search(r'<option value=""\s+selected>All Year</option>', body)

    response = app_client.get("/budgets")
    body = response.get_data(as_text=True)
    assert 'value="" selected>All Months' in body
    assert 'value="" selected>All Years' in body
    assert 'value="" selected>All Currencies' in body


def test_security_headers_and_csp(app_client):
    response = app_client.get("/analytics")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "cdn.jsdelivr.net" not in csp
    assert "frame-ancestors 'none'" in csp


def test_all_state_changing_forms_have_csrf_tokens(app_client):
    pages = [
        "/expenses/add",
        "/income/add",
        "/budgets",
        "/categories",
        "/expenses",
        "/income",
        "/import-export",
        "/expenses/edit/1",
        "/income/edit/1",
    ]

    form_pattern = re.compile(
        r'<form\b[^>]*method=["\']POST["\'][^>]*>(.*?)</form>',
        re.I | re.S,
    )
    token_pattern = re.compile(r'name=["\']csrf_token["\']', re.I)

    for page in pages:
        response = app_client.get(page)
        assert response.status_code == 200, page
        forms = form_pattern.findall(response.get_data(as_text=True))
        assert forms, page
        assert all(token_pattern.search(form) for form in forms), page


def test_no_executable_inline_scripts(app_client):
    for page in ["/", "/budgets", "/categories", "/analytics", "/import-export"]:
        body = app_client.get(page).get_data(as_text=True)
        scripts = re.findall(r'<script\b([^>]*)>(.*?)</script>', body, re.I | re.S)
        for attrs, content in scripts:
            if 'src=' in attrs.lower():
                continue
            if 'type="application/json"' in attrs.lower() or "type='application/json'" in attrs.lower():
                continue
            assert not content.strip(), page


def test_migration_is_idempotent_and_preserves_data(tmp_path, monkeypatch):
    test_db = tmp_path / "expensemate.db"
    shutil.copy2(PROJECT_DB, test_db)
    monkeypatch.setattr(database, "DB_PATH", str(test_db))

    database.init_db()

    conn = database.get_db_connection()
    first_counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in database.TABLES
    }
    assert database._schema_is_current(conn)
    conn.close()

    database.init_db()

    conn = database.get_db_connection()
    second_counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in database.TABLES
    }
    assert first_counts == second_counts
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_dashboard_database_failure_does_not_fake_zero_data(app_module, monkeypatch):
    def fail_dashboard(*args, **kwargs):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(app_module, "get_dashboard_data", fail_dashboard)
    response = app_module.app.test_client().get("/")
    assert response.status_code == 500
    assert "Server Error" in response.get_data(as_text=True)
