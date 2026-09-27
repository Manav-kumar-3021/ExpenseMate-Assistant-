import logging
import sqlite3
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

from database import get_db_connection
from validators import (
    PAYMENT_METHODS,
    VALID_CURRENCIES,
    validate_amount,
    validate_category,
    validate_date,
    validate_date_range,
    validate_expense,
    validate_id,
    validate_income,
    validate_month,
    validate_search,
    validate_budget,
    validate_year,
)

logger = logging.getLogger(__name__)

MONEY_QUANT = Decimal("0.01")
DEFAULT_ALERT_PERCENTAGE = Decimal("80")


# Helpers

def _normalize_money(value) -> tuple[bool, Decimal | None, str | None]:
    valid, _, error = validate_amount(value)
    if not valid:
        return False, None, error

    try:
        raw = value.strip() if isinstance(value, str) else str(value)
        amount = Decimal(raw).quantize(MONEY_QUANT)
        return True, amount, None
    except (InvalidOperation, ValueError, TypeError):
        return False, None, "Amount must be a valid number."


def _normalize_optional_text(value, field_name, max_length=500) -> tuple[bool, str | None, str | None]:
    if value is None:
        return True, None, None

    if not isinstance(value, str):
        return False, None, f"{field_name} must be text."

    cleaned = unicodedata.normalize("NFKC", value)

    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        return False, None, f"{field_name} contains invalid characters."

    if len(cleaned) > max_length:
        return False, None, f"{field_name} cannot exceed {max_length} characters."

    return True, cleaned, None


def _normalize_optional_description(value) -> tuple[bool, str | None, str | None]:
    return _normalize_optional_text(value, "Description", 500)


def _normalize_source(value) -> tuple[bool, str | None, str | None]:
    return _normalize_optional_text(value, "Source", 500)


def _validate_currency_value(value) -> tuple[bool, str | None, str | None]:
    if not isinstance(value, str):
        return False, None, "Invalid currency."

    cleaned = value.strip().upper()
    if cleaned not in VALID_CURRENCIES:
        return False, None, "Invalid currency."

    return True, cleaned, None


def _validate_optional_id(value) -> tuple[bool, int | None]:
    if value is None or value == "":
        return True, None
    valid, cleaned, _ = validate_id(value)
    if not valid:
        return False, None
    return True, cleaned


def _validate_optional_month(value) -> tuple[bool, int | None]:
    if value is None or value == "":
        return True, None
    valid, cleaned, _ = validate_month(value)
    if not valid:
        return False, None
    return True, cleaned


def _validate_optional_year(value) -> tuple[bool, int | None]:
    if value is None or value == "":
        return True, None
    valid, cleaned, _ = validate_year(value)
    if not valid:
        return False, None
    return True, cleaned


def _validate_optional_currency(value) -> tuple[bool, str | None]:
    if value is None or value == "":
        return True, None
    valid, cleaned, _ = _validate_currency_value(value)
    if not valid:
        return False, None
    return True, cleaned


def _validate_optional_date(value) -> tuple[bool, str | None]:
    if value is None or value == "":
        return True, None
    valid, cleaned = validate_date(value)
    if not valid:
        return False, None
    return True, cleaned


def _validate_category_for_type(cursor, category_id: int, category_type: str) -> bool:
    cursor.execute(
        "SELECT id FROM categories WHERE id = ? AND type = ?",
        (category_id, category_type),
    )
    return cursor.fetchone() is not None


def _is_budget_duplicate_error(error: sqlite3.IntegrityError) -> bool:
    message = str(error).lower()
    return "unique constraint failed" in message and "budget" in message


def _safe_money(value) -> Decimal:
    try:
        amount = Decimal(str(value or 0))
        if not amount.is_finite():
            return Decimal("0.00")
        return amount.quantize(MONEY_QUANT)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


# Categories

def get_categories(category_type=None) -> list[dict]:
    if category_type not in (None, "expense", "income"):
        return []

    conn = get_db_connection()
    try:
        c = conn.cursor()
        if category_type is not None:
            c.execute(
                "SELECT * FROM categories WHERE type = ? ORDER BY name",
                (category_type,),
            )
        else:
            c.execute("SELECT * FROM categories ORDER BY name")
        return [dict(row) for row in c.fetchall()]
    except sqlite3.Error:
        logger.exception("Failed to retrieve categories")
        return []
    finally:
        conn.close()


def get_category_by_id(category_id) -> dict | None:
    valid, cleaned_id, _ = validate_id(category_id)
    if not valid:
        return None

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM categories WHERE id = ?", (cleaned_id,))
        row = c.fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        logger.exception("Failed to retrieve category")
        return None
    finally:
        conn.close()


