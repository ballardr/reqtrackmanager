"""
Pins the CI security gates described in the change-management policy: a coverage threshold, dependency
scanning, image scanning before any image is pushed, and a CODEOWNERS file. Each is a workflow setting that
can be deleted by accident and would leave the pipeline green, so a test fails when one disappears.

Skipped when the repository root is not visible (the backend container mounts only backend/).
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

pytestmark = pytest.mark.skipif(not WORKFLOW.is_file(), reason="repository root not available")


def _job(name: str) -> str:
    """Returns the text of one top-level job in ci.yml (from its key to the next job key)."""
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)", text, re.S | re.M)
    assert match, f"job {name!r} not found in ci.yml"
    return match.group(1)


def test_backend_coverage_threshold_fails_the_build():
    """The pytest invocation carries --cov-fail-under, so a coverage drop fails the job."""
    match = re.search(r"--cov-fail-under=(\d+(?:\.\d+)?)", _job("backend-tests"))
    assert match, "backend-tests has no --cov-fail-under"
    assert float(match.group(1)) >= 90


def test_dependency_scan_covers_every_shipped_dependency_file():
    """Both Python requirement files and the frontend and Playwright lockfiles are audited."""
    job = _job("dependency-scan")
    for expected in ("pip_audit -r backend/requirements.txt", "pip_audit -r mcp-server/requirements.txt"):
        assert expected in job
    for folder in ("frontend", "tests/playwright"):
        assert re.search(rf"working-directory: {re.escape(folder)}\n\s+run: npm audit --omit=dev --audit-level=high", job)


def test_only_the_documentation_site_audit_is_non_gating():
    """continue-on-error appears exactly once in dependency-scan, on the documentation site step."""
    job = _job("dependency-scan")
    assert len(re.findall(r"^\s+continue-on-error:", job, re.M)) == 1
    assert re.search(r"working-directory: docs/website\n\s+continue-on-error: true", job)


def test_images_are_scanned_before_any_push():
    """Trivy runs in the image-scan job, which docker-build needs, so nothing is pushed unscanned."""
    scan_job = _job("image-scan")
    assert "Trivy" in scan_job and "--exit-code 1" in scan_job
    assert re.search(r"needs: \[[^\]]*image-scan[^\]]*\]", _job("docker-build"))


def test_every_pushed_image_is_scanned():
    """Each image docker-build pushes is built and named in the Trivy loop of image-scan."""
    pushed = re.findall(r"Build and push ([a-z-]+) image", _job("docker-build"))
    assert {"backend", "backup", "frontend", "mcp-server", "docs"} <= set(pushed)
    scan_job = _job("image-scan")
    loop = re.search(r"for image in ([^;]+); do", scan_job)
    assert loop, "image-scan has no Trivy loop"
    scanned = set(loop.group(1).split())
    for name in pushed:
        assert (f"scan-{name}:ci" in scanned) or (name == "docs" and "docs-smoke:test" in scanned), f"{name} image is pushed but not scanned"


def test_docker_build_waits_for_the_dependency_scan():
    """Publishing images needs the dependency scan to have passed."""
    assert re.search(r"needs: \[[^\]]*dependency-scan[^\]]*\]", _job("docker-build"))


def test_codeowners_file_exists_and_names_an_owner():
    """The ruleset's code-owner review rule has someone to ask."""
    codeowners = ROOT / ".github" / "CODEOWNERS"
    assert codeowners.is_file()
    rules = [line for line in codeowners.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    assert any(line.split()[0] == "*" and line.split()[1].startswith("@") for line in rules)
