"""
Module: perf.lib.resources

Resource limits, the headroom preflight and the pressure watchdog that bound what a run can do to a shared host.

Responsibilities:
- Split the operator's CPU and memory budget across the stack's services (`plan_caps`) and estimate disk use.
- Refuse to start unless the host has the stated headroom free (`preflight_headroom`).
- Watch host load, available memory, swap and free disk during a run, and an optional health URL, and trip when a
  threshold is crossed (`Watchdog`), so the runner can stop and tear the stack down.

Design decisions:
- Isolating the data does not isolate the hardware: the perf stack shares CPU, memory, I/O and network with
  whatever else runs on the host. Caps bound the damage, the preflight refuses to start without headroom, and the
  watchdog stops the run; none of these makes a shared host risk-free (documented in `perf/README.md`).
- Defaults are conservative: at most half the host's cores and a quarter of its memory. `--dedicated` raises them
  for a machine that runs nothing else.
- The watchdog stops the run rather than pausing it first: the safer behaviour for a production neighbour.
- The `--watch-url` probe only issues GET, carries no credentials and follows no redirects.

Dependencies: standard library only (Python 3.9+).
"""

from __future__ import annotations

import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

GIB = 2**30
#: Memory (GiB) the non-backend services get: a share of the budget, never below the floor.
SERVICE_MEMORY = {"db": (0.25, 0.9), "storage": (0.07, 0.25), "loadgen": (0.10, 0.4)}
#: Share of the CPU budget each service gets.
CPU_SHARE = {"backend": 0.5, "db": 0.25, "storage": 0.05, "loadgen": 0.20}
#: Backend memory floor: each uvicorn worker imports the whole application separately (about 0.45 GiB each), plus a
#: base for the parent process and request buffers. A smaller cap puts the workers under constant OOM pressure.
BACKEND_BASE_GIB = 0.5
BACKEND_PER_WORKER_GIB = 0.5
IMAGES_GIB = 4.0
PER_REQUIREMENT_KIB = 40


DEFAULT_WORKERS = 4
"""The production default (`BACKEND_WORKERS`); automatic selection never exceeds it, so a larger host is not silently profiled
at a worker count the default deployment does not use. Pass `--workers N` to go beyond."""


class ResourceError(Exception):
    """The host cannot safely run the stack as asked; the message says what to change."""


@dataclass(frozen=True)
class Caps:
    """The limits the stack runs under.

    Attributes:
        cpus: Total CPUs for the stack.
        memory_gib: Total memory for the stack.
        per_service: `{service: {"cpus": float, "mem": "<n>m"}}` for the compose env file.
        workers: Backend worker processes (`BACKEND_WORKERS`).
        workers_auto: Whether `workers` was chosen from the budget rather than named by the operator.
    """

    cpus: float
    memory_gib: float
    per_service: dict
    workers: int = DEFAULT_WORKERS
    workers_auto: bool = False

    def env(self) -> dict:
        """The `PERF_*_CPUS` / `PERF_*_MEM` variables the compose override reads."""
        values: dict = {}
        for service, limits in self.per_service.items():
            values[f"PERF_{service.upper()}_CPUS"] = f"{limits['cpus']:.2f}"
            values[f"PERF_{service.upper()}_MEM"] = limits["mem"]
        return values

    def as_dict(self) -> dict:
        """The caps as recorded in `run.json`.

        Floats are rounded: `1.2000000000000002` is a 16-character run of hex digits that the anonymisation check
        rightly treats as a possible serial number.
        """
        per_service = {name: {**limits, "cpus": round(limits["cpus"], 2)} if "cpus" in limits else limits for name, limits in self.per_service.items()}
        return {"cpus": round(self.cpus, 2), "memory_gib": round(self.memory_gib, 2), "per_service": per_service}


def backend_floor_gib(workers: int) -> float:
    """The least memory (GiB) the backend can run in with `workers` worker processes."""
    return BACKEND_BASE_GIB + BACKEND_PER_WORKER_GIB * workers


def minimum_budget_gib(workers: int) -> float:
    """The least total budget (GiB) the stack can run in with `workers` backend workers."""
    return backend_floor_gib(workers) + sum(floor for _share, floor in SERVICE_MEMORY.values())


