# ExpenseMate — Personal Expense Manager

ExpenseMate is a Flask + SQLite personal finance application for managing expenses, income, budgets, categories, CSV import/export, and financial analytics.

## Features
- Dashboard with monthly financial summary
- Expense management (add, edit, delete, search, filter, sort)
- Income management (add, edit, delete, search, filter, sort)
- Budget management with alerts and spending status
- Category management
- Analytics and charts
- CSV import/export
- Sample-data loading
- Safe database reset and schema migration
- Server-side validation and CSRF protection

## Project Structure
```text
ExpenseMate Assistant/
├── app.py
├── analytics.py
├── csv_handler.py
├── database.py
├── services.py
├── validators.py
├── requirements.txt
├── README.md
├── database/
│   └── expensemate.db
├── static/
│   ├── css/
│   │   └── style.css
│   └── js/
│       ├── analytics.js
│       ├── dashboard.js
│       └── validation.js
├── templates/
└── tests/
```

## Requirements
- Python 3.10+
- Dependencies listed in `requirements.txt`

## Installation
Create a fresh virtual environment:

```bash
python -m venv .venv
```

### Windows PowerShell
```powershell
.\.venv\Scripts\Activate.ps1
```

### macOS/Linux
```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run
From the project root:

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

The SQLite database is stored in `database/expensemate.db`. The application initializes the schema safely and preserves existing records during supported migrations.

## Testing
Run the full test suite:

```bash
pytest -q
```

Run with coverage for project files:

```bash
coverage run -m pytest -q
coverage report --omit=*.venv/*,tests/*
```

## Security Notes
- State-changing requests require a CSRF token.
- Database queries use parameterized SQL.
- Dynamic SQL sort fields are whitelisted.
- Server-side validation is authoritative; browser validation is only for usability.
- CSV imports enforce size, row, field, header, encoding, and structural checks.
- CSV exports protect text cells against common spreadsheet formula injection.
- The Flask development server is intended for local development, not production deployment.
- Set a stable `SECRET_KEY` when running in production.

## CSV Import
Expense imports require at least:

```text
amount,category,date
```

Optional expense columns include `id`, `description`, `payment_method`, and `currency`.

Income imports require at least:

```text
amount,category,date
```

Optional income columns include `id`, `description`, `source`, and `currency`.

Category names are matched case-insensitively. Currency codes are normalized to uppercase by the service layer.
