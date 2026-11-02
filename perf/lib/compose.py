"""
Module: perf.lib.compose

The only way the performance runner touches Docker: a command builder that cannot address anything outside the
throwaway `reqtrack-perf` Compose project.

Responsibilities:
- Build every `docker compose` command with `-p reqtrack-perf` and the runner's own compose files and env file.
- Validate every argument vector before it runs (`validate_argv`): destructive commands may name only resources
  of the perf project, and prune, image removal and anything not on the allowlist are refused outright.
- Run Docker with a scrubbed environment, so a variable exported in the operator's shell (a production
  `POSTGRES_PASSWORD`, `COMPOSE_FILE`, `COMPOSE_PROJECT_NAME`) can never leak into or redirect the perf stack.
- Report leftovers of a crashed run and any foreign resource that shares the perf name, so a run refuses to start
  rather than touch something that is not its own.

Design decisions:
- Isolation by construction: the runner has no code path that accepts a database URL, API URL, project name or
  file path from the command line. This module is that boundary, and `backend/tests/test_perf_runner.py` pins it.
- The perf images are named `reqtrack-perf-*`, never the production image names, so a local build can never
  retag a production image (`latest`) on a shared host.
- Python 3.9+ and the standard library only, so the runner works on a bare Raspberry Pi.

Dependencies: Docker with the Compose plugin.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

PROJECT = "reqtrack-perf"
"""The one Compose project name the runner uses."""

PROJECT_LABEL = f"com.docker.compose.project={PROJECT}"
RESOURCE_PREFIXES = (f"{PROJECT}-", f"{PROJECT}_")
"""Names Compose gives the project's containers (`reqtrack-perf-db-1`), volumes and networks (`reqtrack-perf_default`)."""

ENV_ALLOWLIST = (
    "PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR",
    "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY", "DOCKER_API_VERSION", "SSH_AUTH_SOCK",
)
"""The only variables passed to Docker; everything else (including `COMPOSE_*` and any secret) is dropped."""

COMPOSE_SUBCOMMANDS = frozenset({"up", "down", "ps", "logs", "exec", "run", "build", "pull", "stop", "kill", "cp", "config", "port", "images", "top", "version"})
COMPOSE_GLOBAL_WITH_VALUE = frozenset({"-p", "--project-name", "-f", "--file", "--env-file", "--profile", "--ansi", "--progress", "--parallel"})
READ_ONLY_DOCKER = (
    ("info",), ("version",), ("ps",), ("inspect",), ("stats",), ("images",), ("volume", "ls"), ("network", "ls"), ("volume", "inspect"),
    ("network", "inspect"), ("image", "inspect"), ("buildx", "imagetools", "inspect"), ("manifest", "inspect"), ("system", "df"),
)
DESTRUCTIVE_DOCKER = (("rm",), ("stop",), ("kill",), ("volume", "rm"), ("network", "rm"))
FORBIDDEN_TOKENS = frozenset({"prune", "--rmi"})
"""Never allowed anywhere: prune removes unused resources of any project, `--rmi` removes images other stacks share."""


class UnsafeCommand(Exception):
    """A command the runner refused to run because it could address something outside the perf project."""


def scrubbed_env(source: "os._Environ[str] | dict") -> dict:
    """The environment Docker runs with: the allowlisted variables of `source` only.

    Args:
        source: Normally `os.environ`.

    Returns:
        A new dict. `COMPOSE_FILE`, `COMPOSE_PROJECT_NAME`, credentials and every other variable are absent.
    """
    return {key: source[key] for key in ENV_ALLOWLIST if key in source}


def _is_perf_resource(name: str) -> bool:
    """Whether `name` is a container, volume or network of the perf project."""
    return name.startswith(RESOURCE_PREFIXES)


def _compose_parts(argv: Sequence[str]) -> tuple[list[tuple[str, str]], str, list[str]]:
    """Splits `docker compose ...` into its global options, the subcommand and the remaining arguments."""
    options: list[tuple[str, str]] = []
    index = 2
    while index < len(argv) and argv[index].startswith("-"):
        token = argv[index]
        flag, equals, inline = token.partition("=")
        if flag not in COMPOSE_GLOBAL_WITH_VALUE:
            raise UnsafeCommand(f"compose global option {flag!r} is not allowed")
        if equals:
            options.append((flag, inline))
            index += 1
        else:
            if index + 1 >= len(argv):
                raise UnsafeCommand(f"compose option {flag!r} has no value")
            options.append((flag, argv[index + 1]))
            index += 2
    if index >= len(argv):
        raise UnsafeCommand("compose command has no subcommand")
    return options, argv[index], list(argv[index + 1:])


