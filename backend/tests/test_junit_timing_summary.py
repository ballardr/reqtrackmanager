"""
Module: tests.test_junit_timing_summary

Pins `scripts/junit_timing_summary.py`: it reads pytest-, Playwright- and Vitest-shaped JUnit files, lists the slowest
cases, states whether the run met its target, and never fails because a run was slow.

Skipped when the repository root is not visible (the backend container mounts only backend/).
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "junit_timing_summary.py"
pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="repository checkout not available")

REPORT = """<testsuites><testsuite name="a" time="120.5">
<testcase classname="x.y" name="fast" time="1.0"/><testcase classname="x.y" name="slow | pipe" time="90.0"/>
</testsuite><testsuite name="b" time="30"><testcase classname="z" name="mid" time="30"/></testsuite></testsuites>"""


def _module():
    spec = importlib.util.spec_from_file_location("junit_timing_summary", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_summary_lists_the_slowest_first_and_states_the_target(tmp_path, capsys):
    report = tmp_path / "r.xml"
    report.write_text(REPORT)
    mod = _module()
    assert mod.main([str(report), "--title", "Suite", "--budget-minutes", "1"]) == 0
    out, err = capsys.readouterr()
    assert "3 tests" in out and "2.0 minutes elapsed" in out and "over" in out
    assert out.index("slow / pipe") < out.index("mid") < out.index("fast")
    assert "::warning::" in err


def test_a_run_within_its_target_has_no_warning(tmp_path, capsys):
    report = tmp_path / "r.xml"
    report.write_text(REPORT)
    assert _module().main([str(report), "--title", "Suite", "--budget-minutes", "5"]) == 0
    out, err = capsys.readouterr()
    assert "within" in out and err == ""


def test_a_missing_report_is_reported_not_raised(tmp_path, capsys):
    assert _module().main([str(tmp_path / "none.xml"), "--title", "Suite"]) == 2
