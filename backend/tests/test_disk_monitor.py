"""Tests for the local storage disk-usage monitor (I-M-11): the actual
threshold-check/email-dedup logic in `check_disk_usage_once`, isolated
from the real 15-minute timer loop and from `shutil.disk_usage` by using a
fake storage backend."""

from unittest.mock import AsyncMock, patch

import pytest

from app.database import SessionLocal
from app.services import disk_monitor


class _FakeBackend:
    def __init__(self, percent: float) -> None:
        self._percent = percent

    def disk_usage_percent(self) -> float:
        return self._percent


@pytest.mark.asyncio
async def test_sends_warning_email_once_when_threshold_crossed():
    disk_monitor.settings.disk_usage_warning_threshold_percent = 90
    disk_monitor.settings.deployment_notification_email = "ops@example.com"
    backend = _FakeBackend(95.0)
    db = SessionLocal()

    with patch.object(disk_monitor, "send_email_async", new=AsyncMock()) as mock_send:
        already_warned = await disk_monitor.check_disk_usage_once(backend, already_warned=False, db=db)
        assert already_warned is True
        assert mock_send.await_count == 1

        # Usage still above threshold on the next check: no repeat email.
        already_warned = await disk_monitor.check_disk_usage_once(backend, already_warned=already_warned, db=db)
        assert already_warned is True
        assert mock_send.await_count == 1
    db.close()


@pytest.mark.asyncio
async def test_no_email_below_threshold_and_rewarns_after_recovery():
    disk_monitor.settings.disk_usage_warning_threshold_percent = 90
    disk_monitor.settings.deployment_notification_email = "ops@example.com"
    db = SessionLocal()

    with patch.object(disk_monitor, "send_email_async", new=AsyncMock()) as mock_send:
        already_warned = await disk_monitor.check_disk_usage_once(_FakeBackend(50.0), already_warned=False, db=db)
        assert already_warned is False
        assert mock_send.await_count == 0

        # Crosses the threshold, recovers, then crosses again -> warns twice.
        already_warned = await disk_monitor.check_disk_usage_once(_FakeBackend(95.0), already_warned=already_warned, db=db)
        assert mock_send.await_count == 1
        already_warned = await disk_monitor.check_disk_usage_once(_FakeBackend(50.0), already_warned=already_warned, db=db)
        assert already_warned is False
        already_warned = await disk_monitor.check_disk_usage_once(_FakeBackend(95.0), already_warned=already_warned, db=db)
        assert mock_send.await_count == 2
    db.close()
