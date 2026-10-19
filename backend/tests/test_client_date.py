"""Tests for services.client_date: which `X-Client-Date` values are trusted."""

from datetime import UTC, date, datetime, timedelta

from app.services.client_date import effective_today, parse_client_date, reset_client_date, set_client_date

UTC_TODAY = date(2026, 10, 18)


def test_a_plausible_local_day_is_accepted():
    assert parse_client_date("2026-10-19", UTC_TODAY) == date(2026, 10, 19)  # Sydney in the morning
    assert parse_client_date("2026-10-17", UTC_TODAY) == date(2026, 10, 17)  # Honolulu in the evening
    assert parse_client_date(" 2026-10-18 ", UTC_TODAY) == UTC_TODAY


def test_absent_malformed_or_implausible_values_are_ignored():
    assert parse_client_date(None, UTC_TODAY) is None
    assert parse_client_date("", UTC_TODAY) is None
    assert parse_client_date("yesterday", UTC_TODAY) is None
    assert parse_client_date("2026-10-20", UTC_TODAY) is None  # two days ahead: no timezone is that far
    assert parse_client_date("2026-10-16", UTC_TODAY) is None


def test_effective_today_uses_the_clients_day_only_within_a_request():
    utc_today = datetime.now(UTC).date()
    assert effective_today() == utc_today
    token = set_client_date((utc_today + timedelta(days=1)).isoformat())
    try:
        assert effective_today() == utc_today + timedelta(days=1)
    finally:
        reset_client_date(token)
    assert effective_today() == utc_today