def other_services_memory_gib(memory_gib: float) -> dict:
    """Memory (GiB) each non-backend service gets from a budget: its share, never below its floor."""
    return {service: max(floor, memory_gib * share) for service, (share, floor) in SERVICE_MEMORY.items()}


def backend_memory_gib(memory_gib: float) -> float:
    """Memory (GiB) the backend gets from a budget: whatever the other services leave."""
    return memory_gib - sum(other_services_memory_gib(memory_gib).values())


def auto_workers(cpus: float, memory_gib: float) -> int:
    """The backend worker count a budget supports: as many as the CPUs and the memory allow, up to the default.

    Args:
        cpus: The stack's CPU budget.
        memory_gib: The stack's memory budget.

    Returns:
        1 to `DEFAULT_WORKERS`.

    Raises:
        ResourceError: If the budget cannot run even one worker.
    """
    if memory_gib < minimum_budget_gib(1):
        raise ResourceError(
            f"a {memory_gib:.2f} GiB budget is below the {minimum_budget_gib(1):.2f} GiB the stack needs even with one backend worker; "
            "raise --max-mem or run on a larger host"
        )
    by_memory = int((backend_memory_gib(memory_gib) - BACKEND_BASE_GIB) / BACKEND_PER_WORKER_GIB)
    return max(1, min(DEFAULT_WORKERS, int(cpus), by_memory))


def plan_caps(
    docker_cores: int, docker_ram_gib: float, *, max_cpus: Optional[float] = None, max_mem_gib: Optional[float] = None,
    dedicated: bool = False, docker_vm: bool = False, workers: Optional[int] = None,
) -> Caps:
    """Chooses the stack's limits.

    Args:
        docker_cores / docker_ram_gib: What Docker can use (the VM's allocation on Docker Desktop).
        max_cpus / max_mem_gib: The operator's budget; defaults are half the cores and a quarter of the memory (half
            when Docker runs in a VM, which is already a limit on the machine), or all cores and 85% of memory when
            `dedicated`.
        dedicated: The host runs nothing else.
        docker_vm: Docker runs in a VM (Docker Desktop), so `docker_ram_gib` is that VM's allocation.
        workers: Backend worker processes, or None to choose the most the CPU and memory budget supports
            (`auto_workers`). The backend's share is whatever the other services leave, and must cover
            `backend_floor_gib(workers)`.

    Returns:
        The caps.

    Raises:
        ResourceError: If the budget exceeds what Docker has, or is below what the stack needs to start.
    """
    cpus = max_cpus if max_cpus is not None else (docker_cores if dedicated else max(1.0, docker_cores / 2))
    memory = max_mem_gib if max_mem_gib is not None else (docker_ram_gib * 0.85 if dedicated else docker_ram_gib / (2 if docker_vm else 4))
    if cpus > docker_cores:
        raise ResourceError(f"--max-cpus {cpus:g} is more than the {docker_cores} CPUs Docker can use")
    if memory > docker_ram_gib:
        raise ResourceError(f"--max-mem {memory:g} GiB is more than the {docker_ram_gib:.1f} GiB Docker can use")
    chosen = auto_workers(cpus, memory) if workers is None else workers
    need = minimum_budget_gib(chosen)
    if memory < need:
        raise ResourceError(
            f"a {memory:.2f} GiB budget is below the {need:.2f} GiB the stack needs with {chosen} backend workers; raise --max-mem "
            "(or use --dedicated on a machine that runs nothing else), lower --workers, or run on a larger host"
        )
    if backend_memory_gib(memory) < backend_floor_gib(chosen):
        raise ResourceError(
            f"with a {memory:.2f} GiB budget the backend gets {backend_memory_gib(memory):.2f} GiB, below the {backend_floor_gib(chosen):.2f} GiB "
            f"{chosen} workers need; raise --max-mem or lower --workers"
        )
    memories = {"backend": backend_memory_gib(memory), **other_services_memory_gib(memory)}
    per_service = {
        service: {"cpus": max(0.25, cpus * CPU_SHARE[service]), "mem": f"{int(memories[service] * 1024)}m"}
        for service in CPU_SHARE
    }
    return Caps(cpus=cpus, memory_gib=memory, per_service=per_service, workers=chosen, workers_auto=workers is None)


