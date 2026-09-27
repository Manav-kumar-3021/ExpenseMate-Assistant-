import datetime
import re
import unicodedata
from decimal import Decimal, InvalidOperation

VALID_CURRENCIES = ['PKR', 'USD', 'EUR', 'GBP', 'AED', 'SAR']

PAYMENT_METHODS = [
    'Cash',
    'Credit Card',
    'Debit Card',
    'Bank Transfer',
    'Mobile Wallet',
    'Other'
]

MIN_AMOUNT = Decimal('0.01')
MAX_AMOUNT = Decimal('99999999.99')

MIN_YEAR = 2000
MAX_YEAR = 2100

MAX_DESCRIPTION_LENGTH = 500
MAX_CATEGORY_NAME_LENGTH = 100
MAX_SOURCE_LENGTH = 500
MAX_SEARCH_LENGTH = 200
MAX_NUMERIC_INPUT_LENGTH = 30

CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x1F\x7F]')
DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')
INTEGER_PATTERN = re.compile(r'^[1-9]\d*$')
AMOUNT_PATTERN = re.compile(r'^\d+(?:\.\d{1,2})?$')
PERCENTAGE_PATTERN = re.compile(r'^\d+(?:\.\d{1,2})?$')


def _is_string(value):
    return isinstance(value, str)


def _contains_control_chars(value):
    return bool(CONTROL_CHAR_PATTERN.search(value))


def _clean_text(value):
    if not isinstance(value, str):
        return None

    value = unicodedata.normalize('NFKC', value)
    value = value.strip()

    if not value:
        return ''

    if _contains_control_chars(value):
        return None

    return value


def validate_amount(amount_str):
    if amount_str is None:
        return (False, None, "Amount is required.")

    if isinstance(amount_str, bool):
        return (False, None, "Amount must be a valid number.")

    if not isinstance(amount_str, (str, int, float, Decimal)):
        return (False, None, "Amount must be a valid number.")

    if isinstance(amount_str, str):
        amount_str = amount_str.strip()

        if not amount_str:
            return (False, None, "Amount is required.")

        if len(amount_str) > MAX_NUMERIC_INPUT_LENGTH:
            return (False, None, "Amount is too long.")

    try:
        amount = Decimal(str(amount_str))
    except (InvalidOperation, ValueError, TypeError):
        return (False, None, "Amount must be a valid number.")

    if not amount.is_finite():
        return (False, None, "Amount must be a finite number.")

    if isinstance(amount_str, str) and not AMOUNT_PATTERN.fullmatch(amount_str):
        return (
            False,
            None,
            "Amount must be a positive number with at most 2 decimal places."
        )

    if amount < MIN_AMOUNT:
        return (False, None, "Amount must be greater than zero.")

    if amount > MAX_AMOUNT:
        return (
            False,
            None,
            f"Amount cannot exceed {MAX_AMOUNT}."
        )

    if amount.as_tuple().exponent < -2:
        return (
            False,
            None,
            "Amount can have at most 2 decimal places."
        )

    return (True, float(amount), None)


def validate_date(date_str):
    if date_str is None:
        return (False, "Date is required.")

    if not isinstance(date_str, str):
        return (False, "Date must be in YYYY-MM-DD format.")

    date_str = date_str.strip()

    if not date_str:
        return (False, "Date is required.")

    if len(date_str) != 10:
        return (False, "Date must be in YYYY-MM-DD format.")

    if not DATE_PATTERN.fullmatch(date_str):
        return (False, "Date must be in YYYY-MM-DD format.")

    try:
        parsed_date = datetime.datetime.strptime(
            date_str,
            '%Y-%m-%d'
        ).date()
    except ValueError:
        return (False, "Invalid date.")

    if not (MIN_YEAR <= parsed_date.year <= MAX_YEAR):
        return (
            False,
            f"Year must be between {MIN_YEAR} and {MAX_YEAR}."
        )

    return (True, parsed_date.isoformat())


def validate_id(id_val):
    if id_val is None or id_val == '':
        return (False, None, "ID is required.")

    if isinstance(id_val, bool):
        return (False, None, "ID must be an integer.")

    if isinstance(id_val, int):
        if id_val <= 0:
            return (False, None, "ID must be a positive integer.")
        return (True, id_val, None)

    if not isinstance(id_val, str):
        return (False, None, "ID must be an integer.")

    id_val = id_val.strip()

    if not id_val:
        return (False, None, "ID is required.")

    if len(id_val) > 12:
        return (False, None, "ID is too long.")

    if not INTEGER_PATTERN.fullmatch(id_val):
        return (False, None, "ID must be a positive integer.")

    try:
        val = int(id_val)
    except ValueError:
        return (False, None, "ID must be an integer.")

    return (True, val, None)


