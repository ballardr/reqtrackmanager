"""
Module: scripts.dr_restore

Command-line entry point for the disaster-recovery restore tool (`app.services.dr_restore`). Runs in the
`backup` image, which has the backend code, `pg_restore` 16, `restic` and `age`.

Usage (configuration comes from `BACKUP_*`, `DATABASE_URL` and `STORAGE_*` environment variables):

    python scripts/dr_restore.py list                         # the sets in the repository, newest first
    python scripts/dr_restore.py restore fresh                # into an empty database and store (new host)
    python scripts/dr_restore.py restore in-place --yes       # replaces the live database; the old one is kept under a new name
    python scripts/dr_restore.py restore fresh --dry-run      # what would happen, and whether it is allowed
    python scripts/dr_restore.py config --age-identity FILE   # the set's .env, decrypted, on stdout
    python scripts/dr_restore.py manifest                     # the set's manifest (JSON) on stdout, nothing downloaded
    python scripts/dr_restore.py check [--subset 5%]          # repository structure plus a sample of its data

`restore` options: `--set` (`latest`, a set id or a snapshot id prefix), `--repository` (read an off-site copy
instead of the primary), `--clear-unreadable-secrets` (remove encrypted values the configured key cannot read),
`--force-reset [all|server_admins]` (with `--reset-2fa`: end every session, revoke access tokens and require a new
password on the restored copy before it goes live; no email is sent, so issue links afterwards with
`python -m app.cli.credentials issue-link`), `--report FILE` (always write the JSON report there).

Exit status: 0 success, 1 the restore failed or was refused (see `restore-report.json`; nothing live was
changed unless the report says `swap` completed), 2 unusable configuration, 75 a backup or another restore is
running. Output never contains a secret, a key or row content; `config` writes the plaintext `.env` to stdout
only, for the caller to redirect into a file with restrictive permissions.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from app.services.dr_backup import EX_TEMPFAIL, AlreadyRunning, BackupConfig, BackupError, require_password  # noqa: E402
from app.services.dr_manifest import dump_manifest  # noqa: E402
from app.services.dr_restic import ResticError  # noqa: E402
from app.services.dr_restore import (  # noqa: E402
    RestoreError,
    RestoreMode,
    RestoreOptions,
    decrypt_config,
    list_sets,
    read_manifest,
    resolve_set,
    restic_from_environment,
    restore_deps_from_environment,
    run_restore,
)


def _parser() -> argparse.ArgumentParser:
    """Builds the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="list the backup sets in the repository")
    listing.add_argument("--repository", help="repository to read instead of the primary")

    restore = sub.add_parser("restore", help="restore a set")
    restore.add_argument("mode", choices=[m.value for m in RestoreMode])
    restore.add_argument("--set", default="latest", dest="selector", help="latest, a set id, or a snapshot id prefix")
    restore.add_argument("--repository", help="repository to read instead of the primary")
    restore.add_argument("--dry-run", action="store_true", help="plan and check only; change nothing")
    restore.add_argument("--yes", action="store_true", help="confirm replacing the live database (in-place)")
    restore.add_argument("--clear-unreadable-secrets", action="store_true", help="remove encrypted values the configured key cannot decrypt")
    restore.add_argument(
        "--force-reset", nargs="?", const="all", choices=["all", "server_admins"], metavar="SCOPE",
        help="force a credential reset on the restored copy before it goes live (all, or server_admins; default all)",
    )
    restore.add_argument("--reset-2fa", action="store_true", help="with --force-reset, also clear two-factor enrolment")
    restore.add_argument("--report", type=Path, help="always write the JSON report here (default: the status directory, for real restores only)")
    restore.add_argument("--maintenance-db", default="postgres", help="database used to create, rename and drop databases")

    config = sub.add_parser("config", help="decrypt the set's .env snapshot to stdout")
    config.add_argument("--age-identity", type=Path, required=True, help="file holding the age identity (private key)")
    config.add_argument("--set", default="latest", dest="selector")
    config.add_argument("--repository", help="repository to read instead of the primary")

    manifest = sub.add_parser("manifest", help="print a set's manifest as JSON")
    manifest.add_argument("--set", default="latest", dest="selector")
    manifest.add_argument("--repository", help="repository to read instead of the primary")

    check = sub.add_parser("check", help="verify the repository's structure and a sample of its data")
    check.add_argument("--repository", help="repository to read instead of the primary")
    check.add_argument("--subset", help="share of data to read (5%% or 1/10; default BACKUP_CHECK_SUBSET; empty for structure only)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Runs the CLI.

    Args:
        argv: Arguments (default `sys.argv[1:]`).

    Returns:
        The process exit status (see the module docstring).
    """
    args = _parser().parse_args(argv)
    try:
        config = BackupConfig()
    except ValueError as exc:
        print(f"invalid configuration: {exc}", file=sys.stderr)
        return 2
    repository = args.repository or config.repository

    try:
        if args.command == "list":
            require_password(config.password_file)
            sets = list_sets(restic_from_environment(config), repository)
            if not sets:
                print("the repository holds no backup sets")
            for info in sets:
                print(f"{info.set_id}  snapshot {info.snapshot_id[:8]}  secrets {info.secrets_mode}  {info.time}")
            return 0

        if args.command == "manifest":
            require_password(config.password_file)
            restic = restic_from_environment(config)
            sys.stdout.write(dump_manifest(read_manifest(restic, repository, resolve_set(list_sets(restic, repository), args.selector))))
            return 0

        if args.command == "check":
            require_password(config.password_file)
            try:
                subset = BackupConfig(check_subset=args.subset).check_subset if args.subset is not None else config.check_subset
            except ValueError as exc:
                print(f"invalid --subset: {exc}", file=sys.stderr)
                return 2
            restic_from_environment(config).check(repository, read_data_subset=subset or None)
            print(f"repository check passed (data sample: {subset or 'none'})")
            return 0

        if args.command == "config":
            data = decrypt_config(config, restic_from_environment(config), repository, args.selector, args.age_identity)
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
            return 0
    except (BackupError, ResticError, RestoreError) as exc:
        print(f"{args.command} failed: {exc}", file=sys.stderr)
        return 1

    deps = restore_deps_from_environment(config)
    options = RestoreOptions(
        mode=RestoreMode(args.mode),
        selector=args.selector,
        repository=args.repository,
        dry_run=args.dry_run,
        confirmed=args.yes,
        clear_unreadable_secrets=args.clear_unreadable_secrets,
        force_reset=args.force_reset,
        reset_2fa=args.reset_2fa,
        maintenance_db=args.maintenance_db,
        report_path=args.report,
    )
    try:
        report = run_restore(config, deps, options)
    except AlreadyRunning as exc:
        print(str(exc), file=sys.stderr)
        return EX_TEMPFAIL
    for line in report.plan:
        print(line)
    for warning in report.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if report.result == "dry-run":
        print("dry run: this set can be restored into this target; nothing was changed")
        return 0
    if report.result == "ok":
        print(f"restore of {report.set_id} ok: verified against the manifest, {report.objects_restored} objects restored")
        if report.credentials_reset:
            counts = report.credentials_reset
            print(
                f"credentials reset on the restored copy: {counts['marked']} account(s) must choose a new password, "
                f"{counts['tokens_revoked']} access token(s) revoked, {counts['two_factor_cleared']} two-factor enrolment(s) cleared; "
                "issue links with: python -m app.cli.credentials issue-link --server-admins"
            )
        if report.previous_database:
            print(f"the replaced database is kept as '{report.previous_database}'; drop it when you no longer need it")
        return 0
    print(f"restore of {report.set_id or args.selector} FAILED at step '{report.step}': {report.error}", file=sys.stderr)
    for mismatch in report.mismatches[:10]:
        print(f"  MISMATCH {mismatch['path']}: expected {mismatch['expected']!r}, got {mismatch['actual']!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