def add_category(name, category_type) -> tuple[bool, str]:
    try:
        is_valid, errors = validate_category({"name": name, "type": category_type})
    except (TypeError, ValueError, AttributeError):
        return False, "Invalid category data."
    if not is_valid:
        return False, "; ".join(errors)

    clean_name = name.strip()

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id FROM categories WHERE name = ? COLLATE NOCASE AND type = ?",
            (clean_name, category_type),
        )
        if c.fetchone():
            return False, "Category name already exists (case-insensitive)."

        c.execute(
            "INSERT INTO categories (name, type) VALUES (?, ?)",
            (clean_name, category_type),
        )
        conn.commit()
        return True, "Category added successfully."
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, "Category name already exists."
    except sqlite3.Error:
        conn.rollback()
        logger.exception("Failed to add category")
        return False, "Unable to add category."
    finally:
        conn.close()


def update_category(category_id, name, category_type) -> tuple[bool, str]:
    valid_id, clean_id, id_error = validate_id(category_id)
    if not valid_id:
        return False, id_error

    try:
        is_valid, errors = validate_category({"name": name, "type": category_type})
    except (TypeError, ValueError, AttributeError):
        return False, "Invalid category data."
    if not is_valid:
        return False, "; ".join(errors)

    clean_name = name.strip()

    conn = get_db_connection()
    try:
        c = conn.cursor()

        c.execute("SELECT * FROM categories WHERE id = ?", (clean_id,))
        existing = c.fetchone()
        if not existing:
            return False, "Category not found."

        c.execute(
            "SELECT id FROM categories WHERE name = ? COLLATE NOCASE AND type = ? AND id != ?",
            (clean_name, category_type, clean_id),
        )
        if c.fetchone():
            return False, "Category name already exists (case-insensitive)."

        if existing["type"] != category_type:
            c.execute(
                "SELECT 1 FROM expenses WHERE category_id = ? LIMIT 1",
                (clean_id,),
            )
            e_used = c.fetchone()

            c.execute(
                "SELECT 1 FROM income WHERE category_id = ? LIMIT 1",
                (clean_id,),
            )
            i_used = c.fetchone()

            c.execute(
                "SELECT 1 FROM budgets WHERE category_id = ? LIMIT 1",
                (clean_id,),
            )
            b_used = c.fetchone()

            if e_used or i_used or b_used:
                return False, "Cannot change type of a category that is in use."

        c.execute(
            "UPDATE categories SET name = ?, type = ? WHERE id = ?",
            (clean_name, category_type, clean_id),
        )
        conn.commit()
        return True, "Category updated successfully."
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, "Category name already exists."
    except sqlite3.Error:
        conn.rollback()
        logger.exception("Failed to update category")
        return False, "Unable to update category."
    finally:
        conn.close()


def delete_category(category_id) -> tuple[bool, str]:
    valid, clean_id, error = validate_id(category_id)
    if not valid:
        return False, error

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM categories WHERE id = ?", (clean_id,))
        if c.rowcount == 0:
            conn.rollback()
            return False, "Category not found."
        conn.commit()
        return True, "Category deleted successfully."
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, "Cannot delete category as it is currently in use."
    except sqlite3.Error:
        conn.rollback()
        logger.exception("Failed to delete category")
        return False, "Unable to delete category."
    finally:
        conn.close()


# Expenses

def get_expenses(
    search=None,
    category_id=None,
    date_from=None,
    date_to=None,
    month=None,
    year=None,
    currency=None,
    payment_method=None,
    sort_by="date",
    sort_order="desc",
) -> list[dict]:
    search = validate_search(search)

    valid_category, category_id = _validate_optional_id(category_id)
    if not valid_category:
        return []

    if date_from not in (None, "") and date_to not in (None, ""):
        valid_dates, _ = validate_date_range(date_from, date_to)
        if not valid_dates:
            return []
        _, date_from = validate_date(date_from)
        _, date_to = validate_date(date_to)
    else:
        valid_from, date_from = _validate_optional_date(date_from)
        valid_to, date_to = _validate_optional_date(date_to)
        if not valid_from or not valid_to:
            return []

    valid_month, month = _validate_optional_month(month)
    valid_year, year = _validate_optional_year(year)
    valid_currency, currency = _validate_optional_currency(currency)

    if not valid_month or not valid_year or not valid_currency:
        return []

    if payment_method in (None, ""):
        payment_method = None
    elif isinstance(payment_method, str):
        payment_method = payment_method.strip()
        if payment_method not in PAYMENT_METHODS:
            return []
    else:
        return []

    valid_sort_cols = {
        "date": "e.date",
        "amount": "e.amount",
        "category_name": "c.name",
    }
    sort_col = valid_sort_cols.get(sort_by, "e.date")
    sort_dir = "ASC" if isinstance(sort_order, str) and sort_order.lower() == "asc" else "DESC"

    query = """
        SELECT e.*, c.name as category_name
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        WHERE 1=1
    """
    params = []

    if search:
        search_esc = search.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        query += " AND (e.description LIKE ? ESCAPE '!' OR c.name LIKE ? ESCAPE '!')"
        params.extend([f"%{search_esc}%", f"%{search_esc}%"])
    if category_id is not None:
        query += " AND e.category_id = ?"
        params.append(category_id)
    if date_from:
        query += " AND e.date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND e.date <= ?"
        params.append(date_to)
    if month is not None:
        query += " AND strftime('%m', e.date) = ?"
        params.append(f"{month:02d}")
    if year is not None:
        query += " AND strftime('%Y', e.date) = ?"
        params.append(str(year))
    if currency:
        query += " AND e.currency = ?"
        params.append(currency)
    if payment_method:
        query += " AND e.payment_method = ?"
        params.append(payment_method)

    query += f" ORDER BY {sort_col} {sort_dir}"

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(query, params)
        return [dict(row) for row in c.fetchall()]
    except sqlite3.Error:
        logger.exception("Failed to retrieve expenses")
        return []
    finally:
        conn.close()


