"""Tests for the monitoring and scheduling files of the disaster-recovery tooling: that every metric an alert
rule reads is one the tools emit, that the alert unit tests pass under `promtool` when it is available, the
expected-interval metrics, the scheduler's CLI entry points, the host wrapper (`scripts/dr-scheduled.sh`) and
the systemd/cron/Compose files that wire them together.

The files live in the repository's `observability/` and `scripts/` directories, which sit next to `backend/` (or
are mounted at `/observability` and `/scripts` in the backup-image run); tests skip when they are absent.
Each test uses its own temporary directories.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from app.services import dr_backup
from app.services.dr_backup import BackupConfig, DestinationResult, RunReport, write_status
from app.services.dr_schedule import HEARTBEAT_FILENAME, heartbeat_text

_ROOT = Path(__file__).resolve().parents[2]
_RULES = _ROOT / "observability" / "alerts" / "disaster-recovery.rules.yml"
_RULE_TESTS = _ROOT / "observability" / "alerts" / "tests" / "disaster-recovery.test.yml"
_SCRIPTS = _ROOT / "scripts"
_BACKEND_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_WRAPPER = _SCRIPTS / "dr-scheduled.sh"
_SCHEDULE_DIR = _SCRIPTS / "schedule"

if not _RULES.is_file() or not _WRAPPER.is_file():
    pytest.skip("observability/ and scripts/ are not available in this environment", allow_module_level=True)

_HARNESS_SCRIPT = _SCRIPTS / "restore_test.py"
_spec = importlib.util.spec_from_file_location("restore_test_monitoring", _HARNESS_SCRIPT)
harness = importlib.util.module_from_spec(_spec)
sys.modules["restore_test_monitoring"] = harness
_spec.loader.exec_module(harness)

_METRIC = re.compile(r"\b(reqtrack_[a-z_]+|node_textfile_[a-z_]+)\b")
_EXTERNAL_METRICS = {"node_textfile_scrape_error"}
"""Metrics the rules read that the Alloy textfile collector produces rather than our tools."""


def _emitted_metric_names(tmp_path: Path) -> set[str]:
    """Every metric name the backup, its scheduler and the restore-test write."""
    report = RunReport(
        result="ok",
        set_id="s",
        started_at=datetime(2026, 5, 1, tzinfo=UTC),
        finished_at=datetime(2026, 5, 1, 0, 5, tzinfo=UTC),
        destinations=[DestinationResult("d", True)],
    )
    write_status(tmp_path, report, None)
    texts = [
        (tmp_path / "reqtrack-backup.prom").read_text(),
        heartbeat_text(datetime(2026, 5, 1, tzinfo=UTC), None, False, 86400),
        harness.prometheus_text(harness.Report(result="ok", finished_at="2026-05-01T00:00:00+00:00"), 0.0),
    ]
    return {name for text in texts for name in re.findall(r"^# TYPE (\S+) ", text, re.M)}


def _rule_metric_names() -> set[str]:
    document = yaml.safe_load(_RULES.read_text())
    return {name for group in document["groups"] for rule in group["rules"] for name in _METRIC.findall(rule["expr"])}


def test_every_metric_an_alert_reads_is_emitted_by_a_tool(tmp_path: Path):
    read = _rule_metric_names()
    assert read, "the rules read no reqtrack metric"
    missing = read - _emitted_metric_names(tmp_path) - _EXTERNAL_METRICS
    assert not missing, f"alert rules read metrics nothing emits: {sorted(missing)}"


def test_every_alert_has_a_severity_summary_and_description():
    document = yaml.safe_load(_RULES.read_text())
    for group in document["groups"]:
        for rule in group["rules"]:
            assert rule["labels"]["severity"] in {"critical", "warning"}, rule["alert"]
            assert rule["annotations"]["summary"] and rule["annotations"]["description"], rule["alert"]
            assert rule.get("for"), f"{rule['alert']} fires on a single bad sample"


def test_every_alert_has_a_unit_test():
    alerts = {rule["alert"] for group in yaml.safe_load(_RULES.read_text())["groups"] for rule in group["rules"]}
    tested = {case["alertname"] for test in yaml.safe_load(_RULE_TESTS.read_text())["tests"] for case in test["alert_rule_test"]}
    assert alerts - tested == set(), f"alerts with no unit test: {sorted(alerts - tested)}"


@pytest.mark.skipif(shutil.which("promtool") is None, reason="promtool is not installed (CI runs it from the prometheus image)")
def test_alert_rules_pass_promtool():
    for command in (["check", "rules", str(_RULES)], ["test", "rules", str(_RULE_TESTS)]):
        done = subprocess.run(["promtool", *command], capture_output=True, text=True, check=False)
        assert done.returncode == 0, done.stdout + done.stderr


# --- the interval metrics ----------------------------------------------------------------------------


def _report(ok: bool = True) -> RunReport:
    return RunReport(
        result="ok" if ok else "failed",
        set_id="s",
        started_at=datetime(2026, 5, 1, tzinfo=UTC),
        finished_at=datetime(2026, 5, 1, 0, 5, tzinfo=UTC),
    )


def test_the_backup_publishes_how_often_it_is_meant_to_run(tmp_path: Path):
    write_status(tmp_path, _report(), None, expected_interval_seconds=6 * 3600)
    assert "reqtrack_backup_expected_interval_seconds 21600" in (tmp_path / "reqtrack-backup.prom").read_text()
    write_status(tmp_path, _report(), None)
    assert "reqtrack_backup_expected_interval_seconds 86400" in (tmp_path / "reqtrack-backup.prom").read_text()


def test_an_empty_expected_interval_means_the_default(monkeypatch: pytest.MonkeyPatch):
    # Compose passes BACKUP_EXPECTED_INTERVAL_HOURS= when the operator leaves it unset.
    monkeypatch.setenv("BACKUP_EXPECTED_INTERVAL_HOURS", "")
    assert BackupConfig().expected_interval_hours == 24.0
    monkeypatch.setenv("BACKUP_EXPECTED_INTERVAL_HOURS", "6")
    assert BackupConfig().expected_interval_hours == 6.0


def test_the_restore_test_publishes_its_interval_and_writes_atomically(tmp_path: Path):
    report = harness.Report(result="ok", finished_at="2026-05-01T00:00:00+00:00")
    assert "reqtrack_restore_test_expected_interval_seconds 604800" in harness.prometheus_text(report, 0.0)
    assert "reqtrack_restore_test_expected_interval_seconds 2592000" in harness.prometheus_text(report, 0.0, expected_interval_hours=720)
    target = tmp_path / "nested" / "x.prom"
    harness.write_atomic(target, "a\n")
    harness.write_atomic(target, "b\n")
    assert target.read_text() == "b\n" and stat.S_IMODE(target.stat().st_mode) == 0o644
    assert [p.name for p in target.parent.iterdir()] == ["x.prom"]


# --- a backup that cannot start is still a recorded failure ------------------------------------------


def _config(tmp_path: Path) -> BackupConfig:
    return BackupConfig(staging_dir=tmp_path / "staging", status_dir=tmp_path / "status", repository=str(tmp_path / "repo"))


def test_a_backup_that_cannot_build_its_dependencies_is_recorded_as_failed(tmp_path: Path):
    config = _config(tmp_path)
    write_status(config.status_dir, _report(), None)  # an earlier success
    before = json.loads((config.status_dir / "status.json").read_text())["last_success_timestamp"]

    def unreachable(_: BackupConfig):
        raise ConnectionError("could not connect to http://storage:9000 with key AKIASECRET")

    report = dr_backup.run_backup_from_environment(config, unreachable)
    assert report.result == "failed" and report.step == "start"
    status = json.loads((config.status_dir / "status.json").read_text())
    assert status["result"] == "failed" and status["failed_step"] == "start" and status["last_success_timestamp"] == before
    assert "ConnectionError" in status["error"] and "AKIASECRET" not in json.dumps(status) and "9000" not in json.dumps(status)
    prom = (config.status_dir / "reqtrack-backup.prom").read_text()
    assert "reqtrack_backup_last_run_success 0" in prom and f"reqtrack_backup_last_success_timestamp_seconds {before:.0f}" in prom


def test_a_failed_start_with_another_run_in_progress_is_refused_not_recorded(tmp_path: Path):
    config = _config(tmp_path)
    with dr_backup.run_lock(config.staging_dir), pytest.raises(dr_backup.AlreadyRunning):
        dr_backup.run_backup_from_environment(config, lambda _: (_ for _ in ()).throw(ConnectionError("x")))
    assert not (config.status_dir / "status.json").exists()


def test_the_bundle_command_needs_neither_the_database_nor_the_object_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cli = _load_cli()
    seen: list[str] = []
    monkeypatch.setattr(cli, "write_bundle", lambda config, restic, recipient, output: seen.append(str(output)))
    monkeypatch.setattr(dr_backup, "deps_from_environment", lambda config: pytest.fail("bundle must not build database or storage dependencies"))
    monkeypatch.setenv("BACKUP_STATUS_DIR", str(tmp_path))
    assert cli.main(["bundle", "--output", str(tmp_path / "x.age"), "--recipient", "age1x"]) == 0
    assert seen == [str(tmp_path / "x.age")]


# --- the CLI entry points ----------------------------------------------------------------------------


def _load_cli():
    spec = importlib.util.spec_from_file_location("dr_backup_cli_for_tests", _BACKEND_SCRIPTS / "dr_backup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_health_reports_the_heartbeat_through_the_exit_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cli = _load_cli()
    monkeypatch.setenv("BACKUP_STATUS_DIR", str(tmp_path))
    assert cli.main(["health"]) == 1
    (tmp_path / HEARTBEAT_FILENAME).write_text(heartbeat_text(datetime.now(UTC), None, False, 86400))
    assert cli.main(["health"]) == 0


def test_schedule_without_a_usable_schedule_refuses_to_start(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch):
    cli = _load_cli()
    monkeypatch.delenv("BACKUP_SCHEDULE", raising=False)
    assert cli.main(["schedule"]) == 2
    assert "BACKUP_SCHEDULE is empty" in capsys.readouterr().err
    monkeypatch.setenv("BACKUP_SCHEDULE", "every 5h")
    assert cli.main(["schedule"]) == 2
    assert "divides 24" in capsys.readouterr().err


def test_the_scheduler_derives_the_expected_interval_unless_it_is_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli()

    class Stop(Exception):
        pass

    seen: list[tuple[float, float]] = []

    def fake_scheduler(schedule, settings, status_dir, run, last_success):
        seen.append((schedule.period_seconds, 0.0))
        raise Stop

    monkeypatch.setattr(cli, "Scheduler", fake_scheduler)
    monkeypatch.setenv("BACKUP_SCHEDULE", "every 6h")
    monkeypatch.setenv("BACKUP_STATUS_DIR", str(tmp_path))
    monkeypatch.setenv("BACKUP_EXPECTED_INTERVAL_HOURS", "")
    with pytest.raises(Stop):
        cli.main(["schedule"])
    assert seen == [(6 * 3600, 0.0)]


def test_the_scheduled_run_publishes_the_schedules_own_period(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli()
    configs: list[BackupConfig] = []

    def fake_run_backup(config):
        configs.append(config)
        return RunReport(result="ok", set_id="s")

    class RunOnce:
        def __init__(self, schedule, settings, status_dir, run, last_success):
            self._run = run

        def serve(self):
            self._run()

        def stop(self):
            pass

    monkeypatch.setattr(cli, "Scheduler", RunOnce)
    monkeypatch.setattr(cli, "run_backup_from_environment", fake_run_backup)
    monkeypatch.setenv("BACKUP_SCHEDULE", "every 6h")
    monkeypatch.setenv("BACKUP_STATUS_DIR", str(tmp_path))
    monkeypatch.setenv("BACKUP_EXPECTED_INTERVAL_HOURS", "")
    assert cli.main(["schedule"]) == 0
    assert configs[0].expected_interval_hours == 6.0
    configs.clear()
    monkeypatch.setenv("BACKUP_EXPECTED_INTERVAL_HOURS", "12")
    assert cli.main(["schedule"]) == 0
    assert configs[0].expected_interval_hours == 12.0


def test_a_scheduled_run_that_cannot_start_or_is_refused_never_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    cli = _load_cli()
    results: list[bool] = []

    class RunOnce:
        def __init__(self, schedule, settings, status_dir, run, last_success):
            self._run = run

        def serve(self):
            results.append(self._run())

        def stop(self):
            pass

    monkeypatch.setattr(cli, "Scheduler", RunOnce)
    monkeypatch.setenv("BACKUP_SCHEDULE", "02:30")
    monkeypatch.setenv("BACKUP_STATUS_DIR", str(tmp_path))

    def locked(config):
        raise dr_backup.AlreadyRunning("another backup is already running")

    def broken(config):
        raise RuntimeError("password=hunter2")

    monkeypatch.setattr(cli, "run_backup_from_environment", locked)
    assert cli.main(["schedule"]) == 0
    monkeypatch.setattr(cli, "run_backup_from_environment", broken)
    assert cli.main(["schedule"]) == 0
    assert results == [True, False]


# --- the host wrapper --------------------------------------------------------------------------------


def _wrapper_sandbox(tmp_path: Path) -> Path:
    """A copy of the wrapper next to stub `dr-backup.sh` and `restore-test.sh` that record their arguments."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(_WRAPPER, root / "scripts" / "dr-scheduled.sh")
    for name in ("dr-backup.sh", "restore-test.sh"):
        stub = root / "scripts" / name
        stub.write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" "$0" "$@" > "$STUB_OUT"\nenv | grep -E "^(BACKUP_|RESTORE_TEST_)" | sort >> "$STUB_OUT"\n'
        )
        stub.chmod(0o755)
    return root


