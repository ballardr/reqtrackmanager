"""
Module: metrics

Prometheus metric definitions, scraped via the /metrics endpoint
(I-M requirements; solution-architecture.md "Required metrics"). Business
event counters are incremented from the service layer at the point each
event occurs, rather than inferred generically from HTTP traffic, so the
figures reflect real domain events (requirement lifecycle, change request
outcomes, login attempts).

`db_statements_total` is the exception: it is incremented from a SQLAlchemy
engine event (`instrument_engine`), because every database statement, from
any code path, must be counted. Its only label is the statement's operation,
never a table name, id or SQL text, so cardinality stays at five series and
nothing Restricted reaches the unauthenticated `/metrics` output.
"""

from prometheus_client import Counter, Histogram
from sqlalchemy import Delete, Insert, Select, Update, event
from sqlalchemy.engine import Engine

http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status_code"]
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds", "HTTP request duration in seconds", ["method", "path"]
)

requirements_created_total = Counter("requirements_created_total", "Requirements created")
requirements_updated_total = Counter("requirements_updated_total", "Requirement versions created")
requirements_approved_total = Counter("requirements_approved_total", "Requirements approved")
requirements_completed_total = Counter("requirements_completed_total", "Requirements completed")
requirements_archived_total = Counter("requirements_archived_total", "Requirements archived")

change_requests_submitted_total = Counter("change_requests_submitted_total", "Change requests submitted")
change_requests_approved_total = Counter("change_requests_approved_total", "Change requests approved")
change_requests_rejected_total = Counter("change_requests_rejected_total", "Change requests rejected")

login_attempts_total = Counter("login_attempts_total", "Login attempts", ["result"])

DB_OPERATIONS = ("select", "insert", "update", "delete", "other")
db_statements_total = Counter(
    "db_statements_total", "Database statements executed, by operation", ["operation"]
)
# Create every series up front so rate()/increase() see a 0 baseline instead
# of an absent series until the first statement of each kind.
for _operation in DB_OPERATIONS:
    db_statements_total.labels(operation=_operation)


def classify_statement(compiled_statement: object) -> str:
    """Maps a SQLAlchemy statement construct to a `DB_OPERATIONS` value.

    Classifies the construct, not the SQL text, so `WITH ... INSERT` counts
    as an insert and a `SELECT ... FOR UPDATE` as a select.

    Args:
        compiled_statement: The `Compiled.statement` of an executed statement,
            or None when the statement was executed as a raw DBAPI string.

    Returns:
        One of `DB_OPERATIONS`; `"other"` for text/raw SQL, DDL and the like.
    """
    if isinstance(compiled_statement, Select):
        return "select"
    if isinstance(compiled_statement, Insert):
        return "insert"
    if isinstance(compiled_statement, Update):
        return "update"
    if isinstance(compiled_statement, Delete):
        return "delete"
    return "other"


def instrument_engine(engine: Engine) -> None:
    """Counts every statement the engine executes in `db_statements_total`.

    An `executemany` batch counts once. Called once, from `app.database`.

    Args:
        engine: The engine to instrument.
    """
    @event.listens_for(engine, "before_cursor_execute")
    def _count_statement(conn, cursor, statement, parameters, context, executemany):
        compiled = getattr(context, "compiled", None)
        operation = classify_statement(getattr(compiled, "statement", None))
        db_statements_total.labels(operation=operation).inc()
