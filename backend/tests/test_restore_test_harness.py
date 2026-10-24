"""Tests for the restore-test harness (`scripts/restore_test.py`): how it builds the scratch stack's environment
(generated credentials, nothing taken from production beyond a short list), how it decides pass and fail, that
an injected fault passes only when it is caught, and that no secret reaches a report.

The harness drives `docker compose`; these tests replace the process runner with a scripted fake, so they need
no Docker. The real thing is exercised end to end by `scripts/restore-test-selfcheck.sh`. The script lives in
the repository's `scripts/` directory, which exists next to `backend/` (or is mounted at `/scripts` in the
backup-image test run); the tests skip when it is absent.
"""

from __future__ import annotations

import importlib.util
import io
import itertools
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "restore_test.py"
if not _SCRIPT.is_file():
    pytest.skip("scripts/restore_test.py is not available in this environment", allow_module_level=True)

_spec = importlib.util.spec_from_file_location("restore_test_harness", _SCRIPT)
harness = importlib.util.module_from_spec(_spec)
sys.modules["restore_test_harness"] = harness
_spec.loader.exec_module(harness)


def _generator():
    """A fresh source of distinct, recognisable secrets (the first one is the scratch database password)."""
    counter = itertools.count()
    return lambda: f"generated-secret-{next(counter)}"


def _generate() -> str:
    return _generator()()


def _manifest(encrypted: dict | None = None, backend: str = "s3", tag: str | None = "v1.2.3") -> dict:
    return {
        "set_id": "20261024T020000Z",
        "app": {"version": "1", "git_sha": "abc", "image_tag": tag},
        "storage_backend": backend,
        "secrets_mode": "config",
        "stats": {
            "tables": {"users": 3, "audit_events": 5, "alembic_version": 1},
            "business": {"users": {"total": 3}, "projects": 2},
            "probes": {"encrypted_columns": encrypted if encrypted is not None else {"users.totp_secret": {"rows": 2, "undecryptable": 0}}},
        },
    }


def _verify_report(failed: tuple[str, ...] = ()) -> dict:
    names = ["migrations", "statistics", "file-objects", "encrypted-columns", "email-disabled", "api-smoke"]
    return {
        "result": "failed" if failed else "ok",
        "checks": [{"name": n, "ok": n not in failed, "detail": f"{n} detail", "data": {}} for n in names],
    }


class FakeDocker:
    """A scripted stand-in for `subprocess.run`: answers each docker command the harness issues and records it."""

    def __init__(
        self,
        manifest: dict,
        *,
        verify: dict | None = None,
        restore_rc: int = 0,
        restore_report: dict | None = None,
        check_rc: int = 0,
        fault_ok: bool = True,
    ):
        self.manifest, self.verify = manifest, verify or _verify_report()
        self.restore_rc = restore_rc
        self.restore_report = restore_report if restore_report is not None else {"result": "ok", "step": "done", "objects_restored": 3}
        self.check_rc, self.fault_ok = check_rc, fault_ok
        self.calls: list[list[str]] = []
        self.env_files: list[str] = []
        self.verify_requests: list[dict] = []

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        if "--env-file" in argv and not self.env_files:
            self.env_files.append(argv[argv.index("--env-file") + 1])
        done = lambda rc=0, out="", err="": subprocess.CompletedProcess(argv, rc, out, err)  # noqa: E731
        if argv[:3] == ["docker", "volume", "ls"]:
            return done(out="")
        if argv[:2] == ["docker", "compose"]:
            verb = argv[argv.index("--profile") + 2]
            rest = argv[argv.index("--profile") + 2 :]
            if verb == "run" and "--entrypoint" in rest and "cat" in rest:
                return done(out=json.dumps(self.restore_report))
            if verb == "run" and "--entrypoint" in rest and "python" in rest:
                return done(rc=0 if self.fault_ok else 3)
            if verb == "run":
                sub = rest[rest.index("restore") + 1 :]
                if sub[0] == "check":
                    return done(rc=self.check_rc, err="" if self.check_rc == 0 else "pack damaged")
                if sub[0] == "manifest":
                    return done(out=json.dumps(self.manifest))
                if sub[0] == "restore":
                    return done(rc=self.restore_rc, err="")
            if verb == "exec" and any("dr_verify.py" in arg for arg in rest):
                self.verify_requests.append(json.loads(kwargs.get("input") or "{}"))
                return done(rc=0 if self.verify["result"] == "ok" else 1, out=json.dumps(self.verify))
            if verb == "exec":  # psql
                if "ON_ERROR_STOP=1" in rest and "pg_class" in " ".join(rest):
                    return done(out="audit_events\nusers\nalembic_version\n")
                if "must_reset_credentials" in " ".join(rest):
                    return done(out="UPDATE 1\n")
                return done()
            return done()
        return done()