def _run_wrapper(root: Path, args: list[str], env_file: str | None, extra_env: dict[str, str] | None = None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("BACKUP_", "RESTORE_TEST_", "REQTRACK_"))}
    env.update({"STUB_OUT": str(root / "out.txt"), "REQTRACK_DR_ENV": str(root / "dr.env")})
    env.update(extra_env or {})
    if env_file is not None:
        (root / "dr.env").write_text(env_file)
    return subprocess.run(["bash", str(root / "scripts" / "dr-scheduled.sh"), *args], capture_output=True, text=True, env=env, check=False)


def test_the_wrapper_runs_a_backup_with_settings_from_the_env_file(tmp_path: Path):
    root = _wrapper_sandbox(tmp_path)
    done = _run_wrapper(root, ["backup"], '# comment\n\nBACKUP_REPO_PASSWORD_FILE=/secure/pw\nBACKUP_SECRETS_MODE="none"\n')
    assert done.returncode == 0, done.stderr
    out = (root / "out.txt").read_text()
    assert out.splitlines()[1] == "run" and "BACKUP_SECRETS_MODE=none" in out and "BACKUP_REPO_PASSWORD_FILE=/secure/pw" in out


def test_the_wrapper_reads_the_env_file_without_executing_it(tmp_path: Path):
    root = _wrapper_sandbox(tmp_path)
    marker = root / "executed"
    done = _run_wrapper(root, ["backup"], f"BACKUP_REPO_PASSWORD_FILE=/pw\nBACKUP_X=$(touch {marker})\n; touch {marker}\n`touch {marker}`\n")
    assert done.returncode == 0, done.stderr
    assert not marker.exists()
    assert f"BACKUP_X=$(touch {marker})" in (root / "out.txt").read_text()


