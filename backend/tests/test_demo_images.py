"""Tests for the demonstration's image refresh: `scripts/demo.sh --pull`, the published-images overlay
(`tests/container/docker-compose.demo-images.yml`) and the host timer that runs it daily.

`demo.sh` is run with a fake `docker` that keeps image identifiers in files, so no Docker or network is needed. The
recording of the outcome by `demo_setup.py` is tested in `test_demo_setup.py`. Skipped when the repository root is not
visible (the backend container mounts only backend/).
"""

from __future__ import annotations

import configparser
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from app.services import demo_setup as rules

ROOT = Path(__file__).resolve().parents[2]
DEMO_SH = ROOT / "scripts" / "demo.sh"
CONTAINER = ROOT / "tests" / "container"
SCHEDULE_DIR = ROOT / "scripts" / "schedule"

pytestmark = pytest.mark.skipif(not DEMO_SH.is_file(), reason="repository checkout not available")

PREFIX = "ghcr.io/ballardr/reqtrackmanager"
SERVICES = ["backend", "converter", "frontend", "mcp-server", "docs"]


class _ComposeLoader(yaml.SafeLoader):
    """Reads Compose's `!reset` and `!override` tags as the value they wrap."""


def _construct_tagged(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> object:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    assert isinstance(node, yaml.ScalarNode)
    return loader.construct_scalar(node)


_ComposeLoader.add_multi_constructor("!", _construct_tagged)


def _load(path: Path) -> dict:
    return yaml.load(path.read_text(), Loader=_ComposeLoader)  # noqa: S506 - a SafeLoader subclass


# ---- the overlay -----------------------------------------------------------------------------------------------


def test_the_overlay_names_exactly_the_services_the_base_file_builds_from_this_repository():
    base = _load(CONTAINER / "docker-compose.yml")["services"]
    built = {name for name, service in base.items() if "build" in service or service.get("extends", {}).get("service") == "backend"}
    overlay = _load(CONTAINER / "docker-compose.demo-images.yml")["services"]
    assert set(overlay) == built, "a service built from this repository needs an image in the overlay (and the reverse)"
    assert set(SERVICES) <= set(overlay)


def test_the_base_file_for_developers_names_no_image_for_what_it_builds():
    base = _load(CONTAINER / "docker-compose.yml")["services"]
    for name in SERVICES:
        assert "image" not in base[name], f"{name} keeps building the working tree for Playwright and pytest"


def test_the_overlay_images_are_the_ones_the_production_file_names():
    production = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    overlay = _load(CONTAINER / "docker-compose.demo-images.yml")["services"]
    for name in SERVICES:
        assert overlay[name]["image"] == production[name]["image"], name
    assert overlay["demo-scheduler"]["image"] == overlay["backend"]["image"]
    assert all("pull_policy" not in service for service in overlay.values()), "demo.sh pulls explicitly so a failed pull is survivable"


def test_demo_sh_updates_exactly_the_overlay_services():
    text = DEMO_SH.read_text()
    listed = text.split("project_services=(")[1].split(")")[0].split()
    overlay = _load(CONTAINER / "docker-compose.demo-images.yml")["services"]
    assert listed == SERVICES and set(listed) == set(overlay) - {"demo-scheduler"}


# ---- demo.sh --pull --------------------------------------------------------------------------------------------

_FAKE_DOCKER = r"""#!/bin/sh
# State: $FAKE/<ref with / and : replaced by _> holds an image id. $FAKE_PULL: changed (backend gets a new id), same, fail.
ref_file() { printf '%s/%s' "$FAKE" "$(printf '%s' "$1" | tr '/:' '__')"; }
echo "$@" >> "$FAKE/log"
case "$1 $2" in
  "image inspect")
    ref="$5"; f="$(ref_file "$ref")"
    [ -f "$f" ] && { cat "$f"; exit 0; }
    exit 1 ;;
  "image rm") echo "$3" >> "$FAKE/removed"; exit 0 ;;
  "compose pull")
    case "$FAKE_PULL" in
      fail) exit 1 ;;
      changed) printf 'sha256:%064d' 2 > "$(ref_file "$PREFIX-backend:latest")" ;;
    esac
    exit 0 ;;
esac
case "$1" in
  tag) printf '%s' "$2" > "$(ref_file "$3")"; exit 0 ;;
  volume) exit 0 ;;
esac
case "$*" in
  *" up "*) [ "$FAKE_UP" = fail ] && exit 1; exit 0 ;;
esac
exit 0
"""


@pytest.fixture
def fake(tmp_path):
    """A fake `docker` on the path, an image state directory and a host state directory; returns (env, state, log)."""
    state = tmp_path / "state"
    state.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(_FAKE_DOCKER)
    docker.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DEMO_", "IMAGE_TAG", "GHCR_"))}
    env.update(PATH=f"{bin_dir}:{env['PATH']}", FAKE=str(state), PREFIX=PREFIX, FAKE_PULL="same", DEMO_HOST_STATE_DIR=str(tmp_path / "host"))
    for service in SERVICES:
        (state / f"{PREFIX}-{service}:latest".replace("/", "_").replace(":", "_")).write_text(f"sha256:{1:064d}")
    return env, state, state / "log"


def _run(env, *args, **extra):
    return subprocess.run(["bash", str(DEMO_SH), *args], capture_output=True, text=True, env={**env, **extra}, timeout=60, check=False)


def _lines(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def _exec_line(log: Path) -> str:
    [line] = [line for line in _lines(log) if line.startswith("compose exec")]
    return line


def _report(line: str) -> dict:
    """The JSON after `--image-report` (the first `}}` closes the last service entry)."""
    tail = line.split("--image-report ", 1)[1]
    return json.loads(tail[: tail.index("}}") + 2])


def test_a_newer_image_recreates_through_one_up_and_is_recorded_as_updated(fake):
    env, state, log = fake
    done = _run(env, "--pull", "--reset", FAKE_PULL="changed")
    assert done.returncode == 0, done.stderr
    lines = _lines(log)
    assert f"compose pull {' '.join(SERVICES)}" in lines
    [up] = [line for line in lines if " up " in f" {line} "]
    assert "--no-build" in up and "--wait" in up and "--build" not in up.replace("--no-build", "")
    assert lines.index(f"compose pull {' '.join(SERVICES)}") < lines.index(up) < lines.index(_exec_line(log))
    exec_line = _exec_line(log)
    assert "--image-update updated" in exec_line and "--reset" in exec_line
    report = _report(exec_line)
    assert report["backend"]["changed"] is True and report["backend"]["image_id"] == f"sha256:{2:064d}"
    assert all(report[name]["changed"] is False for name in SERVICES if name != "backend")
    assert "updated: backend" in done.stdout


def test_only_the_replaced_image_is_kept_as_previous(fake):
    env, state, log = fake
    assert _run(env, "--pull", FAKE_PULL="changed").returncode == 0
    tags = [line for line in _lines(log) if line.startswith("tag ")]
    assert tags == [f"tag sha256:{1:064d} {PREFIX}-backend:previous"]
    assert not (state / "removed").exists(), "nothing displaced yet: there was no earlier :previous"


def test_the_image_displaced_by_a_newer_previous_is_removed_after_the_stack_is_healthy(fake):
    env, state, log = fake
    (state / f"{PREFIX}-backend:previous".replace("/", "_").replace(":", "_")).write_text(f"sha256:{9:064d}")
    assert _run(env, "--pull", FAKE_PULL="changed").returncode == 0
    assert (state / "removed").read_text().split() == [f"sha256:{9:064d}"]
    lines = _lines(log)
    assert lines.index(f"image rm sha256:{9:064d}") > [i for i, line in enumerate(lines) if " up " in f" {line} "][0]
    outside = [line for line in lines if line.startswith(("volume", "system")) or "prune -a" in line or "--volumes" in line]
    assert not outside, "tagged images, containers and volumes are never pruned"


def test_nothing_new_recreates_nothing_and_still_resets(fake):
    env, state, log = fake
    done = _run(env, "--pull", "--reset", FAKE_PULL="same")
    assert done.returncode == 0
    exec_line = _exec_line(log)
    assert "--image-update unchanged" in exec_line and "--reset" in exec_line
    assert not any(line.startswith("tag ") for line in _lines(log))
    assert all(entry["changed"] is False for entry in _report(exec_line).values())


def test_a_failed_pull_keeps_the_current_images_resets_and_reports_failed(fake):
    env, state, log = fake
    done = _run(env, "--pull", "--reset", FAKE_PULL="fail")
    assert done.returncode == 0
    assert "continuing with the images already present" in done.stderr
    assert "--image-update failed" in _exec_line(log)
    assert any(" up " in f" {line} " and "--no-build" in line for line in _lines(log))


def test_an_unhealthy_new_image_stops_the_run_without_rolling_back(fake):
    env, state, log = fake
    done = _run(env, "--pull", "--reset", FAKE_PULL="changed", FAKE_UP="fail")
    assert done.returncode == 1
    assert "No rollback was attempted" in done.stderr and "IMAGE_TAG=" in done.stderr and f"backend was sha256:{1:064d}" in done.stderr
    lines = _lines(log)
    assert not any(line.startswith("compose exec") for line in lines), "nothing is seeded onto an unhealthy stack"
    assert not (state / "removed").exists()
    kept = [line for line in lines if line.startswith("tag ")]
    assert kept == [f"tag sha256:{1:064d} {PREFIX}-backend:previous"], "the old image is kept for a manual pin"


def test_pull_with_the_in_container_scheduler_is_refused_before_anything_runs(fake):
    env, state, log = fake
    done = _run(env, "--pull", "--schedule")
    assert done.returncode == 2 and "cannot be combined" in done.stderr
    assert _lines(log) == []


def test_a_live_run_holds_the_lock_and_a_stale_one_does_not(fake, tmp_path):
    env, state, log = fake
    lock = tmp_path / "host" / "pull.lock"
    lock.mkdir(parents=True)
    holder = subprocess.Popen(["sleep", "30"])
    try:
        (lock / "pid").write_text(str(holder.pid))
        busy = _run(env, "--pull")
        assert busy.returncode == 75 and "in progress" in busy.stderr
        assert _lines(log) == []
    finally:
        holder.kill()
        holder.wait()
    assert _run(env, "--pull").returncode == 0, "the holder has gone: its lock is stale"
    assert not lock.exists(), "the lock is released when the run ends"


def test_the_lock_is_released_after_a_failed_run(fake, tmp_path):
    env, state, log = fake
    assert _run(env, "--pull", FAKE_PULL="changed", FAKE_UP="fail").returncode == 1
    assert not (tmp_path / "host" / "pull.lock").exists()


def test_the_published_images_are_loaded_only_with_pull(fake):
    env, state, log = fake
    log_env = state / "compose-file"
    docker = Path(env["PATH"].split(":")[0]) / "docker"
    record = 'echo "$@" >> "$FAKE/log"'
    docker.write_text(docker.read_text().replace(record, f'{record}; echo "$COMPOSE_FILE" >> "$FAKE/compose-file"'))
    assert _run(env).returncode == 0
    assert "demo-images" not in log_env.read_text()
    assert any(" up " in f" {line} " and "--build" in line for line in _lines(log))
    assert not any(line.startswith("compose pull") for line in _lines(log))
    assert "--image-update" not in _exec_line(log)
    log_env.unlink()
    assert _run(env, "--pull").returncode == 0
    assert "docker-compose.demo-images.yml" in log_env.read_text()


def test_a_pinned_tag_and_registry_prefix_are_the_ones_inspected(fake):
    env, state, log = fake
    (state / "example.org_mirror-backend_v1.2.3").write_text(f"sha256:{3:064d}")
    done = _run(env, "--pull", GHCR_IMAGE_PREFIX="example.org/mirror", IMAGE_TAG="v1.2.3")
    assert done.returncode == 0
    inspected = [line for line in _lines(log) if line.startswith("image inspect")]
    assert any(line.endswith("example.org/mirror-backend:v1.2.3") for line in inspected)
    assert not any(PREFIX in line for line in inspected)


def test_the_reset_time_reaches_the_reset_so_the_sign_in_details_state_it(fake):
    env, state, log = fake
    assert _run(env, "--pull", DEMO_RESET_AT="09:00", DEMO_RESET_TZ="Australia/Sydney").returncode == 0
    line = _exec_line(log)
    assert "-e DEMO_RESET_AT=09:00" in line and "-e DEMO_RESET_TZ=Australia/Sydney" in line
    log.write_text("")
    assert _run(env, "--pull").returncode == 0
    assert "DEMO_RESET_AT" not in _exec_line(log)


# ---- the host timer --------------------------------------------------------------------------------------------


def _unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read_string("\n".join(line for line in path.read_text().splitlines() if not line.lstrip().startswith("#")))
    return parser


def _timer_and_service() -> tuple[str, str, str, str]:
    """(timer time, timer zone, DEMO_RESET_AT, DEMO_RESET_TZ) as shipped."""
    day, time, zone = _unit(SCHEDULE_DIR / "reqtrack-demo-reset.timer")["Timer"]["OnCalendar"].split()
    assert day == "*-*-*"
    variables = dict(
        line.removeprefix("Environment=").split("=", 1)
        for line in (SCHEDULE_DIR / "reqtrack-demo-reset.service").read_text().splitlines()
        if line.startswith("Environment=DEMO_")
    )
    return time, zone, variables["DEMO_RESET_AT"], variables["DEMO_RESET_TZ"]


def test_the_timer_runs_the_service_which_pulls_and_resets():
    timer, service = _unit(SCHEDULE_DIR / "reqtrack-demo-reset.timer"), _unit(SCHEDULE_DIR / "reqtrack-demo-reset.service")
    assert timer["Timer"]["Unit"] == "reqtrack-demo-reset.service" and timer["Timer"]["Persistent"] == "true"
    assert service["Service"]["Type"] == "oneshot" and service["Service"]["SuccessExitStatus"] == "75"
    assert service["Service"]["ExecStart"].endswith("scripts/demo.sh --pull --reset")


def test_the_timer_and_the_reset_time_in_the_service_are_the_same_wall_clock_time_and_zone():
    time, zone, at, tz = _timer_and_service()
    assert f"{at}:00" == time and tz == zone
    schedule = rules.demo_schedule(at, tz)
    assert rules.next_reset_at(schedule, datetime(2026, 11, 10, 0, 0, 1, tzinfo=UTC)) == datetime(2026, 11, 11, 0, 0, tzinfo=UTC)


def test_the_crontab_example_runs_the_same_command_with_the_matching_reset_time():
    jobs = [line for line in (SCHEDULE_DIR / "crontab.example").read_text().splitlines() if "demo.sh" in line and not line.startswith("#")]
    [job] = jobs
    assert job.startswith("0 0 * * * ") and "DEMO_RESET_AT=00:00" in job and "DEMO_RESET_TZ=UTC" in job and "--pull --reset" in job


def _systemd_next(spec_time: str, zone: str, now: datetime) -> datetime:
    """The next instant a systemd `OnCalendar=*-*-* HH:MM:SS <zone>` elapses after `now` (wall-clock in the zone)."""
    tz = ZoneInfo(zone)
    hour, minute, second = (int(part) for part in spec_time.split(":"))
    local = now.astimezone(tz)
    for days in range(3):
        day = (local + timedelta(days=days)).date()
        candidate = datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=tz)
        if candidate.astimezone(UTC) > now:
            return candidate.astimezone(UTC)
    raise AssertionError("no slot found")


@pytest.mark.parametrize(
    ("spec", "zone", "now"),
    [
        ("00:00", "UTC", datetime(2026, 11, 10, 0, 0, 0, tzinfo=UTC)),
        ("09:00", "Australia/Sydney", datetime(2026, 11, 9, 22, 59, 59, tzinfo=UTC)),
        ("09:00", "Australia/Sydney", datetime(2026, 11, 9, 23, 0, 0, tzinfo=UTC)),
        ("23:00", "America/Los_Angeles", datetime(2026, 11, 10, 6, 59, 59, tzinfo=UTC)),
        ("09:00", "Australia/Sydney", datetime(2027, 3, 28, 0, 0, tzinfo=UTC)),
        ("09:00", "Australia/Sydney", datetime(2027, 4, 4, 0, 0, tzinfo=UTC)),
        ("09:00", "Australia/Sydney", datetime(2027, 4, 11, 0, 0, tzinfo=UTC)),
        ("23:00", "America/Los_Angeles", datetime(2027, 3, 7, 0, 0, tzinfo=UTC)),
        ("23:00", "America/Los_Angeles", datetime(2027, 3, 14, 12, 0, tzinfo=UTC)),
        ("23:00", "America/Los_Angeles", datetime(2027, 3, 21, 0, 0, tzinfo=UTC)),
    ],
)
def test_the_reset_time_the_messages_state_is_the_instant_the_timer_elapses(spec, zone, now):
    """The sign-in details name `next_reset_at`; the timer fires at `OnCalendar`. They must be the same UTC instant,
    including at the boundary hours and a week either side of a daylight-saving change."""
    schedule = rules.demo_schedule(spec, zone)
    assert rules.next_reset_at(schedule, now) == _systemd_next(f"{spec}:00", zone, now)


# ---- disk -----------------------------------------------------------------------------------------------------


def test_a_healthy_update_prunes_dangling_images_and_week_old_build_cache_after_the_stack_is_up(fake):
    env, state, log = fake
    assert _run(env, "--pull", FAKE_PULL="changed").returncode == 0
    lines = _lines(log)
    up = next(i for i, line in enumerate(lines) if " up " in f" {line} ")
    assert lines.index("image prune -f") > up
    assert lines.index("builder prune -f --filter until=168h") > up
    assert lines.index("image prune -f") < lines.index(_exec_line(log)), "space is freed before the long seed"


def test_nothing_is_pruned_when_the_new_stack_is_unhealthy_so_the_old_images_remain_for_a_pin(fake):
    env, state, log = fake
    assert _run(env, "--pull", FAKE_PULL="changed", FAKE_UP="fail").returncode == 1
    assert not any("prune" in line for line in _lines(log))


def test_no_prune_keeps_everything_and_a_run_without_pull_never_prunes(fake):
    env, state, log = fake
    assert _run(env, "--pull", "--no-prune", FAKE_PULL="changed").returncode == 0
    assert not any("prune" in line for line in _lines(log))
    log.write_text("")
    assert _run(env).returncode == 0
    assert not any("prune" in line for line in _lines(log))


def test_a_failed_prune_does_not_fail_the_run(fake):
    env, state, log = fake
    docker = Path(env["PATH"].split(":")[0]) / "docker"
    docker.write_text(docker.read_text().replace('echo "$@" >> "$FAKE/log"', 'echo "$@" >> "$FAKE/log"; case "$*" in *prune*) exit 1;; esac'))
    done = _run(env, "--pull", FAKE_PULL="changed")
    assert done.returncode == 0 and "image prune failed" in done.stderr
    assert "--image-update updated" in _exec_line(log)


def test_every_demonstration_service_has_bounded_container_logs():
    """Docker's default log driver keeps logs without limit; an unattended host would fill its disk."""
    overlay = _load(CONTAINER / "docker-compose.demo.yml")["services"]
    base = _load(CONTAINER / "docker-compose.yml")["services"]
    for name in set(base) | {"caddy"}:
        logging = overlay[name]["logging"]
        assert logging["driver"] == "json-file", name
        assert logging["options"] == {"max-size": "10m", "max-file": "3"}, name
