"""
Module: profiling

Developer profiling of a running backend: how many database statements each route runs per request, and which
Python lines are still growing after warm-up. Only active when `PROFILE_MODE=true`; the production Compose file
never sets it.

Responsibilities:
- Count statements and database time per request (`RequestRecord`, filled by SQLAlchemy engine events) and
  aggregate them per route template (`RouteStats`), keeping the statement a single request repeated most, which is
  what an N+1 looks like.
- Write each worker's totals to `PROFILE_OUTPUT_DIR/query_stats_<pid>.json` on a timer, and, with
  `PROFILE_TRACEMALLOC`, the lines whose allocations grew since a post-warm-up baseline to
  `tracemalloc_<pid>.json`.

Design decisions:
- No endpoint, no metric and no log line carries any of this: the output is files in a directory the operator
  mounts, read with `scripts/profile_tools.py`. That keeps a new unauthenticated surface (and new `/metrics`
  label cardinality) out of the product.
- Routes are keyed by their template (`GET /api/v1/projects/{project_id}`), never the resolved path. A statement is
  kept as its parameterised text (placeholders, no bound values) truncated to `STATEMENT_CHARS`, so no record
  content, id or credential reaches the output. Allocation lines are written as paths relative to `/app` or
  `site-packages`.
- Statements run while a streamed response body is still being produced are not counted: the request is
  aggregated when the response starts.
- Python sees one statement per `execute`; an `executemany` batch counts once, as in `db_statements_total`.

External dependencies: SQLAlchemy, Starlette (the request type).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
import tracemalloc
from collections import Counter
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

STATEMENT_CHARS = 300
"""Longest parameterised statement kept per route."""

FLUSH_INTERVAL_SECONDS = 2.0
"""How often a worker writes its query totals."""

TRACEMALLOC_INTERVAL_SECONDS = 30.0
"""How often a worker compares its allocations with the baseline (a comparison walks every tracked block)."""

TRACEMALLOC_FRAMES = 10
TRACEMALLOC_TOP = 25
UNMATCHED = "unmatched"
EXCLUDED_ROUTES = ("/health", "/metrics")
"""Probes and scrapes are not product traffic."""


@dataclass
class RequestRecord:
    """Database activity of one request.

    Attributes:
        queries: Statements executed.
        seconds: Time spent inside the database driver.
        statements: Executions of each parameterised statement, to find the one a request repeats.
    """

    queries: int = 0
    seconds: float = 0.0
    statements: Counter = field(default_factory=Counter)

    def add(self, statement: str, seconds: float) -> None:
        """Records one executed statement.

        Args:
            statement: The parameterised SQL text (placeholders, never bound values).
            seconds: Time the driver took.
        """
        self.queries += 1
        self.seconds += seconds
        self.statements[" ".join(statement.split())[:STATEMENT_CHARS]] += 1


@dataclass
class RouteStats:
    """Totals for one route template.

    Attributes:
        requests: Requests seen.
        queries: Statements executed across them.
        db_seconds: Driver time across them.
        max_queries: The most statements one request ran.
        repeat_statement: The statement one request repeated most often (an N+1 suspect).
        repeat_count: How many times that request ran it.
    """

    requests: int = 0
    queries: int = 0
    db_seconds: float = 0.0
    max_queries: int = 0
    repeat_statement: str = ""
    repeat_count: int = 0

    def add(self, record: RequestRecord) -> None:
        """Folds one finished request into the totals."""
        self.requests += 1
        self.queries += record.queries
        self.db_seconds += record.seconds
        self.max_queries = max(self.max_queries, record.queries)
        if record.statements:
            statement, count = record.statements.most_common(1)[0]
            if count > self.repeat_count:
                self.repeat_statement, self.repeat_count = statement, count

    def as_dict(self) -> dict:
        """The JSON form written to the output directory (milliseconds, rounded)."""
        return {
            "requests": self.requests,
            "queries": self.queries,
            "db_ms": round(self.db_seconds * 1000, 3),
            "max_queries": self.max_queries,
            "repeat_statement": self.repeat_statement,
            "repeat_count": self.repeat_count,
        }


_CURRENT: ContextVar[RequestRecord | None] = ContextVar("profile_request_record", default=None)
_ROUTES: dict[str, RouteStats] = {}


def route_key(request: Request) -> str | None:
    """The key a request is aggregated under, or None when it is not product traffic.

    Args:
        request: The finished request (its route is set by routing).

    Returns:
        `"<METHOD> <route template>"`, `"<METHOD> unmatched"` when no route matched, or None for probes.
    """
    route = request.scope.get("route")
    path = route.path if route else UNMATCHED
    if path in EXCLUDED_ROUTES:
        return None
    return f"{request.method} {path}"


def instrument_engine(engine: Engine) -> None:
    """Counts and times every statement the engine runs on behalf of a request in profile mode.

    Args:
        engine: The engine to instrument. Called once, from `app.database`, only when profile mode is on.
    """

    @event.listens_for(engine, "before_cursor_execute")
    def _start(conn, cursor, statement, parameters, context, executemany):
        if _CURRENT.get() is not None:
            conn.info.setdefault("profile_started", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _finish(conn, cursor, statement, parameters, context, executemany):
        record = _CURRENT.get()
        started = conn.info.get("profile_started")
        if record is not None and started:
            record.add(statement, time.perf_counter() - started.pop())


async def profile_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Attributes the request's database statements to its route (registered only in profile mode).

    Args:
        request: The incoming request.
        call_next: The rest of the application.

    Returns:
        The application's response, unchanged.
    """
    record = RequestRecord()
    token = _CURRENT.set(record)
    try:
        response = await call_next(request)
    finally:
        _CURRENT.reset(token)
    key = route_key(request)
    if key is not None:
        _ROUTES.setdefault(key, RouteStats()).add(record)
    return response