def test_the_wrapper_refuses_without_the_password_file(tmp_path: Path):
    root = _wrapper_sandbox(tmp_path)
    done = _run_wrapper(root, ["backup"], "")
    assert done.returncode == 2 and "BACKUP_REPO_PASSWORD_FILE is not set" in done.stderr
    assert not (root / "out.txt").exists()


def test_the_wrapper_builds_the_restore_test_command(tmp_path: Path):
    root = _wrapper_sandbox(tmp_path)
    settings = (
        "BACKUP_REPO_PASSWORD_FILE=/secure/pw\nBACKUP_STATUS_VOLUME=/var/lib/reqtrack/status\n"
        "RESTORE_TEST_SOURCE_ENV=/secure/.env\nRESTORE_TEST_ARGS=--repository sftp:b@h:/srv --check-subset 10%\n"
    )
    done = _run_wrapper(root, ["restore-test"], settings)
    assert done.returncode == 0, done.stderr
    args = (root / "out.txt").read_text().splitlines()[1:]
    joined = " ".join(args)
    assert "--repository-volume reqtrack_backup_repo" in joined and "--password-file /secure/pw" in joined
    assert "--source-env /secure/.env" in joined and "--status-dir /var/lib/reqtrack/status" in joined
    assert "--output /var/log/reqtrack/restore-test-reports" in joined
    assert "--repository sftp:b@h:/srv --check-subset 10%" in joined