def validate_argv(argv: Sequence[str], allowed_files: Sequence[str] = ()) -> None:
    """Raises `UnsafeCommand` unless `argv` can only affect the perf project.

    Args:
        argv: The full argument vector, starting with `docker`.
        allowed_files: The compose files and env file the runner generated or ships; any other `-f` or
            `--env-file` is refused.

    Raises:
        UnsafeCommand: For prune, image removal, a command off the allowlist, a compose command without exactly
            one `-p reqtrack-perf`, a file the runner did not name, or a destructive command that names a
            resource outside the perf project.
    """
    if not argv or argv[0] != "docker":
        raise UnsafeCommand("only docker commands are allowed")
    bad = FORBIDDEN_TOKENS.intersection(argv)
    if bad:
        raise UnsafeCommand(f"{sorted(bad)[0]!r} is never allowed (it can remove resources of other stacks)")
    if len(argv) >= 2 and argv[1] == "compose":
        options, subcommand, rest = _compose_parts(argv)
        projects = [value for flag, value in options if flag in ("-p", "--project-name")]
        if projects != [PROJECT]:
            raise UnsafeCommand(f"compose must run with exactly one -p {PROJECT}, got {projects}")
        for flag, value in options:
            if flag in ("-f", "--file", "--env-file") and value not in allowed_files:
                raise UnsafeCommand(f"compose file {value!r} was not generated or shipped by the runner")
        if subcommand not in COMPOSE_SUBCOMMANDS:
            raise UnsafeCommand(f"compose subcommand {subcommand!r} is not allowed")
        return
    for prefix in READ_ONLY_DOCKER:
        if tuple(argv[1:1 + len(prefix)]) == prefix:
            return
    for prefix in DESTRUCTIVE_DOCKER:
        if tuple(argv[1:1 + len(prefix)]) == prefix:
            targets = [t for t in argv[1 + len(prefix):] if not t.startswith("-")]
            if not targets:
                raise UnsafeCommand(f"{' '.join(prefix)} names no resource")
            outside = [t for t in targets if not _is_perf_resource(t)]
            if outside:
                raise UnsafeCommand(f"{' '.join(prefix)} may only name {PROJECT} resources, not {outside[0]!r}")
            return
    raise UnsafeCommand(f"docker {' '.join(argv[1:3])!r} is not on the allowlist")


@dataclass
class Result:
    """The outcome of one command.

    Attributes:
        code: Exit status (124 for a timeout, 127 when the program could not run).
        out: Standard output.
        err: Standard error.
    """

    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        """Whether the command exited 0."""
        return self.code == 0


Runner = Callable[..., "subprocess.CompletedProcess"]