@pytest.fixture
def password_file(tmp_path) -> Path:
    path = tmp_path / "repo-password"
    path.write_text("repo-password-value")
    return path


def _options(tmp_path, password_file, **overrides):
    values = dict(
        repository_volume="source_reqtrack_backup_repo",
        password_file=password_file,
        output_dir=tmp_path / "out",
        status_dir=tmp_path / "status",
        compose_dir=tmp_path,
    )
    values.update(overrides)
    return harness.Options(**values)


def _run(fake, options, monkeypatch, *, key="original-encryption-key"):
    """Runs the harness against the fake and returns `(harness, exit status)`."""
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", key)
    test = harness.RestoreTest(
        options, runner=fake, now=lambda: datetime(2026, 10, 24, 2, 0, tzinfo=UTC), generate=_generator(), stdout=io.StringIO()
    )
    return test, test.run()


def _report(tmp_path) -> dict:
    (path,) = list((tmp_path / "out").glob("*/report.json"))
    return json.loads(path.read_text())


# --- pure helpers -------------------------------------------------------------------------------------


def test_env_text_is_parsed_like_the_stacks_dotenv():
    parsed = harness.parse_env_text("# comment\n\nA=1\nB = 'two words'\nC=\"3\"\nnot a pair\nD=x=y\n")
    assert parsed == {"A": "1", "B": "two words", "C": "3", "D": "x=y"}


def test_project_names_are_time_ordered_and_prefixed():
    name = harness.new_project_name(datetime(2026, 10, 24, 2, 5, 9, tzinfo=UTC))
    assert name == "reqtrack-drtest-20261024t020509z"
    assert re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name)


def test_scratch_environment_never_copies_production_credentials(password_file):
    operator = {
        "APP_SECRET_ENCRYPTION_KEY": "original-key",
        "POSTGRES_PASSWORD": "PRODUCTION-DB-PASSWORD",
        "JWT_SECRET": "PRODUCTION-JWT",
        "SERVER_ADMIN_PASSWORD": "PRODUCTION-ADMIN",
        "STORAGE_SECRET_KEY": "PRODUCTION-STORAGE",
        "SMTP_PASSWORD": "PRODUCTION-SMTP",
        "IMAGE_TAG": "v1",
    }
    env = harness.scratch_environment(
        passthrough=operator, key_mode="correct", manifest_backend="s3", image_tag=None, password_file=password_file, generate=_generate
    )
    assert env["APP_SECRET_ENCRYPTION_KEY"] == "original-key"
    assert env["IMAGE_TAG"] == "v1" and env["STORAGE_BACKEND"] == "s3"
    assert not any("PRODUCTION" in value for value in env.values())
    assert "SMTP_PASSWORD" not in env
    assert env["SMTP_HOST"].endswith(".invalid")
    assert env["BACKUP_REPOSITORY_READ_ONLY"] == "true" and env["BACKUP_SECRETS_MODE"] == "none"


def test_a_wrong_key_run_replaces_the_key_and_a_correct_run_needs_one(password_file):
    env = harness.scratch_environment(
        passthrough={"APP_SECRET_ENCRYPTION_KEY": "original"},
        key_mode="wrong",
        manifest_backend=None,
        image_tag="pinned",
        password_file=password_file,
        generate=_generate,
    )
    assert env["APP_SECRET_ENCRYPTION_KEY"].startswith("generated-secret-") and env["IMAGE_TAG"] == "pinned"
    with pytest.raises(harness.HarnessError) as error:
        harness.scratch_environment(
            passthrough={}, key_mode="correct", manifest_backend=None, image_tag=None, password_file=password_file, generate=_generate
        )
    assert error.value.code == 2 and "APP_SECRET_ENCRYPTION_KEY" in str(error.value)


