"""
Module: tests.test_playwright_shards

Pins the end-to-end sharding in `.github/workflows/ci.yml`: the shard count passed to Playwright equals the number of
jobs in the matrix, the aggregator job keeps the required check name, and the shard checker reads the count from the
workflow. Listing the tests per shard needs Node and the Playwright install, so the CI shard runs that part itself
(`scripts/check_playwright_shards.py`).

Skipped when the repository root is not visible (the backend container mounts only backend/).
"""

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
CHECKER = ROOT / "scripts" / "check_playwright_shards.py"
pytestmark = pytest.mark.skipif(not CI.is_file() or not CHECKER.is_file(), reason="repository checkout not available")


def _workflow() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def _checker():
    spec = importlib.util.spec_from_file_location("check_playwright_shards", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_shard_count_in_the_command_equals_the_matrix_size():
    jobs = _workflow()["jobs"]
    matrix = jobs["e2e-tests"]["strategy"]["matrix"]["shard"]
    assert matrix == list(range(1, len(matrix) + 1)), "shards are numbered 1..N"
    assert _checker().ci_shard_count() == len(matrix)
    assert re.search(r"--shard=\$\{\{ matrix\.shard \}\}/%d\b" % len(matrix), CI.read_text(encoding="utf-8"))


def test_the_required_check_name_is_kept_by_an_aggregator_that_needs_every_shard():
    jobs = _workflow()["jobs"]
    suite = jobs["e2e-suite"]
    assert suite["name"] == "E2E (Playwright) suite"
    assert suite["needs"] == ["e2e-tests"] and suite["if"] == "always()"
    assert "e2e-suite" in jobs["docker-build"]["needs"] and "e2e-tests" not in jobs["docker-build"]["needs"]


def test_the_serial_project_runs_once_and_the_parallel_project_is_sharded():
    text = CI.read_text(encoding="utf-8")
    assert text.count("--project=global-state-mutators") == 1
    assert '[ "${{ matrix.shard }}" = "1" ]' in text
    assert "--project=default --no-deps --shard=" in text