def get_expense_by_id(expense_id) -> dict | None:
    valid, clean_id, _ = validate_id(expense_id)
    if not valid:
        return None

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT e.*, c.name as category_name
            FROM expenses e
            JOIN categories c ON e.category_id = c.id
            WHERE e.id = ?
            """,
            (clean_id,),
        )
        row = c.fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        logger.exception("Failed to retrieve expense")
        return None
    finally:
        conn.close()


def add_expense(amount, category_id, description, date, payment_method, currency="PKR") -> tuple[bool, Any]:
    data = {
        "amount": amount,
        "category_id": category_id,
        "description": description,
        "date": date,
        "payment_method": payment_method,
        "currency": currency,
    }

    try:
        is_valid, errors = validate_expense(data)
    except (TypeError, ValueError, AttributeError):
        return False, ["Invalid expense data."]
    if not is_valid:
        return False, errors

    valid_amount, clean_amount, amount_error = _normalize_money(amount)
    valid_category, clean_category_id, category_error = validate_id(category_id)
    valid_date, clean_date = validate_date(date)
    valid_currency, clean_currency, currency_error = _validate_currency_value(currency)
    valid_description, clean_description, description_error = _normalize_optional_description(description)

    if not valid_amount:
        return False, [amount_error]
    if not valid_category:
        return False, [category_error]
    if not valid_date:
        return False, [clean_date]
    if not valid_currency:
        return False, [currency_error]
    if not valid_description:
        return False, [description_error]

    conn = get_db_connection()
    try:
        c = conn.cursor()
        if not _validate_category_for_type(c, clean_category_id, "expense"):
            return False, ["Category type must be 'expense' for expenses."]

        c.execute(
            """
            INSERT INTO expenses
                (amount, category_id, description, date, payment_method, currency)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                float(clean_amount),
                clean_category_id,
                clean_description,
                clean_date,
                payment_method,
                clean_currency,
            ),
        )
        conn.commit()
        return True, c.lastrowid
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, ["Unable to save expense because the data violates a database rule."]
    except sqlite3.Error:
        conn.rollback()
        logger.exception("Failed to add expense")
        return False, ["Unable to save expense."]
    finally:
        conn.close()


def update_expense(expense_id, amount, category_id, description, date, payment_method, currency="PKR") -> tuple[bool, Any]:
    valid_id, clean_expense_id, id_error = validate_id(expense_id)
    if not valid_id:
        return False, [id_error]

    data = {
        "amount": amount,
        "category_id": category_id,
        "description": description,
        "date": date,
        "payment_method": payment_method,
        "currency": currency,
    }

    try:
        is_valid, errors = validate_expense(data)
    except (TypeError, ValueError, AttributeError):
        return False, ["Invalid expense data."]
    if not is_valid:
        return False, errors

    valid_amount, clean_amount, amount_error = _normalize_money(amount)
    valid_category, clean_category_id, category_error = validate_id(category_id)
    valid_date, clean_date = validate_date(date)
    valid_currency, clean_currency, currency_error = _validate_currency_value(currency)
    valid_description, clean_description, description_error = _normalize_optional_description(description)

    if not valid_amount:
        return False, [amount_error]
    if not valid_category:
        return False, [category_error]
    if not valid_date:
        return False, [clean_date]
    if not valid_currency:
        return False, [currency_error]
    if not valid_description:
        return False, [description_error]

    conn = get_db_connection()
    try:
        c = conn.cursor()
        if not _validate_category_for_type(c, clean_category_id, "expense"):
            return False, ["Category type must be 'expense' for expenses."]

        c.execute("SELECT id FROM expenses WHERE id = ?", (clean_expense_id,))
        if not c.fetchone():
            return False, ["Expense not found."]

        c.execute(
            """
            UPDATE expenses
            SET amount = ?, category_id = ?, description = ?, date = ?,
                payment_method = ?, currency = ?
            WHERE id = ?
            """,
            (
                float(clean_amount),
                clean_category_id,
                clean_description,
                clean_date,
                payment_method,
                clean_currency,
                clean_expense_id,
            ),
        )
        conn.commit()
        return True, "Success"
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, ["Unable to update expense because the data violates a database rule."]
    except sqlite3.Error:
        conn.rollback()
        logger.exception("Failed to update expense")
        return False, ["Unable to update expense."]
    finally:
        conn.close()


