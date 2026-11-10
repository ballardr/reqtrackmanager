"""
Module: services.demo_setup

The rules behind the demonstration setup command (`scripts/demo_setup.py`): when it may run, what the sign-in
details message says, when the next daily reset is, and how overlapping resets and failures are recorded.

Responsibilities:
- Refuse to run against a deployment that holds anything other than the demonstration organisation, unless the
  operator confirms the database name (`check_guards`), and refuse a mail relay that is not a mail catcher.
- Build the server-wide sign-in details message and the reset warning (plain text, within the message limits).
- Work out the next reset time from a daily wall-clock time and an IANA zone (`next_reset_at`).
- Hold a lock so a manual and a scheduled reset cannot overlap (`reset_lock`).
- Write the Prometheus textfile the existing monitoring can alert on (`write_reset_metrics`).
- Append each run's start and finish to a history file (`append_reset_event`), so a usage-metrics bundle can mark where
  each cycle begins and explain a counter that falls to zero.

Design decisions:
- Every guard is a pure function of values the caller reads, so each refusal is tested without a database or a
  network, and a scheduled run applies exactly the guards a manual one does.
- The reset time is a future, scheduled wall-clock time: kept as local time plus an IANA zone and resolved to a
  UTC instant only when the next wait is computed (`services.dr_schedule.Schedule`), so a zone other than UTC
  keeps its local time across a daylight-saving change.
- The default demonstration password is fixed and published in the sign-in details message; that is only
  acceptable because the guards keep the command away from any deployment holding real data. A rotating random
  password is opt-in (`generate_password`).
- The message body carries the password, so nothing here logs it, and `login_message_body` fails rather than
  truncating when the accounts do not fit.

Dependencies: `services.dr_schedule` (daily schedule), `services.announcements` (message limits), the standard
library.
"""

from __future__ import annotations

import fcntl
import ipaddress
import json
import re
import secrets
import string
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from app.services.announcements import MAX_BODY_LENGTH
from app.services.dr_backup import write_atomic
from app.services.dr_schedule import Schedule, parse_schedule

DEMO_ORGANISATIONS = ("Solstice Robotics",)
"""Organisations the demonstration seed creates; a reset removes only these."""

DEFAULT_PASSWORD = "DemoDemo123!"
"""The fixed demonstration password (a documented exception to the access control policy)."""

LOGIN_MESSAGE_TITLE = "Demonstration sign-in details"
RESET_WARNING_TITLE = "Demonstration reset"
"""Reserved titles: the command finds, replaces and removes its own messages by these."""

CATCHER_HOSTS = frozenset({"mailhog", "mailpit", "localhost", "127.0.0.1", "::1"})
"""Mail relays that are mail catchers; any other relay could deliver demonstration mail to real people."""

METRICS_FILENAME = "reqtrack-demo-reset.prom"
HISTORY_FILENAME = "reqtrack-demo-resets.jsonl"
HISTORY_LIMIT = 500
"""Lines kept in the reset history; one cycle writes two, so this is about eight months of daily resets."""
LOCK_FILENAME = ".demo-reset.lock"


@dataclass(frozen=True)
class DemoAccount:
    """A demonstration sign-in.

    Attributes:
        email: Sign-in name.
        display_name: Shown name.
        role: Organisation role (`org_admin` or `member`).
    """

    email: str
    display_name: str
    role: str


DEMO_ACCOUNTS = (
    DemoAccount("demo.admin@example.com", "Jordan Alvarez", "org_admin"),
    DemoAccount("demo.engineer@example.com", "Priya Natarajan", "member"),
    DemoAccount("demo.stakeholder@example.com", "Sam Whitfield", "member"),
)
"""The accounts `seed_demo_data` creates, in the order it creates them."""

ROLE_TEXT = {"org_admin": "organisation administrator", "member": "member"}


class DemoGuardError(RuntimeError):
    """The command was refused because it could affect a deployment that is not a demonstration."""


class MessageTooLongError(ValueError):
    """The sign-in details do not fit in one message."""


