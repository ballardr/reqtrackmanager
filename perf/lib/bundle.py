"""
Module: perf.lib.bundle

Writes a results bundle and its archive.

Responsibilities:
- Write `host.json`, `run.json`, `dataset.json`, `samples.csv`, `latency.csv`, `queries.csv`, `processes.csv`,
  `pgstat.csv`, `pgdb.csv`, `plans.csv` (and `heap.csv` and `profiles/*.svg` for a profiling run) into
  `perf/results/<host-label>/<date>-<commit>/` from in-memory results.
- Run the anonymisation check on the finished directory and refuse to produce an archive if it finds anything.
- Create the `.tar.gz` with numeric owners zeroed, normalised modification times and sorted entries, so no
  username, uid or timestamp rides along and the same bundle archives to the same bytes.

Design decisions:
- Only the files named in `lib.scrub.ALLOWED_FILES` are written, with exactly the columns it allows; the scrub
  check then verifies the result, so the writer and the checker cannot drift apart unnoticed.
- Dates only (`YYYY-MM-DD`); sample times are seconds since a scenario's start.

Dependencies: `perf.lib.scrub`; standard library only (Python 3.9+).
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import re
import tarfile
from pathlib import Path
from typing import Iterable, Optional

from perf.lib import scrub

RUN_SCHEMA_VERSION = 1
_SAFE_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")


class BundleError(Exception):
    """The bundle cannot be written or failed the anonymisation check; the message lists why."""


def bundle_dir(results_root: Path, host_label: str, date: str, commit: str) -> Path:
    """The directory for a run: `<results_root>/<host-label>/<date>-<short commit>`.

    Raises:
        BundleError: If the date or commit is not in the expected plain form.
    """
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date) or not _SAFE_COMMIT.match(commit):
        raise BundleError("bundle date must be YYYY-MM-DD and the commit a hex hash")
    return results_root / host_label / f"{date}-{commit[:8]}"


def unused_bundle_dir(directory: Path) -> Path:
    """`directory`, or `<directory>-2`, `-3`... when it exists, so a second run on the same day and commit never
    overwrites the first run's results."""
    candidate, number = directory, 1
    while candidate.exists():
        number += 1
        candidate = directory.with_name(f"{directory.name}-{number}")
    return candidate


def _write_json(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def _write_csv(path: Path, columns: Iterable, rows: Iterable) -> None:
    columns = list(columns)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_bundle(
    directory: Path, *, host: dict, run: dict, datasets: Iterable, samples: Iterable, latency: Iterable,
    queries: Iterable = (), pgstat: Iterable = (), pgdb: Iterable = (), plans: Iterable = (), processes: Iterable = (), heap: Optional[Iterable] = None,
    profiles: Optional[dict] = None,
) -> list:
    """Writes the bundle's files and checks them.

    Args:
        directory: Where to write (created).
        host: The `host.json` document.
        run: The `run.json` document.
        datasets: One entry per tier run (the dataset spec, row counts, link-degree histogram and size), written under
            `datasets` in `dataset.json`.
        samples / latency / queries / pgstat / pgdb / plans / processes: Rows for the CSV files.
        heap: Rows for `heap.csv`, or None to write no such file (only a heap-profiling run has one).
        profiles: `{file name: SVG text}` written under `profiles/` (CPU flamegraphs of a profiling run).

    Returns:
        The names of the files written.

    Raises:
        BundleError: If a document carries a field outside the allowlist, or the anonymisation check finds anything.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for name, document in (("host.json", host), ("run.json", run)):
        extra = set(document) - scrub.ALLOWED_FILES[name]
        if extra:
            raise BundleError(f"{name}: field outside the allowlist: {sorted(extra)[0]}")
        _write_json(directory / name, document)
    dataset_documents = list(datasets)
    for document in dataset_documents:
        extra = set(document) - scrub.DATASET_ENTRY_KEYS
        if extra:
            raise BundleError(f"dataset.json: field outside the allowlist: {sorted(extra)[0]}")
    _write_json(directory / "dataset.json", {"schema_version": RUN_SCHEMA_VERSION, "datasets": dataset_documents})
    _write_csv(directory / "samples.csv", scrub.SAMPLE_COLUMNS, samples)
    _write_csv(directory / "latency.csv", scrub.LATENCY_COLUMNS, latency)
    _write_csv(directory / "queries.csv", scrub.QUERY_COLUMNS, queries)
    _write_csv(directory / "pgstat.csv", scrub.PGSTAT_COLUMNS, pgstat)
    _write_csv(directory / "pgdb.csv", scrub.PGDB_COLUMNS, pgdb)
    _write_csv(directory / "plans.csv", scrub.PLAN_COLUMNS, plans)
    _write_csv(directory / "processes.csv", scrub.PROCESS_COLUMNS, processes)
    if heap is not None:
        _write_csv(directory / "heap.csv", scrub.HEAP_COLUMNS, heap)
    for name, text in sorted((profiles or {}).items()):
        if not re.match(r"^[a-z0-9][a-z0-9_.-]*\.svg$", name):
            raise BundleError(f"profile file name {name!r} is not a plain .svg name")
        (directory / "profiles").mkdir(exist_ok=True)
        (directory / "profiles" / name).write_text(text)
    findings = scrub.scan_tree(directory)
    if findings:
        raise BundleError("the bundle failed the anonymisation check:\n" + "\n".join(f"  {finding}" for finding in findings))
    return sorted(p.name for p in directory.iterdir())


def make_archive(directory: Path, destination: Optional[Path] = None) -> Path:
    """Creates `<directory>.tar.gz` with owners zeroed, times normalised and entries sorted.

    Args:
        directory: A bundle directory that has passed the anonymisation check.
        destination: The archive path (default beside the directory).

    Returns:
        The archive path.

    Raises:
        BundleError: If the directory fails the anonymisation check now.
    """
    findings = scrub.scan_tree(directory)
    if findings:
        raise BundleError("refusing to archive: " + "; ".join(str(f) for f in findings))
    archive = destination or directory.with_suffix(".tar.gz")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            info = tarfile.TarInfo(name=f"{directory.name}/{path.relative_to(directory).as_posix()}")
            data = path.read_bytes()
            info.size = len(data)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    with open(archive, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
        zipped.write(buffer.getvalue())
    return archive
