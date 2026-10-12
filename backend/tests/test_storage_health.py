"""Tests for the file-storage health monitor (`services.storage_health`) and
its server-admin endpoint.

Covers: the probe (healthy, write failure, read-back mismatch), the alert rules
(server admins notified once when storage starts failing and once on recovery,
ERROR logged on every failing check, the Prometheus gauge), the local disk
monitor also notifying admins, and `GET /api/v1/system/storage-health`.

`test_real_configured_storage_accepts_writes` is also the canary for the test
environment itself: if the storage this suite runs against is full or
unreachable it fails here, naming the cause, instead of as an unexplained 500
in some upload test later.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.metrics import storage_write_healthy
from app.models.notification import Notification
from app.models.user import User
from app.services import disk_monitor, storage_health
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


@pytest.mark.asyncio
async def test_admins_are_notified_once_per_outage_and_once_on_recovery(client, admin_token, caplog):
    org = client.get("/api/v1/orgs", headers=auth_headers(admin_token)).json()[0]
    create_org_user(client, admin_token, org["id"], "plain-member@example.com")
    backend = _MemoryBackend(fail_with=OSError("No space left on device"))
    db = SessionLocal()
    try:
        with patch.object(storage_health, "send_email_async", new=AsyncMock()), caplog.at_level(logging.ERROR):
            unhealthy = await storage_health.check_storage_health_once(backend, False, db)
            assert unhealthy is True
            assert storage_write_healthy._value.get() == 0
            first = _alerts(db)
            assert len(first) == 1, "only the server admin is told, once"
            assert first[0].title == "File storage is not accepting writes"
            assert "No space left on device" in first[0].body and "docker builder prune" in first[0].body
            admin = db.scalar(select(User).where(User.email == "admin@example.com"))
            assert first[0].user_id == admin.id

            caplog.clear()
            unhealthy = await storage_health.check_storage_health_once(backend, unhealthy, db)
            assert unhealthy is True and len(_alerts(db)) == 1, "no repeat alert while still failing"
            assert any("not accepting writes" in r.message for r in caplog.records), "still logged at ERROR"

            backend.fail_with = None
            unhealthy = await storage_health.check_storage_health_once(backend, unhealthy, db)
            assert unhealthy is False and storage_write_healthy._value.get() == 1
            assert [a.title for a in _alerts(db)].count("File storage recovered") == 1

            await storage_health.check_storage_health_once(backend, False, db)
            assert len(_alerts(db)) == 2, "a healthy check after recovery stays quiet"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_the_deployment_address_is_emailed_when_configured(client, admin_token):
    db = SessionLocal()
    try:
        with patch.object(storage_health, "send_email_async", new=AsyncMock()) as send, patch.object(
            storage_health.settings, "deployment_notification_email", "ops@example.com"
        ):
            await storage_health.check_storage_health_once(_MemoryBackend(fail_with=OSError("boom")), False, db)
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
    ), patch.object(storage_health, "check_storage_health_once", new=AsyncMock(return_value=False)) as check, patch.object(
        storage_health.asyncio, "sleep", new=fake_sleep
    ), pytest.raises(_Stop):
        await storage_health.run_storage_health_loop()
    check.assert_awaited_once()
    assert sleeps == [900]


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