@pytest.mark.parametrize("bad", ["two\nlines", 'has"quote', "has'quote", "has$dollar"])
def test_env_file_refuses_values_it_cannot_carry(bad):
    with pytest.raises(harness.HarnessError):
        harness.render_env_file({"KEY": bad})


def test_repository_is_mounted_read_only_as_a_volume_or_a_path():
    named = harness.render_repository_override("prod_reqtrack_backup_repo", named_volume=True)
    assert "type: volume" in named and "read_only: true" in named and "external: true" in named
    assert 'name: "prod_reqtrack_backup_repo"' in named and named.count("target: /backup/repo") == 2
    path = harness.render_repository_override("/mnt/nfs/repo", named_volume=False)
    assert "type: bind" in path and 'source: "/mnt/nfs/repo"' in path and "external" not in path


def test_prometheus_text_carries_the_last_success_forward_on_failure():
    report = harness.Report(result="failed", finished_at="2026-10-24T02:00:00+00:00", duration_seconds=12.5, failed=["statistics"])
    text = harness.prometheus_text(report, previous_success=1_700_000_000.0)
    assert "reqtrack_restore_test_last_run_success 0" in text
    assert "reqtrack_restore_test_last_success_timestamp_seconds 1700000000" in text
    assert "reqtrack_restore_test_failed_checks 1" in text
    ok = harness.prometheus_text(harness.Report(result="ok", finished_at="2026-10-24T02:00:00+00:00"), previous_success=5.0)
    assert "reqtrack_restore_test_last_success_timestamp_seconds 1792807200" in ok


def test_unreadable_columns_are_parsed_and_compared_with_what_the_set_holds():
    message = "the configured key cannot decrypt: users.totp_secret (2), organizations.smtp_password (1). Supply the original key"
    assert harness.unreadable_columns(message) == {"users.totp_secret": 2, "organizations.smtp_password": 1}
    manifest = _manifest({"users.totp_secret": {"rows": 2, "undecryptable": 0}, "organizations.oidc_client_secret": {"rows": 0, "undecryptable": 0}})
    assert harness.expected_unreadable_columns(manifest) == {"users.totp_secret": 2}


def test_redaction_masks_every_secret_in_output():
    docker = harness.Docker("p", Path("."), [], Path("env"), ["s3cr3t", ""], runner=lambda *a, **k: None)
    assert docker.redact("password=s3cr3t and again s3cr3t") == "password=*** and again ***"
    docker.mask("later")
    assert docker.redact("a later b") == "a *** b"


# --- whole runs, with a scripted docker ---------------------------------------------------------------


def test_a_passing_run_exits_zero_cleans_up_and_writes_the_reports(tmp_path, password_file, monkeypatch):
    fake = FakeDocker(_manifest())
    test, code = _run(fake, _options(tmp_path, password_file), monkeypatch)
    assert code == 0
    report = _report(tmp_path)
    assert report["result"] == "ok" and report["set_id"] == "20261024T020000Z"
    assert [s["name"] for s in report["steps"]] == ["repository-check", "manifest", "scratch-stack", "restore", "application", "verify", "teardown"]
    assert any(call[:3] == ["docker", "compose", "-p"] and "down" in call and "--volumes" in call for call in fake.calls)
    assert not Path(fake.env_files[0]).exists(), "the private scratch directory must be removed"
    status = json.loads((tmp_path / "status" / "restore-test-status.json").read_text())
    assert status["result"] == "ok" and status["last_success_timestamp"] > 0
    assert "reqtrack_restore_test_last_run_success 1" in (tmp_path / "status" / "reqtrack-restore-test.prom").read_text()


def test_the_scratch_stack_takes_its_storage_backend_and_image_from_the_set(tmp_path, password_file, monkeypatch):
    fake = FakeDocker(_manifest(backend="local", tag="v9.9.9"))
    captured = {}
    original = harness.RestoreTest._start_services

    def spy(self, services, step):
        captured.setdefault("env", (self._work / "scratch.env").read_text())
        return original(self, services, step)

    monkeypatch.setattr(harness.RestoreTest, "_start_services", spy)
    _run(fake, _options(tmp_path, password_file), monkeypatch)
    assert "STORAGE_BACKEND=local" in captured["env"] and "IMAGE_TAG=v9.9.9" in captured["env"]


