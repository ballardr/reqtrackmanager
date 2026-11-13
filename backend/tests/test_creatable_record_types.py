"""The Links panel's "Create new" offers every type a person may author, and only to those who may create it.

Two guards:

- `frontend/src/modules/creatableRecordTypes.json` lists the registered artefact types the panel can create and the
  ones it cannot (`ModuleDefinition.not_creatable_from_links`); the frontend test requires a creator for each of the
  first, so the two halves cannot drift.
- For every creatable type and each kind of person (a plain member, a project manager, a stakeholder, and a holder of
  each module role), the `can_create` flag equals whether the type's real create endpoint accepts the request. A gate
  added to an endpoint without its record-table check, or a looser check than the endpoint, fails here. The create
  request is the one the type's scaling probe sends, replayed as the person.

Each test builds its own organisation, so none depends on state left by another test or run.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from app.database import SessionLocal
from app.models.project import Project
from app.models.user import User
from app.modules.registry import (
    ScalingProbeApi,
    get_all_registered_artefact_types,
    get_module_registry,
    get_not_creatable_from_links_types,
    get_scaling_probes,
)
from app.services.record_tables import creatable_record_types
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

FIXTURE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "modules" / "creatableRecordTypes.json"
PASSWORD = "Password123!"


def test_registered_types_are_creatable_or_state_why_not():
    registered = get_all_registered_artefact_types()
    excluded = get_not_creatable_from_links_types()
    assert set(excluded) <= registered, sorted(set(excluded) - registered)
    assert all(reason.strip() for reason in excluded.values())
    assert set(get_scaling_probes()) | set(excluded) >= registered, (
        "a creatable type needs a scaling probe (its create request is what the gate test replays); "
        f"missing: {sorted(registered - set(get_scaling_probes()) - set(excluded))}"
    )


@pytest.mark.skipif(not FIXTURE.exists(), reason="frontend sources are not available (backend-only image)")
def test_frontend_creatable_fixture_matches_the_backend_registry():
    listed = json.loads(FIXTURE.read_text())
    registered = get_all_registered_artefact_types()
    excluded = set(get_not_creatable_from_links_types())
    assert set(listed["notCreatable"]) == excluded and set(listed["creatable"]) == registered - excluded, (
        "frontend/src/modules/creatableRecordTypes.json is out of date. "
        f"creatable should be {sorted(registered - excluded)}; notCreatable should be {sorted(excluded)}. "
        "A new creatable type also needs a `linkedRecordCreators` entry on its frontend module."
    )


class _Recorder(ScalingProbeApi):
    """Runs a probe's requests as an administrator, except the numbered one, which runs as the person tested and
    reports its status instead of asserting success."""

    def __init__(self, client, admin_token: str, person_token: str | None = None, person_call: int = -1) -> None:
        self._client = client
        self._admin = auth_headers(admin_token)
        self._person = auth_headers(person_token) if person_token else None
        self._person_call = person_call
        self.posts = 0
        self.person_status: int | None = None

    def post(self, path, body=None):
        index = self.posts
        self.posts += 1
        if self._person is not None and index == self._person_call:
            resp = self._client.post(f"/api/v1{path}", json=body or {}, headers=self._person)
            self.person_status = resp.status_code
            return resp.json() if resp.status_code in (200, 201) else {"id": str(uuid.uuid4())}
        resp = self._client.post(f"/api/v1{path}", json=body or {}, headers=self._admin)
        assert resp.status_code in (200, 201), f"POST {path}: {resp.status_code} {resp.text}"
        return resp.json()

    def put(self, path, body=None):
        resp = self._client.put(f"/api/v1{path}", json=body or {}, headers=self._admin)
        assert resp.status_code in (200, 201), f"PUT {path}: {resp.status_code} {resp.text}"
        return resp.json()

    def get(self, path):
        resp = self._client.get(f"/api/v1{path}", headers=self._admin)
        assert resp.status_code == 200, f"GET {path}: {resp.status_code} {resp.text}"
        return resp.json()


def _enable_every_module(client, token: str, org_id: str) -> None:
    for key, definition in get_module_registry().items():
        assert client.put(f"/api/v1/orgs/{org_id}/modules/{key}", json={"enabled": True}, headers=auth_headers(token)).status_code == 200
        for sub in definition.sub_components:
            resp = client.put(
                f"/api/v1/orgs/{org_id}/modules/{key}/subcomponents/{sub.key}", json={"enabled": True}, headers=auth_headers(token),
            )
            assert resp.status_code == 200, resp.text


def _person(client, admin: str, org_id: str, project_id: str, label: str) -> tuple[str, str]:
    """A project member with no further role: `(user id, bearer token)`."""
    email = f"{label}-{uuid.uuid4().hex[:6]}@creatable.example.com"
    user_id = create_org_user(client, admin, org_id, email)
    resp = client.post(f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(admin))
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, PASSWORD)


def _grant_core_role(client, admin: str, project_id: str, user_id: str, role: str) -> None:
    resp = client.post(f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(admin))
    assert resp.status_code == 204, resp.text


def _grant_module_role(client, admin: str, org_id: str, project_id: str, user_id: str, module_key: str, role_key: str, scope: str) -> None:
    owner = f"projects/{project_id}/members" if scope == "project" else f"orgs/{org_id}/users"
    url = f"/api/v1/{owner}/{user_id}/module-roles"
    resp = client.post(url, json={"module_key": module_key, "role_key": role_key}, headers=auth_headers(admin))
    assert resp.status_code == 204, f"{module_key}.{role_key}: {resp.text}"


def _roles_to_try() -> list[tuple[str, str, str]]:
    """`(module key, role key, scope)` for every module role, so a type gated on any one of them is exercised."""
    return [
        (key, role.role_key, role.scope)
        for key, definition in sorted(get_module_registry().items())
        for role in definition.roles
        if role.scope in ("project", "org")
    ]


def test_can_create_flag_equals_the_create_endpoint_for_every_creatable_type_and_person(client, admin_token):
    org, admin = create_org_admin_in(client, admin_token, "Creatable Gate Co")
    _enable_every_module(client, admin, org["id"])
    project = create_project(client, admin, org["id"], "Creatable Gate Project")
    project_id = project["id"]

    people: dict[str, tuple[str, str]] = {"member": _person(client, admin, org["id"], project_id, "member")}
    for core_role in ("project_manager", "stakeholder"):
        user_id, token = _person(client, admin, org["id"], project_id, core_role)
        _grant_core_role(client, admin, project_id, user_id, core_role)
        people[core_role] = (user_id, token)
    for module_key, role_key, scope in _roles_to_try():
        user_id, token = _person(client, admin, org["id"], project_id, role_key)
        _grant_module_role(client, admin, org["id"], project_id, user_id, module_key, role_key, scope)
        people[f"{module_key}.{role_key}"] = (user_id, token)

    creatable = sorted(set(get_scaling_probes()) - set(get_not_creatable_from_links_types()))
    mismatches: list[str] = []
    db = SessionLocal()
    try:
        row = db.get(Project, uuid.UUID(project_id))
        assert row is not None
        for artefact_type in creatable:
            probe = get_scaling_probes()[artefact_type]
            # The first call may create prerequisites (a component, a type); the second shows the steady request count.
            probe.create(_Recorder(client, admin), project_id, 0, 1)
            counter = _Recorder(client, admin)
            probe.create(counter, project_id, 1, 1)
            assert counter.posts > 0, f"{artefact_type}: the probe made no create request"
            last = counter.posts - 1
            for number, (label, (user_id, token)) in enumerate(people.items(), start=1):
                recorder = _Recorder(client, admin, token, last)
                probe.create(recorder, project_id, number + 1, 1)
                assert recorder.person_status is not None, f"{artefact_type}: the probe's request count is not stable"
                assert recorder.person_status in (200, 201, 403), (
                    f"{artefact_type} as {label}: the create endpoint answered {recorder.person_status}, not a success or a refusal"
                )
                user = db.get(User, uuid.UUID(user_id))
                assert user is not None
                offered = artefact_type in creatable_record_types(db, user, row, [artefact_type])
                accepted = recorder.person_status in (200, 201)
                if offered != accepted:
                    mismatches.append(f"{artefact_type} as {label}: can_create={offered}, endpoint {'accepts' if accepted else 'refuses'}")
    finally:
        db.close()
    assert not mismatches, "the Links panel flag disagrees with the create endpoint:\n" + "\n".join(mismatches)
