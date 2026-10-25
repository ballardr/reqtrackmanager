"""
Module: cli.credentials

Command-line credential recovery for a deployment whose administrators cannot sign in (a restore after an
incident, a lost admin password, a locked-out team) and which may have no working email.

Responsibilities:
- `force-reset`: end sessions, revoke personal access tokens and require a new password for a scope of
  accounts (everyone, one organisation, one person, or the server administrators), optionally clearing
  two-factor enrolment and emailing each person a fresh link.
- `issue-link`: print a single-use reset link per account to the operator's terminal, so the first
  administrators can be let back in by hand.

Design decisions:
- Authority comes from shell and database access to the deployment, not from an application sign-in, and
  the application does not need to be running. Only the database (`DATABASE_URL`) is used; the JWT secret
  and the encryption key are not needed.
- Every use writes an audit event with the actor `cli:<os user>`. The event holds counts and the scope,
  never a link or a secret.
- A link is written to standard output only (one `email<TAB>url` line per account); diagnostics and counts
  go to standard error, so `issue-link ... > links.tsv` captures exactly the links. Links are bearer
  secrets: the operator treats the output as confidential and the links expire (60 minutes by default).
- `force-reset` shows what it would do and changes nothing without `--yes`.
- Accounts without a local password (SSO) are listed in the output rather than skipped silently.

Usage (from the backend container or image):

    python -m app.cli.credentials force-reset --all --yes [--reset-2fa] [--send]
    python -m app.cli.credentials force-reset --org ACME --yes
    python -m app.cli.credentials issue-link --server-admins [--ttl-minutes 120]
    python -m app.cli.credentials issue-link --user admin@example.com

Exit status: 0 success, 1 nothing matched or an operation failed, 2 invalid arguments.
"""

from __future__ import annotations

import argparse
import getpass
import sys
import uuid
from collections.abc import Sequence

from sqlalchemy import select

from app.database import SessionLocal
from app.models.organization import Organization
from app.services import credential_reset


def _err(message: str) -> None:
    """Writes a diagnostic line to standard error."""
    print(message, file=sys.stderr)


def _actor() -> str:
    """The audit actor for this run: `cli:<os user>`."""
    try:
        return f"cli:{getpass.getuser()}"
    except Exception:  # noqa: BLE001 - no passwd entry in some containers
        return "cli:unknown"


def _scope_parser(parser: argparse.ArgumentParser) -> None:
    """Adds the mutually exclusive scope options shared by both commands."""
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="every account")
    group.add_argument("--org", metavar="CODE_OR_ID", help="members of one organisation (its code or id)")
    group.add_argument("--user", metavar="EMAIL", help="one account")
    group.add_argument("--server-admins", action="store_true", help="the server administrators")


def build_parser() -> argparse.ArgumentParser:
    """Builds the argument parser.

    Returns:
        The parser with the `force-reset` and `issue-link` sub-commands.
    """
    parser = argparse.ArgumentParser(prog="python -m app.cli.credentials", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    force = sub.add_parser("force-reset", help="end sessions and require a new password")
    _scope_parser(force)
    force.add_argument("--reset-2fa", action="store_true", help="also clear two-factor enrolment")
    force.add_argument("--send", action="store_true", help="email each person a fresh reset link")
    force.add_argument("--yes", action="store_true", help="apply the change (without it, only shows the scope)")
    link = sub.add_parser("issue-link", help="print single-use reset links to this terminal")
    _scope_parser(link)
    link.add_argument("--ttl-minutes", type=int, default=None, help=f"link lifetime, up to {credential_reset.MAX_TTL_MINUTES}")
    return parser


def _resolve_scope(db, args: argparse.Namespace) -> credential_reset.ResetScope:
    """Turns the parsed options into a `ResetScope`.

    Raises:
        LookupError: If `--org` matches no organisation.
    """
    if args.all:
        return credential_reset.ResetScope("all")
    if args.server_admins:
        return credential_reset.ResetScope("server_admins")
    if args.user:
        return credential_reset.ResetScope("user", email=args.user)
    try:
        org_id = uuid.UUID(args.org)
    except ValueError:
        org_id = db.scalar(select(Organization.id).where(Organization.code == args.org.upper()))
    if org_id is None or db.get(Organization, org_id) is None:
        raise LookupError("organisation not found")
    return credential_reset.ResetScope("organization", organization_id=org_id)


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the tool.

    Args:
        argv: Arguments (default `sys.argv[1:]`).

    Returns:
        The process exit status.
    """
    args = build_parser().parse_args(argv)
    if args.command == "issue-link" and args.ttl_minutes is not None and not 1 <= args.ttl_minutes <= credential_reset.MAX_TTL_MINUTES:
        _err(f"--ttl-minutes must be between 1 and {credential_reset.MAX_TTL_MINUTES}")
        return 2
    actor = _actor()
    with SessionLocal() as db:
        try:
            scope = _resolve_scope(db, args)
            users = credential_reset.resolve_scope(db, scope)
        except LookupError as exc:
            _err(str(exc))
            return 1
        if not users:
            _err("no accounts matched")
            return 1

        if args.command == "issue-link":
            links, skipped = credential_reset.issue_links(db, users, actor_label=actor, ttl_minutes=args.ttl_minutes)
            db.commit()
            for email, url in links:
                print(f"{email}\t{url}")
            for email in skipped:
                _err(f"no link (no password here, or deactivated): {email}")
            _err(f"{len(links)} link(s) issued; treat this output as confidential")
            return 0 if links else 1

        summary = credential_reset.ForceResetResult(accounts=len(users))
        if not args.yes:
            local = sum(1 for u in users if credential_reset.has_local_credential(u))
            _err(f"{summary.accounts} account(s) in scope, {local} with a local password. Nothing changed: add --yes to apply.")
            return 0
        result = credential_reset.force_reset(
            db, users, scope=scope, reset_2fa=args.reset_2fa, actor_id=None, actor_label=actor, send_links=args.send
        )
        db.commit()
        _err(
            f"{result.accounts} account(s): sessions ended, {result.marked} must choose a new password, "
            f"{result.tokens_revoked} access token(s) revoked, {result.two_factor_cleared} two-factor enrolment(s) cleared"
        )
        if args.send:
            _err(f"{result.emailed} link(s) emailed, {result.email_failed} not delivered (use issue-link for those people)")
        for email in result.sso_only:
            _err(f"no local password (single sign-on or invited): {email}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
