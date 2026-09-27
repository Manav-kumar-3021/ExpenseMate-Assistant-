import os
import sqlite3

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'database',
    'expensemate.db'
)

SCHEMA_VERSION = 2

VALID_CURRENCIES = ('PKR', 'USD', 'EUR', 'GBP', 'AED', 'SAR')
VALID_PAYMENT_METHODS = (
    'Cash',
    'Credit Card',
    'Debit Card',
    'Bank Transfer',
    'Mobile Wallet',
    'Other'
)

DEFAULT_EXPENSE_CATEGORIES = (
    'Food',
    'Transport',
    'Bills',
    'Shopping',
    'Entertainment',
    'Healthcare',
    'Education',
    'Rent',
    'Travel',
    'Other'
)

DEFAULT_INCOME_CATEGORIES = (
    'Salary',
    'Freelance',
    'Business',
    'Investment',
    'Gift',
    'Other'
)

TABLES = ('categories', 'expenses', 'income', 'budgets')
CHILD_TABLES = ('expenses', 'income', 'budgets')


class DatabaseMigrationError(RuntimeError):
    """Raised when the existing database cannot be migrated safely."""


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,)
    ).fetchone()
    return row is not None


def _table_row_count(conn, table_name):
    row = conn.execute(
        f"SELECT COUNT(*) FROM {table_name}"
    ).fetchone()
    return int(row[0])


def _get_columns(conn, table_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row['name'] for row in rows}


def _normalized_schema_sql(conn, table_name):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,)
    ).fetchone()
    if not row or not row['sql']:
        return ''
    return ''.join(row['sql'].lower().split()).replace('"', '').replace("'", "")


def _schema_is_current(conn):
    """Check the actual schema instead of relying only on PRAGMA user_version."""
    if not all(_table_exists(conn, table) for table in TABLES):
        return False

    required_columns = {
        'categories': {'id', 'name', 'type', 'created_at'},
        'expenses': {
            'id', 'amount', 'category_id', 'description', 'date',
            'payment_method', 'currency', 'created_at'
        },
        'income': {
            'id', 'amount', 'category_id', 'description', 'date',
            'source', 'currency', 'created_at'
        },
        'budgets': {
            'id', 'category_id', 'amount', 'month', 'year',
            'currency', 'alert_percentage', 'created_at'
        }
    }

    for table, columns in required_columns.items():
        if _get_columns(conn, table) != columns:
            return False

    categories_sql = _normalized_schema_sql(conn, 'categories')
    expenses_sql = _normalized_schema_sql(conn, 'expenses')
    income_sql = _normalized_schema_sql(conn, 'income')
    budgets_sql = _normalized_schema_sql(conn, 'budgets')

    required_fragments = {
        'categories': (
            "check(type in ('expense', 'income'))",
            'unique(name collate nocase, type)',
        ),
        'expenses': (
            'check(amount > 0 and amount <= 99999999.99',
            "check(currency in ('pkr','usd','eur','gbp','aed','sar'))",
            'foreign key (category_id) references categories(id) on delete restrict',
            "check(payment_method is null or payment_method in ('cash','credit card','debit card','bank transfer','mobile wallet','other'))",
        ),
        'income': (
            'check(amount > 0 and amount <= 99999999.99',
            "check(currency in ('pkr','usd','eur','gbp','aed','sar'))",
            'foreign key (category_id) references categories(id) on delete restrict',
            "check(source is null or length(source) <= 500)",
        ),
        'budgets': (
            'check(month between 1 and 12)',
            'check(year between 2000 and 2100)',
            "check(currency in ('pkr','usd','eur','gbp','aed','sar'))",
            'check(alert_percentage>=1 and alert_percentage<=100)',
            'unique(category_id, month, year, currency)',
            'foreign key (category_id) references categories(id) on delete restrict',
        )
    }

    schema_sql = {
        'categories': categories_sql,
        'expenses': expenses_sql,
        'income': income_sql,
        'budgets': budgets_sql,
    }

    for table, fragments in required_fragments.items():
        for fragment in fragments:
            compact_fragment = ''.join(fragment.lower().split()).replace('"', '').replace("'", "")
            if compact_fragment not in schema_sql[table]:
                return False

    return True


def _set_schema_version(conn):
    conn.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')


