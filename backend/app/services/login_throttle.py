"""
Module: services.login_throttle

Progressive delay on password sign-in (access control Known Gap 1).

Responsibilities: count recent failed attempts per account (since its last success) and per source address from
`login_events`, which every worker and replica shares; past a free allowance, require a wait that doubles with
each failure up to a maximum, and refuse an attempt inside it before the password is checked; serialise
attempts on one account with a transaction-scoped advisory lock, so parallel guesses cannot all pass the check
before the first failure is recorded. A later attempt waits for the lock briefly (`login_lock_wait_seconds`)
instead of being refused, so chance overlaps (a double submit, two devices) both complete; the wait is bounded.

Design decisions:
- A delay, not a lock: it ends by itself and is capped, so a third party who knows an address can slow a
  sign-in by at most the maximum and never keep a person out. Refused attempts are stored but do not count, so
  repeats do not extend the wait.
- The answer is the same whether or not the address belongs to an account (the count is by the address typed).
- All instants are UTC; the wait runs from the last counted failure.

Dependencies: PostgreSQL (`login_events`, `pg_try_advisory_xact_lock`), `app.config`.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.audit import LoginEvent


def normalise_email(email: str) -> str:
    """The form in which an attempted address is stored and counted (trimmed, lower case, at most 255 characters)."""
    return email.strip().lower()[:255]


_LOCK_NOT_AVAILABLE = "55P03"


def _take_account_lock(db: Session, key: str, wait_seconds: int) -> bool:
    """Takes the account's advisory lock for the rest of the transaction, waiting up to `wait_seconds` for it.

    Args:
        db: An active session; the lock is released when its transaction ends.
        key: The normalised address typed.
        wait_seconds: The longest wait; zero tries once and gives up.

    Returns:
        True when the lock is held; False when another attempt kept it for the whole wait (the transaction is rolled
        back, as the failed wait leaves it unusable).

    Raises:
        OperationalError: For a database error other than the lock wait timing out.
    """
    lock_key = {"k": f"login:{key}"}
    if wait_seconds <= 0:
        return bool(db.scalar(text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))"), lock_key))
    db.execute(text("SELECT set_config('lock_timeout', :ms, true)"), {"ms": str(wait_seconds * 1000)})
    try:
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), lock_key)
    except OperationalError as exc:
        if getattr(exc.orig, "pgcode", None) != _LOCK_NOT_AVAILABLE:
            raise
        db.rollback()
        return False
    db.execute(text("SELECT set_config('lock_timeout', '0', true)"))
    return True


def _delay_seconds(failures: int, free: int, base: int, cap: int) -> int:
    """The wait owed after `failures` counted failures: zero within the allowance, then doubling to `cap`."""
    if failures < free:
        return 0
    return min(cap, base * 2 ** min(failures - free, 20))


def _wait(
    db: Session, now: datetime, since: datetime, *, free: int, column, value: str, base: int, cap: int,
    after_success: bool,
) -> int:
    """Seconds still to wait on one key (account or address); zero when none.

    Args:
        since: The start of the counting window.
        column: The `LoginEvent` column the key matches.
        after_success: Only failures after the key's last success count (an account); an address counts the window.
    """
    start = since
    if after_success:
        last_ok = db.scalar(
            select(func.max(LoginEvent.created_at)).where(column == value, LoginEvent.success.is_(True), LoginEvent.created_at > since)
        )
        if last_ok is not None:
            start = last_ok
    count, last = db.execute(
        select(func.count(), func.max(LoginEvent.created_at)).where(
            column == value, LoginEvent.success.is_(False), LoginEvent.kind == "password", LoginEvent.created_at > start
        )
    ).one()
    delay = _delay_seconds(count, free, base, cap)
    if not delay or last is None:
        return 0
    remaining = (last + timedelta(seconds=delay) - now).total_seconds()
    return max(0, math.ceil(remaining))


def seconds_to_wait(db: Session, email: str, ip_address: str, now: datetime | None = None) -> int:
    """How long this attempt must wait before its password is checked.

    Takes the account's advisory lock for the rest of the transaction, waiting up to `login_lock_wait_seconds` for an
    attempt already in progress on the same account. If that attempt outlasts the wait, the answer is one second, so a
    flood of parallel guesses is bounded rather than queued without limit.

    Args:
        db: An active session; the lock is released when its transaction ends.
        email: The address typed (any case).
        ip_address: The client address from `get_client_ip`.
        now: The current instant (UTC); tests pass it.

    Returns:
        Seconds to wait, zero when the attempt may proceed.
    """
    cfg = get_settings()
    now = now or datetime.now(UTC)
    since = now - timedelta(minutes=cfg.login_delay_window_minutes)
    key = normalise_email(email)
    if not _take_account_lock(db, key, cfg.login_lock_wait_seconds):
        return 1
    by_account = _wait(
        db, now, since, free=cfg.login_delay_free_attempts_account, column=LoginEvent.email_attempted, value=key,
        base=cfg.login_delay_base_seconds, cap=cfg.login_delay_max_seconds, after_success=True,
    )
    by_address = _wait(
        db, now, since, free=cfg.login_delay_free_attempts_address, column=LoginEvent.ip_address, value=ip_address,
        base=cfg.login_delay_base_seconds, cap=cfg.login_delay_max_seconds, after_success=False,
    )
    return max(by_account, by_address)
