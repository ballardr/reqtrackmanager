"""The scaling-shape guard: for every registered artefact type, the number of SQL statements behind its list, its detail,
its comments and its link graph does not grow with the records it serves.

Each type declares a `ScalingProbe` (`ModuleDefinition.scaling_probes`; core types in `services.scaling_probes_core`)
that creates records through the real create endpoint. The test fills a fresh project with a few records, counts the
statements a request issues, adds more records and counts again. A statement count that grows with rows is a lookup
per row (an N+1), the shape the requirement fixes removed; unlike a timing it is deterministic, so it runs with the
rest of the suite. The response may grow with its rows (an unpaged list returns them all); the statements may not.

A type whose count does grow is listed in `KNOWN_GROWING` against the check and the finding that will remove it. The
entry is strict both ways: a check that grows and is not listed fails, and a listed check that no longer grows fails
until the entry is removed, so the list can only shrink as the fixes land.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from app.database import engine
from app.modules.registry import (
    ScalingProbeApi,
    get_all_registered_artefact_types,
    get_module_registry,
    get_no_scaling_probe_types,
    get_scaling_probes,
)
from tests.conftest import auth_headers, create_org_admin_in, create_project

#: Records in the project when the first count is taken, and after the second batch is added.
SMALL, LARGE = 3, 9
#: Comments on the first record at each count.
COMMENTS_SMALL, COMMENTS_LARGE = 2, 6

#: Registered types whose probe is still to be written. Shrinks only: a type that gains a probe (or a reason) must be
#: removed from this set, and a new type must ship with one of the three.
TRACKED_GAPS = frozenset(
    {
        "compliance_required_action_assessment",
        "compliance_requirement",
        "project_compliance_requirement",
    }
)

#: `{artefact type: {check: finding}}` for a check whose statements grow with the records today. Checks are `list`,
#: `detail`, `comments`, `links` (the link graph of a record with N linked requirements), `activity` (its timeline) and
#: `export` (the project bundle, which carries every module's records), `record_export` (the type's own CSV export, the list's
#: Export action) and `record_import` (the preview of importing that CSV back, every row an update).
KNOWN_GROWING: dict[str, dict[str, str]] = {}


class _Api(ScalingProbeApi):
    """The probe's view of the API: JSON in, JSON out, any failure status raises."""

    def __init__(self, client, token: str) -> None:
        self._client = client
        self._headers = auth_headers(token)

    def post(self, path, body=None):
        resp = self._client.post(f"/api/v1{path}", json=body or {}, headers=self._headers)
        assert resp.status_code in (200, 201), f"POST {path}: {resp.status_code} {resp.text}"
        return resp.json()

    def get(self, path):
        resp = self._client.get(f"/api/v1{path}", headers=self._headers)
        assert resp.status_code == 200, f"GET {path}: {resp.status_code} {resp.text}"
        return resp.json()


