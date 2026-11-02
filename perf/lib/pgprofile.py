"""
Module: perf.lib.pgprofile

PostgreSQL profiling for the performance runner: which statements cost the most, how many connections the backend
really holds, whether memory settings are adequate, and what the planner does with the worst statements.

Responsibilities:
- Hold the SQL the runner sends to the perf stack's database (read-only statistics queries plus
  `EXPLAIN (GENERIC_PLAN)`, which plans a parameterised statement without running it).
- Turn the JSON those queries return into the rows of `pgstat.csv`, `pgdb.csv` and `plans.csv`.
- Poll connection counts on a thread while a scenario runs, so the peak is measured and not the idle pool.

Design decisions:
- Only DML statements (`select`, `with`, `insert`, `update`, `delete`) are kept. `pg_stat_statements` replaces the
  constants of those with `$n`, but a utility statement (`SET`, `CREATE ROLE ... PASSWORD`) keeps its literals, and
  the results are committed to a public repository. Nothing from `pg_stat_activity` except counts is read.
- Plans come from `EXPLAIN (GENERIC_PLAN)`: it needs no parameter values (a stored statement has none), executes
  nothing, and is therefore safe. It shows the planner's choice and estimates, not actual times; actual cost per
  statement is in `pgstat.csv` (calls, total and mean time, blocks read). A statement whose parameter types cannot
  be inferred is skipped and counted.
- Query text is whitespace-collapsed and cut to `QUERY_LIMIT` characters in the bundle; the full text is only used
  to ask for a plan.

Dependencies: standard library only (Python 3.9+); the SQL runs inside the stack's database container.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Callable, Optional

#: Characters of a statement kept in `pgstat.csv`.
QUERY_LIMIT = 400
#: Statements of each scenario kept (by total time) and how many of those are planned.
TOP_STATEMENTS = 15
PLANNED_STATEMENTS = 5
#: Settings whose values decide whether the database is sized for its working set.
SETTINGS = ("max_connections", "shared_buffers", "work_mem", "effective_cache_size", "maintenance_work_mem")
#: Connections PostgreSQL keeps back for superusers; application clients cannot use them.
RESERVED_CONNECTIONS = 3

SETUP_SQL = "create extension if not exists pg_stat_statements; analyze;"
RESET_SQL = "select pg_stat_statements_reset();"

TOP_STATEMENTS_SQL = f"""
select coalesce(json_agg(t), '[]'::json) from (
  select calls, round(total_exec_time::numeric, 1) as total_ms, round(mean_exec_time::numeric, 3) as mean_ms,
         rows as row_count, shared_blks_read as read_blocks, temp_blks_written as temp_blocks,
         regexp_replace(query, '\\s+', ' ', 'g') as query
  from pg_stat_statements
  where dbid = (select oid from pg_database where datname = current_database())
    and query ~* '^\\s*(select|with|insert|update|delete)\\M'
    and query !~* 'pg_stat_|pg_catalog|information_schema'
  order by total_exec_time desc limit {TOP_STATEMENTS}
) t;
"""

DATABASE_STATS_SQL = """
select coalesce(row_to_json(t), '{}'::json) from (
  select blks_hit, blks_read, temp_files, temp_bytes, deadlocks from pg_stat_database where datname = current_database()
) t;
"""

CONNECTIONS_SQL = """
select count(*) || ' ' || count(*) filter (where state like 'idle in transaction%') from pg_stat_activity
where datname = current_database() and backend_type = 'client backend' and pid <> pg_backend_pid();
"""

SETTINGS_SQL = (
    "select json_object_agg(name, current_setting(name)) from (values "
    + ", ".join(f"('{name}')" for name in SETTINGS)
    + ") as s(name);"
)

_SCAN_NODES = ("Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan", "Bitmap Index Scan", "Tid Scan", "CTE Scan")
_DML = re.compile(r"^\s*(select|with|insert|update|delete)\b", re.IGNORECASE)


_CAST = re.compile(r"::\s*[A-Za-z_][A-Za-z0-9_]*(?:\(\s*\d+\s*(?:,\s*\d+\s*)?\))?(?:\[\])*")


def collapse(text: str, limit: int = QUERY_LIMIT) -> str:
    """Statement text with whitespace collapsed, `::type` casts removed, cut to `limit` characters (ellipsis = cut).

    The casts go because `$1::uuid` reads as an IPv6 address to the anonymisation check, and they say nothing the
    column does not already.
    """
    flat = " ".join(_CAST.sub("", text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def parse_json(text: str) -> Optional[object]:
    """The JSON a statistics query printed, or None when the output is empty or not JSON."""
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def statement_rows(tier: str, scenario: str, statements: list) -> list:
    """`pgstat.csv` rows from the top-statements JSON; a non-DML statement is dropped.

    Args:
        tier / scenario: What ran.
        statements: The list `TOP_STATEMENTS_SQL` returned, most expensive first.

    Returns:
        Dicts keyed by `scrub.PGSTAT_COLUMNS`.
    """
    return [
        {
            "tier": tier, "scenario": scenario, "calls": item["calls"], "total_ms": item["total_ms"], "mean_ms": item["mean_ms"],
            "rows": item["row_count"], "read_blocks": item["read_blocks"], "temp_blocks": item["temp_blocks"], "query": collapse(item["query"]),
        }
        for item in statements
        if _DML.match(item.get("query", ""))
    ]


def database_row(tier: str, scenario: str, before: dict, after: dict, connections_peak: int, idle_in_transaction_peak: int) -> dict:
    """The `pgdb.csv` row for one scenario: what the database did while it ran.

    Args:
        before / after: `DATABASE_STATS_SQL` readings at the start and end of the scenario.
        connections_peak / idle_in_transaction_peak: The highest polled client connection counts.

    Returns:
        Dict keyed by `scrub.PGDB_COLUMNS`. `cache_hit_percent` is blank when no block was read or hit.
    """
    hit = after.get("blks_hit", 0) - before.get("blks_hit", 0)
    read = after.get("blks_read", 0) - before.get("blks_read", 0)
    return {
        "tier": tier, "scenario": scenario, "connections_peak": connections_peak, "idle_in_transaction_peak": idle_in_transaction_peak,
        "cache_hit_percent": round(100.0 * hit / (hit + read), 2) if hit + read > 0 else "",
        "temp_files": after.get("temp_files", 0) - before.get("temp_files", 0),
        "temp_mib": round((after.get("temp_bytes", 0) - before.get("temp_bytes", 0)) / 2**20, 1),
        "deadlocks": after.get("deadlocks", 0) - before.get("deadlocks", 0),
    }


def explain_sql(query: str) -> str:
    """The statement that plans `query` without running it, or "" when it is not safe to plan.

    Only one DML statement is planned (no `;` inside, so it cannot smuggle a second statement, and no backslash,
    which `psql` would read as a meta-command), and only without `ANALYZE`, so nothing executes.
    """
    flat = query.strip().rstrip(";")
    if not _DML.match(flat) or ";" in flat or "\\" in flat:
        return ""
    return f"EXPLAIN (GENERIC_PLAN, FORMAT JSON) {flat};"


def plan_rows(tier: str, scenario: str, rank: int, plan_json: object) -> list:
    """`plans.csv` rows from an `EXPLAIN (FORMAT JSON)` document: one per scan node.

    Args:
        tier / scenario: What ran.
        rank: The statement's position by total time within the scenario (1 = most expensive).
        plan_json: The parsed EXPLAIN output (a one-element list holding `Plan`).

    Returns:
        Dicts keyed by `scrub.PLAN_COLUMNS`; empty for a document of another shape. Filter text is not kept
        (it can carry a literal).
    """
    if not isinstance(plan_json, list) or not plan_json or "Plan" not in plan_json[0]:
        return []
    root = plan_json[0]["Plan"]
    rows: list = []

    def walk(node: dict) -> None:
        if node.get("Node Type") in _SCAN_NODES:
            rows.append({
                "tier": tier, "scenario": scenario, "rank": rank, "node": node["Node Type"], "relation": node.get("Relation Name", ""),
                "index": node.get("Index Name", ""), "filtered": "yes" if ("Filter" in node or "Recheck Cond" in node) else "no",
                "est_rows": int(node.get("Plan Rows", 0)), "plan_cost": round(float(root.get("Total Cost", 0)), 1),
            })
        for child in node.get("Plans", []):
            walk(child)

    walk(root)
    return rows


def connection_ceiling(workers: int, pool_size: int, max_overflow: int, dedicated: int = 2, replicas: int = 1) -> int:
    """The most database connections the backend can hold: `replicas x workers x (pool + overflow + dedicated)`.

    The two dedicated connections per worker are the `LISTEN` listener and the leadership lock, which are taken
    outside the pool.
    """
    return replicas * workers * (pool_size + max_overflow + dedicated)


class ConnectionPoller:
    """Polls client connection counts on a thread and keeps the highest.

    Args:
        read: Returns `(total, idle_in_transaction)` or None when the database cannot be read.
        interval: Seconds between readings.
    """

    def __init__(self, read: Callable[[], Optional[tuple]], interval: float = 2.0) -> None:
        self._read = read
        self._interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.peak = 0
        self.idle_in_transaction_peak = 0
        self.readings = 0

    def sample(self) -> None:
        """Takes one reading and folds it into the peaks."""
        value = self._read()
        if value is None:
            return
        self.readings += 1
        self.peak = max(self.peak, value[0])
        self.idle_in_transaction_peak = max(self.idle_in_transaction_peak, value[1])

    def _run(self) -> None:
        while not self._stop.is_set():
            self.sample()
            self._stop.wait(self._interval)

    def start(self) -> None:
        """Starts polling (a first reading is taken immediately)."""
        self._thread = threading.Thread(target=self._run, name="pg-connection-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stops polling after one last reading and waits for the thread."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=30)
        self.sample()


def parse_connections(text: str) -> Optional[tuple]:
    """`(total, idle_in_transaction)` from `CONNECTIONS_SQL` output, or None when it is not two integers."""
    parts = text.split()
    if len(parts) == 2 and all(part.isdigit() for part in parts):
        return int(parts[0]), int(parts[1])
    return None
