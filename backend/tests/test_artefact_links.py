"""Tests for the generic polymorphic relationship model (Module 0 —
Platform Foundations, Phase 1): `app.models.relationship.ArtefactLink` and
`app.services.relationships`.

`test_requirement_links.py`/`test_requirement_action_links.py` already
exercise the two currently-wired artefact-type pairs through their own
REST endpoints (`routers.requirements`'s links/actions sections), which
internally call this generic service — this file instead exercises the
*service layer itself* directly, across artefact types, since the entire
point of building a polymorphic table is that it generalises past one type
pair (per the plan's own verification bar: "exercise the cross-module
case... rather than only a single-type-pair happy path").
"""

from uuid import UUID

from app.database import SessionLocal
from app.models.enums import ArtefactType
from app.services import relationships
from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project


def _create_requirement(client, token, project_id, component_id, category_id, name="Req"):
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_action(client, token, project_id, title="Action"):
    action_types = client.get(f"/api/v1/projects/{project_id}/action-types", headers=auth_headers(token)).json()
    resp = client.post(
        f"/api/v1/projects/{project_id}/actions",
        json={"title": title, "action_type_id": action_types[0]["id"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_generic_service_links_two_different_artefact_types(client, admin_token):
    """Creates a link between a `Requirement` and a `RequirementAction` —
    two distinct `ArtefactType` values — via the generic service directly
    (not through either type's own REST endpoint), and confirms it's
    queryable from both `get_links_from`/`get_links_to`/`get_all_links`,
    from either end."""
    org, token = create_org_admin_in(client, admin_token, "Artefact Link Cross-Type Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"], component_id, category_id)
    action = _create_action(client, token, project["id"])
    action_id = UUID(action["id"])
    requirement_id = UUID(requirement["id"])
    creator_id = UUID(action["creator_id"])

    db = SessionLocal()
    try:
        link = relationships.create_link(
            db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=action_id,
            target_type=ArtefactType.REQUIREMENT, target_id=requirement_id,
            link_type_id=None, created_by=creator_id,
        )
        db.commit()

        from_action = relationships.get_links_from(db, ArtefactType.REQUIREMENT_ACTION, action_id)
        assert [link.id for link in from_action] == [link.id]
        assert from_action[0].target_type == ArtefactType.REQUIREMENT
        assert from_action[0].target_id == requirement_id

        to_requirement = relationships.get_links_to(db, ArtefactType.REQUIREMENT, requirement_id)
        assert [link.id for link in to_requirement] == [link.id]
        assert to_requirement[0].source_type == ArtefactType.REQUIREMENT_ACTION
        assert to_requirement[0].source_id == action_id

        # Nothing links *to* the action, and the action links to nothing else.
        assert relationships.get_links_to(db, ArtefactType.REQUIREMENT_ACTION, action_id) == []
        assert relationships.get_links_from(db, ArtefactType.REQUIREMENT, requirement_id) == []

        # get_all_links is direction-agnostic: found from either artefact's
        # own perspective.
        all_from_action = relationships.get_all_links(db, ArtefactType.REQUIREMENT_ACTION, action_id)
        all_from_requirement = relationships.get_all_links(db, ArtefactType.REQUIREMENT, requirement_id)
        assert [link.id for link in all_from_action] == [link.id]
        assert [link.id for link in all_from_requirement] == [link.id]

        found = relationships.get_link_between(
            db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=action_id,
            target_type=ArtefactType.REQUIREMENT, target_id=requirement_id,
        )
        assert found is not None and found.id == link.id

        relationships.delete_link(db, link)
        db.commit()
        assert relationships.get_all_links(db, ArtefactType.REQUIREMENT, requirement_id) == []
    finally:
        db.close()


def test_untyped_link_partial_unique_index_rejects_duplicate(client, admin_token):
    """A second untyped link between the same exact `(source, target)` pair
    must be rejected — this is what `ux_artefact_links_untyped` (the
    partial unique index) exists to guarantee, since Postgres's NULL
    distinctness means the ordinary 5-column unique constraint alone would
    NOT catch this (see `ArtefactLink`'s own docstring). This is the direct
    DB-level pin for the duplicate-prevention guarantee `RequirementActionLink`
    used to provide via `UniqueConstraint(requirement_id, action_id)`."""
    from sqlalchemy.exc import IntegrityError

    org, token = create_org_admin_in(client, admin_token, "Artefact Link Untyped Dup Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"], component_id, category_id)
    action = _create_action(client, token, project["id"])
    action_id = UUID(action["id"])
    requirement_id = UUID(requirement["id"])
    creator_id = UUID(action["creator_id"])

    db = SessionLocal()
    try:
        relationships.create_link(
            db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=action_id,
            target_type=ArtefactType.REQUIREMENT, target_id=requirement_id,
            link_type_id=None, created_by=creator_id,
        )
        db.commit()

        try:
            # `create_link` flushes immediately (see its own docstring) —
            # Postgres enforces `ux_artefact_links_untyped` (a plain
            # `CREATE UNIQUE INDEX`, not a deferrable constraint) at
            # statement time, so the violation surfaces here, on the
            # flush inside `create_link` itself, not on a later
            # `db.commit()`.
            relationships.create_link(
                db, source_type=ArtefactType.REQUIREMENT_ACTION, source_id=action_id,
                target_type=ArtefactType.REQUIREMENT, target_id=requirement_id,
                link_type_id=None, created_by=creator_id,
            )
            raised = False
        except IntegrityError:
            db.rollback()
            raised = True
        assert raised, "A second identical untyped link should have violated ux_artefact_links_untyped."

        # Exactly one link survives.
        assert len(relationships.get_all_links(db, ArtefactType.REQUIREMENT, requirement_id)) == 1
    finally:
        db.close()


def test_link_action_endpoint_rejects_duplicate_via_pre_check(client, admin_token):
    """End-to-end confirmation that the REST layer's own pre-check (not
    just the raw DB constraint above) still rejects a duplicate action link
    with a clean 400 — pinning `routers.requirements.link_action`'s
    behaviour unchanged after its repoint onto the generic service."""
    org, token = create_org_admin_in(client, admin_token, "Artefact Link Action Endpoint Dup Org")
    project = create_project(client, token, org["id"])
    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = _create_requirement(client, token, project["id"], component_id, category_id)
    action = _create_action(client, token, project["id"])

    first = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions",
        json={"action_id": action["id"]}, headers=auth_headers(token),
    )
    assert first.status_code == 204, first.text

    second = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/actions",
        json={"action_id": action["id"]}, headers=auth_headers(token),
    )
    assert second.status_code == 400, second.text
