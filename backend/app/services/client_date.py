"""
Module: client_date

The calendar day the person making a request is in. The browser sends it as `X-Client-Date`
(`YYYY-MM-DD`, its local day); rules of the form "has this date happened yet" use it, because a date a
person types is their local day and the UTC day lags it for part of every day east of Greenwich.

Responsibilities:
- `set_client_date` parses and validates the header once per request (middleware in `app.main`).
- `effective_today` returns the client's day when it is plausible, else the UTC day.

Design: the value is only ever used to decide whether a date is in the past for display and derived
fields; it grants nothing, so it is validated for plausibility (no more than one day from the UTC day,
the widest any timezone can differ) and otherwise ignored. A context variable carries it so the
serialisers that need it need no extra parameter.
"""

from contextvars import ContextVar, Token
from datetime import UTC, date, datetime, timedelta

_client_date: ContextVar[date | None] = ContextVar("client_date", default=None)

# Timezones run from UTC-12 to UTC+14, so a real local day is within one day of the UTC day.
_MAX_SKEW = timedelta(days=1)


def parse_client_date(value: str | None, utc_today: date | None = None) -> date | None:
    """
    Parses an `X-Client-Date` header value.

    Args:
        value: The raw header value, if any.
        utc_today: The reference UTC day (defaults to now); injectable for tests.

    Returns:
        The date, or `None` when the header is absent, malformed or more than a day from the UTC day.
    """
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError:
        return None
    reference = utc_today or datetime.now(UTC).date()
    return parsed if abs(parsed - reference) <= _MAX_SKEW else None


def set_client_date(value: str | None) -> Token:
    """Records this request's client day (call once per request); returns the token to reset it with."""
    return _client_date.set(parse_client_date(value))


def reset_client_date(token: Token) -> None:
    """Clears the client day set by `set_client_date`."""
    _client_date.reset(token)


def effective_today() -> date:
    """The client's calendar day for this request when it sent a plausible one, else the UTC day."""
    return _client_date.get() or datetime.now(UTC).date()