def delete_expense(expense_id) -> tuple[bool, str]:
    valid, clean_id, error = validate_id(expense_id)
    if not valid:
        return False, error

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM expenses WHERE id = ?", (clean_id,))
        if c.rowcount == 0:
            conn.rollback()
            return False, "Expense not found."
        conn.commit()
        return True, "Expense deleted successfully."
    except sqlite3.Error:
        conn.rollback()
        logger.exception("Failed to delete expense")
        return False, "Unable to delete expense."
    finally:
        conn.close()


def calculate_total_expenses(month=None, year=None, currency="PKR") -> float:
    valid_month, month = _validate_optional_month(month)
    valid_year, year = _validate_optional_year(year)
    valid_currency, currency = _validate_optional_currency(currency)

    if not valid_month or not valid_year or not valid_currency or currency is None:
        return 0.0

    query = "SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE currency = ?"
    params = [currency]

    if month is not None:
        query += " AND strftime('%m', date) = ?"
        params.append(f"{month:02d}")
    if year is not None:
        query += " AND strftime('%Y', date) = ?"
        params.append(str(year))

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(query, params)
        total = _safe_money(c.fetchone()[0])
        return float(total)
    except sqlite3.Error:
        logger.exception("Failed to calculate total expenses")
        return 0.0
    finally:
        conn.close()


# Income

def get_incomes(
    search=None,
    category_id=None,
    date_from=None,
    date_to=None,
    month=None,
    year=None,
    currency=None,
    sort_by="date",
    sort_order="desc",
) -> list[dict]:
    search = validate_search(search)

    valid_category, category_id = _validate_optional_id(category_id)
    if not valid_category:
        return []

    if date_from not in (None, "") and date_to not in (None, ""):
        valid_dates, _ = validate_date_range(date_from, date_to)
        if not valid_dates:
            return []
        _, date_from = validate_date(date_from)
        _, date_to = validate_date(date_to)
    else:
        valid_from, date_from = _validate_optional_date(date_from)
        valid_to, date_to = _validate_optional_date(date_to)
        if not valid_from or not valid_to:
            return []

    valid_month, month = _validate_optional_month(month)
    valid_year, year = _validate_optional_year(year)
    valid_currency, currency = _validate_optional_currency(currency)

    if not valid_month or not valid_year or not valid_currency:
        return []

    valid_sort_cols = {
        "date": "i.date",
        "amount": "i.amount",
        "category_name": "c.name",
    }
    sort_col = valid_sort_cols.get(sort_by, "i.date")
    sort_dir = "ASC" if isinstance(sort_order, str) and sort_order.lower() == "asc" else "DESC"

    query = """
        SELECT i.*, c.name as category_name
        FROM income i
        JOIN categories c ON i.category_id = c.id
        WHERE 1=1
    """
    params = []

    if search:
        search_esc = search.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        query += " AND (i.description LIKE ? ESCAPE '!' OR c.name LIKE ? ESCAPE '!')"
        params.extend([f"%{search_esc}%", f"%{search_esc}%"])
    if category_id is not None:
        query += " AND i.category_id = ?"
        params.append(category_id)
    if date_from:
        query += " AND i.date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND i.date <= ?"
        params.append(date_to)
    if month is not None:
        query += " AND strftime('%m', i.date) = ?"
        params.append(f"{month:02d}")
    if year is not None:
        query += " AND strftime('%Y', i.date) = ?"
        params.append(str(year))
    if currency:
        query += " AND i.currency = ?"
        params.append(currency)

    query += f" ORDER BY {sort_col} {sort_dir}"

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(query, params)
        return [dict(row) for row in c.fetchall()]
    except sqlite3.Error:
        logger.exception("Failed to retrieve income")
        return []
    finally:
        conn.close()


