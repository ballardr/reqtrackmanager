"""
Module: loadgen.run

The load generator's entry point: runs one scenario against the performance stack's backend and prints a JSON
summary.

Responsibilities:
- Read the request (scenario, simulated users, duration, warm-up, the dataset manifest) from stdin, sign the
  simulated people in once, run the scenario with Locust's programmatic API, and print per-endpoint statistics.

Design decisions:
- The target is the constant `TARGET`: the stack's own `backend` service on the Compose network. There is no
  option to name another host, URL or database, so this program cannot be pointed at anything else (the
  production stack included).
- Logging in happens before the clock starts, once per simulated person, so bcrypt's deliberate cost is not
  measured. Tokens last twelve hours, longer than any soak.
- The warm-up period runs the scenario and then discards its statistics, so caches and connection pools are warm
  when measurement begins.
- Progress goes to stderr; stdout carries only the final JSON document.

Dependencies: locust (and its `requests`), `scenarios.py` beside it.
"""

from __future__ import annotations

from gevent import monkey

monkey.patch_all()  # before anything imports ssl or requests, as Locust itself does on import

import itertools  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

import gevent  # noqa: E402
import requests  # noqa: E402
from locust.env import Environment  # noqa: E402

from scenarios import SCENARIOS, THROTTLED  # noqa: E402

#: The only host this program talks to: the stack's backend service on the Compose network.
TARGET = "http://backend:8000"
PASSWORD_ENV = "PERF_USER_PASSWORD"
LOGIN_TIMEOUT_SECONDS = 120


def say(line: str) -> None:
    """Writes a progress line to stderr."""
    print(line, file=sys.stderr, flush=True)


