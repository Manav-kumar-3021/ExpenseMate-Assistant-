import calendar
import datetime

from database import get_db_connection
from services import calculate_total_expenses, calculate_total_income
from validators import VALID_CURRENCIES, validate_month, validate_year


def _normalize_currency(currency):
    if not isinstance(currency, str):
        return None
    value = currency.strip().upper()
    return value if value in VALID_CURRENCIES else None


def get_analytics_data(month=None, year=None, currency='PKR') -> dict:
    if year is None:
        year = datetime.date.today().year
    else:
        valid_year, year_value, _ = validate_year(year)
        year = year_value if valid_year else datetime.date.today().year

    if month is not None:
        valid_month, month_value, _ = validate_month(month)
        month = month_value if valid_month else None

    currency = _normalize_currency(currency) or 'PKR'

    total_expenses = calculate_total_expenses(month, year, currency)
    total_income = calculate_total_income(month, year, currency)
    balance = round(total_income - total_expenses, 2)

    conn = get_db_connection()
    try:
        c = conn.cursor()

        exp_category_query = """
            SELECT c.name AS category, COALESCE(SUM(e.amount), 0) AS total
            FROM expenses e
            JOIN categories c ON e.category_id = c.id
            WHERE strftime('%Y', e.date) = ?
              AND e.currency = ?
        """
        exp_category_params = [str(year), currency]
        if month is not None:
            exp_category_query += " AND strftime('%m', e.date) = ?"
            exp_category_params.append(f"{month:02d}")
        exp_category_query += " GROUP BY c.id, c.name ORDER BY total DESC"
        c.execute(exp_category_query, exp_category_params)
        category_expenses = [
            {'category': row['category'], 'total': round(float(row['total']), 2)}
            for row in c.fetchall()
        ]

        highest_spending_category = (
            category_expenses[0]['category'] if category_expenses else 'N/A'
        )

        inc_category_query = """
            SELECT c.name AS category, COALESCE(SUM(i.amount), 0) AS total
            FROM income i
            JOIN categories c ON i.category_id = c.id
            WHERE strftime('%Y', i.date) = ?
              AND i.currency = ?
        """
        inc_category_params = [str(year), currency]
        if month is not None:
            inc_category_query += " AND strftime('%m', i.date) = ?"
            inc_category_params.append(f"{month:02d}")
        inc_category_query += " GROUP BY c.id, c.name ORDER BY total DESC"
        c.execute(inc_category_query, inc_category_params)
        category_income = [
            {'category': row['category'], 'total': round(float(row['total']), 2)}
            for row in c.fetchall()
        ]

        c.execute(
            """
            SELECT CAST(strftime('%m', date) AS INTEGER) AS month,
                   COALESCE(SUM(amount), 0) AS total
            FROM expenses
            WHERE strftime('%Y', date) = ?
              AND currency = ?
            GROUP BY strftime('%m', date)
            ORDER BY month
            """,
            (str(year), currency),
        )
        expense_by_month = {
            int(row['month']): round(float(row['total']), 2)
            for row in c.fetchall()
        }

        c.execute(
            """
            SELECT CAST(strftime('%m', date) AS INTEGER) AS month,
                   COALESCE(SUM(amount), 0) AS total
            FROM income
            WHERE strftime('%Y', date) = ?
              AND currency = ?
            GROUP BY strftime('%m', date)
            ORDER BY month
            """,
            (str(year), currency),
        )
        income_by_month = {
            int(row['month']): round(float(row['total']), 2)
            for row in c.fetchall()
        }

        monthly_expenses = []
        monthly_income = []
        for month_number in range(1, 13):
            monthly_expenses.append({
                'month': month_number,
                'month_name': calendar.month_name[month_number],
                'total': expense_by_month.get(month_number, 0.0),
            })
            monthly_income.append({
                'month': month_number,
                'month_name': calendar.month_name[month_number],
                'total': income_by_month.get(month_number, 0.0),
            })

        stats_query = """
            SELECT COALESCE(MAX(amount), 0) AS maximum,
                   COALESCE(AVG(amount), 0) AS average,
                   COUNT(*) AS expense_count
            FROM expenses
            WHERE strftime('%Y', date) = ?
              AND currency = ?
        """
        stats_params = [str(year), currency]
        if month is not None:
            stats_query += " AND strftime('%m', date) = ?"
            stats_params.append(f"{month:02d}")
        c.execute(stats_query, stats_params)
        stats = c.fetchone()

        count_query = """
            SELECT
                (SELECT COUNT(*) FROM expenses
                 WHERE strftime('%Y', date) = ? AND currency = ? {expense_month})
                +
                (SELECT COUNT(*) FROM income
                 WHERE strftime('%Y', date) = ? AND currency = ? {income_month})
                AS transaction_count
        """
        if month is not None:
            count_query = count_query.format(
                expense_month=" AND strftime('%m', date) = ?",
                income_month=" AND strftime('%m', date) = ?",
            )
            count_params = [str(year), currency, f"{month:02d}", str(year), currency, f"{month:02d}"]
        else:
            count_query = count_query.format(expense_month="", income_month="")
            count_params = [str(year), currency, str(year), currency]
        c.execute(count_query, count_params)
        transaction_count = int(c.fetchone()['transaction_count'] or 0)

    finally:
        conn.close()

    return {
        'total_expenses': total_expenses,
        'total_income': total_income,
        'balance': balance,
        'category_expenses': category_expenses,
        'category_income': category_income,
        'monthly_expenses': monthly_expenses,
        'monthly_income': monthly_income,
        'highest_spending_category': highest_spending_category,
        'highest_expense': round(float(stats['maximum'] or 0.0), 2),
        'average_expense': round(float(stats['average'] or 0.0), 2),
        'transaction_count': transaction_count,
    }
