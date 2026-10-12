"""
Module: services.storage_health

Detects file storage that has stopped accepting writes (a full disk, a bad
credential, an unreachable bucket) and tells people, instead of leaving it to
surface as a confusing 500 on the next upload.

Responsibilities:
- `probe_storage`: writes, reads back and deletes a tiny object through the
  configured backend. It works for any backend, including S3-compatible
  services whose capacity this process cannot read (`services.disk_monitor`
  only covers local disk percentage).
- `check_storage_health_once`: one probe plus the alerting rules. A failing
  probe is logged at ERROR on every check (so log shipping can alert), the
  `storage_write_healthy` gauge is set for Prometheus, and server admins are
  notified once when it starts failing and once when it recovers.
- `run_storage_health_loop`: the periodic check, started as a leader-only
  singleton (`main.py`). It can be switched off (`STORAGE_HEALTH_CHECK_ENABLED`)
  or slowed (`STORAGE_HEALTH_CHECK_INTERVAL_SECONDS`) so a metered S3 bucket is
  not charged for the probe requests.

Design decisions:
- State is held by the caller (`was_unhealthy`), like `disk_monitor`, so one
  alert is sent per outage, not one per check.
- The probe key lives under `_health/`, never a key `services.files` generates.
- A monitor failure must never take the app down, so the loop swallows and logs.

Dependencies: `services.notifications` (server-admin alert), `services.email`,
`app.metrics`, the storage backend from `services.files`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.metrics import storage_write_healthy
from app.models.notification import NotificationType
from app.services.email import send_email_async
from app.services.notifications import notify_server_admins

logger = logging.getLogger(__name__)
settings = get_settings()

PROBE_KEY = "_health/write-probe"
_PROBE_DATA = b"reqtrack-storage-probe"

FULL_DISK_HINT = (
    "A full disk is the usual cause. On the Docker test stack, free space with `docker builder prune -af`."
)


@dataclass(frozen=True)
class StorageProbeResult:
    """The outcome of one probe.

    Attributes:
        backend: The backend's name (`local` or `s3`).
        healthy: True when the write, read-back and delete all succeeded.
        error: The failure, as `ExceptionType: message`; None when healthy.
        checked_at: When the probe ran (UTC).
    """

    backend: str
    healthy: bool
    error: str | None
    checked_at: datetime


def probe_storage(backend) -> StorageProbeResult:
    """Writes, reads back and deletes a tiny object through `backend`.

    Args:
        backend: A `FileStorageBackend`.

    Returns:
        The result; never raises.
    """
    error: str | None = None
    try:
        backend.save(PROBE_KEY, _PROBE_DATA)
        if backend.read(PROBE_KEY) != _PROBE_DATA:
            error = "The probe object read back different bytes than were written."
        backend.delete(PROBE_KEY)
    except Exception as exc:  # noqa: BLE001 - any failure is the signal being reported
        error = f"{type(exc).__name__}: {exc}"
    return StorageProbeResult(
        backend=getattr(backend, "name", "unknown"), healthy=error is None, error=error, checked_at=datetime.now(UTC),
    )


async def check_storage_health_once(backend, was_unhealthy: bool, db: Session) -> bool:
    """Probes `backend` and alerts on a change of state.

    Args:
        backend: A `FileStorageBackend`.
        was_unhealthy: Whether the previous check failed (so only a change alerts).
        db: Session used to create the admin notifications.

    Returns:
        Whether storage is unhealthy now, to pass to the next call.
    """
    result = await asyncio.to_thread(probe_storage, backend)
    storage_write_healthy.set(1 if result.healthy else 0)
    if not result.healthy:
        logger.error("File storage (%s) is not accepting writes: %s. %s", result.backend, result.error, FULL_DISK_HINT)
        if not was_unhealthy:
            await _alert(
                db, "File storage is not accepting writes",
                f"The {result.backend} file storage failed a write check ({result.error}). "
                f"Uploads will fail until it is fixed. {FULL_DISK_HINT}",
            )
        return True
    if was_unhealthy:
        logger.warning("File storage (%s) is accepting writes again.", result.backend)
        await _alert(db, "File storage recovered", f"The {result.backend} file storage is accepting writes again.")
    return False


async def _alert(db: Session, title: str, body: str) -> None:
    """Notifies server admins in-app and the deployment address by email, if one is set."""
    notify_server_admins(db, notification_type=NotificationType.SYSTEM_STORAGE_ALERT, title=title, body=body)
    if settings.deployment_notification_email:
        try:
            await send_email_async(settings.deployment_notification_email, f"ReqTrackManager: {title}", body)
        except Exception:  # noqa: BLE001 - the in-app alert above already went out
            logger.exception("Could not email the storage alert")


async def run_storage_health_loop() -> None:
    """Runs forever, probing the configured storage backend every
    `STORAGE_HEALTH_CHECK_INTERVAL_SECONDS`; returns at once when
    `STORAGE_HEALTH_CHECK_ENABLED` is false (each probe is a billable
    write, read and delete on a metered S3 provider)."""
    if not settings.storage_health_check_enabled:
        logger.info("Storage health check disabled (STORAGE_HEALTH_CHECK_ENABLED=false).")
        return
    from app.database import SessionLocal
    from app.services.files import get_storage_backend

    was_unhealthy = False
    while True:
        db = SessionLocal()
        try:
            was_unhealthy = await check_storage_health_once(get_storage_backend(), was_unhealthy, db)
        except Exception:  # noqa: BLE001 - a monitor failure must never crash the app
            logger.exception("Storage health check failed")
        finally:
            db.close()
        await asyncio.sleep(settings.storage_health_check_interval_seconds)
