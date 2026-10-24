#!/usr/bin/env python3
"""
Module: scripts.restore_test

The disaster-recovery restore-test: proves a backup set restores into a working platform whose numbers match
the source, on a throwaway Docker Compose project that cannot touch or reach the real deployment. Run it
through `scripts/restore-test.sh`.

Responsibilities:
- Check the repository (`restic check` with a data sample) and read the chosen set's manifest.
- Start an isolated Compose project (`reqtrack-drtest-<UTC time>`, its own volumes and network, no published
  ports, email delivery disabled, throwaway credentials) and restore the set into it with the real restore tool.
- Start the application on the restored data and run the post-restore checks inside it
  (`backend/scripts/dr_verify.py`): migrations, statistics, stored objects, encrypted columns, email, API.
- Write `report.json` and `report.md`, a status file and a Prometheus textfile, and tear the project down
  (unless `--keep`), never leaving the scratch credentials, volumes or containers behind.
- Prove the checks bite: `--inject FAULT` damages the restored copy (or the repository, or the key) and
  succeeds only when the harness catches it.

Design decisions:
- Host-side Python using only the standard library, because it must drive `docker compose` (the backup and
  restore tools stay free of the Docker socket). Everything that needs the application's code runs in the
  scratch containers.
- The repository is mounted read-only into the scratch project (restic reads take no lock), so a bug in a
  test cannot change the backups it is testing. An off-site copy is read with `--repository`.
- Credentials for the scratch stack are generated per run into a private (0700) directory that is removed at
  the end; the production `.env` is never read except for the keys listed in `PASSTHROUGH_KEYS` (and only from
  a file named with `--source-env`). `APP_SECRET_ENCRYPTION_KEY` comes from the operator (`--key-mode
  correct`) or is a fresh random one (`wrong`), because the key is the one input a restore cannot invent.
- Output shown to a person and written to reports is redacted of every generated or supplied secret and carries
  counts and names only.
- A run with `--inject` never writes success metrics, and its exit status means "the fault was detected".
- Exit status: 0 passed (or, with `--inject`, the fault was caught), 1 a check failed (or the fault went
  unnoticed), 2 unusable arguments or environment, 75 another backup or restore is running.

Dependencies: Docker with the Compose plugin, the `backup` and `backend` images, the repository password file.
Python 3.9 or newer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.restore-test.yml")
PROJECT_PREFIX = "reqtrack-drtest-"
FAULTS = ("delete-row", "delete-object", "wrong-key", "corrupt-dump")
KEY_MODES = ("correct", "wrong")
EX_TEMPFAIL = 75
REPOSITORY_VOLUME_KEY = "reqtrack_backup_repo"
"""The repository volume's key in `docker-compose.yml`; a service mounts it by key, `name:` binds the real volume."""

PASSTHROUGH_KEYS = (
    "APP_SECRET_ENCRYPTION_KEY",
    "GHCR_IMAGE_PREFIX",
    "IMAGE_TAG",
    "STORAGE_BACKEND",
    "STORAGE_S3_BUCKET",
    "BACKUP_AWS_ACCESS_KEY_ID",
    "BACKUP_AWS_SECRET_ACCESS_KEY",
    "BACKUP_AWS_DEFAULT_REGION",
    "BACKUP_AZURE_ACCOUNT_NAME",
    "BACKUP_AZURE_ACCOUNT_KEY",
    "BACKUP_SSH_DIR",
)
"""The only settings taken from the operator's environment or `--source-env`; everything else is generated."""

SECRET_KEYS = (
    "APP_SECRET_ENCRYPTION_KEY",
    "BACKUP_AWS_SECRET_ACCESS_KEY",
    "BACKUP_AZURE_ACCOUNT_KEY",
    "POSTGRES_PASSWORD",
    "JWT_SECRET",
    "SERVER_ADMIN_PASSWORD",
    "STORAGE_SECRET_KEY",
)
"""Environment entries whose values are masked in everything the harness prints or writes."""