class Shared:
    """What every simulated person shares: the manifest and the signed-in personas.

    Attributes:
        projects_by_org: The manifest's projects grouped by organisation id.
        members / admins: Signed-in personas (dicts with `email`, `token`, `user_id`, `org_id`).
    """

    def __init__(self, manifest: dict, users: int, needs_admin: bool, password: str) -> None:
        self.projects_by_org: dict[str, list[dict]] = {}
        for project in manifest["projects"]:
            self.projects_by_org.setdefault(project["organization_id"], []).append(project)
        self.members: list[dict] = []
        self.admins: list[dict] = []
        orgs = manifest["organisations"]
        wanted_members = max(users, 1)
        for index in range(wanted_members):
            org = orgs[index % len(orgs)]
            slot = (index // len(orgs)) % len(org["member_emails"])
            self.members.append(self._login(org, org["member_emails"][slot], org["user_ids"][slot + 1], password))
        if needs_admin:
            for org in orgs[: max(1, min(len(orgs), users))]:
                self.admins.append(self._login(org, org["admin_email"], org["user_ids"][0], password))
        self._members = itertools.cycle(self.members)
        self._admins = itertools.cycle(self.admins)

    @staticmethod
    def _login(org: dict, email: str, user_id: str, password: str) -> dict:
        response = requests.post(f"{TARGET}/api/v1/auth/login", json={"email": email, "password": password}, timeout=LOGIN_TIMEOUT_SECONDS)
        response.raise_for_status()
        return {"email": email, "token": response.json()["access_token"], "user_id": user_id, "org_id": org["id"]}

    def next_persona(self, *, admin: bool) -> dict:
        """The next signed-in person, round-robin (an organisation administrator when `admin`)."""
        return next(self._admins if admin else self._members)

    def pick_project(self, persona: dict, *, nested_root: bool) -> dict:
        """A project of the persona's organisation (the root of a project tree when `nested_root`)."""
        projects = self.projects_by_org[persona["org_id"]]
        if nested_root:
            roots = [p for p in projects if p["depth"] == 0 and any(c["parent_id"] == p["id"] for c in projects)]
            return roots[0] if roots else projects[0]
        return random.choice(projects)


def summarise(environment: Environment, duration: float) -> dict:
    """Per-endpoint statistics for the measured period.

    Args:
        environment: The finished Locust environment.
        duration: Seconds measured (after warm-up).

    Returns:
        `{"requests": [...], "total": {...}}` with counts, failures, throttled counts, percentiles in
        milliseconds and requests per second.
    """
    throttled: dict[tuple[str, str], int] = {}
    for error in environment.stats.errors.values():
        if THROTTLED in str(error.error):
            throttled[(error.method, error.name)] = throttled.get((error.method, error.name), 0) + error.occurrences

    def row(entry) -> dict:
        count = entry.num_requests
        limited = throttled.get((entry.method, entry.name), 0)
        return {
            "name": entry.name, "method": entry.method, "count": count, "failures": entry.num_failures - limited, "throttled": limited,
            "p50_ms": entry.get_response_time_percentile(0.50) if count else None,
            "p95_ms": entry.get_response_time_percentile(0.95) if count else None,
            "p99_ms": entry.get_response_time_percentile(0.99) if count else None,
            "mean_ms": round(entry.avg_response_time, 1) if count else None,
            "max_ms": entry.max_response_time if count else None,
            "rps": round(count / duration, 3) if duration else None,
            "bytes_mean": round(entry.avg_content_length) if count else None,
        }

    rows = [row(entry) for entry in environment.stats.entries.values() if not entry.name.startswith("setup:")]
    total = {"count": sum(r["count"] for r in rows), "failures": sum(r["failures"] for r in rows), "throttled": sum(r["throttled"] for r in rows)}
    total["rps"] = round(total["count"] / duration, 3) if duration else None
    return {"requests": sorted(rows, key=lambda r: r["name"]), "total": total}


def run(request: dict, password: str) -> dict:
    """Runs one scenario and returns the summary document.

    Args:
        request: `scenario`, `users`, `duration_s`, `warmup_s`, optional `min_requests` and `max_seconds`, and the dataset `manifest`.
        password: The password every generated person was given for this run.

    Returns:
        The summary (see `summarise`) plus the request parameters and the wall-clock seconds measured.

    Raises:
        KeyError: If the scenario is not defined.
    """
    scenario = SCENARIOS[request["scenario"]]
    users, duration, warmup = int(request["users"]), float(request["duration_s"]), float(request.get("warmup_s", 0))
    say(f"signing in {users} simulated people")
    environment = Environment(user_classes=[scenario], host=TARGET)
    environment.shared = Shared(request["manifest"], users, scenario.needs_admin, password)
    runner = environment.create_local_runner()
    say(f"running {request['scenario']} with {users} users: {warmup:.0f}s warm-up, {duration:.0f}s measured")
    runner.start(users, spawn_rate=max(users, 1))
    if warmup:
        gevent.sleep(warmup)
        environment.stats.reset_all()
    started = time.monotonic()
    gevent.sleep(duration)
    # A slow closed-loop scenario keeps going until enough requests finished, but never past `max_seconds`.
    minimum, ceiling = int(request.get("min_requests", 0)), float(request.get("max_seconds", duration))
    while environment.stats.total.num_requests < minimum and time.monotonic() - started < ceiling:
        gevent.sleep(1)
    measured = time.monotonic() - started
    summary = summarise(environment, measured)
    runner.quit()
    return {"scenario": request["scenario"], "users": users, "duration_s": round(measured, 1), "warmup_s": warmup, **summary}


def main() -> int:
    """Reads the request from stdin, runs it and prints the summary; returns the process exit status."""
    password = os.environ.get(PASSWORD_ENV, "")
    if not password:
        say(f"{PASSWORD_ENV} is not set")
        return 2
    request = json.load(sys.stdin)
    if request.get("scenario") not in SCENARIOS:
        say(f"unknown scenario {request.get('scenario')!r}; defined: {', '.join(sorted(SCENARIOS))}")
        return 2
    print(json.dumps(run(request, password)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