def estimate_disk_gib(total_requirements: int) -> float:
    """Disk the images, the database and a snapshot of it will take for a dataset of this size."""
    return IMAGES_GIB + total_requirements * PER_REQUIREMENT_KIB / 1024 / 1024


def disk_free_gib(path: Path) -> float:
    """Free space (GiB) on the filesystem holding `path`."""
    return shutil.disk_usage(path).free / GIB


def available_memory_gib() -> Optional[float]:
    """Memory available to new work in GiB (`MemAvailable` on Linux); None where it cannot be read."""
    try:
        match = re.search(r"MemAvailable:\s*(\d+) kB", Path("/proc/meminfo").read_text())
    except OSError:
        return None
    return int(match.group(1)) / 1024 / 1024 if match else None


def swap_used_gib() -> Optional[float]:
    """Swap in use in GiB (Linux); None where it cannot be read."""
    try:
        text = Path("/proc/meminfo").read_text()
    except OSError:
        return None
    total, free = re.search(r"SwapTotal:\s*(\d+) kB", text), re.search(r"SwapFree:\s*(\d+) kB", text)
    return (int(total.group(1)) - int(free.group(1))) / 1024 / 1024 if total and free else None


def load_per_core() -> Optional[float]:
    """The 1-minute load average divided by the core count; None if unavailable."""
    try:
        return os.getloadavg()[0] / (os.cpu_count() or 1)
    except (OSError, AttributeError):
        return None


@dataclass
class Thresholds:
    """Limits beyond which the watchdog trips.

    Attributes:
        max_load_per_core: Load average per core.
        min_available_gib: Least available memory (Linux).
        max_swap_growth_gib: Most the swap in use may grow during the run (Linux). Swap already in use when the
            run starts is not pressure by itself (a long-running server holds idle pages there); growth during the
            run is.
        min_free_disk_gib: Least free disk where the stack stores data.
        watch_max_seconds: Slowest acceptable answer from `--watch-url`.
        watch_failures: Consecutive slow or failed probes that trip it.
    """

    max_load_per_core: float = 1.5
    min_available_gib: float = 1.0
    max_swap_growth_gib: float = 0.25
    min_free_disk_gib: float = 5.0
    watch_max_seconds: float = 3.0
    watch_failures: int = 3


def preflight_headroom(
    caps: Caps, *, total_requirements: int, disk_path: Path, thresholds: Optional[Thresholds] = None,
    load: Callable = load_per_core, available: Callable = available_memory_gib, swap: Callable = swap_used_gib, free_disk: Callable = disk_free_gib,
) -> list:
    """Checks the host has the stated headroom free, after the caps.

    Args:
        caps: The limits the stack will run under.
        total_requirements: Requirements the dataset will hold (for the disk estimate).
        disk_path: A path on the filesystem the stack and its snapshot use.
        thresholds: Limits (defaults).
        load / available / swap / free_disk: Readers (replaced in tests).

    Returns:
        Reasons the run must not start; empty when there is headroom.
    """
    limits = thresholds or Thresholds()
    reasons = []
    current_load = load()
    if current_load is not None and current_load + caps.cpus / (os.cpu_count() or 1) > limits.max_load_per_core:
        reasons.append(f"the host is already busy (load {current_load:.2f} per core); the run would push it past {limits.max_load_per_core:g}")
    free = available()
    if free is not None and free - caps.memory_gib < limits.min_available_gib:
        reasons.append(f"only {free:.1f} GiB of memory is available; the {caps.memory_gib:.1f} GiB budget would leave under {limits.min_available_gib:g} GiB")
    # Existing swap is only a problem when the memory left after the caps could not take it back: then the
    # first pressure would push the kernel to kill something, and it may not be the perf stack.
    used_swap = swap()
    if used_swap and free is not None and free - caps.memory_gib < used_swap + limits.min_available_gib:
        reasons.append(
            f"the host is using {used_swap:.1f} GiB of swap and only {free - caps.memory_gib:.1f} GiB of memory would be left "
            f"after the {caps.memory_gib:.1f} GiB budget, which could not absorb it"
        )
    need = estimate_disk_gib(total_requirements)
    disk = free_disk(disk_path)
    if disk - need < limits.min_free_disk_gib:
        reasons.append(f"disk: {disk:.1f} GiB free, the run needs about {need:.1f} GiB and must leave {limits.min_free_disk_gib:g} GiB")
    return reasons