def get_db_connection():
    db_dir = os.path.dirname(DB_PATH)

    try:
        os.makedirs(db_dir, exist_ok=True)
    except OSError as exc:
        raise PermissionError(
            f"Cannot create database directory: {db_dir}"
        ) from exc

    try:
        conn = sqlite3.connect(
            DB_PATH,
            timeout=10,
            isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA busy_timeout = 10000')

        try:
            conn.execute('PRAGMA journal_mode = WAL')
        except sqlite3.OperationalError:
            # WAL may not be available on some filesystems. Normal journaling
            # still provides correct transactional behavior.
            conn.execute('PRAGMA journal_mode = DELETE')

        return conn
    except sqlite3.Error as exc:
        raise sqlite3.OperationalError(
            f"Cannot open database: {exc}"
        ) from exc


def _create_schema(c, suffix=''):
    categories = f'categories{suffix}'
    expenses = f'expenses{suffix}'
    income = f'income{suffix}'
    budgets = f'budgets{suffix}'

    c.execute(f'''
        CREATE TABLE IF NOT EXISTS {categories} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 100) COLLATE NOCASE,
            type TEXT NOT NULL CHECK(type IN ('expense', 'income')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name COLLATE NOCASE, type)
        )
    ''')

    c.execute(f'''
        CREATE TABLE IF NOT EXISTS {expenses} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL CHECK(
                amount > 0 AND
                amount <= 99999999.99 AND
                amount = ROUND(amount, 2)
            ),
            category_id INTEGER NOT NULL,
            description TEXT CHECK(description IS NULL OR length(description) <= 500),
            date DATE NOT NULL CHECK(
                length(date) = 10 AND
                date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND
                date(date) IS NOT NULL AND
                date(date) = date AND
                date BETWEEN '2000-01-01' AND '2100-12-31'
            ),
            payment_method TEXT CHECK(
                payment_method IS NULL OR
                payment_method IN (
                    'Cash',
                    'Credit Card',
                    'Debit Card',
                    'Bank Transfer',
                    'Mobile Wallet',
                    'Other'
                )
            ),
            currency TEXT NOT NULL DEFAULT 'PKR' CHECK(
                currency IN ('PKR', 'USD', 'EUR', 'GBP', 'AED', 'SAR')
            ),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES {categories}(id) ON DELETE RESTRICT
        )
    ''')

    c.execute(f'''
        CREATE TABLE IF NOT EXISTS {income} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL CHECK(
                amount > 0 AND
                amount <= 99999999.99 AND
                amount = ROUND(amount, 2)
            ),
            category_id INTEGER NOT NULL,
            description TEXT CHECK(description IS NULL OR length(description) <= 500),
            date DATE NOT NULL CHECK(
                length(date) = 10 AND
                date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND
                date(date) IS NOT NULL AND
                date(date) = date AND
                date BETWEEN '2000-01-01' AND '2100-12-31'
            ),
            source TEXT CHECK(source IS NULL OR length(source) <= 500),
            currency TEXT NOT NULL DEFAULT 'PKR' CHECK(
                currency IN ('PKR', 'USD', 'EUR', 'GBP', 'AED', 'SAR')
            ),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES {categories}(id) ON DELETE RESTRICT
        )
    ''')

    c.execute(f'''
        CREATE TABLE IF NOT EXISTS {budgets} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            amount REAL NOT NULL CHECK(
                amount > 0 AND
                amount <= 99999999.99 AND
                amount = ROUND(amount, 2)
            ),
            month INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12),
            year INTEGER NOT NULL CHECK(year BETWEEN 2000 AND 2100),
            currency TEXT NOT NULL DEFAULT 'PKR' CHECK(
                currency IN ('PKR', 'USD', 'EUR', 'GBP', 'AED', 'SAR')
            ),
            alert_percentage REAL DEFAULT 80 CHECK(
                alert_percentage >= 1 AND alert_percentage <= 100
            ),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES {categories}(id) ON DELETE RESTRICT,
            UNIQUE(category_id, month, year, currency)
        )
    ''')

    index_suffix = suffix.replace(' ', '_')
    c.execute(
        f'CREATE INDEX IF NOT EXISTS idx_expenses_date{index_suffix} '
        f'ON {expenses}(date)'
    )
    c.execute(
        f'CREATE INDEX IF NOT EXISTS idx_expenses_category{index_suffix} '
        f'ON {expenses}(category_id)'
    )
    c.execute(
        f'CREATE INDEX IF NOT EXISTS idx_expenses_currency{index_suffix} '
        f'ON {expenses}(currency)'
    )
    c.execute(
        f'CREATE INDEX IF NOT EXISTS idx_income_date{index_suffix} '
        f'ON {income}(date)'
    )
    c.execute(
        f'CREATE INDEX IF NOT EXISTS idx_income_category{index_suffix} '
        f'ON {income}(category_id)'
    )
    c.execute(
        f'CREATE INDEX IF NOT EXISTS idx_income_currency{index_suffix} '
        f'ON {income}(currency)'
    )
    c.execute(
        f'CREATE INDEX IF NOT EXISTS idx_budgets_category_period{index_suffix} '
        f'ON {budgets}(category_id, month, year, currency)'
    )


def init_db_schema(c, suffix=''):
    """Create the application schema. Kept public for compatibility with tests."""
    _create_schema(c, suffix)


def _legacy_expr(columns, column_name, default_sql):
    if column_name in columns:
        return column_name
    return default_sql


def _copy_table(conn, source_table, target_table, table_name):
    source_columns = _get_columns(conn, source_table)

    required_by_table = {
        'categories': {'id', 'name', 'type'},
        'expenses': {'id', 'amount', 'category_id', 'date'},
        'income': {'id', 'amount', 'category_id', 'date'},
        'budgets': {'id', 'category_id', 'amount', 'month', 'year'},
    }

    missing = required_by_table[table_name] - source_columns
    if missing:
        raise DatabaseMigrationError(
            f"Cannot migrate {table_name}: missing columns "
            f"{', '.join(sorted(missing))}."
        )

    if table_name == 'categories':
        created_at = _legacy_expr(
            source_columns,
            'created_at',
            'CURRENT_TIMESTAMP'
        )
        sql = f'''
            INSERT INTO {target_table} (id, name, type, created_at)
            SELECT id, name, type, {created_at}
            FROM {source_table}
        '''

    elif table_name == 'expenses':
        description = _legacy_expr(source_columns, 'description', 'NULL')
        payment_method = _legacy_expr(source_columns, 'payment_method', 'NULL')
        currency = _legacy_expr(source_columns, 'currency', "'PKR'")
        created_at = _legacy_expr(
            source_columns,
            'created_at',
            'CURRENT_TIMESTAMP'
        )
        sql = f'''
            INSERT INTO {target_table} (
                id, amount, category_id, description, date,
                payment_method, currency, created_at
            )
            SELECT
                id, amount, category_id, {description}, date,
                {payment_method}, {currency}, {created_at}
            FROM {source_table}
        '''

    elif table_name == 'income':
        description = _legacy_expr(source_columns, 'description', 'NULL')
        source = _legacy_expr(source_columns, 'source', 'NULL')
        currency = _legacy_expr(source_columns, 'currency', "'PKR'")
        created_at = _legacy_expr(
            source_columns,
            'created_at',
            'CURRENT_TIMESTAMP'
        )
        sql = f'''
            INSERT INTO {target_table} (
                id, amount, category_id, description, date,
                source, currency, created_at
            )
            SELECT
                id, amount, category_id, {description}, date,
                {source}, {currency}, {created_at}
            FROM {source_table}
        '''

    elif table_name == 'budgets':
        currency = _legacy_expr(source_columns, 'currency', "'PKR'")
        alert_percentage = _legacy_expr(
            source_columns,
            'alert_percentage',
            '80'
        )
        created_at = _legacy_expr(
            source_columns,
            'created_at',
            'CURRENT_TIMESTAMP'
        )
        sql = f'''
            INSERT INTO {target_table} (
                id, category_id, amount, month, year,
                currency, alert_percentage, created_at
            )
            SELECT
                id, category_id, amount, month, year,
                {currency}, {alert_percentage}, {created_at}
            FROM {source_table}
        '''

    else:
        raise DatabaseMigrationError(f'Unsupported table: {table_name}')

    try:
        conn.execute(sql)
    except sqlite3.IntegrityError as exc:
        raise DatabaseMigrationError(
            f"Cannot migrate {table_name}: existing data violates the new "
            f"database constraints. No data was changed."
        ) from exc
    except sqlite3.Error as exc:
        raise DatabaseMigrationError(
            f"Cannot migrate {table_name}: {exc}"
        ) from exc


def _validate_migrated_tables(conn):
    for table in TABLES:
        violations = conn.execute(
            f'PRAGMA foreign_key_check({table}_new)'
        ).fetchall()
        if violations:
            raise DatabaseMigrationError(
                f"Foreign-key validation failed while migrating {table}. "
                "No data was changed."
            )

    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    if integrity != 'ok':
        raise DatabaseMigrationError(
            f"Database integrity check failed during migration: {integrity}"
        )


def _choose_migration_sources(conn):
    sources = {}

    for table in TABLES:
        current_exists = _table_exists(conn, table)
        old_name = f'{table}_old'
        old_exists = _table_exists(conn, old_name)

        current_count = _table_row_count(conn, table) if current_exists else 0
        old_count = _table_row_count(conn, old_name) if old_exists else 0

        if current_exists and old_exists and current_count > 0 and old_count > 0:
            raise DatabaseMigrationError(
                f"Ambiguous database state: both {table} and {old_name} "
                "contain data. Migration was stopped to prevent data loss."
            )

        if old_exists and old_count > 0:
            sources[table] = old_name
        elif current_exists:
            sources[table] = table
        else:
            sources[table] = None

    return sources


def _cleanup_stale_new_tables(conn):
    stale_tables = [f'{table}_new' for table in TABLES if _table_exists(conn, f'{table}_new')]

    for table in stale_tables:
        if _table_row_count(conn, table) > 0:
            raise DatabaseMigrationError(
                f"Unexpected migration artifact {table} contains data. "
                "Migration was stopped to prevent data loss."
            )

    for table in reversed(stale_tables):
        conn.execute(f'DROP TABLE IF EXISTS {table}')


def _drop_existing_tables(conn):
    # Children must be removed before categories because of foreign keys.
    for table in CHILD_TABLES:
        conn.execute(f'DROP TABLE IF EXISTS {table}')
    conn.execute('DROP TABLE IF EXISTS categories')

    # Remove legacy artifacts only after the new tables have been validated.
    for table in CHILD_TABLES:
        conn.execute(f'DROP TABLE IF EXISTS {table}_old')
    conn.execute('DROP TABLE IF EXISTS categories_old')


def _rename_new_tables(conn):
    for table in TABLES:
        conn.execute(f'ALTER TABLE {table}_new RENAME TO {table}')


def migrate_db():
    conn = get_db_connection()

    try:
        # A fully current schema should not be rebuilt on every application start.
        has_legacy_artifacts = any(
            _table_exists(conn, f'{table}_old') for table in TABLES
        )

        if _schema_is_current(conn) and not has_legacy_artifacts:
            conn.execute('BEGIN IMMEDIATE')
            _set_schema_version(conn)
            conn.commit()
            return

        conn.execute('BEGIN IMMEDIATE')

        _cleanup_stale_new_tables(conn)
        sources = _choose_migration_sources(conn)

        init_db_schema(conn.cursor(), '_new')

        # Parent table first, then children.
        for table in TABLES:
            source = sources.get(table)
            if source is None:
                continue
            _copy_table(conn, source, f'{table}_new', table)

        # Verify row counts before replacing anything.
        for table in TABLES:
            source = sources.get(table)
            if source is None:
                source_count = 0
            else:
                source_count = _table_row_count(conn, source)

            target_count = _table_row_count(conn, f'{table}_new')

            if source_count != target_count:
                raise DatabaseMigrationError(
                    f"Migration row-count check failed for {table}: "
                    f"expected {source_count}, copied {target_count}. "
                    "No data was changed."
                )

        _validate_migrated_tables(conn)

        _drop_existing_tables(conn)
        _rename_new_tables(conn)
        _set_schema_version(conn)
        conn.commit()

    except Exception:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def _insert_default_categories(conn):
    """Seed defaults only for a new/empty category table.

    Existing user-created/deleted categories are not silently recreated on
    every application startup. If the table is completely empty, defaults are
    restored so the application still has usable categories.
    """
    if _table_exists(conn, 'categories') and _table_row_count(conn, 'categories') > 0:
        return

    for name in DEFAULT_EXPENSE_CATEGORIES:
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, type) VALUES (?, 'expense')",
            (name,)
        )

    for name in DEFAULT_INCOME_CATEGORIES:
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, type) VALUES (?, 'income')",
            (name,)
        )