def validate_month(month_val):
    if month_val is None or month_val == '':
        return (False, None, "Month is required.")

    if isinstance(month_val, bool):
        return (False, None, "Month must be an integer.")

    if isinstance(month_val, int):
        val = month_val
    elif isinstance(month_val, str):
        month_val = month_val.strip()

        if not month_val:
            return (False, None, "Month is required.")

        if not re.fullmatch(r'^(0?[1-9]|1[0-2])$', month_val):
            return (False, None, "Month must be an integer between 1 and 12.")

        val = int(month_val)
    else:
        return (False, None, "Month must be an integer.")

    if not (1 <= val <= 12):
        return (False, None, "Month must be between 1 and 12.")

    return (True, val, None)


def validate_year(year_val):
    if year_val is None or year_val == '':
        return (False, None, "Year is required.")

    if isinstance(year_val, bool):
        return (False, None, "Year must be an integer.")

    if isinstance(year_val, int):
        val = year_val
    elif isinstance(year_val, str):
        year_val = year_val.strip()

        if not re.fullmatch(r'^\d{4}$', year_val):
            return (False, None, "Year must be a 4-digit integer.")

        val = int(year_val)
    else:
        return (False, None, "Year must be an integer.")

    if not (MIN_YEAR <= val <= MAX_YEAR):
        return (
            False,
            None,
            f"Year must be between {MIN_YEAR} and {MAX_YEAR}."
        )

    return (True, val, None)


def validate_currency(currency):
    if currency is None:
        return (False, "Currency is required.")

    if not isinstance(currency, str):
        return (False, "Invalid currency.")

    currency = currency.strip().upper()

    if not currency:
        return (False, "Currency is required.")

    if currency not in VALID_CURRENCIES:
        return (False, "Invalid currency.")

    return (True, None)


def validate_date_range(date_from, date_to):
    valid_from, date_from_res = validate_date(date_from)

    if not valid_from:
        return (
            False,
            "Invalid 'from' date: " + date_from_res
        )

    valid_to, date_to_res = validate_date(date_to)

    if not valid_to:
        return (
            False,
            "Invalid 'to' date: " + date_to_res
        )

    if date_from_res > date_to_res:
        return (
            False,
            "From date cannot be after to date."
        )

    return (True, None)


def validate_search(search_str):
    if search_str is None:
        return ""

    if not isinstance(search_str, str):
        return ""

    search_str = unicodedata.normalize('NFKC', search_str)
    search_str = search_str.strip()

    if _contains_control_chars(search_str):
        return ""

    return search_str[:MAX_SEARCH_LENGTH]


def validate_description(description):
    if description is None:
        return (True, '', None)

    if not isinstance(description, str):
        return (False, None, "Description must be text.")

    description = unicodedata.normalize('NFKC', description)

    if _contains_control_chars(description):
        return (
            False,
            None,
            "Description contains invalid characters."
        )

    if len(description) > MAX_DESCRIPTION_LENGTH:
        return (
            False,
            None,
            f"Description cannot exceed {MAX_DESCRIPTION_LENGTH} characters."
        )

    return (True, description, None)


def validate_source(source):
    if source is None:
        return (True, '', None)

    if not isinstance(source, str):
        return (False, None, "Source must be text.")

    source = unicodedata.normalize('NFKC', source)

    if _contains_control_chars(source):
        return (
            False,
            None,
            "Source contains invalid characters."
        )

    if len(source) > MAX_SOURCE_LENGTH:
        return (
            False,
            None,
            f"Source cannot exceed {MAX_SOURCE_LENGTH} characters."
        )

    return (True, source, None)


def validate_expense(data: dict) -> tuple[bool, list[str]]:
    errors = []

    if not isinstance(data, dict):
        return (False, ["Invalid expense data."])

    valid_amount, amount, amt_err = validate_amount(
        data.get('amount')
    )

    if not valid_amount:
        errors.append(amt_err)

    valid_cat, cat_val, cat_err = validate_id(
        data.get('category_id')
    )

    if not valid_cat:
        errors.append(cat_err)

    valid_date, date_err = validate_date(
        data.get('date')
    )

    if not valid_date:
        errors.append(date_err)

    valid_curr, curr_err = validate_currency(
        data.get('currency')
    )

    if not valid_curr:
        errors.append(curr_err)

    payment_method = data.get('payment_method')

    if payment_method not in (None, ''):
        if not isinstance(payment_method, str):
            errors.append("Invalid payment method.")
        elif payment_method not in PAYMENT_METHODS:
            errors.append("Invalid payment method.")

    valid_desc, desc_val, desc_err = validate_description(
        data.get('description')
    )

    if not valid_desc:
        errors.append(desc_err)

    return (len(errors) == 0, errors)


