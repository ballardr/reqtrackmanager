"""Tests for the file-storage health monitor (`services.storage_health`) and
its server-admin endpoint.

Covers: the probe (healthy, write failure, read-back mismatch), the alert rules
(server admins notified once when an outage is confirmed and once on recovery, a dropped probe ignored, the open outage surviving a restart,
ERROR logged on every failing check, the Prometheus gauge), the local disk
monitor also notifying admins, and `GET /api/v1/system/storage-health`.

`test_real_configured_storage_accepts_writes` is also the canary for the test
environment itself: if the storage this suite runs against is full or
unreachable it fails here, naming the cause, instead of as an unexplained 500
in some upload test later.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.metrics import storage_write_healthy
from app.models.notification import Notification
from app.models.user import User
from app.services import disk_monitor, storage_health
from app.services.storage_health import StorageHealthState
from tests.conftest import auth_headers, create_org_user


class _MemoryBackend:
    """In-memory backend whose writes can be made to fail."""

    name = "memory"

    def __init__(self, *, fail_with: Exception | None = None, corrupt: bool = False) -> None:
        self.fail_with = fail_with
        self.corrupt = corrupt
        self.objects: dict[str, bytes] = {}

    def save(self, key: str, data: bytes) -> None:
        if self.fail_with:
            raise self.fail_with
        self.objects[key] = data

    def read(self, key: str) -> bytes:
        return b"other" if self.corrupt else self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def _alerts(db) -> list[Notification]:
    return list(db.scalars(select(Notification).where(Notification.type == "system_storage_alert")).all())


def test_probe_reports_healthy_and_leaves_nothing_behind():
    backend = _MemoryBackend()
    result = storage_health.probe_storage(backend)
    assert result.healthy and result.error is None and result.backend == "memory"
    assert backend.objects == {}


def test_probe_reports_a_write_failure_and_a_read_back_mismatch():
    failing = storage_health.probe_storage(_MemoryBackend(fail_with=OSError("No space left on device")))
    assert not failing.healthy and "No space left on device" in failing.error
    corrupt = storage_health.probe_storage(_MemoryBackend(corrupt=True))
    assert not corrupt.healthy and "different bytes" in corrupt.error


async def _check(backend, state, db, *, threshold: int = 1):
    """One monitor check with the alert threshold and the email channel pinned."""
    with patch.object(storage_health, "send_email_async", new=AsyncMock()), patch.object(
        storage_health.settings, "storage_health_failures_before_alert", threshold
    ), patch.object(storage_health.settings, "deployment_notification_email", None):
        return await storage_health.check_storage_health_once(backend, state, db)


@pytest.mark.asyncio
async def test_admins_are_notified_once_per_outage_and_once_on_recovery(client, admin_token, caplog):
    org = client.get("/api/v1/orgs", headers=auth_headers(admin_token)).json()[0]
    create_org_user(client, admin_token, org["id"], "plain-member@example.com")
    backend = _MemoryBackend(fail_with=OSError("No space left on device"))
    db = SessionLocal()
    try:
        with caplog.at_level(logging.ERROR):
            state = await _check(backend, StorageHealthState(), db)
        assert state.outage_alerted is True
        assert storage_write_healthy._value.get() == 0
        first = _alerts(db)
        assert len(first) == 1, "only the server admin is told, once"
        assert first[0].title == "File storage is not accepting writes"
        assert "No space left on device" in first[0].body and "docker builder prune" in first[0].body
        admin = db.scalar(select(User).where(User.email == "admin@example.com"))
        assert first[0].user_id == admin.id

        caplog.clear()
        with caplog.at_level(logging.ERROR):
            state = await _check(backend, state, db)
        assert state.outage_alerted is True and len(_alerts(db)) == 1, "no repeat alert while still failing"
        assert any("not accepting writes" in r.message for r in caplog.records), "still logged at ERROR"

        backend.fail_with = None
        state = await _check(backend, state, db)
        assert state.outage_alerted is False and storage_write_healthy._value.get() == 1
        assert [a.title for a in _alerts(db)].count("File storage recovered") == 1

        await _check(backend, state, db)
        assert len(_alerts(db)) == 2, "a healthy check after recovery stays quiet"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_a_dropped_probe_between_healthy_checks_does_not_alert(client, admin_token):
    backend = _MemoryBackend(fail_with=OSError("timed out"))
    db = SessionLocal()
    try:
        state = await _check(backend, StorageHealthState(outage_alerted=False), db, threshold=2)
        assert state.failures == 1 and state.outage_alerted is False
        backend.fail_with = None
        state = await _check(backend, state, db, threshold=2)
        assert state == StorageHealthState(outage_alerted=False, failures=0)
        backend.fail_with = OSError("timed out")
        state = await _check(backend, state, db, threshold=2)
        assert state.failures == 1, "the count restarts after a healthy check"
        assert _alerts(db) == []
        state = await _check(backend, state, db, threshold=2)
        assert state.outage_alerted is True and len(_alerts(db)) == 1, "the second consecutive failure confirms it"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_a_restart_during_an_outage_neither_repeats_the_alert_nor_misses_the_recovery(client, admin_token):
    backend = _MemoryBackend(fail_with=OSError("full"))
    db = SessionLocal()
    try:
        await _check(backend, StorageHealthState(), db)
        assert len(_alerts(db)) == 1
        # A new process (restart, or another worker elected leader) starts with no memory.
        state = await _check(backend, StorageHealthState(), db)
        assert state.outage_alerted is True and len(_alerts(db)) == 1, "the open outage is read from the alerts sent"
        # And it recovers in the new process: the recovery is not lost.
        backend.fail_with = None
        restarted = await _check(backend, StorageHealthState(), db)
        assert restarted.outage_alerted is False
        assert [a.title for a in _alerts(db)] == [
            "File storage is not accepting writes", "File storage recovered",
        ]
        # After a recovery, a new process starts clean.
        again = await _check(backend, StorageHealthState(), db)
        assert again.outage_alerted is False and len(_alerts(db)) == 2
    finally:
        db.close()


@pytest.mark.asyncio
async def test_admin_emails_are_sent_outside_the_running_event_loop(client, admin_token):
    """`send_email` uses `asyncio.run`, which raises inside a running loop; the alert must not call it there."""
    in_loop: list[bool] = []

    def spy(*_args, **_kwargs) -> None:
        try:
            asyncio.get_running_loop()
            in_loop.append(True)
        except RuntimeError:
            in_loop.append(False)

    db = SessionLocal()
    try:
        with patch("app.services.notifications.send_email", new=spy):
            await _check(_MemoryBackend(fail_with=OSError("full")), StorageHealthState(), db)
    finally:
        db.close()
    assert in_loop and not any(in_loop)


@pytest.mark.asyncio
async def test_the_deployment_address_is_emailed_when_configured(client, admin_token):
    db = SessionLocal()
    try:
        with patch.object(storage_health, "send_email_async", new=AsyncMock()) as send, patch.object(
            storage_health.settings, "deployment_notification_email", "ops@example.com"
        ), patch.object(storage_health.settings, "storage_health_failures_before_alert", 1):
            await storage_health.check_storage_health_once(
                _MemoryBackend(fail_with=OSError("boom")), StorageHealthState(), db,
            )
        send.assert_awaited_once()
        assert send.await_args.args[0] == "ops@example.com"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_local_disk_threshold_alert_also_notifies_server_admins_without_an_email_address(client, admin_token):
    class _Full:
        def disk_usage_percent(self) -> float:
            return 97.0

    db = SessionLocal()
    try:
        with patch.object(disk_monitor.settings, "deployment_notification_email", None), patch.object(
            disk_monitor.settings, "disk_usage_warning_threshold_percent", 90
        ), patch.object(disk_monitor, "send_email_async", new=AsyncMock()) as send:
            warned = await disk_monitor.check_disk_usage_once(_Full(), False, db)
        assert warned is True
        send.assert_not_awaited()
        assert [a.title for a in _alerts(db)] == ["Storage disk usage warning"]
    finally:
        db.close()


@pytest.mark.asyncio
async def test_loop_does_nothing_when_disabled():
    with patch.object(storage_health.settings, "storage_health_check_enabled", False), patch.object(
        storage_health, "check_storage_health_once", new=AsyncMock()
    ) as check:
        await storage_health.run_storage_health_loop()
    check.assert_not_awaited()


@pytest.mark.asyncio
async def test_loop_probes_then_waits_for_the_configured_interval():
    class _Stop(Exception):
        pass

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise _Stop

    with patch.object(storage_health.settings, "storage_health_check_enabled", True), patch.object(
        storage_health.settings, "storage_health_check_interval_seconds", 900
    ), patch.object(storage_health, "check_storage_health_once", new=AsyncMock(return_value=StorageHealthState())) as check, patch.object(
        storage_health.asyncio, "sleep", new=fake_sleep
    ), pytest.raises(_Stop):
        await storage_health.run_storage_health_loop()
    check.assert_awaited_once()
    assert sleeps == [900]


def test_alert_threshold_below_one_is_rejected():
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(storage_health_failures_before_alert=0)


def test_interval_below_a_minute_is_rejected():
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(storage_health_check_interval_seconds=10)


def test_storage_health_endpoint_is_server_admin_only_and_reports_failures(client, admin_token):
    org = client.get("/api/v1/orgs", headers=auth_headers(admin_token)).json()[0]
    create_org_user(client, admin_token, org["id"], "not-admin@example.com")
    from tests.conftest import login

    member_token = login(client, "not-admin@example.com", "Password123!")
    assert client.get("/api/v1/system/storage-health", headers=auth_headers(member_token)).status_code == 403

    with patch("app.routers.system.config.get_storage_backend", return_value=_MemoryBackend(fail_with=OSError("full"))):
        body = client.get("/api/v1/system/storage-health", headers=auth_headers(admin_token)).json()
    assert body["healthy"] is False and "full" in body["error"] and body["backend"] == "memory"


def test_real_configured_storage_accepts_writes(client, admin_token):
    """Canary for the environment: the storage this suite uses must be writable."""
    resp = client.get("/api/v1/system/storage-health", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["healthy"], (
        f"The {body['backend']} file storage is not accepting writes ({body['error']}). Uploads in other tests "
        f"will fail. {storage_health.FULL_DISK_HINT}"
    )
