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

The `worker_*` and `db_pool_*` gauges describe the process that sets them, so
in multi-process mode they use `liveall` (one series per live worker, labelled
with its `pid`). `multiprocess` cannot export the standard process collector,
so `update_worker_gauges` (run on a timer by `app.main`) refreshes them; only
byte and connection counts are exported, never paths or arguments.
"""

import asyncio
import os
import re
import resource
import sys
from pathlib import Path

from prometheus_client import Counter, Gauge, Histogram, multiprocess
from sqlalchemy import Delete, Insert, Select, Update, event
from sqlalchemy.engine import Engine

http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status_code"]
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds", "HTTP request duration in seconds", ["method", "path"]
)

requests_shed_total = Counter(
    "requests_shed_total", "Requests refused with 503 because no request slot freed within the queue timeout"
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

# 1 while the last file-storage write probe succeeded, 0 while it is failing (services/storage_health.py).
# `livemostrecent` so a multi-worker scrape reports the leader's latest probe, not a stale worker's.
storage_write_healthy = Gauge(
    "storage_write_healthy", "1 if the file storage backend accepted a write probe, else 0",
    multiprocess_mode="livemostrecent",
)

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


worker_resident_memory_bytes = Gauge(
    "worker_resident_memory_bytes", "Resident set size of this backend worker process",
    multiprocess_mode="liveall",
)
db_pool_connections = Gauge(
    "db_pool_connections", "Connections in this worker's database pool, by state (checked_out, idle)",
    ["state"], multiprocess_mode="liveall",
)

_STATM = Path("/proc/self/statm")
_PAGE_SIZE = resource.getpagesize()


def read_resident_memory_bytes() -> int:
    """Returns this process's resident set size in bytes.

    Reads `/proc/self/statm` (current RSS) on Linux; elsewhere falls back to the
    peak RSS from `getrusage`, which is bytes on macOS and KiB on other systems.

    Returns:
        The resident set size in bytes.
    """
    try:
        return int(_STATM.read_text().split()[1]) * _PAGE_SIZE
    except (OSError, IndexError, ValueError):
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak if sys.platform == "darwin" else peak * 1024


def update_worker_gauges(engine: Engine) -> None:
    """Refreshes this worker's memory and database-pool gauges.

    Args:
        engine: The engine whose pool is reported. A pool without checkout
            counters (`NullPool`) reports zeros.
    """
    worker_resident_memory_bytes.set(read_resident_memory_bytes())
    pool = engine.pool
    checked_out = pool.checkedout() if hasattr(pool, "checkedout") else 0
    idle = pool.checkedin() if hasattr(pool, "checkedin") else 0
    db_pool_connections.labels(state="checked_out").set(checked_out)
    db_pool_connections.labels(state="idle").set(idle)


WORKER_GAUGE_INTERVAL_SECONDS = 5

_LIVE_GAUGE_FILE = re.compile(r"^gauge_live\w+_(\d+)\.db$")


def purge_dead_worker_gauges(multiproc_dir: str) -> list[int]:
    """Drops the live-gauge files of worker processes that no longer exist.

    `prometheus_client` keeps reporting a `live*` gauge for a pid until
    `mark_process_dead` is called, and uvicorn never calls it, so a restarted
    worker would leave a frozen series behind. Run before each scrape.

    Args:
        multiproc_dir: The `PROMETHEUS_MULTIPROC_DIR` directory.

    Returns:
        The pids whose files were removed.
    """
    removed = []
    for path in Path(multiproc_dir).glob("gauge_live*.db"):
        match = _LIVE_GAUGE_FILE.match(path.name)
        if not match:
            continue
        pid = int(match.group(1))
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            multiprocess.mark_process_dead(pid, multiproc_dir)
            removed.append(pid)
        except PermissionError:
            pass  # exists, owned by someone else
    return removed


async def run_worker_gauge_loop(engine: Engine, interval_seconds: float = WORKER_GAUGE_INTERVAL_SECONDS) -> None:
    """Keeps this worker's gauges fresh until cancelled.

    Every worker runs one (not only the elected leader), because each reports
    its own process. A failed refresh is skipped so it can never stop the worker.

    Args:
        engine: The engine whose pool is reported.
        interval_seconds: Time between refreshes.
    """
    while True:
        try:
            update_worker_gauges(engine)
        except Exception:  # monitoring must never take the worker down
            pass
        await asyncio.sleep(interval_seconds)
