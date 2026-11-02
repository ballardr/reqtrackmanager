"""
Pins the multi-architecture image pipeline in ci.yml: every production image is built for amd64 and arm64 on a
native runner of that architecture, the arm64 image is smoke tested and scanned before its digest is pushed, and
the tags are assembled into one manifest list only after every leg has passed.

Why: an arm64 image that builds but does not start (or that is silently left out of the manifest) is a
user-facing failure for people self-hosting on Raspberry Pi, and none of it shows in the amd64-only test suites.
A workflow edit that drops a leg, an image or a gate would leave the pipeline green, so a test fails instead.

Skipped when the repository root is not visible (the backend container mounts only backend/).
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SMOKE_SCRIPT = ROOT / "scripts" / "smoke_test_image.sh"

pytestmark = pytest.mark.skipif(not WORKFLOW.is_file(), reason="repository root not available")

IMAGES = {"backend", "backup", "frontend", "mcp-server", "docs"}


@pytest.fixture(scope="module")
def jobs() -> dict:
    """Returns the parsed `jobs` mapping of ci.yml."""
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


@pytest.fixture(scope="module")
def matrix(jobs) -> dict:
    """Returns docker-build's strategy matrix."""
    return jobs["docker-build"]["strategy"]["matrix"]


def _includes(matrix: dict) -> dict[str, dict]:
    """Returns the matrix `include` entries keyed by image name."""
    return {entry["image"]: entry for entry in matrix["include"]}


def test_every_image_is_built_for_both_architectures(matrix):
    """The matrix is exactly the five production images times amd64 and arm64."""
    assert set(matrix["image"]) == IMAGES
    assert set(matrix["arch"]) == {"amd64", "arm64"}


def test_arm64_legs_run_on_a_native_arm_runner(jobs):
    """arm64 builds natively (QEMU emulation of the pip and npm builds is several times slower)."""
    runs_on = jobs["docker-build"]["runs-on"]
    assert "ubuntu-24.04-arm" in runs_on and "matrix.arch == 'arm64'" in runs_on
    assert "ubuntu-latest" in runs_on


def test_the_matrix_covers_every_image_the_compose_stack_pulls():
    """A new `-<name>` image in docker-compose.yml must be added to the build matrix, or arm hosts cannot pull it."""
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    pulled = set(re.findall(r"GHCR_IMAGE_PREFIX:-[^}]+\}-([a-z-]+):", compose))
    assert pulled <= IMAGES, f"compose pulls images the build matrix does not publish: {pulled - IMAGES}"


def test_each_matrix_image_has_a_dockerfile_and_the_build_args_it_declares(matrix):
    """The context and Dockerfile exist, and version build args are passed exactly to images that declare them."""
    includes = _includes(matrix)
    assert set(includes) == IMAGES
    for name, entry in includes.items():
        context = ROOT / entry["context"]
        dockerfile = ROOT / entry["file"] if "file" in entry else context / "Dockerfile"
        assert dockerfile.is_file(), f"{name}: {dockerfile} not found"
        declares_version = "ARG APP_VERSION" in dockerfile.read_text(encoding="utf-8")
        assert bool(entry.get("version_args")) == declares_version, f"{name}: version_args does not match its Dockerfile"


def test_arm64_legs_smoke_test_and_scan_before_pushing(jobs):
    """In the arm64 leg the smoke test and Trivy scan come before the digest push, and both are arm64-only."""
    steps = jobs["docker-build"]["steps"]
    names = [step.get("name", "") for step in steps]
    smoke = next(i for i, n in enumerate(names) if n.startswith("Smoke test image"))
    scan = next(i for i, n in enumerate(names) if n.startswith("Scan image"))
    push = next(i for i, n in enumerate(names) if n == "Push image by digest")
    assert smoke < push and scan < push
    for index in (smoke, scan):
        assert steps[index]["if"] == "matrix.arch == 'arm64'"
    assert "scripts/smoke_test_image.sh" in steps[smoke]["run"]
    assert steps[smoke]["run"].rstrip().endswith("arm64")


def test_digests_are_pushed_untagged_and_only_off_pull_requests(jobs):
    """Legs push by digest (no tags) and only when this is not a pull request."""
    push = next(s for s in jobs["docker-build"]["steps"] if s.get("name") == "Push image by digest")
    assert push["if"] == "env.PUSH == 'true'"
    assert "push-by-digest=true" in push["with"]["outputs"]
    assert "tags" not in push["with"]
    assert jobs["docker-build"]["env"]["PUSH"] == "${{ github.event_name != 'pull_request' }}"


def test_manifest_job_publishes_every_image_only_after_all_legs_pass(jobs):
    """docker-publish needs the whole build matrix, skips pull requests and verifies both platforms."""
    publish = jobs["docker-publish"]
    assert "docker-build" in publish["needs"]
    assert "pull_request" in publish["if"]
    script = next(s["run"] for s in publish["steps"] if s.get("name", "").startswith("Create and verify"))
    for image in IMAGES:
        assert image in script
    for platform in ("linux/amd64", "linux/arm64"):
        assert platform in script
    for tag in ("$SEMVER", "$GITHUB_SHA", "latest"):
        assert tag in script


def test_registry_write_permission_is_limited_to_the_push_jobs(jobs):
    """Only the image legs and the manifest job may write packages."""
    writers = {name for name, job in jobs.items() if job.get("permissions", {}).get("packages") == "write"}
    assert writers == {"docker-build", "docker-publish"}


def test_smoke_script_handles_every_image():
    """The script has a branch for each matrix image."""
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")
    for image in IMAGES:
        assert re.search(rf"^{re.escape(image)}\)", script, re.M), f"smoke script has no {image} case"


def test_smoke_script_only_removes_what_it_created():
    """Cleanup is by this run's own names; the script never prunes or removes by wildcard."""
    script = SMOKE_SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert "prune" not in code
    assert 'docker rm -f -v "$name"' in script and 'docker network rm "$NETWORK"' in script
    assert 'PREFIX="reqtrack-smoke-${RUN_ID}"' in script
