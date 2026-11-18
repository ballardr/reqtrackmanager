"""The access review of the Architecture module as tests: every route of the module is driven as someone who may not use
it, and none answers with a success or leaks a record. The sweeps read the real route table, so a route added later is
covered without an edit here.

- A person with no role in a project (or no membership of an organisation) gets 403/404 from every route.
- A person who may use one project gets nothing from another project's or organisation's records through any route.
- A plain member is refused by every write route.
- An Architect is refused by every route that needs an administrator.
Every test builds its own organisations.
"""

from __future__ import annotations

import re

from app.modules.architecture.tests._security_sweep import MEMBER_WRITES, WRITES, call, fill, minimal_body, routes
from app.modules.architecture.tests._security_world import World, build, records


def _leaks(world: World, text: str) -> list[str]:
    return [name for name in world.secrets if name in text]


def test_a_person_with_no_role_in_the_project_is_refused_by_every_route(client, admin_token):
    """Gate: the project routes of a project the caller has no role in, and the organisation routes of another
    organisation, answer 403/404 whatever the method, and carry no record."""
    world = build(client, admin_token, "Review gate")
    failures: list[str] = []
    found = list(routes(client.app))
    assert len(found) > 150, "the sweep found too few routes; the module's prefix may have changed"
    for method, path, _route in found:
        # The tester belongs to organisation A's project 1 only: project 2 of A and everything of B are out of reach.
        for owner, ids in (
            ({"project_id": world.a.p2["id"], "organization_id": world.a.org["id"]}, world.a.ids),
            ({"project_id": world.b.p1["id"], "organization_id": world.b.org["id"]}, world.b.ids),
        ):
            if "{organization_id}" in path and owner["organization_id"] == world.a.org["id"]:
                # The caller is a member of A (their role in project 1 makes them one), so organisation A's routes are
                # open to read; its writes need an administrator and are covered by the administrator sweep.
                continue
            url = fill(path, owner, ids)
            resp = call(client, method, url, world.architect)
            leaked = _leaks(world, resp.text)
            if resp.status_code not in (403, 404) or leaked:
                failures.append(f"{method} {url} -> {resp.status_code} {leaked}")
    assert not failures, "\n".join(failures)


def test_another_projects_records_are_unreachable_through_a_project_the_caller_can_open(client, admin_token):
    """Isolation: the caller opens project 1 and names project 2's or organisation B's records in it, and, at the organisation
    level, another organisation's. Nothing answers with a success for a write or a secret name for a read."""
    world = build(client, admin_token, "Review ids")
    failures: list[str] = []
    for method, path, _route in routes(client.app):
        if not re.search(r"\{(?!project_id|organization_id)\w+\}", path):
            continue
        owner = {"project_id": world.a.p1["id"], "organization_id": world.a.org["id"]}
        for ids in (world.a.ids, world.b.ids):
            url = fill(path, owner, ids)
            resp = call(client, method, url, world.architect)
            leaked = _leaks(world, resp.text)
            # A listing keyed by a requirement may answer 200 with no record; a write never may succeed.
            if resp.status_code >= 500 or leaked or (method != "GET" and resp.status_code < 300):
                failures.append(f"{method} {url} -> {resp.status_code} {leaked}")
    assert not failures, "\n".join(failures)


def test_a_plain_member_is_refused_by_every_write_route(client, admin_token):
    """RBAC: a member of the project who holds no module role cannot write through any route of its own project, apart
    from commenting, which needs only the right to read the record."""
    world = build(client, admin_token, "Review member")
    failures: list[str] = []
    # The member works in project 1; it has records of its own for the routes to find.
    own = records(client, world.a.admin, world.a.p1, "Own")
    for method, path, route in routes(client.app):
        if method not in WRITES or "{project_id}" not in path or MEMBER_WRITES.search(path):
            continue
        url = fill(path, {"project_id": world.a.p1["id"]}, own)
        resp = call(client, method, url, world.member, minimal_body(route), route)
        if resp.status_code not in (403, 404):
            failures.append(f"{method} {url} -> {resp.status_code} {resp.text[:120]}")
    assert not failures, "\n".join(failures)


def test_an_architect_is_refused_by_every_administrator_route(client, admin_token):
    """RBAC: an Architect cannot change a vocabulary or a symbol, import a file or change the organisation's records."""
    world = build(client, admin_token, "Review admin")
    failures: list[str] = []
    own = records(client, world.a.admin, world.a.p1, "Own")
    admin_only = re.compile(r"/(element-types|connection-types|domains|symbols)(/|$)|/interchange/json$")
    for method, path, route in routes(client.app):
        if method not in WRITES:
            continue
        if not (("{project_id}" in path and admin_only.search(path)) or "{organization_id}" in path):
            continue
        url = fill(path, {"project_id": world.a.p1["id"], "organization_id": world.a.org["id"]}, own)
        resp = call(client, method, url, world.architect, minimal_body(route), route)
        if resp.status_code not in (403, 404):
            failures.append(f"{method} {url} -> {resp.status_code} {resp.text[:120]}")
    assert not failures, "\n".join(failures)
