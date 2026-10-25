"""Tests for the in-container backup schedule (`services.dr_schedule`): parsing, slot arithmetic across
daylight-saving changes, and the scheduler loop driven by a fake clock.

A daily time is a scheduled future wall-clock time, so the boundary cases are tested: 09:00 at UTC+10, 23:00 at
UTC-8, and the same wall-clock time a week either side of a daylight-saving change, plus a local time that does
not exist or occurs twice. The loop tests use no real time, database or restic; each builds its own state.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.services.dr_schedule import (
    HEALTHY_WITHIN_SECONDS,
    HEARTBEAT_FILENAME,
    ScheduleError,
    Scheduler,
    ScheduleSettings,
    heartbeat_text,
    is_healthy,
    parse_schedule,
    settings_from_environment,
)


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


# --- parsing ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("spec", ["02:30", "2:30", "00:00", "23:59", " 04:15 "])
def test_daily_times_parse(spec: str):
    schedule = parse_schedule(spec)
    assert schedule.every_hours == 0 and schedule.period_seconds == 86400


@pytest.mark.parametrize("spec,hours", [("every 6h", 6), ("every 1h", 1), ("EVERY 24h", 24), ("every 12 h", 12)])
def test_interval_schedules_parse(spec: str, hours: int):
    schedule = parse_schedule(spec)
    assert schedule.every_hours == hours and schedule.period_seconds == hours * 3600


@pytest.mark.parametrize("spec", ["", "nightly", "24:00", "02:60", "every 5h", "every 0h", "every 48h", "*/5 * * * *", "02:30:00"])
def test_unusable_schedules_are_refused(spec: str):
    with pytest.raises(ScheduleError):
        parse_schedule(spec)


def test_an_unknown_time_zone_is_refused_by_name():
    with pytest.raises(ScheduleError, match="IANA"):
        parse_schedule("02:30", "Mars/Olympus")


def test_environment_without_a_schedule_is_refused(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BACKUP_SCHEDULE", raising=False)
    with pytest.raises(ScheduleError, match="BACKUP_SCHEDULE is empty"):
        settings_from_environment()


def test_environment_is_read(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BACKUP_SCHEDULE", "03:15")
    monkeypatch.setenv("BACKUP_SCHEDULE_TIMEZONE", "Australia/Sydney")
    monkeypatch.setenv("BACKUP_SCHEDULE_RETRIES", "2")
    schedule, settings = settings_from_environment()
    assert (schedule.hour, schedule.minute, str(schedule.zone)) == (3, 15, "Australia/Sydney")
    assert settings.retries == 2 and settings.retry_minutes == 30


# --- slot arithmetic -------------------------------------------------------------------------------


def test_nine_oclock_at_utc_plus_ten_is_the_previous_evening_in_utc():
    schedule = parse_schedule("09:00", "Australia/Brisbane")  # no daylight saving: a fixed +10:00
    assert schedule.next_slot(_utc(2026, 7, 1, 0, 0)) == _utc(2026, 6, 30, 23, 0) + timedelta(days=1)
    assert schedule.next_slot(_utc(2026, 6, 30, 22, 59)) == _utc(2026, 6, 30, 23, 0)


def test_twenty_three_hundred_at_utc_minus_eight_lands_on_the_next_utc_day():
    schedule = parse_schedule("23:00", "America/Los_Angeles")  # PST in January: -08:00
    assert schedule.next_slot(_utc(2026, 1, 10, 12, 0)) == _utc(2026, 1, 11, 7, 0)
    assert schedule.previous_slot(_utc(2026, 1, 10, 12, 0)) == _utc(2026, 1, 10, 7, 0)


def test_the_same_wall_clock_time_holds_a_week_either_side_of_daylight_saving():
    # Sydney clocks go forward at 02:00 on Sunday 2026-10-04 (+10 to +11). 09:00 local stays 09:00 local.
    schedule = parse_schedule("09:00", "Australia/Sydney")
    before = schedule.next_slot(_utc(2026, 9, 27, 0, 0))
    after = schedule.next_slot(_utc(2026, 10, 11, 0, 0))
    assert before == _utc(2026, 9, 26, 23, 0) + timedelta(days=1) and before.astimezone(schedule.zone).hour == 9
    assert after == _utc(2026, 10, 10, 22, 0) + timedelta(days=1) and after.astimezone(schedule.zone).hour == 9
    assert before.utcoffset() == timedelta(0) and (before.astimezone(schedule.zone).utcoffset(), after.astimezone(schedule.zone).utcoffset()) == (
        timedelta(hours=10),
        timedelta(hours=11),
    )


def test_a_local_time_that_does_not_exist_runs_an_hour_later_on_the_wall_clock():
    schedule = parse_schedule("02:30", "Australia/Sydney")
    slot = schedule.next_slot(_utc(2026, 10, 3, 12, 0))  # the night clocks jump from 02:00 to 03:00
    assert slot.astimezone(schedule.zone).strftime("%Y-%m-%d %H:%M") == "2026-10-04 03:30"


def test_a_local_time_that_occurs_twice_runs_at_its_first_occurrence_only_once():
    schedule = parse_schedule("02:30", "Australia/Sydney")  # clocks go back 03:00 to 02:00 on 2026-04-05
    first = schedule.next_slot(_utc(2026, 4, 4, 12, 0))
    assert first == _utc(2026, 4, 4, 15, 30)  # 02:30 AEDT (+11)
    assert schedule.next_slot(first) == _utc(2026, 4, 5, 16, 30)  # the next day, 02:30 AEST (+10); not the repeat


def test_a_twenty_five_hour_day_does_not_skip_or_double_a_slot():
    schedule = parse_schedule("23:30", "Australia/Sydney")
    after_midnight = _utc(2026, 4, 4, 13, 45)  # 00:45 AEDT on the long day
    slot = schedule.next_slot(after_midnight)
    assert slot.astimezone(schedule.zone).strftime("%Y-%m-%d %H:%M") == "2026-04-05 23:30"
    assert schedule.next_slot(slot).astimezone(schedule.zone).strftime("%Y-%m-%d %H:%M") == "2026-04-06 23:30"


def test_next_is_strictly_after_and_previous_is_at_or_before():
    schedule = parse_schedule("02:30")
    on_the_slot = _utc(2026, 5, 1, 2, 30)
    assert schedule.previous_slot(on_the_slot) == on_the_slot
    assert schedule.next_slot(on_the_slot) == _utc(2026, 5, 2, 2, 30)
    assert schedule.previous_slot(_utc(2026, 5, 1, 2, 29)) == _utc(2026, 4, 30, 2, 30)


def test_interval_slots_are_aligned_to_utc_midnight():
    schedule = parse_schedule("every 6h")
    assert schedule.next_slot(_utc(2026, 5, 1, 0, 0)) == _utc(2026, 5, 1, 6, 0)
    assert schedule.next_slot(_utc(2026, 5, 1, 17, 59)) == _utc(2026, 5, 1, 18, 0)
    assert schedule.next_slot(_utc(2026, 5, 1, 18, 0)) == _utc(2026, 5, 2, 0, 0)
    assert schedule.previous_slot(_utc(2026, 5, 1, 17, 59)) == _utc(2026, 5, 1, 12, 0)


# --- the loop --------------------------------------------------------------------------------------


class Clock:
    """A clock that only moves when the scheduler waits, so a day of schedule runs in microseconds."""

    def __init__(self, start: datetime) -> None:
        self.now = start
        self.stop_at: datetime | None = None

    def __call__(self) -> datetime:
        return self.now

    def wait(self, seconds: float) -> bool:
        self.now += timedelta(seconds=seconds)
        return self.stop_at is not None and self.now >= self.stop_at


def _scheduler(
    tmp_path: Path,
    clock: Clock,
    outcomes: list[bool],
    spec: str = "02:30",
    last_success: float | None = None,
    retries: int = 1,
    retry_minutes: float = 30,
):
    runs: list[datetime] = []
    logs: list[str] = []

    def run() -> bool:
        runs.append(clock.now)
        return outcomes.pop(0) if outcomes else True

    scheduler = Scheduler(
        parse_schedule(spec),
        ScheduleSettings(retries=retries, retry_minutes=retry_minutes),
        tmp_path,
        run,
        lambda: last_success,
        now=clock,
        wait=clock.wait,
        log=logs.append,
    )
    return scheduler, runs, logs


def test_a_backup_runs_at_each_slot_and_not_in_between(tmp_path: Path):
    clock = Clock(_utc(2026, 5, 1, 12, 0))
    clock.stop_at = _utc(2026, 5, 4, 12, 0)
    scheduler, runs, _ = _scheduler(tmp_path, clock, [], last_success=_utc(2026, 5, 1, 2, 30).timestamp())
    scheduler.serve()
    assert runs == [_utc(2026, 5, 2, 2, 30), _utc(2026, 5, 3, 2, 30), _utc(2026, 5, 4, 2, 30)]


def test_it_catches_up_at_start_when_the_last_success_predates_the_last_slot(tmp_path: Path):
    clock = Clock(_utc(2026, 5, 3, 9, 0))
    clock.stop_at = _utc(2026, 5, 3, 9, 1)
    stale = _utc(2026, 5, 1, 2, 30).timestamp()  # the 05-02 and 05-03 slots were missed
    scheduler, runs, logs = _scheduler(tmp_path, clock, [], last_success=stale)
    scheduler.serve()
    assert runs == [_utc(2026, 5, 3, 9, 0)]
    assert any("catching up" in line for line in logs)


def test_it_catches_up_when_there_has_never_been_a_success(tmp_path: Path):
    clock = Clock(_utc(2026, 5, 3, 9, 0))
    clock.stop_at = _utc(2026, 5, 3, 9, 1)
    scheduler, runs, _ = _scheduler(tmp_path, clock, [], last_success=None)
    scheduler.serve()
    assert len(runs) == 1


def test_it_does_not_catch_up_after_a_success_since_the_last_slot(tmp_path: Path):
    clock = Clock(_utc(2026, 5, 3, 9, 0))
    clock.stop_at = _utc(2026, 5, 3, 9, 1)
    recent = _utc(2026, 5, 3, 2, 40).timestamp()
    scheduler, runs, _ = _scheduler(tmp_path, clock, [], last_success=recent)
    scheduler.serve()
    assert runs == []


def test_a_failed_run_is_retried_once_after_the_delay_then_waits_for_the_next_slot(tmp_path: Path):
    clock = Clock(_utc(2026, 5, 1, 2, 0))
    clock.stop_at = _utc(2026, 5, 1, 12, 0)
    scheduler, runs, _ = _scheduler(tmp_path, clock, [False, False], last_success=_utc(2026, 5, 1, 2, 0).timestamp(), retries=1, retry_minutes=30)
    scheduler.serve()
    assert len(runs) == 2
    assert runs[0] == _utc(2026, 5, 1, 2, 30)
    assert runs[1] - runs[0] == timedelta(minutes=30)


def test_a_retry_that_would_pass_the_next_slot_is_not_scheduled(tmp_path: Path):
    clock = Clock(_utc(2026, 5, 1, 2, 31))
    clock.stop_at = _utc(2026, 5, 2, 2, 29)
    # Catch-up fails at 02:31; a retry in 23 h 59 min would be past... retry_minutes is huge, so only the slot runs.
    scheduler, runs, _ = _scheduler(tmp_path, clock, [False, True], last_success=None, retries=1, retry_minutes=24 * 60)
    scheduler.serve()
    assert runs == [_utc(2026, 5, 1, 2, 31)]


def test_a_success_resets_the_retry_allowance(tmp_path: Path):
    clock = Clock(_utc(2026, 5, 1, 2, 0))
    clock.stop_at = _utc(2026, 5, 3, 0, 0)
    # slot1 fails, retry succeeds; slot2 fails, retry succeeds: each slot gets its own retry.
    scheduler, runs, _ = _scheduler(tmp_path, clock, [False, True, False, True], last_success=clock.now.timestamp(), retries=1)
    scheduler.serve()
    assert len(runs) == 4


def test_zero_retries_means_no_retry(tmp_path: Path):
    clock = Clock(_utc(2026, 5, 1, 2, 0))
    clock.stop_at = _utc(2026, 5, 1, 12, 0)
    scheduler, runs, _ = _scheduler(tmp_path, clock, [False], last_success=clock.now.timestamp(), retries=0)
    scheduler.serve()
    assert len(runs) == 1


def test_stop_ends_the_loop_without_running(tmp_path: Path):
    clock = Clock(_utc(2026, 5, 1, 12, 0))
    scheduler, runs, _ = _scheduler(tmp_path, clock, [], last_success=_utc(2026, 5, 1, 2, 30).timestamp())
    clock.stop_at = clock.now  # stopped on the first wait
    scheduler.serve()
    assert runs == []


def test_the_heartbeat_is_written_and_reports_progress(tmp_path: Path):
    clock = Clock(_utc(2026, 5, 1, 12, 0))
    clock.stop_at = _utc(2026, 5, 1, 12, 5)
    scheduler, _, _ = _scheduler(tmp_path, clock, [], last_success=_utc(2026, 5, 1, 2, 30).timestamp())
    scheduler.serve()
    text = (tmp_path / HEARTBEAT_FILENAME).read_text()
    assert f"reqtrack_backup_scheduler_next_run_timestamp_seconds {_utc(2026, 5, 2, 2, 30).timestamp():.0f}" in text
    assert "reqtrack_backup_scheduler_run_in_progress 0" in text
    assert "reqtrack_backup_scheduler_period_seconds 86400" in text


def test_a_backup_in_progress_is_flagged_in_the_heartbeat(tmp_path: Path):
    clock = Clock(_utc(2026, 5, 1, 2, 0))
    seen: list[str] = []
    holder: dict[str, Scheduler] = {}

    def run() -> bool:
        holder["s"].heartbeat()
        seen.append((tmp_path / HEARTBEAT_FILENAME).read_text())
        return True

    scheduler = Scheduler(
        parse_schedule("02:30"), ScheduleSettings(), tmp_path, run, lambda: clock.now.timestamp(), now=clock, wait=clock.wait, log=lambda _: None
    )
    holder["s"] = scheduler
    clock.stop_at = _utc(2026, 5, 1, 3, 0)
    scheduler.serve()
    assert "reqtrack_backup_scheduler_run_in_progress 1" in seen[0]
    assert "reqtrack_backup_scheduler_run_in_progress 0" in (tmp_path / HEARTBEAT_FILENAME).read_text()


# --- health ----------------------------------------------------------------------------------------


def test_health_follows_the_age_of_the_heartbeat(tmp_path: Path):
    assert not is_healthy(tmp_path)  # no file: never started
    (tmp_path / HEARTBEAT_FILENAME).write_text(heartbeat_text(_utc(2026, 5, 1), None, False, 86400))
    mtime = (tmp_path / HEARTBEAT_FILENAME).stat().st_mtime
    assert is_healthy(tmp_path, now=mtime + HEALTHY_WITHIN_SECONDS - 1)
    assert not is_healthy(tmp_path, now=mtime + HEALTHY_WITHIN_SECONDS + 1)


def test_the_heartbeat_text_is_valid_exposition_format_with_no_unit_surprises():
    text = heartbeat_text(_utc(2026, 5, 1, 12, 0), None, True, 21600)
    samples = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            name, value = line.split(" ")
            samples[name] = float(value)
    assert samples["reqtrack_backup_scheduler_heartbeat_timestamp_seconds"] == _utc(2026, 5, 1, 12, 0).timestamp()
    assert samples["reqtrack_backup_scheduler_next_run_timestamp_seconds"] == 0
    assert samples["reqtrack_backup_scheduler_run_in_progress"] == 1 and json.dumps(samples)