def init_db():
    migrate_db()

    conn = get_db_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        _insert_default_categories(conn)
        _set_schema_version(conn)
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def _insert_sample_if_missing(conn, table, columns, values, match_columns):
    where = ' AND '.join(f'{column} = ?' for column in match_columns)
    params = [values[columns.index(column)] for column in match_columns]

    placeholders = ', '.join('?' for _ in columns)
    column_sql = ', '.join(columns)

    conn.execute(
        f'''
            INSERT INTO {table} ({column_sql})
            SELECT {placeholders}
            WHERE NOT EXISTS (
                SELECT 1 FROM {table} WHERE {where}
            )
        ''',
        list(values) + params
    )


def load_sample_data():
    conn = get_db_connection()

    try:
        conn.execute('BEGIN IMMEDIATE')

        _insert_default_categories(conn)

        exp_cats = {
            row['name']: row['id']
            for row in conn.execute(
                "SELECT id, name FROM categories WHERE type = 'expense'"
            ).fetchall()
        }

        inc_cats = {
            row['name']: row['id']
            for row in conn.execute(
                "SELECT id, name FROM categories WHERE type = 'income'"
            ).fetchall()
        }

        if 'Salary' in inc_cats and 'Freelance' in inc_cats:
            incomes = [
                (150000.0, inc_cats['Salary'], 'January Salary', '2024-01-05', 'Bank Transfer', 'PKR'),
                (150000.0, inc_cats['Salary'], 'February Salary', '2024-02-05', 'Bank Transfer', 'PKR'),
                (50000.0, inc_cats['Freelance'], 'Web Project', '2024-01-20', 'Bank Transfer', 'PKR'),
            ]

            columns = ('amount', 'category_id', 'description', 'date', 'source', 'currency')
            for row in incomes:
                _insert_sample_if_missing(
                    conn,
                    'income',
                    columns,
                    row,
                    ('category_id', 'description', 'date', 'amount', 'currency')
                )

        if all(cat in exp_cats for cat in ('Rent', 'Food', 'Transport', 'Shopping')):
            expenses = [
                (30000.0, exp_cats['Rent'], 'January Rent', '2024-01-01', 'Bank Transfer', 'PKR'),
                (15000.0, exp_cats['Food'], 'Groceries', '2024-01-10', 'Cash', 'PKR'),
                (5000.0, exp_cats['Transport'], 'Fuel', '2024-01-15', 'Credit Card', 'PKR'),
                (25000.0, exp_cats['Shopping'], 'Clothes', '2024-01-25', 'Credit Card', 'PKR'),
                (30000.0, exp_cats['Rent'], 'February Rent', '2024-02-01', 'Bank Transfer', 'PKR'),
                (18000.0, exp_cats['Food'], 'Groceries', '2024-02-10', 'Cash', 'PKR'),
            ]

            columns = (
                'amount', 'category_id', 'description', 'date',
                'payment_method', 'currency'
            )
            for row in expenses:
                _insert_sample_if_missing(
                    conn,
                    'expenses',
                    columns,
                    row,
                    ('category_id', 'description', 'date', 'amount', 'currency')
                )

        if all(cat in exp_cats for cat in ('Food', 'Shopping', 'Transport')):
            budgets = [
                (exp_cats['Food'], 20000.0, 1, 2024, 'PKR', 80.0),
                (exp_cats['Shopping'], 20000.0, 1, 2024, 'PKR', 80.0),
                (exp_cats['Transport'], 6000.0, 1, 2024, 'PKR', 80.0),
            ]

            for row in budgets:
                conn.execute(
                    '''
                    INSERT OR IGNORE INTO budgets (
                        category_id, amount, month, year,
                        currency, alert_percentage
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    row
                )

        conn.commit()

    except Exception:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def reset_database():
    conn = get_db_connection()

    try:
        conn.execute('BEGIN IMMEDIATE')

        # Remove active and migration-artifact tables safely.
        for table in CHILD_TABLES:
            conn.execute(f'DROP TABLE IF EXISTS {table}')
            conn.execute(f'DROP TABLE IF EXISTS {table}_old')
            conn.execute(f'DROP TABLE IF EXISTS {table}_new')

        conn.execute('DROP TABLE IF EXISTS categories')
        conn.execute('DROP TABLE IF EXISTS categories_old')
        conn.execute('DROP TABLE IF EXISTS categories_new')

        init_db_schema(conn.cursor())
        _insert_default_categories(conn)
        _set_schema_version(conn)
        conn.commit()

    except Exception:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()
