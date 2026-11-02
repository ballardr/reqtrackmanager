"""
Module: perf.lib.sampler

Samples per-container memory and CPU with `docker stats`, independent of any monitoring stack.

Responsibilities:
- Poll the perf project's containers on a thread, parse `docker stats` output into rows keyed by service, and tag
  each row with the tier, scenario and repeat being run.
- On a Raspberry Pi, record whether `vcgencmd get_throttled` ever reported throttling (a flag word, no identity).

Design decisions:
- Its own sampler so results never depend on cAdvisor, Prometheus or Grafana: the Pi cannot afford the
  observability profile, and the bundle must be self-contained.
- Rows carry seconds since the scenario started, never wall-clock time, and the service name, never a container id
  or name (which embed the project and an index).
- `docker stats` reports a cgroup's usage minus page cache where the kernel exposes it, which is the working set
  an out-of-memory killer acts on; Docker Desktop numbers describe its Linux VM.

Dependencies: Docker (through `perf.lib.compose.PerfDocker`).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from typing import Callable, Optional

from perf.lib.compose import PROJECT, PerfDocker

_UNITS = {"b": 1 / 2**20, "kib": 1 / 1024, "kb": 1 / 1000 * 0.95367, "mib": 1.0, "mb": 0.95367, "gib": 1024.0, "gb": 953.67}
_USAGE = re.compile(r"^\s*([\d.]+)\s*([A-Za-z]+)\s*/\s*([\d.]+)\s*([A-Za-z]+)\s*$")
_SERVICE = re.compile(rf"^{re.escape(PROJECT)}-(.+)-(?:\d+|run-[0-9a-f]+)$")


def to_mib(value: str, unit: str) -> float:
    """Converts a `docker stats` amount (such as `1.5` `GiB`) to MiB; an unknown unit raises `ValueError`."""
    factor = _UNITS.get(unit.lower())
    if factor is None:
        raise ValueError(f"unknown memory unit {unit!r}")
    return float(value) * factor


def parse_stats_line(line: str) -> Optional[dict]:
    """Parses one `docker stats --format '{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}'` line.

    Returns:
        `{"service", "mem_mib", "mem_limit_mib", "cpu_percent"}`, or None for a line that is not a perf-project
        container or cannot be parsed.
    """
    parts = line.strip().split("|")
    if len(parts) != 3:
        return None
    name, usage, cpu = parts
    service = _SERVICE.match(name.strip())
    match = _USAGE.match(usage)
    if not service or not match:
        return None
    try:
        return {
            "service": "loadgen" if "-run-" in name else service.group(1),
            "mem_mib": round(to_mib(match.group(1), match.group(2)), 1),
            "mem_limit_mib": round(to_mib(match.group(3), match.group(4)), 1),
            "cpu_percent": round(float(cpu.strip().rstrip("%") or 0), 1),
        }
    except ValueError:
        return None


def pi_throttled_flags() -> Optional[str]:
    """The `vcgencmd get_throttled` flag word (for example `0x0`), or None when not on a Raspberry Pi."""
    if not shutil.which("vcgencmd"):
        return None
    try:
        done = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"throttled=(0x[0-9a-fA-F]+)", done.stdout)
    return match.group(1) if match else None


class Sampler:
    """Polls container statistics on a thread.

    Args:
        docker: The validated Docker runner.
        interval: Minimum seconds between polls (a poll itself takes a second or two).
        clock: Monotonic clock (replaced in tests).
        flags: Reader for the Pi throttle flags (replaced in tests).

    Attributes:
        rows: Collected rows (dicts with `t_seconds` and the tags).
        throttle_flags_seen: Non-zero throttle flag words seen.
    """

    def __init__(
        self, docker: PerfDocker, interval: float = 2.0, clock: Callable[[], float] = time.monotonic,
        flags: Callable[[], Optional[str]] = pi_throttled_flags,
    ) -> None:
        self._docker = docker
        self._interval = interval
        self._clock = clock
        self._flags = flags
        self._tags: dict = {}
        self._origin = clock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.rows: list = []
        self.throttle_flags_seen: set = set()

    def tag(self, **tags: object) -> None:
        """Sets the tags added to later rows and restarts the clock (`t_seconds` counts from now)."""
        with self._lock:
            self._tags = dict(tags)
            self._origin = self._clock()

    def poll_once(self) -> list:
        """Takes one sample of every perf container and returns (and stores) its rows."""
        names = self._docker.project_resources()["containers"]
        taken: list = []
        if names:
            result = self._docker.docker("stats", "--no-stream", "--format", "{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}", *names, timeout=60)
            if result.ok:
                with self._lock:
                    elapsed = round(self._clock() - self._origin, 1)
                    for line in result.out.splitlines():
                        row = parse_stats_line(line)
                        if row:
                            row.update(self._tags)
                            row["t_seconds"] = elapsed
                            taken.append(row)
                    self.rows.extend(taken)
        flag = self._flags()
        if flag and flag != "0x0":
            self.throttle_flags_seen.add(flag)
        return taken

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = self._clock()
            self.poll_once()
            self._stop.wait(max(0.0, self._interval - (self._clock() - started)))

    def start(self) -> None:
        """Starts polling on a background thread."""
        self._thread = threading.Thread(target=self._loop, name="perf-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stops polling."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=90)

    def peak_mib(self, service: str, **match: object) -> float:
        """Highest memory (MiB) seen for `service` among rows whose tags equal `match`."""
        with self._lock:
            values = [r["mem_mib"] for r in self.rows if r["service"] == service and all(r.get(k) == v for k, v in match.items())]
        return max(values) if values else 0.0


def total_container_memory_gib(docker: PerfDocker) -> Optional[float]:
    """Memory (GiB) all running containers on this Docker engine use, perf or not (read-only `docker stats`).

    Used on Docker Desktop, whose VM is shared by every container, to see how much of it is already taken. None if
    it cannot be read.
    """
    result = docker.docker("stats", "--no-stream", "--format", "{{.MemUsage}}", timeout=60)
    if not result.ok:
        return None
    total = 0.0
    for line in result.out.splitlines():
        match = _USAGE.match(line)
        if match:
            try:
                total += to_mib(match.group(1), match.group(2))
            except ValueError:
                continue
    return total / 1024
