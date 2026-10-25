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

Usage:
    python3 perf/analyse.py perf/results/<host-label>/<date>-<commit> [--json]

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
    by_tier: dict = defaultdict(lambda: defaultdict(list))
    for row in processes:
        by_tier[row["tier"]][(row["scenario"], row["repeat"])].append(row)
    result = {}
    for tier, readings in by_tier.items():
        best = max(readings.values(), key=lambda rows: sum(float(r["pss_mib"]) for r in rows))
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


def analyse(directory: Path, budgets: dict) -> dict:
    """The full analysis of one bundle directory."""
    datasets = json.loads((directory / "dataset.json").read_text())["datasets"]
    sizes = {d["tier"]: d["spec"]["requirements_per_project"] for d in datasets}
    latency = read_csv(directory / "latency.csv")
    samples = read_csv(directory / "samples.csv")
    table = scaling_table(latency, sizes, budgets)
    peaks = memory_peaks(samples)
    queries = query_scaling(read_csv(directory / "queries.csv"), sizes, budgets)
    return {
        "tiers": sizes,
        "scaling": table,
        "scaling_findings": [r for r in table if r["finding"]],
        "query_scaling": queries,
        "query_findings": [r for r in queries if r["finding"]],
        "worker_memory": worker_memory(read_csv(directory / "processes.csv")),
        "budget_findings": budget_findings(table, budgets),
        "peak_memory_mib": {f"{tier}/{service}": value for (tier, service), value in sorted(peaks.items())},
        "soak_backend_mib_per_hour": {tier: memory_slope_mib_per_hour(samples, tier) for tier in sizes},
        "failures": [r for r in latency if int(r["failures"] or 0) > 0],
    }


def main(argv: list) -> int:
    """Prints the analysis; exits 1 when there is a finding."""
    import yaml

    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print(__doc__)
        return 2
    budgets = yaml.safe_load(BUDGETS.read_text())
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
        for tier, memory in sorted(result["worker_memory"].items()):
            print(f"workers {tier}: {memory['workers']} x {memory['private_mib_per_worker']:.0f} MiB private + {memory['shared_mib_per_worker']:.0f} MiB shared each; {memory['pss_total_mib']:.0f} MiB total")
        for finding in result["budget_findings"]:
            print(f"OVER BUDGET {finding['request']} u={finding['users']} {finding['tier']}: p95 {finding['p95_ms']:.0f}ms > {finding['budget_ms']}ms ({finding['class']})")
        for key, value in result["peak_memory_mib"].items():
            print(f"peak memory {key}: {value:.0f} MiB")
        for tier, value in result["soak_backend_mib_per_hour"].items():
            if value is not None:
                print(f"soak backend memory slope {tier}: {value:+.1f} MiB/hour")
    return 1 if result["scaling_findings"] or result["budget_findings"] or result["query_findings"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