class PerfDocker:
    """Runs validated Docker and Compose commands for the perf project.

    Args:
        files: Compose files in merge order (absolute paths); also the only `-f` values accepted.
        env_file: The generated env file Compose reads (the only `--env-file` accepted).
        cwd: The directory commands run in (the repository root).
        secrets: Values masked in everything returned or printed.
        runner: A `subprocess.run`-compatible callable (replaced in tests).
        environ: The environment to scrub (replaced in tests).
    """

    def __init__(
        self, files: Sequence[Path], env_file: Optional[Path], cwd: Path, secrets: Sequence[str] = (),
        runner: Runner = subprocess.run, environ: Optional[dict] = None,
    ) -> None:
        self.files = [str(f) for f in files]
        self.env_file = str(env_file) if env_file else None
        self.cwd = cwd
        self._secrets = [s for s in secrets if len(s) >= 4]
        self._runner = runner
        self._environ = scrubbed_env(os.environ if environ is None else environ)

    def add_secret(self, value: str) -> None:
        """Masks `value` in every later result."""
        if len(value) >= 4:
            self._secrets.append(value)

    def redact(self, text: str) -> str:
        """Replaces every known secret in `text` with `***`."""
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return text

    def _allowed(self) -> list[str]:
        return self.files + ([self.env_file] if self.env_file else [])

    def run(
        self, argv: Sequence[str], *, input: Optional[str] = None, timeout: Optional[float] = None, show_stderr: bool = False,
        stdin_path: Optional[Path] = None, stdout_path: Optional[Path] = None,
    ) -> Result:
        """Validates and runs `argv` with the scrubbed environment.

        Args:
            argv: The full argument vector.
            input: Text sent to standard input.
            timeout: Seconds before the command is killed (reported as exit status 124).
            show_stderr: Let standard error through to the terminal as it happens (long, chatty commands) instead of
                capturing it.
            stdin_path: A file streamed to standard input (a database restore).
            stdout_path: A file standard output is streamed to (a database dump); `Result.out` is then empty.

        Raises:
            UnsafeCommand: As `validate_argv`.
        """
        validate_argv(argv, self._allowed())
        streaming = stdin_path is not None or stdout_path is not None
        options: dict = {
            "cwd": str(self.cwd), "env": self._environ, "check": False, "timeout": timeout, "text": not streaming,
            "stderr": None if show_stderr else subprocess.PIPE,
        }
        handles = []
        try:
            if stdin_path is not None:
                handles.append(open(stdin_path, "rb"))
                options["stdin"] = handles[-1]
            elif input is not None:
                options["input"] = input
            else:
                options["stdin"] = subprocess.DEVNULL
            if stdout_path is not None:
                handles.append(open(stdout_path, "wb"))
                options["stdout"] = handles[-1]
            else:
                options["stdout"] = subprocess.PIPE
            try:
                done = self._runner(list(argv), **options)
            except subprocess.TimeoutExpired:
                return Result(124, "", f"timed out after {timeout}s")
            except OSError as exc:
                return Result(127, "", f"cannot run {argv[0]}: {exc}")
        finally:
            for handle in handles:
                handle.close()
        out, err = done.stdout, done.stderr
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        if isinstance(err, bytes):
            err = err.decode(errors="replace")
        return Result(done.returncode, self.redact(out or ""), self.redact(err or ""))

    def compose_argv(self, *args: str, profiles: Sequence[str] = ()) -> list[str]:
        """The full argument vector for `docker compose <args>` in the perf project."""
        argv = ["docker", "compose", "-p", PROJECT]
        for file in self.files:
            argv += ["-f", file]
        if self.env_file:
            argv += ["--env-file", self.env_file]
        for profile in profiles:
            argv += ["--profile", profile]
        return argv + list(args)

    def compose(self, *args: str, profiles: Sequence[str] = (), **options) -> Result:
        """Runs `docker compose -p reqtrack-perf ... <args>`; `options` are those of `run`."""
        return self.run(self.compose_argv(*args, profiles=profiles), **options)

    def docker(self, *args: str, timeout: Optional[float] = None) -> Result:
        """Runs an allowlisted `docker <args>` (read-only, or destructive on perf resources only)."""
        return self.run(["docker", *args], timeout=timeout)

    # --- what exists ---------------------------------------------------------------------------

    def project_resources(self) -> dict:
        """Containers, volumes and networks labelled as the perf project.

        Returns:
            `{"containers": [...], "volumes": [...], "networks": [...]}` of names.
        """
        def names(*args: str) -> list[str]:
            result = self.docker(*args)
            return [line.strip() for line in result.out.splitlines() if line.strip()] if result.ok else []

        return {
            "containers": names("ps", "-a", "--filter", f"label={PROJECT_LABEL}", "--format", "{{.Names}}"),
            "volumes": names("volume", "ls", "--filter", f"label={PROJECT_LABEL}", "--format", "{{.Name}}"),
            "networks": names("network", "ls", "--filter", f"label={PROJECT_LABEL}", "--format", "{{.Name}}"),
        }

    def foreign_resources(self) -> list[str]:
        """Resources whose name starts with the perf prefix but that are not labelled as the perf project.

        These are not ours, so the runner refuses to start rather than risk reusing or removing one.
        """
        found: list[str] = []
        for kind, args in (
            ("container", ("ps", "-a", "--filter", f"name={PROJECT}", "--format", '{{.Names}}|{{.Label "com.docker.compose.project"}}')),
            ("volume", ("volume", "ls", "--filter", f"name={PROJECT}", "--format", '{{.Name}}|{{.Label "com.docker.compose.project"}}')),
            ("network", ("network", "ls", "--filter", f"name={PROJECT}", "--format", '{{.Name}}|{{.Label "com.docker.compose.project"}}')),
        ):
            result = self.docker(*args)
            for line in result.out.splitlines() if result.ok else []:
                name, _, label = line.partition("|")
                if _is_perf_resource(name.strip()) and label.strip() != PROJECT:
                    found.append(f"{kind} {name.strip()}")
        return found

    def remove_leftovers(self) -> list[str]:
        """Removes the perf project's containers, volumes and networks, and nothing else.

        Returns:
            The names removed.
        """
        removed: list[str] = []
        resources = self.project_resources()
        if resources["containers"]:
            self.docker("rm", "-f", "-v", *resources["containers"])
            removed += resources["containers"]
        if resources["networks"]:
            self.docker("network", "rm", *resources["networks"])
            removed += resources["networks"]
        if resources["volumes"]:
            self.docker("volume", "rm", *resources["volumes"])
            removed += resources["volumes"]
        return removed
