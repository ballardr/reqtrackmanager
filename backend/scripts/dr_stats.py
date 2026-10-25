"""
Module: scripts.dr_stats

Command-line entry point for the disaster-recovery statistics (`app.services.dr_stats`) and the backup
manifest contract (`app.services.dr_manifest`). Run inside the backend image so the backup tool and the
restore verifier use the same code.

Usage (from `backend/`, with the database and storage environment of the target):

    python scripts/dr_stats.py                          # print the stats document as JSON
    python scripts/dr_stats.py --snapshot 00000003-0000001B-1   # read a pg_dump --snapshot's view
    python scripts/dr_stats.py --no-storage-probe       # skip the object-store probe
    python scripts/dr_stats.py --compare manifest.json  # verify against a manifest or stats file
    python scripts/dr_stats.py --manifest-schema        # print the manifest JSON Schema

Exit status: 0 when healthy (and equal, with `--compare`), 1 when a probe fails or a statistic differs,
2 when the input cannot be used. Output holds counts and ids only, never row content or secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from app.services.dr_manifest import load_manifest, manifest_json_schema  # noqa: E402
from app.services.dr_stats import DrStats, collect_stats, compare_stats, probe_failures  # noqa: E402


def _load_expected(path: Path) -> DrStats:
    """Reads the expected document from a manifest (its `stats`) or a bare stats file.

    Raises:
        ValueError: If the file is neither.
    """
    text = path.read_text()
    raw = json.loads(text)
    if isinstance(raw, dict) and "stats" in raw:
        return load_manifest(text).stats
    return DrStats.model_validate(raw)


def main(argv: list[str] | None = None) -> int:
    """Runs the CLI.

    Args:
        argv: Arguments (default `sys.argv[1:]`).

    Returns:
        The process exit status (see the module docstring).
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", help="snapshot id exported by pg_export_snapshot()")
    parser.add_argument("--no-storage-probe", action="store_true", help="do not check file records against the object store")
    parser.add_argument("--compare", type=Path, help="manifest.json or stats JSON to verify against")
    parser.add_argument("--manifest-schema", action="store_true", help="print the manifest JSON Schema and exit")
    args = parser.parse_args(argv)

    if args.manifest_schema:
        print(json.dumps(manifest_json_schema(), indent=2))
        return 0

    from sqlalchemy.orm import Session

    from app.database import engine
    from app.services.files import get_storage_backend

    try:
        expected = _load_expected(args.compare) if args.compare else None
    except (OSError, ValueError) as exc:
        print(f"cannot read --compare file: {exc}", file=sys.stderr)
        return 2

    storage = None if args.no_storage_probe else get_storage_backend()
    with Session(engine) as db:
        stats = collect_stats(db, storage, snapshot_id=args.snapshot)
        db.rollback()

    failures = probe_failures(stats)
    mismatches = compare_stats(expected, stats) if expected is not None else []
    print(stats.model_dump_json(indent=2))
    for line in failures:
        print(f"PROBE FAILED: {line}", file=sys.stderr)
    for mismatch in mismatches:
        print(f"MISMATCH {mismatch.path}: expected {mismatch.expected!r}, got {mismatch.actual!r}", file=sys.stderr)
    return 1 if failures or mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