def get_income_by_id(income_id) -> dict | None:
    valid, clean_id, _ = validate_id(income_id)
    if not valid:
        return None

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT i.*, c.name as category_name
            FROM income i
            JOIN categories c ON i.category_id = c.id
            WHERE i.id = ?
            """,
            (clean_id,),
        )
        row = c.fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        logger.exception("Failed to retrieve income")
        return None
    finally:
        conn.close()


def add_income(amount, category_id, description, date, source, currency="PKR") -> tuple[bool, Any]:
    data = {
        "amount": amount,
        "category_id": category_id,
        "description": description,
        "date": date,
        "source": source,
        "currency": currency,
    }

    try:
        is_valid, errors = validate_income(data)
    except (TypeError, ValueError, AttributeError):
        return False, ["Invalid income data."]
    if not is_valid:
        return False, errors

    valid_amount, clean_amount, amount_error = _normalize_money(amount)
    valid_category, clean_category_id, category_error = validate_id(category_id)
    valid_date, clean_date = validate_date(date)
    valid_currency, clean_currency, currency_error = _validate_currency_value(currency)
    valid_description, clean_description, description_error = _normalize_optional_description(description)
    valid_source, clean_source, source_error = _normalize_source(source)

    if not valid_amount:
        return False, [amount_error]
    if not valid_category:
        return False, [category_error]
    if not valid_date:
        return False, [clean_date]
    if not valid_currency:
        return False, [currency_error]
    if not valid_description:
        return False, [description_error]
    if not valid_source:
        return False, [source_error]

    conn = get_db_connection()
    try:
        c = conn.cursor()
        if not _validate_category_for_type(c, clean_category_id, "income"):
            return False, ["Category type must be 'income' for incomes."]

        c.execute(
            """
            INSERT INTO income
                (amount, category_id, description, date, source, currency)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                float(clean_amount),
                clean_category_id,
                clean_description,
                clean_date,
                clean_source,
                clean_currency,
            ),
        )
        conn.commit()
        return True, c.lastrowid
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, ["Unable to save income because the data violates a database rule."]
    except sqlite3.Error:
        conn.rollback()
        logger.exception("Failed to add income")
        return False, ["Unable to save income."]
    finally:
        conn.close()


def update_income(income_id, amount, category_id, description, date, source, currency="PKR") -> tuple[bool, Any]:
    valid_id, clean_income_id, id_error = validate_id(income_id)
    if not valid_id:
        return False, [id_error]

    data = {
        "amount": amount,
        "category_id": category_id,
        "description": description,
        "date": date,
        "source": source,
        "currency": currency,
    }

    try:
        is_valid, errors = validate_income(data)
    except (TypeError, ValueError, AttributeError):
        return False, ["Invalid income data."]
    if not is_valid:
        return False, errors

    valid_amount, clean_amount, amount_error = _normalize_money(amount)
    valid_category, clean_category_id, category_error = validate_id(category_id)
    valid_date, clean_date = validate_date(date)
    valid_currency, clean_currency, currency_error = _validate_currency_value(currency)
    valid_description, clean_description, description_error = _normalize_optional_description(description)
    valid_source, clean_source, source_error = _normalize_source(source)

    if not valid_amount:
        return False, [amount_error]
    if not valid_category:
        return False, [category_error]
    if not valid_date:
        return False, [clean_date]
    if not valid_currency:
        return False, [currency_error]
    if not valid_description:
        return False, [description_error]
    if not valid_source:
        return False, [source_error]

    conn = get_db_connection()
    try:
        c = conn.cursor()
        if not _validate_category_for_type(c, clean_category_id, "income"):
            return False, ["Category type must be 'income' for incomes."]

        c.execute("SELECT id FROM income WHERE id = ?", (clean_income_id,))
        if not c.fetchone():
            return False, ["Income not found."]

        c.execute(
            """
            UPDATE income
            SET amount = ?, category_id = ?, description = ?, date = ?,
                source = ?, currency = ?
            WHERE id = ?
            """,
            (
                float(clean_amount),
                clean_category_id,
                clean_description,
                clean_date,
                clean_source,
                clean_currency,
                clean_income_id,
            ),
        )
        conn.commit()
        return True, "Success"
    except sqlite3.IntegrityError:
        conn.rollback()
        return False, ["Unable to update income because the data violates a database rule."]
    except sqlite3.Error:
        conn.rollback()
        logger.exception("Failed to update income")
        return False, ["Unable to update income."]
    finally:
        conn.close()


def delete_income(income_id) -> tuple[bool, str]:
    valid, clean_id, error = validate_id(income_id)
    if not valid:
        return False, error

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM income WHERE id = ?", (clean_id,))
        if c.rowcount == 0:
            conn.rollback()
            return False, "Income not found."
        conn.commit()
        return True, "Income deleted successfully."
    except sqlite3.Error:
        conn.rollback()
        logger.exception("Failed to delete income")
        return False, "Unable to delete income."
    finally:
        conn.close()


