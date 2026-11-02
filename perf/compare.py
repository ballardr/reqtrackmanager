#!/usr/bin/env python3
"""
Module: perf.compare

Diffs one results bundle against the latest comparable bundle of the same host and reports what moved.

Responsibilities:
- Decide whether two bundles are comparable (same host label, commit aside: workers, pool, PostgreSQL settings,
  caps, seed, dataset profile version, density and breadth), and say why not (`incomparable`).
- Find the baseline for a bundle automatically: the newest earlier comparable bundle of the same host label
  (`find_baseline`).
- Flag a latency regression only when it exceeds the run's own noise band: the spread across the repeats of the
  newer run (three standard deviations), a relative floor and an absolute floor (`latency_changes`).
- Flag exact changes without a noise band: statements per request (an N+1 grows them), peak memory per service,
  and the usable capacity level and its delivered rate (`query_changes`, `memory_changes`, `capacity_changes`).
- Flag a request that is over budget in the newer bundle and was not in the older one (`new_budget_findings`).

Usage:
    python3 perf/compare.py perf/results/<host-label>/<date>-<commit>            (against the latest comparable)
    python3 perf/compare.py <newer-bundle> --against <older-bundle> [--json]
Exit status: 0 nothing regressed, 1 a regression, 2 no comparable baseline or bad usage.

Design decisions:
- Pure functions over rows, unit-tested; the command line only loads files. Reads results only: it never starts a
  stack, so it is safe on any host and in a scheduled job.
- A difference is only reported between like and like. A bundle that differs in an input (workers, pool, caps, seed)
  is refused with the reason, never diffed with a caveat, because the number would describe the input and not the code.
- A shared host's latency is noisy; the noise band is measured from the bundle's own repeats, and a single-repeat
  (quick) run falls back to the wider relative floor, so a quick run flags large moves only.
- Imports `analyse` for budgets, the capacity curve and the request classes so there is one definition of each.

Dependencies: PyYAML (through `analyse`); standard library otherwise (Python 3.9+).
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import analyse  # noqa: E402

# A bundle is comparable only when these `run.json` inputs are equal (the commit is the thing being compared).
COMPARABLE_INPUTS = ("host_label", "workers", "db_pool", "postgres", "backend_memory", "caps", "seed", "profiles_version", "density", "breadth")

REQUIRED_FILES = ("run.json", "dataset.json", "latency.csv", "queries.csv", "samples.csv")

NOISE_SIGMAS = 3.0  # a change must exceed this many standard deviations of the newer run's repeats
RELATIVE_FLOOR = 0.15  # ... and this fraction of the older value (0.30 when the newer run has no repeats)
RELATIVE_FLOOR_SINGLE = 0.30
ABSOLUTE_FLOOR_MS = 10.0  # ... and this many milliseconds, so 3 ms becoming 5 ms is not a finding
MIN_SAMPLES = 3  # requests behind each side of a latency comparison
QUERY_GROWTH = 0.10  # statements per request: more than 10% and at least one extra statement
MEMORY_GROWTH = 0.10  # peak memory: more than 10% and at least 64 MiB
MEMORY_FLOOR_MIB = 64.0


def incomparable(older: dict, newer: dict) -> list:
    """Reasons two `run.json` documents cannot be diffed (empty when they can).

    Args:
        older: The baseline's parsed `run.json`.
        newer: The new run's parsed `run.json`.

    Returns:
        One sentence per differing input in `COMPARABLE_INPUTS`.
    """
    return [f"{key} differs ({older.get(key)!r} vs {newer.get(key)!r})" for key in COMPARABLE_INPUTS if older.get(key) != newer.get(key)]


def find_baseline(bundle: Path) -> Path | None:
    """The newest earlier bundle of the same host label that is comparable with `bundle`, or None.

    Bundles are directories `<date>-<commit>[-n]` under `perf/results/<host-label>/`; earlier means a name that sorts
    before `bundle`'s. An aborted run and a partial bundle (copied back without its CSV files) are skipped.
    """
    newer_run = _run(bundle)
    candidates = sorted(p for p in bundle.parent.iterdir() if p.is_dir() and p.name < bundle.name)
    for candidate in reversed(candidates):
        older_run = _run(candidate)
        complete = all((candidate / name).is_file() for name in REQUIRED_FILES)
        if complete and older_run and not older_run.get("aborted") and not incomparable(older_run, newer_run):
            return candidate
    return None


def _run(bundle: Path) -> dict:
    """The parsed `run.json` of a bundle ({} when absent)."""
    path = bundle / "run.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def _per_repeat_means(rows: list) -> dict:
    """Count-weighted mean latency per `(tier, scenario, request, users)`, one value per repeat, plus the sample count.

    Returns:
        `{key: {"means": [mean_ms per repeat], "count": total requests}}`.
    """
    grouped: dict = defaultdict(lambda: {"means": [], "count": 0})
    for row in rows:
        count = int(row["count"] or 0)
        if count == 0 or row["scenario"].startswith("capacity"):
            continue
        key = (row["tier"], row["scenario"], row["request"], int(row["users"]))
        grouped[key]["means"].append(float(row["mean_ms"] or 0))
        grouped[key]["count"] += count
    return grouped


def latency_changes(older: list, newer: list) -> dict:
    """Latency moves beyond the noise band, between two `latency.csv` row lists.

    A request regresses when its mean rose by more than the largest of: three standard deviations of the newer run's
    repeats, a relative floor of the older mean, and an absolute floor in milliseconds; it improved on the mirror image.

    Returns:
        `{"regressions": [...], "improvements": [...]}`, each entry `{key, request, tier, scenario, users, old_ms, new_ms,
        change, band_ms}`, worst first. Requests with fewer than `MIN_SAMPLES` requests on either side are skipped.
    """
    before, after = _per_repeat_means(older), _per_repeat_means(newer)
    regressions, improvements = [], []
    for key in sorted(set(before) & set(after)):
        if before[key]["count"] < MIN_SAMPLES or after[key]["count"] < MIN_SAMPLES:
            continue
        old = statistics.fmean(before[key]["means"])
        new = statistics.fmean(after[key]["means"])
        spread = statistics.stdev(after[key]["means"]) if len(after[key]["means"]) > 1 else 0.0
        floor = RELATIVE_FLOOR if len(after[key]["means"]) > 1 else RELATIVE_FLOOR_SINGLE
        band = max(NOISE_SIGMAS * spread, floor * old, ABSOLUTE_FLOOR_MS)
        tier, scenario, request, users = key
        entry = {"request": request, "tier": tier, "scenario": scenario, "users": users, "old_ms": round(old, 1),
                 "new_ms": round(new, 1), "change": round(new / old, 2) if old else None, "band_ms": round(band, 1)}
        if new - old > band:
            regressions.append(entry)
        elif old - new > band:
            improvements.append(entry)
    regressions.sort(key=lambda e: e["new_ms"] - e["old_ms"], reverse=True)
    improvements.sort(key=lambda e: e["old_ms"] - e["new_ms"], reverse=True)
    return {"regressions": regressions, "improvements": improvements}


def query_changes(older: list, newer: list) -> list:
    """Routes whose statements per request grew (an N+1 or a new lookup), between two `queries.csv` row lists.

    Statement counts are exact, so any growth over `QUERY_GROWTH` of at least one statement is reported.

    Returns:
        Entries `{tier, scenario, request, old, new}`, largest growth first.
    """
    def table(rows: list) -> dict:
        return {(r["tier"], r["scenario"], r["request"]): float(r["queries_per_request"]) for r in rows}

    old, new = table(older), table(newer)
    grown = [{"tier": k[0], "scenario": k[1], "request": k[2], "old": old[k], "new": new[k]}
             for k in sorted(set(old) & set(new)) if new[k] - old[k] >= 1 and new[k] > old[k] * (1 + QUERY_GROWTH)]
    return sorted(grown, key=lambda e: e["new"] - e["old"], reverse=True)


def memory_changes(older: list, newer: list) -> list:
    """Services whose peak memory per tier grew, between two `samples.csv` row lists.

    A peak is a single sample, so the floor is wide: more than `MEMORY_GROWTH` and at least `MEMORY_FLOOR_MIB`.

    Returns:
        Entries `{tier, service, old_mib, new_mib}`, largest growth first.
    """
    old, new = analyse.memory_peaks(older), analyse.memory_peaks(newer)
    grown = [{"tier": k[0], "service": k[1], "old_mib": round(old[k]), "new_mib": round(new[k])}
             for k in sorted(set(old) & set(new)) if new[k] - old[k] >= MEMORY_FLOOR_MIB and new[k] > old[k] * (1 + MEMORY_GROWTH)]
    return sorted(grown, key=lambda e: e["new_mib"] - e["old_mib"], reverse=True)


def capacity_changes(older: list, newer: list, budgets: dict) -> list:
    """Capacity levels that moved: the usable level and the delivered rate at each level both runs measured.

    A fall of the usable level, or of the delivered rate at a shared level by more than `RELATIVE_FLOOR`, is a regression.

    Returns:
        Entries `{scenario, kind, users, old, new, regression}` where `kind` is `usable` or `delivered`.
    """
    changes = []
    for scenario in ("capacity", "capacity_mixed"):
        before = analyse.capacity_curve(older, budgets, scenario)
        after = analyse.capacity_curve(newer, budgets, scenario)
        if not before["levels"] or not after["levels"]:
            continue
        old_u, new_u = before["usable_users"] or 0, after["usable_users"] or 0
        if old_u != new_u:
            changes.append({"scenario": scenario, "kind": "usable", "users": None, "old": old_u, "new": new_u, "regression": new_u < old_u})
        old_levels = {(lvl["tier"], lvl["users"]): lvl for lvl in before["levels"]}
        for level in after["levels"]:
            prior = old_levels.get((level["tier"], level["users"]))
            if not prior or not prior["delivered_rps"]:
                continue
            ratio = level["delivered_rps"] / prior["delivered_rps"]
            if abs(ratio - 1) > RELATIVE_FLOOR:
                changes.append({"scenario": scenario, "kind": "delivered", "users": level["users"], "old": prior["delivered_rps"],
                                "new": level["delivered_rps"], "regression": ratio < 1})
    return changes


def new_budget_findings(older: list, newer: list, budgets: dict, sizes_old: dict, sizes_new: dict) -> list:
    """Budget breaches present in the newer bundle and absent from the older one (judged on p95, as `analyse` does)."""
    def breached(rows: list, sizes: dict) -> dict:
        table = analyse.scaling_table([r for r in rows if not r["scenario"].startswith("capacity")], sizes, budgets)
        return {(f["request"], f["users"], f["tier"]): f for f in analyse.budget_findings(table, budgets)}

    old, new = breached(older, sizes_old), breached(newer, sizes_new)
    return [new[k] for k in sorted(set(new) - set(old))]


def compare(older: Path, newer: Path, budgets: dict) -> dict:
    """Compares two bundle directories.

    Raises:
        ValueError: If the bundles are not comparable (the message lists each differing input).
    """
    reasons = incomparable(_run(older), _run(newer))
    if reasons:
        raise ValueError("not comparable: " + "; ".join(reasons))

    def sizes(bundle: Path) -> dict:
        datasets = json.loads((bundle / "dataset.json").read_text())["datasets"]
        return {d["tier"]: d["spec"]["requirements_per_project"] for d in datasets}

    lat_old, lat_new = analyse.read_csv(older / "latency.csv"), analyse.read_csv(newer / "latency.csv")
    latency = latency_changes(lat_old, lat_new)
    queries = query_changes(analyse.read_csv(older / "queries.csv"), analyse.read_csv(newer / "queries.csv"))
    memory = memory_changes(analyse.read_csv(older / "samples.csv"), analyse.read_csv(newer / "samples.csv"))
    capacity = capacity_changes(lat_old, lat_new, budgets)
    budget = new_budget_findings(lat_old, lat_new, budgets, sizes(older), sizes(newer))
    regressed = bool(latency["regressions"] or queries or memory or budget or any(c["regression"] for c in capacity))
    return {"older": older.name, "newer": newer.name, "latency": latency, "queries": queries, "memory": memory,
            "capacity": capacity, "new_budget_findings": budget, "regressed": regressed}


def main(argv: list) -> int:
    """Prints the comparison; exits 1 on a regression, 2 without a comparable baseline."""
    import yaml

    paths = [a for a in argv if not a.startswith("--")]
    against = argv[argv.index("--against") + 1] if "--against" in argv else None
    if against:
        paths = [p for p in paths if p != against]
    if len(paths) != 1:
        print(__doc__)
        return 2
    newer = Path(paths[0])
    older = Path(against) if against else find_baseline(newer)
    if older is None:
        print(f"no earlier comparable bundle of {newer.parent.name} for {newer.name}")
        return 2
    budgets = yaml.safe_load(analyse.BUDGETS.read_text())
    try:
        result = compare(older, newer, budgets)
    except ValueError as error:
        print(f"{older.name} vs {newer.name}: {error}")
        return 2
    if "--json" in argv:
        print(json.dumps(result, indent=2, default=str))
        return 1 if result["regressed"] else 0
    print(f"{older.name} -> {newer.name}")
    for e in result["latency"]["regressions"]:
        print(f"SLOWER {e['tier']}/{e['scenario']} u={e['users']} {e['request']}: {e['old_ms']} -> {e['new_ms']} ms "
              f"(x{e['change']}, noise band {e['band_ms']} ms)")
    for e in result["queries"]:
        print(f"MORE STATEMENTS {e['tier']}/{e['scenario']} {e['request']}: {e['old']:g} -> {e['new']:g} per request")
    for e in result["memory"]:
        print(f"MORE MEMORY {e['tier']}/{e['service']}: peak {e['old_mib']} -> {e['new_mib']} MiB")
    for e in result["capacity"]:
        what = (f"usable level {e['old']} -> {e['new']} connections" if e["kind"] == "usable"
                else f"{e['users']} connections deliver {e['old']} -> {e['new']} req/s")
        print(f"{'CAPACITY DOWN' if e['regression'] else 'capacity up'} {e['scenario']}: {what}")
    for e in result["new_budget_findings"]:
        print(f"NEWLY OVER BUDGET {e['request']} u={e['users']} {e['tier']}: p95 {e['p95_ms']:.0f} ms > {e['budget_ms']} ms")
    for e in result["latency"]["improvements"][:10]:
        print(f"faster {e['tier']}/{e['scenario']} u={e['users']} {e['request']}: {e['old_ms']} -> {e['new_ms']} ms")
    print("REGRESSED" if result["regressed"] else "no regression beyond the noise band")
    return 1 if result["regressed"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