def database_name_of(database_url: str) -> str:
    """Returns the database name in a connection URL.

    Args:
        database_url: A SQLAlchemy URL such as `postgresql://user:pass@db:5432/reqtrack_test`.

    Returns:
        The database name (the last path segment), empty when the URL has none.
    """
    return urlparse(database_url).path.lstrip("/")


def smtp_host_is_catcher(host: str) -> bool:
    """True for a mail catcher: a known catcher name or any loopback address.

    Args:
        host: The configured SMTP host.
    """
    name = host.strip().lower()
    if name in CATCHER_HOSTS:
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def check_guards(
    *,
    demo_flag: bool,
    existing_organisations: list[str],
    database_name: str,
    confirm_database: str | None,
    smtp_host: str,
) -> list[str]:
    """Decides whether the command may run.

    Args:
        demo_flag: True when `--demo` or `DEMO_MODE=1` was given.
        existing_organisations: Names of every organisation the server holds.
        database_name: The database the application is connected to.
        confirm_database: The database name the operator typed, if any.
        smtp_host: The configured SMTP host.

    Returns:
        The names of organisations the command did not create and that the operator confirmed it may run
        beside (empty on a clean or demonstration-only database). A reset never removes them.

    Raises:
        DemoGuardError: The flag is missing, the mail relay is not a mail catcher, or the database holds an
            organisation the command did not create and the database name was not confirmed.
    """
    if not demo_flag:
        raise DemoGuardError("Refusing to run: pass --demo (or set DEMO_MODE=1) to confirm this is a demonstration.")
    if not smtp_host_is_catcher(smtp_host):
        raise DemoGuardError(
            f"Refusing to run: SMTP_HOST is {smtp_host!r}, which is not a mail catcher. Demonstration accounts"
            " could send mail to real addresses; point SMTP_HOST at the bundled mail catcher."
        )
    others = sorted(name for name in existing_organisations if name not in DEMO_ORGANISATIONS)
    if others and confirm_database != database_name:
        raise DemoGuardError(
            f"Refusing to run: database {database_name!r} holds {len(others)} organisation(s) this command did not"
            " create. If this database really is a demonstration, repeat the command with"
            f" --confirm-database {database_name}."
        )
    return others