def routes_snapshot() -> dict:
    """The totals so far, as `{route key: RouteStats.as_dict()}`."""
    return {key: stats.as_dict() for key, stats in sorted(_ROUTES.items())}


def reset() -> None:
    """Forgets all totals (tests)."""
    _ROUTES.clear()


def _write_json(path: Path, document: dict) -> None:
    """Writes `document` atomically, so a reader never sees half a file."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, sort_keys=True))
    os.replace(temporary, path)


def write_query_stats(output_dir: Path) -> Path:
    """Writes this worker's totals to `query_stats_<pid>.json`.

    Args:
        output_dir: The profile output directory (created if missing).

    Returns:
        The file written.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"query_stats_{os.getpid()}.json"
    _write_json(path, {"pid": os.getpid(), "routes": routes_snapshot()})
    return path


def relative_location(filename: str) -> str:
    """Shortens a source path so no checkout, user or image layout detail is written.

    Args:
        filename: An absolute path from a traceback.

    Returns:
        The part after `site-packages/` or `/app/`, else the file's base name.
    """
    for marker in ("/site-packages/", "/app/"):
        if marker in filename:
            return filename.split(marker, 1)[1]
    return os.path.basename(filename)


def allocation_growth(baseline: tracemalloc.Snapshot, current: tracemalloc.Snapshot, top: int = TRACEMALLOC_TOP) -> list:
    """The source lines whose live allocations grew most since the baseline.

    Args:
        baseline: The snapshot taken after warm-up.
        current: A snapshot now.
        top: How many lines to return.

    Returns:
        `[{"location", "size_diff_kib", "size_kib", "count_diff"}]`, largest growth first, growth only.
    """
    rows = []
    for stat in current.compare_to(baseline, "lineno")[: top * 3]:
        if stat.size_diff <= 0:
            continue
        frame = stat.traceback[0]
        rows.append(
            {
                "location": f"{relative_location(frame.filename)}:{frame.lineno}",
                "size_diff_kib": round(stat.size_diff / 1024, 1),
                "size_kib": round(stat.size / 1024, 1),
                "count_diff": stat.count_diff,
            }
        )
    return rows[:top]


async def run_profile_loop(
    output_dir: Path, *, tracemalloc_enabled: bool, baseline_seconds: int, interval_seconds: float = FLUSH_INTERVAL_SECONDS
) -> None:
    """Writes this worker's profile files until cancelled. A failed write is logged when it starts failing, then skipped.

    Args:
        output_dir: The profile output directory.
        tracemalloc_enabled: Also track allocations and write growth against a baseline.
        baseline_seconds: Worker age at which the baseline is taken (a `SIGUSR2` takes a new one at any time).
        interval_seconds: Time between query-total writes.
    """
    started = time.monotonic()
    baseline: tracemalloc.Snapshot | None = None
    rebaseline = asyncio.Event()
    last_compare = 0.0
    failing = False
    if tracemalloc_enabled:
        tracemalloc.start(TRACEMALLOC_FRAMES)
        try:
            asyncio.get_running_loop().add_signal_handler(signal.SIGUSR2, rebaseline.set)
        except (NotImplementedError, RuntimeError, ValueError):
            logger.warning("profile mode: cannot install the SIGUSR2 baseline handler on this platform")
    while True:
        try:
            write_query_stats(output_dir)
            if tracemalloc_enabled:
                now = time.monotonic()
                if rebaseline.is_set() or (baseline is None and now - started >= baseline_seconds):
                    rebaseline.clear()
                    baseline = tracemalloc.take_snapshot()
                    last_compare = now
                elif baseline is not None and now - last_compare >= TRACEMALLOC_INTERVAL_SECONDS:
                    last_compare = now
                    current = await asyncio.to_thread(tracemalloc.take_snapshot)
                    growth = await asyncio.to_thread(allocation_growth, baseline, current)
                    _write_json(
                        output_dir / f"tracemalloc_{os.getpid()}.json",
                        {
                            "pid": os.getpid(),
                            "traced_kib": round(tracemalloc.get_traced_memory()[0] / 1024, 1),
                            "growth": growth,
                        },
                    )
            failing = False
        except Exception:  # noqa: BLE001 - profiling must never stop a worker
            if not failing:
                logger.warning("profile mode: could not write the profile files", exc_info=True)
            failing = True
        await asyncio.sleep(interval_seconds)
