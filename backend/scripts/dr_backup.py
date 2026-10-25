"""
Module: scripts.dr_backup

Command-line entry point for the disaster-recovery backup tool (`app.services.dr_backup`). Runs in the
`backup` image, which has the backend code, `pg_dump` 16, `restic` and `age`.

Usage (configuration comes from `BACKUP_*`, `DATABASE_URL` and `STORAGE_*` environment variables):

    python scripts/dr_backup.py run                       # one backup: dump, mirror, snapshot, copy, prune, check
    python scripts/dr_backup.py bundle --output FILE      # latest set as one age-encrypted tar for scp or a USB disk
    python scripts/dr_backup.py schedule                  # stay running and back up on BACKUP_SCHEDULE (the `backup-scheduler` service)
    python scripts/dr_backup.py health                    # exit 0 if the scheduler's heartbeat is recent (container health probe)

Exit status: 0 success, 1 the run failed (see `status.json`; a failed destination counts; for `health`, the
scheduler is not alive), 2 unusable configuration, 75 another backup is already running. Output is one line per outcome and never contains a
secret, a key or row content.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from app.services.dr_backup import (  # noqa: E402
    EX_TEMPFAIL,
    AlreadyRunning,
    BackupConfig,
    BackupError,
    previous_success,
    restic_from_environment,
    run_backup_from_environment,
    write_bundle,
)
from app.services.dr_restic import ResticError  # noqa: E402
from app.services.dr_schedule import ScheduleError, Scheduler, is_healthy, settings_from_environment  # noqa: E402


def serve_schedule(config: BackupConfig) -> int:
    """Runs the in-container schedule until SIGTERM or SIGINT.

    Args:
        config: Tool settings; `expected_interval_hours` is taken from the schedule unless set explicitly.

    Returns:
        0 after a clean stop, 2 if `BACKUP_SCHEDULE` is missing or invalid.
    """
    try:
        schedule, settings = settings_from_environment()
    except ScheduleError as exc:
        print(f"invalid backup schedule: {exc}", file=sys.stderr)
        return 2
    if not os.environ.get("BACKUP_EXPECTED_INTERVAL_HOURS", "").strip():
        config = config.model_copy(update={"expected_interval_hours": schedule.period_seconds / 3600})

    def run() -> bool:
        """One scheduled backup. Never raises: a failure is logged and the status file says why."""
        try:
            report = run_backup_from_environment(config)
        except AlreadyRunning as exc:
            print(f"scheduler: skipped: {exc}", flush=True)
            return True
        except Exception as exc:  # the loop must outlive any one run; the class is enough to act on
            print(f"scheduler: backup could not start: {type(exc).__name__}", file=sys.stderr, flush=True)
            return False
        if report.result != "ok":
            print(f"scheduler: backup {report.set_id} failed at step '{report.step}': {report.error}", file=sys.stderr, flush=True)
        return report.result == "ok"

    scheduler = Scheduler(schedule, settings, config.status_dir, run, lambda: previous_success(config.status_dir))
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: scheduler.stop())
    print(f"scheduler: {os.environ['BACKUP_SCHEDULE']} ({settings.timezone})", flush=True)
    scheduler.serve()
    return 0


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
    sub.add_parser("schedule", help="stay running and take a backup at each time in BACKUP_SCHEDULE")
    sub.add_parser("health", help="exit 0 if the scheduler's heartbeat is recent")
    args = parser.parse_args(argv)

    try:
        config = BackupConfig()
    except ValueError as exc:
        print(f"invalid backup configuration: {exc}", file=sys.stderr)
        return 2
    if args.command == "health":
        return 0 if is_healthy(config.status_dir) else 1
    if args.command == "schedule":
        return serve_schedule(config)

    if args.command == "bundle":
        try:
            write_bundle(config, restic_from_environment(config), args.recipient, args.output)
        except (BackupError, ResticError) as exc:
            print(f"bundle failed: {exc}", file=sys.stderr)
            return 1
        print(f"bundle written to {args.output}")
        return 0

    try:
        report = run_backup_from_environment(config)
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