def test_no_secret_reaches_a_report_or_the_output(tmp_path, password_file, monkeypatch):
    fake = FakeDocker(
        _manifest(), restore_rc=1, restore_report={"result": "failed", "step": "verify", "error": "boom generated-secret-0 original-encryption-key"}
    )
    _run(fake, _options(tmp_path, password_file), monkeypatch, key="original-encryption-key")
    text = "".join(p.read_text() for p in (tmp_path / "out").rglob("*") if p.is_file())
    assert "original-encryption-key" not in text
    assert not re.search(r"generated-secret-\d+", text)
    assert "***" in text


def test_cleared_secrets_allow_exactly_one_audit_event_in_the_statistics(tmp_path, password_file, monkeypatch):
    fake = FakeDocker(
        _manifest(), restore_report={"result": "ok", "step": "done", "objects_restored": 3, "secrets_cleared": {"users.totp_secret": 2}}
    )
    _run(fake, _options(tmp_path, password_file, clear_unreadable_secrets=True), monkeypatch)
    verify = next(call for call in fake.calls if any("dr_verify.py" in arg for arg in call))
    assert verify[verify.index("--extra-rows") + 1] == "audit_events=1" and "--allow-unreadable-secrets" in verify
    plain = FakeDocker(_manifest())
    _run(plain, _options(tmp_path / "b", password_file), monkeypatch)
    assert "--extra-rows" not in next(call for call in plain.calls if any("dr_verify.py" in arg for arg in call))


def test_a_forced_reset_run_restores_with_the_flag_and_asks_for_the_recovery_check(tmp_path, password_file, monkeypatch):
    login_file = tmp_path / "login-password"
    login_file.write_text("a-password")
    fake = FakeDocker(
        _manifest(),
        restore_report={"result": "ok", "step": "done", "objects_restored": 3, "credentials_reset": {"marked": 2}},
    )
    _run(
        fake,
        _options(tmp_path, password_file, force_reset="all", reset_2fa=True, login_email="a@example.com", login_password_file=login_file),
        monkeypatch,
    )
    restore = next(call for call in fake.calls if "restore" in call and "fresh" in call)
    assert restore[restore.index("--force-reset") + 1] == "all" and "--reset-2fa" in restore
    request = fake.verify_requests[0]
    assert request["credential_reset"] is True and "login" not in request, "restored passwords are unusable by design"
    verify = next(call for call in fake.calls if any("dr_verify.py" in arg for arg in call))
    assert verify[verify.index("--extra-rows") + 1] == "audit_events=1"


def test_clearing_and_a_forced_reset_each_allow_their_own_audit_event(tmp_path, password_file, monkeypatch):
    fake = FakeDocker(
        _manifest(),
        restore_report={
            "result": "ok", "step": "done", "objects_restored": 3,
            "secrets_cleared": {"users.totp_secret": 2}, "credentials_reset": {"marked": 2},
        },
    )
    _run(fake, _options(tmp_path, password_file, clear_unreadable_secrets=True, force_reset="all"), monkeypatch)
    verify = next(call for call in fake.calls if any("dr_verify.py" in arg for arg in call))
    assert verify[verify.index("--extra-rows") + 1] == "audit_events=2"


def test_a_plain_run_does_not_ask_for_the_recovery_check(tmp_path, password_file, monkeypatch):
    fake = FakeDocker(_manifest())
    _run(fake, _options(tmp_path, password_file), monkeypatch)
    assert "credential_reset" not in fake.verify_requests[0]


def test_an_unmarked_account_that_the_recovery_check_catches_passes_the_self_test(tmp_path, password_file, monkeypatch):
    verify = _verify_report()
    verify["checks"].append({"name": "credential-recovery", "ok": False, "detail": "1 of 2 local accounts are not marked", "data": {}})
    verify["result"] = "failed"
    fake = FakeDocker(_manifest(), verify=verify)
    _, code = _run(fake, _options(tmp_path, password_file, inject="unmarked-account"), monkeypatch)
    assert code == 0 and _report(tmp_path)["fault_detected"] is True
    restore = next(call for call in fake.calls if "restore" in call and "fresh" in call)
    assert "--force-reset" in restore, "the fault damages a forced reset, so one is applied"
    assert any("must_reset_credentials" in " ".join(call) for call in fake.calls)


