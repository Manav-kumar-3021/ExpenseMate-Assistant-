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

def test_create_budget(test_db):
    cats = services.get_categories('expense')
    cat_id = cats[0]['id']
    success, msg = services.create_budget(cat_id, 500, 1, 2024, 'PKR', 80)
    assert success is True

def test_duplicate_budget_prevention(test_db):
    cats = services.get_categories('expense')
    cat_id = cats[0]['id']
    success1, msg1 = services.create_budget(cat_id, 500, 1, 2024, 'PKR', 80)
    assert success1 is True
    success2, msg2 = services.create_budget(cat_id, 600, 1, 2024, 'PKR', 80)
    assert success2 is False

def test_calculate_budget_status(test_db):
    cats = services.get_categories('expense')
    cat_id = cats[0]['id']
    status1 = services.calculate_budget_status(500, cat_id, 1, 2024, 'PKR')
    assert status1['spent'] == 0
    assert status1['status'] == 'Safe'
    
    services.add_expense(450, cat_id, "Buy", "2024-01-10", "Cash", "PKR")
    status2 = services.calculate_budget_status(500, cat_id, 1, 2024, 'PKR')
    assert status2['status'] == 'Warning'

    services.add_expense(100, cat_id, "Buy2", "2024-01-15", "Cash", "PKR")
    status3 = services.calculate_budget_status(500, cat_id, 1, 2024, 'PKR')
    assert status3['status'] == 'Exceeded'

def test_check_budget_alerts(test_db):
    cats = services.get_categories('expense')
    cat_id = cats[0]['id']
    services.create_budget(cat_id, 500, 1, 2024, 'PKR', 80)
    services.add_expense(450, cat_id, "Buy", "2024-01-10", "Cash", "PKR")
    alerts = services.check_budget_alerts(1, 2024, 'PKR')
    assert len(alerts) == 1
    assert alerts[0]['status'] == 'Warning'

def test_update_budget(test_db):
    cats = services.get_categories('expense')
    cat_id = cats[0]['id']
    services.create_budget(cat_id, 500, 1, 2024, 'PKR', 80)
    budgets = services.get_budgets(1, 2024, 'PKR')
    b_id = budgets[0]['id']
    success, msg = services.update_budget(b_id, cat_id, 1000, 1, 2024, 'PKR', 80)
    assert success is True
    b = services.get_budget_by_id(b_id)
    assert b['amount'] == 1000

def test_delete_budget(test_db):
    cats = services.get_categories('expense')
    cat_id = cats[0]['id']
    services.create_budget(cat_id, 500, 1, 2024, 'PKR', 80)
    budgets = services.get_budgets(1, 2024, 'PKR')
    b_id = budgets[0]['id']
    success, msg = services.delete_budget(b_id)
    assert success is True
    assert services.get_budget_by_id(b_id) is None
