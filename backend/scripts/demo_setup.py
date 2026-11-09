"""
Module: scripts.demo_setup

Sets a stack up as a demonstration, resets it, and optionally resets it every day.

Responsibilities:
- Seed every demonstration project through the real HTTP API (`seed_demo_data`, which also seeds the repository
  project and the example templates), so validation, versioning and audit apply as for a person.
- Remove the demonstration organisation on `--reset` and `--teardown` through the organisation deletion route.
- Post the server-wide sign-in details message (and a warning for the hour before a scheduled reset) through the
  server administration messages API, replacing its own earlier messages.
- Run the daily reset (`schedule`), applying the same guards on every run.

Design decisions:
- Guards live in `services.demo_setup` and run first on every invocation: `--demo` is required, mail must go to
  a mail catcher, and a database that holds an organisation this command did not create is refused unless the
  database name is confirmed. A reset only ever removes the demonstration organisation.
- The default password is fixed (`DemoDemo123!`); `--rotate-passwords` (or `DEMO_ROTATE_PASSWORDS=1`) gives every
  demonstration account a new random password on each run. The current one is kept in `DEMO_STATE_DIR` (mode
  0600) so the next run can sign in and change it, because accounts outlive the organisation's removal.
- The password appears only in the sign-in details message and the state file: never in a log line, an audit
  event or a notification (the message is never sent as a notification).
- A failed seed removes the partly seeded organisation (accounts and names are unique, so the previous data
  cannot be kept alongside it), says so, writes the failure metric and exits non-zero.
- The reset is not an in-application job: a wipe inside the backend of a deployment that had the flag set by
  mistake is the worst case; the scheduler is a separate opt-in service.

External dependencies: `httpx`, `seed_demo_data`, `services.demo_setup`, `services.dr_schedule`.

Run from `tests/container` (`scripts/demo.sh` wraps this):
    docker compose exec backend python scripts/demo_setup.py --demo
    docker compose exec backend python scripts/demo_setup.py --demo --reset
    docker compose exec backend python scripts/demo_setup.py --demo --teardown
    docker compose run --rm demo-scheduler            # daily reset (profile demo-schedule)
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

import seed_demo_data as base  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services import demo_setup as rules  # noqa: E402
from app.services.dr_schedule import Schedule, ScheduleError  # noqa: E402

PASSWORD_FILE = "password"
STATE_DIR_DEFAULT = "/demo/state"
STATUS_DIR_DEFAULT = "/demo/status"
EXIT_REFUSED = 2
EXIT_BUSY = 75
EXIT_FAILED = 1


def env_flag(name: str) -> bool:
    """True when an environment variable is set to 1, true or yes.

    Args:
        name: Variable name.
    """
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def log(message: str) -> None:
    """Prints one line (counts and times only, never a password)."""
    print(f"demo: {message}", flush=True)


def read_state_password(state_dir: Path) -> str | None:
    """Reads the rotated password the previous run stored, if any.

    Args:
        state_dir: The state directory.
    """
    try:
        return (state_dir / PASSWORD_FILE).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def write_state_password(state_dir: Path, password: str) -> None:
    """Stores the current rotated password with mode 0600.

    Args:
        state_dir: The state directory (created if missing).
        password: The password.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / PASSWORD_FILE
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(password)
    os.chmod(path, 0o600)


def api(method: str, path: str, headers: dict, **kwargs) -> httpx.Response:
    """Sends one API request.

    Args:
        method: HTTP method.
        path: Path below the API base.
        headers: Request headers.
        **kwargs: Passed to `httpx.request`.

    Returns:
        The response (not checked).
    """
    return httpx.request(method, f"{base.BASE}{path}", headers=headers, timeout=60, **kwargs)


def demo_organisation_ids(admin: dict) -> dict[str, str]:
    """Returns the demonstration organisations the server holds.

    Args:
        admin: Server administrator headers.

    Returns:
        Name to id for each organisation in `DEMO_ORGANISATIONS`.
    """
    found = api("GET", "/orgs", admin)
    found.raise_for_status()
    return {o["name"]: o["id"] for o in found.json() if o["name"] in rules.DEMO_ORGANISATIONS}


