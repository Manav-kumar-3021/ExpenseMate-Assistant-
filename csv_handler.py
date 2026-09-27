import csv
import io
import logging
import unicodedata

from services import add_expense, add_income, get_categories

logger = logging.getLogger(__name__)

MAX_CSV_SIZE = 5 * 1024 * 1024
MAX_CSV_ROWS = 5000
MAX_CSV_FIELD_SIZE = 64 * 1024
MAX_ERROR_MESSAGE_LENGTH = 500

EXPENSE_HEADERS = {
    'id',
    'amount',
    'category',
    'description',
    'date',
    'payment_method',
    'currency',
}

INCOME_HEADERS = {
    'id',
    'amount',
    'category',
    'description',
    'date',
    'source',
    'currency',
}

EXPENSE_REQUIRED_HEADERS = {'amount', 'category', 'date'}
INCOME_REQUIRED_HEADERS = {'amount', 'category', 'date'}

CSV_FORMULA_PREFIXES = ('=', '+', '-', '@')

try:
    csv.field_size_limit(MAX_CSV_FIELD_SIZE)
except (OverflowError, ValueError):
    csv.field_size_limit(64 * 1024)


def _safe_csv_cell(value):
    """Protect exported text cells from spreadsheet formula execution."""
    if not isinstance(value, str):
        return value

    stripped = value.lstrip()
    if stripped.startswith(CSV_FORMULA_PREFIXES):
        return "'" + value

    return value


def _csv_value(record: dict, key: str, default=''):
    value = record.get(key, default)
    if value is None:
        return default
    return _safe_csv_cell(value)


def export_expenses_csv(expenses: list[dict]) -> str:
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')

    writer.writerow([
        'id',
        'amount',
        'category',
        'description',
        'date',
        'payment_method',
        'currency',
    ])

    for expense in expenses or []:
        writer.writerow([
            expense.get('id', ''),
            expense.get('amount', ''),
            _csv_value(expense, 'category_name'),
            _csv_value(expense, 'description'),
            _csv_value(expense, 'date'),
            _csv_value(expense, 'payment_method'),
            _csv_value(expense, 'currency'),
        ])

    return output.getvalue()


def export_income_csv(incomes: list[dict]) -> str:
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')

    writer.writerow([
        'id',
        'amount',
        'category',
        'description',
        'date',
        'source',
        'currency',
    ])

    for income in incomes or []:
        writer.writerow([
            income.get('id', ''),
            income.get('amount', ''),
            _csv_value(income, 'category_name'),
            _csv_value(income, 'description'),
            _csv_value(income, 'date'),
            _csv_value(income, 'source'),
            _csv_value(income, 'currency'),
        ])

    return output.getvalue()


def export_budgets_csv(budgets: list[dict]) -> str:
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')

    writer.writerow([
        'id',
        'category',
        'amount',
        'month',
        'year',
        'currency',
        'alert_percentage',
        'spent',
        'remaining',
        'percentage_used',
        'status',
    ])

    for budget in budgets or []:
        writer.writerow([
            budget.get('id', ''),
            _csv_value(budget, 'category_name'),
            budget.get('amount', ''),
            budget.get('month', ''),
            budget.get('year', ''),
            budget.get('currency', ''),
            budget.get('alert_percentage', ''),
            budget.get('spent', ''),
            budget.get('remaining', ''),
            budget.get('percentage_used', ''),
            _csv_value(budget, 'status'),
        ])

    return output.getvalue()


def _normalize_header(value):
    if not isinstance(value, str):
        return ''

    value = unicodedata.normalize('NFKC', value)
    return value.strip().casefold()


def _prepare_csv_reader(file_stream, required_headers, allowed_headers):
    if file_stream is None or not hasattr(file_stream, 'read'):
        raise ValueError('Invalid CSV file.')

    try:
        raw = file_stream.read(MAX_CSV_SIZE + 1)
    except (OSError, ValueError, AttributeError) as exc:
        raise ValueError('Unable to read the CSV file.') from exc

    if isinstance(raw, bytes):
        if len(raw) > MAX_CSV_SIZE:
            raise ValueError('CSV file exceeds maximum allowed size of 5MB.')

        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValueError(
                'Invalid file encoding. Please upload a UTF-8 encoded CSV file.'
            ) from exc
    elif isinstance(raw, str):
        if len(raw.encode('utf-8')) > MAX_CSV_SIZE:
            raise ValueError('CSV file exceeds maximum allowed size of 5MB.')
        text = raw.lstrip('\ufeff')
    else:
        raise ValueError('Invalid CSV file content.')

    if not text.strip():
        raise ValueError('CSV file is empty.')

    stream = io.StringIO(text, newline='')

    try:
        reader = csv.DictReader(stream, strict=True)
    except csv.Error as exc:
        raise ValueError('Invalid CSV structure.') from exc

    if not reader.fieldnames:
        raise ValueError('Could not read CSV headers.')

    normalized_headers = []
    seen = set()

    for header in reader.fieldnames:
        normalized = _normalize_header(header)

        if not normalized:
            raise ValueError('CSV contains an empty header.')

        if normalized in seen:
            raise ValueError(f'Duplicate CSV header: {normalized}')

        if normalized not in allowed_headers:
            raise ValueError(f'Unexpected CSV header: {normalized}')

        seen.add(normalized)
        normalized_headers.append(normalized)

    missing_headers = sorted(set(required_headers) - seen)
    if missing_headers:
        raise ValueError(
            f"Missing required header: {', '.join(missing_headers)}"
        )

    reader.fieldnames = normalized_headers
    return reader


