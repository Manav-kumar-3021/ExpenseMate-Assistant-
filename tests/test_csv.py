import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import database
import services
import csv_handler
import tempfile
import pytest
from io import StringIO

@pytest.fixture
def test_db(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    database.init_db()
    yield str(db_path)

def test_export_expenses_csv(test_db):
    exp_cats = services.get_categories('expense')
    services.add_expense(100, exp_cats[0]['id'], "Food", "2024-01-10", "Cash", "PKR")
    expenses = services.get_expenses()
    csv_str = csv_handler.export_expenses_csv(expenses)
    assert "id,amount,category,description,date,payment_method,currency" in csv_str
    assert "100" in csv_str
    assert "Food" in csv_str

def test_export_income_csv(test_db):
    inc_cats = services.get_categories('income')
    services.add_income(1000, inc_cats[0]['id'], "Salary", "2024-01-01", "Company", "PKR")
    incomes = services.get_incomes()
    csv_str = csv_handler.export_income_csv(incomes)
    assert "id,amount,category,description,date,source,currency" in csv_str
    assert "1000" in csv_str
    assert "Salary" in csv_str

def test_import_expenses_csv_valid(test_db):
    exp_cats = services.get_categories('expense')
    cat_name = exp_cats[0]['name']
    csv_data = f"amount,category,description,date,payment_method,currency\n100,{cat_name},Lunch,2024-01-01,Cash,PKR\n"
    f = StringIO(csv_data)
    success, fail, errs = csv_handler.import_expenses_csv(f)
    assert success == 1
    assert fail == 0
    assert len(errs) == 0

def test_import_expenses_csv_invalid(test_db):
    exp_cats = services.get_categories('expense')
    cat_name = exp_cats[0]['name']
    csv_data = f"amount,category,description,date,payment_method,currency\n-100,{cat_name},Lunch,2024-01-01,Cash,PKR\n200,BadCat,Dinner,not-a-date,Cash,PKR\n"
    f = StringIO(csv_data)
    success, fail, errs = csv_handler.import_expenses_csv(f)
    assert success == 0
    assert fail == 2
    assert len(errs) == 2

def test_import_income_csv(test_db):
    inc_cats = services.get_categories('income')
    cat_name = inc_cats[0]['name']
    csv_data = f"amount,category,description,date,source,currency\n1000,{cat_name},Salary,2024-01-01,Company,PKR\n"
    f = StringIO(csv_data)
    success, fail, errs = csv_handler.import_income_csv(f)
    assert success == 1
    assert fail == 0
    assert len(errs) == 0
