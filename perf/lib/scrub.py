"""
Module: perf.lib.scrub

Checks that a results bundle (and `perf/results/` in general) contains only measurements and generic host
characteristics, nothing identifying.

Responsibilities:
- Fail on any file or field outside the allowlist, on the machine's own hostname and username, home-directory
  prefixes, MAC / IPv4 / IPv6 addresses, email addresses, serial-number shapes, 32/64-character hex ids and common
  token shapes.
- Report findings by file, line and rule only, never echoing the matched text (it may be the secret itself).

Design decisions:
- Results are committed to a public repository, so the check is a gate, not advice: the runner refuses to write an
  archive on a finding, a repository test scans `perf/results/`, and the pre-commit hook scans it when staged.
- File names and JSON/CSV keys are allowlisted; the pattern scan is the second layer for values.
- A 40-character hex string (a git commit) is deliberately not flagged; 32 and 64 are (container and image ids).

Dependencies: standard library only (Python 3.9+).
"""

from __future__ import annotations

import csv
import getpass
import io
import json
import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

#: Allowed files in a bundle and the keys (JSON) or columns (CSV) each may carry.
ALLOWED_FILES: dict = {
    "host.json": {
        "schema_version", "arch", "host_cores", "docker_cores", "host_ram_gib", "docker_ram_gib", "docker_vm", "os", "docker_version",
        "compose_version", "cpu_family", "storage", "virtualised", "python", "throttle_flags_seen",
    },
    "run.json": {
        "schema_version", "host_label", "commit", "date", "mode", "tiers", "breadth", "density", "seed", "profiles_version",
        "scenarios", "repeats", "workers", "workers_auto", "image_source", "caps", "shared_host", "non_publishable", "non_publishable_reasons",
        "aborted", "comparable_with", "durations_s", "scenario_users", "warmup_s", "measure_s", "snapshot_used", "startup_seconds",
        "migrations_applied", "notes", "profiling", "heap_live_mib", "heap_peak_mib", "postgres", "db_pool",
    },
    "dataset.json": {"schema_version", "datasets"},
    "samples.csv": {"tier", "scenario", "repeat", "service", "t_seconds", "mem_mib", "mem_limit_mib", "cpu_percent"},
    "latency.csv": {
        "tier", "scenario", "repeat", "users", "request", "count", "failures", "throttled", "p50_ms", "p95_ms", "p99_ms", "mean_ms",
        "max_ms", "rps", "bytes_mean",
    },
    "queries.csv": {"tier", "scenario", "request", "requests", "queries_per_request", "db_ms_per_request"},
    "processes.csv": {"tier", "scenario", "repeat", "role", "index", "rss_mib", "pss_mib", "private_mib", "shared_mib"},
    "heap.csv": {"kind", "name", "mib", "allocations"},
    "pgstat.csv": {"tier", "scenario", "calls", "total_ms", "mean_ms", "rows", "read_blocks", "temp_blocks", "query"},
    "pgdb.csv": {"tier", "scenario", "connections_peak", "idle_in_transaction_peak", "cache_hit_percent", "temp_files", "temp_mib", "deadlocks"},
    "plans.csv": {"tier", "scenario", "rank", "node", "relation", "index", "filtered", "est_rows", "plan_cost"},
}
#: Keys of each entry in `dataset.json`'s `datasets` list (one per tier run).
DATASET_ENTRY_KEYS = {"tier", "spec", "rows", "link_degree_histogram", "integrity_problems", "database_bytes", "generation_seconds"}
SAMPLE_COLUMNS = ("tier", "scenario", "repeat", "service", "t_seconds", "mem_mib", "mem_limit_mib", "cpu_percent")
LATENCY_COLUMNS = (
    "tier", "scenario", "repeat", "users", "request", "count", "failures", "throttled", "p50_ms", "p95_ms", "p99_ms", "mean_ms", "max_ms",
    "rps", "bytes_mean",
)
QUERY_COLUMNS = ("tier", "scenario", "request", "requests", "queries_per_request", "db_ms_per_request")
PROCESS_COLUMNS = ("tier", "scenario", "repeat", "role", "index", "rss_mib", "pss_mib", "private_mib", "shared_mib")
HEAP_COLUMNS = ("kind", "name", "mib", "allocations")
PGSTAT_COLUMNS = ("tier", "scenario", "calls", "total_ms", "mean_ms", "rows", "read_blocks", "temp_blocks", "query")
PGDB_COLUMNS = ("tier", "scenario", "connections_peak", "idle_in_transaction_peak", "cache_hit_percent", "temp_files", "temp_mib", "deadlocks")
PLAN_COLUMNS = ("tier", "scenario", "rank", "node", "relation", "index", "filtered", "est_rows", "plan_cost")
ALLOWED_SUFFIXES = (".svg",)
ROOT_FILES = ("README.md", ".gitkeep")

