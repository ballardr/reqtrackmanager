"""
Module: services.dr_schedule

The in-container backup schedule: a small long-running loop that runs `run_backup` at each scheduled time, so
a deployment with no cron or systemd on the host still takes backups.

Responsibilities:
- Parse `BACKUP_SCHEDULE` (`HH:MM` daily in `BACKUP_SCHEDULE_TIMEZONE`, or `every Nh` for an N that divides 24)
  and work out the next and previous slot.
- Run a backup at each slot, catch up once at start when the last success is older than the previous slot,
  and retry a failed run after a delay (bounded, and never past the next slot).
- Publish a heartbeat textfile (`reqtrack-backup-scheduler.prom`) from a separate thread, so a backup that
  runs for hours is not mistaken for a dead scheduler, and answer the container health probe from it.

Design decisions:
- A daily time is a future, scheduled wall-clock time: it is kept as local time plus an IANA zone name and
  resolved to a UTC instant only when the next wait is computed, so "02:30 Australia/Sydney" stays 02:30
  across a daylight-saving change. A local time that does not exist that day (spring forward) runs an
  hour later on the wall clock; an ambiguous one (fall back) runs at its first occurrence.
- `every Nh` slots are aligned to UTC midnight; they carry no zone because an interval has no wall clock.
- The run itself is `run_backup` unchanged (same lock, same status file and metrics), so a scheduled run and
  a hand-started one cannot overlap and look identical to the monitoring.
- Nothing here talks to Docker, so the container needs no socket. The restore-test cannot run here for that
  reason and is scheduled from the host.

Dependencies: `services.dr_backup` (the run), the standard library (`zoneinfo`, `threading`).
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.dr_backup import write_atomic

HEARTBEAT_FILENAME = "reqtrack-backup-scheduler.prom"
HEARTBEAT_SECONDS = 30.0
"""How often the heartbeat file is rewritten; the health probe tolerates several missed beats."""
HEALTHY_WITHIN_SECONDS = 180.0
"""A heartbeat older than this means the scheduler is stuck or gone."""

_DAILY = re.compile(r"^(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)$")
_EVERY = re.compile(r"^every\s+(?P<hours>\d{1,2})\s*h$", re.IGNORECASE)


class ScheduleError(ValueError):
    """`BACKUP_SCHEDULE` or its time zone is not usable."""


class ScheduleSettings(BaseSettings):
    """Scheduler settings, read from `BACKUP_SCHEDULE*` environment variables.

    Attributes:
        schedule: `HH:MM` (daily) or `every Nh`; empty means no schedule.
        timezone: IANA zone name the daily time is meant in.
        retries: Extra attempts after a failed run in the same slot.
        retry_minutes: Delay before each retry.
    """

    model_config = SettingsConfigDict(env_prefix="BACKUP_SCHEDULE_", extra="ignore", populate_by_name=True)

    schedule: str = Field(default="", alias="BACKUP_SCHEDULE")
    timezone: str = "UTC"
    retries: int = Field(default=1, ge=0, le=5)
    retry_minutes: float = Field(default=30.0, gt=0)


@dataclass(frozen=True)
class Schedule:
    """A parsed schedule.

    Attributes:
        every_hours: Interval in hours for `every Nh` slots; 0 for a daily wall-clock time.
        hour / minute: The daily local time.
        zone: The zone the daily time is meant in.
    """

    every_hours: int = 0
    hour: int = 0
    minute: int = 0
    zone: ZoneInfo = ZoneInfo("UTC")

    @property
    def period_seconds(self) -> float:
        """The nominal time between runs (a day for a daily schedule), published as the expected interval."""
        return (self.every_hours or 24) * 3600.0

    def _slot_on(self, day: date) -> datetime:
        """The UTC instant of the daily time on a calendar day in `self.zone`.

        Args:
            day: The local calendar day.

        Returns:
            The slot as UTC. A local time that does not exist that day (spring forward) maps to the same
            offset-shifted instant, i.e. an hour later on the wall clock; an ambiguous one (fall back) to its
            first occurrence.
        """
        return datetime(day.year, day.month, day.day, self.hour, self.minute, tzinfo=self.zone).astimezone(UTC)

    def previous_slot(self, instant: datetime) -> datetime:
        """The latest slot at or before `instant` (UTC)."""
        instant = instant.astimezone(UTC)
        if self.every_hours:
            midnight = instant.replace(hour=0, minute=0, second=0, microsecond=0)
            hours = int((instant - midnight).total_seconds() // 3600)
            return midnight + timedelta(hours=hours - hours % self.every_hours)
        today = instant.astimezone(self.zone).date()
        slot = self._slot_on(today)
        return slot if slot <= instant else self._slot_on(today - timedelta(days=1))

    def next_slot(self, instant: datetime) -> datetime:
        """The first slot strictly after `instant` (UTC)."""
        instant = instant.astimezone(UTC)
        if self.every_hours:
            return self.previous_slot(instant) + timedelta(hours=self.every_hours)
        today = instant.astimezone(self.zone).date()
        slot = self._slot_on(today)
        return slot if slot > instant else self._slot_on(today + timedelta(days=1))


def parse_schedule(spec: str, timezone: str = "UTC") -> Schedule:
    """Parses a schedule.

    Args:
        spec: `HH:MM` or `every Nh` (N must divide 24: 1, 2, 3, 4, 6, 8, 12 or 24).
        timezone: IANA zone name for a daily time (ignored for `every Nh`).

    Returns:
        The schedule.

    Raises:
        ScheduleError: If the text or the zone is not recognised.
    """
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ScheduleError(f"unknown time zone {timezone!r} (use an IANA name such as Australia/Sydney)") from exc
    text = spec.strip()
    if daily := _DAILY.match(text):
        return Schedule(hour=int(daily["hour"]), minute=int(daily["minute"]), zone=zone)
    if every := _EVERY.match(text):
        hours = int(every["hours"])
        if hours < 1 or 24 % hours:
            raise ScheduleError("every Nh needs an N that divides 24 (1, 2, 3, 4, 6, 8, 12 or 24)")
        return Schedule(every_hours=hours, zone=zone)
    raise ScheduleError(f"BACKUP_SCHEDULE {spec!r} is neither HH:MM nor 'every Nh'")


def heartbeat_text(now: datetime, next_run: datetime | None, running: bool, period_seconds: float) -> str:
    """The scheduler's Prometheus textfile.

    Args:
        now: The current time.
        next_run: When the next run is due (None if unknown).
        running: Whether a backup is in progress.
        period_seconds: The nominal time between runs.
    """
    return "\n".join(
        [
            "# HELP reqtrack_backup_scheduler_heartbeat_timestamp_seconds Unix time the in-container scheduler last reported alive.",
            "# TYPE reqtrack_backup_scheduler_heartbeat_timestamp_seconds gauge",
            f"reqtrack_backup_scheduler_heartbeat_timestamp_seconds {now.timestamp():.0f}",
            "# HELP reqtrack_backup_scheduler_next_run_timestamp_seconds Unix time of the next scheduled backup.",
            "# TYPE reqtrack_backup_scheduler_next_run_timestamp_seconds gauge",
            f"reqtrack_backup_scheduler_next_run_timestamp_seconds {next_run.timestamp() if next_run else 0:.0f}",
            "# HELP reqtrack_backup_scheduler_run_in_progress 1 while a scheduled backup is running.",
            "# TYPE reqtrack_backup_scheduler_run_in_progress gauge",
            f"reqtrack_backup_scheduler_run_in_progress {1 if running else 0}",
            "# HELP reqtrack_backup_scheduler_period_seconds Nominal time between scheduled backups.",
            "# TYPE reqtrack_backup_scheduler_period_seconds gauge",
            f"reqtrack_backup_scheduler_period_seconds {period_seconds:.0f}",
            "",
        ]
    )


def is_healthy(status_dir: Path, now: float | None = None) -> bool:
    """Whether the scheduler's heartbeat file is recent (the container health probe).

    Args:
        status_dir: Where the heartbeat is written.
        now: Unix time to compare with (default: the clock).
    """
    try:
        age = (time.time() if now is None else now) - (status_dir / HEARTBEAT_FILENAME).stat().st_mtime
    except OSError:
        return False
    return age <= HEALTHY_WITHIN_SECONDS


class Scheduler:
    """Runs a backup callable at each slot of a schedule.

    The clock, the wait and the backup are injected so tests drive the loop without real time or a database.
    """

    def __init__(
        self,
        schedule: Schedule,
        settings: ScheduleSettings,
        status_dir: Path,
        run: Callable[[], bool],
        last_success: Callable[[], float | None],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        wait: Callable[[float], bool] | None = None,
        log: Callable[[str], None] = lambda message: print(message, flush=True),
    ) -> None:
        """Creates the scheduler.

        Args:
            schedule: The parsed schedule.
            settings: Retry settings.
            status_dir: Where the heartbeat is written.
            run: Takes one backup; returns True on success. It must not raise.
            last_success: Unix time of the last successful backup, or None if there has not been one.
            now: Clock (UTC).
            wait: Waits up to N seconds and returns True if the scheduler was asked to stop.
            log: Receives one line per event (counts and times only).
        """
        self._schedule, self._settings, self._status_dir = schedule, settings, status_dir
        self._run, self._last_success, self._now, self._log = run, last_success, now, log
        self._stop = threading.Event()
        self._wait = wait or self._stop.wait
        self._next_run: datetime | None = None
        self._running = False
        self._beat_lock = threading.Lock()

    def stop(self) -> None:
        """Asks the loop to finish (a backup in progress is allowed to complete)."""
        self._stop.set()

    def heartbeat(self) -> None:
        """Rewrites the heartbeat file once (serialised, so a slow beat can never overwrite a newer state)."""
        with self._beat_lock:
            write_atomic(
                self._status_dir / HEARTBEAT_FILENAME,
                heartbeat_text(self._now(), self._next_run, self._running, self._schedule.period_seconds),
            )

    def _beat(self) -> None:
        """Writes the heartbeat, logging (not raising) when the status directory is unwritable."""
        try:
            self.heartbeat()
        except OSError as exc:
            self._log(f"scheduler: cannot write heartbeat: {exc.__class__.__name__}")

    def _beat_until_stopped(self) -> None:
        """Thread body: beats until stopped, including while a backup holds the main thread."""
        while not self._stop.is_set():
            self._beat()
            self._stop.wait(HEARTBEAT_SECONDS)

    def _run_once(self, reason: str) -> bool:
        """Runs a backup, flagging it in progress for the heartbeat."""
        self._log(f"scheduler: starting backup ({reason})")
        self._running = True
        self._beat()
        try:
            ok = self._run()
        finally:
            self._running = False
            self._beat()
        self._log(f"scheduler: backup {'succeeded' if ok else 'FAILED'}")
        return ok

    def _needs_catch_up(self) -> bool:
        """True when the previous slot passed with no successful run after it (the container was down)."""
        last = self._last_success()
        return last is None or last < self._schedule.previous_slot(self._now()).timestamp()

    def serve(self) -> None:
        """Runs until `stop()`: catch up if due, then wait for each slot, run, retry a failure within the slot."""
        beat = threading.Thread(target=self._beat_until_stopped, name="backup-heartbeat", daemon=True)
        beat.start()
        try:
            ok = True
            if self._needs_catch_up():
                ok = self._run_once("catching up: no success since the last slot")
            retries = 0 if ok else self._settings.retries
            while not self._stop.is_set():
                slot = self._schedule.next_slot(self._now())
                retry_at = None
                if not ok and retries > 0:
                    retry_at = self._now() + timedelta(minutes=self._settings.retry_minutes)
                    if retry_at >= slot:
                        retry_at = None
                due = retry_at or slot
                self._next_run = due
                self._beat()
                self._log(f"scheduler: next backup at {due.isoformat()}")
                if self._sleep_until(due):
                    return
                if retry_at is not None:
                    retries -= 1
                    ok = self._run_once(f"retry, {retries} left")
                else:
                    ok = self._run_once("scheduled")
                    retries = 0 if ok else self._settings.retries
        finally:
            self._stop.set()
            beat.join(timeout=5)

    def _sleep_until(self, due: datetime) -> bool:
        """Waits until `due` in short steps (so a clock change or a stop is noticed); True if stopped."""
        while True:
            remaining = (due - self._now()).total_seconds()
            if remaining <= 0:
                return False
            if self._wait(min(remaining, 60.0)):
                return True


def settings_from_environment() -> tuple[Schedule, ScheduleSettings]:
    """Reads and validates the schedule from the environment.

    Returns:
        The parsed schedule and the retry settings.

    Raises:
        ScheduleError: If `BACKUP_SCHEDULE` is empty or invalid.
    """
    settings = ScheduleSettings()
    if not settings.schedule.strip():
        raise ScheduleError("BACKUP_SCHEDULE is empty: set it to HH:MM (daily) or 'every Nh'")
    return parse_schedule(settings.schedule, settings.timezone), settings