def remove_demo_organisations(admin: dict) -> int:
    """Deletes every demonstration organisation (never any other).

    Args:
        admin: Server administrator headers.

    Returns:
        The number removed.
    """
    removed = 0
    for name, org_id in demo_organisation_ids(admin).items():
        api("DELETE", f"/orgs/{org_id}", admin, json={"confirm_name": name}).raise_for_status()
        removed += 1
    return removed


def remove_own_messages(admin: dict) -> int:
    """Deletes the server messages this command owns (found by their reserved titles).

    Args:
        admin: Server administrator headers.

    Returns:
        The number removed.
    """
    listed = api("GET", "/system/announcements", admin)
    listed.raise_for_status()
    removed = 0
    for item in listed.json()["items"]:
        if item["title"] in (rules.LOGIN_MESSAGE_TITLE, rules.RESET_WARNING_TITLE):
            api("DELETE", f"/system/announcements/{item['id']}", admin).raise_for_status()
            removed += 1
    return removed


def rotate_accounts(admin: dict, state_dir: Path) -> str:
    """Chooses a new random password and changes it on every demonstration account that already exists.

    Args:
        admin: Server administrator headers.
        state_dir: Where the previous password is kept and the new one is stored.

    Returns:
        The new password.

    Raises:
        rules.DemoGuardError: An account exists and neither the stored nor the default password signs it in.
    """
    new_password = rules.generate_password()
    known = [p for p in (read_state_password(state_dir), rules.DEFAULT_PASSWORD) if p]
    for account in rules.DEMO_ACCOUNTS:
        found = api("GET", "/system/users", admin, params={"search": account.email})
        found.raise_for_status()
        if not any(u["email"].lower() == account.email for u in found.json()):
            continue
        for current in known:
            tried = httpx.post(f"{base.BASE}/auth/login", json={"email": account.email, "password": current}, timeout=60)
            if tried.status_code == httpx.codes.OK:
                headers = base.h(tried.json()["access_token"])
                api("POST", "/auth/change-password", headers, json={"current_password": current, "new_password": new_password}).raise_for_status()
                break
        else:
            raise rules.DemoGuardError(
                f"Cannot sign in as {account.email} to change its password: the stored password is missing or out of date."
                f" Remove the account's data some other way or restore {state_dir / PASSWORD_FILE}."
            )
    write_state_password(state_dir, new_password)
    return new_password


def verify_demo_accounts_only(password: str) -> None:
    """Confirms every listed account holds demonstration data only.

    Args:
        password: The password every account currently has.

    Raises:
        rules.DemoGuardError: An account is a server administrator or belongs to a non-demonstration organisation.
    """
    for account in rules.DEMO_ACCOUNTS:
        token = base.login(account.email, password)
        headers = base.h(token)
        me = api("GET", "/auth/me", headers)
        me.raise_for_status()
        mine = api("GET", "/orgs", headers, params={"mine": "true"})
        mine.raise_for_status()
        outside = [o["name"] for o in mine.json() if o["name"] not in rules.DEMO_ORGANISATIONS]
        if me.json()["is_server_admin"] or outside:
            raise rules.DemoGuardError(
                f"Refusing to publish the sign-in details: {account.email} is a server administrator or belongs to an"
                " organisation that is not a demonstration."
            )


def post_messages(admin: dict, password: str, schedule: Schedule | None, now: datetime) -> None:
    """Replaces the sign-in details message and, with a schedule, the reset warning.

    Args:
        admin: Server administrator headers.
        password: The password every demonstration account has.
        schedule: The reset schedule, if one is configured.
        now: The current instant.

    Raises:
        rules.MessageTooLongError: The sign-in details do not fit in a message.
        httpx.HTTPStatusError: A messages request failed.
    """
    reset_at = rules.next_reset_at(schedule, now) if schedule is not None else None
    body = rules.login_message_body(rules.DEMO_ACCOUNTS, password, reset_at, schedule)
    remove_own_messages(admin)
    created = api("POST", "/system/announcements", admin, json={
        "title": rules.LOGIN_MESSAGE_TITLE, "body": body, "severity": "information", "show_on_login": True, "dismissible": False,
    })
    created.raise_for_status()
    if schedule is not None and reset_at is not None:
        warning = api("POST", "/system/announcements", admin, json={
            "title": rules.RESET_WARNING_TITLE, "body": rules.reset_warning_body(reset_at, schedule), "severity": "warning",
            "show_on_login": True, "dismissible": False,
            "starts_at": (reset_at - timedelta(hours=1)).isoformat(), "ends_at": reset_at.isoformat(),
        })
        warning.raise_for_status()
    log("sign-in details message posted (it publishes the demonstration credentials to anyone who can reach the login page)")