_PATTERNS = (
    ("home-directory path", re.compile(r"(?:/Users/|/home/|C:\\Users\\)[A-Za-z0-9._-]+")),
    ("MAC address", re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b")),
    ("IPv4 address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("IPv6 address", re.compile(
        r"\b(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}\b|\b[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4})*::(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4})*)?"
        r"|(?<![A-Za-z0-9:]):{2}[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4})*\b"
    )),
    ("email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+")),
    ("serial number", re.compile(r"(?i)serial(?:[ _-]?(?:number|no))?\s*[:=]\s*\S+")),
    ("serial-like 16 hex", re.compile(r"\b[0-9a-f]{16}\b")),
    ("32 or 64 character hex id", re.compile(r"\b(?:[0-9a-f]{32}|[0-9a-f]{64})\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*KEY-----")),
    ("password assignment", re.compile(r"(?i)(?:password|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]{6,}")),
)
_OPAQUE_STRING = re.compile(r"\b[A-Za-z0-9_-]{48,}\b")
#: A long snake_case name (a database index or alias such as `requirement_versions_requirement_id_version_number_key`)
#: is not a secret: random tokens are mixed-case or hex, and one made only of lowercase words joined by underscores
#: would also have to be 48+ characters of that shape by chance.
_SNAKE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}$")


@dataclass(frozen=True)
class Finding:
    """One problem found.

    Attributes:
        path: The file, relative to the scanned root.
        line: 1-based line (0 for a whole-file finding).
        rule: Which rule fired; never the matched text.
    """

    path: str
    line: int
    rule: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}" if self.line else f"{self.path}: {self.rule}"


def machine_identities() -> list:
    """Strings that identify this machine or its user and must not appear in results."""
    names = {socket.gethostname(), socket.gethostname().split(".")[0]}
    try:
        names.add(getpass.getuser())
    except Exception:  # noqa: BLE001
        pass
    names.add(os.environ.get("USER", ""))
    return sorted(n for n in names if len(n) >= 3)


def _scan_text(rel: str, text: str, identities: Iterable, *, opaque: bool) -> list:
    """Pattern findings for one file's text."""
    findings: list = []
    lowered = [(name, name.lower()) for name in identities]
    for number, line in enumerate(text.splitlines(), start=1):
        lower = line.lower()
        for _name, needle in lowered:
            if needle and re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", lower):
                findings.append(Finding(rel, number, "this machine's hostname or username"))
        for rule, pattern in _PATTERNS:
            if pattern.search(line):
                findings.append(Finding(rel, number, rule))
        if opaque and any(not _SNAKE_IDENTIFIER.match(token) for token in _OPAQUE_STRING.findall(line)):
            findings.append(Finding(rel, number, "long opaque string (possible secret)"))
    return findings


def _json_keys(document: object) -> set:
    return set(document) if isinstance(document, dict) else set()


def scan_file(path: Path, root: Path, identities: Iterable) -> list:
    """Findings for one file: allowlist (name, keys or columns) and pattern scan."""
    rel = str(path.relative_to(root))
    name = path.name
    findings: list = []
    text = path.read_text(errors="replace")
    if name in ALLOWED_FILES:
        allowed = ALLOWED_FILES[name]
        if name.endswith(".json"):
            try:
                keys = _json_keys(json.loads(text))
            except json.JSONDecodeError:
                return [Finding(rel, 0, "not valid JSON")]
            extra = keys - allowed
            if extra:
                findings.append(Finding(rel, 0, f"field outside the allowlist: {sorted(extra)[0]}"))
            if name == "dataset.json":
                for entry in json.loads(text).get("datasets", []):
                    bad = _json_keys(entry) - DATASET_ENTRY_KEYS
                    if bad:
                        findings.append(Finding(rel, 0, f"dataset field outside the allowlist: {sorted(bad)[0]}"))
        else:
            header = next(csv.reader(io.StringIO(text)), [])
            extra = set(header) - allowed
            if extra:
                findings.append(Finding(rel, 0, f"column outside the allowlist: {sorted(extra)[0]}"))
        opaque = True
    elif name.endswith(ALLOWED_SUFFIXES):
        opaque = False
    elif name in ROOT_FILES:
        opaque = False
    else:
        return [Finding(rel, 0, "file is not on the allowlist")]
    return findings + _scan_text(rel, text, identities, opaque=opaque)


def scan_tree(root: Path, identities: Optional[Iterable] = None) -> list:
    """Scans every file under `root`.

    Args:
        root: A bundle directory or `perf/results/`.
        identities: Strings to reject (defaults to `machine_identities()`).

    Returns:
        The findings, empty when clean. A symlink is itself a finding (it could point outside the tree).
    """
    names = list(machine_identities() if identities is None else identities)
    findings: list = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            findings.append(Finding(str(path.relative_to(root)), 0, "symbolic link"))
        elif path.is_file():
            findings.extend(scan_file(path, root, names))
    return findings
