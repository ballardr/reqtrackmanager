"""The Links panel's "Create new" answer: `can_create` on each record type of a `link-types` option.

The flag is the record type's own table check (`RecordTableProvider.can_create`, else the fine-grained
`propose_create` permission), so it must agree with what the type's create endpoint does for the same person.
Each test builds its own organisation, so none depends on state left by another test or run.
"""

from __future__ import annotations

import uuid

from app.database import SessionLocal
from app.models.project import Project
from app.models.user import User
from app.modules.stakeholders.tests.test_need_api import _PAYLOAD as NEED_PAYLOAD
from app.modules.stakeholders.tests.test_need_api import _needs
from app.modules.stakeholders.tests.test_persona_api import _add_member, _grant_project_role, _setup
from app.services.record_tables import creatable_record_types
from tests.conftest import auth_headers, create_component_and_category

NEED = "stakeholder_need"


def _requirement(client, token, project_id) -> str:
    component_id, category_id = create_component_and_category(client, token, project_id)
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _can_create(client, token, project_id, requirement_id) -> dict[str, bool]:
    """`{record type: can_create}` over every option the requirement's Links panel is offered."""
    resp = client.get(
        f"/api/v1/projects/{project_id}/artefacts/requirement/{requirement_id}/link-types", headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    flags: dict[str, set[bool]] = {}
    for option in resp.json():
        for other in option["other_types"]:
            flags.setdefault(other["type"], set()).add(other["can_create"])
    assert all(len(values) == 1 for values in flags.values()), "one type must carry one answer across options"
    return {artefact_type: next(iter(values)) for artefact_type, values in flags.items()}


def _create_status(client, token, project_id) -> int:
    return client.post(_needs(project_id), json={**NEED_PAYLOAD}, headers=auth_headers(token)).status_code


def test_flag_follows_the_types_own_create_gate_for_each_person(client, admin_token):
    org, project, admin = _setup(client, admin_token, "Can Create Co")
    requirement_id = _requirement(client, admin, project["id"])
    _, member = _add_member(client, admin, org["id"], project["id"], f"member-{uuid.uuid4().hex[:6]}@can-create.example.com")
    owner_id, owner = _add_member(client, admin, org["id"], project["id"], f"owner-{uuid.uuid4().hex[:6]}@can-create.example.com")
    _grant_project_role(client, admin, project["id"], owner_id, "stakeholder_need_owner")

    assert _can_create(client, admin, project["id"], requirement_id)[NEED] is True
    assert _create_status(client, admin, project["id"]) == 201

    # A plain member sees the type is not creatable, and the create endpoint agrees.
    assert _can_create(client, member, project["id"], requirement_id)[NEED] is False
    assert _create_status(client, member, project["id"]) == 403

    # The role that gates the create endpoint is the role that turns the flag on.
    assert _can_create(client, owner, project["id"], requirement_id)[NEED] is True
    assert _create_status(client, owner, project["id"]) == 201


def test_a_type_with_no_record_table_is_never_creatable(client, admin_token):
    _org, project, admin = _setup(client, admin_token, "Can Create No Table Co")
    admin_id = uuid.UUID(client.get("/api/v1/auth/me", headers=auth_headers(admin)).json()["id"])
    db = SessionLocal()
    try:
        row = db.get(Project, uuid.UUID(project["id"]))
        user = db.get(User, admin_id)
        assert row is not None and user is not None
        assert creatable_record_types(db, user, row, ["nothing_registered", NEED]) == {NEED}
    finally:
        db.close()
