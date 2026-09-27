import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import database
import services
import analytics
import tempfile
import pytest

@pytest.fixture
def test_db(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.init_db()
    yield str(db_path)

def test_get_analytics_data_empty(test_db):
    data = analytics.get_analytics_data(month=1, year=2024, currency='PKR')
    assert data['total_expenses'] == 0
    assert data['total_income'] == 0
    assert data['balance'] == 0
    assert len(data['category_expenses']) == 0
    assert len(data['monthly_expenses']) == 12

def test_analytics_with_data(test_db):
    exp_cats = services.get_categories('expense')
    inc_cats = services.get_categories('income')
    services.add_expense(100, exp_cats[0]['id'], "Food", "2024-01-10", "Cash", "PKR")
    services.add_income(1000, inc_cats[0]['id'], "Salary", "2024-01-01", "Company", "PKR")
    
    data = analytics.get_analytics_data(month=1, year=2024, currency='PKR')
    assert data['total_expenses'] == 100
    assert data['total_income'] == 1000
    assert data['balance'] == 900
    assert len(data['category_expenses']) == 1
    assert data['category_expenses'][0]['total'] == 100
    assert len(data['category_income']) == 1
    assert data['monthly_expenses'][0]['total'] == 100
    assert data['monthly_income'][0]['total'] == 1000
