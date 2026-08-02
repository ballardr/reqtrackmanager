"""
Module: services.scheduler

APScheduler wiring for the date-driven background checks introduced in
Massif (v3): the requirement review-due notification sweep (C-R-08) and the
project-stage review-deadline auto-approval sweep (C-R-05). Runs in-process
inside the existing single backend container/uvicorn process via
AsyncIOScheduler, sharing the app's event loop — no separate worker service.

The existing digest/disk-monitor loops (services/notifications.py,
services/disk_monitor.py) are deliberately left on their own
`while True: sleep(...)` mechanism rather than migrated here; this module is
additive infrastructure for the new date-driven jobs, not a replacement for
proven, already-tested code.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import SessionLocal
from app.services.reviews import send_due_review_reminders
from app.services.stages import auto_approve_overdue_stage_reviews

_scheduler: AsyncIOScheduler | None = None


def _run_review_reminders() -> None:
    """Opens a DB session and runs the review-due reminder sweep (C-R-08)."""
    db = SessionLocal()
    try:
        send_due_review_reminders(db)
    finally:
        db.close()


def _run_stage_auto_approval() -> None:
    """Opens a DB session and runs the stage review-deadline sweep (C-R-05)."""
    db = SessionLocal()
    try:
        auto_approve_overdue_stage_reviews(db)
    finally:
        db.close()


def start_scheduler() -> None:
    """Starts the daily review-reminder and stage-deadline sweeps.

    Called once from `main.py`'s lifespan startup.
    """
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_run_review_reminders, CronTrigger(hour=1, minute=0), id="review_reminders")
    _scheduler.add_job(_run_stage_auto_approval, CronTrigger(hour=1, minute=15), id="stage_auto_approval")
    _scheduler.start()


def stop_scheduler() -> None:
    """Stops the scheduler on app shutdown."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
