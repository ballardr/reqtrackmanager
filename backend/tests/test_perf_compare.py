"""
Pins perf/compare.py, the run-to-run diff that tells a maintainer whether a change moved the measured numbers.

Why: the diff is the cheap way to repeat the profile as the product grows. A noise band that is too tight cries
wolf on every shared-host run, one that is too loose hides a real regression, and a diff across runs with different
inputs (workers, pool, seed) describes the input, not the code. Deterministic cases on made-up rows keep that honest
without running any load, so this is a main-suite test; the numbers it reads are never gated in CI.

Skipped when the repository root is not visible (the backend container mounts only backend/).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PERF = Path(__file__).resolve().parents[2] / "perf"
if not (_PERF / "compare.py").is_file():
    pytest.skip("perf/ is not visible from here", allow_module_level=True)
sys.path.insert(0, str(_PERF.parent))

from perf import compare  # noqa: E402

RUN = {"host_label": "x-host", "workers": 4, "db_pool": {"pool_size": 5}, "postgres": {"shared_buffers": "128MB"},
       "caps": {"cpus": 8}, "seed": 1, "profiles_version": 3, "density": "typical", "breadth": "single"}


def _lat(request: str, means: list, count: int = 50, scenario: str = "browse", tier: str = "T2", users: int = 4) -> list:
    """One latency row per repeat, with the given mean."""
    return [{"tier": tier, "scenario": scenario, "repeat": str(i + 1), "users": str(users), "request": request,
             "count": str(count), "mean_ms": str(m), "failures": "0", "p95_ms": str(m * 2), "rps": "1"} for i, m in enumerate(means)]


def test_bundles_with_different_inputs_are_not_comparable():
    """Workers, pool, PostgreSQL settings, caps, seed, profile version, density, breadth and host are all inputs."""
    assert compare.incomparable(RUN, dict(RUN)) == []
    for key, other in (("workers", 6), ("db_pool", {"pool_size": 3}), ("postgres", {}), ("caps", {"cpus": 4}), ("seed", 2),
                       ("profiles_version", 4), ("density", "dense"), ("breadth", "projects-10"), ("host_label", "y-host")):
        reasons = compare.incomparable(RUN, {**RUN, key: other})
        assert len(reasons) == 1 and key in reasons[0]


def test_a_latency_move_inside_the_noise_band_is_not_a_regression():
    """Repeats that scatter by 40 ms make a 30 ms rise noise; the same rise on steady repeats is a regression."""
    older = _lat("GET /a", [100, 100, 100])
    noisy = compare.latency_changes(older, _lat("GET /a", [100, 160, 100]))
    assert noisy["regressions"] == []
    steady = compare.latency_changes(older, _lat("GET /a", [150, 151, 149]))
    assert [e["request"] for e in steady["regressions"]] == ["GET /a"]
    assert steady["regressions"][0]["old_ms"] == 100 and steady["regressions"][0]["new_ms"] == 150


def test_small_absolute_and_small_relative_moves_are_ignored_and_improvements_are_reported():
    """3 ms to 6 ms is a doubling but below the absolute floor; a 10% rise on 1 s is below the relative floor."""
    assert compare.latency_changes(_lat("GET /a", [3, 3, 3]), _lat("GET /a", [6, 6, 6]))["regressions"] == []
    assert compare.latency_changes(_lat("GET /b", [1000] * 3), _lat("GET /b", [1100] * 3))["regressions"] == []
    faster = compare.latency_changes(_lat("GET /c", [200] * 3), _lat("GET /c", [100] * 3))
    assert faster["regressions"] == [] and [e["request"] for e in faster["improvements"]] == ["GET /c"]


def test_a_single_repeat_needs_a_wider_move_and_too_few_samples_are_skipped():
    """A quick run has no spread to measure, so a 20% rise is not flagged, a 50% rise is; two requests prove nothing."""
    assert compare.latency_changes(_lat("GET /a", [100]), _lat("GET /a", [120]))["regressions"] == []
    assert len(compare.latency_changes(_lat("GET /a", [100]), _lat("GET /a", [150]))["regressions"]) == 1
    assert compare.latency_changes(_lat("GET /a", [100], count=2), _lat("GET /a", [900], count=2)) == {"regressions": [], "improvements": []}


def test_capacity_rows_are_not_read_as_request_latency():
    """The capacity climb is judged on delivered rate, so its rows never appear as a slower request."""
    older = _lat("GET /a", [10] * 3, scenario="capacity")
    assert compare.latency_changes(older, _lat("GET /a", [900] * 3, scenario="capacity")) == {"regressions": [], "improvements": []}


def test_statement_growth_is_exact_and_memory_needs_a_real_step():
    """One extra statement on a 5-statement route is flagged; 3 to 3.2 is not. Peak memory must grow by 64 MiB and 10%."""
    older = [{"tier": "T2", "scenario": "s", "request": "GET /a", "queries_per_request": "5"},
             {"tier": "T2", "scenario": "s", "request": "GET /b", "queries_per_request": "3"}]
    newer = [{"tier": "T2", "scenario": "s", "request": "GET /a", "queries_per_request": "6"},
             {"tier": "T2", "scenario": "s", "request": "GET /b", "queries_per_request": "3.2"}]
    assert [e["request"] for e in compare.query_changes(older, newer)] == ["GET /a"]

    def sample(mem):
        return [{"tier": "T2", "scenario": "s", "repeat": "1", "service": "backend", "t_seconds": "1", "mem_mib": str(mem)}]

    assert compare.memory_changes(sample(2000), sample(2100)) == []  # 5%
    assert compare.memory_changes(sample(200), sample(250)) == []  # 25% but 50 MiB
    assert compare.memory_changes(sample(2000), sample(2300))[0]["new_mib"] == 2300


def test_a_lower_usable_capacity_or_delivered_rate_is_a_regression():
    """The usable level falling, or a shared level delivering over 15% less, regresses; delivering more does not."""
    budgets = {"capacity": {"delivered": 0.9, "failure_rate": 0.01, "p95_ms": 1000, "requests_per_user_per_second": 1.0,
                            "person_request_interval_seconds": {"busy": 5, "relaxed": 10}}}

    def level(users, rps, p95):
        return [{"tier": "T2", "scenario": "capacity", "repeat": "1", "users": str(users), "request": "GET /a", "count": "1000",
                 "failures": "0", "rps": str(rps), "p95_ms": str(p95)}]

    older = level(128, 125, 500) + level(256, 200, 1500)
    worse = level(128, 100, 900) + level(256, 190, 1500)
    changes = compare.capacity_changes(older, worse, budgets)
    assert any(c["kind"] == "delivered" and c["users"] == 128 and c["regression"] for c in changes)
    better = level(128, 127, 400) + level(256, 240, 800)
    changes = compare.capacity_changes(older, better, budgets)
    assert not any(c["regression"] for c in changes) and any(c["kind"] == "usable" and c["new"] == 256 for c in changes)


def _bundle(directory: Path, run: dict, complete: bool = True) -> Path:
    """Writes the minimum files of a bundle (or only run.json for a partial copy)."""
    directory.mkdir(parents=True)
    (directory / "run.json").write_text(json.dumps(run))
    if complete:
        (directory / "dataset.json").write_text(json.dumps({"datasets": [{"tier": "T2", "spec": {"requirements_per_project": 1000}}]}))
        for name in ("latency.csv", "queries.csv", "samples.csv"):
            (directory / name).write_text("")
    return directory


def test_the_baseline_is_the_newest_earlier_complete_comparable_bundle(tmp_path):
    """Skips a bundle with another input, an aborted run and a partial copy; never picks a later or the same bundle."""
    host = tmp_path / "x-host"
    good = _bundle(host / "2026-10-20-aaaaaaaa", RUN)
    _bundle(host / "2026-10-21-bbbbbbbb", {**RUN, "workers": 6})
    _bundle(host / "2026-10-22-cccccccc", {**RUN, "aborted": "host pressure"})
    _bundle(host / "2026-10-23-dddddddd", RUN, complete=False)
    newer = _bundle(host / "2026-10-24-eeeeeeee", RUN)
    _bundle(host / "2026-10-25-ffffffff", RUN)
    assert compare.find_baseline(newer) == good
    assert compare.find_baseline(good) is None
