"""
Module: services.disk_monitor

Monitors local file storage disk usage and emails the configured deployment
notification address when a threshold is exceeded (I-M-11), so operators
find out before storage actually fills up. Only meaningful for the "local"
storage backend — an S3-compatible backend's capacity is managed by that
service, not this process's disk.

Runs as an in-process asyncio background task on a timer, consistent with
the existing single-instance pub/sub pattern (services/pubsub.py), rather
than a separate worker service — that's a later-milestone concern per
solution-architecture.md, not required for this deployment model.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.email import send_email_async
from app.services.email_branding import resolve_email_branding
from app.services.email_templates import render_email

logger = logging.getLogger(__name__)
settings = get_settings()

CHECK_INTERVAL_SECONDS = 15 * 60


async def check_disk_usage_once(backend, already_warned: bool, db: Session) -> bool:
    """Runs a single disk-usage check against `backend`, emailing the
    deployment notification address the first time usage crosses the
    configured threshold. Returns the updated `already_warned` state so the
    caller can avoid re-sending the warning on every subsequent check while
    usage remains above the threshold.

    Split out from `run_disk_monitor_loop` so the check itself (the part
    with actual branching logic) can be exercised in tests without waiting
    on `CHECK_INTERVAL_SECONDS`.

    Args:
        db: Used only to resolve platform branding for the alert email —
            this is a deployment-operator alert, not tied to any single
            organisation, so it always uses the platform defaults (see
            `services/email_templates.py`).
    """
    if not hasattr(backend, "disk_usage_percent"):
        return already_warned
    usage_percent = backend.disk_usage_percent()
    if usage_percent >= settings.disk_usage_warning_threshold_percent:
        if not already_warned:
            branding = resolve_email_branding(db, organization_id=None)
            html_body, text_body = render_email(
                "disk_alert", branding=branding, usage_percent=usage_percent,
                threshold_percent=settings.disk_usage_warning_threshold_percent,
                cta_url=f"{settings.frontend_base_url}/server/management",
            )
            inline_images = {"brand_logo": (branding.logo_bytes, branding.logo_content_type)} if branding.logo_bytes else None
            await send_email_async(
                settings.deployment_notification_email,
                "ReqTrackManager: storage disk usage warning",
                text_body, html_body=html_body, inline_images=inline_images,
            )
        return True
    return False


async def run_disk_monitor_loop() -> None:
    """Runs forever, periodically checking local disk usage."""
    if settings.storage_backend != "local" or not settings.deployment_notification_email:
        return

    from app.database import SessionLocal
    from app.services.files import get_storage_backend

    already_warned = False
    while True:
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        db = SessionLocal()
        try:
            backend = get_storage_backend()
            already_warned = await check_disk_usage_once(backend, already_warned, db)
        except Exception:  # noqa: BLE001 - a monitor failure must never crash the app
            logger.exception("Disk usage monitor check failed")
        finally:
            db.close()