def run_once(args: argparse.Namespace, schedule: Schedule | None) -> int:
    """Performs one setup, reset or teardown under the lock, with every guard.

    Args:
        args: Parsed command line.
        schedule: The reset schedule, if one is configured.

    Returns:
        The process exit status.
    """
    state_dir, status_dir = Path(args.state_dir), Path(args.status_dir)
    try:
        with rules.reset_lock(state_dir):
            return _locked_run(args, schedule, state_dir, status_dir)
    except rules.ResetInProgressError as exc:
        log(str(exc))
        return EXIT_BUSY


def _locked_run(args: argparse.Namespace, schedule: Schedule | None, state_dir: Path, status_dir: Path) -> int:
    """The body of `run_once`, with the lock held."""
    now = datetime.now(UTC)
    next_reset = rules.next_reset_at(schedule, now) if schedule is not None else None
    try:
        base.BASE = args.api_base
        admin = base.h(base.login(base.ADMIN_EMAIL, base.ADMIN_PASSWORD))
        orgs = api("GET", "/orgs", admin)
        orgs.raise_for_status()
        rules.check_guards(
            demo_flag=args.demo, existing_organisations=[o["name"] for o in orgs.json()],
            database_name=rules.database_name_of(get_settings().database_url), confirm_database=args.confirm_database,
            smtp_host=get_settings().smtp_host,
        )
    except rules.DemoGuardError as exc:
        print(f"demo: {exc}", file=sys.stderr, flush=True)
        return EXIT_REFUSED
    except httpx.HTTPError as exc:
        print(f"demo: cannot reach the API ({type(exc).__name__})", file=sys.stderr, flush=True)
        rules.write_reset_metrics(status_dir, succeeded=False, finished=now, next_reset=next_reset)
        return EXIT_FAILED

    seeding = False
    try:
        if args.reset or args.teardown:
            log(f"removed {remove_demo_organisations(admin)} demonstration organisation(s) and {remove_own_messages(admin)} message(s)")
            if args.teardown:
                rules.write_reset_metrics(status_dir, succeeded=True, finished=datetime.now(UTC), next_reset=None)
                return 0
        password = rotate_accounts(admin, state_dir) if args.rotate_passwords else rules.DEFAULT_PASSWORD
        base.PASSWORD = password
        if demo_organisation_ids(admin):
            log("the demonstration data is already present; use --reset to start again")
        else:
            seeding = True
            base.main()
            seeding = False
        if not args.no_login_message:
            verify_demo_accounts_only(password)
            post_messages(admin, password, schedule, datetime.now(UTC))
        rules.write_reset_metrics(status_dir, succeeded=True, finished=datetime.now(UTC), next_reset=next_reset)
        return 0
    except rules.DemoGuardError as exc:
        print(f"demo: {exc}", file=sys.stderr, flush=True)
        _fail(admin, status_dir, next_reset, remove_partial=seeding)
        return EXIT_REFUSED
    except (httpx.HTTPError, rules.MessageTooLongError, OSError, StopIteration) as exc:
        reason = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else exc
        print(f"demo: failed ({type(exc).__name__}): {reason}", file=sys.stderr, flush=True)
        _fail(admin, status_dir, next_reset, remove_partial=seeding)
        return EXIT_FAILED


def _fail(admin: dict, status_dir: Path, next_reset: datetime | None, *, remove_partial: bool) -> None:
    """Records the failure and, when the seed had started, removes the partly seeded demonstration.

    Accounts and names are unique, so the previous data cannot be kept beside a second copy; the log says so.

    Args:
        admin: Server administrator headers.
        status_dir: Where the metrics file is written.
        next_reset: The next scheduled reset, if any.
        remove_partial: True when the seed had started, so a half-seeded organisation exists to remove; a failure
            before it (a password change, the guards) leaves existing data untouched.
    """
    if remove_partial:
        try:
            removed = remove_demo_organisations(admin)
            remove_own_messages(admin)
            log(
                "the previous demonstration data could not be kept (names and accounts are unique); "
                f"removed {removed} partly seeded organisation(s)"
            )
        except (httpx.HTTPError, OSError) as exc:
            log(f"clean-up after the failure also failed ({type(exc).__name__})")
    rules.write_reset_metrics(status_dir, succeeded=False, finished=datetime.now(UTC), next_reset=next_reset)