def calculate_total_income(month=None, year=None, currency="PKR") -> float:
    valid_month, month = _validate_optional_month(month)
    valid_year, year = _validate_optional_year(year)
    valid_currency, currency = _validate_optional_currency(currency)

    if not valid_month or not valid_year or not valid_currency or currency is None:
        return 0.0

    query = "SELECT COALESCE(SUM(amount), 0) FROM income WHERE currency = ?"
    params = [currency]

    if month is not None:
        query += " AND strftime('%m', date) = ?"
        params.append(f"{month:02d}")
    if year is not None:
        query += " AND strftime('%Y', date) = ?"
        params.append(str(year))

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(query, params)
        total = _safe_money(c.fetchone()[0])
        return float(total)
    except sqlite3.Error:
        logger.exception("Failed to calculate total income")
        return 0.0
    finally:
        conn.close()


# Budgets

def get_budgets(month=None, year=None, currency=None) -> list[dict]:
    valid_month, month = _validate_optional_month(month)
    valid_year, year = _validate_optional_year(year)
    valid_currency, currency = _validate_optional_currency(currency)

    if not valid_month or not valid_year or not valid_currency:
        return []

    query = """
        SELECT b.*, c.name as category_name
        FROM budgets b
        JOIN categories c ON b.category_id = c.id
        WHERE 1=1
    """
    params = []

    if month is not None:
        query += " AND b.month = ?"
        params.append(month)
    if year is not None:
        query += " AND b.year = ?"
        params.append(year)
    if currency:
        query += " AND b.currency = ?"
        params.append(currency)

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(query, params)
        budgets = [dict(row) for row in c.fetchall()]
    except sqlite3.Error:
        logger.exception("Failed to retrieve budgets")
        return []
    finally:
        conn.close()

    for budget in budgets:
        status_info = calculate_budget_status(
            budget["amount"],
            budget["category_id"],
            budget["month"],
            budget["year"],
            budget["currency"],
            budget.get("alert_percentage"),
        )
        budget.update(status_info)

    return budgets


def get_budget_by_id(budget_id) -> dict | None:
    valid, clean_id, _ = validate_id(budget_id)
    if not valid:
        return None

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT b.*, c.name as category_name
            FROM budgets b
            JOIN categories c ON b.category_id = c.id
            WHERE b.id = ?
            """,
            (clean_id,),
        )
        row = c.fetchone()
        if not row:
            return None
        budget = dict(row)
    except sqlite3.Error:
        logger.exception("Failed to retrieve budget")
        return None
    finally:
        conn.close()

    status_info = calculate_budget_status(
        budget["amount"],
        budget["category_id"],
        budget["month"],
        budget["year"],
        budget["currency"],
        budget.get("alert_percentage"),
    )
    budget.update(status_info)
    return budget


def _normalize_alert_percentage(value) -> tuple[bool, Decimal | None, str | None]:
    if value is None or value == "":
        value = 80

    if isinstance(value, bool):
        return False, None, "Invalid alert percentage."

    try:
        alert = Decimal(str(value).strip() if isinstance(value, str) else str(value))
    except (InvalidOperation, ValueError, TypeError):
        return False, None, "Invalid alert percentage."

    if not alert.is_finite() or not (Decimal("1") <= alert <= Decimal("100")):
        return False, None, "Alert percentage must be between 1 and 100."

    return True, alert.quantize(MONEY_QUANT), None


def create_budget(category_id, amount, month, year, currency="PKR", alert_percentage=80) -> tuple[bool, str]:
    data = {
        "category_id": category_id,
        "amount": amount,
        "month": month,
        "year": year,
        "currency": currency,
        "alert_percentage": alert_percentage,
    }

    try:
        is_valid, errors = validate_budget(data)
    except (TypeError, ValueError, AttributeError):
        return False, "Invalid budget data."
    if not is_valid:
        return False, "; ".join(errors)

    valid_amount, clean_amount, amount_error = _normalize_money(amount)
    valid_category, clean_category_id, category_error = validate_id(category_id)
    valid_month, clean_month, month_error = validate_month(month)
    valid_year, clean_year, year_error = validate_year(year)
    valid_currency, clean_currency, currency_error = _validate_currency_value(currency)
    valid_alert, clean_alert, alert_error = _normalize_alert_percentage(alert_percentage)

    if not valid_amount:
        return False, amount_error
    if not valid_category:
        return False, category_error
    if not valid_month:
        return False, month_error
    if not valid_year:
        return False, year_error
    if not valid_currency:
        return False, currency_error
    if not valid_alert:
        return False, alert_error

    conn = get_db_connection()
    try:
        c = conn.cursor()

        if not _validate_category_for_type(c, clean_category_id, "expense"):
            return False, "Category type must be 'expense' for budgets."

        c.execute(
            """
            SELECT id FROM budgets
            WHERE category_id = ? AND month = ? AND year = ? AND currency = ?
            LIMIT 1
            """,
            (clean_category_id, clean_month, clean_year, clean_currency),
        )
        if c.fetchone():
            return False, "Budget for this category, month, year, and currency already exists."

        c.execute(
            """
            INSERT INTO budgets
                (category_id, amount, month, year, currency, alert_percentage)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                clean_category_id,
                float(clean_amount),
                clean_month,
                clean_year,
                clean_currency,
                float(clean_alert),
            ),
        )
        conn.commit()
        return True, "Budget created successfully."
    except sqlite3.IntegrityError as error:
        conn.rollback()
        if _is_budget_duplicate_error(error):
            return False, "Budget for this category, month, year, and currency already exists."
        logger.exception("Budget insert integrity error")
        return False, "Unable to create budget because the data violates a database rule."
    except sqlite3.Error:
        conn.rollback()
        logger.exception("Failed to create budget")
        return False, "Unable to create budget."
    finally:
        conn.close()