@pytest.mark.parametrize(
    "missing,message",
    [("RESTORE_TEST_SOURCE_ENV", "RESTORE_TEST_SOURCE_ENV is not set"), ("BACKUP_STATUS_VOLUME", "BACKUP_STATUS_VOLUME is not set")],
)
def test_the_restore_test_wrapper_names_a_missing_setting(tmp_path: Path, missing: str, message: str):
    root = _wrapper_sandbox(tmp_path)
    settings = {"BACKUP_REPO_PASSWORD_FILE": "/pw", "BACKUP_STATUS_VOLUME": "/var/lib/s", "RESTORE_TEST_SOURCE_ENV": "/e"}
    del settings[missing]
    done = _run_wrapper(root, ["restore-test"], "".join(f"{k}={v}\n" for k, v in settings.items()))
    assert done.returncode == 2 and message in done.stderr


def test_the_restore_test_wrapper_refuses_a_named_status_volume(tmp_path: Path):
    root = _wrapper_sandbox(tmp_path)
    done = _run_wrapper(
        root, ["restore-test"], "BACKUP_REPO_PASSWORD_FILE=/pw\nRESTORE_TEST_SOURCE_ENV=/e\nBACKUP_STATUS_VOLUME=reqtrack_backup_status\n"
    )
    assert done.returncode == 2 and "absolute host directory" in done.stderr


