"""
Module: perf.lib.catalog

The scenario catalogue: which scenarios exist, how long and how widely each runs in quick and full mode, and which
data volumes they apply to.

Responsibilities:
- Name every scenario the load generator defines (`perf/loadgen/scenarios.py::SCENARIOS` has the same names; a test
  keeps the two in step) with its kind, simulated-user levels, durations and limits.
- Choose the scenarios and parameters for a mode (`quick` or `full`) at a dataset tier.

Design decisions:
- The runner never imports Locust; this file is the host side's whole knowledge of the scenarios.
- Quick mode is T0 and T1, one repeat, no soak, short measured periods: minutes, for "did my change move anything".
  Full mode runs every tier with repeats and the soak: the figures that get published.
- Heavy scenarios (reports, bundles, imports, attachments, unpaged lists at large tiers, soak) are opt-in on a
  shared host (`--allow-heavy`): on a machine that also serves production they are the ones that can hurt.
- A scenario that is closed-loop and slow runs until `min_requests` complete (bounded by `max_seconds`), so a
  slow endpoint still yields samples instead of an empty row.

Dependencies: standard library only (Python 3.9+).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

TIER_ORDER = ("T0", "T1", "T2", "T3", "T4")
QUICK_TIERS = ("T0", "T1")
CAPACITY_REQUESTS_PER_SECOND = 1.0
"""Requests per second one simulated connection makes in the `capacity` scenario (`perf/loadgen/scenarios.py::Capacity`
paces itself the same). A real person makes one every 5-10 seconds, so N connections stand for 5-10 times N active people."""
CAPACITY_USERS_QUICK = (16, 64)
CAPACITY_USERS_FULL = (16, 32, 64, 128, 256)
CAPACITY_TIER = "T2"
CAPACITY_MAX_FAILURE_RATE = 0.05
"""The capacity steps stop once more than this share of requests fail: the stack is past what it can serve."""
CAPACITY_MIN_DELIVERED = 0.5
"""...or once it delivers less than this share of the offered request rate."""
IMPORT_ROW_LIMIT = 5000
"""The CSV import endpoint refuses more rows than this (HTTP 413), so a larger project is not a valid import test."""


@dataclass(frozen=True)
class ScenarioSpec:
    """One scenario's parameters.

    Attributes:
        name: Scenario name (a key of the load generator's `SCENARIOS`).
        kind: `read`, `write`, `heavy`, `soak` or `capacity`.
        description: What it exercises, for the plan output.
        users_quick / users_full: Simulated-user levels run in each mode.
        measure_seconds: Measured period (after warm-up) in quick and full mode.
        min_requests: Keep going until this many requests finished (heavy, slow scenarios).
        max_seconds: Longest the scenario may run in total, whatever `min_requests` says.
        heavy: Opt-in on a shared host.
        needs_nested: Only meaningful with a nested breadth profile.
        max_requirements: Skipped above this many requirements in the project.
        tiers: Run only at these tiers (None for every tier).
        repeats: Fixed number of repeats whatever the mode says (None for the mode's).
    """

    name: str
    kind: str
    description: str
    users_quick: tuple = (4,)
    users_full: tuple = (1, 4, 16)
    measure_seconds: tuple = (20, 60)
    min_requests: int = 0
    max_seconds: int = 900
    heavy: bool = False
    needs_nested: bool = False
    max_requirements: Optional[int] = None
    tiers: Optional[tuple] = None
    repeats: Optional[int] = None


CATALOG: dict = {
    spec.name: spec
    for spec in (
        ScenarioSpec("browse", "read", "projects, a page of requirements, a record, its links, comments, activity, the dashboard"),
        ScenarioSpec("list_unpaged", "read", "the default requirement list, which returns every requirement", users_quick=(1,), users_full=(1, 4), measure_seconds=(30, 90), min_requests=3),
        ScenarioSpec("list_filtered", "read", "status, tag and text filters with sorting, one page"),
        ScenarioSpec("search", "read", "global search within a project and across projects", users_quick=(2,), users_full=(1, 4, 8)),
        ScenarioSpec("links", "read", "link graph and links of a hub record, link candidates"),
        ScenarioSpec("edit", "write", "create, edit (new version + audit), comment and add an action", users_quick=(2,), users_full=(1, 4, 8)),
        ScenarioSpec("export_csv", "heavy", "the list as a CSV", users_quick=(1,), users_full=(1,), min_requests=3, heavy=True),
        ScenarioSpec("import_preview", "heavy", "preview of a CSV import of the project's own export", users_quick=(1,), users_full=(1,), min_requests=2, heavy=True, max_requirements=IMPORT_ROW_LIMIT),
        ScenarioSpec("report_pdf", "heavy", "a PDF report of the project (peak memory)", users_quick=(1,), users_full=(1,), min_requests=2, heavy=True),
        ScenarioSpec("report_docx", "heavy", "a Word report of the project (peak memory)", users_quick=(1,), users_full=(1,), min_requests=2, heavy=True),
        ScenarioSpec("bundle_export", "heavy", "the full project export bundle", users_quick=(1,), users_full=(1,), min_requests=3, heavy=True),
        ScenarioSpec("bundle_import", "heavy", "importing a project bundle into a new project", users_quick=(1,), users_full=(1,), min_requests=2, heavy=True),
        ScenarioSpec("attachment", "heavy", "uploading a 256 KB file to a requirement", users_quick=(2,), users_full=(1, 4), heavy=True),
        ScenarioSpec("project_scope", "read", "a parent's widened list and dashboard over its descendants", users_quick=(2,), users_full=(1, 4), needs_nested=True),
        ScenarioSpec(
            "capacity", "capacity", "steps the number of simulated connections up until the stack saturates or fails (one tier)",
            users_quick=CAPACITY_USERS_QUICK, users_full=CAPACITY_USERS_FULL, measure_seconds=(20, 45), heavy=True,
            tiers=(CAPACITY_TIER,), repeats=1,
        ),
        ScenarioSpec("soak", "soak", "a steady mix at a fixed rate to see whether memory keeps growing", users_quick=(4,), users_full=(4,), heavy=True),
    )
}

QUICK_SCENARIOS = ("browse", "list_unpaged", "list_filtered", "search", "links", "edit")
FULL_SCENARIOS = tuple(name for name in CATALOG if name != "soak")


def scenarios_for(mode: str, *, allow_heavy: bool, nested: bool, soak: bool) -> list:
    """The scenario names a run executes.

    Args:
        mode: `quick` or `full`.
        allow_heavy: Whether heavy scenarios may run (always true on a dedicated host).
        nested: Whether the breadth profile nests projects (enables `project_scope`).
        soak: Whether to add the soak (full mode only).

    Returns:
        Scenario names in catalogue order.
    """
    names = QUICK_SCENARIOS if mode == "quick" else FULL_SCENARIOS
    chosen = []
    for name in names:
        spec = CATALOG[name]
        if spec.heavy and not allow_heavy:
            continue
        if spec.needs_nested and not nested:
            continue
        chosen.append(name)
    if mode == "full" and soak and allow_heavy:
        chosen.append("soak")
    if mode == "quick" and nested and "project_scope" not in chosen:
        chosen.append("project_scope")
    return chosen


def parameters(name: str, mode: str, requirements_per_project: int, tier: Optional[str] = None, users: Optional[tuple] = None) -> list:
    """The runs of one scenario at one data volume.

    Args:
        name: Scenario name.
        mode: `quick` or `full`.
        requirements_per_project: Requirements in each project at this tier.
        tier: The tier (a scenario limited to some tiers is skipped at the others).
        users: Replaces the scenario's user levels (the operator's `--capacity-users`).

    Returns:
        A list of `{"users", "measure_seconds", "warmup_seconds", "min_requests", "max_seconds"}`, empty when the
        scenario does not apply at this size.
    """
    spec = CATALOG[name]
    if spec.max_requirements is not None and requirements_per_project > spec.max_requirements:
        return []
    if spec.tiers is not None and tier is not None and tier not in spec.tiers:
        return []
    index = 0 if mode == "quick" else 1
    levels = users or (spec.users_quick if mode == "quick" else spec.users_full)
    return [
        {"users": users, "measure_seconds": spec.measure_seconds[index], "warmup_seconds": 5 if mode == "quick" else 10,
         "min_requests": spec.min_requests, "max_seconds": spec.max_seconds}
        for users in levels
    ]