def serve_schedule(args: argparse.Namespace, schedule: Schedule) -> int:
    """Resets the demonstration at each slot until SIGTERM or SIGINT.

    Args:
        args: Parsed command line (a scheduled run always resets).
        schedule: The reset schedule.

    Returns:
        0 on a clean stop.
    """
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    args.reset = True
    log(f"scheduled reset at {args.reset_at} ({args.reset_tz})")
    while not stop.is_set():
        due = rules.next_reset_at(schedule, datetime.now(UTC))
        log(f"next reset at {due.isoformat()}")
        while not stop.is_set() and (due - datetime.now(UTC)).total_seconds() > 0:
            stop.wait(min(60.0, max(1.0, (due - datetime.now(UTC)).total_seconds())))
        if stop.is_set():
            break
        status = run_once(args, schedule)
        log(f"reset {'succeeded' if status == 0 else f'FAILED (exit {status})'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Builds the command line parser (options default from the matching environment variables)."""
    parser = argparse.ArgumentParser(description="Set up, reset or schedule the reset of a demonstration.")
    parser.add_argument("command", nargs="?", choices=["setup", "schedule"], default="setup")
    parser.add_argument("--demo", action="store_true", default=env_flag("DEMO_MODE"), help="confirm this is a demonstration (DEMO_MODE=1)")
    parser.add_argument("--reset", action="store_true", help="remove the demonstration organisation and seed again")
    parser.add_argument("--teardown", action="store_true", help="remove the demonstration organisation and the messages, seed nothing")
    parser.add_argument(
        "--rotate-passwords", action="store_true", default=env_flag("DEMO_ROTATE_PASSWORDS"),
        help="a new random password on every run (DEMO_ROTATE_PASSWORDS=1)",
    )
    parser.add_argument(
        "--no-login-message", action="store_true", default=env_flag("DEMO_NO_LOGIN_MESSAGE"),
        help="do not publish the sign-in details (DEMO_NO_LOGIN_MESSAGE=1)",
    )
    parser.add_argument(
        "--confirm-database", default=os.environ.get("DEMO_CONFIRM_DATABASE") or None,
        help="the database name, to run beside organisations this command did not create (DEMO_CONFIRM_DATABASE)",
    )
    parser.add_argument("--api-base", default=base.BASE, help="API base URL (DEMO_API_BASE)")
    parser.add_argument("--state-dir", default=os.environ.get("DEMO_STATE_DIR", STATE_DIR_DEFAULT))
    parser.add_argument("--status-dir", default=os.environ.get("DEMO_STATUS_DIR", STATUS_DIR_DEFAULT))
    parser.add_argument("--reset-at", default=os.environ.get("DEMO_RESET_AT", ""), help="daily reset time HH:MM (DEMO_RESET_AT)")
    parser.add_argument("--reset-tz", default=os.environ.get("DEMO_RESET_TZ", "UTC"), help="IANA zone of the reset time (DEMO_RESET_TZ)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Arguments (default `sys.argv[1:]`).

    Returns:
        The process exit status: 0 done, 1 failed, 2 refused or invalid, 75 another run holds the lock.
    """
    args = build_parser().parse_args(argv)
    schedule: Schedule | None = None
    if args.command == "schedule" and not args.reset_at:
        print("demo: schedule needs DEMO_RESET_AT (HH:MM)", file=sys.stderr)
        return EXIT_REFUSED
    if args.reset_at:
        try:
            schedule = rules.demo_schedule(args.reset_at, args.reset_tz)
        except ScheduleError as exc:
            print(f"demo: invalid reset time: {exc}", file=sys.stderr)
            return EXIT_REFUSED
    if args.command == "schedule":
        return serve_schedule(args, schedule) if schedule is not None else EXIT_REFUSED
    return run_once(args, schedule)


if __name__ == "__main__":
    sys.exit(main())
