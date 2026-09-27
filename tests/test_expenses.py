import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import database
import services
import tempfile
import pytest

@pytest.fixture
def test_db(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.init_db()
    yield str(db_path)

def test_add_expense_valid(test_db):
    cats = services.get_categories('expense')
    cat_id = cats[0]['id']
    success, res = services.add_expense(100, cat_id, "Lunch", "2024-01-01", "Cash", "PKR")
    assert success is True

def test_add_expense_invalid_amount(test_db):
    cats = services.get_categories('expense')
    cat_id = cats[0]['id']
    success, errs = services.add_expense(-100, cat_id, "Lunch", "2024-01-01", "Cash", "PKR")
    assert success is False
    success2, errs2 = services.add_expense(0, cat_id, "Lunch", "2024-01-01", "Cash", "PKR")
    assert success2 is False
    success3, errs3 = services.add_expense("abc", cat_id, "Lunch", "2024-01-01", "Cash", "PKR")
    assert success3 is False

def test_get_expenses(test_db):
    cats = services.get_categories('expense')
    cat_id = cats[0]['id']
    services.add_expense(100, cat_id, "Lunch", "2024-01-01", "Cash", "PKR")
    expenses = services.get_expenses()
    assert len(expenses) > 0
    assert expenses[0]['amount'] == 100

def test_update_expense(test_db):
    cats = services.get_categories('expense')
    cat_id = cats[0]['id']
    success, exp_id = services.add_expense(100, cat_id, "Lunch", "2024-01-01", "Cash", "PKR")
    success_up, msg = services.update_expense(exp_id, 200, cat_id, "Dinner", "2024-01-02", "Credit Card", "PKR")
    assert success_up is True
    exp = services.get_expense_by_id(exp_id)
    assert exp['amount'] == 200
    assert exp['description'] == "Dinner"

def test_delete_expense(test_db):
    cats = services.get_categories('expense')
    cat_id = cats[0]['id']
    success, exp_id = services.add_expense(100, cat_id, "Lunch", "2024-01-01", "Cash", "PKR")
    success_del, msg = services.delete_expense(exp_id)
    assert success_del is True
    assert services.get_expense_by_id(exp_id) is None

def test_calculate_total_expenses(test_db):
    cats = services.get_categories('expense')
    cat_id = cats[0]['id']
    services.add_expense(100, cat_id, "Lunch", "2024-01-01", "Cash", "PKR")
    services.add_expense(200, cat_id, "Dinner", "2024-01-01", "Cash", "PKR")
    total = services.calculate_total_expenses(month=1, year=2024, currency="PKR")
    assert total == 300

def test_filtering(test_db):
    cats = services.get_categories('expense')
    cat_id = cats[0]['id']
    services.add_expense(100, cat_id, "Lunch", "2024-01-01", "Cash", "PKR")
    services.add_expense(200, cat_id, "Dinner", "2024-02-01", "Cash", "PKR")
    exps = services.get_expenses(month=1, year=2024)
    assert len(exps) == 1
    assert exps[0]['amount'] == 100
