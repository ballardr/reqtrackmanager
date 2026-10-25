"""
Module: scripts.dr_verify

Command-line entry point for the post-restore checks (`app.services.dr_verify`). Run inside the restored
stack's backend container, after the application has started on the restored database; the restore-test
(`scripts/restore_test.py`) does this through `docker compose exec`.

Usage (the stack's own `DATABASE_URL`, `STORAGE_*` and `APP_SECRET_ENCRYPTION_KEY` apply):

    python scripts/dr_verify.py < request.json

The request is one JSON document on standard input, so no manifest content or credential is ever on a command
line: `{"manifest": {...}, "login": {"email": "...", "password": "..."}, "credential_reset": true}` (`login` and
`credential_reset` optional; `credential_reset` adds the `credential-recovery` check after a forced reset).

Options: `--api-base URL` (default `http://127.0.0.1:8000`), `--allow-unreadable-secrets`, `--sample N`,
`--extra-rows TABLE=N` (repeatable: rows the restore wrote itself, such as the one audit event of clearing
unreadable secrets; no other difference is tolerated).

Standard output is the JSON report (`result`, one entry per check: counts and ids only); a one-line summary
per check goes to standard error. Exit status: 0 every check passed, 1 a check failed, 2 unusable input.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

import httpx  # noqa: E402

from app.services.dr_manifest import load_manifest  # noqa: E402
from app.services.dr_verify import DEFAULT_SAMPLE_SIZE, LoginCredentials, run_verification  # noqa: E402

_TIMEOUT_SECONDS = 90.0
"""Per-request limit; sign-in verifies a bcrypt hash and is deliberately slow under load."""


def main(argv: list[str] | None = None) -> int:
    """Runs the CLI.

    Args:
        argv: Arguments (default `sys.argv[1:]`).

    Returns:
        The process exit status (see the module docstring).
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="the backend's own address")
    parser.add_argument("--allow-unreadable-secrets", action="store_true", help="the restore was run with --clear-unreadable-secrets")
    parser.add_argument(
        "--extra-rows", action="append", default=[], metavar="TABLE=N", help="rows the restore wrote itself, allowed on top of the manifest"
    )
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE_SIZE, help="stored objects to read back in full")
    args = parser.parse_args(argv)

    try:
        extra_rows = {table: int(count) for table, _, count in (item.partition("=") for item in args.extra_rows)}
        request = json.load(sys.stdin)
        manifest = load_manifest(json.dumps(request["manifest"]))
        login_data = request.get("login")
        login = LoginCredentials(email=login_data["email"], password=login_data["password"]) if login_data else None
        expect_credential_reset = bool(request.get("credential_reset"))
    except (ValueError, KeyError, TypeError) as exc:  # json.JSONDecodeError and a bad TABLE=N are ValueErrors
        print(f"cannot read the request: {type(exc).__name__}", file=sys.stderr)
        return 2

    from sqlalchemy.orm import Session

    from app.database import engine
    from app.services.dr_restore import code_revisions
    from app.services.files import get_storage_backend

    _, heads = code_revisions()
    with Session(engine) as db, httpx.Client(base_url=args.api_base, timeout=_TIMEOUT_SECONDS) as client:
        report = run_verification(
            manifest,
            db,
            get_storage_backend(),
            client,
            head_revisions=heads,
            key_supplied=bool(os.environ.get("APP_SECRET_ENCRYPTION_KEY")),
            allow_unreadable_secrets=args.allow_unreadable_secrets,
            extra_rows=extra_rows,
            login=login,
            expect_credential_reset=expect_credential_reset,
            sample_size=args.sample,
        )
    print(json.dumps(report.to_json_dict(), indent=2))
    for check in report.checks:
        print(f"{'ok  ' if check.ok else 'FAIL'} {check.name}: {check.detail}", file=sys.stderr)
    return 0 if report.result == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
