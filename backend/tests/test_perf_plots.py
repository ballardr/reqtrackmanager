"""
Pins the parts of `perf/plot_results.py` that decide what a figure may say, without drawing one.

Why: the website's figures are drawn from local results bundles that the repository does not hold, so a figure can quietly be
built from the wrong bundle (another commit, another worker count) or label a statement wrongly. These tests fix the rules
that stop that: a bundle must be what the source table says, the pieces of a comparison must share a commit, and a statement
is named by its verb and first real table. They need matplotlib (not a backend dependency), so they skip without it.

Skipped when the repository root is not visible (the backend container mounts only backend/).
"""

import json
import sys
from pathlib import Path

import pytest

_PERF = Path(__file__).resolve().parents[2] / "perf"
if not (_PERF / "plot_results.py").is_file():
    pytest.skip("perf/ is not visible from here", allow_module_level=True)
pytest.importorskip("matplotlib")
sys.path.insert(0, str(_PERF.parent))
sys.path.insert(0, str(_PERF))

import plot_results  # noqa: E402


def test_a_statement_is_named_by_its_verb_and_first_real_table():
    name = plot_results.statement_name
    assert name("SELECT requirements.id FROM requirements LEFT OUTER JOIN requirement_versions ON x = y") == "SELECT requirements"
    assert name("SELECT count(*) FROM requirement_versions WHERE a = $1") == "SELECT count requirement_versions"
    assert name("SELECT x FROM (SELECT y FROM audit_events WHERE z = 1) AS sub") == "SELECT audit_events"
    assert name("UPDATE projects SET a = $1") == "UPDATE projects"


def _bundle(root: Path, directory: str, *, workers: int, tiers: list, aborted: bool = False) -> None:
    path = root / directory
    path.mkdir(parents=True)
    (path / "run.json").write_text(json.dumps({"workers": workers, "tiers": tiers, "aborted": "x" if aborted else None, "non_publishable": False}))
    (path / "host.json").write_text(json.dumps({"schema_version": 1}))


def test_a_bundle_that_is_not_what_the_source_table_says_is_refused(tmp_path, monkeypatch):
    role, directory, workers, tiers = plot_results.BUNDLES[0]
    monkeypatch.setattr(plot_results, "RESULTS", tmp_path)
    monkeypatch.setattr(plot_results, "BUNDLES", [(role, directory, workers, tiers)])

    with pytest.raises(SystemExit, match="not a results bundle"):
        plot_results.load_bundles()

    _bundle(tmp_path, directory, workers=workers + 1, tiers=list(tiers))
    with pytest.raises(SystemExit, match=f"expected {workers} workers"):
        plot_results.load_bundles()


def test_an_aborted_bundle_is_refused(tmp_path, monkeypatch):
    role, directory, workers, tiers = plot_results.BUNDLES[0]
    monkeypatch.setattr(plot_results, "RESULTS", tmp_path)
    monkeypatch.setattr(plot_results, "BUNDLES", [(role, directory, workers, tiers)])
    _bundle(tmp_path, directory, workers=workers, tiers=list(tiers), aborted=True)
    with pytest.raises(SystemExit, match="aborted"):
        plot_results.load_bundles()


def test_bundles_drawn_together_must_share_a_commit():
    def bundle(commit):
        return {"run": {"commit": commit, "caps": {"per_service": {"backend": {"mem": "9502m"}}}}, "path": Path("/nonexistent")}

    with pytest.raises(plot_results.NotComparable, match="different commits"):
        plot_results.figure_memory({"memory-4w": bundle("a" * 40), "memory-6w": bundle("b" * 40)}, plot_results.THEMES["light"])
    with pytest.raises(plot_results.NotComparable, match="different commits"):
        plot_results.figure_scaling({"onew-linux": bundle("a" * 40), "onew-pi": bundle("b" * 40)}, plot_results.THEMES["light"])


def test_every_source_has_a_distinct_role_and_directory():
    roles = [role for role, *_ in plot_results.BUNDLES]
    directories = [directory for _, directory, *_ in plot_results.BUNDLES]
    assert len(set(roles)) == len(roles) and len(set(directories)) == len(directories)