def update_budget(
    budget_id,
    category_id,
    amount,
    month,
    year,
    currency="PKR",
    alert_percentage=80,
) -> tuple[bool, str]:
    valid_id, clean_budget_id, id_error = validate_id(budget_id)
    if not valid_id:
        return False, id_error

    data = {
        "category_id": category_id,
        "amount": amount,
        "month": month,
        "year": year,
        "currency": currency,
        "alert_percentage": alert_percentage,
    }

    try:
        is_valid, errors = validate_budget(data)
    except (TypeError, ValueError, AttributeError):
        return False, "Invalid budget data."
    if not is_valid:
        return False, "; ".join(errors)

    valid_amount, clean_amount, amount_error = _normalize_money(amount)
    valid_category, clean_category_id, category_error = validate_id(category_id)
    valid_month, clean_month, month_error = validate_month(month)
    valid_year, clean_year, year_error = validate_year(year)
    valid_currency, clean_currency, currency_error = _validate_currency_value(currency)
    valid_alert, clean_alert, alert_error = _normalize_alert_percentage(alert_percentage)

    if not valid_amount:
        return False, amount_error
    if not valid_category:
        return False, category_error
    if not valid_month:
        return False, month_error
    if not valid_year:
        return False, year_error
    if not valid_currency:
        return False, currency_error
    if not valid_alert:
        return False, alert_error

    conn = get_db_connection()
    try:
        c = conn.cursor()

        c.execute("SELECT id FROM budgets WHERE id = ?", (clean_budget_id,))
        if not c.fetchone():
            return False, "Budget not found."

        if not _validate_category_for_type(c, clean_category_id, "expense"):
            return False, "Category type must be 'expense' for budgets."

        c.execute(
            """
            SELECT id FROM budgets
            WHERE category_id = ? AND month = ? AND year = ? AND currency = ?
              AND id != ?
            LIMIT 1
            """,
            (
                clean_category_id,
                clean_month,
                clean_year,
                clean_currency,
                clean_budget_id,
            ),
        )
        if c.fetchone():
            return False, "Budget for this category, month, year, and currency already exists."

        c.execute(
            """
            UPDATE budgets
            SET category_id = ?, amount = ?, month = ?, year = ?,
                currency = ?, alert_percentage = ?
            WHERE id = ?
            """,
            (
                clean_category_id,
                float(clean_amount),
                clean_month,
                clean_year,
                clean_currency,
                float(clean_alert),
                clean_budget_id,
            ),
        )
        conn.commit()
        return True, "Budget updated successfully."
    except sqlite3.IntegrityError as error:
        conn.rollback()
        if _is_budget_duplicate_error(error):
            return False, "Budget for this category, month, year, and currency already exists."
        logger.exception("Budget update integrity error")
        return False, "Unable to update budget because the data violates a database rule."
    except sqlite3.Error:
        conn.rollback()
        logger.exception("Failed to update budget")
        return False, "Unable to update budget."
    finally:
        conn.close()


def delete_budget(budget_id) -> tuple[bool, str]:
    valid, clean_id, error = validate_id(budget_id)
    if not valid:
        return False, error

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM budgets WHERE id = ?", (clean_id,))
        if c.rowcount == 0:
            conn.rollback()
            return False, "Budget not found."
        conn.commit()
        return True, "Budget deleted successfully."
    except sqlite3.Error:
        conn.rollback()
        logger.exception("Failed to delete budget")
        return False, "Unable to delete budget."
    finally:
        conn.close()