def _normalize_category_key(value):
    if not isinstance(value, str):
        return ''

    value = unicodedata.normalize('NFKC', value)
    return value.strip().casefold()


def _get_category_map(category_type):
    categories = get_categories(category_type) or []
    category_map = {}

    for category in categories:
        category_name = category.get('name')
        category_id = category.get('id')

        key = _normalize_category_key(category_name)
        if not key or category_id is None:
            continue

        category_map[key] = category_id

    return category_map


def _cell(row, key, default=''):
    value = row.get(key, default)
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _is_blank_row(row):
    if not row:
        return True

    for key, value in row.items():
        if key is None:
            continue
        if isinstance(value, str) and value.strip():
            return False
        if value not in (None, ''):
            return False

    return True


def _row_error(row_number, message):
    text = str(message).strip()
    if not text:
        text = 'Invalid row.'
    return f'Row {row_number}: {text[:MAX_ERROR_MESSAGE_LENGTH]}'


def _format_service_errors(result):
    if isinstance(result, (list, tuple)):
        messages = [str(item).strip() for item in result if item is not None]
    else:
        messages = [str(result).strip()]

    messages = [item for item in messages if item]
    if not messages:
        return 'Unable to process row.'

    return '; '.join(messages)[:MAX_ERROR_MESSAGE_LENGTH]


def _process_import_rows(reader, kind):
    if kind == 'expense':
        category_map = _get_category_map('expense')
        process_row = add_expense
    else:
        category_map = _get_category_map('income')
        process_row = add_income

    success_count = 0
    fail_count = 0
    error_messages = []
    processed_rows = 0
    csv_row_number = 1

    while True:
        if processed_rows >= MAX_CSV_ROWS:
            try:
                next(reader)
                fail_count += 1
                error_messages.append(
                    f'Row limit exceeded. Only processing first {MAX_CSV_ROWS} rows.'
                )
            except StopIteration:
                pass
            except csv.Error:
                fail_count += 1
                error_messages.append('CSV parsing error after the maximum row limit.')
            break

        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error:
            fail_count += 1
            error_messages.append(
                f'CSV parsing error near row {csv_row_number + 1}.'
            )
            logger.exception('CSV parsing error during %s import', kind)
            break

        csv_row_number += 1

        if _is_blank_row(row):
            continue

        processed_rows += 1

        if None in row:
            fail_count += 1
            error_messages.append(
                _row_error(csv_row_number, 'Too many columns in this row.')
            )
            continue

        try:
            amount = _cell(row, 'amount')
            category_text = _cell(row, 'category')
            description = _cell(row, 'description')
            date = _cell(row, 'date')
            currency = _cell(row, 'currency', 'PKR').strip() or 'PKR'
            category_key = _normalize_category_key(category_text)

            if not category_key:
                fail_count += 1
                error_messages.append(
                    _row_error(csv_row_number, 'Category is required.')
                )
                continue

            category_id = category_map.get(category_key)
            if category_id is None:
                fail_count += 1
                error_messages.append(
                    _row_error(
                        csv_row_number,
                        f"Category '{category_text.strip()}' not found."
                    )
                )
                continue

            if kind == 'expense':
                payment_method = _cell(row, 'payment_method').strip() or None
                success, result = process_row(
                    amount,
                    category_id,
                    description,
                    date,
                    payment_method,
                    currency,
                )
            else:
                source = _cell(row, 'source')
                success, result = process_row(
                    amount,
                    category_id,
                    description,
                    date,
                    source,
                    currency,
                )

            if success:
                success_count += 1
            else:
                fail_count += 1
                error_messages.append(
                    _row_error(csv_row_number, _format_service_errors(result))
                )

        except (TypeError, ValueError, AttributeError) as exc:
            fail_count += 1
            error_messages.append(
                _row_error(csv_row_number, 'Invalid row data.')
            )
            logger.warning(
                'Invalid %s CSV row %s: %s',
                kind,
                csv_row_number,
                type(exc).__name__,
            )
        except Exception:
            fail_count += 1
            error_messages.append(
                _row_error(
                    csv_row_number,
                    'Unexpected error while processing this row.'
                )
            )
            logger.exception(
                'Unexpected error processing %s CSV row %s',
                kind,
                csv_row_number,
            )

    return success_count, fail_count, error_messages


def import_expenses_csv(file_stream) -> tuple[int, int, list[str]]:
    try:
        reader = _prepare_csv_reader(
            file_stream,
            EXPENSE_REQUIRED_HEADERS,
            EXPENSE_HEADERS,
        )
    except ValueError as exc:
        return 0, 1, [str(exc)]
    except Exception:
        logger.exception('Unexpected error preparing expense CSV')
        return 0, 1, ['Unable to process the expense CSV file.']

    return _process_import_rows(reader, 'expense')


def import_income_csv(file_stream) -> tuple[int, int, list[str]]:
    try:
        reader = _prepare_csv_reader(
            file_stream,
            INCOME_REQUIRED_HEADERS,
            INCOME_HEADERS,
        )
    except ValueError as exc:
        return 0, 1, [str(exc)]
    except Exception:
        logger.exception('Unexpected error preparing income CSV')
        return 0, 1, ['Unable to process the income CSV file.']

    return _process_import_rows(reader, 'income')