def validate_income(data: dict) -> tuple[bool, list[str]]:
    errors = []

    if not isinstance(data, dict):
        return (False, ["Invalid income data."])

    valid_amount, amount, amt_err = validate_amount(
        data.get('amount')
    )

    if not valid_amount:
        errors.append(amt_err)

    valid_cat, cat_val, cat_err = validate_id(
        data.get('category_id')
    )

    if not valid_cat:
        errors.append(cat_err)

    valid_date, date_err = validate_date(
        data.get('date')
    )

    if not valid_date:
        errors.append(date_err)

    valid_curr, curr_err = validate_currency(
        data.get('currency')
    )

    if not valid_curr:
        errors.append(curr_err)

    valid_desc, desc_val, desc_err = validate_description(
        data.get('description')
    )

    if not valid_desc:
        errors.append(desc_err)

    # Source is checked only when the caller supplies it.
    if 'source' in data:
        valid_source, source_val, source_err = validate_source(
            data.get('source')
        )

        if not valid_source:
            errors.append(source_err)

    return (len(errors) == 0, errors)


def validate_budget(data: dict) -> tuple[bool, list[str]]:
    errors = []

    if not isinstance(data, dict):
        return (False, ["Invalid budget data."])

    valid_amount, amount, amt_err = validate_amount(
        data.get('amount')
    )

    if not valid_amount:
        errors.append(amt_err)

    valid_cat, cat_val, cat_err = validate_id(
        data.get('category_id')
    )

    if not valid_cat:
        errors.append(cat_err)

    valid_mon, mon_val, mon_err = validate_month(
        data.get('month')
    )

    if not valid_mon:
        errors.append(mon_err)

    valid_yr, yr_val, yr_err = validate_year(
        data.get('year')
    )

    if not valid_yr:
        errors.append(yr_err)

    valid_curr, curr_err = validate_currency(
        data.get('currency')
    )

    if not valid_curr:
        errors.append(curr_err)

    alert_value = data.get('alert_percentage', 80)

    if isinstance(alert_value, bool):
        errors.append("Invalid alert percentage.")
    elif isinstance(alert_value, (int, float, Decimal)):
        try:
            alert = Decimal(str(alert_value))

            if not alert.is_finite():
                errors.append("Invalid alert percentage.")
            elif not (Decimal('1') <= alert <= Decimal('100')):
                errors.append(
                    "Alert percentage must be between 1 and 100."
                )
        except (InvalidOperation, ValueError, TypeError):
            errors.append("Invalid alert percentage.")

    elif isinstance(alert_value, str):
        alert_value = alert_value.strip()

        if (
            not alert_value
            or len(alert_value) > MAX_NUMERIC_INPUT_LENGTH
            or not PERCENTAGE_PATTERN.fullmatch(alert_value)
        ):
            errors.append("Invalid alert percentage.")
        else:
            try:
                alert = Decimal(alert_value)

                if not (Decimal('1') <= alert <= Decimal('100')):
                    errors.append(
                        "Alert percentage must be between 1 and 100."
                    )
            except (InvalidOperation, ValueError, TypeError):
                errors.append("Invalid alert percentage.")

    else:
        errors.append("Invalid alert percentage.")

    return (len(errors) == 0, errors)


def validate_category(data: dict) -> tuple[bool, list[str]]:
    errors = []

    if not isinstance(data, dict):
        return (False, ["Invalid category data."])

    raw_name = data.get('name', '')

    if raw_name is None:
        name = ''
    elif isinstance(raw_name, str):
        name = unicodedata.normalize('NFKC', raw_name).strip()
    else:
        name = ''

    if not name:
        errors.append("Category name is required.")
    elif _contains_control_chars(name):
        errors.append("Category name contains invalid characters.")
    elif len(name) > MAX_CATEGORY_NAME_LENGTH:
        errors.append(
            f"Category name cannot exceed "
            f"{MAX_CATEGORY_NAME_LENGTH} characters."
        )

    category_type = data.get('type')

    if not isinstance(category_type, str):
        errors.append("Type must be 'expense' or 'income'.")
    elif category_type not in ('expense', 'income'):
        errors.append("Type must be 'expense' or 'income'.")

    return (len(errors) == 0, errors)