def calculate_budget_status(
    budget_amount,
    category_id,
    month,
    year,
    currency,
    alert_percentage=None,
) -> dict:
    budget_value = _safe_money(budget_amount)

    valid_category, category_id = _validate_optional_id(category_id)
    valid_month, month = _validate_optional_month(month)
    valid_year, year = _validate_optional_year(year)
    valid_currency, currency = _validate_optional_currency(currency)

    if not valid_category or not valid_month or month is None or not valid_year or year is None or not valid_currency or currency is None:
        return {
            "spent": 0.0,
            "remaining": float(budget_value),
            "percentage_used": 0.0,
            "status": "Safe",
        }

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT COALESCE(SUM(amount), 0) FROM expenses
            WHERE category_id = ?
              AND strftime('%m', date) = ?
              AND strftime('%Y', date) = ?
              AND currency = ?
            """,
            (category_id, f"{month:02d}", str(year), currency),
        )
        spent = _safe_money(c.fetchone()[0])

        if alert_percentage is None:
            c.execute(
                """
                SELECT alert_percentage FROM budgets
                WHERE category_id = ? AND month = ? AND year = ? AND currency = ?
                LIMIT 1
                """,
                (category_id, month, year, currency),
            )
            row = c.fetchone()
            alert_percentage = row[0] if row else DEFAULT_ALERT_PERCENTAGE
    except sqlite3.Error:
        logger.exception("Failed to calculate budget status")
        return {
            "spent": float(spent) if "spent" in locals() else 0.0,
            "remaining": float(budget_value),
            "percentage_used": 0.0,
            "status": "Safe",
        }
    finally:
        conn.close()

    alert_value = _safe_money(alert_percentage)
    if alert_value <= 0:
        alert_value = DEFAULT_ALERT_PERCENTAGE

    remaining = budget_value - spent
    percentage_used = (spent / budget_value * Decimal("100")) if budget_value > 0 else (
        Decimal("100") if spent > 0 else Decimal("0")
    )

    if percentage_used >= Decimal("100"):
        status = "Exceeded"
    elif percentage_used >= alert_value:
        status = "Warning"
    else:
        status = "Safe"

    return {
        "spent": float(spent),
        "remaining": float(remaining.quantize(MONEY_QUANT)),
        "percentage_used": float(percentage_used.quantize(MONEY_QUANT)),
        "status": status,
    }


def check_budget_alerts(month, year, currency="PKR") -> list[dict]:
    valid_month, month = _validate_optional_month(month)
    valid_year, year = _validate_optional_year(year)
    valid_currency, currency = _validate_optional_currency(currency)

    if not valid_month or month is None or not valid_year or year is None or not valid_currency or currency is None:
        return []

    budgets = get_budgets(month, year, currency)
    alerts = []

    for budget in budgets:
        if budget["status"] in ("Warning", "Exceeded"):
            alerts.append(
                {
                    "category_name": budget["category_name"],
                    "budget_amount": budget["amount"],
                    "spent": budget["spent"],
                    "percentage_used": budget["percentage_used"],
                    "status": budget["status"],
                    "alert_percentage": budget["alert_percentage"],
                }
            )

    return alerts


# Dashboard

def get_dashboard_data(month, year, currency="PKR") -> dict:
    valid_month, month = _validate_optional_month(month)
    valid_year, year = _validate_optional_year(year)
    valid_currency, currency = _validate_optional_currency(currency)

    if not valid_month or month is None or not valid_year or year is None or not valid_currency or currency is None:
        return {}

    total_expenses = calculate_total_expenses(month, year, currency)
    total_income = calculate_total_income(month, year, currency)
    balance = float((_safe_money(total_income) - _safe_money(total_expenses)).quantize(MONEY_QUANT))

    budgets = get_budgets(month, year, currency)
    total_budget = float(_safe_money(sum(_safe_money(b["amount"]) for b in budgets)))
    total_spent = float(_safe_money(sum(_safe_money(b["spent"]) for b in budgets)))

    alerts = [
        {
            "category_name": b["category_name"],
            "budget_amount": b["amount"],
            "spent": b["spent"],
            "percentage_used": b["percentage_used"],
            "status": b["status"],
            "alert_percentage": b["alert_percentage"],
        }
        for b in budgets
        if b["status"] in ("Warning", "Exceeded")
    ]

    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT COUNT(*) FROM expenses
            WHERE strftime('%m', date) = ?
              AND strftime('%Y', date) = ?
              AND currency = ?
            """,
            (f"{month:02d}", str(year), currency),
        )
        expense_count = c.fetchone()[0]

        c.execute(
            """
            SELECT COUNT(*) FROM income
            WHERE strftime('%m', date) = ?
              AND strftime('%Y', date) = ?
              AND currency = ?
            """,
            (f"{month:02d}", str(year), currency),
        )
        income_count = c.fetchone()[0]
    except sqlite3.Error:
        logger.exception("Failed to retrieve dashboard counts")
        expense_count = 0
        income_count = 0
    finally:
        conn.close()

    return {
        "total_income": total_income,
        "total_expenses": total_expenses,
        "balance": balance,
        "total_budget": total_budget,
        "total_spent": total_spent,
        "expense_count": expense_count,
        "income_count": income_count,
        "alerts": alerts,
        "budgets_with_status": budgets,
    }