def generate_password(length: int = 20) -> str:
    """Generates a random password with lower case, upper case, digit and symbol characters.

    Args:
        length: Number of characters (at least 12).

    Returns:
        The password.

    Raises:
        ValueError: If `length` is below 12.
    """
    if length < 12:
        raise ValueError("A generated password needs at least 12 characters.")
    classes = (string.ascii_lowercase, string.ascii_uppercase, string.digits, "!#%*+-=?")
    chars = [secrets.choice(group) for group in classes]
    pool = "".join(classes)
    chars += [secrets.choice(pool) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def format_reset_time(instant: datetime, schedule: Schedule) -> str:
    """Formats a reset instant as local wall-clock time with its zone name.

    Args:
        instant: The reset instant.
        schedule: The schedule that supplies the zone.
    """
    return instant.astimezone(schedule.zone).strftime("%H:%M %Z (%Y-%m-%d)")


def login_message_body(
    accounts: tuple[DemoAccount, ...], password: str, reset_at: datetime | None, schedule: Schedule | None,
) -> str:
    """Builds the sign-in details message.

    Args:
        accounts: The demonstration accounts to list.
        password: The password every listed account currently has.
        reset_at: The next scheduled reset, or `None` when there is no schedule.
        schedule: The schedule, for the zone of the displayed time.

    Returns:
        Plain text, one line per account.

    Raises:
        MessageTooLongError: If the text exceeds the message body limit (it is never truncated).
    """
    lines = ["Sign in with one of these demonstration accounts. All hold sample data only."]
    lines += [f"{a.email} ({ROLE_TEXT.get(a.role, a.role)})" for a in accounts]
    lines.append(f"Password for every account: {password}")
    if reset_at is not None and schedule is not None:
        lines.append(f"The demonstration data resets daily; the next reset is at {format_reset_time(reset_at, schedule)}.")
    else:
        lines.append("The demonstration data can be reset at any time; work entered here is not kept.")
    body = "\n".join(lines)
    if len(body) > MAX_BODY_LENGTH:
        raise MessageTooLongError(
            f"The sign-in details need {len(body)} characters; a message holds {MAX_BODY_LENGTH}. List fewer accounts."
        )
    return body


def reset_warning_body(reset_at: datetime, schedule: Schedule) -> str:
    """Builds the warning shown for the hour before a reset.

    Args:
        reset_at: The reset instant.
        schedule: The schedule, for the zone of the displayed time.
    """
    return (
        f"The demonstration data resets at {format_reset_time(reset_at, schedule)}. "
        "Anything entered is removed and signed-in sessions end."
    )


def demo_schedule(spec: str, timezone: str = "UTC") -> Schedule:
    """Parses `DEMO_RESET_AT` and `DEMO_RESET_TZ`.

    Args:
        spec: `HH:MM` (daily) or `every Nh`.
        timezone: IANA zone name for a daily time.

    Returns:
        The schedule.

    Raises:
        services.dr_schedule.ScheduleError: If the text or the zone is not recognised.
    """
    return parse_schedule(spec, timezone)


def next_reset_at(schedule: Schedule, now: datetime) -> datetime:
    """The next reset strictly after `now`, as a UTC instant.

    Args:
        schedule: The reset schedule.
        now: The current instant (timezone-aware).
    """
    return schedule.next_slot(now)


class ResetInProgressError(RuntimeError):
    """Another reset holds the lock."""


@contextmanager
def reset_lock(directory: Path) -> Iterator[None]:
    """Holds an exclusive lock for the duration of a setup or reset.

    Args:
        directory: A directory shared by every process that may reset (created if missing).

    Raises:
        ResetInProgressError: Another process holds the lock.
    """
    directory.mkdir(parents=True, exist_ok=True)
    handle = open(directory / LOCK_FILENAME, "w")  # noqa: SIM115  (held for the context's lifetime)
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ResetInProgressError("Another demonstration reset is already running.") from exc
        yield
    finally:
        handle.close()


IMAGE_UPDATE_OUTCOMES = ("updated", "unchanged", "failed")
"""What `scripts/demo.sh --pull` reports: new images in use, nothing newer published, or the pull failed (the run
carried on with the images already present)."""

_IMAGE_ID = re.compile(r"^(?:sha256:[0-9a-f]{12,64}|none)$")
_SERVICE_NAME = re.compile(r"^[a-z][a-z0-9-]{0,40}$")


@dataclass(frozen=True)
class ImageUpdate:
    """The container image refresh that preceded a run (`demo.sh --pull`).

    Attributes:
        outcome: One of `IMAGE_UPDATE_OUTCOMES`.
        images: Per service: `{"image_id": "sha256:...", "changed": bool}`. Identifiers only, never a registry
            credential or a path.
    """

    outcome: str
    images: dict[str, dict[str, object]]

    @property
    def succeeded(self) -> bool:
        """True unless the pull failed: an unchanged set of images is a healthy outcome."""
        return self.outcome != "failed"


def parse_image_update(outcome: str | None, report: str | None) -> ImageUpdate | None:
    """Validates the image refresh reported by `demo.sh --pull`.

    Args:
        outcome: `updated`, `unchanged` or `failed`; None or empty when the run did not refresh images.
        report: JSON object `{service: {"image_id": ..., "changed": bool}}`; may be empty.

    Returns:
        The refresh, or None when the run did not refresh images.

    Raises:
        ValueError: The outcome is unknown or the report is not the documented shape.
    """
    if not outcome:
        return None
    if outcome not in IMAGE_UPDATE_OUTCOMES:
        raise ValueError(f"image update outcome must be one of {', '.join(IMAGE_UPDATE_OUTCOMES)}")
    try:
        loaded = json.loads(report) if report else {}
    except json.JSONDecodeError as exc:
        raise ValueError("image report is not valid JSON") from exc
    if not isinstance(loaded, dict):
        raise ValueError("image report must be an object")
    images: dict[str, dict[str, object]] = {}
    for name, entry in loaded.items():
        if not (isinstance(name, str) and _SERVICE_NAME.match(name) and isinstance(entry, dict)):
            raise ValueError("image report holds an invalid service entry")
        image_id, changed = entry.get("image_id"), entry.get("changed")
        if not (isinstance(image_id, str) and _IMAGE_ID.match(image_id) and isinstance(changed, bool)):
            raise ValueError(f"image report entry for {name} is invalid")
        images[name] = {"image_id": image_id, "changed": changed}
    return ImageUpdate(outcome=outcome, images=images)


def reset_metrics_text(
    *, succeeded: bool, finished: datetime, next_reset: datetime | None, image_update: ImageUpdate | None = None,
) -> str:
    """The Prometheus textfile for a finished run (counts and times only).

    Args:
        succeeded: Whether the run completed.
        finished: When it finished (UTC).
        next_reset: The next scheduled reset, if any.
        image_update: The image refresh that preceded the run, if there was one.
    """
    lines = [
        "# HELP reqtrack_demo_reset_last_success 1 when the last demonstration setup or reset succeeded, else 0.",
        "# TYPE reqtrack_demo_reset_last_success gauge",
        f"reqtrack_demo_reset_last_success {1 if succeeded else 0}",
        "# HELP reqtrack_demo_reset_last_run_timestamp_seconds When the last run finished.",
        "# TYPE reqtrack_demo_reset_last_run_timestamp_seconds gauge",
        f"reqtrack_demo_reset_last_run_timestamp_seconds {finished.astimezone(UTC).timestamp():.0f}",
    ]
    if next_reset is not None:
        lines += [
            "# HELP reqtrack_demo_reset_next_timestamp_seconds When the next scheduled reset is due.",
            "# TYPE reqtrack_demo_reset_next_timestamp_seconds gauge",
            f"reqtrack_demo_reset_next_timestamp_seconds {next_reset.astimezone(UTC).timestamp():.0f}",
        ]
    if image_update is not None:
        lines += [
            "# HELP reqtrack_demo_image_update_last_success 1 when the last image refresh pulled or confirmed the latest images, else 0.",
            "# TYPE reqtrack_demo_image_update_last_success gauge",
            f"reqtrack_demo_image_update_last_success {1 if image_update.succeeded else 0}",
        ]
    return "\n".join(lines) + "\n"


def write_reset_metrics(
    directory: Path, *, succeeded: bool, finished: datetime, next_reset: datetime | None, image_update: ImageUpdate | None = None,
) -> None:
    """Writes `reqtrack-demo-reset.prom` atomically.

    Args:
        directory: The status directory Alloy reads.
        succeeded: Whether the run completed.
        finished: When it finished (UTC).
        next_reset: The next scheduled reset, if any.
        image_update: The image refresh that preceded the run, if there was one.
    """
    write_atomic(
        directory / METRICS_FILENAME,
        reset_metrics_text(succeeded=succeeded, finished=finished, next_reset=next_reset, image_update=image_update),
    )
    append_reset_event(directory, "reset_finished", at=finished, succeeded=succeeded)


def append_reset_event(
    directory: Path, event: str, *, at: datetime, succeeded: bool | None = None, image_update: ImageUpdate | None = None,
) -> None:
    """Appends one line to `reqtrack-demo-resets.jsonl` (the last `HISTORY_LIMIT` lines are kept).

    The history holds times and outcomes only. A failure to write it never fails the run (the history is a
    reviewer's aid, not part of the reset).

    Args:
        directory: The status directory.
        event: `reset_started` or `reset_finished`.
        at: When it happened (UTC instant).
        succeeded: For `reset_finished`, whether the run completed.
        image_update: For `reset_started`, the image refresh that preceded the run (outcome and image identifiers),
            so a metrics bundle shows which build served each period.
    """
    entry: dict[str, object] = {"event": event, "at": at.astimezone(UTC).isoformat().replace("+00:00", "Z")}
    if succeeded is not None:
        entry["succeeded"] = succeeded
    if image_update is not None:
        entry["image_update"] = image_update.outcome
        entry["images"] = image_update.images
    path = directory / HISTORY_FILENAME
    try:
        lines = path.read_text().splitlines() if path.exists() else []
        lines.append(json.dumps(entry, separators=(",", ":")))
        write_atomic(path, "\n".join(lines[-HISTORY_LIMIT:]) + "\n")
    except OSError:
        return
