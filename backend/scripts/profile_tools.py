#!/usr/bin/env python3
"""
Module: profile_tools

In-container helpers for backend profiling, run with `docker compose exec backend python scripts/profile_tools.py`.
They only read: process memory from `/proc`, the files profile mode writes (`app.profiling`) and, for `heap`, a
memray capture. Each prints one JSON document.

Responsibilities:
- `memory`: resident, proportional and private memory per backend process (parent, workers, resource tracker),
  which separates what every worker holds privately from what the processes share.
- `queries`: the per-route database statement totals of every worker, merged.
- `snapshot`: `memory` and `queries` together (one exec per measurement point).
- `rebaseline`: ask workers that track allocations to take a new baseline (`SIGUSR2`).
- `heap <capture>`: the memory a memray capture still held at exit, by source line and by package.

Design decisions:
- Output carries sizes, counts, route templates, parameterised statement text and paths relative to `/app` or
  `site-packages`; never environment, arguments, values or absolute paths.
- Standard library only, apart from `memray` for `heap` (present in the profile image only).
- A signal is sent only to a process that is verifiably a backend worker, because the default action of `SIGUSR2`
  is to terminate.

Dependencies: Linux `/proc` (`smaps_rollup`); `memray` for `heap`.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_DIR = os.environ.get("PROFILE_OUTPUT_DIR", "/tmp/profile")
PROC = Path("/proc")
"""The process table; a test points it at a fake tree."""
MIB = 1024 * 1024
HEAP_TOP = 40


def _cmdline(pid: int) -> str:
    """The process's command line with NULs as spaces, or "" if it has gone."""
    try:
        return (PROC / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


def _smaps(pid: int) -> dict | None:
    """Memory totals of one process in kibibytes (`Rss`, `Pss`, `Private`, `Shared`), or None if unreadable."""
    values: dict = {}
    try:
        for line in (PROC / str(pid) / "smaps_rollup").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2] == "kB":
                values[parts[0].rstrip(":")] = int(parts[1])
    except OSError:
        return None
    if "Rss" not in values:
        return None
    return {
        "Rss": values["Rss"],
        "Pss": values.get("Pss", 0),
        "Private": values.get("Private_Clean", 0) + values.get("Private_Dirty", 0),
        "Shared": values.get("Shared_Clean", 0) + values.get("Shared_Dirty", 0),
    }


def is_worker(pid: int) -> bool:
    """Whether `pid` is a uvicorn worker (a `multiprocessing` spawn child)."""
    return "multiprocessing.spawn" in _cmdline(pid)


def memory() -> dict:
    """Memory per backend process.

    Returns:
        `{"processes": [{"role", "index", "rss_mib", "pss_mib", "private_mib", "shared_mib"}], "pss_total_mib"}`.
        `role` is `parent`, `worker`, `tracker` or `single` (one process serving requests, no workers). PSS divides
        shared pages between the processes that map them, so the PSS total is the real footprint.
    """
    pids = sorted(int(name) for name in os.listdir(PROC) if name.isdigit())
    workers = [pid for pid in pids if is_worker(pid)]
    rows = []
    for pid in pids:
        if pid == 1:
            role = "parent" if workers else "single"
        elif pid in workers:
            role = "worker"
        elif "multiprocessing.resource_tracker" in _cmdline(pid):
            role = "tracker"
        else:
            continue
        stats = _smaps(pid)
        if stats is None:
            continue
        rows.append((role, pid, stats))
    order = {"single": 0, "parent": 0, "worker": 1, "tracker": 2}
    rows.sort(key=lambda row: (order[row[0]], row[1]))
    counters: dict = defaultdict(int)
    processes = []
    total = 0
    for role, _pid, stats in rows:
        counters[role] += 1
        total += stats["Pss"]
        processes.append(
            {
                "role": role,
                "index": counters[role],
                "rss_mib": round(stats["Rss"] / 1024, 1),
                "pss_mib": round(stats["Pss"] / 1024, 1),
                "private_mib": round(stats["Private"] / 1024, 1),
                "shared_mib": round(stats["Shared"] / 1024, 1),
            }
        )
    return {"processes": processes, "pss_total_mib": round(total / 1024, 1)}


