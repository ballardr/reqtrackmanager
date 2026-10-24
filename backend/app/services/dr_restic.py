"""
Module: services.dr_restic

A thin, secret-safe wrapper around the `restic` command line, the one engine the backup tool uses to store,
encrypt, deduplicate, copy, prune and check backup sets.

Responsibilities:
- Build every restic invocation (repository, password file, arguments) and run it without a shell.
- Initialise a repository on first use, and a copy target with the source's chunker parameters so
  `restic copy` deduplicates.
- Expose the few operations the tool needs: backup, copy, forget with retention, check, list snapshots,
  restore (optionally verified against the repository), and dump of one stored file.
- Redact secrets from anything that can reach a log, a status file or an exception message.

Design decisions:
- The repository password is only ever passed as `--password-file`; cloud credentials are only ever
  inherited from the environment. Nothing secret is placed on a command line, where `ps` would show it.
- Output is redacted (`Redactor`) before it leaves this module: URL credentials (`sftp://user:pw@host`)
  and every configured secret value are replaced, because restic echoes repository URLs in its errors.
- One password serves the primary repository and every copy target, so a copy needs a single secret.

Dependencies: the `restic` binary on PATH (or `RESTIC_BINARY`).
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_URL_CREDENTIALS = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@")


def _as_text(value: str | bytes) -> str:
    """Decodes captured output for an error message, tolerating binary garbage."""
    return value if isinstance(value, str) else value.decode("utf-8", "replace")


class ResticError(RuntimeError):
    """A restic command failed; the message is already redacted and safe to log."""


class Redactor:
    """Removes secrets from text before it is logged, stored or raised.

    Attributes:
        secrets: Exact secret values to mask (empty values are ignored).
    """

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets = sorted({s for s in secrets if s and len(s) >= 4}, key=len, reverse=True)

    def __call__(self, text: str) -> str:
        """Returns `text` with URL credentials and every known secret masked."""
        text = _URL_CREDENTIALS.sub(r"\g<scheme>***@", text)
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return text


@dataclass(frozen=True)
class BackupResult:
    """What `Restic.backup` created.

    Attributes:
        snapshot_id: Full id of the new snapshot.
        bytes_added: Bytes newly stored in the repository (after deduplication and compression).
    """

    snapshot_id: str
    bytes_added: int


@dataclass(frozen=True)
class Retention:
    """The `forget` policy (restic `--keep-*`)."""

    hourly: int = 0
    daily: int = 7
    weekly: int = 4
    monthly: int = 12


Runner = Callable[..., subprocess.CompletedProcess]


class Restic:
    """Runs restic against one or more repositories sharing a password.

    Args:
        password_file: File holding the repository password.
        binary: The restic executable.
        env: Environment for restic (cloud credentials, `RESTIC_*`); defaults to the process environment.
        redactor: Masks secrets in output; build it from the values that must never be logged.
        runner: `subprocess.run`-compatible callable (replaced in tests).
        timeout: Seconds one restic command may run; restic retries an unreachable remote for a long time,
            so without a limit one dead destination would hold the backup lock indefinitely.
    """

    def __init__(
        self,
        password_file: Path,
        *,
        binary: str = "restic",
        env: Mapping[str, str] | None = None,
        redactor: Redactor | None = None,
        runner: Runner = subprocess.run,
        timeout: float | None = None,
        probe_timeout: float = 120.0,
    ) -> None:
        self._password_file = str(password_file)
        self._binary = binary
        self._env = dict(env) if env is not None else None
        self.redact = redactor or Redactor()
        self._runner = runner
        self._timeout = timeout
        self._probe_timeout = probe_timeout

    def run(
        self,
        repo: str,
        *args: str,
        from_repo: str | None = None,
        check: bool = True,
        timeout: float | None = None,
        text: bool = True,
    ) -> subprocess.CompletedProcess:
        """Runs `restic -r <repo> <args>`.

        Args:
            repo: Repository location (a path or a restic URL).
            args: The sub-command and its options.
            from_repo: A source repository (`--from-repo`), for `init` and `copy`.
            check: Raise `ResticError` on a non-zero exit.
            timeout: Overrides the instance timeout for this command.
            text: False to capture stdout as bytes (a binary file from `dump`); stderr is then text-decoded
                only for error messages.

        Returns:
            The completed process (stdout and stderr captured, unredacted: callers parse stdout and must
            not log it raw).

        Raises:
            ResticError: If `check` and restic exits non-zero or cannot be started.
        """
        argv = [self._binary, "-r", repo, "--password-file", self._password_file, "--no-cache"]
        if from_repo is not None:
            argv += ["--from-repo", from_repo, "--from-password-file", self._password_file]
        argv += list(args)
        try:
            proc = self._runner(argv, capture_output=True, text=text, env=self._env, check=False, timeout=timeout or self._timeout)
        except subprocess.TimeoutExpired as exc:
            raise ResticError(self.redact(f"restic {args[0]} timed out after {exc.timeout:.0f}s")) from exc
        except OSError as exc:
            raise ResticError(self.redact(f"cannot run restic: {exc}")) from exc
        if check and proc.returncode != 0:
            detail = _as_text(proc.stderr or (proc.stdout if text else b"")).strip().splitlines()
            tail = " | ".join(detail[-3:])
            raise ResticError(self.redact(f"restic {args[0]} failed (exit {proc.returncode}): {tail}"))
        return proc

    def ensure_repo(self, repo: str, *, from_repo: str | None = None) -> bool:
        """Initialises `repo` when it does not exist yet.

        Args:
            repo: The repository to prepare.
            from_repo: The primary repository whose chunker parameters a copy target must share.

        Returns:
            True when it was created, False when it already existed.

        Raises:
            ResticError: If it can neither be opened nor created (wrong password, unreachable, no rights).
        """
        probe = self.run(repo, "cat", "config", check=False, timeout=self._probe_timeout)
        if probe.returncode == 0:
            return False
        text = (probe.stderr or "") + (probe.stdout or "")
        if "wrong password" in text.lower():
            raise ResticError(self.redact("repository exists but the password is wrong"))
        if from_repo is not None:
            self.run(repo, "init", "--copy-chunker-params", from_repo=from_repo)
        else:
            self.run(repo, "init")
        return True

    def backup(self, repo: str, paths: Sequence[Path], *, tags: Sequence[str], host: str) -> BackupResult:
        """Stores `paths` as a new snapshot.

        Raises:
            ResticError: If restic fails or reports no snapshot.
        """
        args = ["backup", "--json", "--host", host]
        for tag in tags:
            args += ["--tag", tag]
        args += [str(p) for p in paths]
        proc = self.run(repo, *args)
        summary: dict[str, Any] | None = None
        for line in proc.stdout.splitlines():
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and message.get("message_type") == "summary":
                summary = message
        if not summary or not summary.get("snapshot_id"):
            raise ResticError("restic backup reported no snapshot id")
        return BackupResult(summary["snapshot_id"], int(summary.get("data_added", 0)))

    def copy(self, source_repo: str, target_repo: str, snapshot_id: str) -> None:
        """Copies one snapshot from `source_repo` to `target_repo`."""
        self.run(target_repo, "copy", snapshot_id, from_repo=source_repo)

    def forget(self, repo: str, retention: Retention) -> None:
        """Applies the retention policy and prunes unreferenced data.

        Snapshots are grouped by host only: every set has its own tags, which would otherwise make each
        its own group and retain everything.
        """
        self.run(
            repo,
            "forget",
            "--prune",
            "--group-by",
            "host",
            "--keep-hourly",
            str(retention.hourly),
            "--keep-daily",
            str(retention.daily),
            "--keep-weekly",
            str(retention.weekly),
            "--keep-monthly",
            str(retention.monthly),
        )

    def check(self, repo: str, *, read_data_subset: str | None = None) -> None:
        """Verifies repository structure and, with `read_data_subset` (`5%`), a sample of pack contents."""
        args = ["check"]
        if read_data_subset:
            args.append(f"--read-data-subset={read_data_subset}")
        self.run(repo, *args)

    def snapshots(self, repo: str) -> list[dict[str, Any]]:
        """Lists snapshots (restic's JSON records, oldest first)."""
        proc = self.run(repo, "snapshots", "--json")
        records = json.loads(proc.stdout or "[]")
        return sorted(records or [], key=lambda r: r.get("time", ""))

    def restore(self, repo: str, snapshot: str, target: Path, *, include: Sequence[str] = (), verify: bool = False) -> None:
        """Restores a snapshot (`latest` or an id) into `target`, optionally only paths matching `include`.

        Args:
            repo: Repository to read.
            snapshot: `latest` or a snapshot id.
            target: Directory to restore into (paths keep their absolute form beneath it).
            include: Restrict the restore to paths matching these patterns.
            verify: Re-read every restored file and compare it with the repository (`restic restore --verify`),
                so a damaged pack or a short write fails the restore instead of surfacing later.

        Raises:
            ResticError: If restic fails.
        """
        args = ["restore", snapshot, "--target", str(target)]
        if verify:
            args.append("--verify")
        for pattern in include:
            args += ["--include", pattern]
        self.run(repo, *args)

    def dump_file(self, repo: str, snapshot: str, path: str) -> bytes:
        """Returns the bytes of one file stored in a snapshot, without restoring anything else.

        Args:
            repo: Repository to read.
            snapshot: `latest` or a snapshot id.
            path: Absolute path of the file inside the snapshot.

        Raises:
            ResticError: If the snapshot or the file is not found, or restic fails.
        """
        return self.run(repo, "dump", snapshot, path, text=False).stdout
