#!/usr/bin/env python3
"""
Module: perf.analyse

Reads results bundles and reports scaling shape, budget breaches, peak memory and memory growth.

Responsibilities:
- Fit latency (p95) against requirements per project across tiers on log-log axes and label each request flat,
  linear or superlinear (`classify`); a request that returns a fixed-size page and is not flat is a finding, and so
  is anything superlinear.
- Judge each request against `budgets.yaml` per tier (`budget_findings`).
- Report peak memory per service by tier and the backend's memory slope after warm-up in the soak (`memory_*`).
- Fit statements per request (`queries.csv`) against requirements per project: a route whose statement count grows
  with the data is an N+1 by definition (`query_scaling`), and report each worker's private memory (`processes.csv`).
- Judge the database: the connection peak and the backend's pool ceiling against `max_connections`, cache hit rate
  and temp files against the memory settings, the costliest statements, and scans of large tables the planner
  does with a filter and no index (`database_findings`, `plan_findings`).

Usage:
    python3 perf/analyse.py perf/results/<host-label>/<date>-<commit> [--json]
    python3 perf/analyse.py --workers <bundle> <bundle> ...     (capacity by worker count; a worker sweep's runs)

Design decisions:
- Pure functions over rows, so the classification is unit-tested; the command line only loads files.
- A tier with fewer than three distinct sizes is "insufficient data", never a guessed slope.
- Needs PyYAML for budgets.yaml (the backend virtualenv has it); the runner itself does not.

Dependencies: PyYAML; standard library otherwise (Python 3.9+).
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

BUDGETS = Path(__file__).resolve().parent / "budgets.yaml"
WARMUP_FRACTION = 0.2


def slope(points: list) -> Optional[float]:
    """Least-squares slope of log(y) on log(x) for `(x, y)` points with positive values; None below three points."""
    usable = [(math.log(x), math.log(y)) for x, y in points if x > 0 and y > 0]
    if len({x for x, _ in usable}) < 3:
        return None
    mean_x = statistics.fmean(x for x, _ in usable)
    mean_y = statistics.fmean(y for _, y in usable)
    denominator = sum((x - mean_x) ** 2 for x, _ in usable)
    return sum((x - mean_x) * (y - mean_y) for x, y in usable) / denominator if denominator else None


def classify(value: Optional[float], flat: float = 0.25, superlinear: float = 1.3) -> str:
    """`flat`, `linear`, `superlinear` or `insufficient data` for a log-log slope."""
    if value is None:
        return "insufficient data"
    return "flat" if value < flat else ("linear" if value <= superlinear else "superlinear")


def is_fixed_size_page(request: str) -> bool:
    """Whether the request returns one page of bounded size, so its cost should not grow with the data."""
    return any(token in request for token in ("(page", "page of", ", page)", "/requirements/{id}", "(create)", "(edit)", "/comments", "/activity"))


def scaling_table(latency: list, sizes: dict, budgets: dict) -> list:
    """One row per (scenario, request, users): p95 by tier, slope, label and any finding.

    Args:
        latency: Rows of `latency.csv` (strings).
        sizes: `{tier: requirements per project}`.
        budgets: The parsed `budgets.yaml`.

    Returns:
        Dicts with `scenario`, `request`, `users`, `p95` (`{tier: ms}`), `slope`, `label`, `finding`.
    """
    grouped: dict = defaultdict(lambda: defaultdict(list))
    for row in latency:
        if row["p95_ms"] in ("", None):
            continue
        grouped[(row["scenario"], row["request"], row["users"])][row["tier"]].append(float(row["p95_ms"]))
    rows = []
    for (scenario, request, users), by_tier in sorted(grouped.items()):
        p95 = {tier: statistics.median(values) for tier, values in by_tier.items()}
        value = slope([(sizes[t], v) for t, v in p95.items() if t in sizes])
        label = classify(value, budgets.get("flat_slope", 0.25), budgets.get("superlinear_slope", 1.3))
        finding = None
        if label == "superlinear":
            finding = "grows faster than the data"
        elif value is not None and is_fixed_size_page(request) and value > budgets.get("fixed_size_page_max_slope", 0.35):
            finding = f"returns a fixed-size page but grows with the data (slope {value:.2f})"
        rows.append({"scenario": scenario, "request": request, "users": users, "p95": p95, "slope": value, "label": label, "finding": finding})
    return rows


def query_scaling(queries: list, sizes: dict, budgets: dict) -> list:
    """One row per (scenario, route): statements per request by tier, slope, label, and a finding when it grows.

    Statement counts are small integers, so the "flat" bound is tighter than for latency (`query_flat_slope`). A
    route that runs more statements per request on a bigger project is repeating a statement per row (an N+1).

    Args:
        queries: Rows of `queries.csv` (strings).
        sizes: `{tier: requirements per project}`.
        budgets: The parsed `budgets.yaml`.

    Returns:
        Dicts with `scenario`, `request`, `per_request` (`{tier: statements}`), `slope`, `label`, `finding`.
    """
    grouped: dict = defaultdict(dict)
    for row in queries:
        grouped[(row["scenario"], row["request"])][row["tier"]] = float(row["queries_per_request"])
    rows = []
    for (scenario, request), by_tier in sorted(grouped.items()):
        value = slope([(sizes[t], v) for t, v in by_tier.items() if t in sizes])
        label = classify(value, budgets.get("query_flat_slope", 0.1), budgets.get("superlinear_slope", 1.3))
        finding = "statements per request grow with the data (N+1 suspect)" if label in ("linear", "superlinear") else None
        rows.append({"scenario": scenario, "request": request, "per_request": by_tier, "slope": value, "label": label, "finding": finding})
    return rows


def worker_memory(processes: list) -> dict:
    """Private and shared memory of the backend's processes, by tier: the evidence for how much each worker costs.

    Args:
        processes: Rows of `processes.csv` (strings).

    Returns:
        `{tier: {"workers", "private_mib_per_worker", "shared_mib_per_worker", "pss_total_mib"}}` from the largest
        reading of each tier (after the heaviest scenario), with means across workers.
    """
    # A reading is one snapshot of every process. The file has no user-level column, so consecutive snapshots of the
    # same scenario and repeat (one per user level) are told apart by a process index appearing a second time.
    by_tier: dict = defaultdict(list)
    current: dict = {}
    for row in processes:
        key = (row["tier"], row["scenario"], row["repeat"])
        process = (row["role"], row["index"])
        if current.get("key") != key or process in current["seen"]:
            current = {"key": key, "seen": set(), "rows": []}
            by_tier[row["tier"]].append(current["rows"])
        current["seen"].add(process)
        current["rows"].append(row)
    result = {}
    for tier, readings in by_tier.items():
        best = max(readings, key=lambda rows: sum(float(r["pss_mib"]) for r in rows))
        serving = [r for r in best if r["role"] in ("worker", "single")]
        if not serving:
            continue
        result[tier] = {
            "workers": len(serving),
            "private_mib_per_worker": round(statistics.fmean(float(r["private_mib"]) for r in serving), 1),
            "shared_mib_per_worker": round(statistics.fmean(float(r["shared_mib"]) for r in serving), 1),
            "pss_total_mib": round(sum(float(r["pss_mib"]) for r in best), 1),
        }
    return result


def top_statements(pgstat: list, per_scenario: int = 3) -> dict:
    """The costliest statements of each `(tier, scenario)`, by total time, from `pgstat.csv` rows.

    Returns:
        `{(tier, scenario): [row, ...]}` with at most `per_scenario` rows each (numbers converted).
    """
    grouped: dict = defaultdict(list)
    for row in pgstat:
        grouped[(row["tier"], row["scenario"])].append({**row, "total_ms": float(row["total_ms"]), "calls": int(row["calls"]), "mean_ms": float(row["mean_ms"])})
    return {key: sorted(rows, key=lambda r: -r["total_ms"])[:per_scenario] for key, rows in sorted(grouped.items())}


def parse_size_mib(text: str) -> Optional[float]:
    """MiB in a PostgreSQL size setting such as `128MB`, `4GB` or `512kB`; None when it is not one."""
    units = {"kb": 1 / 1024, "mb": 1.0, "gb": 1024.0, "tb": 1024.0 * 1024}
    text = str(text).strip().lower()
    for unit, factor in units.items():
        if text.endswith(unit) and text[: -len(unit)].strip().replace(".", "", 1).isdigit():
            return float(text[: -len(unit)]) * factor
    return None


def database_findings(pgdb: list, run: dict, hit_floor: float = 99.0) -> list:
    """Connection, cache and temp-file findings from `pgdb.csv` and the run's recorded settings.

    Args:
        pgdb: Rows of `pgdb.csv` (strings).
        run: `run.json` (`postgres` settings and `db_pool` ceiling, when recorded).
        hit_floor: Buffer cache hit rate (percent) below which a scenario is reported.

    Returns:
        Dicts with `kind` (`connections`, `cache`, `work_mem`, `deadlock`), `where` and `detail`.
    """
    findings = []
    settings = run.get("postgres", {})
    usable = int(settings["max_connections"]) - 3 if str(settings.get("max_connections", "")).isdigit() else None
    ceiling = run.get("db_pool", {}).get("connection_ceiling")
    if usable and ceiling and ceiling > usable:
        findings.append({"kind": "connections", "where": "configuration", "detail": f"the backend can hold {ceiling} connections (workers x (pool + overflow + 2)), more than the {usable} PostgreSQL allows clients"})
    for row in pgdb:
        where = f"{row['tier']}/{row['scenario']}"
        if usable and int(row["connections_peak"]) > 0.8 * usable:
            findings.append({"kind": "connections", "where": where, "detail": f"peak {row['connections_peak']} of {usable} client connections"})
        if row["cache_hit_percent"] not in ("", None) and float(row["cache_hit_percent"]) < hit_floor:
            findings.append({"kind": "cache", "where": where, "detail": f"buffer cache hit rate {row['cache_hit_percent']}% (shared_buffers {settings.get('shared_buffers', '?')})"})
        if int(row["temp_files"]) > 0:
            findings.append({"kind": "work_mem", "where": where, "detail": f"{row['temp_files']} temporary files, {row['temp_mib']} MiB spilled to disk (work_mem {settings.get('work_mem', '?')})"})
        if int(row["deadlocks"]) > 0:
            findings.append({"kind": "deadlock", "where": where, "detail": f"{row['deadlocks']} deadlock(s)"})
    return findings


def plan_findings(plans: list, sizes: dict, min_rows: int = 1000) -> list:
    """Sequential scans the planner chose for a filtered read of a table it expects to be large.

    Args:
        plans: Rows of `plans.csv` (strings).
        sizes: `{tier: requirements per project}`, to order the tiers.
        min_rows: Estimated rows at or above which a filtered `Seq Scan` is reported.

    Returns:
        Dicts with `relation`, `tier`, `scenario`, `rank`, `est_rows`, deduplicated by relation and scenario at the
        largest tier that shows it.
    """
    seen: dict = {}
    for row in plans:
        if row["node"] != "Seq Scan" or row["filtered"] != "yes" or int(row["est_rows"]) < min_rows:
            continue
        key = (row["relation"], row["scenario"])
        candidate = {"relation": row["relation"], "tier": row["tier"], "scenario": row["scenario"], "rank": int(row["rank"]), "est_rows": int(row["est_rows"])}
        if key not in seen or sizes.get(row["tier"], 0) > sizes.get(seen[key]["tier"], 0):
            seen[key] = candidate
    return sorted(seen.values(), key=lambda r: (-r["est_rows"], r["relation"]))


def request_class(request: str, budgets: dict) -> Optional[str]:
    """The budget class of a request name (first matching rule), or None."""
    for rule in budgets.get("rules", []):
        if rule["match"] in request:
            return rule["class"]
    return None


def budget_findings(table: list, budgets: dict) -> list:
    """Requests whose p95 at a tier exceeds the budget for their class.

    Returns:
        Dicts with `request`, `users`, `tier`, `p95_ms`, `budget_ms`, `class`.
    """
    findings = []
    for row in table:
        klass = request_class(row["request"], budgets)
        if klass is None:
            continue
        spec = budgets["classes"][klass]
        for tier, value in row["p95"].items():
            if "tiers" in spec and tier not in spec["tiers"]:
                continue
            if value > spec["p95_ms"]:
                findings.append({"request": row["request"], "users": row["users"], "tier": tier, "p95_ms": value, "budget_ms": spec["p95_ms"], "class": klass})
    return findings


def memory_peaks(samples: list) -> dict:
    """Peak MiB per `(tier, service)` over all rows."""
    peaks: dict = {}
    for row in samples:
        key = (row["tier"], row["service"])
        peaks[key] = max(peaks.get(key, 0.0), float(row["mem_mib"]))
    return peaks


def memory_slope_mib_per_hour(samples: list, tier: str, scenario: str = "soak", service: str = "backend") -> Optional[float]:
    """Backend memory growth after warm-up: least-squares slope (MiB per hour) of the rows after the first 20%.

    Returns None with fewer than ten points after warm-up.
    """
    points = sorted((float(r["t_seconds"]), float(r["mem_mib"])) for r in samples if r["tier"] == tier and r["scenario"] == scenario and r["service"] == service)
    if len(points) < 10:
        return None
    points = points[int(len(points) * WARMUP_FRACTION):]
    mean_t = statistics.fmean(t for t, _ in points)
    mean_m = statistics.fmean(m for _, m in points)
    denominator = sum((t - mean_t) ** 2 for t, _ in points)
    return sum((t - mean_t) * (m - mean_m) for t, m in points) / denominator * 3600 if denominator else None


def read_csv(path: Path) -> list:
    """Rows of a CSV file as dicts (empty when the file is missing)."""
    if not path.is_file():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def capacity_curve(latency: list, budgets: dict, scenario: str = "capacity") -> dict:
    """The capacity scenario's levels, and the largest level the stack served within the budget.

    Args:
        latency: Rows of `latency.csv` (strings).
        budgets: The parsed `budgets.yaml` (its `capacity` section).
        scenario: `capacity`, or `capacity_mixed` for the run with the other record types and links in the mix.

    Returns:
        `{"levels": [...], "usable_users": int | None, "first_unusable": dict | None}`; each level has `tier`, `users`,
        `offered_rps`, `delivered_rps`, `delivered`, `failure_rate`, `p95_ms` (weighted by request count), `usable` and
        `people_low` / `people_high` (active people the delivered rate stands for, at one request every busy / relaxed
        interval of the budgets).
        Empty `levels` when the bundle has no capacity run. Levels are judged in order and the first unusable one ends
        the usable range, so a lucky later level does not count.
    """
    limits = budgets.get("capacity", {})
    rate = float(limits.get("requests_per_user_per_second", 1.0))
    interval = limits.get("person_request_interval_seconds", {"busy": 5, "relaxed": 10})
    grouped: dict = defaultdict(list)
    for row in latency:
        if row["scenario"] == scenario:
            grouped[(row["tier"], int(row["users"]))].append(row)
    levels = []
    for (tier, users), rows in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        count = sum(int(r["count"] or 0) for r in rows)
        failures = sum(int(r["failures"] or 0) for r in rows)
        delivered_rps = sum(float(r["rps"] or 0) for r in rows)
        weighted = sum(float(r["p95_ms"] or 0) * int(r["count"] or 0) for r in rows) / count if count else 0.0
        offered = users * rate
        failure_rate = failures / count if count else 1.0
        delivered = delivered_rps / offered if offered else 0.0
        usable = (delivered >= float(limits.get("delivered", 0.9)) and failure_rate <= float(limits.get("failure_rate", 0.01))
                  and weighted <= float(limits.get("p95_ms", 1000)))
        levels.append({"tier": tier, "users": users, "offered_rps": offered, "delivered_rps": round(delivered_rps, 1),
                       "delivered": round(delivered, 3), "failure_rate": round(failure_rate, 4), "p95_ms": round(weighted), "usable": usable,
                       "people_low": round(delivered_rps * float(interval["busy"])), "people_high": round(delivered_rps * float(interval["relaxed"]))})
    usable_users, first_unusable = None, None
    for level in levels:
        if not level["usable"]:
            first_unusable = level
            break
        usable_users = level["users"]
    return {"levels": levels, "usable_users": usable_users, "first_unusable": first_unusable}


def analyse(directory: Path, budgets: dict) -> dict:
    """The full analysis of one bundle directory."""
    datasets = json.loads((directory / "dataset.json").read_text())["datasets"]
    sizes = {d["tier"]: d["spec"]["requirements_per_project"] for d in datasets}
    latency = read_csv(directory / "latency.csv")
    samples = read_csv(directory / "samples.csv")
    table = scaling_table([r for r in latency if not r["scenario"].startswith("capacity")], sizes, budgets)
    peaks = memory_peaks(samples)
    queries = query_scaling(read_csv(directory / "queries.csv"), sizes, budgets)
    run_file = directory / "run.json"
    run = json.loads(run_file.read_text()) if run_file.is_file() else {}
    pgdb = database_findings(read_csv(directory / "pgdb.csv"), run)
    plans = plan_findings(read_csv(directory / "plans.csv"), sizes)
    return {
        "postgres": run.get("postgres", {}),
        "db_pool": run.get("db_pool", {}),
        "top_statements": {f"{tier}/{scenario}": rows for (tier, scenario), rows in top_statements(read_csv(directory / "pgstat.csv")).items()},
        "database_findings": pgdb,
        "plan_findings": plans,
        "tiers": sizes,
        "scaling": table,
        "scaling_findings": [r for r in table if r["finding"]],
        "query_scaling": queries,
        "query_findings": [r for r in queries if r["finding"]],
        "worker_memory": worker_memory(read_csv(directory / "processes.csv")),
        "budget_findings": budget_findings(table, budgets),
        "peak_memory_mib": {f"{tier}/{service}": value for (tier, service), value in sorted(peaks.items())},
        "soak_backend_mib_per_hour": {tier: memory_slope_mib_per_hour(samples, tier) for tier in sizes},
        "failures": [r for r in latency if int(r["failures"] or 0) > 0 and not r["scenario"].startswith("capacity")],
        "capacity": capacity_curve(latency, budgets),
        "capacity_mixed": capacity_curve(latency, budgets, "capacity_mixed"),
    }


def worker_scaling(directories: list, budgets: dict) -> list:
    """How the capacity result changes with the backend worker count, one row per bundle.

    Args:
        directories: Bundle directories that each ran the `capacity` scenario (a worker sweep's runs).
        budgets: The parsed `budgets.yaml`.

    Returns:
        Rows sorted by workers: `workers`, `usable_users`, `delivered_rps` (at the usable level), `rps_per_worker`,
        `peak_rps` and `peak_rps_per_worker` (the most any level delivered, which is where the stack saturates),
        `next_level` (the first level beyond the budget, or None) and `host_shared`.
    """
    rows = []
    for directory in directories:
        run = json.loads((Path(directory) / "run.json").read_text())
        curve = capacity_curve(read_csv(Path(directory) / "latency.csv"), budgets)
        usable = next((lvl for lvl in curve["levels"] if lvl["users"] == curve["usable_users"]), None)
        workers = int(run.get("workers") or 0)
        delivered = usable["delivered_rps"] if usable else 0.0
        peak = max((lvl["delivered_rps"] for lvl in curve["levels"]), default=0.0)
        rows.append({
            "workers": workers, "usable_users": curve["usable_users"], "delivered_rps": delivered,
            "rps_per_worker": round(delivered / workers, 1) if workers else None,
            "peak_rps": peak, "peak_rps_per_worker": round(peak / workers, 1) if workers else None,
            "people_low": usable["people_low"] if usable else 0, "people_high": usable["people_high"] if usable else 0,
            "next_level": curve["first_unusable"],
            "host_shared": bool(run.get("shared_host")),
        })
    return sorted(rows, key=lambda r: r["workers"])


def main(argv: list) -> int:
    """Prints the analysis; exits 1 when there is a finding."""
    import yaml

    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print(__doc__)
        return 2
    budgets = yaml.safe_load(BUDGETS.read_text())
    if "--workers" in argv:
        print("workers  usable connections  req/s there  peak req/s  peak per worker  active people (at usable)  next level")
        for row in worker_scaling(paths, budgets):
            nxt = row["next_level"]
            beyond = f"{nxt['users']} connections: {nxt['delivered'] * 100:.0f}% delivered, p95 {nxt['p95_ms']} ms" if nxt else "none reached"
            people = f"{row['people_low']:,}-{row['people_high']:,}"
            print(f"{row['workers']:>7}  {row['usable_users'] or 0:>18}  {row['delivered_rps']:>11.0f}  {row['peak_rps']:>10.0f}  {row['peak_rps_per_worker'] or 0:>15.1f}  {people:>25}  {beyond}")
        return 0
    result = analyse(Path(paths[0]), budgets)
    if "--json" in argv:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Tiers: {result['tiers']}")
        for row in result["scaling"]:
            tiers = ", ".join(f"{t} {v:.0f}ms" for t, v in sorted(row["p95"].items()))
            print(f"{row['label']:>17}  {row['scenario']:<14} u={row['users']:<3} {row['request']}  [{tiers}]" + (f"  <-- {row['finding']}" if row["finding"] else ""))
        for row in result["query_findings"]:
            counts = ", ".join(f"{t} {v:g}" for t, v in sorted(row["per_request"].items()))
            print(f"N+1 SUSPECT {row['scenario']:<14} {row['request']}  statements per request [{counts}]")
        for label, capacity in (("capacity", result["capacity"]), ("capacity (mixed)", result["capacity_mixed"])):
            for level in capacity["levels"]:
                print(f"{label} {level['tier']} {level['users']:>4} connections: offered {level['offered_rps']:.0f} req/s, delivered {level['delivered_rps']:.0f} "
                      f"({level['delivered'] * 100:.0f}%), failures {level['failure_rate'] * 100:.1f}%, p95 {level['p95_ms']} ms, "
                      f"about {level['people_low']:,}-{level['people_high']:,} active people"
                      + ("" if level["usable"] else "  <-- beyond the budget"))
            if capacity["levels"]:
                usable_level = next((lvl for lvl in capacity["levels"] if lvl["users"] == capacity["usable_users"]), None)
                print(f"usable {label}: {capacity['usable_users']} connections (about {usable_level['people_low']:,}-{usable_level['people_high']:,} active people)"
                      if usable_level else f"usable {label}: below the first level run")
        for tier, memory in sorted(result["worker_memory"].items()):
            print(f"workers {tier}: {memory['workers']} x {memory['private_mib_per_worker']:.0f} MiB private + {memory['shared_mib_per_worker']:.0f} MiB shared each; {memory['pss_total_mib']:.0f} MiB total")
        if result["postgres"]:
            print("postgres settings: " + ", ".join(f"{k}={v}" for k, v in result["postgres"].items()))
        if result["db_pool"]:
            print(f"backend pool: {result['db_pool']['pool_size']} + {result['db_pool']['max_overflow']} per worker, ceiling {result['db_pool']['connection_ceiling']} connections")
        for key, rows in result["top_statements"].items():
            for row in rows:
                print(f"top statement {key}: {row['total_ms']:.0f} ms over {row['calls']} calls ({row['mean_ms']:.2f} ms each): {row['query'][:110]}")
        for finding in result["database_findings"]:
            print(f"DATABASE {finding['kind']} {finding['where']}: {finding['detail']}")
        for finding in result["plan_findings"]:
            print(f"SEQ SCAN {finding['relation']} (~{finding['est_rows']} rows, filtered) in {finding['tier']}/{finding['scenario']} statement #{finding['rank']}: check for a missing index")
        for finding in result["budget_findings"]:
            print(f"OVER BUDGET {finding['request']} u={finding['users']} {finding['tier']}: p95 {finding['p95_ms']:.0f}ms > {finding['budget_ms']}ms ({finding['class']})")
        for key, value in result["peak_memory_mib"].items():
            print(f"peak memory {key}: {value:.0f} MiB")
        for tier, value in result["soak_backend_mib_per_hour"].items():
            if value is not None:
                print(f"soak backend memory slope {tier}: {value:+.1f} MiB/hour")
    findings = ("scaling_findings", "budget_findings", "query_findings", "database_findings", "plan_findings")
    return 1 if any(result[name] for name in findings) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