def queries(directory: Path) -> dict:
    """The database statement totals of every worker, merged.

    Args:
        directory: The profile output directory.

    Returns:
        `{route key: {"requests", "queries", "db_ms", "max_queries", "repeat_statement", "repeat_count"}}`; empty when
        profile mode wrote nothing (an image without it, or the flag off).
    """
    merged: dict = {}
    for path in sorted(directory.glob("query_stats_*.json")):
        try:
            document = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for key, stats in document.get("routes", {}).items():
            into = merged.setdefault(key, {"requests": 0, "queries": 0, "db_ms": 0.0, "max_queries": 0, "repeat_statement": "", "repeat_count": 0})
            into["requests"] += stats["requests"]
            into["queries"] += stats["queries"]
            into["db_ms"] = round(into["db_ms"] + stats["db_ms"], 3)
            into["max_queries"] = max(into["max_queries"], stats["max_queries"])
            if stats["repeat_count"] > into["repeat_count"]:
                into["repeat_statement"], into["repeat_count"] = stats["repeat_statement"], stats["repeat_count"]
    return merged


def rebaseline(directory: Path) -> dict:
    """Asks every worker that tracks allocations to take a new baseline.

    Args:
        directory: The profile output directory.

    Returns:
        `{"signalled": [pids]}`.
    """
    signalled = []
    for path in sorted(directory.glob("tracemalloc_*.json")):
        pid = int(path.stem.rsplit("_", 1)[1])
        if is_worker(pid) or pid == 1:
            os.kill(pid, signal.SIGUSR2)
            signalled.append(pid)
    return {"signalled": signalled}


def _location(filename: str) -> str:
    for marker in ("/site-packages/", "/app/"):
        if marker in filename:
            return filename.split(marker, 1)[1]
    return os.path.basename(filename)


def _package(filename: str) -> str:
    """Groups a source file: `site-packages/<package>`, `app/<area>` (`app/modules/<module>`), `stdlib` or `other`."""
    if "/site-packages/" in filename:
        return "site-packages/" + filename.split("/site-packages/", 1)[1].split("/", 1)[0].removesuffix(".py")
    if "/app/" in filename:
        parts = filename.split("/app/", 1)[1].split("/")
        if parts[0] == "app" and len(parts) > 1:
            parts = parts[1:]
        if parts[0] == "modules" and len(parts) > 2:
            return "app/modules/" + parts[1]
        return "app/" + parts[0].removesuffix(".py")
    if "/lib/python" in filename:
        return "stdlib"
    return "other"


def heap(capture: Path) -> dict:
    """What a memray capture still held when it ended, by source line and by package.

    Importing a module creates its code, classes and functions while the import machinery is on the stack, so the
    innermost frame that is not the import machinery is taken as the owner.

    Args:
        capture: A memray capture file.

    Returns:
        `{"live_mib", "peak_mib", "by_location": [...], "by_package": [...]}`, each entry carrying `mib` and
        `allocations`.
    """
    from memray import FileReader  # noqa: PLC0415 - only the profile image has memray

    reader = FileReader(str(capture))
    by_location: dict = defaultdict(lambda: [0, 0])
    by_package: dict = defaultdict(lambda: [0, 0])
    live = 0
    for record in reader.get_leaked_allocation_records(merge_threads=True):
        frames = record.stack_trace()
        owner = next((frame for frame in frames if not frame[1].startswith("<frozen")), frames[0] if frames else ("<unknown>", "<unknown>", 0))
        function, filename, line = owner
        live += record.size
        for bucket, key in ((by_location, f"{_location(filename)}:{line} {function}"), (by_package, _package(filename))):
            bucket[key][0] += record.size
            bucket[key][1] += record.n_allocations

    def table(bucket: dict, limit: int | None) -> list:
        ordered = sorted(bucket.items(), key=lambda item: -item[1][0])[:limit]
        return [{"name": name, "mib": round(size / MIB, 2), "allocations": count} for name, (size, count) in ordered]

    metadata = reader.metadata
    return {
        "live_mib": round(live / MIB, 1),
        "peak_mib": round(metadata.peak_memory / MIB, 1),
        "by_location": table(by_location, HEAP_TOP),
        "by_package": table(by_package, None),
    }


def main(argv: list | None = None) -> int:
    """Entry point; prints one JSON document and returns the exit status."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", type=Path, default=Path(DEFAULT_DIR), help="the profile output directory")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("memory", "queries", "snapshot", "rebaseline"):
        sub.add_parser(name)
    heap_parser = sub.add_parser("heap")
    heap_parser.add_argument("capture", type=Path)
    args = parser.parse_args(argv)
    if args.command == "memory":
        result = memory()
    elif args.command == "queries":
        result = queries(args.dir)
    elif args.command == "snapshot":
        result = {**memory(), "queries": queries(args.dir)}
    elif args.command == "rebaseline":
        result = rebaseline(args.dir)
    else:
        result = heap(args.capture)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