def test_an_unmarked_account_that_nothing_notices_fails_the_self_test(tmp_path, password_file, monkeypatch):
    _, code = _run(FakeDocker(_manifest()), _options(tmp_path, password_file, inject="unmarked-account"), monkeypatch)
    assert code == 1 and _report(tmp_path)["fault_detected"] is False


def test_a_failed_check_fails_the_run_and_keeps_the_last_success_time(tmp_path, password_file, monkeypatch):
    (tmp_path / "status").mkdir()
    (tmp_path / "status" / "restore-test-status.json").write_text(json.dumps({"last_success_timestamp": 1_700_000_000.0}))
    fake = FakeDocker(_manifest(), verify=_verify_report(failed=("statistics",)))
    _, code = _run(fake, _options(tmp_path, password_file), monkeypatch)
    assert code == 1
    report = _report(tmp_path)
    assert report["result"] == "failed" and "statistics" in report["failed"]
    prom = (tmp_path / "status" / "reqtrack-restore-test.prom").read_text()
    assert "reqtrack_restore_test_last_run_success 0" in prom
    assert "reqtrack_restore_test_last_success_timestamp_seconds 1700000000" in prom


def test_a_failed_restore_stops_before_the_application_starts(tmp_path, password_file, monkeypatch):
    fake = FakeDocker(_manifest(), restore_rc=1, restore_report={"result": "failed", "step": "verify", "error": "3 statistics differ"})
    _, code = _run(fake, _options(tmp_path, password_file), monkeypatch)
    assert code == 1
    names = [s["name"] for s in _report(tmp_path)["steps"]]
    assert "restore" in names and "application" not in names and names[-1] == "teardown"
    assert _report(tmp_path)["restore"]["error"] == "3 statistics differ"


def test_a_failed_repository_check_stops_the_run(tmp_path, password_file, monkeypatch):
    _, code = _run(FakeDocker(_manifest(), check_rc=1), _options(tmp_path, password_file), monkeypatch)
    assert code == 1
    assert [s["name"] for s in _report(tmp_path)["steps"]][:2] == ["repository-check", "teardown"]


def test_a_running_backup_is_reported_with_its_own_exit_status(tmp_path, password_file, monkeypatch):
    class Busy(FakeDocker):
        def __call__(self, argv, **kwargs):
            if "restore" in argv and "fresh" in argv:
                self.calls.append(list(argv))
                return subprocess.CompletedProcess(argv, harness.EX_TEMPFAIL, "", "a backup is running")
            return super().__call__(argv, **kwargs)

    _, code = _run(Busy(_manifest()), _options(tmp_path, password_file), monkeypatch)
    assert code == harness.EX_TEMPFAIL


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"password_file": None}, "password file"),
        ({"repository_volume": None}, "name the repository"),
        ({"key_mode": "bogus"}, "--key-mode"),
        ({"inject": "nonsense"}, "unknown fault"),
    ],
)
def test_unusable_arguments_exit_two_without_touching_docker(tmp_path, password_file, monkeypatch, kwargs, message):
    fake = FakeDocker(_manifest())
    options = _options(tmp_path, password_file)
    for key, value in kwargs.items():
        setattr(options, key, value)
    _, code = _run(fake, options, monkeypatch)
    assert code == 2 and message in json.dumps(_report(tmp_path))
    assert not any("up" in call for call in fake.calls)


def test_a_correct_key_run_without_a_key_exits_two(tmp_path, password_file, monkeypatch):
    monkeypatch.delenv("APP_SECRET_ENCRYPTION_KEY", raising=False)
    test = harness.RestoreTest(_options(tmp_path, password_file), runner=FakeDocker(_manifest()), generate=_generate, stdout=io.StringIO())
    assert test.run() == 2


# --- the self-test: an injected fault passes only when it is caught ------------------------------------


