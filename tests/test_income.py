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

def test_add_income_valid(test_db):
    cats = services.get_categories('income')
    cat_id = cats[0]['id']
    success, res = services.add_income(1000, cat_id, "Salary", "2024-01-01", "Company", "PKR")
    assert success is True

def test_add_income_invalid(test_db):
    cats = services.get_categories('income')
    cat_id = cats[0]['id']
    success, errs = services.add_income(-100, cat_id, "Salary", "2024-01-01", "Company", "PKR")
    assert success is False

def test_get_incomes(test_db):
    cats = services.get_categories('income')
    cat_id = cats[0]['id']
    services.add_income(1000, cat_id, "Salary", "2024-01-01", "Company", "PKR")
    incomes = services.get_incomes()
    assert len(incomes) > 0
    assert incomes[0]['amount'] == 1000

def test_update_income(test_db):
    cats = services.get_categories('income')
    cat_id = cats[0]['id']
    success, inc_id = services.add_income(1000, cat_id, "Salary", "2024-01-01", "Company", "PKR")
    success_up, msg = services.update_income(inc_id, 2000, cat_id, "Bonus", "2024-01-02", "Company", "PKR")
    assert success_up is True
    inc = services.get_income_by_id(inc_id)
    assert inc['amount'] == 2000
    assert inc['description'] == "Bonus"

def test_delete_income(test_db):
    cats = services.get_categories('income')
    cat_id = cats[0]['id']
    success, inc_id = services.add_income(1000, cat_id, "Salary", "2024-01-01", "Company", "PKR")
    success_del, msg = services.delete_income(inc_id)
    assert success_del is True
    assert services.get_income_by_id(inc_id) is None

def test_calculate_total_income(test_db):
    cats = services.get_categories('income')
    cat_id = cats[0]['id']
    services.add_income(1000, cat_id, "Salary", "2024-01-01", "Company", "PKR")
    services.add_income(2000, cat_id, "Bonus", "2024-01-05", "Company", "PKR")
    total = services.calculate_total_income(month=1, year=2024, currency="PKR")
    assert total == 3000