class _Statements:
    """Counts the SQL statements executed while active."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self, *_args, **_kwargs) -> None:
        self.count += 1

    def __enter__(self):
        event.listen(engine, "before_cursor_execute", self)
        return self

    def __exit__(self, *_exc) -> None:
        event.remove(engine, "before_cursor_execute", self)


def _measure(api: _Api, path: str) -> int:
    """Statements for one GET of `path`, after a first identical GET has warmed the process-wide caches."""
    api.get(path)
    with _Statements() as statements:
        api.get(path)
    return statements.count


def _measure_export(client, token: str, project_id: str) -> int:
    """Statements for one project bundle export (a zip, so read as bytes), after a first identical export."""
    url = f"/api/v1/projects/{project_id}/export"
    assert client.get(url, headers=auth_headers(token)).status_code == 200
    with _Statements() as statements:
        resp = client.get(url, headers=auth_headers(token))
    assert resp.status_code == 200
    return statements.count


def _measure_record_table(client, token: str, project_id: str, artefact_type: str) -> dict[str, int]:
    """Statements for the type's CSV export and for the preview of importing that CSV back (a type that cannot be imported
    gives only the export), each after an identical first request."""
    headers = auth_headers(token)
    export = f"/api/v1/projects/{project_id}/records/{artefact_type}/export"
    first = client.get(export, headers=headers)
    assert first.status_code == 200, f"{export}: {first.status_code} {first.text[:200]}"
    with _Statements() as statements:
        csv_bytes = client.get(export, headers=headers).content
    counts = {"record_export": statements.count}
    url = f"/api/v1/projects/{project_id}/records/{artefact_type}/import?dry_run=true"
    files = {"file": ("records.csv", csv_bytes, "text/csv")}
    attempt = client.post(url, files=files, headers=headers)
    if attempt.status_code == 200:
        # Every row of the type's own export is found again (none is an error), so the batched lookup of the named
        # records matches what a lookup per row finds; a code that names no record is still reported as one.
        assert attempt.json()["failed"] == 0, attempt.text[:300]
        with _Statements() as statements:
            assert client.post(url, files=files, headers=headers).status_code == 200
        counts["record_import"] = statements.count
        unknown = client.post(url, files={"file": ("records.csv", b"code\nZZZ-999\n", "text/csv")}, headers=headers)
        assert unknown.status_code == 200 and unknown.json()["failed"] == 1, unknown.text[:300]
    else:
        assert attempt.status_code in (403, 404, 422), f"{url}: {attempt.status_code} {attempt.text[:200]}"
    return counts


def _first_link_option(api: _Api, project_id: str, artefact_type: str, artefact_id: str) -> dict | None:
    """A link type usable from the record to a requirement, in the orientation it offers, or `None`."""
    options = api.get(f"/projects/{project_id}/artefacts/{artefact_type}/{artefact_id}/link-types?other_type=requirement")
    return options[0] if options else None


def _link_requirements(api: _Api, project_id: str, artefact_type: str, artefact_id: str, option: dict, start: int, count: int) -> None:
    """Creates `count` requirements and links each to the record with the chosen link type."""
    probe = get_scaling_probes()["requirement"]
    for requirement_id in probe.create(api, project_id, start, count):
        api.post(
            f"/projects/{project_id}/artefacts/{artefact_type}/{artefact_id}/links",
            {"link_type_id": option["link_type_id"], "direction": option["direction"], "other_type": "requirement",
             "other_id": requirement_id},
        )


def _enable_every_module(client, token: str, org_id: str) -> None:
    for key, definition in get_module_registry().items():
        resp = client.put(f"/api/v1/orgs/{org_id}/modules/{key}", json={"enabled": True}, headers=auth_headers(token))
        assert resp.status_code == 200, f"enabling {key}: {resp.text}"
        for sub in definition.sub_components:
            resp = client.put(
                f"/api/v1/orgs/{org_id}/modules/{key}/subcomponents/{sub.key}", json={"enabled": True},
                headers=auth_headers(token),
            )
            assert resp.status_code == 200, f"enabling {key}/{sub.key}: {resp.text}"


def _growth(artefact_type: str, client, admin_token: str) -> dict[str, tuple[int, int]]:
    """`{check: (statements at SMALL, statements at LARGE)}` for every check of the type whose count differs."""
    org, token = create_org_admin_in(client, admin_token, f"Scaling {artefact_type} Co")
    _enable_every_module(client, token, org["id"])
    project_id = create_project(client, token, org["id"], "Scaling Project")["id"]
    api = _Api(client, token)
    probe = get_scaling_probes()[artefact_type]
    base = f"/projects/{project_id}/{probe.list_path}"
    grown: dict[str, tuple[int, int]] = {}

    def record(check: str, small: int, large: int) -> None:
        if small != large:
            grown[check] = (small, large)

    ids = probe.create(api, project_id, 0, SMALL)
    first = ids[0]
    option = _first_link_option(api, project_id, artefact_type, first)
    assert option is not None, f"{artefact_type} has no link type usable to a requirement, so the link graph cannot be probed"
    _link_requirements(api, project_id, artefact_type, first, option, 0, SMALL)
    if probe.has_comments:
        for n in range(COMMENTS_SMALL):
            api.post(f"{base}/{first}/comments", {"body": f"comment {n}"})
    graph = f"/projects/{project_id}/artefacts/{artefact_type}/{first}/link-graph?depth=1"
    activity = f"/projects/{project_id}/artefacts/{artefact_type}/{first}/activity?limit=25"
    small = {
        "list": _measure(api, base), "links": _measure(api, graph), "activity": _measure(api, activity),
        "export": _measure_export(client, token, project_id),
        **_measure_record_table(client, token, project_id, artefact_type),
    }
    if probe.has_detail:
        small["detail"] = _measure(api, f"{base}/{first}")
    if probe.has_comments:
        small["comments"] = _measure(api, f"{base}/{first}/comments")

    ids += probe.create(api, project_id, SMALL, LARGE - SMALL)
    _link_requirements(api, project_id, artefact_type, first, option, SMALL, LARGE - SMALL)
    if probe.has_comments:
        for n in range(COMMENTS_SMALL, COMMENTS_LARGE):
            api.post(f"{base}/{first}/comments", {"body": f"comment {n}"})
    large = {
        "list": _measure(api, base), "links": _measure(api, graph), "activity": _measure(api, activity),
        "export": _measure_export(client, token, project_id),
        **_measure_record_table(client, token, project_id, artefact_type),
    }
    if probe.has_detail:
        large["detail"] = _measure(api, f"{base}/{first}")
    if probe.has_comments:
        large["comments"] = _measure(api, f"{base}/{first}/comments")

    assert len(api.get(base)) >= LARGE, "the list did not return the records created"
    for check in small:
        record(check, small[check], large[check])
    return grown


def test_every_registered_artefact_type_has_a_scaling_probe_a_reason_or_a_tracked_gap():
    probes = set(get_scaling_probes())
    reasons = set(get_no_scaling_probe_types())
    missing = get_all_registered_artefact_types() - probes - reasons - TRACKED_GAPS
    assert not missing, f"artefact types with no scaling probe and no stated reason: {sorted(missing)}"


def test_the_tracked_gap_list_only_names_types_still_without_a_probe():
    registered = get_all_registered_artefact_types()
    done = TRACKED_GAPS & (set(get_scaling_probes()) | set(get_no_scaling_probe_types()))
    assert not done, f"remove from TRACKED_GAPS, they now have a probe or reason: {sorted(done)}"
    assert not (TRACKED_GAPS - registered), f"TRACKED_GAPS names unregistered types: {sorted(TRACKED_GAPS - registered)}"


def test_known_growing_names_only_probed_types_and_real_checks():
    probed = set(get_scaling_probes())
    assert set(KNOWN_GROWING) <= probed, sorted(set(KNOWN_GROWING) - probed)
    for artefact_type, checks in KNOWN_GROWING.items():
        known = {"list", "detail", "comments", "links", "activity", "export", "record_export", "record_import"}
        assert set(checks) <= known, (artefact_type, sorted(checks))
        assert all(reason.strip() for reason in checks.values()), artefact_type


@pytest.mark.parametrize("artefact_type", sorted(get_scaling_probes()))
def test_statements_do_not_grow_with_the_records(artefact_type, client, admin_token):
    grown = _growth(artefact_type, client, admin_token)
    expected = KNOWN_GROWING.get(artefact_type, {})
    unexpected = {check: counts for check, counts in grown.items() if check not in expected}
    fixed = sorted(set(expected) - set(grown))
    assert not unexpected, (
        f"{artefact_type}: statements grow with the records (check: (at {SMALL}, at {LARGE})): {unexpected}"
    )
    assert not fixed, f"{artefact_type}: {fixed} no longer grow; remove them from KNOWN_GROWING"


def test_organisation_export_statements_do_not_grow_with_the_records_of_its_projects(client, admin_token):
    """The organisation bundle runs the same module exports for every project, so its cost per record is the project
    export's: flat. (A project adds a fixed number of statements; a record adds none.)"""
    org, token = create_org_admin_in(client, admin_token, "Org Export Co")
    _enable_every_module(client, token, org["id"])
    project_id = create_project(client, token, org["id"], "Org Export Project")["id"]
    api = _Api(client, token)
    probes = get_scaling_probes()
    types = ("risk", "decision", "persona", "stakeholder", "engagement", "pain_point", "compliance_evidence")

    def measure() -> int:
        url = f"/api/v1/orgs/{org['id']}/export"
        assert client.get(url, headers=auth_headers(token)).status_code == 200
        with _Statements() as statements:
            assert client.get(url, headers=auth_headers(token)).status_code == 200
        return statements.count

    for t in types:
        probes[t].create(api, project_id, 0, SMALL)
    small = measure()
    for t in types:
        probes[t].create(api, project_id, SMALL, LARGE - SMALL)
    assert measure() == small