def test_a_deleted_row_that_the_statistics_catch_passes_the_self_test(tmp_path, password_file, monkeypatch):
    fake = FakeDocker(_manifest(), verify=_verify_report(failed=("statistics",)))
    _, code = _run(fake, _options(tmp_path, password_file, inject="delete-row"), monkeypatch)
    assert code == 0
    report = _report(tmp_path)
    assert report["fault_detected"] is True and report["inject"] == "delete-row"
    assert any("DELETE" in " ".join(call) for call in fake.calls)
    assert not (tmp_path / "status").exists(), "a self-test must never write success metrics"


def test_a_deleted_row_that_nothing_notices_fails_the_self_test(tmp_path, password_file, monkeypatch):
    _, code = _run(FakeDocker(_manifest()), _options(tmp_path, password_file, inject="delete-row"), monkeypatch)
    assert code == 1 and _report(tmp_path)["fault_detected"] is False


def test_a_deleted_object_is_caught_by_the_file_check_only(tmp_path, password_file, monkeypatch):
    _, caught = _run(
        FakeDocker(_manifest(), verify=_verify_report(failed=("file-objects",))),
        _options(tmp_path, password_file, inject="delete-object"),
        monkeypatch,
    )
    assert caught == 0
    _, wrong_check = _run(
        FakeDocker(_manifest(), verify=_verify_report(failed=("api-smoke",))),
        _options(tmp_path / "b", password_file, inject="delete-object"),
        monkeypatch,
    )
    assert wrong_check == 1


def test_a_fault_that_cannot_be_applied_proves_nothing(tmp_path, password_file, monkeypatch):
    fake = FakeDocker(_manifest(), verify=_verify_report(failed=("file-objects",)), fault_ok=False)
    _, code = _run(fake, _options(tmp_path, password_file, inject="delete-object"), monkeypatch)
    assert code == 1 and _report(tmp_path)["fault_detected"] is False


def test_a_wrong_key_must_be_reported_with_exactly_the_unreadable_columns(tmp_path, password_file, monkeypatch):
    error = "the configured APP_SECRET_ENCRYPTION_KEY cannot decrypt: users.totp_secret (2). Supply the original key"
    exact = FakeDocker(_manifest(), restore_rc=1, restore_report={"result": "failed", "step": "verify", "error": error})
    _, code = _run(exact, _options(tmp_path, password_file, inject="wrong-key"), monkeypatch)
    assert code == 0
    vague = FakeDocker(
        _manifest(), restore_rc=1, restore_report={"result": "failed", "step": "verify", "error": "cannot decrypt: users.totp_secret (1)"}
    )
    _, code = _run(vague, _options(tmp_path / "b", password_file, inject="wrong-key"), monkeypatch)
    assert code == 1


def test_a_wrong_key_that_the_restore_accepts_fails_the_self_test(tmp_path, password_file, monkeypatch):
    _, code = _run(FakeDocker(_manifest()), _options(tmp_path, password_file, inject="wrong-key"), monkeypatch)
    assert code == 1


def test_an_unreadable_repository_is_not_mistaken_for_a_damaged_one(tmp_path, password_file, monkeypatch):
    class Denied(FakeDocker):
        def __call__(self, argv, **kwargs):
            if "check" in argv and "restore" in argv:
                self.calls.append(list(argv))
                return subprocess.CompletedProcess(argv, 1, "", "Fatal: open /backup/repo/keys: permission denied")
            return super().__call__(argv, **kwargs)

    _, code = _run(Denied(_manifest()), _options(tmp_path, password_file, inject="corrupt-dump"), monkeypatch)
    assert code == 1 and _report(tmp_path)["fault_detected"] is False


def test_a_damaged_repository_must_fail_the_check_or_the_restore(tmp_path, password_file, monkeypatch):
    _, by_check = _run(FakeDocker(_manifest(), check_rc=1), _options(tmp_path, password_file, inject="corrupt-dump"), monkeypatch)
    assert by_check == 0
    _, by_restore = _run(
        FakeDocker(_manifest(), restore_rc=1, restore_report={"result": "failed", "step": "download", "error": "bad blob"}),
        _options(tmp_path / "b", password_file, inject="corrupt-dump"),
        monkeypatch,
    )
    assert by_restore == 0
    _, unnoticed = _run(FakeDocker(_manifest()), _options(tmp_path / "c", password_file, inject="corrupt-dump"), monkeypatch)
    assert unnoticed == 1
