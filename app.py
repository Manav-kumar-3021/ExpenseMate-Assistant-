import hmac
import logging
import os
import secrets
from datetime import date
from urllib.parse import urlsplit

from flask import (
    Flask,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from database import DatabaseMigrationError, init_db, load_sample_data, reset_database
from services import (
    add_category,
    add_expense,
    add_income,
    calculate_total_expenses,
    calculate_total_income,
    check_budget_alerts,
    create_budget,
    delete_budget,
    delete_category,
    delete_expense,
    delete_income,
    get_budgets,
    get_categories,
    get_category_by_id,
    get_dashboard_data,
    get_expense_by_id,
    get_expenses,
    get_income_by_id,
    get_incomes,
    update_budget,
    update_category,
    update_expense,
    update_income,
)
from analytics import get_analytics_data
from csv_handler import (
    MAX_CSV_SIZE,
    export_budgets_csv,
    export_expenses_csv,
    export_income_csv,
    import_expenses_csv,
    import_income_csv,
)
from validators import (
    PAYMENT_METHODS,
    VALID_CURRENCIES,
    validate_date,
    validate_date_range,
    validate_id,
    validate_month,
    validate_search,
    validate_year,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MONTHS = [
    (1, "January"),
    (2, "February"),
    (3, "March"),
    (4, "April"),
    (5, "May"),
    (6, "June"),
    (7, "July"),
    (8, "August"),
    (9, "September"),
    (10, "October"),
    (11, "November"),
    (12, "December"),
]

MAX_UPLOAD_REQUEST_SIZE = MAX_CSV_SIZE + (256 * 1024)
MAX_IMPORT_ERRORS_TO_FLASH = 20
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _is_truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_port(value: str | None) -> int:
    try:
        port = int(value or 5000)
    except (TypeError, ValueError):
        return 5000
    return port if 1 <= port <= 65535 else 5000


def _production_mode() -> bool:
    return _is_truthy_env(os.environ.get("FLASK_PRODUCTION")) or (
        os.environ.get("FLASK_ENV", "").strip().lower() == "production"
    )


def _configure_security(app: Flask) -> None:
    production = _production_mode()
    secret_key = os.environ.get("SECRET_KEY")

    if production and not secret_key:
        raise RuntimeError(
            "SECRET_KEY must be set when FLASK_PRODUCTION=true or FLASK_ENV=production."
        )

    app.config.update(
        SECRET_KEY=secret_key or secrets.token_hex(32),
        MAX_CONTENT_LENGTH=MAX_UPLOAD_REQUEST_SIZE,
        MAX_FORM_MEMORY_SIZE=128 * 1024,
        MAX_FORM_PARTS=100,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=production,
        SESSION_COOKIE_NAME="expensemate_session",
    )


def _same_origin(url: str) -> bool:
    try:
        expected = urlsplit(request.host_url)
        actual = urlsplit(url)
    except ValueError:
        return False

    return (
        actual.scheme.lower() == expected.scheme.lower()
        and actual.netloc.lower() == expected.netloc.lower()
    )


def _csrf_token() -> str:
    token = session.get("csrf_token")
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _csrf_valid() -> bool:
    expected = session.get("csrf_token")
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")

    if not isinstance(expected, str) or not isinstance(supplied, str):
        return False

    return hmac.compare_digest(expected, supplied)


def _request_origin_allowed() -> bool:
    """Require CSRF validation for every state-changing browser request."""
    if request.method not in UNSAFE_METHODS:
        return True

    if not _csrf_valid():
        return False

    sec_fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()
    if sec_fetch_site == "cross-site":
        return False

    origin = request.headers.get("Origin")
    if origin and not _same_origin(origin):
        return False

    referer = request.headers.get("Referer")
    if referer and not _same_origin(referer):
        return False

    return True


def _flash_result(result, category="error") -> None:
    if isinstance(result, (list, tuple)):
        messages = result
    else:
        messages = [result]

    for message in messages:
        if message is None:
            continue
        text = str(message).strip()
        if text:
            flash(text[:500], category)


def _validated_optional_id(raw_value):
    if raw_value in (None, ""):
        return None, None
    valid, value, error = validate_id(raw_value)
    return (value, None) if valid else (None, error)


def _validated_optional_month(raw_value):
    if raw_value in (None, ""):
        return None, None
    valid, value, error = validate_month(raw_value)
    return (value, None) if valid else (None, error)


def _validated_optional_year(raw_value):
    if raw_value in (None, ""):
        return None, None
    valid, value, error = validate_year(raw_value)
    return (value, None) if valid else (None, error)


def _validated_optional_date(raw_value):
    if raw_value in (None, ""):
        return None, None
    valid, value = validate_date(raw_value)
    return (value, None) if valid else (None, "Invalid date.")


def _validated_currency(raw_value, default=None, optional=True):
    if raw_value in (None, ""):
        return (default if not optional else None), None

    if not isinstance(raw_value, str):
        return None, "Invalid currency."

    value = raw_value.strip().upper()
    if value not in VALID_CURRENCIES:
        return None, "Invalid currency."
    return value, None


def _validated_filters(include_payment=False, defaults=None):
    defaults = defaults or {}
    errors = []

    raw_search = request.args.get("search", "")
    search = validate_search(raw_search)

    raw_category_id = request.args.get("category_id", "")
    category_id, error = _validated_optional_id(raw_category_id)
    if error:
        errors.append("Invalid category filter.")

    raw_date_from = request.args.get("date_from", "")
    raw_date_to = request.args.get("date_to", "")
    date_from = None
    date_to = None

    if raw_date_from and raw_date_to:
        valid_range, range_error = validate_date_range(raw_date_from, raw_date_to)
        if not valid_range:
            errors.append(range_error)
        else:
            _, date_from = validate_date(raw_date_from)
            _, date_to = validate_date(raw_date_to)
    else:
        date_from, from_error = _validated_optional_date(raw_date_from)
        date_to, to_error = _validated_optional_date(raw_date_to)
        if from_error:
            errors.append("Invalid 'from' date.")
        if to_error:
            errors.append("Invalid 'to' date.")

    raw_month = request.args.get("month", "")
    raw_year = request.args.get("year", "")
    month, month_error = _validated_optional_month(raw_month)
    year, year_error = _validated_optional_year(raw_year)

    if month_error:
        errors.append("Invalid month filter.")
    if year_error:
        errors.append("Invalid year filter.")

    currency, currency_error = _validated_currency(request.args.get("currency", ""))
    if currency_error:
        errors.append(currency_error)

    payment_method = None
    if include_payment:
        raw_payment_method = request.args.get("payment_method", "")
        if raw_payment_method:
            if raw_payment_method not in PAYMENT_METHODS:
                errors.append("Invalid payment method filter.")
            else:
                payment_method = raw_payment_method

    sort_by = request.args.get("sort_by", "date")
    if sort_by not in {"date", "amount", "category_name"}:
        sort_by = "date"

    sort_order = request.args.get("sort_order", "desc").lower()
    if sort_order not in {"asc", "desc"}:
        sort_order = "desc"

    return {
        "search": search,
        "category_id": category_id,
        "date_from": date_from,
        "date_to": date_to,
        "month": month,
        "year": year,
        "currency": currency,
        "payment_method": payment_method,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "errors": errors,
        "raw": {
            "category_id": raw_category_id,
            "date_from": raw_date_from,
            "date_to": raw_date_to,
            "month": raw_month,
            "year": raw_year,
            "currency": request.args.get("currency", ""),
            "payment_method": request.args.get("payment_method", ""),
        },
        "defaults": defaults,
    }


def _database_startup(app: Flask) -> None:
    try:
        init_db()
    except DatabaseMigrationError:
        logger.exception("ExpenseMate database migration failed")
        raise
    except Exception:
        logger.exception("ExpenseMate database initialization failed")
        raise


def create_app() -> Flask:
    app = Flask(__name__)
    _configure_security(app)

    current_year_val = date.today().year
    app.config["APP_YEARS"] = list(range(2020, current_year_val + 3))

    _database_startup(app)

    @app.context_processor
    def inject_security_helpers():
        return {"csrf_token": _csrf_token}

    @app.before_request
    def protect_unsafe_requests():
        if not _request_origin_allowed():
            abort(403)

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "object-src 'none'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "font-src 'self' data:",
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        if _production_mode() and request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response

    @app.errorhandler(400)
    def bad_request_error(error):
        if request.path.startswith("/analytics/data"):
            return jsonify({"error": "Invalid request."}), 400
        return render_template("400.html"), 400

    @app.errorhandler(403)
    def forbidden_error(error):
        if request.path.startswith("/analytics/data"):
            return jsonify({"error": "Request rejected."}), 403
        flash("Your request was rejected for security reasons.", "error")
        return render_template("403.html"), 403

    @app.errorhandler(404)
    def not_found_error(error):
        if request.path.startswith("/analytics/data"):
            return jsonify({"error": "Resource not found."}), 404
        return render_template("404.html"), 404

    @app.errorhandler(413)
    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large_error(error):
        if request.path.startswith("/import/"):
            flash("Uploaded file or request is too large.", "error")
            return redirect(url_for("import_export"))
        return render_template("413.html"), 413

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(
            "Unhandled application error: %s",
            error,
            exc_info=(type(error), error, getattr(error, "__traceback__", None)),
        )
        if request.path.startswith("/analytics/data"):
            return jsonify({"error": "An internal server error occurred."}), 500
        return render_template("500.html"), 500

    @app.route("/")
    def dashboard():
        today = date.today()
        month_raw = request.args.get("month", str(today.month))
        year_raw = request.args.get("year", str(today.year))
        currency_raw = request.args.get("currency", "PKR")

        valid_month, month_value, _ = validate_month(month_raw)
        valid_year, year_value, _ = validate_year(year_raw)
        currency, currency_error = _validated_currency(currency_raw, default="PKR", optional=False)

        if not valid_month:
            month_value = today.month
            flash("Invalid month. Showing the current month.", "error")
        if not valid_year:
            year_value = today.year
            flash("Invalid year. Showing the current year.", "error")
        if currency_error:
            currency = "PKR"
            flash("Invalid currency. Showing PKR.", "error")

        try:
            dashboard_data = get_dashboard_data(month_value, year_value, currency)
            return render_template(
                "dashboard.html",
                month=str(month_value),
                year=str(year_value),
                currency=currency,
                currencies=VALID_CURRENCIES,
                dashboard_data=dashboard_data,
                current_month=today.month,
                current_year=today.year,
                months=MONTHS,
            )
        except Exception:
            logger.exception("Error loading dashboard")
            return render_template("500.html"), 500

    @app.route("/expenses")
    def expenses():
        filters = _validated_filters(include_payment=True)
        if filters["errors"]:
            for error in filters["errors"][:5]:
                flash(error, "error")

        try:
            expenses_list = get_expenses(
                search=filters["search"] or None,
                category_id=filters["category_id"],
                date_from=filters["date_from"],
                date_to=filters["date_to"],
                month=filters["month"],
                year=filters["year"],
                currency=filters["currency"],
                payment_method=filters["payment_method"],
                sort_by=filters["sort_by"],
                sort_order=filters["sort_order"],
            )
            categories = get_categories("expense")
            raw = filters["raw"]
            return render_template(
                "expenses.html",
                expenses=expenses_list,
                categories=categories,
                search=filters["search"],
                category_id=raw["category_id"],
                date_from=raw["date_from"],
                date_to=raw["date_to"],
                month=raw["month"],
                year=raw["year"],
                currency=raw["currency"],
                payment_method=raw["payment_method"],
                sort_by=filters["sort_by"],
                sort_order=filters["sort_order"],
                currencies=VALID_CURRENCIES,
                payment_methods=PAYMENT_METHODS,
            )
        except Exception:
            logger.exception("Error loading expenses")
            flash("An error occurred while processing your request.", "error")
            return redirect(url_for("dashboard"))

    @app.route("/expenses/add", methods=["GET", "POST"])
    def add_expense_page():
        if request.method == "POST":
            amount_str = request.form.get("amount")
            category_id = request.form.get("category_id")
            description = request.form.get("description", "")
            date_val = request.form.get("date")
            payment_method = request.form.get("payment_method")
            currency = request.form.get("currency", "PKR")

            try:
                success, result = add_expense(
                    amount_str,
                    category_id,
                    description,
                    date_val,
                    payment_method,
                    currency,
                )
                if success:
                    flash("Expense added successfully!", "success")
                    return redirect(url_for("expenses"))
                _flash_result(result)
            except Exception:
                logger.exception("Error adding expense")
                flash("An error occurred while processing your request.", "error")

            categories = get_categories("expense")
            return render_template(
                "add_expense.html",
                categories=categories,
                currencies=VALID_CURRENCIES,
                payment_methods=PAYMENT_METHODS,
                today=date_val,
                form_data=request.form,
            )

        categories = get_categories("expense")
        today = date.today().strftime("%Y-%m-%d")
        return render_template(
            "add_expense.html",
            categories=categories,
            currencies=VALID_CURRENCIES,
            payment_methods=PAYMENT_METHODS,
            today=today,
            form_data={},
        )

    @app.route("/expenses/edit/<int:id>", methods=["GET", "POST"])
    def edit_expense_page(id):
        if request.method == "POST":
            amount_str = request.form.get("amount")
            category_id = request.form.get("category_id")
            description = request.form.get("description", "")
            date_val = request.form.get("date")
            payment_method = request.form.get("payment_method")
            currency = request.form.get("currency", "PKR")

            try:
                success, result = update_expense(
                    id,
                    amount_str,
                    category_id,
                    description,
                    date_val,
                    payment_method,
                    currency,
                )
                if success:
                    flash("Expense updated successfully!", "success")
                    return redirect(url_for("expenses"))
                _flash_result(result)
            except Exception:
                logger.exception("Error updating expense")
                flash("An error occurred while processing your request.", "error")

            expense = {
                "id": id,
                "amount": amount_str,
                "category_id": category_id,
                "description": description,
                "date": date_val,
                "payment_method": payment_method,
                "currency": currency,
            }
            categories = get_categories("expense")
            return render_template(
                "edit_expense.html",
                expense=expense,
                categories=categories,
                currencies=VALID_CURRENCIES,
                payment_methods=PAYMENT_METHODS,
            )

        try:
            expense = get_expense_by_id(id)
            if not expense:
                flash("Expense not found.", "error")
                return redirect(url_for("expenses"))
            categories = get_categories("expense")
            return render_template(
                "edit_expense.html",
                expense=expense,
                categories=categories,
                currencies=VALID_CURRENCIES,
                payment_methods=PAYMENT_METHODS,
            )
        except Exception:
            logger.exception("Error loading expense for edit")
            flash("An error occurred while processing your request.", "error")
            return redirect(url_for("expenses"))

    @app.route("/expenses/delete/<int:id>", methods=["POST"])
    def delete_expense_page(id):
        try:
            success, msg = delete_expense(id)
            flash(msg, "success" if success else "error")
        except Exception:
            logger.exception("Error deleting expense")
            flash("An error occurred while processing your request.", "error")
        return redirect(url_for("expenses"))

    @app.route("/income")
    def income_list():
        filters = _validated_filters(include_payment=False)
        if filters["errors"]:
            for error in filters["errors"][:5]:
                flash(error, "error")

        try:
            incomes = get_incomes(
                search=filters["search"] or None,
                category_id=filters["category_id"],
                date_from=filters["date_from"],
                date_to=filters["date_to"],
                month=filters["month"],
                year=filters["year"],
                currency=filters["currency"],
                sort_by=filters["sort_by"],
                sort_order=filters["sort_order"],
            )
            categories = get_categories("income")
            raw = filters["raw"]
            return render_template(
                "income.html",
                incomes=incomes,
                categories=categories,
                search=filters["search"],
                category_id=raw["category_id"],
                date_from=raw["date_from"],
                date_to=raw["date_to"],
                month=raw["month"],
                year=raw["year"],
                currency=raw["currency"],
                sort_by=filters["sort_by"],
                sort_order=filters["sort_order"],
                currencies=VALID_CURRENCIES,
            )
        except Exception:
            logger.exception("Error loading incomes")
            flash("An error occurred while processing your request.", "error")
            return redirect(url_for("dashboard"))

    @app.route("/income/add", methods=["GET", "POST"])
    def add_income_page():
        if request.method == "POST":
            amount_str = request.form.get("amount")
            category_id = request.form.get("category_id")
            description = request.form.get("description", "")
            date_val = request.form.get("date")
            source = request.form.get("source")
            currency = request.form.get("currency", "PKR")

            try:
                success, result = add_income(
                    amount_str,
                    category_id,
                    description,
                    date_val,
                    source,
                    currency,
                )
                if success:
                    flash("Income added successfully!", "success")
                    return redirect(url_for("income_list"))
                _flash_result(result)
            except Exception:
                logger.exception("Error adding income")
                flash("An error occurred while processing your request.", "error")

            categories = get_categories("income")
            return render_template(
                "add_income.html",
                categories=categories,
                currencies=VALID_CURRENCIES,
                today=date_val,
                form_data=request.form,
            )

        categories = get_categories("income")
        today = date.today().strftime("%Y-%m-%d")
        return render_template(
            "add_income.html",
            categories=categories,
            currencies=VALID_CURRENCIES,
            today=today,
            form_data={},
        )

    @app.route("/income/edit/<int:id>", methods=["GET", "POST"])
    def edit_income_page(id):
        if request.method == "POST":
            amount_str = request.form.get("amount")
            category_id = request.form.get("category_id")
            description = request.form.get("description", "")
            date_val = request.form.get("date")
            source = request.form.get("source")
            currency = request.form.get("currency", "PKR")

            try:
                success, result = update_income(
                    id,
                    amount_str,
                    category_id,
                    description,
                    date_val,
                    source,
                    currency,
                )
                if success:
                    flash("Income updated successfully!", "success")
                    return redirect(url_for("income_list"))
                _flash_result(result)
            except Exception:
                logger.exception("Error updating income")
                flash("An error occurred while processing your request.", "error")

            income_record = {
                "id": id,
                "amount": amount_str,
                "category_id": category_id,
                "description": description,
                "date": date_val,
                "source": source,
                "currency": currency,
            }
            categories = get_categories("income")
            return render_template(
                "edit_income.html",
                income_record=income_record,
                categories=categories,
                currencies=VALID_CURRENCIES,
            )

        try:
            income_record = get_income_by_id(id)
            if not income_record:
                flash("Income not found.", "error")
                return redirect(url_for("income_list"))
            categories = get_categories("income")
            return render_template(
                "edit_income.html",
                income_record=income_record,
                categories=categories,
                currencies=VALID_CURRENCIES,
            )
        except Exception:
            logger.exception("Error loading income for edit")
            flash("An error occurred while processing your request.", "error")
            return redirect(url_for("income_list"))

    @app.route("/income/delete/<int:id>", methods=["POST"])
    def delete_income_page(id):
        try:
            success, msg = delete_income(id)
            flash(msg, "success" if success else "error")
        except Exception:
            logger.exception("Error deleting income")
            flash("An error occurred while processing your request.", "error")
        return redirect(url_for("income_list"))

    @app.route("/budgets")
    def budgets_page():
        today = date.today()
        raw_month = request.args.get("month", "")
        raw_year = request.args.get("year", "")
        raw_currency = request.args.get("currency", "")

        month = None
        year = None
        currency = None

        if raw_month:
            valid_month, month, month_error = validate_month(raw_month)
            if not valid_month:
                month = None
                flash("Invalid month filter.", "error")

        if raw_year:
            valid_year, year, year_error = validate_year(raw_year)
            if not valid_year:
                year = None
                flash("Invalid year filter.", "error")

        if raw_currency:
            currency, currency_error = _validated_currency(raw_currency)
            if currency_error:
                currency = None
                flash("Invalid currency filter.", "error")

        try:
            budgets = get_budgets(month, year, currency)
            categories = get_categories("expense")
            return render_template(
                "budgets.html",
                budgets=budgets,
                categories=categories,
                months=MONTHS,
                years=app.config["APP_YEARS"],
                currencies=VALID_CURRENCIES,
                current_month=today.month,
                current_year=today.year,
                filter_month="" if month is None else str(month),
                filter_year="" if year is None else str(year),
                filter_currency="" if currency is None else currency,
            )
        except Exception:
            logger.exception("Error loading budgets")
            flash("An error occurred while processing your request.", "error")
            return redirect(url_for("dashboard"))

    @app.route("/budgets/add", methods=["POST"])
    def add_budget():
        try:
            success, msg = create_budget(
                request.form.get("category_id"),
                request.form.get("amount"),
                request.form.get("month"),
                request.form.get("year"),
                request.form.get("currency", "PKR"),
                request.form.get("alert_percentage", "80"),
            )
            flash(msg, "success" if success else "error")
        except Exception:
            logger.exception("Error adding budget")
            flash("An error occurred while processing your request.", "error")
        return redirect(url_for("budgets_page"))

    @app.route("/budgets/edit/<int:id>", methods=["POST"])
    def edit_budget(id):
        try:
            success, msg = update_budget(
                id,
                request.form.get("category_id"),
                request.form.get("amount"),
                request.form.get("month"),
                request.form.get("year"),
                request.form.get("currency", "PKR"),
                request.form.get("alert_percentage", "80"),
            )
            flash(msg, "success" if success else "error")
        except Exception:
            logger.exception("Error updating budget")
            flash("An error occurred while processing your request.", "error")
        return redirect(url_for("budgets_page"))

    @app.route("/budgets/delete/<int:id>", methods=["POST"])
    def delete_budget_route(id):
        try:
            success, msg = delete_budget(id)
            flash(msg, "success" if success else "error")
        except Exception:
            logger.exception("Error deleting budget")
            flash("An error occurred while processing your request.", "error")
        return redirect(url_for("budgets_page"))

    @app.route("/categories")
    def categories_page():
        try:
            expense_categories = get_categories("expense")
            income_categories = get_categories("income")
            return render_template(
                "categories.html",
                expense_categories=expense_categories,
                income_categories=income_categories,
            )
        except Exception:
            logger.exception("Error loading categories")
            flash("An error occurred while processing your request.", "error")
            return redirect(url_for("dashboard"))

    @app.route("/categories/add", methods=["POST"])
    def add_category_route():
        try:
            success, msg = add_category(
                request.form.get("name"),
                request.form.get("type"),
            )
            flash(msg, "success" if success else "error")
        except Exception:
            logger.exception("Error adding category")
            flash("An error occurred while processing your request.", "error")
        return redirect(url_for("categories_page"))

    @app.route("/categories/edit/<int:id>", methods=["POST"])
    def edit_category_route(id):
        try:
            success, msg = update_category(
                id,
                request.form.get("name"),
                request.form.get("type"),
            )
            flash(msg, "success" if success else "error")
        except Exception:
            logger.exception("Error updating category")
            flash("An error occurred while processing your request.", "error")
        return redirect(url_for("categories_page"))

    @app.route("/categories/delete/<int:id>", methods=["POST"])
    def delete_category_route(id):
        try:
            success, msg = delete_category(id)
            flash(msg, "success" if success else "error")
        except Exception:
            logger.exception("Error deleting category")
            flash("An error occurred while processing your request.", "error")
        return redirect(url_for("categories_page"))

    @app.route("/analytics")
    def analytics_page():
        today = date.today()
        raw_month = request.args.get("month", "")
        raw_year = request.args.get("year", str(today.year))
        raw_currency = request.args.get("currency", "PKR")

        month = None
        if raw_month:
            valid_month, month, month_error = validate_month(raw_month)
            if not valid_month:
                month = None
                flash("Invalid month filter. Showing the full year.", "error")

        valid_year, year, year_error = validate_year(raw_year)
        if not valid_year:
            year = today.year
            flash("Invalid year. Showing the current year.", "error")

        currency, currency_error = _validated_currency(raw_currency, default="PKR", optional=False)
        if currency_error:
            currency = "PKR"
            flash("Invalid currency. Showing PKR.", "error")

        try:
            analytics_data = get_analytics_data(month, year, currency)
            return render_template(
                "analytics.html",
                analytics_data=analytics_data,
                month="" if month is None else str(month),
                year=str(year),
                currency=currency,
                currencies=VALID_CURRENCIES,
                months=MONTHS,
                years=app.config["APP_YEARS"],
                current_year=today.year,
            )
        except Exception:
            logger.exception("Error loading analytics")
            flash("An error occurred while processing your request.", "error")
            return redirect(url_for("dashboard"))

    @app.route("/analytics/data")
    def analytics_data():
        today = date.today()
        raw_month = request.args.get("month", "")
        raw_year = request.args.get("year", str(today.year))
        raw_currency = request.args.get("currency", "PKR")

        month = None
        if raw_month:
            valid_month, month, month_error = validate_month(raw_month)
            if not valid_month:
                return jsonify({"error": "Invalid month."}), 400

        valid_year, year, year_error = validate_year(raw_year)
        if not valid_year:
            return jsonify({"error": "Invalid year."}), 400

        currency, currency_error = _validated_currency(raw_currency, default="PKR", optional=False)
        if currency_error:
            return jsonify({"error": "Invalid currency."}), 400

        try:
            data = get_analytics_data(month, year, currency)
            return jsonify(data)
        except Exception:
            logger.exception("Error fetching analytics data")
            return jsonify({"error": "An error occurred while processing your request."}), 500

    @app.route("/import-export")
    def import_export():
        return render_template("import_export.html")

    def _csv_response(csv_data, filename):
        response = Response(
            csv_data,
            mimetype="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
            },
        )
        return response

    @app.route("/export/expenses")
    def export_expenses():
        try:
            return _csv_response(export_expenses_csv(get_expenses()), "expenses.csv")
        except Exception:
            logger.exception("Error exporting expenses")
            flash("An error occurred while processing your request.", "error")
            return redirect(url_for("import_export"))

    @app.route("/export/income")
    def export_income():
        try:
            return _csv_response(export_income_csv(get_incomes()), "income.csv")
        except Exception:
            logger.exception("Error exporting income")
            flash("An error occurred while processing your request.", "error")
            return redirect(url_for("import_export"))

    @app.route("/export/budgets")
    def export_budgets_csv_route():
        try:
            return _csv_response(export_budgets_csv(get_budgets()), "budgets.csv")
        except Exception:
            logger.exception("Error exporting budgets")
            flash("An error occurred while processing your request.", "error")
            return redirect(url_for("import_export"))

    def _validate_csv_upload(file):
        if file is None:
            return False, "No file part."

        original_name = str(file.filename or "").strip()
        if not original_name:
            return False, "No selected file."

        safe_name = secure_filename(original_name)
        if not safe_name or not safe_name.lower().endswith(".csv"):
            return False, "File must be a CSV."

        try:
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)
        except (OSError, AttributeError):
            return False, "Unable to inspect the uploaded file."

        if size < 1:
            return False, "The uploaded CSV file is empty."
        if size > MAX_CSV_SIZE:
            return False, "File size exceeds the 5MB limit."

        return True, None

    def _flash_import_result(success_count, fail_count, errors, entity_name):
        level = "success" if fail_count == 0 else "warning"
        flash(
            f"Imported {success_count} {entity_name} successfully. "
            f"{fail_count} failed.",
            level,
        )

        safe_errors = list(errors or [])[:MAX_IMPORT_ERRORS_TO_FLASH]
        for error in safe_errors:
            flash(str(error)[:500], "error")

        extra = max(0, len(list(errors or [])) - len(safe_errors))
        if extra:
            flash(f"{extra} additional import errors were not displayed.", "error")

    @app.route("/import/expenses", methods=["POST"])
    def import_expenses():
        try:
            valid, error = _validate_csv_upload(request.files.get("file"))
            if not valid:
                flash(error, "error")
                return redirect(url_for("import_export"))

            success_count, fail_count, errors = import_expenses_csv(request.files["file"])
            _flash_import_result(success_count, fail_count, errors, "expenses")
        except RequestEntityTooLarge:
            flash("Uploaded file or request is too large.", "error")
        except Exception:
            logger.exception("Error importing expenses")
            flash("An error occurred while processing your request.", "error")
        return redirect(url_for("import_export"))

    @app.route("/import/income", methods=["POST"])
    def import_income():
        try:
            valid, error = _validate_csv_upload(request.files.get("file"))
            if not valid:
                flash(error, "error")
                return redirect(url_for("import_export"))

            success_count, fail_count, errors = import_income_csv(request.files["file"])
            _flash_import_result(success_count, fail_count, errors, "income records")
        except RequestEntityTooLarge:
            flash("Uploaded file or request is too large.", "error")
        except Exception:
            logger.exception("Error importing income")
            flash("An error occurred while processing your request.", "error")
        return redirect(url_for("import_export"))

    @app.route("/load-sample-data", methods=["POST"])
    def load_sample():
        try:
            load_sample_data()
            flash("Sample data loaded successfully!", "success")
        except Exception:
            logger.exception("Error loading sample data")
            flash("An error occurred while processing your request.", "error")
        return redirect(url_for("dashboard"))

    @app.route("/reset-database", methods=["POST"])
    def reset_db():
        try:
            reset_database()
            flash("Database reset successfully!", "success")
        except Exception:
            logger.exception("Error resetting database")
            flash("An error occurred while processing your request.", "error")
        return redirect(url_for("dashboard"))

    return app


app = create_app()


if __name__ == "__main__":
    debug = _is_truthy_env(os.environ.get("FLASK_DEBUG")) and not _production_mode()
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = _parse_port(os.environ.get("FLASK_PORT"))
    app.run(host=host, port=port, debug=debug)