MIN_MASKED_LENGTH = 4
"""Secrets shorter than this are not masked: a one- or two-character value would garble every line of output."""
_COMPOSE_OUTPUT_TAIL = 12
LOG_TAIL_LINES = 40
_COMPOSE_PROGRESS = re.compile(r"^\s*(Volume|Container|Network)\s+\S+\s+(Creat\w+|Start\w+|Wait\w+|Heal\w+|Remov\w+|Runn\w+|Stopp\w+|Stopped)\s*$")
_ACCESS_FAILURE = re.compile(r"permission denied|no such file|not found|cannot open|read-only file system", re.IGNORECASE)
_UNREADABLE_COLUMN = re.compile(r"([a-z0-9_]+\.[a-z0-9_]+) \((\d+)\)")
_SAFE_NAME = re.compile(r"^[a-z0-9_]+$")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class HarnessError(Exception):
    """A step could not run or failed; the message is redacted and safe to print.

    Attributes:
        step: The step name recorded in the report.
        code: A process exit status to prefer over the default 1 (75 for a running backup).
    """

    def __init__(self, step: str, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.step = step
        self.code = code


@dataclass
class Step:
    """One step of the run, as written to the report.

    Attributes:
        name: Stable step name.
        ok: Whether it passed.
        detail: One redacted line.
        seconds: How long it took.
    """

    name: str
    ok: bool
    detail: str
    seconds: float = 0.0


@dataclass
class Options:
    """What the operator asked for (the parsed command line).

    Attributes:
        repository: Repository to read instead of the primary (an off-site copy); None uses the volume or path below.
        repository_volume: A Docker volume name or host path holding the primary repository.
        password_file: File holding the repository password.
        selector: `latest`, a set id or a snapshot id prefix.
        source_env: A `.env` file to take `PASSTHROUGH_KEYS` from (the production `.env` or a decrypted config snapshot).
        key_mode: `correct` uses the supplied encryption key, `wrong` a fresh random one.
        clear_unreadable_secrets: Restore with `--clear-unreadable-secrets` (the supported way past a lost key).
        image_tag: Image tag for the scratch stack; None uses the tag recorded in the set's manifest.
        output_dir: Where the report is written.
        status_dir: Where the status file and Prometheus textfile are written; None writes none.
        keep: Leave the scratch project running afterwards, for inspection.
        inject: A fault to inject (self-test), or None.
        login_email / login_password_file: An account whose sign-in is exercised.
        check_subset: Share of repository data the integrity check reads (`5%`, empty for structure only).
        timeout_seconds: Longest any one command may run.
        compose_dir: The repository root (where the compose files are).
    """

    repository: Optional[str] = None
    repository_volume: Optional[str] = None
    password_file: Optional[Path] = None
    selector: str = "latest"
    source_env: Optional[Path] = None
    key_mode: str = "correct"
    clear_unreadable_secrets: bool = False
    image_tag: Optional[str] = None
    output_dir: Path = Path("restore-test-reports")
    status_dir: Optional[Path] = None
    keep: bool = False
    inject: Optional[str] = None
    login_email: Optional[str] = None
    login_password_file: Optional[Path] = None
    check_subset: str = "5%"
    timeout_seconds: float = 3600.0
    compose_dir: Path = REPO_ROOT


@dataclass
class Report:
    """The run's report (`report.json`)."""

    result: str = "failed"
    project: str = ""
    set_id: str = ""
    key_mode: str = "correct"
    inject: Optional[str] = None
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    steps: list = field(default_factory=list)
    restore: dict = field(default_factory=dict)
    verify: dict = field(default_factory=dict)
    failed: list = field(default_factory=list)
    logs: dict = field(default_factory=dict)
    fault_detected: Optional[bool] = None

    def as_dict(self) -> dict:
        """The report as JSON-ready data."""
        data = dict(self.__dict__)
        data["steps"] = [dict(s.__dict__) for s in self.steps]
        return data


# --- pure helpers ----------------------------------------------------------------------------------------


def parse_env_text(text: str) -> dict:
    """Parses `KEY=VALUE` lines (the subset of dotenv syntax the stack's `.env` uses).

    Args:
        text: File contents. Blank lines and `#` comments are skipped; one pair of matching quotes is removed.

    Returns:
        The entries, later lines winning.
    """
    entries = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        entries[key] = value
    return entries


def new_project_name(now: datetime) -> str:
    """The throwaway Compose project name for a run started at `now` (UTC)."""
    return f"{PROJECT_PREFIX}{now.strftime('%Y%m%dt%H%M%Sz').lower()}"


def scratch_environment(
    *, passthrough: dict, key_mode: str, manifest_backend: Optional[str], image_tag: Optional[str], password_file: Path, generate: Callable[[], str]
) -> dict:
    """Builds the scratch stack's environment: generated credentials plus the few settings it must share.

    Args:
        passthrough: Values for `PASSTHROUGH_KEYS` taken from the operator (only those keys are used).
        key_mode: `correct` keeps the supplied `APP_SECRET_ENCRYPTION_KEY`; `wrong` replaces it.
        manifest_backend: The set's storage backend, which the scratch stack must use.
        image_tag: Tag to run, or None to keep what `passthrough` says.
        password_file: The repository password file (the compose `backup_repo_password` secret).
        generate: Source of random secrets (replaced in tests).

    Returns:
        The environment as a dict. The same dict is also the redaction list: every `SECRET_KEYS` value in it.

    Raises:
        HarnessError: If `key_mode` is `correct` and no encryption key was supplied.
    """
    env = {k: v for k, v in passthrough.items() if k in PASSTHROUGH_KEYS and v}
    if key_mode == "correct":
        if not env.get("APP_SECRET_ENCRYPTION_KEY"):
            raise HarnessError(
                "setup",
                "the original APP_SECRET_ENCRYPTION_KEY is needed to prove the restored secrets decrypt: set it in the environment or in "
                "--source-env (a decrypted config snapshot), or run with --key-mode wrong to test recovery without it",
                2,
            )
    else:
        env["APP_SECRET_ENCRYPTION_KEY"] = generate()
    if image_tag:
        env["IMAGE_TAG"] = image_tag
    if manifest_backend:
        env["STORAGE_BACKEND"] = manifest_backend
    env.update(
        {
            "POSTGRES_PASSWORD": generate(),
            "JWT_SECRET": generate(),
            "SERVER_ADMIN_PASSWORD": generate(),
            "STORAGE_SECRET_KEY": generate(),
            "STORAGE_ACCESS_KEY": "drtest",
            "SMTP_HOST": "mail-sink.invalid",
            "BACKUP_REPO_PASSWORD_FILE": str(password_file),
            "BACKUP_REPOSITORY_READ_ONLY": "true",
            "BACKUP_SECRETS_MODE": "none",
            "BACKUP_CHECK_SUBSET": "",
        }
    )
    return env


def render_env_file(env: dict) -> str:
    """Renders an environment as an env file Compose reads (a value with a newline or quote is refused)."""
    lines = []
    for key, value in sorted(env.items()):
        if any(c in value for c in "\n\r\"'$"):
            raise HarnessError("setup", f"{key} holds a character the env file cannot carry safely (newline, quote or $)", 2)
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def render_repository_override(source: str, *, named_volume: bool) -> str:
    """The generated Compose override that mounts the repository read-only into the tools that read it.

    Args:
        source: A host path, or an existing Docker volume name when `named_volume`.
        named_volume: Whether `source` is a volume name (declared external, so the real repository volume of
            another project is used instead of a new empty one).

    Returns:
        YAML text (JSON strings are valid YAML scalars, so values are quoted with `json.dumps`).
    """
    mount = (
        f'      - type: {"volume" if named_volume else "bind"}\n'
        f"        source: {json.dumps(REPOSITORY_VOLUME_KEY if named_volume else source)}\n"
        "        target: /backup/repo\n"
        "        read_only: true\n"
    )
    text = "services:\n  backup:\n    volumes:\n" + mount + "  restore:\n    volumes:\n" + mount
    if named_volume:
        text += f"volumes:\n  {REPOSITORY_VOLUME_KEY}:\n    external: true\n    name: {json.dumps(source)}\n"
    return text


def prometheus_text(report: Report, previous_success: float) -> str:
    """The Prometheus textfile for a finished, non-injected run.

    Args:
        report: The finished report.
        previous_success: Unix time of the last passing run (carried forward when this one failed).
    """
    finished = datetime.fromisoformat(report.finished_at).timestamp()
    ok = report.result == "ok"
    success = finished if ok else previous_success
    failed_checks = len(report.failed)
    return "\n".join(
        [
            "# HELP reqtrack_restore_test_last_run_success 1 if the last restore-test passed, else 0.",
            "# TYPE reqtrack_restore_test_last_run_success gauge",
            f"reqtrack_restore_test_last_run_success {1 if ok else 0}",
            "# HELP reqtrack_restore_test_last_run_timestamp_seconds Unix time the last restore-test finished.",
            "# TYPE reqtrack_restore_test_last_run_timestamp_seconds gauge",
            f"reqtrack_restore_test_last_run_timestamp_seconds {finished:.0f}",
            "# HELP reqtrack_restore_test_last_success_timestamp_seconds Unix time of the last passing restore-test.",
            "# TYPE reqtrack_restore_test_last_success_timestamp_seconds gauge",
            f"reqtrack_restore_test_last_success_timestamp_seconds {success:.0f}",
            "# HELP reqtrack_restore_test_duration_seconds Duration of the last restore-test.",
            "# TYPE reqtrack_restore_test_duration_seconds gauge",
            f"reqtrack_restore_test_duration_seconds {report.duration_seconds:.1f}",
            "# HELP reqtrack_restore_test_failed_checks Checks and steps that failed in the last restore-test.",
            "# TYPE reqtrack_restore_test_failed_checks gauge",
            f"reqtrack_restore_test_failed_checks {failed_checks}",
            "",
        ]
    )


def unreadable_columns(message: str) -> dict:
    """The `{"table.column": count}` pairs a restore's key-mismatch error names."""
    return {column: int(count) for column, count in _UNREADABLE_COLUMN.findall(message)}


def expected_unreadable_columns(manifest: dict) -> dict:
    """Encrypted columns that hold values in the set, which a wrong key must name exactly (with their counts)."""
    columns = manifest["stats"]["probes"]["encrypted_columns"]
    return {name: probe["rows"] for name, probe in columns.items() if probe["rows"]}


def render_markdown(report: Report) -> str:
    """The human-readable form of the report."""
    lines = [
        f"# Restore test: {report.result.upper()}",
        "",
        f"- Set: `{report.set_id or 'unknown'}`; scratch project `{report.project}`; key `{report.key_mode}`"
        + (f"; injected fault `{report.inject}` ({'detected' if report.fault_detected else 'NOT detected'})" if report.inject else ""),
        f"- Started {report.started_at}, finished {report.finished_at} ({report.duration_seconds:.0f}s)",
        "",
        "| Step | Result | Detail |",
        "|------|--------|--------|",
    ]
    for step in report.steps:
        lines.append(f"| {step.name} | {'ok' if step.ok else 'FAILED'} | {step.detail.replace('|', '/')} |")
    checks = report.verify.get("checks") or []
    if checks:
        lines += ["", "| Check | Result | Detail |", "|-------|--------|--------|"]
        for check in checks:
            lines.append(f"| {check['name']} | {'ok' if check['ok'] else 'FAILED'} | {check['detail'].replace('|', '/')} |")
        for check in checks:
            for mismatch in (check.get("data") or {}).get("mismatches", [])[:20]:
                lines.append(f"\n- MISMATCH `{mismatch['path']}`: expected {mismatch['expected']!r}, got {mismatch['actual']!r}")
    return "\n".join(lines) + "\n"


# --- running docker --------------------------------------------------------------------------------------


class Docker:
    """Runs `docker` and `docker compose` for one scratch project, redacting secrets from what it returns.

    Args:
        project: The Compose project name.
        compose_dir: Directory holding the compose files.
        files: Compose files, in merge order (paths relative to `compose_dir` or absolute).
        env_file: The generated env file.
        secrets_to_mask: Values removed from every message.
        runner: `subprocess.run`-compatible callable (replaced in tests).
        timeout: Seconds one command may run.
    """

    def __init__(
        self, project: str, compose_dir: Path, files: Sequence, env_file: Path, secrets_to_mask: Sequence, runner: Runner = subprocess.run, timeout: float = 3600.0
    ) -> None:
        self.project = project
        self._dir = compose_dir
        self._files = list(files)
        self._env_file = env_file
        self._mask = [s for s in secrets_to_mask if len(s) >= MIN_MASKED_LENGTH]
        self._runner = runner
        self._timeout = timeout

    def mask(self, secret: str) -> None:
        """Adds a value to those removed from every message."""
        if len(secret) >= MIN_MASKED_LENGTH:
            self._mask.append(secret)

    def redact(self, text: str) -> str:
        """Masks every secret value in `text`."""
        for secret in self._mask:
            text = text.replace(secret, "***")
        return text

    def raw(self, argv: Sequence, *, input: Optional[str] = None, timeout: Optional[float] = None) -> "subprocess.CompletedProcess[str]":
        """Runs an argument vector, capturing text output; a timeout is returned as exit status 124."""
        try:
            return self._runner(list(argv), input=input, capture_output=True, text=True, timeout=timeout or self._timeout, cwd=self._dir, check=False)
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(list(argv), 124, "", f"timed out after {exc.timeout:.0f}s")
        except OSError as exc:
            return subprocess.CompletedProcess(list(argv), 127, "", f"cannot run {argv[0]}: {exc}")

    def compose(self, *args: str, input: Optional[str] = None, timeout: Optional[float] = None) -> "subprocess.CompletedProcess[str]":
        """Runs `docker compose -p <project> -f ... --env-file ... --profile restore <args>`."""
        base = ["docker", "compose", "-p", self.project, "--env-file", str(self._env_file)]
        for file in self._files:
            base += ["-f", str(file)]
        base += ["--profile", "restore"]
        return self.raw(base + list(args), input=input, timeout=timeout)

    def tail(self, proc: "subprocess.CompletedProcess[str]") -> str:
        """The last lines of a command's output, redacted and joined, for an error message."""
        lines = [line for line in ((proc.stderr or "") + (proc.stdout or "")).strip().splitlines() if line.strip() and not _COMPOSE_PROGRESS.match(line)]
        return self.redact(" | ".join(lines[-_COMPOSE_OUTPUT_TAIL:]))


# --- the run ---------------------------------------------------------------------------------------------


class RestoreTest:
    """One restore-test run.

    Args:
        options: What the operator asked for.
        runner: `subprocess.run`-compatible callable (replaced in tests).
        now: Clock (UTC).
        generate: Source of random secrets.
        stdout: Where progress lines go.
    """

    def __init__(
        self,
        options: Options,
        runner: Runner = subprocess.run,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        generate: Callable[[], str] = lambda: secrets.token_urlsafe(24),
        stdout: Any = sys.stdout,
    ) -> None:
        self.options = options
        self._runner = runner
        self._now = now
        self._generate = generate
        self._out = stdout
        self.report = Report(key_mode=options.key_mode, inject=options.inject)
        self.docker: Optional[Docker] = None
        self._work: Optional[Path] = None
        self._temp_volumes: list = []
        self._manifest: dict = {}
        self._restore_ok = False

    # progress ---------------------------------------------------------------

    def _say(self, line: str) -> None:
        print(line, file=self._out, flush=True)

    def _step(self, name: str, started: float, ok: bool, detail: str) -> None:
        self.report.steps.append(Step(name, ok, detail, round(time.monotonic() - started, 1)))
        self._say(f"{'ok  ' if ok else 'FAIL'} {name}: {detail}")

    # entry point ------------------------------------------------------------

    def run(self) -> int:
        """Runs the test end to end and returns the process exit status (see the module docstring)."""
        started = self._now()
        self.report.started_at = started.isoformat()
        self.report.project = new_project_name(started)
        clock = time.monotonic()
        code = 1
        try:
            self._prepare()
            self._execute()
        except HarnessError as exc:
            last = self.report.steps[-1] if self.report.steps else None
            if not (last is not None and last.name == exc.step and not last.ok):
                self.report.steps.append(Step(exc.step, False, str(exc)))
                self._say(f"FAIL {exc.step}: {exc}")
            code = exc.code
        finally:
            self._teardown()
            self.report.duration_seconds = round(time.monotonic() - clock, 1)
            self.report.finished_at = self._now().isoformat()
        self._conclude()
        self._write_outputs()
        if code in (2, EX_TEMPFAIL):
            return code  # unusable arguments, or another run holds the repository: nothing was proven either way
        if self.options.inject:
            return 0 if self.report.fault_detected else 1
        return 0 if self.report.result == "ok" else code

    def _conclude(self) -> None:
        """Decides the result from the recorded steps and checks."""
        failed_steps = [s.name for s in self.report.steps if not s.ok]
        failed_checks = [c["name"] for c in (self.report.verify.get("checks") or []) if not c["ok"]]
        self.report.failed = failed_steps + failed_checks
        self.report.result = "ok" if not self.report.failed else "failed"
        if self.options.inject:
            self.report.fault_detected = self._fault_detected(failed_steps, failed_checks)
            self.report.result = "ok" if self.report.fault_detected else "failed"

    def _fault_detected(self, failed_steps: list, failed_checks: list) -> bool:
        """Whether the injected fault failed the step or check that exists to catch it, and nothing else broke first."""
        fault = self.options.inject
        if not self.report.steps or any(s.name == "fault" and not s.ok for s in self.report.steps):
            return False  # the fault could not even be applied: the self-test proves nothing
        if fault == "delete-row":
            return "statistics" in failed_checks
        if fault == "delete-object":
            return "file-objects" in failed_checks
        if fault == "wrong-key":
            return "restore" in failed_steps and any(s.name == "unreadable-columns" and s.ok for s in self.report.steps)
        if fault == "corrupt-dump":
            caught = [s for s in self.report.steps if s.name in ("restore", "repository-check") and not s.ok]
            # an unreadable repository is not a damaged one: the failure must come from the data, not from access
            return bool(caught) and not any(_ACCESS_FAILURE.search(s.detail) for s in caught)
        return False

    # setup ------------------------------------------------------------------

    def _prepare(self) -> None:
        """Validates the inputs and writes the scratch environment to a private directory."""
        opts = self.options
        if opts.inject and opts.inject not in FAULTS:
            raise HarnessError("setup", f"unknown fault {opts.inject!r}; use one of {', '.join(FAULTS)}", 2)
        if opts.inject == "wrong-key":
            opts.key_mode = "wrong"
            self.report.key_mode = "wrong"
        if opts.key_mode not in KEY_MODES:
            raise HarnessError("setup", f"--key-mode must be one of {', '.join(KEY_MODES)}", 2)
        if opts.password_file is None or not opts.password_file.is_file():
            raise HarnessError("setup", "the repository password file is required (--password-file or BACKUP_REPO_PASSWORD_FILE)", 2)
        if opts.repository is None and not opts.repository_volume:
            raise HarnessError("setup", "name the repository: --repository-volume (a Docker volume or host path) or --repository (an off-site copy)", 2)
        if shutil.which("docker") is None and self._runner is subprocess.run:
            raise HarnessError("setup", "docker is not installed or not on PATH", 2)

        source: dict = {}
        if opts.source_env:
            try:
                source = parse_env_text(opts.source_env.read_text())
            except OSError as exc:
                raise HarnessError("setup", f"cannot read --source-env: {exc.strerror}", 2) from exc
        passthrough = {k: os.environ[k] for k in PASSTHROUGH_KEYS if os.environ.get(k)}
        passthrough.update({k: v for k, v in source.items() if k in PASSTHROUGH_KEYS})

        self._work = Path(tempfile.mkdtemp(prefix="reqtrack-restore-test-"))
        os.chmod(self._work, 0o700)
        self._passthrough = passthrough
        self._env = scratch_environment(
            passthrough=passthrough, key_mode=opts.key_mode, manifest_backend=None, image_tag=opts.image_tag, password_file=opts.password_file.resolve(), generate=self._generate
        )
        env_file = self._work / "scratch.env"
        self._write_private(env_file, render_env_file(self._env))
        override = self._work / "repository.override.yml"
        volume = opts.repository_volume or ""
        named = bool(volume) and not volume.startswith(("/", ".", "~"))
        if volume and not named:
            volume = str(Path(volume).expanduser().resolve())
        if opts.repository is not None and not volume:
            volume = str(self._work)  # never read: the tools use --repository
            named = False
        self._repo_source, self._repo_named = volume, named
        self._write_private(override, render_repository_override(volume, named_volume=named))
        files = [opts.compose_dir / f for f in COMPOSE_FILES] + [override]
        self.docker = Docker(
            self.report.project, opts.compose_dir, files, env_file, [self._env[k] for k in SECRET_KEYS if k in self._env], self._runner, opts.timeout_seconds
        )

    @staticmethod
    def _write_private(path: Path, text: str) -> None:
        """Writes a file readable only by the current user."""
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(text)

    # steps ------------------------------------------------------------------

    def _tool(self, *args: str, input: Optional[str] = None, timeout: Optional[float] = None) -> "subprocess.CompletedProcess[str]":
        """Runs the restore tool (`scripts/dr_restore.py`) in a one-off container with no dependencies started."""
        repo = ["--repository", self.options.repository] if self.options.repository and args and args[0] in ("manifest", "check") else []
        return self.docker.compose("run", "--rm", "-T", "--no-deps", "restore", *args, *repo, input=input, timeout=timeout)

    def _execute(self) -> None:
        opts, docker = self.options, self.docker
        self._say(f"restore-test: scratch project {self.report.project}")

        if opts.inject == "corrupt-dump":
            self._corrupt_repository_copy()

        started = time.monotonic()
        subset = ["--subset", opts.check_subset]
        proc = self._tool("check", *subset)
        if proc.returncode != 0:
            self._step("repository-check", started, False, docker.tail(proc))
            if opts.inject == "corrupt-dump":
                return
            raise HarnessError("repository-check", docker.tail(proc))
        self._step("repository-check", started, True, f"repository passes restic check (data sample: {opts.check_subset or 'none'})")

        started = time.monotonic()
        proc = self._tool("manifest", "--set", opts.selector)
        if proc.returncode != 0:
            raise HarnessError("manifest", docker.tail(proc))
        try:
            self._manifest = json.loads(proc.stdout)
        except ValueError as exc:
            raise HarnessError("manifest", "the manifest is not valid JSON") from exc
        self.report.set_id = self._manifest["set_id"]
        tag = self._manifest["app"].get("image_tag")
        stats = self._manifest["stats"]
        self._step(
            "manifest",
            started,
            True,
            f"set {self._manifest['set_id']} ({self._manifest['storage_backend']} storage, secrets {self._manifest['secrets_mode']}, image {tag or 'untagged'}, "
            f"{len(stats['tables'])} tables, {stats['business']['users']['total']} users, {stats['business']['projects']} projects)",
        )

        self._reconfigure(tag)
        self._start_services(("db", "storage"), "scratch-stack")
        self._restore(stats)
        if not self._restore_ok:
            return

        if opts.inject in ("delete-row", "delete-object"):
            self._inject_fault(stats)

        self._start_services(("backend",), "application")
        self._verify()

    def _reconfigure(self, manifest_tag: Optional[str]) -> None:
        """Rewrites the scratch environment now the set's storage backend and image tag are known."""
        tag = self.options.image_tag or manifest_tag
        # the credentials already generated (and masked) are kept: only the two newly-known settings change
        current = dict(line.split("=", 1) for line in (self._work / "scratch.env").read_text().splitlines() if "=" in line)
        current["STORAGE_BACKEND"] = self._manifest["storage_backend"]
        if tag:
            current["IMAGE_TAG"] = tag
        self._write_private(self._work / "scratch.env", render_env_file(current))
        self._env = current

    def _start_services(self, services: Sequence, step: str) -> None:
        started = time.monotonic()
        proc = self.docker.compose("up", "-d", "--wait", "--wait-timeout", "600", "--pull", "missing", *services)
        if proc.returncode != 0:
            self._step(step, started, False, self.docker.tail(proc))
            self._capture_logs(services)
            raise HarnessError(step, "the scratch stack did not become healthy; the end of each service's log is in the report")
        self._step(step, started, True, f"{', '.join(services)} healthy in an isolated project (no published ports)")

    def _capture_logs(self, services: Sequence) -> None:
        """Keeps the end of each failed service's log in the report (redacted of every secret), so a stack that
        would not start can be diagnosed after the scratch project is gone."""
        for service in services:
            proc = self.docker.compose("logs", "--no-color", "--tail", str(LOG_TAIL_LINES), service)
            lines = self.docker.redact((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
            self.report.logs[service] = lines[-LOG_TAIL_LINES:]
            self._say(f"--- last {len(self.report.logs[service])} lines of the {service} log ---")
            for line in self.report.logs[service]:
                self._say(line)

    def _restore(self, stats: dict) -> None:
        opts = self.options
        started = time.monotonic()
        report_path = "/backup/status/harness-restore-report.json"
        args = ["restore", "fresh", "--set", self.report.set_id, "--report", report_path]
        if opts.clear_unreadable_secrets:
            args.append("--clear-unreadable-secrets")
        if opts.repository:
            args += ["--repository", opts.repository]
        proc = self.docker.compose("run", "--rm", "-T", "restore", *args)
        document = self._fetch_json(report_path)
        self.report.restore = {k: document.get(k) for k in ("result", "step", "error", "objects_restored", "secrets_cleared", "warnings", "mismatches") if k in document}
        if proc.returncode == EX_TEMPFAIL:
            raise HarnessError("restore", "a backup or another restore is running against this repository's staging area", EX_TEMPFAIL)
        if proc.returncode != 0:
            self._step("restore", started, False, redact_error(self.docker, document, proc))
            if opts.inject == "wrong-key":
                self._check_unreadable_columns(document)
            return
        self._restore_ok = True
        self._step("restore", started, True, f"restored and verified against the manifest; {document.get('objects_restored', 0)} objects put back")
        if opts.inject == "wrong-key":
            self._step("unreadable-columns", started, False, "the wrong key was accepted: nothing reported unreadable")

    def _check_unreadable_columns(self, document: dict) -> None:
        """A wrong key must be reported with exactly the encrypted columns that hold values, and their counts."""
        started = time.monotonic()
        expected = expected_unreadable_columns(self._manifest)
        actual = unreadable_columns(str(document.get("error") or ""))
        if not expected:
            self._step("unreadable-columns", started, False, "the set holds no encrypted values, so a wrong key cannot be told from the right one")
        elif actual == expected:
            self._step("unreadable-columns", started, True, f"the restore named exactly the {len(expected)} unreadable columns and their counts")
        else:
            self._step("unreadable-columns", started, False, f"expected {expected}, the restore reported {actual}")

    def _fetch_json(self, path: str) -> dict:
        proc = self.docker.compose("run", "--rm", "-T", "--no-deps", "--entrypoint", "cat", "restore", path)
        try:
            return json.loads(proc.stdout)
        except ValueError:
            return {}

    def _verify(self) -> None:
        opts, docker = self.options, self.docker
        started = time.monotonic()
        request: dict = {"manifest": self._manifest}
        if opts.login_email and opts.login_password_file:
            request["login"] = {"email": opts.login_email, "password": opts.login_password_file.read_text().strip()}
            docker.mask(request["login"]["password"])
        args = ["exec", "-T", "backend", "python", "scripts/dr_verify.py"]
        if opts.clear_unreadable_secrets:
            args.append("--allow-unreadable-secrets")
        if self.report.restore.get("secrets_cleared"):
            args += ["--extra-rows", "audit_events=1"]  # clearing writes exactly one audit event; nothing else may differ
        proc = docker.compose(*args, input=json.dumps(request))
        try:
            self.report.verify = json.loads(proc.stdout)
        except ValueError:
            self._step("verify", started, False, f"the verifier produced no report: {docker.tail(proc)}")
            return
        for check in self.report.verify["checks"]:
            self._say(f"{'ok  ' if check['ok'] else 'FAIL'} {check['name']}: {docker.redact(check['detail'])}")
        self._step("verify", started, self.report.verify["result"] == "ok", f"{len(self.report.verify['checks'])} checks run in the restored application")

    # fault injection (self-test) --------------------------------------------

    def _sql(self, sql: str) -> "subprocess.CompletedProcess[str]":
        return self.docker.compose("exec", "-T", "db", "psql", "-U", "reqtrack", "-d", "reqtrack", "-v", "ON_ERROR_STOP=1", "-tA", "-c", sql)

    def _inject_fault(self, stats: dict) -> None:
        started = time.monotonic()
        if self.options.inject == "delete-row":
            detail = self._delete_one_row(stats)
        else:
            detail = self._delete_one_object()
        self._step("fault", started, detail is not None, detail or f"could not apply {self.options.inject}: the set holds nothing of that kind to remove")

    def _delete_one_row(self, stats: dict) -> Optional[str]:
        """Deletes one row from a populated table that no other table references; None if none could be deleted."""
        listing = self._sql(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.confrelid = c.oid) ORDER BY 1"
        )
        if listing.returncode != 0:
            return None
        leaves = set(listing.stdout.split())
        for table, count in sorted(stats["tables"].items()):
            if count and table in leaves and table != "alembic_version" and _SAFE_NAME.match(table):
                done = self._sql(f'DELETE FROM "{table}" WHERE ctid = (SELECT ctid FROM "{table}" LIMIT 1)')
                if done.returncode == 0:
                    return f"deleted one row of one table ({count} rows in the set)"
        return None

    def _delete_one_object(self) -> Optional[str]:
        """Deletes one stored object that a file record points at; None if there is none."""
        script = (
            "from sqlalchemy.orm import Session\n"
            "from sqlalchemy import select\n"
            "from app.database import engine\n"
            "from app.models.file import FileAsset\n"
            "from app.services.files import get_storage_backend\n"
            "storage = get_storage_backend()\n"
            "with Session(engine) as db:\n"
            "    key = db.scalar(select(FileAsset.storage_key).where(FileAsset.storage_backend == storage.name).limit(1))\n"
            "    if key is None:\n"
            "        raise SystemExit(3)\n"
            "    storage.delete(key)\n"
        )
        # the application is not running yet on this path; the backend image is run one-off against the restored stack
        proc = self.docker.compose("run", "--rm", "-T", "--no-deps", "--entrypoint", "python", "backend", "-c", script)
        return "deleted one stored object that a file record points at" if proc.returncode == 0 else None

    def _corrupt_repository_copy(self) -> None:
        """Replaces the repository with a damaged copy: one pack's bytes are flipped, so a restore must notice."""
        started = time.monotonic()
        name = f"{self.report.project}_corrupt_repo"
        self.docker.raw(["docker", "volume", "create", name])
        self._temp_volumes.append(name)
        image = f"{self._env.get('GHCR_IMAGE_PREFIX', 'ghcr.io/ballardr/reqtrackmanager')}-backup:{self._env.get('IMAGE_TAG', 'latest')}"
        mount = f"{self._repo_source}:/src:ro"
        script = (
            "import os, pwd, shutil\n"
            "shutil.copytree('/src', '/dst', dirs_exist_ok=True)\n"
            "packs = [os.path.join(d, f) for d, _, fs in os.walk('/dst/data') for f in fs]\n"
            "target = max(packs, key=os.path.getsize)\n"
            "with open(target, 'r+b') as h:\n"
            "    h.seek(os.path.getsize(target) // 2)\n"
            "    block = h.read(256)\n"
            "    h.seek(os.path.getsize(target) // 2)\n"
            "    h.write(bytes(b ^ 0xFF for b in block))\n"
            "# the tools read the repository as the image's own user: the copy must belong to it, or the failure seen\n"
            "# would be 'permission denied' and the test would pass without having tested damage at all\n"
            "user = pwd.getpwnam('app')\n"
            "for root, dirs, files in os.walk('/dst'):\n"
            "    for name in dirs + files:\n"
            "        os.chown(os.path.join(root, name), user.pw_uid, user.pw_gid)\n"
            "os.chown('/dst', user.pw_uid, user.pw_gid)\n"
        )
        proc = self.docker.raw(["docker", "run", "--rm", "--user", "0", "-v", mount, "-v", f"{name}:/dst", "--entrypoint", "python", image, "-c", script])
        if proc.returncode != 0:
            self._step("fault", started, False, "could not damage the repository copy: " + self.docker.tail(proc))
            raise HarnessError("fault", "the self-test could not prepare its damaged repository")
        self._repo_source, self._repo_named = name, True
        self._write_private(self._work / "repository.override.yml", render_repository_override(name, named_volume=True))
        self._step("fault", started, True, "repository copy damaged (256 bytes of the largest pack flipped)")

    # teardown and outputs ---------------------------------------------------

    def _teardown(self) -> None:
        """Removes the scratch project's containers and volumes (unless `--keep`) and the private directory."""
        started = time.monotonic()
        if self.docker is None:
            if self._work is not None:
                shutil.rmtree(self._work, ignore_errors=True)
            return
        if self.options.keep:
            files = " ".join(f"-f {f}" for f in self.docker._files)
            self._say(
                f"--keep: scratch project {self.report.project} is left running, with its credentials in {self._work}/scratch.env (delete that directory when done). "
                f"Remove everything with: docker compose -p {self.report.project} --env-file {self._work}/scratch.env {files} down -v"
            )
            return
        proc = self.docker.compose("down", "--volumes", "--remove-orphans", "--timeout", "30")
        leftovers = self.docker.raw(["docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={self.report.project}"])
        for volume in self._temp_volumes:
            self.docker.raw(["docker", "volume", "rm", "-f", volume])
        remaining = leftovers.stdout.split() if leftovers.returncode == 0 else []
        ok = proc.returncode == 0 and not remaining
        self._step("teardown", started, ok, "scratch containers, volumes and credentials removed" if ok else f"could not remove the scratch project: {self.docker.tail(proc)}")
        if self._work is not None:
            shutil.rmtree(self._work, ignore_errors=True)

    def _write_outputs(self) -> None:
        """Writes `report.json`, `report.md` and (for a real run) the status file and Prometheus textfile."""
        opts = self.options
        directory = opts.output_dir / self.report.project
        directory.mkdir(parents=True, exist_ok=True)
        redact = self.docker.redact if self.docker else (lambda t: t)
        (directory / "report.json").write_text(redact(json.dumps(self.report.as_dict(), indent=2)) + "\n")
        (directory / "report.md").write_text(redact(render_markdown(self.report)))
        self._say(f"report: {directory / 'report.json'}")
        if opts.status_dir is None or opts.inject:
            return
        opts.status_dir.mkdir(parents=True, exist_ok=True)
        previous = 0.0
        try:
            previous = float(json.loads((opts.status_dir / "restore-test-status.json").read_text()).get("last_success_timestamp") or 0)
        except (OSError, ValueError):
            pass
        finished = datetime.fromisoformat(self.report.finished_at).timestamp()
        last_success = finished if self.report.result == "ok" else previous
        status = {
            "result": self.report.result,
            "set_id": self.report.set_id,
            "project": self.report.project,
            "finished_at": self.report.finished_at,
            "duration_seconds": self.report.duration_seconds,
            "failed": self.report.failed,
            "last_success_timestamp": last_success,
        }
        (opts.status_dir / "restore-test-status.json").write_text(json.dumps(status, indent=2) + "\n")
        (opts.status_dir / "reqtrack-restore-test.prom").write_text(prometheus_text(self.report, previous))


def redact_error(docker: Docker, document: dict, proc: "subprocess.CompletedProcess[str]") -> str:
    """The restore's own failure message (already redacted by the tool), else the tail of the process output."""
    if document.get("error"):
        return docker.redact(f"at step '{document.get('step')}': {document['error']}")
    return docker.tail(proc)


def build_parser() -> argparse.ArgumentParser:
    """Builds the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repository-volume", default=os.environ.get("BACKUP_REPO_VOLUME"), help="Docker volume name or host path holding the primary repository (default $BACKUP_REPO_VOLUME)")
    parser.add_argument("--repository", help="read this repository instead (an off-site copy, as restic names it)")
    parser.add_argument("--password-file", type=Path, default=os.environ.get("BACKUP_REPO_PASSWORD_FILE"), help="repository password file (default $BACKUP_REPO_PASSWORD_FILE)")
    parser.add_argument("--set", default="latest", dest="selector", help="latest, a set id, or a snapshot id prefix")
    parser.add_argument("--source-env", type=Path, help=".env file to take the encryption key and image settings from")
    parser.add_argument("--key-mode", choices=KEY_MODES, default="correct", help="correct: use the supplied key; wrong: a replacement key (tests recovery without the original)")
    parser.add_argument("--clear-unreadable-secrets", action="store_true", help="restore with --clear-unreadable-secrets")
    parser.add_argument("--image-tag", help="image tag for the scratch stack (default: the tag recorded in the set)")
    parser.add_argument("--output", type=Path, default=Path("restore-test-reports"), help="directory for the report")
    parser.add_argument("--status-dir", type=Path, help="directory for restore-test-status.json and the Prometheus textfile (real runs only)")
    parser.add_argument("--keep", action="store_true", help="leave the scratch project running afterwards")
    parser.add_argument("--inject", choices=FAULTS, help="self-test: damage the restored copy and pass only if the harness catches it")
    parser.add_argument("--login-email", help="an account whose sign-in is exercised (proves the password hashes verify)")
    parser.add_argument("--login-password-file", type=Path, help="file holding that account's password")
    parser.add_argument("--check-subset", default="5%", help="share of repository data the integrity check reads (empty for structure only)")
    parser.add_argument("--timeout", type=float, default=3600.0, help="longest any one command may run, in seconds")
    return parser


def main(argv: Optional[Sequence] = None) -> int:
    """Runs the restore-test.

    Args:
        argv: Arguments (default `sys.argv[1:]`).

    Returns:
        The process exit status (see the module docstring).
    """
    args = build_parser().parse_args(argv)
    if bool(args.login_email) != bool(args.login_password_file):
        print("--login-email and --login-password-file go together", file=sys.stderr)
        return 2
    options = Options(
        repository=args.repository,
        repository_volume=args.repository_volume,
        password_file=Path(args.password_file) if args.password_file else None,
        selector=args.selector,
        source_env=args.source_env,
        key_mode=args.key_mode,
        clear_unreadable_secrets=args.clear_unreadable_secrets,
        image_tag=args.image_tag,
        output_dir=args.output,
        status_dir=args.status_dir,
        keep=args.keep,
        inject=args.inject,
        login_email=args.login_email,
        login_password_file=args.login_password_file,
        check_subset=args.check_subset,
        timeout_seconds=args.timeout,
    )
    return RestoreTest(options).run()


if __name__ == "__main__":
    sys.exit(main())
