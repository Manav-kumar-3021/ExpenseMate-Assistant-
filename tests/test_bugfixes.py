import pytest
import math
import tempfile
import os
import sqlite3
import datetime

# Mock the database path so we don't mess with the real one
@pytest.fixture(autouse=True)
def test_db(monkeypatch):
    from database import init_db, get_db_connection
    import database
    
    # Create temp db
    db_fd, db_path = tempfile.mkstemp()
    monkeypatch.setattr(database, 'DB_PATH', db_path)
    
    init_db()
    
    yield
    
    os.close(db_fd)
    os.unlink(db_path)

from services import (
    add_category, get_categories, update_category,
    add_expense, update_expense,
    add_income, update_income,
    create_budget, update_budget
)
from validators import validate_amount, validate_date, validate_budget, validate_expense
from database import load_sample_data, get_db_connection

# --- BUG 1 TESTS ---
def test_expense_with_expense_category_passes():
    add_category("FoodTest", "expense")
    cats = get_categories("expense")
    cat_id = [c['id'] for c in cats if c['name'] == "FoodTest"][0]
    
    success, result = add_expense(100, cat_id, "test", "2024-01-01", "Cash")
    assert success is True

def test_expense_with_income_category_rejected():
    add_category("SalaryTest", "income")
    cats = get_categories("income")
    cat_id = [c['id'] for c in cats if c['name'] == "SalaryTest"][0]
    
    success, result = add_expense(100, cat_id, "test", "2024-01-01", "Cash")
    assert success is False
    assert "Category type must be 'expense' for expenses." in result

def test_income_with_income_category_passes():
    add_category("SalaryTest2", "income")
    cats = get_categories("income")
    cat_id = [c['id'] for c in cats if c['name'] == "SalaryTest2"][0]
    
    success, result = add_income(100, cat_id, "test", "2024-01-01", "Cash")
    assert success is True

def test_income_with_expense_category_rejected():
    add_category("FoodTest2", "expense")
    cats = get_categories("expense")
    cat_id = [c['id'] for c in cats if c['name'] == "FoodTest2"][0]
    
    success, result = add_income(100, cat_id, "test", "2024-01-01", "Cash")
    assert success is False
    assert "Category type must be 'income' for incomes." in result

def test_budget_with_expense_category_passes():
    add_category("FoodTest3", "expense")
    cats = get_categories("expense")
    cat_id = [c['id'] for c in cats if c['name'] == "FoodTest3"][0]
    
    success, result = create_budget(cat_id, 1000, 1, 2024)
    assert success is True

def test_budget_with_income_category_rejected():
    add_category("SalaryTest3", "income")
    cats = get_categories("income")
    cat_id = [c['id'] for c in cats if c['name'] == "SalaryTest3"][0]
    
    success, result = create_budget(cat_id, 1000, 1, 2024)
    assert success is False
    assert "Category type must be 'expense' for budgets." in result

def test_update_expense_wrong_category_rejected():
    add_category("FoodTest4", "expense")
    cats = get_categories("expense")
    exp_cat_id = [c['id'] for c in cats if c['name'] == "FoodTest4"][0]
    
    success, expense_id = add_expense(100, exp_cat_id, "test", "2024-01-01", "Cash")
    assert success is True
    
    add_category("SalaryTest4", "income")
    cats = get_categories("income")
    inc_cat_id = [c['id'] for c in cats if c['name'] == "SalaryTest4"][0]
    
    success, result = update_expense(expense_id, 100, inc_cat_id, "test", "2024-01-01", "Cash")
    assert success is False

def test_update_income_wrong_category_rejected():
    add_category("SalaryTest5", "income")
    cats = get_categories("income")
    inc_cat_id = [c['id'] for c in cats if c['name'] == "SalaryTest5"][0]
    
    success, income_id = add_income(100, inc_cat_id, "test", "2024-01-01", "Cash")
    assert success is True
    
    add_category("FoodTest5", "expense")
    cats = get_categories("expense")
    exp_cat_id = [c['id'] for c in cats if c['name'] == "FoodTest5"][0]
    
    success, result = update_income(income_id, 100, exp_cat_id, "test", "2024-01-01", "Cash")
    assert success is False

def test_update_budget_wrong_category_rejected():
    add_category("FoodTest6", "expense")
    cats = get_categories("expense")
    exp_cat_id = [c['id'] for c in cats if c['name'] == "FoodTest6"][0]
    
    success, result = create_budget(exp_cat_id, 1000, 1, 2024)
    assert success is True
    
    # Needs a budget_id. Since sqlite autonumbers, let's just query it or assume 1.
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM budgets WHERE category_id = ?", (exp_cat_id,))
    budget_id = c.fetchone()[0]
    conn.close()
    
    add_category("SalaryTest6", "income")
    cats = get_categories("income")
    inc_cat_id = [c['id'] for c in cats if c['name'] == "SalaryTest6"][0]
    
    success, result = update_budget(budget_id, inc_cat_id, 1000, 1, 2024)
    assert success is False

