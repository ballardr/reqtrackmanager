"""Tests for the demonstration setup command: its guards, the sign-in details message, the reset schedule,
password rotation and failure handling.

The pure rules (`services.demo_setup`) are tested directly. The command (`scripts/demo_setup.py`) talks HTTP with
`httpx`; the tests route those calls to the test client and replace the very large demonstration seed with a small
stand-in that creates the demonstration organisation and accounts through the seed's own helpers (the seed's
output is covered by its own tests).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services import demo_setup as rules
from tests.conftest import auth_headers, login

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import demo_setup as command  # noqa: E402
import seed_demo_data as seed  # noqa: E402

CATCHER = "mailhog"
DB = "reqtrack_demo"


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


# ---- pure rules -------------------------------------------------------------------------------------------


def _guard(**overrides):
    values = {"demo_flag": True, "existing_organisations": [], "database_name": DB, "confirm_database": None, "smtp_host": CATCHER}
    return rules.check_guards(**{**values, **overrides})


def test_the_flag_is_required():
    with pytest.raises(rules.DemoGuardError, match="--demo"):
        _guard(demo_flag=False)


def test_an_empty_or_demonstration_only_database_is_allowed():
    assert _guard() == []
    assert _guard(existing_organisations=["Solstice Robotics"]) == []


def test_another_organisation_refuses_until_the_database_name_is_typed():
    with pytest.raises(rules.DemoGuardError, match="--confirm-database reqtrack_demo"):
        _guard(existing_organisations=["Solstice Robotics", "Acme"])
    with pytest.raises(rules.DemoGuardError):
        _guard(existing_organisations=["Acme"], confirm_database="some_other_database")
    assert _guard(existing_organisations=["Acme"], confirm_database=DB) == ["Acme"]


@pytest.mark.parametrize("host", ["smtp.example.com", "10.0.0.5", "relay.corp.test"])
def test_a_mail_relay_that_is_not_a_catcher_is_refused(host: str):
    with pytest.raises(rules.DemoGuardError, match="mail catcher"):
        _guard(smtp_host=host)


@pytest.mark.parametrize("host", ["mailhog", "Mailpit", "localhost", "127.0.0.1", "::1", "127.0.0.2"])
def test_a_mail_catcher_or_loopback_address_is_allowed(host: str):
    assert _guard(smtp_host=host) == []


def test_database_name_is_read_from_the_url():
    assert rules.database_name_of("postgresql://u:p@db:5432/reqtrack_test") == "reqtrack_test"


def test_generated_passwords_are_long_varied_and_different():
    first, second = rules.generate_password(), rules.generate_password()
    assert first != second and len(first) == 20
    assert any(c.islower() for c in first) and any(c.isupper() for c in first) and any(c.isdigit() for c in first)
    assert any(not c.isalnum() for c in first)
    with pytest.raises(ValueError):
        rules.generate_password(8)


def test_the_accounts_are_the_ones_the_seed_creates():
    source = (Path(seed.__file__)).read_text(encoding="utf-8")
    for account in rules.DEMO_ACCOUNTS:
        assert f'"{account.email}", "{account.display_name}", "{account.role}"' in source
    assert rules.DEFAULT_PASSWORD == seed.PASSWORD


def test_the_message_lists_every_account_the_password_and_the_next_reset():
    schedule = rules.demo_schedule("00:00", "UTC")
    reset_at = rules.next_reset_at(schedule, _utc(2026, 11, 9, 13, 0))
    body = rules.login_message_body(rules.DEMO_ACCOUNTS, "Pa55word!", reset_at, schedule)
    for account in rules.DEMO_ACCOUNTS:
        assert account.email in body
    assert "Pa55word!" in body and "00:00 UTC (2026-11-10)" in body
    assert "http" not in body.lower() and "www." not in body.lower()


def test_a_message_that_does_not_fit_fails_instead_of_truncating():
    many = tuple(rules.DemoAccount(f"demo.person.{i}@example.com", "Person", "member") for i in range(60))
    with pytest.raises(rules.MessageTooLongError):
        rules.login_message_body(many, "Pa55word!", None, None)


@pytest.mark.parametrize(
    ("spec", "zone", "now", "expected"),
    [
        ("00:00", "UTC", _utc(2026, 11, 9, 13, 0), _utc(2026, 11, 10, 0, 0)),
        ("00:00", "UTC", _utc(2026, 11, 10, 0, 0), _utc(2026, 11, 11, 0, 0)),
        # 09:00 at UTC+10 is the previous evening in UTC.
        ("09:00", "Australia/Brisbane", _utc(2026, 11, 9, 13, 0), _utc(2026, 11, 9, 23, 0)),
        # 23:00 at UTC-8 lands on the next UTC day.
        ("23:00", "Etc/GMT+8", _utc(2026, 11, 9, 13, 0), _utc(2026, 11, 10, 7, 0)),
    ],
)
def test_the_next_reset_is_the_next_wall_clock_time_in_its_zone(spec, zone, now, expected):
    assert rules.next_reset_at(rules.demo_schedule(spec, zone), now) == expected


def test_the_same_wall_clock_time_holds_a_week_either_side_of_daylight_saving():
    schedule = rules.demo_schedule("00:00", "Australia/Sydney")
    before = rules.next_reset_at(schedule, _utc(2026, 9, 29, 0, 0))  # UTC+10, before the October change
    after = rules.next_reset_at(schedule, _utc(2026, 10, 10, 0, 0))  # UTC+11, after it
    assert before.astimezone(schedule.zone).strftime("%H:%M") == "00:00"
    assert after.astimezone(schedule.zone).strftime("%H:%M") == "00:00"
    assert before.hour == 14 and after.hour == 13


def test_overlapping_resets_are_refused(tmp_path):
    with rules.reset_lock(tmp_path):
        with pytest.raises(rules.ResetInProgressError), rules.reset_lock(tmp_path):
            pass
    with rules.reset_lock(tmp_path):
        pass


def test_the_metrics_file_says_what_happened_without_secrets():
    text = rules.reset_metrics_text(succeeded=False, finished=_utc(2026, 11, 9, 1, 0), next_reset=_utc(2026, 11, 10, 0, 0))
    assert "reqtrack_demo_reset_last_success 0" in text
    assert "reqtrack_demo_reset_next_timestamp_seconds" in text


# ---- the command ------------------------------------------------------------------------------------------


@pytest.fixture
def routed(client, monkeypatch):
    """Routes the command's and the seed's `httpx` calls to the test client."""
    origin = "http://localhost:8000"

    def route(method: str):
        def call(url: str, **kwargs):
            kwargs.pop("timeout", None)
            return getattr(client, method)(url.removeprefix(origin), **kwargs)

        return call

    def request(method: str, url: str, **kwargs):
        kwargs.pop("timeout", None)
        return client.request(method, url.removeprefix(origin), **kwargs)

    shim = SimpleNamespace(
        **{method: route(method) for method in ("get", "post", "put", "patch", "delete")},
        request=request, codes=httpx.codes, HTTPError=httpx.HTTPError, HTTPStatusError=httpx.HTTPStatusError,
    )
    monkeypatch.setattr(seed, "httpx", shim)
    monkeypatch.setattr(command, "httpx", shim)
    return client


@pytest.fixture
def stand_in_seed(monkeypatch):
    """Replaces the full seed by one that creates the demonstration organisation and its accounts."""

    def fake_main():
        admin = seed.h(seed.login(seed.ADMIN_EMAIL, seed.ADMIN_PASSWORD))
        org = seed.create_org(admin, "Solstice Robotics")
        for account in rules.DEMO_ACCOUNTS:
            seed.create_org_user(admin, org["id"], account.email, account.display_name, account.role)

    monkeypatch.setattr(seed, "main", fake_main)
    monkeypatch.setattr(seed, "PASSWORD", rules.DEFAULT_PASSWORD)


@pytest.fixture
def dirs(tmp_path):
    return ["--state-dir", str(tmp_path / "state"), "--status-dir", str(tmp_path / "status")]


def _confirm() -> list[str]:
    return ["--confirm-database", rules.database_name_of(command.get_settings().database_url)]


def _run(*arguments: str) -> int:
    return command.main(list(arguments))


def _messages(client, admin_token) -> list[dict]:
    return client.get("/api/v1/system/announcements", headers=auth_headers(admin_token)).json()["items"]


def test_setup_seeds_and_publishes_one_sign_in_message(routed, admin_token, stand_in_seed, dirs):
    assert _run("--demo", *_confirm(), *dirs) == 0
    assert any(o["name"] == "Solstice Robotics" for o in routed.get("/api/v1/orgs", headers=auth_headers(admin_token)).json())
    [message] = _messages(routed, admin_token)
    assert message["title"] == rules.LOGIN_MESSAGE_TITLE
    assert message["show_on_login"] is True and message["dismissible"] is False
    assert message["notified_at"] is None
    for account in rules.DEMO_ACCOUNTS:
        assert account.email in message["body"]
    assert rules.DEFAULT_PASSWORD in message["body"]
    shown = routed.get("/api/v1/announcements/login").json()
    assert [m["title"] for m in shown] == [rules.LOGIN_MESSAGE_TITLE]


def test_a_second_run_changes_nothing_and_does_not_duplicate_the_message(routed, admin_token, stand_in_seed, dirs):
    assert _run("--demo", *_confirm(), *dirs) == 0
    assert _run("--demo", *_confirm(), *dirs) == 0
    assert len(_messages(routed, admin_token)) == 1
    names = [o["name"] for o in routed.get("/api/v1/orgs", headers=auth_headers(admin_token)).json()]
    assert names.count("Solstice Robotics") == 1


def test_without_the_flag_nothing_is_changed(routed, admin_token, stand_in_seed, dirs, capsys):
    assert _run(*_confirm(), *dirs) == command.EXIT_REFUSED
    assert "--demo" in capsys.readouterr().err
    assert _messages(routed, admin_token) == []


def test_a_database_with_another_organisation_is_refused_without_confirmation(routed, admin_token, stand_in_seed, dirs, capsys):
    # The test database holds the bootstrap organisation, which this command did not create.
    assert _run("--demo", *dirs) == command.EXIT_REFUSED
    assert "--confirm-database" in capsys.readouterr().err
    names = [o["name"] for o in routed.get("/api/v1/orgs", headers=auth_headers(admin_token)).json()]
    assert "Solstice Robotics" not in names and _messages(routed, admin_token) == []


def test_a_reset_removes_only_the_demonstration_organisation(routed, admin_token, stand_in_seed, dirs):
    before = {o["name"] for o in routed.get("/api/v1/orgs", headers=auth_headers(admin_token)).json()}
    assert _run("--demo", *_confirm(), *dirs) == 0
    assert _run("--demo", "--reset", *_confirm(), *dirs) == 0
    after = [o["name"] for o in routed.get("/api/v1/orgs", headers=auth_headers(admin_token)).json()]
    assert before <= set(after) and after.count("Solstice Robotics") == 1
    assert len(_messages(routed, admin_token)) == 1


def test_teardown_removes_the_organisation_and_its_messages(routed, admin_token, stand_in_seed, dirs):
    assert _run("--demo", *_confirm(), *dirs) == 0
    assert _run("--demo", "--teardown", *_confirm(), *dirs) == 0
    names = [o["name"] for o in routed.get("/api/v1/orgs", headers=auth_headers(admin_token)).json()]
    assert "Solstice Robotics" not in names and _messages(routed, admin_token) == []


def test_rotating_gives_every_run_a_new_password_that_the_message_shows(routed, admin_token, stand_in_seed, dirs, capsys):
    assert _run("--demo", "--rotate-passwords", *_confirm(), *dirs) == 0
    first = _messages(routed, admin_token)[0]["body"].split("Password for every account: ")[1].splitlines()[0]
    assert first != rules.DEFAULT_PASSWORD
    login(routed, "demo.admin@example.com", first)
    # The accounts outlive the reset: the next run signs in with the stored password, changes it and re-joins them.
    assert _run("--demo", "--reset", "--rotate-passwords", *_confirm(), *dirs) == 0
    second = _messages(routed, admin_token)[0]["body"].split("Password for every account: ")[1].splitlines()[0]
    assert second not in (first, rules.DEFAULT_PASSWORD)
    login(routed, "demo.engineer@example.com", second)
    assert routed.post("/api/v1/auth/login", json={"email": "demo.engineer@example.com", "password": first}).status_code == 401
    output = capsys.readouterr()
    assert first not in output.out + output.err and second not in output.out + output.err
    assert (Path(dirs[1]) / "password").stat().st_mode & 0o777 == 0o600


def test_the_message_is_not_published_when_an_account_is_a_server_administrator(routed, admin_token, stand_in_seed, dirs, capsys):
    def seed_with_an_administrator():
        admin = seed.h(seed.login(seed.ADMIN_EMAIL, seed.ADMIN_PASSWORD))
        org = seed.create_org(admin, "Solstice Robotics")
        users = [seed.create_org_user(admin, org["id"], a.email, a.display_name, a.role) for a in rules.DEMO_ACCOUNTS]
        routed.put(
            f"/api/v1/system/users/{users[1]['user_id']}/server-admin", json={"is_server_admin": True}, headers=admin,
        ).raise_for_status()

    seed.main = seed_with_an_administrator
    assert _run("--demo", *_confirm(), *dirs) != 0
    assert _messages(routed, admin_token) == []
    assert "not a demonstration" in capsys.readouterr().err


def test_the_message_can_be_skipped(routed, admin_token, stand_in_seed, dirs):
    assert _run("--demo", "--no-login-message", *_confirm(), *dirs) == 0
    assert _messages(routed, admin_token) == []


def test_a_schedule_adds_a_non_dismissable_warning_for_the_hour_before_the_reset(routed, admin_token, stand_in_seed, dirs):
    assert _run("--demo", "--reset-at", "00:00", *_confirm(), *dirs) == 0
    by_title = {m["title"]: m for m in _messages(routed, admin_token)}
    warning = by_title[rules.RESET_WARNING_TITLE]
    assert warning["dismissible"] is False and warning["severity"] == "warning"
    assert warning["starts_at"] and warning["ends_at"] and warning["status"] == "scheduled"
    assert "resets daily" in by_title[rules.LOGIN_MESSAGE_TITLE]["body"]


def test_a_failed_seed_leaves_nothing_half_made_and_says_so(routed, admin_token, stand_in_seed, dirs, capsys):
    def failing_seed():
        admin = seed.h(seed.login(seed.ADMIN_EMAIL, seed.ADMIN_PASSWORD))
        seed.create_org(admin, "Solstice Robotics")
        raise httpx.ConnectError("seed failed")

    seed.main = failing_seed
    assert _run("--demo", "--reset", *_confirm(), *dirs) == command.EXIT_FAILED
    names = [o["name"] for o in routed.get("/api/v1/orgs", headers=auth_headers(admin_token)).json()]
    assert "Solstice Robotics" not in names
    assert "could not be kept" in capsys.readouterr().out
    assert "reqtrack_demo_reset_last_success 0" in (Path(dirs[3]) / rules.METRICS_FILENAME).read_text()


def test_overlapping_runs_are_refused(routed, stand_in_seed, dirs):
    with rules.reset_lock(Path(dirs[1])):
        assert _run("--demo", *_confirm(), *dirs) == command.EXIT_BUSY


def test_an_unusable_reset_time_is_refused(routed, dirs):
    assert _run("--demo", "--reset-at", "25:99", *dirs) == command.EXIT_REFUSED
    assert _run("schedule", "--demo", *dirs) == command.EXIT_REFUSED
    assert _run("--demo", "--reset-at", "00:00", "--reset-tz", "Nowhere/Land", *dirs) == command.EXIT_REFUSED
