"""
Module: services.scheduler

APScheduler wiring for the date-driven background checks: the review reminder sweep (C-R-08; requirement reviews and, through
the review engine, every other type's reviews and the phase schedules of stages and component tracks) and the project-stage
review-deadline auto-approval sweep (C-R-05).

Design decisions:
- Runs in-process in the single backend uvicorn process through `AsyncIOScheduler`, sharing the app's event loop; there is
  no separate worker service. The digest and disk-monitor loops (`services/notifications.py`, `services/disk_monitor.py`)
  use their own `while True: sleep(...)` mechanism.
- Modules contribute jobs generically through `app.modules.registry.ModuleScheduledJob` /
  `get_all_module_scheduled_jobs`, so this file never imports a module's sweep functions.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import SessionLocal
from app.modules.registry import ModuleScheduledJob, get_all_module_scheduled_jobs
from app.services.credential_reset import purge_spent_tokens
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


def _run_credential_token_purge() -> None:
    """Opens a DB session and removes password-reset tokens that were spent or expired more than a week ago."""
    db = SessionLocal()
    try:
        purge_spent_tokens(db)
    finally:
        db.close()


def _run_module_job(job: ModuleScheduledJob) -> None:
    """Opens a DB session and runs one module-contributed sweep
 — the generic counterpart of
    `_run_review_reminders`/`_run_stage_auto_approval` above, for any
    module's own `ModuleScheduledJob.run`."""
    db = SessionLocal()
    try:
        job.run(db)
    finally:
        db.close()


def start_scheduler() -> None:
    """Starts the daily review-reminder, stage-deadline and reset-token purge sweeps, plus
    every registered module's own declared scheduled jobs.

    Called once from `main.py`'s lifespan startup.
    """
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_run_review_reminders, CronTrigger(hour=1, minute=0), id="review_reminders")
    _scheduler.add_job(_run_stage_auto_approval, CronTrigger(hour=1, minute=15), id="stage_auto_approval")
    _scheduler.add_job(_run_credential_token_purge, CronTrigger(hour=1, minute=30), id="credential_token_purge")
    for module_key, job in get_all_module_scheduled_jobs():
        _scheduler.add_job(
            _run_module_job, CronTrigger(hour="*" if job.hour is None else job.hour, minute=job.minute),
            args=[job], id=f"{module_key}_{job.job_id}",
        )
    _scheduler.start()


def stop_scheduler() -> None:
    """Stops the scheduler on app shutdown."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