@dataclass
class Watchdog:
    """Samples host pressure on a thread and trips when a threshold is crossed.

    Args:
        thresholds: The limits.
        disk_path: Where to measure free disk.
        watch_url: A health URL to probe with GET (production's `/health`), or None.
        interval: Seconds between samples.
        readers: Replaceable readers `load`, `available`, `swap`, `free_disk`, `probe` (for tests).
        on_trip: Called once, on the watchdog's thread, with the reason (the runner stops the load there).

    Attributes:
        reason: Why it tripped, or None.
        swap_baseline: Swap in use (GiB) when sampling began; growth beyond `max_swap_growth_gib` trips. Taken from
            the first sample when not given.
    """

    thresholds: Thresholds
    disk_path: Path
    watch_url: Optional[str] = None
    interval: float = 5.0
    readers: dict = field(default_factory=dict)
    on_trip: Optional[Callable[[str], None]] = None
    reason: Optional[str] = None
    swap_baseline: Optional[float] = None

    def __post_init__(self) -> None:
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._failures = 0

    @property
    def tripped(self) -> bool:
        """Whether a threshold was crossed."""
        return self.reason is not None

    def probe(self) -> tuple:
        """One GET of the watch URL: `(ok, seconds)`. No credentials, no redirects, `ok` false on error or non-2xx."""
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):  # noqa: D102
                return None

        opener = urllib.request.build_opener(_NoRedirect)
        started = time.monotonic()
        try:
            with opener.open(urllib.request.Request(self.watch_url, method="GET"), timeout=10) as response:  # noqa: S310
                return 200 <= response.status < 300, time.monotonic() - started
        except (urllib.error.URLError, OSError, ValueError):
            return False, time.monotonic() - started

    def check_once(self) -> Optional[str]:
        """Takes one sample and returns the reason it trips, else None (also records it in `reason`)."""
        reader = lambda name, default: self.readers.get(name, default)  # noqa: E731
        limits = self.thresholds
        load = reader("load", load_per_core)()
        if load is not None and load > limits.max_load_per_core:
            return self._trip(f"host load {load:.2f} per core exceeds {limits.max_load_per_core:g}")
        free = reader("available", available_memory_gib)()
        if free is not None and free < limits.min_available_gib:
            return self._trip(f"available memory {free:.1f} GiB is below {limits.min_available_gib:g}")
        swap = reader("swap", swap_used_gib)()
        if swap is not None:
            if self.swap_baseline is None:
                self.swap_baseline = swap
            if swap - self.swap_baseline > limits.max_swap_growth_gib:
                return self._trip(
                    f"swap use grew by {swap - self.swap_baseline:.2f} GiB during the run (limit {limits.max_swap_growth_gib:g})"
                )
        disk = reader("free_disk", disk_free_gib)(self.disk_path)
        if disk < limits.min_free_disk_gib:
            return self._trip(f"free disk {disk:.1f} GiB is below {limits.min_free_disk_gib:g}")
        if self.watch_url:
            ok, seconds = reader("probe", self.probe)()
            self._failures = 0 if ok and seconds <= limits.watch_max_seconds else self._failures + 1
            if self._failures >= limits.watch_failures:
                return self._trip(f"the watched health URL was slow or failing {self._failures} times in a row")
        return None

    def _trip(self, reason: str) -> str:
        self.reason = reason
        return reason

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            reason = self.check_once()
            if reason:
                if self.on_trip:
                    self.on_trip(reason)
                return

    def start(self) -> None:
        """Starts sampling on a background thread, taking the swap baseline now so growth is measured from the start."""
        if self.swap_baseline is None:
            self.swap_baseline = self.readers.get("swap", swap_used_gib)()
        self._thread = threading.Thread(target=self._loop, name="perf-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stops sampling."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
