"""
Module: scripts.dr_backup

Command-line entry point for the disaster-recovery backup tool (`app.services.dr_backup`). Runs in the
`backup` image, which has the backend code, `pg_dump` 16, `restic` and `age`.

Usage (configuration comes from `BACKUP_*`, `DATABASE_URL` and `STORAGE_*` environment variables):

    python scripts/dr_backup.py run                       # one backup: dump, mirror, snapshot, copy, prune, check
    python scripts/dr_backup.py bundle --output FILE      # latest set as one age-encrypted tar for scp or a USB disk

Exit status: 0 success, 1 the run failed (see `status.json`; a failed destination counts), 2 unusable
configuration, 75 another backup is already running. Output is one line per outcome and never contains a
secret, a key or row content.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from app.services.dr_backup import (  # noqa: E402
    EX_TEMPFAIL,
    AlreadyRunning,
    BackupConfig,
    BackupError,
    deps_from_environment,
    run_backup,
    write_bundle,
)
from app.services.dr_restic import ResticError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Runs the CLI.

    Args:
        argv: Arguments (default `sys.argv[1:]`).

    Returns:
        The process exit status (see the module docstring).
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="take one backup")
    bundle = sub.add_parser("bundle", help="write the latest set as one age-encrypted tar")
    bundle.add_argument("--output", type=Path, required=True)
    bundle.add_argument(
        "--recipient", default=os.environ.get("BACKUP_BUNDLE_AGE_RECIPIENT", ""), help="age public key (default BACKUP_BUNDLE_AGE_RECIPIENT)"
    )
    args = parser.parse_args(argv)

    try:
        config = BackupConfig()
    except ValueError as exc:
        print(f"invalid backup configuration: {exc}", file=sys.stderr)
        return 2
    deps = deps_from_environment(config)

    if args.command == "bundle":
        try:
            write_bundle(config, deps.restic, args.recipient, args.output)
        except (BackupError, ResticError) as exc:
            print(f"bundle failed: {exc}", file=sys.stderr)
            return 1
        print(f"bundle written to {args.output}")
        return 0

    try:
        report = run_backup(config, deps)
    except AlreadyRunning as exc:
        print(str(exc), file=sys.stderr)
        return EX_TEMPFAIL
    if report.result == "ok":
        print(f"backup {report.set_id} ok: snapshot {report.snapshot_id}, {report.bytes_added} bytes added")
        return 0
    print(f"backup {report.set_id} FAILED at step '{report.step}': {report.error}", file=sys.stderr)
    for dest in report.destinations:
        print(f"  destination {dest.target}: {'ok' if dest.ok else 'FAILED ' + (dest.error or '')}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