# --- BUG 2 TESTS ---
def test_expense_nan_amount_rejected():
    valid, _, msg = validate_amount(math.nan)
    assert valid is False
    assert "Amount must be a finite number." in msg

def test_expense_infinity_amount_rejected():
    valid, _, msg = validate_amount(math.inf)
    assert valid is False
    assert "Amount must be a finite number." in msg

def test_expense_negative_infinity_rejected():
    valid, _, msg = validate_amount(-math.inf)
    assert valid is False
    assert "Amount must be a finite number." in msg

def test_income_nan_rejected():
    valid, _, msg = validate_amount(str(math.nan))
    assert valid is False
    assert "Amount must be a finite number." in msg

def test_budget_infinity_rejected():
    valid, _, msg = validate_amount(str(math.inf))
    assert valid is False
    assert "Amount must be a finite number." in msg

def test_valid_finite_amount_passes():
    valid, amt, msg = validate_amount(100.5)
    assert valid is True
    assert amt == 100.5

# --- BUG 3 TESTS ---
def test_unused_category_type_change_allowed():
    add_category("UnusedCat", "expense")
    cats = get_categories("expense")
    cat_id = [c['id'] for c in cats if c['name'] == "UnusedCat"][0]
    
    success, result = update_category(cat_id, "UnusedCat", "income")
    assert success is True

def test_used_category_type_change_rejected():
    add_category("UsedCat", "expense")
    cats = get_categories("expense")
    cat_id = [c['id'] for c in cats if c['name'] == "UsedCat"][0]
    
    success, expense_id = add_expense(100, cat_id, "test", "2024-01-01", "Cash")
    assert success is True
    
    success, result = update_category(cat_id, "UsedCat", "income")
    assert success is False
    assert "in use" in result

# --- BUG 4 TESTS ---
def test_sample_data_loads_first_time():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM expenses")
    count_before = c.fetchone()[0]
    conn.close()
    
    load_sample_data()
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM expenses")
    count_after = c.fetchone()[0]
    conn.close()
    
    assert count_after > count_before

def test_sample_data_no_duplicates_on_reload():
    load_sample_data()
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM expenses")
    count_after_first = c.fetchone()[0]
    conn.close()
    
    load_sample_data()
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM expenses")
    count_after_second = c.fetchone()[0]
    conn.close()
    
    assert count_after_first == count_after_second

# --- BUG 5 TESTS ---
def test_case_insensitive_category_duplicate_rejected():
    add_category("Food123", "expense")
    success, result = add_category("food123", "expense")
    assert success is False
    assert "already exists" in result.lower()

def test_case_insensitive_category_uppercase_rejected():
    add_category("drink", "expense")
    success, result = add_category("DRINK", "expense")
    assert success is False
    assert "already exists" in result.lower()

def test_different_categories_allowed():
    success1, _ = add_category("CatA", "expense")
    success2, _ = add_category("CatB", "expense")
    assert success1 is True
    assert success2 is True

# --- BUG 6 TESTS ---
def test_validate_date_with_integer_input():
    valid, msg = validate_date(123)
    assert valid is False

def test_validate_budget_with_none_month():
    valid, errors = validate_budget({"amount": "100", "category_id": 1, "month": None, "year": 2024, "currency": "PKR"})
    assert valid is False
    assert any("month" in e.lower() for e in errors)

def test_validate_budget_with_none_alert_percentage():
    valid, errors = validate_budget({"amount": "100", "category_id": 1, "month": 1, "year": 2024, "currency": "PKR", "alert_percentage": None})
    assert valid is False
    assert "Invalid alert percentage." in errors

def test_validate_expense_with_none_values_no_crash():
    valid, errors = validate_expense({"amount": None, "category_id": None, "date": None})
    assert valid is False
    assert len(errors) > 0


def test_lowercase_currency_is_normalized_before_storage():
    add_category("CurrencyTest", "expense")
    category = next(c for c in get_categories("expense") if c["name"] == "CurrencyTest")

    success, expense_id = add_expense(
        "100.25", category["id"], "currency", "2024-01-01", "Cash", "pkr"
    )
    assert success is True
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT currency FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        assert row[0] == "PKR"
    finally:
        conn.close()


def test_same_category_name_can_exist_for_different_types():
    success1, _ = add_category("Shared Name", "expense")
    success2, _ = add_category("Shared Name", "income")
    assert success1 is True
    assert success2 is True


def test_income_source_length_is_validated():
    add_category("SourceTest", "income")
    category = next(c for c in get_categories("income") if c["name"] == "SourceTest")
    too_long = "x" * 501
    success, result = add_income(
        100, category["id"], "income", "2024-01-01", too_long, "PKR"
    )
    assert success is False
    assert any("Source cannot exceed 500" in str(item) for item in result)