def test_the_wrapper_rejects_an_unknown_job(tmp_path: Path):
    root = _wrapper_sandbox(tmp_path)
    assert _run_wrapper(root, ["nonsense"], "BACKUP_REPO_PASSWORD_FILE=/pw\n").returncode == 2
    assert _run_wrapper(root, [], "").returncode == 2


# --- the schedule files and Compose wiring -----------------------------------------------------------


def _unit(path: Path) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current = ""
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            current = line.strip("[]")
            sections[current] = {}
        else:
            key, _, value = line.partition("=")
            sections[current][key] = value
    return sections


@pytest.mark.parametrize("job", ["backup", "restore-test"])
def test_each_timer_triggers_its_service_which_runs_the_wrapper(job: str):
    timer = _unit(_SCHEDULE_DIR / f"reqtrack-{job}.timer")
    service = _unit(_SCHEDULE_DIR / f"reqtrack-{job}.service")
    assert timer["Timer"]["Unit"] == f"reqtrack-{job}.service" and timer["Timer"]["Persistent"] == "true"
    assert timer["Timer"]["OnCalendar"] and timer["Install"]["WantedBy"] == "timers.target"
    assert service["Service"]["Type"] == "oneshot"
    assert service["Service"]["ExecStart"].endswith(f"scripts/dr-scheduled.sh {job}")
    assert service["Service"]["SuccessExitStatus"] == "75"


def test_the_restore_test_runs_weekly_and_after_the_nightly_backup():
    backup = _unit(_SCHEDULE_DIR / "reqtrack-backup.timer")["Timer"]["OnCalendar"]
    restore = _unit(_SCHEDULE_DIR / "reqtrack-restore-test.timer")["Timer"]["OnCalendar"]
    assert restore.startswith("Sun ") and "04:00" in restore and "02:30" in backup


def test_the_crontab_example_calls_the_wrapper_for_both_jobs():
    lines = [line for line in (_SCHEDULE_DIR / "crontab.example").read_text().splitlines() if line and not line.startswith("#")]
    jobs = [line for line in lines if "dr-scheduled.sh" in line]
    assert len(jobs) == 2 and any(" backup " in line for line in jobs) and any(" restore-test " in line for line in jobs)
    assert any(line.startswith("PATH=") for line in lines), "cron's own PATH does not include docker"


def test_backup_may_use_a_read_only_storage_identity_but_restore_never_does():
    compose = yaml.safe_load((_ROOT / "docker-compose.yml").read_text())["services"]
    backup, restore = compose["backup"]["environment"], compose["restore"]["environment"]
    assert backup["STORAGE_S3_ACCESS_KEY"].startswith("${BACKUP_STORAGE_ACCESS_KEY:-")
    assert backup["STORAGE_S3_SECRET_KEY"].startswith("${BACKUP_STORAGE_SECRET_KEY:-")
    # A restore puts objects back: it is pinned to the application's pair whatever the backup uses.
    assert "BACKUP_STORAGE" not in restore["STORAGE_S3_ACCESS_KEY"] + restore["STORAGE_S3_SECRET_KEY"]
    assert compose["backup-scheduler"]["extends"]["service"] == "backup"


def test_compose_wires_the_scheduler_status_volume_and_metric_pipeline():
    compose = yaml.safe_load((_ROOT / "docker-compose.yml").read_text())["services"]
    scheduler = compose["backup-scheduler"]
    assert scheduler["extends"]["service"] == "backup" and scheduler["command"] == ["schedule"]
    assert scheduler["profiles"] == ["backup-schedule"] and scheduler["restart"] == "unless-stopped"
    assert scheduler["healthcheck"]["test"][-1] == "health"
    status_mount = "${BACKUP_STATUS_VOLUME:-reqtrack_backup_status}:/backup/status"
    assert status_mount in compose["backup"]["volumes"]
    assert status_mount + ":ro" in compose["alloy"]["volumes"]
    assert "--web.enable-remote-write-receiver" in compose["prometheus"]["command"]
    assert "./observability/alerts:/etc/prometheus/alerts:ro" in compose["prometheus"]["volumes"]
    assert (_ROOT / "observability" / "prometheus.yml").read_text().count("/etc/prometheus/alerts/*.rules.yml") == 1
    alloy = (_ROOT / "observability" / "alloy.river").read_text()
    assert 'directory = "/backup/status"' in alloy and "prometheus.remote_write" in alloy and 'set_collectors = ["textfile"]' in alloy
