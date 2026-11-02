"""
Module: services.perf_dataset.registry

The core artefact types' dataset generators, in the shape `ModuleDefinition.perf_generators` uses for a module's
own. `modules.registry.get_perf_generators` merges the two.

Responsibilities:
- Name which generator writes each core artefact type and in what order.

Design decisions:
- A module never edits this file: it declares `ModuleDefinition.perf_generators` instead, the same extension
  point shape as `search_providers` and `record_tables`.

Dependencies: `perf_dataset.core`, `modules.registry.PerfDatasetGenerator`.
"""

from __future__ import annotations

from app.modules.registry import PerfDatasetGenerator
from app.services.perf_dataset.change_requests import generate_change_requests
from app.services.perf_dataset.core import generate_actions, generate_requirements

CORE_PERF_GENERATORS: dict[str, PerfDatasetGenerator] = {
    "requirement": PerfDatasetGenerator(generate=generate_requirements, order=10),
    "requirement_action": PerfDatasetGenerator(generate=generate_actions, order=20),
    "change_request": PerfDatasetGenerator(generate=generate_change_requests, order=30),
}
